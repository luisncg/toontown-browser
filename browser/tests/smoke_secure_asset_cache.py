"""Verify heavy browser assets are cached only as AES-GCM ciphertext."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SECURE_CACHE_SCRIPT = (
    PROJECT_DIR / "browser" / "web" / "secure-asset-cache.js"
).read_bytes()
VERSION = "a" * 64
MARKER = b"TOONTOWN-PLAINTEXT-CACHE-MUST-NOT-CONTAIN-THIS-MARKER"
ASSET = MARKER + bytes(range(256)) * (5 * 1024 * 1024 // 256)
ASSET_SHA256 = hashlib.sha256(ASSET).hexdigest()


class FixtureHandler(BaseHTTPRequestHandler):
    asset_requests = 0

    def do_GET(self):
        if self.path == "/":
            body = (
                b"<!doctype html><script src='/secure-asset-cache.js'></script>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        elif self.path == "/secure-asset-cache.js":
            body = SECURE_CACHE_SCRIPT
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
        elif self.path in {
            f"/fixture.data?v={VERSION}",
            f"/direct.data?v={VERSION}",
            f"/cache-failure.data?v={VERSION}",
        }:
            type(self).asset_requests += 1
            body = ASSET
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "private, no-store")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
origin = f"http://127.0.0.1:{server.server_port}"


def fetch_digest(page):
    return page.evaluate(
        """async ({ version }) => {
            const response = await fetch(`/fixture.data?v=${version}`);
            const bytes = new Uint8Array(await response.arrayBuffer());
            const digest = await crypto.subtle.digest('SHA-256', bytes);
            return [...new Uint8Array(digest)]
                .map((byte) => byte.toString(16).padStart(2, '0')).join('');
        }""",
        {"version": VERSION},
    )


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(origin, wait_until="networkidle")

        page.evaluate(
            """async () => {
                for (const name of ['EM_PRELOAD_CACHE', 'TOONTOWN_PHASE_CACHE_V1']) {
                    await new Promise((resolve, reject) => {
                        const request = indexedDB.open(name, 1);
                        request.onupgradeneeded = () => {
                            request.result.createObjectStore('PACKAGES');
                        };
                        request.onsuccess = () => {
                            const db = request.result;
                            const tx = db.transaction('PACKAGES', 'readwrite');
                            tx.objectStore('PACKAGES').put(
                                new TextEncoder().encode('legacy plaintext'),
                                'legacy',
                            );
                            tx.oncomplete = () => {
                                db.close();
                                resolve();
                            };
                            tx.onerror = () => reject(tx.error);
                        };
                        request.onerror = () => reject(request.error);
                    });
                }
            }"""
        )

        assert fetch_digest(page) == ASSET_SHA256
        page.evaluate("ToontownSecureAssetCache.waitForIdle()")
        assert FixtureHandler.asset_requests == 1
        assert page.evaluate(
            "ToontownSecureAssetCache.missingAssetNames(["
            f"'/fixture.data?v={VERSION}'"
            "] )"
        ) == []

        storage = page.evaluate(
            """async ({ marker }) => {
                const db = await new Promise((resolve, reject) => {
                    const request = indexedDB.open('TOONTOWN_SECURE_ASSET_CACHE_V1', 1);
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                const read = (store, key) => new Promise((resolve, reject) => {
                    const tx = db.transaction(store, 'readonly');
                    const request = key === undefined
                        ? tx.objectStore(store).getAll()
                        : tx.objectStore(store).get(key);
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                const key = await read('KEYS', 'device-aes-gcm-v1');
                const assets = await read('ASSETS');
                const chunks = await read('CHUNKS');
                const markerBytes = new TextEncoder().encode(marker);
                const containsMarker = (source) => {
                    const bytes = new Uint8Array(source);
                    outer: for (let index = 0;
                        index <= bytes.length - markerBytes.length; index += 1) {
                        for (let offset = 0; offset < markerBytes.length; offset += 1) {
                            if (bytes[index + offset] !== markerBytes[offset]) continue outer;
                        }
                        return true;
                    }
                    return false;
                };
                return {
                    keyExtractable: key.extractable,
                    keyAlgorithm: key.algorithm.name,
                    assetCount: assets.length,
                    chunkCount: chunks.length,
                    metadataChunkCount: assets[0]?.chunkCount,
                    containsPlaintextMarker: chunks.some(
                        (chunk) => containsMarker(chunk.ciphertext),
                    ),
                    databases: (await indexedDB.databases()).map((item) => item.name),
                    diagnostics: ToontownSecureAssetCache.diagnostics(),
                };
            }""",
            {"marker": MARKER.decode()},
        )
        assert storage["keyExtractable"] is False
        assert storage["keyAlgorithm"] == "AES-GCM"
        assert storage["assetCount"] == 1
        assert storage["chunkCount"] == 2
        assert storage["metadataChunkCount"] == 2
        assert storage["containsPlaintextMarker"] is False
        assert "EM_PRELOAD_CACHE" not in storage["databases"]
        assert "TOONTOWN_PHASE_CACHE_V1" not in storage["databases"]
        assert storage["diagnostics"]["writes"] == 1

        assert fetch_digest(page) == ASSET_SHA256
        assert FixtureHandler.asset_requests == 1
        assert page.evaluate(
            "ToontownSecureAssetCache.diagnostics().hits"
        ) == 1

        direct_before = FixtureHandler.asset_requests
        direct = page.evaluate(
            """async ({ version }) => {
                const read = await ToontownSecureAssetCache.readPackageBuffer(
                    `/direct.data?v=${version}`,
                );
                const digest = await crypto.subtle.digest(
                    'SHA-256',
                    read.buffer,
                );
                const persisted =
                    await ToontownSecureAssetCache.persistPackageBuffer(read);
                return {
                    source: read.source,
                    bytes: read.buffer.byteLength,
                    digest: [...new Uint8Array(digest)]
                        .map((byte) => byte.toString(16).padStart(2, '0'))
                        .join(''),
                    persisted,
                };
            }""",
            {"version": VERSION},
        )
        assert direct["source"] == "network"
        assert direct["bytes"] == len(ASSET)
        assert direct["digest"] == ASSET_SHA256
        assert direct["persisted"] == {"stored": True, "skipped": False}
        assert FixtureHandler.asset_requests == direct_before + 1

        direct_warm = page.evaluate(
            """async ({ version }) => {
                const read = await ToontownSecureAssetCache.readPackageBuffer(
                    `/direct.data?v=${version}`,
                );
                const digest = await crypto.subtle.digest(
                    'SHA-256',
                    read.buffer,
                );
                return {
                    source: read.source,
                    bytes: read.buffer.byteLength,
                    digest: [...new Uint8Array(digest)]
                        .map((byte) => byte.toString(16).padStart(2, '0'))
                        .join(''),
                };
            }""",
            {"version": VERSION},
        )
        assert direct_warm == {
            "source": "encrypted_cache",
            "bytes": len(ASSET),
            "digest": ASSET_SHA256,
        }
        assert FixtureHandler.asset_requests == direct_before + 1

        cache_failure_before = FixtureHandler.asset_requests
        cache_failure = page.evaluate(
            """async ({ version }) => {
                const original =
                    ToontownSecureAssetCache.storeArrayBuffer.bind(
                        ToontownSecureAssetCache,
                    );
                ToontownSecureAssetCache.storeArrayBuffer = async () => {
                    throw new Error('injected cache write failure');
                };
                try {
                    const read =
                        await ToontownSecureAssetCache.readPackageBuffer(
                            `/cache-failure.data?v=${version}`,
                        );
                    const persisted =
                        await ToontownSecureAssetCache.persistPackageBuffer(
                            read,
                        );
                    const digest = await crypto.subtle.digest(
                        'SHA-256',
                        read.buffer,
                    );
                    return {
                        source: read.source,
                        digest: [...new Uint8Array(digest)]
                            .map((byte) => byte.toString(16).padStart(2, '0'))
                            .join(''),
                        persisted,
                    };
                } finally {
                    ToontownSecureAssetCache.storeArrayBuffer = original;
                }
            }""",
            {"version": VERSION},
        )
        assert cache_failure["source"] == "network"
        assert cache_failure["digest"] == ASSET_SHA256
        assert cache_failure["persisted"]["stored"] is False
        assert cache_failure["persisted"]["skipped"] is False
        assert "injected cache write failure" in cache_failure[
            "persisted"
        ]["error"]
        assert FixtureHandler.asset_requests == cache_failure_before + 1

        corrupt_retry_before = FixtureHandler.asset_requests
        page.evaluate(
            """async ({ version }) => {
                const db = await new Promise((resolve, reject) => {
                    const request = indexedDB.open('TOONTOWN_SECURE_ASSET_CACHE_V1', 1);
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                const cacheKey = `/fixture.data?v=${version}`;
                const metadata = await new Promise((resolve, reject) => {
                    const tx = db.transaction('ASSETS', 'readonly');
                    const request = tx.objectStore('ASSETS').get(cacheKey);
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('CHUNKS', 'readwrite');
                    const store = tx.objectStore('CHUNKS');
                    const key = [cacheKey, metadata.generation, 0];
                    const request = store.get(key);
                    request.onsuccess = () => {
                        const value = request.result;
                        const bytes = new Uint8Array(value.ciphertext);
                        bytes[0] ^= 0xff;
                        value.ciphertext = bytes.buffer;
                        store.put(value, key);
                    };
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                });
            }""",
            {"version": VERSION},
        )
        assert fetch_digest(page) == ASSET_SHA256
        page.evaluate("ToontownSecureAssetCache.waitForIdle()")
        assert FixtureHandler.asset_requests == corrupt_retry_before + 1

        page.close()
        context.close()

        fallback_context = browser.new_context()
        fallback_context.add_init_script(
            "Object.defineProperty(window, 'indexedDB', { value: undefined });"
        )
        fallback_page = fallback_context.new_page()
        fallback_page.goto(origin, wait_until="networkidle")
        before_fallback = FixtureHandler.asset_requests
        assert fetch_digest(fallback_page) == ASSET_SHA256
        assert fetch_digest(fallback_page) == ASSET_SHA256
        assert FixtureHandler.asset_requests == before_fallback + 2
        assert fallback_page.evaluate(
            "ToontownSecureAssetCache.diagnostics().disabled"
        ) is True
        fallback_context.close()
        browser.close()

    print(json.dumps({
        "secure_cache": "passed",
        "asset_bytes": len(ASSET),
        "network_requests": FixtureHandler.asset_requests,
    }))
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
