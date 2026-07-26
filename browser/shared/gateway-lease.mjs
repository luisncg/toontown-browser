import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "node:crypto";

const LEASE_VERSION = "v1";
const LEASE_AAD = Buffer.from("toontown-browser-gateway-lease-v1", "utf8");
export const DEFAULT_GATEWAY_LEASE_TTL_SECONDS = 5 * 60;
export const MAX_GATEWAY_LEASE_TTL_SECONDS = 10 * 60;
const CLOCK_SKEW_SECONDS = 15;
const RESUME_TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;
const SESSION_PATTERN = /^[a-f0-9]{32}$/;

function decodeSecret(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value)) {
    throw new Error(
      "GATEWAY_LEASE_SECRET must be a base64url-encoded 32-byte value",
    );
  }
  const secret = Buffer.from(value, "base64url");
  if (secret.length !== 32) {
    throw new Error(
      "GATEWAY_LEASE_SECRET must be a base64url-encoded 32-byte value",
    );
  }
  return secret;
}

export function validateGatewayLeaseSecret(value) {
  decodeSecret(value);
  return true;
}

function digest(value) {
  return createHash("sha256")
    .update(String(value ?? "").slice(0, 1_024))
    .digest("hex");
}

function requireContext({
  sessionKey,
  resumeToken,
  clientAddress,
  userAgent,
  origin,
  authorityKey,
}) {
  if (typeof sessionKey !== "string" || !SESSION_PATTERN.test(sessionKey)) {
    throw new Error("A valid bootstrap session key is required");
  }
  if (
    typeof resumeToken !== "string" ||
    !RESUME_TOKEN_PATTERN.test(resumeToken)
  ) {
    throw new Error("A valid gateway resume token is required");
  }
  if (
    typeof clientAddress !== "string" ||
    clientAddress.length < 2 ||
    clientAddress.length > 64
  ) {
    throw new Error("A valid client address is required");
  }
  if (
    typeof userAgent !== "string" ||
    userAgent.length < 1 ||
    userAgent.length > 1_024
  ) {
    throw new Error("A valid browser identity is required");
  }
  let parsedOrigin;
  try {
    parsedOrigin = new URL(origin);
  } catch {
    throw new Error("A valid gateway origin is required");
  }
  if (parsedOrigin.origin !== origin || !["http:", "https:"].includes(
    parsedOrigin.protocol,
  )) {
    throw new Error("A valid gateway origin is required");
  }
  if (
    typeof authorityKey !== "string" ||
    !SESSION_PATTERN.test(authorityKey)
  ) {
    throw new Error("A valid runtime authority key is required");
  }
  return {
    s: sessionKey,
    r: resumeToken,
    ip: digest(clientAddress),
    ua: digest(userAgent),
    o: origin,
    a: authorityKey,
  };
}

export function createGatewayResumeToken() {
  return randomBytes(24).toString("base64url");
}

export function createGatewayLease({
  secret,
  sessionKey,
  resumeToken,
  clientAddress,
  userAgent,
  origin,
  authorityKey,
  now = Date.now(),
  ttlSeconds = DEFAULT_GATEWAY_LEASE_TTL_SECONDS,
}) {
  const key = decodeSecret(secret);
  if (
    !Number.isInteger(ttlSeconds) ||
    ttlSeconds < 30 ||
    ttlSeconds > MAX_GATEWAY_LEASE_TTL_SECONDS
  ) {
    throw new Error(
      `Gateway lease TTL must be 30-${MAX_GATEWAY_LEASE_TTL_SECONDS} seconds`,
    );
  }
  const issuedAt = Math.floor(now / 1_000);
  const payload = {
    v: 1,
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
    n: randomBytes(16).toString("base64url"),
    ...requireContext({
      sessionKey,
      resumeToken,
      clientAddress,
      userAgent,
      origin,
      authorityKey,
    }),
  };
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(LEASE_AAD);
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
  return [
    LEASE_VERSION,
    iv.toString("base64url"),
    ciphertext.toString("base64url"),
    tag.toString("base64url"),
  ].join(".");
}

function decodePart(value, expectedBytes, label) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error(`Gateway lease ${label} is invalid`);
  }
  const decoded = Buffer.from(value, "base64url");
  if (decoded.toString("base64url") !== value) {
    throw new Error(`Gateway lease ${label} is invalid`);
  }
  if (expectedBytes && decoded.length !== expectedBytes) {
    throw new Error(`Gateway lease ${label} is invalid`);
  }
  return decoded;
}

export function openGatewayLease(token, secret) {
  if (typeof token !== "string" || token.length < 80 || token.length > 2_048) {
    throw new Error("Gateway lease is invalid");
  }
  const parts = token.split(".");
  if (parts.length !== 4 || parts[0] !== LEASE_VERSION) {
    throw new Error("Gateway lease version is invalid");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    decodeSecret(secret),
    decodePart(parts[1], 12, "IV"),
  );
  decipher.setAAD(LEASE_AAD);
  decipher.setAuthTag(decodePart(parts[3], 16, "authentication tag"));
  const plaintext = Buffer.concat([
    decipher.update(decodePart(parts[2], 0, "ciphertext")),
    decipher.final(),
  ]);
  return JSON.parse(plaintext.toString("utf8"));
}

export function verifyGatewayLease(
  token,
  secret,
  context,
  now = Date.now(),
) {
  try {
    const expected = requireContext(context);
    const payload = openGatewayLease(token, secret);
    const current = Math.floor(now / 1_000);
    return (
      payload?.v === 1 &&
      Number.isSafeInteger(payload.iat) &&
      Number.isSafeInteger(payload.exp) &&
      payload.iat <= current + CLOCK_SKEW_SECONDS &&
      payload.exp >= current - CLOCK_SKEW_SECONDS &&
      payload.exp - payload.iat >= 30 &&
      payload.exp - payload.iat <= MAX_GATEWAY_LEASE_TTL_SECONDS &&
      typeof payload.n === "string" &&
      /^[A-Za-z0-9_-]{22}$/.test(payload.n) &&
      payload.s === expected.s &&
      payload.r === expected.r &&
      payload.ip === expected.ip &&
      payload.ua === expected.ua &&
      payload.o === expected.o &&
      payload.a === expected.a
    );
  } catch {
    return false;
  }
}

export function gatewayReconnectIdentity({
  sessionKey,
  userAgent,
  origin,
  authorityKey,
}) {
  if (typeof sessionKey !== "string" || !SESSION_PATTERN.test(sessionKey)) {
    return null;
  }
  if (
    typeof userAgent !== "string" ||
    userAgent.length < 1 ||
    userAgent.length > 1_024
  ) {
    return null;
  }
  try {
    if (new URL(origin).origin !== origin) return null;
  } catch {
    return null;
  }
  if (
    typeof authorityKey !== "string" ||
    !SESSION_PATTERN.test(authorityKey)
  ) {
    return null;
  }
  return Object.freeze({
    sessionKey,
    userAgentDigest: digest(userAgent),
    origin,
    authorityKey,
  });
}
