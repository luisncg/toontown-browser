import { readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import {
  GetObjectCommand,
  HeadObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import {
  decodeAssetTicketSecret,
  sealAssetTicket,
} from "./asset-ticket.mjs";

const REQUIRED_ENVIRONMENT = [
  "R2_ENDPOINT",
  "R2_ACCESS_KEY_ID",
  "R2_SECRET_ACCESS_KEY",
  "R2_BUCKET_NAME",
];
const DEFAULT_TTL_SECONDS = 3 * 60;
const MINIMUM_TTL_SECONDS = 60;
const MAXIMUM_TTL_SECONDS = 60 * 60;
const SIGNATURE_CACHE_SAFETY_SECONDS = 15;

function acceptsEncoding(header, encoding) {
  if (typeof header !== "string") return false;
  let wildcardQuality;
  for (const entry of header.split(",")) {
    const [name, ...parameters] = entry.trim().toLowerCase().split(";");
    let quality = 1;
    for (const parameter of parameters) {
      const match = parameter.trim().match(/^q=(0(?:\.\d+)?|1(?:\.0+)?)$/);
      if (match) quality = Number(match[1]);
    }
    if (name === encoding) return quality > 0;
    if (name === "*") wildcardQuality = quality;
  }
  return (wildcardQuality ?? 0) > 0;
}

function validateRepresentation(release, value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`R2 asset manifest has an invalid ${label} representation`);
  }
  if (
    typeof value.objectKey !== "string" ||
    !value.objectKey.startsWith(`releases/${release}/`) ||
    value.objectKey.includes("..") ||
    value.objectKey.includes("\\")
  ) {
    throw new Error(`R2 asset manifest has an invalid ${label} object key`);
  }
  if (!Number.isSafeInteger(value.size) || value.size < 1) {
    throw new Error(`R2 asset manifest has an invalid ${label} size`);
  }
  if (typeof value.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(value.sha256)) {
    throw new Error(`R2 asset manifest has an invalid ${label} checksum`);
  }
  return Object.freeze({
    objectKey: value.objectKey,
    size: value.size,
    sha256: value.sha256,
  });
}

export function validateR2AssetManifest(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("R2 asset manifest must be an object");
  }
  if (value.version !== 1) {
    throw new Error("R2 asset manifest version is unsupported");
  }
  if (typeof value.release !== "string" || !/^[a-f0-9]{64}$/.test(value.release)) {
    throw new Error("R2 asset manifest release must be a SHA-256 value");
  }
  if (!value.files || typeof value.files !== "object" || Array.isArray(value.files)) {
    throw new Error("R2 asset manifest files must be an object");
  }

  const files = {};
  for (const [name, entry] of Object.entries(value.files)) {
    if (!/^(?:open-toontown\.(?:data|wasm)|phase-[a-z0-9.-]+\.data|audio-bank-[a-z0-9.-]+\.data)$/.test(name)) {
      throw new Error(`R2 asset manifest contains an unsupported filename: ${name}`);
    }
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`R2 asset manifest contains an invalid entry: ${name}`);
    }
    const contentType = name.endsWith(".wasm")
      ? "application/wasm"
      : "application/octet-stream";
    files[name] = Object.freeze({
      contentType,
      identity: validateRepresentation(value.release, entry.identity, `${name} identity`),
      ...(entry.gzip
        ? { gzip: validateRepresentation(value.release, entry.gzip, `${name} gzip`) }
        : {}),
    });
  }
  if (Object.keys(files).length < 1) {
    throw new Error("R2 asset manifest cannot be empty");
  }

  return Object.freeze({
    version: 1,
    release: value.release,
    generatedAt:
      typeof value.generatedAt === "string" ? value.generatedAt : undefined,
    files: Object.freeze(files),
  });
}

export class R2AssetStore {
  constructor({
    bucket,
    client,
    manifest,
    sign = (command, options) => getSignedUrl(client, command, options),
    ttlSeconds = DEFAULT_TTL_SECONDS,
  }) {
    if (typeof bucket !== "string" || !bucket) {
      throw new Error("R2 bucket name is required");
    }
    if (!client) throw new Error("R2 S3 client is required");
    if (!Number.isInteger(ttlSeconds) ||
        ttlSeconds < MINIMUM_TTL_SECONDS ||
        ttlSeconds > MAXIMUM_TTL_SECONDS) {
      throw new Error(
        `R2 signed URL TTL must be between ${MINIMUM_TTL_SECONDS} and ${MAXIMUM_TTL_SECONDS} seconds`,
      );
    }
    this.bucket = bucket;
    this.client = client;
    this.manifest = validateR2AssetManifest(manifest);
    this.sign = sign;
    this.ttlSeconds = ttlSeconds;
    this.signedUrls = new Map();
  }

  get release() {
    return this.manifest.release;
  }

  get assetCount() {
    return Object.keys(this.manifest.files).length;
  }

  get deliveryMode() {
    return "direct-r2";
  }

