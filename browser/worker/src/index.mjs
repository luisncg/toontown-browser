import { openAssetTicket } from "../../shared/asset-ticket.mjs";

const MAX_SESSION_AGE_SECONDS = 6 * 60 * 60;
const MAX_TICKET_FUTURE_SECONDS = 5 * 60;
const OBJECT_KEY = /^releases\/([a-f0-9]{64})\/([A-Za-z0-9._-]+)$/;
const ASSET_NAME = /^(?:open-toontown\.(?:data|wasm)|phase-[a-z0-9.-]+\.data|audio-bank-[a-z0-9.-]+\.data)$/;

function text(status, body) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function cookieValue(request, name) {
  const header = request.headers.get("cookie") || "";
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() === name) {
      return part.slice(separator + 1).trim();
    }
  }
  return "";
}

function hex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifyBootstrapCookie(value, secret, nowSeconds) {
  if (typeof secret !== "string" || secret.length < 32) return false;
  const parts = value.split(".");
  if (parts.length !== 3) return false;
  const [issuedAtText, nonce, signature] = parts;
  if (
    !/^\d{10}$/.test(issuedAtText) ||
    !/^[A-Za-z0-9_-]{24}$/.test(nonce) ||
    !/^[a-f0-9]{64}$/.test(signature)
  ) {
    return false;
  }
  const issuedAt = Number(issuedAtText);
  if (
    !Number.isSafeInteger(issuedAt) ||
    issuedAt > nowSeconds + 60 ||
    nowSeconds - issuedAt > MAX_SESSION_AGE_SECONDS
  ) {
    return false;
  }
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify(
    "HMAC",
    key,
    Uint8Array.from(signature.match(/../g), (byte) => Number.parseInt(byte, 16)),
    new TextEncoder().encode(`${issuedAtText}.${nonce}`),
  );
}

async function sessionDigest(value) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return hex(new Uint8Array(digest)).slice(0, 32);
}

function validTicket(ticket, request, session, nowSeconds) {
  if (!ticket || ![1, 2].includes(ticket.version)) return false;
  if (
    !Number.isSafeInteger(ticket.expiresAt) ||
    ticket.expiresAt < nowSeconds ||
    ticket.expiresAt > nowSeconds + MAX_TICKET_FUTURE_SECONDS
  ) {
    return false;
  }
  if (ticket.method !== request.method || !["GET", "HEAD"].includes(ticket.method)) {
    return false;
  }
  if (ticket.session !== session || !/^[a-f0-9]{32}$/.test(ticket.session)) {
    return false;
  }
  if (
    ticket.version === 2 &&
    (
      typeof ticket.authority !== "string" ||
      !/^[a-f0-9]{32}$/.test(ticket.authority) ||
      request.headers.get("x-toontown-asset-authority") !== ticket.authority
    )
  ) {
    return false;
  }
  if (!ASSET_NAME.test(ticket.name)) return false;
  if (!["application/octet-stream", "application/wasm"].includes(ticket.contentType)) {
    return false;
  }
  if (!["identity", "gzip"].includes(ticket.contentEncoding)) return false;
  const match = typeof ticket.objectKey === "string"
    ? ticket.objectKey.match(OBJECT_KEY)
    : undefined;
  if (!match) return false;
  const expectedObject = `${ticket.name}${ticket.contentEncoding === "gzip" ? ".gz" : ""}`;
  return match[2] === expectedObject;
}

export default {
  async fetch(request, environment) {
    const url = new URL(request.url);
    if (url.origin !== environment.PUBLIC_ORIGIN) return text(404, "Not found");
    const match = url.pathname.match(/^\/assets\/([^/]+)$/);
    if (!match) return text(404, "Not found");
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD", "Cache-Control": "private, no-store" },
      });
    }

    const bootstrapCookie = cookieValue(request, "__Host-toontown_bootstrap");
    const nowSeconds = Math.floor(Date.now() / 1_000);
    if (!await verifyBootstrapCookie(
      bootstrapCookie,
      environment.TURNSTILE_SESSION_SECRET,
      nowSeconds,
    )) {
      return text(401, "Unauthorized");
    }

    let ticket;
    try {
      ticket = await openAssetTicket(
        match[1],
        environment.ASSET_GATEWAY_TOKEN_SECRET,
      );
    } catch {
      return text(403, "Invalid asset ticket");
    }
    const session = await sessionDigest(bootstrapCookie);
    if (!validTicket(ticket, request, session, nowSeconds)) {
      return text(403, "Invalid asset ticket");
    }

    const object = request.method === "HEAD"
      ? await environment.ASSETS.head(ticket.objectKey)
      : await environment.ASSETS.get(ticket.objectKey);
    if (!object) return text(404, "Asset not found");

    const headers = new Headers();
    object.writeHttpMetadata?.(headers);
    headers.set("Content-Type", ticket.contentType);
    if (ticket.contentEncoding === "gzip") {
      headers.set("Content-Encoding", "gzip");
    } else {
      headers.delete("Content-Encoding");
    }
    headers.set("Content-Length", String(object.size));
    headers.set("Cache-Control", "private, no-store");
    headers.set("Content-Disposition", `inline; filename="${ticket.name}"`);
    headers.set("Cross-Origin-Resource-Policy", "same-origin");
    headers.set("X-Content-Type-Options", "nosniff");
    if (object.httpEtag) headers.set("ETag", object.httpEtag);
    return new Response(request.method === "HEAD" ? null : object.body, {
      status: 200,
      headers,
      // R2 stores the .gz representation exactly as uploaded. Cloudflare's
      // default automatic response encoding would gzip those bytes a second
      // time, leaving browsers with a still-compressed WASM/data payload after
      // their normal Content-Encoding decode.
      encodeBody: ticket.contentEncoding === "gzip" ? "manual" : "automatic",
    });
  },
};
