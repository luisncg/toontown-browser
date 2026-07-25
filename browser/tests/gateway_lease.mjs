import assert from "node:assert/strict";
import {
  createGatewayLease,
  createGatewayResumeToken,
  gatewayReconnectIdentity,
  openGatewayLease,
  verifyGatewayLease,
} from "../shared/gateway-lease.mjs";

const secret = Buffer.alloc(32, 17).toString("base64url");
const now = Date.UTC(2026, 6, 24, 12, 0, 0);
const context = {
  sessionKey: "a".repeat(32),
  resumeToken: createGatewayResumeToken(),
  clientAddress: "198.51.100.25",
  userAgent: "Toontown Browser lease test/1.0",
  origin: "https://toontown.lui.ss",
};
const lease = createGatewayLease({
  secret,
  ...context,
  now,
  ttlSeconds: 120,
});

assert.match(lease, /^v1(?:\.[A-Za-z0-9_-]+){3}$/);
assert.ok(!lease.includes(context.sessionKey));
assert.ok(!lease.includes(context.resumeToken));
assert.equal(verifyGatewayLease(lease, secret, context, now), true);
assert.equal(
  verifyGatewayLease(
    lease,
    secret,
    { ...context, resumeToken: createGatewayResumeToken() },
    now,
  ),
  false,
);
assert.equal(
  verifyGatewayLease(
    lease,
    secret,
    { ...context, clientAddress: "203.0.113.10" },
    now,
  ),
  false,
);
assert.equal(
  verifyGatewayLease(
    lease,
    secret,
    { ...context, userAgent: `${context.userAgent} altered` },
    now,
  ),
  false,
);
assert.equal(
  verifyGatewayLease(
    lease,
    secret,
    { ...context, origin: "https://copied.example" },
    now,
  ),
  false,
);
assert.equal(verifyGatewayLease(lease, secret, context, now + 136_000), false);

const tampered = `${lease.slice(0, -1)}${lease.endsWith("A") ? "B" : "A"}`;
assert.equal(verifyGatewayLease(tampered, secret, context, now), false);
assert.equal(openGatewayLease(lease, secret).r, context.resumeToken);

assert.deepEqual(
  gatewayReconnectIdentity(context),
  gatewayReconnectIdentity(context),
);
assert.notDeepEqual(
  gatewayReconnectIdentity(context),
  gatewayReconnectIdentity({
    ...context,
    userAgent: `${context.userAgent} altered`,
  }),
);

console.log(
  "Gateway lease unit test passed: opaque authenticated context binding and expiry",
);
