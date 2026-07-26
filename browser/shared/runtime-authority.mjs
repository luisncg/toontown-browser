import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createPublicKey,
  randomBytes,
  verify as verifySignature,
} from "node:crypto";

export const RUNTIME_AUTHORITY_PROTOCOL = 1;
export const DEFAULT_RUNTIME_CHALLENGE_TTL_SECONDS = 2 * 60;
export const DEFAULT_RUNTIME_AUTHORIZATION_TTL_SECONDS = 30 * 60;
export const MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS = 60 * 60;
export const RUNTIME_PROOF_CLOCK_SKEW_SECONDS = 60;

const TOKEN_SPECS = Object.freeze({
  challenge: Object.freeze({
    prefix: "rc1",
    aad: Buffer.from("toontown-browser-runtime-challenge-v1", "utf8"),
  }),
  authorization: Object.freeze({
    prefix: "ra1",
    aad: Buffer.from("toontown-browser-runtime-authorization-v1", "utf8"),
  }),
  world: Object.freeze({
    prefix: "rw1",
    aad: Buffer.from("toontown-browser-world-capability-v1", "utf8"),
  }),
});
const SESSION_PATTERN = /^[a-f0-9]{32}$/;
const RELEASE_PATTERN = /^[a-f0-9]{64}$/;
const NONCE_PATTERN = /^[A-Za-z0-9_-]{22}$/;
const CHALLENGE_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const SIGNATURE_PATTERN = /^[A-Za-z0-9_-]{86}$/;
const PROOF_TIMESTAMP_PATTERN = /^\d{10}$/;
const WORLD_PHASE_PATTERN = /^(?:3\.5|5\.5|[4-9]|1[0-3]|news)$/;

function decodeSecret(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value)) {
    throw new Error(
      "RUNTIME_AUTHORITY_SECRET must be a base64url-encoded 32-byte value",
    );
  }
  const secret = Buffer.from(value, "base64url");
  if (secret.length !== 32 || secret.toString("base64url") !== value) {
    throw new Error(
      "RUNTIME_AUTHORITY_SECRET must be a base64url-encoded 32-byte value",
    );
  }
  return secret;
}

export function validateRuntimeAuthoritySecret(value) {
  decodeSecret(value);
  return true;
}

function digest(value) {
  return createHash("sha256")
    .update(String(value ?? "").slice(0, 8_192))
    .digest("hex");
}

function normalizeOrigin(origin) {
  let parsed;
  try {
    parsed = new URL(origin);
  } catch {
    throw new Error("A valid runtime authority origin is required");
  }
  if (
    parsed.origin !== origin ||
    !["http:", "https:"].includes(parsed.protocol)
  ) {
    throw new Error("A valid runtime authority origin is required");
  }
  return origin;
}

function requireContext({
  sessionKey,
  release,
  clientAddress,
  userAgent,
  origin,
}) {
  if (typeof sessionKey !== "string" || !SESSION_PATTERN.test(sessionKey)) {
    throw new Error("A valid bootstrap session key is required");
  }
  if (typeof release !== "string" || !RELEASE_PATTERN.test(release)) {
    throw new Error("A valid runtime release is required");
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
  return {
    s: sessionKey,
    r: release,
    ip: digest(clientAddress),
    ua: digest(userAgent),
    o: normalizeOrigin(origin),
  };
}

function sealToken(type, payload, secret) {
  const spec = TOKEN_SPECS[type];
  if (!spec) throw new Error("Runtime authority token type is invalid");
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", decodeSecret(secret), iv);
  cipher.setAAD(spec.aad);
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  return [
    spec.prefix,
    iv.toString("base64url"),
    ciphertext.toString("base64url"),
    cipher.getAuthTag().toString("base64url"),
  ].join(".");
}

function decodePart(value, expectedBytes, label) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error(`Runtime authority ${label} is invalid`);
  }
  const decoded = Buffer.from(value, "base64url");
  if (decoded.toString("base64url") !== value) {
    throw new Error(`Runtime authority ${label} is invalid`);
  }
  if (expectedBytes && decoded.length !== expectedBytes) {
    throw new Error(`Runtime authority ${label} is invalid`);
  }
  return decoded;
}