  async redirect(
    pathname,
    method,
    acceptEncodingHeader,
    sessionKey,
    authorityKey = "",
    officialBuildId = "",
  ) {
    let decoded;
    try {
      decoded = decodeURIComponent(pathname);
    } catch {
      return null;
    }
    if (!/^\/[A-Za-z0-9._-]+$/.test(decoded)) return null;

    const name = decoded.slice(1);
    const entry = this.manifest.files[name];
    if (!entry) return null;
    if (typeof sessionKey !== "string" || !/^[a-f0-9]{16,64}$/.test(sessionKey)) {
      throw new Error("A private asset session key is required");
    }
    if (authorityKey && !/^[a-f0-9]{32}$/.test(authorityKey)) {
      throw new Error("A valid runtime asset authority is required");
    }
    if (officialBuildId && !/^[a-f0-9]{32}$/.test(officialBuildId)) {
      throw new Error("A valid official build attestation is required");
    }

    const useGzip = Boolean(
      entry.gzip && acceptsEncoding(acceptEncodingHeader, "gzip"),
    );
    const representation = useGzip ? entry.gzip : entry.identity;
    const cacheKey =
      `${sessionKey}:${authorityKey}:${officialBuildId}:${method}:` +
      representation.objectKey;
    const now = Date.now();
    const cached = this.signedUrls.get(cacheKey);
    if (cached && cached.expiresAt > now) return cached.url;

    const Command = method === "HEAD" ? HeadObjectCommand : GetObjectCommand;
    const commandInput = {
      Bucket: this.bucket,
      Key: representation.objectKey,
    };
    if (method === "GET") {
      // This response override is covered by the S3 signature, making the
      // bearer URL unique to the verified bootstrap session that requested it.
      // The object bytes are unchanged and Emscripten ignores this header.
      commandInput.ResponseContentDisposition =
        `inline; filename="${name}"; toontown-session="${sessionKey}"; ` +
        `toontown-authority="${authorityKey || "local"}"`;
    }
    const command = new Command(commandInput);
    const url = await this.sign(command, { expiresIn: this.ttlSeconds });
    const expiresAt = now +
      Math.max(1, this.ttlSeconds - SIGNATURE_CACHE_SAFETY_SECONDS) * 1_000;
    this.signedUrls.set(cacheKey, { url, expiresAt });
    return url;
  }
}

export class WorkerAssetGatewayStore {
  constructor({ gatewayOrigin, manifest, secret, ttlSeconds = DEFAULT_TTL_SECONDS }) {
    let parsedOrigin;
    try {
      parsedOrigin = new URL(gatewayOrigin);
    } catch {
      throw new Error("ASSET_GATEWAY_ORIGIN must be a valid HTTPS origin");
    }
    if (
      parsedOrigin.protocol !== "https:" ||
      parsedOrigin.origin !== gatewayOrigin ||
      parsedOrigin.pathname !== "/"
    ) {
      throw new Error("ASSET_GATEWAY_ORIGIN must be an exact HTTPS origin");
    }
    decodeAssetTicketSecret(secret);
    if (!Number.isInteger(ttlSeconds) ||
        ttlSeconds < MINIMUM_TTL_SECONDS ||
        ttlSeconds > MAXIMUM_TTL_SECONDS) {
      throw new Error(
        `Asset gateway TTL must be between ${MINIMUM_TTL_SECONDS} and ${MAXIMUM_TTL_SECONDS} seconds`,
      );
    }
    this.gatewayOrigin = parsedOrigin.origin;
    this.manifest = validateR2AssetManifest(manifest);
    this.secret = secret;
    this.ttlSeconds = ttlSeconds;
    this.tickets = new Map();
  }

  get release() {
    return this.manifest.release;
  }

  get assetCount() {
    return Object.keys(this.manifest.files).length;
  }

  get deliveryMode() {
    return "worker-gateway";
  }

  async redirect(
    pathname,
    method,
    acceptEncodingHeader,
    sessionKey,
    authorityKey,
    officialBuildId,
  ) {
    let decoded;
    try {
      decoded = decodeURIComponent(pathname);
    } catch {
      return null;
    }
    if (!/^\/[A-Za-z0-9._-]+$/.test(decoded)) return null;
    const name = decoded.slice(1);
    const entry = this.manifest.files[name];
    if (!entry) return null;
    if (typeof sessionKey !== "string" || !/^[a-f0-9]{32}$/.test(sessionKey)) {
      throw new Error("A private asset session key is required");
    }
    if (
      typeof authorityKey !== "string" ||
      !/^[a-f0-9]{32}$/.test(authorityKey)
    ) {
      throw new Error("A valid runtime asset authority is required");
    }
    if (
      typeof officialBuildId !== "string" ||
      !/^[a-f0-9]{32}$/.test(officialBuildId)
    ) {
      throw new Error("A valid official build attestation is required");
    }
    if (!["GET", "HEAD"].includes(method)) return null;

    const useGzip = Boolean(
      entry.gzip && acceptsEncoding(acceptEncodingHeader, "gzip"),
    );
    const representation = useGzip ? entry.gzip : entry.identity;
    const cacheKey =
      `${sessionKey}:${authorityKey}:${officialBuildId}:${method}:` +
      representation.objectKey;
    const now = Date.now();
    const cached = this.tickets.get(cacheKey);
    if (cached && cached.expiresAt > now) return cached.url;

    const expiresAtSeconds = Math.floor(now / 1_000) + this.ttlSeconds;
    const ticket = await sealAssetTicket(
      {
        version: 3,
        expiresAt: expiresAtSeconds,
        method,
        session: sessionKey,
        authority: authorityKey,
        build: this.release,
        officialBuild: officialBuildId,
        objectKey: representation.objectKey,
        name,
        contentType: entry.contentType,
        contentEncoding: useGzip ? "gzip" : "identity",
        expectedBytes: representation.size,
      },
      this.secret,
    );
    const url = new URL(`/assets/${ticket}`, this.gatewayOrigin).href;
    const expiresAt = now +
      Math.max(1, this.ttlSeconds - SIGNATURE_CACHE_SAFETY_SECONDS) * 1_000;
    this.tickets.set(cacheKey, { url, expiresAt });
    return url;
  }
}

