# Private R2 browser assets

Toontown Browser serves its bandwidth-heavy Emscripten artifacts from the
private Cloudflare R2 bucket `toontown-browser-assets`.

## Request flow

1. The dedicated server serves the public page and Turnstile bootstrap.
2. A verified browser receives the normal secure bootstrap cookie.
3. Runtime loader JavaScript and phase loader JavaScript remain same-origin on
   the dedicated server so Emscripten keeps the correct path resolution.
4. During the ordinary boot, the browser creates a non-extractable ECDSA key
   and exchanges a server-bound challenge for a short-lived runtime
   authorization tied to the current immutable release.
5. The browser signs one batched asset-ticket request. The signature covers the
   exact body, request path, timestamp, one-use nonce, and authorization id.
6. Requests for the main `.wasm`, initial `.data`, and phase `.data` files are
   checked against a private manifest stored outside the served web root.
   Direct heavy-asset paths are rejected even for a verified bootstrap cookie.
7. The dedicated server returns three-minute, AES-GCM-encrypted,
   session-and-authority-bound opaque ticket URLs. Tickets do not reveal asset
   names, release hashes, or R2 object keys.
8. A Cloudflare Worker verifies the signed bootstrap cookie, ticket session,
   and matching authority header, validates the exact object path, and streams
   the private R2 object through `toontown.lui.ss/assets/*`. The browser never
   receives R2 credentials, an R2 hostname, a presigned S3 URL, or the private
   manifest.
9. The browser encrypts completed heavy responses into 4 MiB AES-GCM chunks in
   IndexedDB. Its device key is non-extractable. Old plaintext Emscripten and
   phase caches are removed; if WebCrypto or IndexedDB is unavailable, the
   client uses the network rather than storing plaintext.

These layers prevent anonymous bulk fetching and make casual cache copying and
asset enumeration materially harder. They cannot make a playable browser
client impossible to capture: a verified player controls a browser that must
eventually decrypt and render the bytes.

Private asset access is independent from gameplay transport authorization.
After browser verification, the web origin separately issues an opaque
five-minute `GATEWAY_LEASE_SECRET`-protected connection lease. The WebSocket
gateway validates that lease before it opens an Astron TCP connection; copied
asset bytes alone therefore cannot enter the game.

## Release upload

The upload is immutable and additive. It does not delete older R2 releases.
Set the uploader-only `R2_*` environment variables, then run:

```bash
npm run upload:r2-assets
```

The script reads the runtime release hash from `dist-web/app.js`, hashes every
heavy representation, reuses exact matching objects, uploads identity and gzip
forms, and writes `.build-wasm/private/r2-assets.json` last with owner-only
permissions. The manifest is copied to a private server path during deploy and
is never served by the website or uploaded into the release prefix.

Required variables on the dedicated web origin:

- `ASSET_GATEWAY_ORIGIN=https://toontown.lui.ss`
- `ASSET_GATEWAY_TOKEN_SECRET` (32 random bytes encoded as base64url)
- `ASSET_GATEWAY_TTL_SECONDS=180`
- `R2_ASSET_RELEASE`
- `R2_ASSET_MANIFEST_PATH` (an absolute path outside `dist-web`)
- `GATEWAY_LEASE_SECRET` (a separate 32-byte base64url secret used only by the
  dedicated web origin and its loopback WebSocket gateway)
- `RUNTIME_AUTHORITY_SECRET` (a separate 32-byte base64url secret used to seal
  proof-of-possession challenges, runtime authorizations, and world
  capabilities)

Required secrets/bindings on the Cloudflare Worker:

- `ASSET_GATEWAY_TOKEN_SECRET` (the same value as the origin)
- `TURNSTILE_SESSION_SECRET` (the same value as the origin)
- `ASSETS` R2 binding to private bucket `toontown-browser-assets`
- `PUBLIC_ORIGIN=https://toontown.lui.ss`

The `toontown.lui.ss` DNS record must remain proxied through Cloudflare. A
Worker route can exist in the zone route table while silently receiving no
traffic when the hostname is DNS-only. After each route or DNS change, verify
that an `/assets/*` request has a Cloudflare edge IP and a `server: cloudflare`
response header.

The Worker returns uploaded `.gz` objects with `encodeBody: "manual"`. Those
objects are already compressed; leaving Workers' default automatic response
encoding enabled would gzip them a second time and make the WASM unreadable.

Uploader-only variables, stored separately from the running web service:

- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`

Never put these credentials in the browser bundle, repository, or logs.

## Rollback

The timestamped deployment backup deliberately retains the previous local
`.wasm` and `.data` files. To roll back, restore that application backup and
origin environment, restore the previous Worker version if its route changed,
and restart only `toontown-browser.service`.

Do not delete an R2 release as part of rollback. R2 cleanup requires a separate
inventory and explicit destructive approval.