function openToken(type, token, secret) {
  const spec = TOKEN_SPECS[type];
  if (
    !spec ||
    typeof token !== "string" ||
    token.length < 80 ||
    token.length > 4_096
  ) {
    throw new Error("Runtime authority token is invalid");
  }
  const parts = token.split(".");
  if (parts.length !== 4 || parts[0] !== spec.prefix) {
    throw new Error("Runtime authority token version is invalid");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    decodeSecret(secret),
    decodePart(parts[1], 12, "IV"),
  );
  decipher.setAAD(spec.aad);
  decipher.setAuthTag(decodePart(parts[3], 16, "authentication tag"));
  const plaintext = Buffer.concat([
    decipher.update(decodePart(parts[2], 0, "ciphertext")),
    decipher.final(),
  ]);
  return JSON.parse(plaintext.toString("utf8"));
}

function validLifetime(payload, now, maximumSeconds) {
  const current = Math.floor(now / 1_000);
  return (
    Number.isSafeInteger(payload?.iat) &&
    Number.isSafeInteger(payload?.exp) &&
    payload.iat <= current + RUNTIME_PROOF_CLOCK_SKEW_SECONDS &&
    payload.exp >= current - RUNTIME_PROOF_CLOCK_SKEW_SECONDS &&
    payload.exp > payload.iat &&
    payload.exp - payload.iat <= maximumSeconds
  );
}

function contextMatches(payload, context) {
  const expected = requireContext(context);
  return (
    payload?.s === expected.s &&
    payload?.r === expected.r &&
    payload?.ip === expected.ip &&
    payload?.ua === expected.ua &&
    payload?.o === expected.o
  );
}

export function createRuntimeChallenge({
  secret,
  now = Date.now(),
  ttlSeconds = DEFAULT_RUNTIME_CHALLENGE_TTL_SECONDS,
  ...context
}) {
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 30 || ttlSeconds > 5 * 60) {
    throw new Error("Runtime challenge TTL must be 30-300 seconds");
  }
  const issuedAt = Math.floor(now / 1_000);
  const challenge = randomBytes(32).toString("base64url");
  const payload = {
    v: RUNTIME_AUTHORITY_PROTOCOL,
    t: "challenge",
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
    n: randomBytes(16).toString("base64url"),
    c: challenge,
    ...requireContext(context),
  };
  return Object.freeze({
    version: RUNTIME_AUTHORITY_PROTOCOL,
    release: context.release,
    challenge,
    challengeToken: sealToken("challenge", payload, secret),
    expiresAt: payload.exp * 1_000,
  });
}

export function runtimeRegistrationMessage({
  challenge,
  release,
  origin,
}) {
  if (!CHALLENGE_PATTERN.test(challenge ?? "")) {
    throw new Error("Runtime challenge is invalid");
  }
  if (!RELEASE_PATTERN.test(release ?? "")) {
    throw new Error("Runtime release is invalid");
  }
  return Buffer.from(
    [
      "toontown-browser-runtime-registration-v1",
      challenge,
      release,
      normalizeOrigin(origin),
    ].join("\n"),
    "utf8",
  );
}

export function normalizeRuntimePublicKey(value) {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    value.kty !== "EC" ||
    value.crv !== "P-256" ||
    typeof value.x !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(value.x) ||
    typeof value.y !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(value.y)
  ) {
    throw new Error("Runtime authority public key is invalid");
  }
  for (const coordinate of [value.x, value.y]) {
    const decoded = Buffer.from(coordinate, "base64url");
    if (decoded.length !== 32 || decoded.toString("base64url") !== coordinate) {
      throw new Error("Runtime authority public key is invalid");
    }
  }
  return Object.freeze({
    kty: "EC",
    crv: "P-256",
    x: value.x,
    y: value.y,
  });
}

export function runtimePublicKeyThumbprint(publicKey) {
  const key = normalizeRuntimePublicKey(publicKey);
  return digest(JSON.stringify({
    crv: key.crv,
    kty: key.kty,
    x: key.x,
    y: key.y,
  }));
}