export function createR2AssetStoreFromEnvironment({
  environment = process.env,
  webRoot,
  requireExternalManifest = false,
  requireWorkerGateway = false,
} = {}) {
  const gatewayConfigured = Boolean(
    environment.ASSET_GATEWAY_ORIGIN || environment.ASSET_GATEWAY_TOKEN_SECRET,
  );
  const configured = REQUIRED_ENVIRONMENT.filter((name) => environment[name]);
  if (!gatewayConfigured && configured.length === 0) {
    if (requireWorkerGateway) {
      throw new Error("Production requires the private Worker asset gateway");
    }
    return null;
  }
  if (gatewayConfigured) {
    const missing = ["ASSET_GATEWAY_ORIGIN", "ASSET_GATEWAY_TOKEN_SECRET"].filter(
      (name) => !environment[name],
    );
    if (missing.length) {
      throw new Error(`Incomplete asset gateway configuration; missing ${missing.join(", ")}`);
    }
  } else if (requireWorkerGateway) {
    throw new Error("Production requires the private Worker asset gateway");
  }
  if (configured.length !== REQUIRED_ENVIRONMENT.length) {
    if (gatewayConfigured && configured.length === 0) {
      // The Worker owns the R2 binding, so the origin does not need S3 keys.
    } else {
      const missing = REQUIRED_ENVIRONMENT.filter((name) => !environment[name]);
      throw new Error(`Incomplete R2 asset configuration; missing ${missing.join(", ")}`);
    }
  }

  const ttlSeconds = environment.ASSET_GATEWAY_TTL_SECONDS
    ? Number(environment.ASSET_GATEWAY_TTL_SECONDS)
    : environment.R2_SIGNED_URL_TTL_SECONDS
      ? Number(environment.R2_SIGNED_URL_TTL_SECONDS)
      : DEFAULT_TTL_SECONDS;
  const manifestPath = resolve(
    environment.R2_ASSET_MANIFEST_PATH || join(webRoot, "r2-assets.json"),
  );
  const resolvedWebRoot = resolve(webRoot);
  const manifestRelativeToWebRoot = relative(resolvedWebRoot, manifestPath);
  if (
    requireExternalManifest &&
    (manifestRelativeToWebRoot === "" ||
      (!manifestRelativeToWebRoot.startsWith("..") &&
        !manifestRelativeToWebRoot.startsWith("/")))
  ) {
    throw new Error("R2 asset manifest must be outside the served web root");
  }
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`Unable to read R2 asset manifest: ${error.message}`);
  }
  const validatedManifest = validateR2AssetManifest(manifest);
  if (
    environment.R2_ASSET_RELEASE &&
    environment.R2_ASSET_RELEASE !== validatedManifest.release
  ) {
    throw new Error("R2_ASSET_RELEASE does not match the asset manifest");
  }

  if (gatewayConfigured) {
    return new WorkerAssetGatewayStore({
      gatewayOrigin: environment.ASSET_GATEWAY_ORIGIN,
      manifest: validatedManifest,
      secret: environment.ASSET_GATEWAY_TOKEN_SECRET,
      ttlSeconds,
    });
  }

  let endpoint;
  try {
    endpoint = new URL(environment.R2_ENDPOINT);
  } catch {
    throw new Error("R2_ENDPOINT must be a valid HTTPS URL");
  }
  if (endpoint.protocol !== "https:") {
    throw new Error("R2_ENDPOINT must use HTTPS");
  }

  const client = new S3Client({
    region: "auto",
    endpoint: endpoint.href,
    forcePathStyle: true,
    requestChecksumCalculation: "WHEN_REQUIRED",
    credentials: {
      accessKeyId: environment.R2_ACCESS_KEY_ID,
      secretAccessKey: environment.R2_SECRET_ACCESS_KEY,
    },
  });
  return new R2AssetStore({
    bucket: environment.R2_BUCKET_NAME,
    client,
    manifest: validatedManifest,
    ttlSeconds,
  });
}
