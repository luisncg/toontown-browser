import {
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";


export const BOOTSTRAP_COOKIE = "__Host-toontown_bootstrap";
export const BOOTSTRAP_MAX_AGE_SECONDS = 6 * 60 * 60;

function signature(value, secret) {
  return createHmac("sha256", secret).update(value).digest("hex");
}

export function bootstrapSessionValue(headers) {
  const cookieHeader = headers.cookie ?? "";
  for (const part of cookieHeader.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const name = part.slice(0, separator).trim();
    if (name === BOOTSTRAP_COOKIE) {
      return part.slice(separator + 1).trim();
    }
  }
  return "";
}

export function createBootstrapSession(secret, now = Date.now()) {
  if (typeof secret !== "string" || secret.length < 32) {
    throw new Error("TURNSTILE_SESSION_SECRET must contain at least 32 characters");
  }
  const issuedAt = Math.floor(now / 1000);
  const payload = `${issuedAt}.${randomBytes(18).toString("base64url")}`;
  return `${payload}.${signature(payload, secret)}`;
}

export function verifyBootstrapSession(headers, secret, now = Date.now()) {
  if (typeof secret !== "string" || secret.length < 32) return false;
  const value = bootstrapSessionValue(headers);
  const parts = value.split(".");
  if (parts.length !== 3) return false;
  const [issuedAtText, nonce, providedSignature] = parts;
  if (!/^\d{10}$/.test(issuedAtText) || !/^[A-Za-z0-9_-]{24}$/.test(nonce)) {
    return false;
  }
  const issuedAt = Number(issuedAtText);
  const current = Math.floor(now / 1000);
  if (
    !Number.isSafeInteger(issuedAt) ||
    issuedAt > current + 60 ||
    current - issuedAt > BOOTSTRAP_MAX_AGE_SECONDS
  ) {
    return false;
  }
  const expected = Buffer.from(signature(`${issuedAtText}.${nonce}`, secret));
  const provided = Buffer.from(providedSignature);
  return (
    expected.length === provided.length &&
    timingSafeEqual(expected, provided)
  );
}

export function bootstrapSessionDigest(headers, length = 32) {
  if (!Number.isInteger(length) || length < 16 || length > 64) {
    throw new RangeError("Bootstrap session digest length must be 16-64");
  }
  const value = bootstrapSessionValue(headers);
  if (!value) return "";
  return createHash("sha256").update(value).digest("hex").slice(0, length);
}

export function bootstrapCookieHeader(value) {
  return (
    `${BOOTSTRAP_COOKIE}=${value}; ` +
    `Max-Age=${BOOTSTRAP_MAX_AGE_SECONDS}; Path=/; ` +
    "HttpOnly; Secure; SameSite=Strict"
  );
}