export function verifyRuntimeRegistration({
  challengeToken,
  publicKey,
  signature,
  secret,
  context,
  now = Date.now(),
}) {
  try {
    if (
      typeof signature !== "string" ||
      !SIGNATURE_PATTERN.test(signature)
    ) {
      return null;
    }
    const payload = openToken("challenge", challengeToken, secret);
    if (
      payload?.v !== RUNTIME_AUTHORITY_PROTOCOL ||
      payload?.t !== "challenge" ||
      !validLifetime(payload, now, 5 * 60) ||
      !NONCE_PATTERN.test(payload.n ?? "") ||
      !CHALLENGE_PATTERN.test(payload.c ?? "") ||
      !contextMatches(payload, context)
    ) {
      return null;
    }
    const key = normalizeRuntimePublicKey(publicKey);
    const valid = verifySignature(
      "sha256",
      runtimeRegistrationMessage({
        challenge: payload.c,
        release: payload.r,
        origin: payload.o,
      }),
      {
        key: createPublicKey({ key, format: "jwk" }),
        dsaEncoding: "ieee-p1363",
      },
      Buffer.from(signature, "base64url"),
    );
    if (!valid) return null;
    return Object.freeze({
      challengeId: digest(challengeToken).slice(0, 32),
      publicKey: key,
      thumbprint: runtimePublicKeyThumbprint(key),
      expiresAt: payload.exp * 1_000,
    });
  } catch {
    return null;
  }
}

export function createRuntimeAuthorization({
  secret,
  publicKey,
  now = Date.now(),
  ttlSeconds = DEFAULT_RUNTIME_AUTHORIZATION_TTL_SECONDS,
  ...context
}) {
  if (
    !Number.isInteger(ttlSeconds) ||
    ttlSeconds < 5 * 60 ||
    ttlSeconds > MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS
  ) {
    throw new Error(
      `Runtime authorization TTL must be 300-${MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS} seconds`,
    );
  }
  const key = normalizeRuntimePublicKey(publicKey);
  const issuedAt = Math.floor(now / 1_000);
  const payload = {
    v: RUNTIME_AUTHORITY_PROTOCOL,
    t: "authorization",
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
    n: randomBytes(16).toString("base64url"),
    p: runtimePublicKeyThumbprint(key),
    k: key,
    ...requireContext(context),
  };
  const authorization = sealToken("authorization", payload, secret);
  return Object.freeze({
    version: RUNTIME_AUTHORITY_PROTOCOL,
    release: context.release,
    authorization,
    authorizationId: runtimeAuthorizationId(authorization),
    expiresAt: payload.exp * 1_000,
  });
}

export function runtimeAuthorizationId(authorization) {
  return digest(authorization).slice(0, 32);
}

export function runtimeRequestMessage({
  authorizationId,
  method,
  pathname,
  timestamp,
  nonce,
  body,
}) {
  if (!SESSION_PATTERN.test(authorizationId ?? "")) {
    throw new Error("Runtime authorization id is invalid");
  }
  if (!["GET", "POST"].includes(method)) {
    throw new Error("Runtime proof method is invalid");
  }
  if (
    typeof pathname !== "string" ||
    !/^\/api\/[a-z0-9/_-]+$/.test(pathname)
  ) {
    throw new Error("Runtime proof path is invalid");
  }
  if (!PROOF_TIMESTAMP_PATTERN.test(String(timestamp ?? ""))) {
    throw new Error("Runtime proof timestamp is invalid");
  }
  if (!NONCE_PATTERN.test(nonce ?? "")) {
    throw new Error("Runtime proof nonce is invalid");
  }
  const bytes = Buffer.isBuffer(body) ? body : Buffer.from(body ?? "");
  return Buffer.from([
    "toontown-browser-request-proof-v1",
    method,
    pathname,
    String(timestamp),
    nonce,
    digest(bytes),
    authorizationId,
  ].join("\n"), "utf8");
}

