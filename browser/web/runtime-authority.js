(() => {
  "use strict";

  const PROTOCOL = 1;
  const AUTHORIZATION_REFRESH_MS = 60_000;
  const RELEASE = /^[a-f0-9]{64}$/;
  const AUTHORIZATION_ID = /^[a-f0-9]{32}$/;
  const OPAQUE_TOKEN = /^ra1(?:\.[A-Za-z0-9_-]+){3}$/;
  const CHALLENGE_TOKEN = /^rc1(?:\.[A-Za-z0-9_-]+){3}$/;
  const CHALLENGE = /^[A-Za-z0-9_-]{43}$/;
  const nativeFetch = window.fetch.bind(window);
  const encoder = new TextEncoder();
  const worldCapabilities = new Map();
  const diagnostics = {
    configuredAt: 0,
    keyReadyAt: 0,
    authorizedAt: 0,
    authorizationMs: 0,
    signedRequests: 0,
    refreshes: 0,
    worldRequests: 0,
    worldHits: 0,
    errors: 0,
  };

  let required = false;
  let release = "";
  let pendingChallenge;
  let authorization;
  let authorizationPromise;

  function isLocalDevelopmentPage() {
    return ["127.0.0.1", "localhost", "::1"].includes(
      window.location.hostname,
    ) && ["8080", "8180"].includes(window.location.port);
  }

  function base64url(bytes) {
    let binary = "";
    for (const byte of new Uint8Array(bytes)) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary)
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replaceAll("=", "");
  }

  function randomNonce() {
    return base64url(crypto.getRandomValues(new Uint8Array(16)));
  }

  async function sha256Hex(value) {
    const bytes = typeof value === "string" ? encoder.encode(value) : value;
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(
      new Uint8Array(digest),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
  }

  const keyPromise = crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign", "verify"],
  ).then((keyPair) => {
    diagnostics.keyReadyAt = performance.now();
    return keyPair;
  });

  function validChallenge(value) {
    return (
      value?.version === PROTOCOL &&
      RELEASE.test(value.release ?? "") &&
      CHALLENGE.test(value.challenge ?? "") &&
      CHALLENGE_TOKEN.test(value.challengeToken ?? "") &&
      Number.isFinite(value.expiresAt) &&
      value.expiresAt > Date.now()
    );
  }

  function configure(value = {}) {
    required = value.required === true;
    if (typeof value.release === "string" && RELEASE.test(value.release)) {
      if (release && release !== value.release) {
        authorization = undefined;
        authorizationPromise = undefined;
        worldCapabilities.clear();
      }
      release = value.release;
    }
    if (validChallenge(value.challenge)) {
      pendingChallenge = value.challenge;
    }
    diagnostics.configuredAt = performance.now();
  }

  function primeChallenge(value) {
    if (!validChallenge(value)) return false;
    if (release && value.release !== release) return false;
    release = value.release;
    pendingChallenge = value;
    return true;
  }

  async function fetchChallenge() {
    const response = await nativeFetch("/api/runtime/challenge", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!response.ok) {
      throw new Error(`Runtime challenge failed with ${response.status}`);
    }
    const value = await response.json();
    if (!validChallenge(value) || (release && value.release !== release)) {
      throw new Error("Runtime challenge response is invalid");
    }
    release = value.release;
    return value;
  }

  async function createAuthorization(challenge) {
    const startedAt = performance.now();
    const keyPair = await keyPromise;
    const publicKey = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
    const message = encoder.encode([
      "toontown-browser-runtime-registration-v1",
      challenge.challenge,
      challenge.release,
      window.location.origin,
    ].join("\n"));
    const signature = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      keyPair.privateKey,
      message,
    );
    const response = await nativeFetch("/api/runtime/authorize", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        challengeToken: challenge.challengeToken,
        publicKey: {
          kty: publicKey.kty,
          crv: publicKey.crv,
          x: publicKey.x,
          y: publicKey.y,
        },
        signature: base64url(signature),
      }),
    });
    if (!response.ok) {
      throw new Error(`Runtime authorization failed with ${response.status}`);
    }
    const value = await response.json();
    if (
      value?.version !== PROTOCOL ||
      value.release !== release ||
      !OPAQUE_TOKEN.test(value.authorization ?? "") ||
      !AUTHORIZATION_ID.test(value.authorizationId ?? "") ||
      !Number.isFinite(value.expiresAt) ||
      value.expiresAt <= Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      throw new Error("Runtime authorization response is invalid");
    }
    diagnostics.authorizedAt = performance.now();
    diagnostics.authorizationMs = diagnostics.authorizedAt - startedAt;
    return Object.freeze(value);
  }

  async function prepare({ force = false } = {}) {
    if (!required || isLocalDevelopmentPage()) {
      return Object.freeze({
        version: PROTOCOL,
        release,
        local: true,
        authorizationId: "0".repeat(32),
        expiresAt: Number.MAX_SAFE_INTEGER,
      });
    }
    if (
      !force &&
      authorization &&
      authorization.expiresAt > Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      return authorization;
    }
    if (
      authorization &&
      authorization.expiresAt <= Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      authorization = undefined;
      authorizationPromise = undefined;
    }
    if (authorizationPromise && !force) return authorizationPromise;
    if (force) {
      authorization = undefined;
      authorizationPromise = undefined;
      pendingChallenge = undefined;
      diagnostics.refreshes += 1;
    }
    authorizationPromise = (async () => {
      const challenge = pendingChallenge && pendingChallenge.expiresAt > Date.now()
        ? pendingChallenge
        : await fetchChallenge();
      pendingChallenge = undefined;
      authorization = await createAuthorization(challenge);
      return authorization;
    })().catch((error) => {
      diagnostics.errors += 1;
      authorizationPromise = undefined;
      throw error;
    });
    return authorizationPromise;
  }

  async function signedRequest(pathname, bodyObject, { retry = true } = {}) {
    if (!required || isLocalDevelopmentPage()) {
      return nativeFetch(pathname, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bodyObject),
      });
    }
    const current = await prepare();
    const body = JSON.stringify(bodyObject);
    const timestamp = String(Math.floor(Date.now() / 1_000));
    const nonce = randomNonce();
    const bodyHash = await sha256Hex(encoder.encode(body));
    const message = encoder.encode([
      "toontown-browser-request-proof-v1",
      "POST",
      pathname,
      timestamp,
      nonce,
      bodyHash,
      current.authorizationId,
    ].join("\n"));
    const keyPair = await keyPromise;
    const signature = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      keyPair.privateKey,
      message,
    );
    diagnostics.signedRequests += 1;
    const response = await nativeFetch(pathname, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Toontown-Authority": current.authorization,
        "X-Toontown-Authority-Id": current.authorizationId,
        "X-Toontown-Proof-Time": timestamp,
        "X-Toontown-Proof-Nonce": nonce,
        "X-Toontown-Proof": base64url(signature),
      },
      body,
    });
    if (retry && [401, 403, 409].includes(response.status)) {
      await prepare({ force: true });
      return signedRequest(pathname, bodyObject, { retry: false });
    }
    return response;
  }

  async function prefetchWorld(zoneIds) {
    const requested = [...new Set(
      (Array.isArray(zoneIds) ? zoneIds : [zoneIds])
        .map(Number)
        .filter((zoneId) => Number.isSafeInteger(zoneId) && zoneId >= 0),
    )].slice(0, 16);
    const now = Date.now();
    const missing = requested.filter((zoneId) => {
      const current = worldCapabilities.get(zoneId);
      if (current?.expiresAt > now + AUTHORIZATION_REFRESH_MS) {
        diagnostics.worldHits += 1;
        return false;
      }
      return true;
    });
    if (!missing.length) {
      return requested.map((zoneId) => worldCapabilities.get(zoneId));
    }
    diagnostics.worldRequests += 1;
    const response = await signedRequest(
      "/api/runtime/world-capabilities",
      { zoneIds: missing },
    );
    if (!response.ok) {
      throw new Error(`World capability request failed with ${response.status}`);
    }
    const value = await response.json();
    if (
      value?.version !== PROTOCOL ||
      value.release !== release ||
      !Array.isArray(value.capabilities) ||
      value.capabilities.length !== missing.length
    ) {
      throw new Error("World capability response is invalid");
    }
    for (const capability of value.capabilities) {
      if (
        !Number.isSafeInteger(capability?.zoneId) ||
        !missing.includes(capability.zoneId) ||
        typeof capability.capability !== "string" ||
        !/^rw1(?:\.[A-Za-z0-9_-]+){3}$/.test(capability.capability) ||
        !Number.isFinite(capability.expiresAt) ||
        capability.expiresAt <= Date.now() ||
        !Array.isArray(capability.requiredPhases)
      ) {
        throw new Error("World capability entry is invalid");
      }
      worldCapabilities.set(capability.zoneId, Object.freeze(capability));
    }
    return requested.map((zoneId) => worldCapabilities.get(zoneId));
  }

  function getWorldCapability(zoneId) {
    const value = worldCapabilities.get(Number(zoneId));
    return value?.expiresAt > Date.now() ? value : undefined;
  }

  window.ToontownRuntimeAuthority = Object.freeze({
    configure,
    primeChallenge,
    prepare,
    signedRequest,
    prefetchWorld,
    getWorldCapability,
    diagnostics: () => ({
      ...diagnostics,
      required,
      release,
      authorized: Boolean(
        authorization?.expiresAt > Date.now() + AUTHORIZATION_REFRESH_MS,
      ),
      authorizationExpiresAt: authorization?.expiresAt,
      worldCapabilities: worldCapabilities.size,
    }),
  });
})();
