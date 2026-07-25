import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer as createTcpServer } from "node:net";
import { WebSocket } from "ws";
import {
  createGateway,
  DEFAULT_MAX_ATTACHED_CONNECTIONS_PER_IP,
  DEFAULT_MAX_RETAINED_SESSIONS_PER_IP,
  resolveGatewayClientAddress,
} from "../gateway/server.mjs";

const ORIGIN = "https://toontown.lui.ss";
const CLIENT_A = "198.51.100.10";
const CLIENT_B = "203.0.113.20";

assert.equal(DEFAULT_MAX_ATTACHED_CONNECTIONS_PER_IP, 6);
assert.equal(DEFAULT_MAX_RETAINED_SESSIONS_PER_IP, 18);

assert.equal(
  resolveGatewayClientAddress({
    socket: { remoteAddress: "127.0.0.1" },
    headers: {
      "x-toontown-client-ip": CLIENT_A,
    },
  }),
  CLIENT_A,
  "Caddy's sanitized address should win at the trusted loopback boundary",
);
assert.equal(
  resolveGatewayClientAddress({
    socket: { remoteAddress: "::ffff:127.0.0.1" },
    headers: {
      "x-toontown-client-ip": "not-an-address",
    },
  }),
  "::ffff:127.0.0.1",
  "An invalid trusted-proxy address should fall back to the direct peer",
);
assert.equal(
  resolveGatewayClientAddress({
    socket: { remoteAddress: "192.0.2.40" },
    headers: { "x-toontown-client-ip": CLIENT_A },
  }),
  "192.0.2.40",
  "An untrusted direct peer must not be able to spoof forwarding headers",
);

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
  allowedOrigins: [ORIGIN],
  heartbeatIntervalMs: 1_000,
  browserSuspendGraceMs: 5_000,
  browserResumeGraceMs: 5_000,
  astronHeartbeatIntervalMs: 1_000,
  maxAttachedConnectionsPerIp: 2,
  maxRetainedSessionsPerIp: 3,
});
await once(gateway, "listening");
const gatewayPort = gateway.address().port;

function resumeToken(id) {
  return `${id}`.padEnd(32, String(id % 10));
}

function connect(id, clientAddress) {
  return new WebSocket(
    `ws://127.0.0.1:${gatewayPort}/astron?resume=${resumeToken(id)}`,
    {
      origin: ORIGIN,
      headers: { "X-Toontown-Client-IP": clientAddress },
    },
  );
}

async function closeNormally(webSocket) {
  if (webSocket.readyState === WebSocket.CLOSED) return;
  const closed = once(webSocket, "close");
  webSocket.close(1000, "test complete");
  await closed;
}

async function expectRejected(webSocket, expectedStatus) {
  const [, response] = await once(webSocket, "unexpected-response");
  assert.equal(response.statusCode, expectedStatus);
  response.resume();
}

async function detach(webSocket) {
  webSocket.send(Buffer.from([1, 0]));
  webSocket.send("toontown:visibility:hidden");
  await new Promise((resolve) => setTimeout(resolve, 10));
  const closed = once(webSocket, "close");
  webSocket.terminate();
  await closed;
  await new Promise((resolve) => setTimeout(resolve, 10));
}

const clientAOne = connect(1, CLIENT_A);
const clientATwo = connect(2, CLIENT_A);
await Promise.all([once(clientAOne, "open"), once(clientATwo, "open")]);

const clientAOverAttachedLimit = connect(3, CLIENT_A);
await expectRejected(clientAOverAttachedLimit, 429);

const clientBOne = connect(4, CLIENT_B);
await once(clientBOne, "open");

await Promise.all([
  closeNormally(clientAOne),
  closeNormally(clientATwo),
  closeNormally(clientBOne),
]);

const detachedOne = connect(5, CLIENT_A);
await once(detachedOne, "open");
await detach(detachedOne);

const detachedTwo = connect(6, CLIENT_A);
await once(detachedTwo, "open");
await detach(detachedTwo);

const detachedThree = connect(7, CLIENT_A);
await once(detachedThree, "open");
await detach(detachedThree);

const clientAOverRetainedLimit = connect(8, CLIENT_A);
await expectRejected(clientAOverRetainedLimit, 429);

gateway.close();
await once(gateway, "close");
for (const socket of astronSockets) socket.destroy();
tcpServer.close();
await once(tcpServer, "close");

console.log(
  "Gateway proxy/limit test passed: trusted client IPs, per-IP attached slots, and separate retained-session cap",
);
