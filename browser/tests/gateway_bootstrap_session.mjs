import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer as createTcpServer } from "node:net";
import { WebSocket } from "ws";
import { createGateway } from "../gateway/server.mjs";
import {
  bootstrapSessionDigest,
  BOOTSTRAP_COOKIE,
  createBootstrapSession,
} from "../shared/bootstrap-session.mjs";
import {
  createGatewayLease,
  createGatewayResumeToken,
} from "../shared/gateway-lease.mjs";

const secret = "gateway-smoke-secret-with-at-least-thirty-two-characters";
const leaseSecret = Buffer.alloc(32, 19).toString("base64url");
const origin = "https://toontown.lui.ss";
const userAgent = "Toontown Gateway Bootstrap Smoke/1.0";
const astronSockets = new Set();
const tcpServer = createTcpServer((socket) => {
  astronSockets.add(socket);
  socket.on("close", () => astronSockets.delete(socket));
});
tcpServer.listen(0, "127.0.0.1");
await once(tcpServer, "listening");

const gateway = createGateway({
  port: 0,
  targetPort: tcpServer.address().port,
  allowedOrigins: ["https://toontown.lui.ss"],
  requireBootstrapSession: true,
  bootstrapSessionSecret: secret,
  requireGatewayLease: true,
  gatewayLeaseSecret: leaseSecret,
});
await once(gateway, "listening");
const resumeToken = createGatewayResumeToken();
const authorityKey = "d".repeat(32);
const buildId = "e".repeat(64);
const officialBuildId = "f".repeat(32);
const url =
  `ws://127.0.0.1:${gateway.address().port}/astron?resume=${resumeToken}` +
  `&authority=${authorityKey}&build=${buildId}` +
  `&attestation=${officialBuildId}`;

const rejected = new WebSocket(url, {
  origin,
  headers: { "User-Agent": userAgent },
});
const [, response] = await once(rejected, "unexpected-response");
assert.equal(response.statusCode, 401);
response.resume();

const session = createBootstrapSession(secret);
const cookie = `${BOOTSTRAP_COOKIE}=${session}`;
const lease = createGatewayLease({
  secret: leaseSecret,
  sessionKey: bootstrapSessionDigest({ cookie }),
  resumeToken,
  clientAddress: "127.0.0.1",
  userAgent,
  origin,
  authorityKey,
  buildId,
  officialBuildId,
});

const missingLease = new WebSocket(url, {
  origin,
  headers: { Cookie: cookie, "User-Agent": userAgent },
});
const [, missingLeaseResponse] = await once(
  missingLease,
  "unexpected-response",
);
assert.equal(missingLeaseResponse.statusCode, 403);
missingLeaseResponse.resume();

const alteredResume = createGatewayResumeToken();
const mismatchedLease = new WebSocket(
  `${url.replace(resumeToken, alteredResume)}&lease=${lease}`,
  {
    origin,
    headers: { Cookie: cookie, "User-Agent": userAgent },
  },
);
const [, mismatchedLeaseResponse] = await once(
  mismatchedLease,
  "unexpected-response",
);
assert.equal(mismatchedLeaseResponse.statusCode, 403);
mismatchedLeaseResponse.resume();

const accepted = new WebSocket(`${url}&lease=${lease}`, {
  origin,
  headers: { Cookie: cookie, "User-Agent": userAgent },
});
await once(accepted, "open");
assert.equal(accepted.readyState, WebSocket.OPEN);

accepted.send(Buffer.from([1, 0]));
accepted.send("toontown:visibility:hidden");
await new Promise((resolve) => setTimeout(resolve, 10));
const acceptedClosed = once(accepted, "close");
accepted.terminate();
await acceptedClosed;
await new Promise((resolve) => setTimeout(resolve, 10));

const wrongBrowserResume = new WebSocket(
  `${url}&lease=${lease}&reconnect=1`,
  {
    origin,
    headers: {
      Cookie: cookie,
      "User-Agent": `${userAgent} altered`,
    },
  },
);
const [, wrongBrowserResponse] = await once(
  wrongBrowserResume,
  "unexpected-response",
);
assert.equal(wrongBrowserResponse.statusCode, 403);
wrongBrowserResponse.resume();

const resumed = new WebSocket(`${url}&lease=${lease}&reconnect=1`, {
  origin,
  headers: { Cookie: cookie, "User-Agent": userAgent },
});
await once(resumed, "open");
assert.equal(resumed.readyState, WebSocket.OPEN);
resumed.close(1000, "test complete");
await once(resumed, "close");

gateway.close();
for (const socket of astronSockets) socket.destroy();
tcpServer.close();
await Promise.all([once(gateway, "close"), once(tcpServer, "close")]);

console.log("Gateway bootstrap session smoke test passed");
