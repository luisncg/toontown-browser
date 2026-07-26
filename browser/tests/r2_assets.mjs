import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createR2AssetStoreFromEnvironment,
  R2AssetStore,
  validateR2AssetManifest,
  WorkerAssetGatewayStore,
} from "../shared/r2-assets.mjs";
import { openAssetTicket } from "../shared/asset-ticket.mjs";

const release = "a".repeat(64);
const checksum = "b".repeat(64);
const manifest = {
  version: 1,
  release,
  generatedAt: "2026-07-22T00:00:00.000Z",
  files: {
    "open-toontown.wasm": {
      identity: {
        objectKey: `releases/${release}/open-toontown.wasm`,
        size: 100,
        sha256: checksum,
      },
      gzip: {
        objectKey: `releases/${release}/open-toontown.wasm.gz`,
        size: 50,
        sha256: checksum,
      },
    },
    "phase-4-part-1.data": {
      identity: {
        objectKey: `releases/${release}/phase-4-part-1.data`,
        size: 200,
        sha256: checksum,
      },
    },
  },
};

assert.equal(validateR2AssetManifest(manifest).release, release);
assert.throws(
  () => validateR2AssetManifest({ ...manifest, release: "../private" }),
  /release/,
);
assert.throws(
  () => validateR2AssetManifest({
    ...manifest,
    files: { "../secret.data": manifest.files["phase-4-part-1.data"] },
  }),
  /unsupported filename/,
);

const commands = [];
let signed = 0;
const store = new R2AssetStore({
  bucket: "private-assets",
  client: {},
  manifest,
  ttlSeconds: 60,
  sign: async (command, options) => {
    signed += 1;
    commands.push({
      command: command.constructor.name,
      input: command.input,
      expiresIn: options.expiresIn,
    });
    return `https://private.example.invalid/signed/${signed}`;
  },
});

assert.equal(await store.redirect("/app.js", "GET", "gzip"), null);
assert.equal(await store.redirect("/../open-toontown.wasm", "GET", "gzip"), null);
assert.equal(
  await store.redirect("/open-toontown.wasm", "GET", "gzip, br", "1".repeat(32)),
  "https://private.example.invalid/signed/1",
);
assert.deepEqual(commands[0], {
  command: "GetObjectCommand",
  input: {
    Bucket: "private-assets",
    Key: `releases/${release}/open-toontown.wasm.gz`,
    ResponseContentDisposition:
      `inline; filename="open-toontown.wasm"; ` +
      `toontown-session="${"1".repeat(32)}"; ` +
      `toontown-authority="local"`,
  },
  expiresIn: 60,
});
assert.equal(
  await store.redirect("/open-toontown.wasm", "GET", "gzip", "1".repeat(32)),
  "https://private.example.invalid/signed/1",
);
assert.equal(signed, 1, "fresh signed URLs should be reused briefly");
assert.equal(
  await store.redirect("/open-toontown.wasm", "GET", "gzip", "2".repeat(32)),
  "https://private.example.invalid/signed/2",
);
assert.equal(
  commands[1].input.ResponseContentDisposition,
  `inline; filename="open-toontown.wasm"; ` +
  `toontown-session="${"2".repeat(32)}"; ` +
  `toontown-authority="local"`,
);
assert.equal(signed, 2, "separate sessions must receive separate signed URLs");
assert.equal(
  await store.redirect("/phase-4-part-1.data", "HEAD", "identity", "1".repeat(32)),
  "https://private.example.invalid/signed/3",
);
assert.equal(commands[2].command, "HeadObjectCommand");
assert.equal(
  commands[2].input.Key,
  `releases/${release}/phase-4-part-1.data`,
);

