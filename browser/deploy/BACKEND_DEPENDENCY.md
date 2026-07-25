# Production backend dependency

The production client is deliberately usable only with the real Toontown
Browser backend. This is an authorization boundary, not an assertion that
browser-delivered bytes cannot be copied.

## New game connection

1. Cloudflare proxies the browser to the dedicated origin.
2. The verified browser sends a same-origin `POST /api/gateway/lease`.
3. The origin generates the resume token; the browser does not choose it.
4. The origin encrypts an authenticated five-minute lease containing:
   - bootstrap-session digest;
   - resume token;
   - client-address digest;
   - User-Agent digest;
   - exact public origin;
   - issued/expiry times and a random nonce.
5. The browser passes the opaque lease and resume token to `/astron`.
6. The loopback gateway independently validates every field before opening a
   loopback TCP connection to Astron.

Changing the token, browser, address, origin, session, ciphertext, tag, or
expiry rejects the socket. The signing key exists only in
`/etc/toontown-browser/environment`.

## Mobile reconnect

Safari backgrounding may destroy the browser WebSocket while the gateway still
has the authorized Astron session. The existing five-minute retained-session
window remains:

- the initial connection must have passed a valid gateway lease;
- reconnect requires the same resume token, bootstrap session, browser
  identity, and origin;
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
npm run test:gateway-lease
npm run test:gateway-bootstrap
npm run test:gateway
npm run test:gateway-limits
```

Production acceptance also checks:

- `/api/gateway/lease` is `401` without a bootstrap session;
- a verified connection without `lease` is `401`;
- the real runtime URL contains only `resume` and `lease`;
- direct origin HTTPS is `403`;
- all internal ports `7197`-`7200` and `8180` remain loopback-only.

## Rollback

Each deployment snapshots the previous app tree, environment, private R2
manifest, and Caddyfile under
`/srv/toontown-browser/deploy-backups/backend-lease-<timestamp>`.

Restore all four pieces together. A client containing the new `lease` query
must not be paired with the old Python URL validator or old gateway.
