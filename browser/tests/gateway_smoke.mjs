import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer as createTcpServer } from "node:net";
import { WebSocket } from "ws";
import { createGateway } from "../gateway/server.mjs";

const receivedDatagrams = [];
let tcpConnectionCount = 0;
let latestAstronSocket;
const tcpServer = createTcpServer((socket) => {
  tcpConnectionCount += 1;
  latestAstronSocket = socket;
  let buffer = Buffer.alloc(0);
  socket.on("data", (chunk) => {
    buffer = buffer.length ? Buffer.concat([buffer, chunk]) : chunk;
    while (buffer.length >= 2) {
      const length = buffer.readUInt16LE(0);
      if (buffer.length < length + 2) return;
      const datagram = Buffer.from(buffer.subarray(2, length + 2));
      buffer = buffer.subarray(length + 2);
      receivedDatagrams.push(datagram);

      if (datagram.toString() === "browser-to-astron") {
        const response = Buffer.from("astron-to-browser");
        const framed = Buffer.alloc(response.length + 2);
        framed.writeUInt16LE(response.length, 0);
        response.copy(framed, 2);
        socket.write(framed);
      }
    }
  });
});

tcpServer.listen(0, "127.0.0.1");
await once(tcpServer, "listening");
const targetPort = tcpServer.address().port;

const gateway = createGateway({
  port: 0,
  targetPort,
  heartbeatIntervalMs: 25,
  browserSuspendGraceMs: 100,
  browserResumeGraceMs: 150,
  astronHeartbeatIntervalMs: 25,
});
await once(gateway, "listening");
const gatewayPort = gateway.address().port;

const webSocket = new WebSocket(
  `ws://127.0.0.1:${gatewayPort}/astron?resume=${"a".repeat(32)}`,
  {
  origin: "http://127.0.0.1:8080",
  },
);
await once(webSocket, "open");
webSocket.send(Buffer.from([1, 0]));
webSocket.send(Buffer.from("browser-to-astron"));
const [message, isBinary] = await once(webSocket, "message");

assert.equal(isBinary, true);
assert.equal(message.toString(), "astron-to-browser");

// A healthy browser may legitimately send no game datagrams while it remains
// on the login screen. Protocol-level ping/pong liveness must keep it open.
await new Promise((resolve) => setTimeout(resolve, 125));
assert.equal(webSocket.readyState, WebSocket.OPEN);
assert.ok(
  receivedDatagrams.filter(
    (datagram) => datagram.length === 2 && datagram.readUInt16LE(0) === 5,
  ).length >= 3,
  "Gateway did not keep Astron alive while browser game traffic was idle",
);

// iOS may suspend Safari's JavaScript and automatic pong handling while the
// native app is backgrounded. The gateway should retain that otherwise-open
// session beyond the old two-ping timeout, but still reap it after the bounded
// suspension grace.
const suspendedSocket = new WebSocket(
  `ws://127.0.0.1:${gatewayPort}/astron?resume=${"b".repeat(32)}`,
  {
    origin: "http://127.0.0.1:8080",
    autoPong: false,
  },
);
await once(suspendedSocket, "open");
suspendedSocket.send(Buffer.from([1, 0]));
await new Promise((resolve) => setTimeout(resolve, 75));
assert.equal(suspendedSocket.readyState, WebSocket.OPEN);
const [suspendedCloseCode, suspendedCloseReason] = await once(
  suspendedSocket,
  "close",
);
assert.equal(suspendedCloseCode, 1001);
assert.equal(
  suspendedCloseReason.toString(),
  "Connection heartbeat timed out",
);

// A browser socket that disappears while the page is hidden must not destroy
// the Astron TCP session. A reconnect with the same opaque token rebinds to
// that session and receives datagrams buffered during the short absence.
const resumeToken = "c".repeat(32);
const resumableSocket = new WebSocket(
  `ws://127.0.0.1:${gatewayPort}/astron?resume=${resumeToken}`,
  { origin: "http://127.0.0.1:8080" },
);
await once(resumableSocket, "open");
resumableSocket.send(Buffer.from([1, 0]));
resumableSocket.send("toontown:visibility:hidden");
await new Promise((resolve) => setTimeout(resolve, 10));
const connectionsBeforeResume = tcpConnectionCount;
resumableSocket.terminate();
await once(resumableSocket, "close");
await new Promise((resolve) => setTimeout(resolve, 10));

const buffered = Buffer.from("astron-during-background");
const bufferedFrame = Buffer.alloc(buffered.length + 2);
bufferedFrame.writeUInt16LE(buffered.length, 0);
buffered.copy(bufferedFrame, 2);
latestAstronSocket.write(bufferedFrame);

const resumedSocket = new WebSocket(
  `ws://127.0.0.1:${gatewayPort}/astron?resume=${resumeToken}&reconnect=1`,
  { origin: "http://127.0.0.1:8080" },
);
const resumedMessagePromise = once(resumedSocket, "message");
await once(resumedSocket, "open");
const [resumedMessage, resumedIsBinary] = await resumedMessagePromise;
assert.equal(resumedIsBinary, true);
assert.equal(resumedMessage.toString(), buffered.toString());
assert.equal(
  tcpConnectionCount,
  connectionsBeforeResume,
  "Resume unexpectedly opened a second Astron connection",
);

const resumedClosed = once(resumedSocket, "close");
resumedSocket.close(1000, "test complete");
await resumedClosed;
const webSocketClosed = once(webSocket, "close");
webSocket.close(1000, "test complete");
await webSocketClosed;
gateway.close();
tcpServer.close();
await Promise.all([once(gateway, "close"), once(tcpServer, "close")]);

console.log(
  "Gateway smoke test passed: binary WebSocket ↔ Astron TCP + idle heartbeat + hidden-page resume",
);
