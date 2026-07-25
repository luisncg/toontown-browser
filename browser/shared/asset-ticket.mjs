const TICKET_VERSION = "v1";
const TICKET_AAD = new TextEncoder().encode("toontown-browser-asset-ticket-v1");

function encodeBase64Url(bytes) {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(bytes).toString("base64url");
  }
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function decodeBase64Url(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("Asset ticket contains invalid base64url data");
  }
  if (typeof Buffer !== "undefined") {
    return new Uint8Array(Buffer.from(value, "base64url"));
  }
  const standard = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = standard.padEnd(Math.ceil(standard.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

export function decodeAssetTicketSecret(value) {
  const secret = decodeBase64Url(value);
  if (secret.byteLength !== 32) {
    throw new Error("ASSET_GATEWAY_TOKEN_SECRET must encode exactly 32 bytes");
  }
  return secret;
}

async function ticketKey(secret, usages) {
  return crypto.subtle.importKey(
    "raw",
    decodeAssetTicketSecret(secret),
    { name: "AES-GCM", length: 256 },
    false,
    usages,
  );
}

export async function sealAssetTicket(payload, secret) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: TICKET_AAD,
      tagLength: 128,
    },
    await ticketKey(secret, ["encrypt"]),
    plaintext,
  );
  return [
    TICKET_VERSION,
    encodeBase64Url(iv),
    encodeBase64Url(new Uint8Array(ciphertext)),
  ].join(".");
}

export async function openAssetTicket(token, secret) {
  if (typeof token !== "string" || token.length > 2_048) {
    throw new Error("Asset ticket is invalid");
  }
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== TICKET_VERSION) {
    throw new Error("Asset ticket version is invalid");
  }
  const iv = decodeBase64Url(parts[1]);
  if (iv.byteLength !== 12) throw new Error("Asset ticket IV is invalid");
  const ciphertext = decodeBase64Url(parts[2]);
  if (ciphertext.byteLength < 17) {
    throw new Error("Asset ticket ciphertext is invalid");
  }
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: TICKET_AAD,
      tagLength: 128,
    },
    await ticketKey(secret, ["decrypt"]),
    ciphertext,
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}
