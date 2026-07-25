import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { WebSocket } from "ws";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const PROJECT_DIR = resolve(TEST_DIR, "../..");
const IDLE_MS = Number(process.env.OPEN_TOONTOWN_ASTRON_IDLE_MS ?? 65_000);
const GATEWAY_URL = new URL(
  process.env.OPEN_TOONTOWN_GATEWAY_URL ??
    "ws://127.0.0.1:7200/astron",
);
GATEWAY_URL.searchParams.set("resume", "a".repeat(32));

assert.ok(IDLE_MS > 60_000, "Idle test must exceed Astron's timeout");

const hashResult = spawnSync(
  "python3.12",
  [
    "-c",
    "from panda3d.core import loadPrcFile; " +
      "from panda3d.direct import DCFile; " +
      "loadPrcFile('etc/Configrc.prc'); " +
      "dc=DCFile(); assert dc.readAll(); print(dc.getHash())",
  ],
  {
    cwd: PROJECT_DIR,
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: `${PROJECT_DIR}/.toolchain/build/panda3d-native-server:${PROJECT_DIR}`,
    },
  },
);
assert.equal(hashResult.status, 0, hashResult.stderr);
const dcHash = Number(hashResult.stdout.trim().split("\n").at(-1));
assert.ok(Number.isInteger(dcHash));

const config = readFileSync(resolve(PROJECT_DIR, "etc/Configrc.prc"), "utf8");
const versionMatch = config.match(/^server-version\s+(\S+)/m);
assert.ok(versionMatch, "Missing server-version in Configrc.prc");
const version = Buffer.from(versionMatch[1], "utf8");
const hello = Buffer.alloc(8 + version.length);
hello.writeUInt16LE(1, 0);
hello.writeUInt32LE(dcHash, 2);
hello.writeUInt16LE(version.length, 6);
version.copy(hello, 8);

const webSocket = new WebSocket(GATEWAY_URL, {
  origin: "http://127.0.0.1:8180",
});
await new Promise((resolveOpen, rejectOpen) => {
  webSocket.once("open", resolveOpen);
  webSocket.once("error", rejectOpen);
});

let helloAccepted = false;
let ejected = false;
let unexpectedClose = null;
webSocket.on("message", (message, isBinary) => {
  if (!isBinary || message.length < 2) return;
  const type = message.readUInt16LE(0);
  if (type === 2) helloAccepted = true;
  if (type === 4) ejected = true;
});
webSocket.once("close", (code, reason) => {
  unexpectedClose = { code, reason: reason.toString() };
});
webSocket.send(hello);

const helloDeadline = Date.now() + 5_000;
while (!helloAccepted && Date.now() < helloDeadline) {
  await new Promise((resolveWait) => setTimeout(resolveWait, 25));
}
assert.ok(helloAccepted, "Astron did not accept CLIENT_HELLO");

await new Promise((resolveWait) => setTimeout(resolveWait, IDLE_MS));
assert.equal(ejected, false, "Astron ejected the deliberately idle client");
assert.equal(unexpectedClose, null, JSON.stringify(unexpectedClose));
assert.equal(webSocket.readyState, WebSocket.OPEN);

const closed = new Promise((resolveClose) => webSocket.once("close", resolveClose));
webSocket.close();
await closed;

console.log(
  `Real Astron idle heartbeat passed: ${Math.round(IDLE_MS / 1000)}s without browser game traffic`,
);
