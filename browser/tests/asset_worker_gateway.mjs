import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createBootstrapSession } from "../shared/bootstrap-session.mjs";
import { sealAssetTicket } from "../shared/asset-ticket.mjs";
import worker from "../worker/src/index.mjs";

const origin = "https://toontown.lui.ss";
const bootstrapSecret = "worker-bootstrap-secret-with-at-least-thirty-two-characters";
const ticketSecret = Buffer.alloc(32, 11).toString("base64url");
const bootstrapCookie = createBootstrapSession(bootstrapSecret);
const session = createHash("sha256")
  .update(bootstrapCookie)
  .digest("hex")
  .slice(0, 32);
const release = "a".repeat(64);
const now = Math.floor(Date.now() / 1_000);
const calls = [];

function object(body = "private-r2-object") {
  const bytes = new TextEncoder().encode(body);
  return {
    body: bytes,
    size: bytes.byteLength,
    httpEtag: '"private-etag"',
    writeHttpMetadata(headers) {
      headers.set("Content-Type", "application/octet-stream");
      headers.set("Cache-Control", "private, max-age=31536000, immutable");
    },
  };
}

const environment = {
  PUBLIC_ORIGIN: origin,
  TURNSTILE_SESSION_SECRET: bootstrapSecret,
  ASSET_GATEWAY_TOKEN_SECRET: ticketSecret,
  ASSETS: {
    async get(key) {
      calls.push(["get", key]);
      return key.includes("missing") ? null : object();
    },
    async head(key) {
      calls.push(["head", key]);
      return key.includes("missing") ? null : object();
    },
  },
};

function request(token, { method = "GET", cookie = bootstrapCookie } = {}) {
  return new Request(`${origin}/assets/${token}`, {
    method,
    headers: cookie
      ? { Cookie: `__Host-toontown_bootstrap=${cookie}` }
      : {},
  });
}

async function ticket(overrides = {}) {
  return sealAssetTicket(
    {
      version: 1,
      expiresAt: now + 180,
      method: "GET",
      session,
      objectKey: `releases/${release}/open-toontown.data.gz`,
      name: "open-toontown.data",
      contentType: "application/octet-stream",
      contentEncoding: "gzip",
      ...overrides,
    },
    ticketSecret,
  );
}

const validToken = await ticket();
const response = await worker.fetch(request(validToken), environment);
assert.equal(response.status, 200);
assert.equal(response.headers.get("cache-control"), "private, no-store");
assert.equal(response.headers.get("content-encoding"), "gzip");
assert.equal(response.headers.get("content-disposition"), 'inline; filename="open-toontown.data"');
assert.equal(await response.text(), "private-r2-object");
assert.deepEqual(calls.at(-1), [
  "get",
  `releases/${release}/open-toontown.data.gz`,
]);

assert.equal((await worker.fetch(request(validToken, { cookie: "" }), environment)).status, 401);
assert.equal((await worker.fetch(request(await ticket({ session: "0".repeat(32) })), environment)).status, 403);
assert.equal((await worker.fetch(request(await ticket({ expiresAt: now - 1 })), environment)).status, 403);
assert.equal((await worker.fetch(request(await ticket({ objectKey: "private/secret" })), environment)).status, 403);

const tamperAt = Math.floor(validToken.length / 2);
const tampered = `${validToken.slice(0, tamperAt)}${
  validToken[tamperAt] === "A" ? "B" : "A"
}${validToken.slice(tamperAt + 1)}`;
assert.equal((await worker.fetch(request(tampered), environment)).status, 403);

const headToken = await ticket({
  method: "HEAD",
  objectKey: `releases/${release}/open-toontown.data`,
  contentEncoding: "identity",
});
const headResponse = await worker.fetch(
  request(headToken, { method: "HEAD" }),
  environment,
);
assert.equal(headResponse.status, 200);
assert.equal(headResponse.body, null);
assert.deepEqual(calls.at(-1), [
  "head",
  `releases/${release}/open-toontown.data`,
]);

const missingToken = await ticket({
  name: "phase-missing.data",
  objectKey: `releases/${release}/phase-missing.data`,
  contentEncoding: "identity",
});
assert.equal((await worker.fetch(request(missingToken), environment)).status, 404);
assert.equal(
  (await worker.fetch(
    new Request(`${origin}/assets/${validToken}`, {
      method: "POST",
      headers: { Cookie: `__Host-toontown_bootstrap=${bootstrapCookie}` },
    }),
    environment,
  )).status,
  405,
);

console.log("Private R2 Worker gateway tests passed");
