# Production backend dependency

The production client is deliberately usable only with the real Toontown
Browser backend. This is an authorization boundary, not an assertion that
browser-delivered bytes cannot be copied.

## New game connection

1. Cloudflare proxies the browser to the dedicated origin.
2. During normal bootstrap, the page generates a non-extractable ECDSA P-256
   proof-of-possession key.
3. The origin returns an encrypted challenge bound to the bootstrap session,
   current immutable runtime/R2 release, browser identity, address, and exact
   public origin.
4. The browser signs that challenge. The origin verifies it and returns a
   short-lived encrypted runtime authorization containing the public-key
   thumbprint and the same release/context bindings.
5. The origin mints a short-lived official-build attestation bound to the
   immutable release, bootstrap session, exact public origin, browser context,
   and the same proof-of-possession key. Its identifier is included in every
   protected request proof and every downstream capability.
6. The verified browser signs a same-origin
   `POST /api/gateway/lease`. The signature covers the exact method, path, body,
   timestamp, one-use nonce, runtime-authorization id, and official-build
   attestation id.
7. The origin generates the resume token; the browser does not choose it.
8. The origin encrypts an authenticated five-minute lease containing:
   - bootstrap-session digest;
   - runtime-authorization digest;
   - official-build attestation digest;
   - immutable release id;
   - resume token;
   - client-address digest;
   - User-Agent digest;
   - exact public origin;
   - issued/expiry times and a random nonce.
9. The browser passes the opaque lease, authority digest, official-build
   attestation digest, and resume token to `/astron`.
10. The loopback gateway independently validates every field before opening a
    loopback TCP connection to Astron.

Changing the token, browser, address, origin, session, ciphertext, tag, or
expiry rejects the socket. Copying an old client also fails when its embedded
runtime release no longer matches the server's current release. Server signing
keys exist only in
`/etc/toontown-browser/environment`.

Bootstrap, asset tickets, gateway leases, and gameplay capabilities all require
the same official-build attestation chain. A wrong origin, embedded client,
mismatched release, or missing/invalid attestation receives the consistent
`403 OFFICIAL_ORIGIN_REQUIRED` response. The official client displays a
non-dismissible full-canvas warning that points the player back to
`https://toontown.lui.ss/`, while the backend remains unavailable to that copy.
Telemetry records only bounded reason/build categories and never stores raw
attestation material, account credentials, or proof-of-possession keys.

The authority registration runs in parallel with runtime/cache preparation.
It is completed during boot and reused by Pick-a-Toon, so it does not add a
serial Toon-selection round trip.

## World-transition capability foundation

The verified runtime prefetches short-lived, encrypted capabilities for likely
initial zones while login/Pick-a-Toon is on screen. Each capability is bound to
the runtime authorization, current release, zone id, required phase metadata,
and a content epoch. The first deployment is observe/prefetch only; gameplay
enforcement is enabled only after transition p50/p95 telemetry proves there is
no regression.

Custom systems are migrated behind this authority one at a time. Rendering,
animation, audio, and input stay local; custom eligibility, state transitions,
and rewards move server-side.

## Mobile reconnect

Safari backgrounding may destroy the browser WebSocket while the gateway still
has the authorized Astron session. The existing five-minute retained-session
window remains:

- the initial connection must have passed a valid gateway lease;
- reconnect requires the same resume token, bootstrap session, browser
  identity, runtime authority, and origin;
- no new Astron TCP connection is opened;
- the lease may have expired because it authorized the retained session, not a
  second new session;
- the retained session and any buffered datagrams are destroyed when the grace
  period expires.

## Origin boundary

Caddy permits app and WebSocket traffic only when the immediate peer belongs to
Cloudflare's published IPv4/IPv6 networks. It forwards
`X-Toontown-Client-IP` from Cloudflare's `CF-Connecting-IP` to both loopback
processes. Direct requests to the server IP receive `403`.

When Cloudflare publishes an IP-range change, update `browser/deploy/Caddyfile`,
validate with `caddy validate`, reload, verify the Cloudflare path, and recheck
that a direct `--resolve` request still receives `403`.

## Required production checks

```bash
npm run test:bootstrap-session
npm run test:bootstrap-production
npm run test:runtime-authority
npm run test:gateway-lease
npm run test:gateway-bootstrap
npm run test:gateway
npm run test:gateway-limits
```

Production acceptance also checks:

- `/api/gateway/lease` is `401` without a bootstrap session;
- a verified connection without `lease` is `401`;
- a bootstrap cookie without a valid PoP request cannot mint asset tickets or a
  gateway lease;
- replayed request nonces are rejected;
- the real runtime URL contains only `resume`, `lease`, and `authority`;
- direct origin HTTPS is `403`;
- all internal ports `7197`-`7200` and `8180` remain loopback-only.

## Rollback

Per owner instruction, routine edits and deployments do not create extra
snapshots or copy the previous app tree, environment, R2 manifest, or Caddyfile.
Use Git history and retained immutable releases when recovery is needed.
Existing snapshots, including the protected classic/OG build, remain untouched.
The scheduled daily player-state backups are independent and remain enabled.

Restore matching client, manifest, and server versions together when needed.
A client containing the `lease` query must not be paired with an older Python
URL validator or gateway that cannot accept it.
