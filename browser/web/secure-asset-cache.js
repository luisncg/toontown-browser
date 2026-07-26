(() => {
  "use strict";

  const DATABASE_NAME = "TOONTOWN_SECURE_ASSET_CACHE_V1";
  const DATABASE_VERSION = 1;
  const KEY_STORE = "KEYS";
  const ASSET_STORE = "ASSETS";
  const CHUNK_STORE = "CHUNKS";
  const DEVICE_KEY_NAME = "device-aes-gcm-v1";
  const CACHE_SCHEMA = 1;
  const ENCRYPTION_CHUNK_BYTES = 4 * 1024 * 1024;
  const LEGACY_PLAINTEXT_DATABASES = [
    "EM_PRELOAD_CACHE",
    "TOONTOWN_PHASE_CACHE_V1",
  ];
  const VERSION = /^[a-f0-9]{16,64}$/;
  const HEAVY_ASSET = /\.(?:data|wasm)$/;
  const encoder = new TextEncoder();
  const nativeFetch = window.fetch.bind(window);

  class AssetTicketPool {
    constructor() {
      this.urls = new Map();
      this.stats = {
        batches: 0,
        requested: 0,
        issued: 0,
        uses: 0,
        errors: 0,
      };
    }

    async prepare(names) {
      const requested = [...new Set(names.map(String))];
      if (!requested.length) return { requested: 0, issued: 0 };
      const authority = window.ToontownRuntimeAuthority;
      const response = authority
        ? await authority.signedRequest(
          "/api/assets/tickets",
          { names: requested },
        )
        : await nativeFetch("/api/assets/tickets", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ names: requested }),
        });
      if (!response.ok) {
        this.stats.errors += 1;
        throw new Error(`Asset ticket batch failed with ${response.status}`);
      }
      const result = await response.json();
      if (
        ![1, 2].includes(result?.version) ||
        !Array.isArray(result.tickets) ||
        result.tickets.length > requested.length
      ) {
        this.stats.errors += 1;
        throw new Error("Asset ticket batch response is invalid");
      }

      const requestedNames = new Set(requested);
      const issuedNames = new Set();
      for (const ticket of result.tickets) {
        if (
          !ticket ||
          typeof ticket.name !== "string" ||
          !requestedNames.has(ticket.name) ||
          issuedNames.has(ticket.name) ||
          typeof ticket.url !== "string" ||
          (
            result.version === 2 &&
            (
              typeof ticket.authority !== "string" ||
              !/^[a-f0-9]{32}$/.test(ticket.authority)
            )
          )
        ) {
          this.stats.errors += 1;
          throw new Error("Asset ticket batch entry is invalid");
        }
        const url = new URL(ticket.url, window.location.href);
        if (
          url.origin !== window.location.origin ||
          !/^\/assets\/v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(
            url.pathname,
          ) ||
          url.search ||
          url.hash
        ) {
          this.stats.errors += 1;
          throw new Error("Asset ticket URL is invalid");
        }
        issuedNames.add(ticket.name);
        this.urls.set(ticket.name, Object.freeze({
          url: url.href,
          authority: ticket.authority,
        }));
      }
      this.stats.batches += 1;
      this.stats.requested += requested.length;
      this.stats.issued += issuedNames.size;
      return { requested: requested.length, issued: issuedNames.size };
    }

    requestFor(asset) {
      const ticket = this.urls.get(asset.assetName);
      if (!ticket) return asset.request;
      this.stats.uses += 1;
      const headers = new Headers(asset.request.headers);
      if (ticket.authority) {
        headers.set("X-Toontown-Asset-Authority", ticket.authority);
      }
      return new Request(ticket.url, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers,
        signal: asset.request.signal,
      });
    }

    diagnostics() {
      return { ...this.stats, available: this.urls.size };
    }
  }

  function requestResult(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("IndexedDB request failed"));
    });
  }

  function transactionDone(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = resolve;
      transaction.onabort = () => reject(
        transaction.error || new Error("IndexedDB transaction aborted"),
      );
      transaction.onerror = () => reject(
        transaction.error || new Error("IndexedDB transaction failed"),
      );
    });
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(KEY_STORE)) {
          database.createObjectStore(KEY_STORE);
        }
        if (!database.objectStoreNames.contains(ASSET_STORE)) {
          database.createObjectStore(ASSET_STORE);
        }
        if (!database.objectStoreNames.contains(CHUNK_STORE)) {
          database.createObjectStore(CHUNK_STORE);
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(
        request.error || new Error("Encrypted asset cache could not be opened"),
      );
      request.onblocked = () => reject(
        new Error("Encrypted asset cache upgrade was blocked"),
      );
    });
  }

  function deleteDatabaseQuietly(name) {
    try {
      const request = indexedDB.deleteDatabase(name);
      request.onerror = () => {};
      request.onblocked = () => {};
    } catch {
      // The secure cache remains usable even if an old browser profile keeps a
      // legacy database open in another tab.
    }
  }

  function normalizedAssetRequest(input, init) {
    let request;
    try {
      request = new Request(input, init);
    } catch {
      return undefined;
    }
    if (request.method !== "GET") return undefined;
    const url = new URL(request.url, window.location.href);
    if (url.origin !== window.location.origin) return undefined;
    if (!HEAVY_ASSET.test(url.pathname)) return undefined;
    const version = url.searchParams.get("v") || "";
    if (!VERSION.test(version)) return undefined;
    return {
      request,
      url,
      cacheKey: `${url.pathname}?v=${version}`,
      assetName: url.pathname.split("/").pop(),
    };
  }

  function safeResponseHeaders(source, assetName, byteLength) {
    const headers = new Headers(source || undefined);
    for (const name of [
      "cache-control",
      "content-disposition",
      "content-encoding",
      "content-length",
      "etag",
      "last-modified",
      "transfer-encoding",
    ]) {
      headers.delete(name);
    }
    headers.set(
      "content-type",
      assetName.endsWith(".wasm")
        ? "application/wasm"
        : "application/octet-stream",
    );
    headers.set("cache-control", "private, no-store");
    if (Number.isSafeInteger(byteLength) && byteLength >= 0) {
      headers.set("content-length", String(byteLength));
    }
    return headers;
  }

  function randomId(bytes = 12) {
    const value = crypto.getRandomValues(new Uint8Array(bytes));
    return Array.from(value, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  function chunkKey(cacheKey, generation, index) {
    return [cacheKey, generation, index];
  }

  function additionalData(cacheKey, generation, index, plainBytes) {
    return encoder.encode(
      `${CACHE_SCHEMA}\0${cacheKey}\0${generation}\0${index}\0${plainBytes}`,
    );
  }

  class SecureAssetCache {
    constructor() {
      this.databasePromise = undefined;
      this.keyPromise = undefined;
      this.cacheHits = new Map();
      this.pendingWrites = new Set();
      this.stats = {
        hits: 0,
        misses: 0,
        writes: 0,
        errors: 0,
        disabled: false,
        legacyCleanupRequested: false,
      };
    }

    database() {
      if (!this.databasePromise) {
        if (!window.indexedDB || !window.crypto?.subtle) {
          this.stats.disabled = true;
          this.databasePromise = Promise.reject(
            new Error("Encrypted browser storage is unavailable"),
          );
          this.databasePromise.catch(() => {});
        } else {
          this.databasePromise = openDatabase().then((database) => {
            for (const name of LEGACY_PLAINTEXT_DATABASES) {
              deleteDatabaseQuietly(name);
            }
            this.stats.legacyCleanupRequested = true;
            return database;
          }).catch((error) => {
            this.stats.disabled = true;
            throw error;
          });
        }
      }
      return this.databasePromise;
    }

    deviceKey() {
      if (!this.keyPromise) {
        this.keyPromise = this.database().then(async (database) => {
          const readTransaction = database.transaction(KEY_STORE, "readonly");
          const existing = await requestResult(
            readTransaction.objectStore(KEY_STORE).get(DEVICE_KEY_NAME),
          );
          await transactionDone(readTransaction);
          if (
            existing instanceof CryptoKey &&
            existing.type === "secret" &&
            existing.extractable === false &&
            existing.algorithm?.name === "AES-GCM"
          ) {
            return existing;
          }

          const generated = await crypto.subtle.generateKey(
            { name: "AES-GCM", length: 256 },
            false,
            ["encrypt", "decrypt"],
          );
          const writeTransaction = database.transaction(KEY_STORE, "readwrite");
          writeTransaction.objectStore(KEY_STORE).put(generated, DEVICE_KEY_NAME);
          await transactionDone(writeTransaction);
          return generated;
        });
      }
      return this.keyPromise;
    }

    async metadata(cacheKey) {
      const database = await this.database();
      const transaction = database.transaction(ASSET_STORE, "readonly");
      const value = await requestResult(
        transaction.objectStore(ASSET_STORE).get(cacheKey),
      );
      await transactionDone(transaction);
      if (
        !value ||
        value.schema !== CACHE_SCHEMA ||
        typeof value.generation !== "string" ||
        !Number.isSafeInteger(value.chunkCount) ||
        value.chunkCount < 1 ||
        !Number.isSafeInteger(value.byteLength) ||
        value.byteLength < 1
      ) {
        return undefined;
      }
      return value;
    }

    async encryptedChunk(cacheKey, metadata, index) {
      const database = await this.database();
      const transaction = database.transaction(CHUNK_STORE, "readonly");
      const value = await requestResult(
        transaction.objectStore(CHUNK_STORE).get(
          chunkKey(cacheKey, metadata.generation, index),
        ),
      );
      await transactionDone(transaction);
      if (
        !value ||
        !(value.iv instanceof ArrayBuffer) ||
        !(value.ciphertext instanceof ArrayBuffer) ||
        !Number.isSafeInteger(value.plainBytes) ||
        value.plainBytes < 1 ||
        value.plainBytes > ENCRYPTION_CHUNK_BYTES
      ) {
        throw new Error("Encrypted asset chunk is missing or invalid");
      }
      return value;
    }

    async decryptChunk(cacheKey, metadata, index) {
      const [key, value] = await Promise.all([
        this.deviceKey(),
        this.encryptedChunk(cacheKey, metadata, index),
      ]);
      const plaintext = await crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: new Uint8Array(value.iv),
          additionalData: additionalData(
            cacheKey,
            metadata.generation,
            index,
            value.plainBytes,
          ),
          tagLength: 128,
        },
        key,
        value.ciphertext,
      );
      if (plaintext.byteLength !== value.plainBytes) {
        throw new Error("Encrypted asset chunk length does not match metadata");
      }
      return new Uint8Array(plaintext);
    }

    async removeMetadata(cacheKey) {
      try {
        const database = await this.database();
        const transaction = database.transaction(ASSET_STORE, "readwrite");
        transaction.objectStore(ASSET_STORE).delete(cacheKey);
        await transactionDone(transaction);
      } catch {
        // A corrupt entry can safely remain unreachable until browser storage
        // eviction if IndexedDB itself is unavailable.
      }
    }

    async cachedResponse(cacheKey, assetName) {
      const metadata = await this.metadata(cacheKey);
      if (!metadata) return undefined;
      try {
        // Authenticate the first chunk before reporting a cache hit. Later
        // chunks are independently authenticated as the game consumes them.
        const first = await this.decryptChunk(cacheKey, metadata, 0);
        let index = 1;
        const stream = new ReadableStream({
          pull: async (controller) => {
            try {
              if (index === 1) {
                controller.enqueue(first);
              } else if (index <= metadata.chunkCount) {
                controller.enqueue(
                  await this.decryptChunk(cacheKey, metadata, index - 1),
                );
              }
              index += 1;
              if (index > metadata.chunkCount) controller.close();
            } catch (error) {
              controller.error(error);
            }
          },
        });
        return new Response(stream, {
          status: 200,
          headers: safeResponseHeaders(undefined, assetName, metadata.byteLength),
        });
      } catch {
        await this.removeMetadata(cacheKey);
        return undefined;
      }
    }

    async putEncryptedChunk(cacheKey, generation, index, plaintext) {
      const key = await this.deviceKey();
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = await crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv,
          additionalData: additionalData(
            cacheKey,
            generation,
            index,
            plaintext.byteLength,
          ),
          tagLength: 128,
        },
        key,
        plaintext,
      );
      const database = await this.database();
      const transaction = database.transaction(CHUNK_STORE, "readwrite");
      transaction.objectStore(CHUNK_STORE).put(
        {
          iv: iv.buffer,
          ciphertext,
          plainBytes: plaintext.byteLength,
        },
        chunkKey(cacheKey, generation, index),
      );
      await transactionDone(transaction);
    }

    async storeStream(cacheKey, assetName, stream) {
      const generation = randomId();
      const reader = stream.getReader();
      let pending = new Uint8Array(ENCRYPTION_CHUNK_BYTES);
      let pendingBytes = 0;
      let byteLength = 0;
      let chunkCount = 0;

      const flush = async () => {
        if (!pendingBytes) return;
        const plaintext = pending.slice(0, pendingBytes);
        await this.putEncryptedChunk(
          cacheKey,
          generation,
          chunkCount,
          plaintext,
        );
        chunkCount += 1;
        byteLength += plaintext.byteLength;
        pending = new Uint8Array(ENCRYPTION_CHUNK_BYTES);
        pendingBytes = 0;
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        let offset = 0;
        while (offset < value.byteLength) {
          const available = pending.byteLength - pendingBytes;
          const copyBytes = Math.min(available, value.byteLength - offset);
          pending.set(value.subarray(offset, offset + copyBytes), pendingBytes);
          pendingBytes += copyBytes;
          offset += copyBytes;
          if (pendingBytes === pending.byteLength) await flush();
        }
      }
      await flush();
      if (!chunkCount || !byteLength) return;

      const database = await this.database();
      const transaction = database.transaction(ASSET_STORE, "readwrite");
      transaction.objectStore(ASSET_STORE).put(
        {
          schema: CACHE_SCHEMA,
          generation,
          chunkCount,
          byteLength,
          contentType: assetName.endsWith(".wasm")
            ? "application/wasm"
            : "application/octet-stream",
          storedAt: Date.now(),
        },
        cacheKey,
      );
      await transactionDone(transaction);
      this.stats.writes += 1;
    }

    async storeArrayBuffer(cacheKey, assetName, buffer) {
      if (!(buffer instanceof ArrayBuffer) || !buffer.byteLength) {
        throw new Error("Encrypted asset cache received an empty package");
      }
      const generation = randomId();
      const bytes = new Uint8Array(buffer);
      let chunkCount = 0;
      for (
        let offset = 0;
        offset < bytes.byteLength;
        offset += ENCRYPTION_CHUNK_BYTES
      ) {
        const plaintext = bytes.subarray(
          offset,
          Math.min(offset + ENCRYPTION_CHUNK_BYTES, bytes.byteLength),
        );
        await this.putEncryptedChunk(
          cacheKey,
          generation,
          chunkCount,
          plaintext,
        );
        chunkCount += 1;
      }

      // Publish metadata only after every ciphertext chunk is durable. An
      // interrupted write therefore never becomes a readable cache entry.
      const database = await this.database();
      const transaction = database.transaction(ASSET_STORE, "readwrite");
      transaction.objectStore(ASSET_STORE).put(
        {
          schema: CACHE_SCHEMA,
          generation,
          chunkCount,
          byteLength: bytes.byteLength,
          contentType: assetName.endsWith(".wasm")
            ? "application/wasm"
            : "application/octet-stream",
          storedAt: Date.now(),
        },
        cacheKey,
      );
      await transactionDone(transaction);
      this.stats.writes += 1;
    }

    trackWrite(promise) {
      this.pendingWrites.add(promise);
      promise.catch(() => {
        this.stats.errors += 1;
      }).finally(() => {
        this.pendingWrites.delete(promise);
      });
    }

    async fetch(input, init) {
      const asset = normalizedAssetRequest(input, init);
      if (!asset || this.stats.disabled) return nativeFetch(input, init);

      try {
        const cached = await this.cachedResponse(asset.cacheKey, asset.assetName);
        if (cached) {
          this.cacheHits.set(asset.assetName, true);
          this.stats.hits += 1;
          return cached;
        }
      } catch {
        this.stats.errors += 1;
      }

      this.cacheHits.set(asset.assetName, false);
      this.stats.misses += 1;
      const response = await nativeFetch(assetTicketPool.requestFor(asset));
      if (!response.ok || !response.body) return response;

      try {
        await this.deviceKey();
        const [gameStream, cacheStream] = response.body.tee();
        this.trackWrite(
          this.storeStream(asset.cacheKey, asset.assetName, cacheStream),
        );
        return new Response(gameStream, {
          status: response.status,
          statusText: response.statusText,
          headers: safeResponseHeaders(response.headers, asset.assetName),
        });
      } catch {
        this.stats.errors += 1;
        return response;
      }
    }

    async readPackageBuffer(input, init) {
      const asset = normalizedAssetRequest(input, init);
      if (!asset) {
        throw new Error("Direct package handoff requires a versioned asset");
      }

      if (!this.stats.disabled) {
        try {
          const cached = await this.cachedResponse(
            asset.cacheKey,
            asset.assetName,
          );
          if (cached) {
            const buffer = await cached.arrayBuffer();
            this.cacheHits.set(asset.assetName, true);
            this.stats.hits += 1;
            return {
              assetName: asset.assetName,
              cacheKey: asset.cacheKey,
              buffer,
              source: "encrypted_cache",
              cacheable: false,
            };
          }
        } catch {
          this.stats.errors += 1;
          await this.removeMetadata(asset.cacheKey);
        }
      }

      this.cacheHits.set(asset.assetName, false);
      this.stats.misses += 1;
      const response = await nativeFetch(assetTicketPool.requestFor(asset));
      if (!response.ok) {
        throw new Error(
          `Package request failed with ${response.status}: ${asset.assetName}`,
        );
      }
      const buffer = await response.arrayBuffer();
      return {
        assetName: asset.assetName,
        cacheKey: asset.cacheKey,
        buffer,
        source: "network",
        cacheable: !this.stats.disabled,
      };
    }

    async persistPackageBuffer(packageRead) {
      if (
        packageRead?.source !== "network" ||
        packageRead.cacheable !== true
      ) {
        return { stored: false, skipped: true };
      }
      try {
        await this.storeArrayBuffer(
          packageRead.cacheKey,
          packageRead.assetName,
          packageRead.buffer,
        );
        return { stored: true, skipped: false };
      } catch (error) {
        this.stats.errors += 1;
        return {
          stored: false,
          skipped: false,
          error: String(error?.message || error).slice(0, 240),
        };
      }
    }

    wasCacheHit(assetName) {
      return this.cacheHits.get(String(assetName)) === true;
    }

    async waitForIdle() {
      while (this.pendingWrites.size) {
        await Promise.allSettled([...this.pendingWrites]);
      }
    }

    async missingAssetNames(inputs) {
      const assets = inputs.map((input) => normalizedAssetRequest(input));
      if (assets.some((asset) => !asset) || this.stats.disabled) {
        return assets.filter(Boolean).map((asset) => asset.assetName);
      }
      try {
        const metadata = await Promise.all(
          assets.map((asset) => this.metadata(asset.cacheKey)),
        );
        return assets.filter((_asset, index) => !metadata[index]).map(
          (asset) => asset.assetName,
        );
      } catch {
        return assets.map((asset) => asset.assetName);
      }
    }

    diagnostics() {
      return { ...this.stats, pendingWrites: this.pendingWrites.size };
    }
  }

  const assetTicketPool = new AssetTicketPool();
  const secureAssetCache = new SecureAssetCache();
  window.ToontownAssetTicketPool = assetTicketPool;
  window.ToontownSecureAssetCache = secureAssetCache;
  window.fetch = (input, init) => secureAssetCache.fetch(input, init);
})();
