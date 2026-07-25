import assert from "node:assert/strict";
import {
  BOOTSTRAP_COOKIE,
  BOOTSTRAP_MAX_AGE_SECONDS,
  bootstrapSessionDigest,
  bootstrapSessionValue,
  bootstrapCookieHeader,
  createBootstrapSession,
  verifyBootstrapSession,
} from "../shared/bootstrap-session.mjs";

const secret = "test-secret-that-is-at-least-thirty-two-characters";
const now = Date.UTC(2026, 6, 21, 12, 0, 0);
const value = createBootstrapSession(secret, now);
const headers = { cookie: `${BOOTSTRAP_COOKIE}=${value}` };

assert.equal(verifyBootstrapSession(headers, secret, now), true);
assert.equal(bootstrapSessionValue(headers), value);
assert.match(bootstrapSessionDigest(headers), /^[a-f0-9]{32}$/);
assert.equal(
  verifyBootstrapSession(headers, secret, now + BOOTSTRAP_MAX_AGE_SECONDS * 1_000),
  true,
);
assert.equal(
  verifyBootstrapSession(
    headers,
    secret,
    now + (BOOTSTRAP_MAX_AGE_SECONDS + 1) * 1_000,
  ),
  false,
);
assert.equal(verifyBootstrapSession(headers, `${secret}!`, now), false);
assert.equal(
  verifyBootstrapSession({ cookie: `${BOOTSTRAP_COOKIE}=${value}x` }, secret, now),
  false,
);
assert.match(bootstrapCookieHeader(value), /^__Host-toontown_bootstrap=/);
assert.match(bootstrapCookieHeader(value), /HttpOnly; Secure; SameSite=Strict$/);

console.log("Bootstrap session unit test passed");
