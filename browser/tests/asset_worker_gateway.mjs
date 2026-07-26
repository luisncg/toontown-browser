import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createBootstrapSession } from "../shared/bootstrap-session.mjs";
import { sealAssetTicket } from "../shared/asset-ticket.mjs";
import worker, { AssetBudget } from "../worker/src/index.mjs";

const origin = "https://toontown.lui.ss";
const bootstrapSecret = "worker-bootstrap-secret-with-at-least-thirty-two-characters";
const ticketSecret = Buffer.alloc(32, 11).toString("base64url");
const bootstrapCookie = createBootstrapSession(bootstrapSecret);
const session = createHash("sha256")
  .update(bootstrapCookie)
  .digest("hex")
  .slice(0, 32);
const release = "a".repeat(64);
const authority = "c".repeat(32);
const now = Math.floor(Date.now() / 1_000);
const calls = [];
const objectBytes = new TextEncoder().encode("private-r2-object").byteLength;

function durableNamespace() {
  const objects = new Map();
  return {
    idFromName(name) {
      return name;
    },
    get(id) {
      if (!objects.has(id)) {
        const values = new Map();
        const budget = new AssetBudget({
          storage: {
            async get(key) {
              return values.get(key);
            },
            async put(key, value) {
              values.set(key, structuredClone(value));
            },
          },
        });
        objects.set(id, {
          fetch(input, init) {
            return budget.fetch(new Request(input, init));
          },
        });
      }
      return objects.get(id);
    },
  };
}

function isolatedBudget() {
  const values = new Map();
  return new AssetBudget({
    storage: {
      async get(key) {
        return values.get(key);
      },
      async put(key, value) {
        values.set(key, structuredClone(value));
      },
    },
  });
}

function budgetCall(budget, path, value) {
  return budget.fetch(new Request(`https://asset-budget.internal/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  }));
}

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
  ASSET_BUDGETS: durableNamespace(),
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

function request(
  token,
  {
    method = "GET",
    cookie = bootstrapCookie,
    authorityHeader = authority,
  } = {},
) {
  return new Request(`${origin}/assets/${token}`, {
    method,
    headers: {
      "CF-Connecting-IP": "203.0.113.12",
      ...(cookie
        ? { Cookie: `__Host-toontown_bootstrap=${cookie}` }
        : {}),
      ...(authorityHeader
        ? { "X-Toontown-Asset-Authority": authorityHeader }
        : {}),
    },
  });
}

async function ticket(overrides = {}) {
  return sealAssetTicket(
    {
      version: 2,
      expiresAt: now + 180,
      method: "GET",
      session,
      authority,
      objectKey: `releases/${release}/open-toontown.data.gz`,
      name: "open-toontown.data",
      contentType: "application/octet-stream",
      contentEncoding: "gzip",
      expectedBytes: objectBytes,
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
for (let attempt = 0; attempt < 2; attempt += 1) {
  const retry = await worker.fetch(request(validToken), environment);
  assert.equal(retry.status, 200);
  await retry.arrayBuffer();
}
assert.equal(
  (await worker.fetch(request(validToken), environment)).status,
  429,
  "the same opaque asset ticket must have a bounded replay count",
);

assert.equal((await worker.fetch(request(validToken, { cookie: "" }), environment)).status, 401);
assert.equal(
  (
    await worker.fetch(
      request(validToken, { authorityHeader: "d".repeat(32) }),
      environment,
    )
  ).status,
  403,
);
assert.equal((await worker.fetch(request(await ticket({ session: "0".repeat(32) })), environment)).status, 403);
assert.equal((await worker.fetch(request(await ticket({ expiresAt: now - 1 })), environment)).status, 403);
assert.equal((await worker.fetch(request(await ticket({ objectKey: "private/secret" })), environment)).status, 403);
assert.equal(
  (
    await worker.fetch(
      request(await ticket({ expectedBytes: objectBytes + 1 })),
      environment,
    )
  ).status,
  409,
  "the signed byte length must match the exact R2 representation",
);

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

const concurrencyBudget = isolatedBudget();
const reservations = [];
for (let index = 0; index < 12; index += 1) {
  const reserved = await budgetCall(concurrencyBudget, "reserve", {
    scope: "session",
    ticket: index.toString(16).padStart(64, "0"),
    bytes: 1,
  });
  assert.equal(reserved.status, 200);
  reservations.push((await reserved.json()).reservation);
}
assert.equal(
  (
    await budgetCall(concurrencyBudget, "reserve", {
      scope: "session",
      ticket: "f".repeat(64),
      bytes: 1,
    })
  ).status,
  429,
  "the durable session concurrency budget must support boot but fail closed",
);
assert.equal(
  (
    await budgetCall(concurrencyBudget, "release", {
      reservation: reservations[0],
    })
  ).status,
  200,
);
assert.equal(
  (
    await budgetCall(concurrencyBudget, "reserve", {
      scope: "session",
      ticket: "f".repeat(64),
      bytes: 1,
    })
  ).status,
  200,
  "releasing a response must free its concurrency slot",
);

const byteBudget = isolatedBudget();
assert.equal(
  (
    await budgetCall(byteBudget, "reserve", {
      scope: "session",
      ticket: "1".repeat(64),
      bytes: 700 * 1024 * 1024,
    })
  ).status,
  200,
);
assert.equal(
  (
    await budgetCall(byteBudget, "reserve", {
      scope: "session",
      ticket: "2".repeat(64),
      bytes: 100 * 1024 * 1024,
    })
  ).status,
  429,
  "the durable session byte budget must fail closed",
);

console.log("Private R2 Worker gateway tests passed");