const ticketSecret = Buffer.alloc(32, 7).toString("base64url");
const gatewayStore = new WorkerAssetGatewayStore({
  gatewayOrigin: "https://toontown.lui.ss",
  manifest,
  secret: ticketSecret,
  ttlSeconds: 180,
});
assert.equal(gatewayStore.deliveryMode, "worker-gateway");
const gatewayUrl = await gatewayStore.redirect(
  "/open-toontown.wasm",
  "GET",
  "gzip, br",
  "3".repeat(32),
  "5".repeat(32),
);
const parsedGatewayUrl = new URL(gatewayUrl);
assert.equal(parsedGatewayUrl.origin, "https://toontown.lui.ss");
assert.match(parsedGatewayUrl.pathname, /^\/assets\/v1\./);
assert.ok(!gatewayUrl.includes("open-toontown"));
assert.ok(!gatewayUrl.includes(release));
const gatewayTicket = await openAssetTicket(
  parsedGatewayUrl.pathname.slice("/assets/".length),
  ticketSecret,
);
assert.deepEqual(
  {
    method: gatewayTicket.method,
    session: gatewayTicket.session,
    authority: gatewayTicket.authority,
    objectKey: gatewayTicket.objectKey,
    name: gatewayTicket.name,
    contentType: gatewayTicket.contentType,
    contentEncoding: gatewayTicket.contentEncoding,
  },
  {
    method: "GET",
    session: "3".repeat(32),
    authority: "5".repeat(32),
    objectKey: `releases/${release}/open-toontown.wasm.gz`,
    name: "open-toontown.wasm",
    contentType: "application/wasm",
    contentEncoding: "gzip",
  },
);
assert.equal(
  await gatewayStore.redirect(
    "/open-toontown.wasm",
    "GET",
    "gzip",
    "3".repeat(32),
    "5".repeat(32),
  ),
  gatewayUrl,
  "the same session may briefly reuse its opaque ticket",
);
assert.notEqual(
  await gatewayStore.redirect(
    "/open-toontown.wasm",
    "GET",
    "gzip",
    "4".repeat(32),
    "5".repeat(32),
  ),
  gatewayUrl,
  "separate sessions must receive separate opaque tickets",
);

const temporary = mkdtempSync(join(tmpdir(), "toontown-r2-manifest-"));
try {
  const webRoot = join(temporary, "web");
  const privateRoot = join(temporary, "private");
  mkdirSync(webRoot);
  mkdirSync(privateRoot);
  const environment = {
    R2_ENDPOINT: "https://example.r2.cloudflarestorage.com",
    R2_ACCESS_KEY_ID: "test-access-key",
    R2_SECRET_ACCESS_KEY: "test-secret-key",
    R2_BUCKET_NAME: "private-assets",
  };
  writeFileSync(join(webRoot, "r2-assets.json"), JSON.stringify(manifest));
  assert.throws(
    () => createR2AssetStoreFromEnvironment({
      environment,
      webRoot,
      requireExternalManifest: true,
    }),
    /outside the served web root/,
  );

  const privateManifest = join(privateRoot, "r2-assets.json");
  writeFileSync(privateManifest, JSON.stringify(manifest));
  assert.equal(
    createR2AssetStoreFromEnvironment({
      environment: {
        ...environment,
        R2_ASSET_MANIFEST_PATH: privateManifest,
      },
      webRoot,
      requireExternalManifest: true,
    }).release,
    release,
  );
  assert.throws(
    () => createR2AssetStoreFromEnvironment({
      environment: {
        ...environment,
        R2_ASSET_MANIFEST_PATH: privateManifest,
      },
      webRoot,
      requireExternalManifest: true,
      requireWorkerGateway: true,
    }),
    /requires the private Worker asset gateway/,
  );
  const configuredGateway = createR2AssetStoreFromEnvironment({
    environment: {
      ASSET_GATEWAY_ORIGIN: "https://toontown.lui.ss",
      ASSET_GATEWAY_TOKEN_SECRET: ticketSecret,
      ASSET_GATEWAY_TTL_SECONDS: "180",
      R2_ASSET_MANIFEST_PATH: privateManifest,
      R2_ASSET_RELEASE: release,
    },
    webRoot,
    requireExternalManifest: true,
    requireWorkerGateway: true,
  });
  assert.equal(configuredGateway.deliveryMode, "worker-gateway");
} finally {
  rmSync(temporary, { recursive: true, force: true });
}

console.log("R2 asset manifest and signing tests passed");
