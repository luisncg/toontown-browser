import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import {
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";

const webRoot = resolve(process.argv[2] ?? "dist-web");
const manifestOutput = resolve(
  process.env.R2_ASSET_MANIFEST_OUTPUT ||
    join(webRoot, "..", ".build-wasm", "private", "r2-assets.json"),
);
const requiredEnvironment = [
  "R2_ENDPOINT",
  "R2_ACCESS_KEY_ID",
  "R2_SECRET_ACCESS_KEY",
  "R2_BUCKET_NAME",
];
for (const name of requiredEnvironment) {
  if (!process.env[name]) throw new Error(`${name} is required`);
}

let endpoint;
try {
  endpoint = new URL(process.env.R2_ENDPOINT);
} catch {
  throw new Error("R2_ENDPOINT must be a valid HTTPS URL");
}
if (endpoint.protocol !== "https:") {
  throw new Error("R2_ENDPOINT must use HTTPS");
}

const appSource = await readFile(join(webRoot, "app.js"), "utf8");
const versionMatch = appSource.match(
  /const runtimeAssetVersion = "([a-f0-9]{64})";/,
);
if (!versionMatch) {
  throw new Error("Could not find runtimeAssetVersion in dist-web/app.js");
}
const release = versionMatch[1];
const releasePrefix = `releases/${release}`;
const bucket = process.env.R2_BUCKET_NAME;
const client = new S3Client({
  region: "auto",
  endpoint: endpoint.href,
  forcePathStyle: true,
  requestChecksumCalculation: "WHEN_REQUIRED",
  credentials: {
    accessKeyId: process.env.R2_ACCESS_KEY_ID,
    secretAccessKey: process.env.R2_SECRET_ACCESS_KEY,
  },
});

async function sha256(path) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

async function uploadRepresentation(path, objectKey, contentType, contentEncoding) {
  const fileStat = await stat(path);
  const checksum = await sha256(path);
  let current;
  try {
    current = await client.send(new HeadObjectCommand({
      Bucket: bucket,
      Key: objectKey,
    }));
  } catch (error) {
    if (error?.$metadata?.httpStatusCode !== 404 && error?.name !== "NotFound") {
      throw error;
    }
  }
  if (
    current?.ContentLength === fileStat.size &&
    current?.Metadata?.sha256 === checksum
  ) {
    return { objectKey, size: fileStat.size, sha256: checksum, uploaded: false };
  }

  await client.send(new PutObjectCommand({
    Bucket: bucket,
    Key: objectKey,
    Body: createReadStream(path),
    ContentLength: fileStat.size,
    ContentType: contentType,
    ...(contentEncoding ? { ContentEncoding: contentEncoding } : {}),
    CacheControl: "private, max-age=31536000, immutable",
    Metadata: { sha256: checksum },
  }));
  return { objectKey, size: fileStat.size, sha256: checksum, uploaded: true };
}

const names = (await readdir(webRoot))
  .filter((name) =>
    /^(?:open-toontown\.(?:data|wasm)|phase-[a-z0-9.-]+\.data|audio-bank-[a-z0-9.-]+\.data)$/.test(name),
  )
  .sort();
if (names.length < 1) throw new Error("No browser data or WASM assets were found");

const manifest = {
  version: 1,
  release,
  generatedAt: new Date().toISOString(),
  files: {},
};
let uploaded = 0;
let reused = 0;
let completed = 0;

async function processAsset(name) {
  const path = join(webRoot, name);
  const contentType = name.endsWith(".wasm")
    ? "application/wasm"
    : "application/octet-stream";
  const identity = await uploadRepresentation(
    path,
    `${releasePrefix}/${basename(name)}`,
    contentType,
  );
  const result = { identity };
  try {
    const gzipPath = `${path}.gz`;
    await stat(gzipPath);
    result.gzip = await uploadRepresentation(
      gzipPath,
      `${releasePrefix}/${basename(name)}.gz`,
      contentType,
      "gzip",
    );
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  for (const representation of [result.identity, result.gzip].filter(Boolean)) {
    if (representation.uploaded) uploaded += 1;
    else reused += 1;
    delete representation.uploaded;
  }
  manifest.files[name] = result;
  completed += 1;
  if (completed % 10 === 0 || completed === names.length) {
    console.log(`Prepared ${completed} of ${names.length} browser assets`);
  }
}

const queue = [...names];
const workers = Array.from({ length: Math.min(3, queue.length) }, async () => {
  while (queue.length) await processAsset(queue.shift());
});
await Promise.all(workers);

manifest.files = Object.fromEntries(
  Object.entries(manifest.files).sort(([left], [right]) => left.localeCompare(right)),
);
const manifestBody = `${JSON.stringify(manifest, null, 2)}\n`;
await mkdir(dirname(manifestOutput), { recursive: true, mode: 0o700 });
await writeFile(manifestOutput, manifestBody, { mode: 0o600 });

console.log(
  `R2 release ${release.slice(0, 12)} prepared: ${uploaded} uploaded, ${reused} already current`,
);
console.log(`Private R2 manifest written outside the web root: ${manifestOutput}`);