export function verifyRuntimeRequestProof({
  secret,
  authorization,
  signature,
  timestamp,
  nonce,
  method,
  pathname,
  body,
  context,
  now = Date.now(),
}) {
  try {
    if (
      typeof signature !== "string" ||
      !SIGNATURE_PATTERN.test(signature) ||
      !PROOF_TIMESTAMP_PATTERN.test(String(timestamp ?? "")) ||
      !NONCE_PATTERN.test(nonce ?? "")
    ) {
      return null;
    }
    const current = Math.floor(now / 1_000);
    const requestedAt = Number(timestamp);
    if (
      !Number.isSafeInteger(requestedAt) ||
      Math.abs(current - requestedAt) > RUNTIME_PROOF_CLOCK_SKEW_SECONDS
    ) {
      return null;
    }
    const payload = openToken("authorization", authorization, secret);
    if (
      payload?.v !== RUNTIME_AUTHORITY_PROTOCOL ||
      payload?.t !== "authorization" ||
      !validLifetime(
        payload,
        now,
        MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS,
      ) ||
      !NONCE_PATTERN.test(payload.n ?? "") ||
      !contextMatches(payload, context)
    ) {
      return null;
    }
    const publicKey = normalizeRuntimePublicKey(payload.k);
    if (
      payload.p !== runtimePublicKeyThumbprint(publicKey) ||
      !RELEASE_PATTERN.test(payload.r ?? "")
    ) {
      return null;
    }
    const authorizationId = runtimeAuthorizationId(authorization);
    const valid = verifySignature(
      "sha256",
      runtimeRequestMessage({
        authorizationId,
        method,
        pathname,
        timestamp: requestedAt,
        nonce,
        body,
      }),
      {
        key: createPublicKey({ key: publicKey, format: "jwk" }),
        dsaEncoding: "ieee-p1363",
      },
      Buffer.from(signature, "base64url"),
    );
    if (!valid) return null;
    return Object.freeze({
      authorizationId,
      thumbprint: payload.p,
      release: payload.r,
      expiresAt: payload.exp * 1_000,
      replayKey: `${authorizationId}:${nonce}`,
    });
  } catch {
    return null;
  }
}

export function createWorldCapability({
  secret,
  authorizationId,
  zoneId,
  requiredPhases,
  contentEpoch,
  now = Date.now(),
  ttlSeconds = 10 * 60,
  ...context
}) {
  if (!SESSION_PATTERN.test(authorizationId ?? "")) {
    throw new Error("A valid runtime authorization id is required");
  }
  if (!Number.isSafeInteger(zoneId) || zoneId < 0 || zoneId > 99_999_999) {
    throw new Error("A valid world zone is required");
  }
  if (
    !Array.isArray(requiredPhases) ||
    requiredPhases.length < 1 ||
    requiredPhases.length > 16 ||
    requiredPhases.some((phase) => !WORLD_PHASE_PATTERN.test(String(phase)))
  ) {
    throw new Error("World capability phases are invalid");
  }
  if (
    typeof contentEpoch !== "string" ||
    !/^[a-z0-9][a-z0-9_.-]{0,63}$/.test(contentEpoch)
  ) {
    throw new Error("World content epoch is invalid");
  }
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 60 || ttlSeconds > 30 * 60) {
    throw new Error("World capability TTL must be 60-1800 seconds");
  }
  const issuedAt = Math.floor(now / 1_000);
  const phases = [...new Set(requiredPhases.map(String))];
  const payload = {
    v: RUNTIME_AUTHORITY_PROTOCOL,
    t: "world",
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
    n: randomBytes(16).toString("base64url"),
    a: authorizationId,
    z: zoneId,
    ph: phases,
    ce: contentEpoch,
    ...requireContext(context),
  };
  return Object.freeze({
    version: RUNTIME_AUTHORITY_PROTOCOL,
    release: context.release,
    zoneId,
    requiredPhases: Object.freeze(phases),
    contentEpoch,
    capability: sealToken("world", payload, secret),
    expiresAt: payload.exp * 1_000,
  });
}
