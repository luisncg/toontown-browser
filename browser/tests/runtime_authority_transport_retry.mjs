import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

const source = await readFile(
  new URL("../web/runtime-authority.js", import.meta.url),
  "utf8",
);

const release = "a".repeat(64);
const officialBuildId = "b".repeat(32);
let attempts = 0;
let transitionMode = "drop-once";
const window = {
  fetch: async (pathname) => {
    if (pathname === "/api/runtime/authorize") {
      return new Response(JSON.stringify({
        version: 2,
        release,
        authorization: "ra2.a.b.c",
        authorizationId: "c".repeat(32),
        officialBuild: {
          version: 1,
          buildId: release,
          attestation: "ob1.a.b.c",
          attestationId: officialBuildId,
          expiresAt: Date.now() + 10 * 60_000,
        },
        expiresAt: Date.now() + 10 * 60_000,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    attempts += 1;
    if (transitionMode === "drop-once" && attempts === 1) {
      throw new TypeError("connection closed");
    }
    if (transitionMode === "deny") {
      return new Response("{}", { status: 400 });
    }
    return new Response("{}", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
  location: {
    origin: "https://toontown.lui.ss",
    hostname: "toontown.lui.ss",
    port: "",
  },
};
window.self = window;
window.top = window;

const context = vm.createContext({
  window,
  document: {
    documentElement: { classList: { add() {} } },
    querySelector: () => null,
  },
  crypto: webcrypto,
  TextEncoder,
  Response,
  performance,
  setTimeout,
  clearTimeout,
  btoa,
});
vm.runInContext(source, context, { filename: "runtime-authority.js" });
window.ToontownRuntimeAuthority.configure({
  required: true,
  officialOrigin: "https://toontown.lui.ss",
  buildId: release,
  release,
  attestationRequired: true,
  attestationProtocol: 1,
  challenge: {
    version: 2,
    release,
    challenge: "d".repeat(43),
    challengeToken: "rc2.a.b.c",
    expiresAt: Date.now() + 10 * 60_000,
  },
});

const response = await window.ToontownRuntimeAuthority.signedRequest(
  "/api/runtime/game-transitions",
  { action: "estate.enter" },
  { transportRetries: 2 },
);

assert.equal(response.status, 200);
assert.equal(attempts, 2);
assert.equal(
  window.ToontownRuntimeAuthority.diagnostics().transportRetries,
  1,
);

attempts = 0;
transitionMode = "deny";
const denied = await window.ToontownRuntimeAuthority.signedRequest(
  "/api/runtime/game-transitions",
  { action: "estate.enter" },
  { transportRetries: 2 },
);
assert.equal(denied.status, 400);
assert.equal(attempts, 1);

console.log("Runtime authority transport retry tests passed");
