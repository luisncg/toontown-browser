import { openAssetTicket } from "../../shared/asset-ticket.mjs";

const MAX_SESSION_AGE_SECONDS = 6 * 60 * 60;
const MAX_TICKET_FUTURE_SECONDS = 5 * 60;
const BUDGET_WINDOW_MILLISECONDS = 15 * 60 * 1_000;
const RESERVATION_TTL_MILLISECONDS = 5 * 60 * 1_000;
const SESSION_BYTE_BUDGET = 768 * 1024 * 1024;
const IP_BYTE_BUDGET = 4 * 1024 * 1024 * 1024;
// Boot overlaps four Phase 4 parts, the main data/WASM pair, and two short
// audio banks. Keep two recovery slots above that normal eight-stream peak.
const SESSION_CONCURRENCY = 10;
const IP_CONCURRENCY = 30;
const MAX_TICKET_USES = 3;
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

function json(status, value) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
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

async function digestText(value) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return hex(new Uint8Array(digest));
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
  if (
    !Number.isSafeInteger(ticket.expectedBytes) ||
    ticket.expectedBytes < 1 ||
    ticket.expectedBytes > 768 * 1024 * 1024
  ) {
    return false;
  }
  const match = typeof ticket.objectKey === "string"
    ? ticket.objectKey.match(OBJECT_KEY)
    : undefined;
  if (!match) return false;
  const expectedObject = `${ticket.name}${ticket.contentEncoding === "gzip" ? ".gz" : ""}`;
  return match[2] === expectedObject;
}

async function budgetRequest(namespace, name, payload) {
  if (!namespace) throw new Error("Asset budget binding is unavailable");
  const id = namespace.idFromName(name);
  return namespace.get(id).fetch("https://asset-budget.internal/reserve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function releaseBudget(namespace, name, reservation) {
  if (!reservation) return;
  try {
    const id = namespace.idFromName(name);
    await namespace.get(id).fetch("https://asset-budget.internal/release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reservation }),
    });
  } catch {
    // Reservations also expire. A failed release cannot expand byte budgets.
  }
}

async function reserveAsset(environment, session, ipDigest, ticketDigest, bytes) {
  const sessionName = `session:${session}`;
  const ipName = `ip:${ipDigest}`;
  const sessionResponse = await budgetRequest(
    environment.ASSET_BUDGETS,
    sessionName,
    { scope: "session", ticket: ticketDigest, bytes },
  );
  if (!sessionResponse.ok) return { response: sessionResponse };
  const sessionValue = await sessionResponse.json();
  const ipResponse = await budgetRequest(
    environment.ASSET_BUDGETS,
    ipName,
    { scope: "ip", bytes },
  );
  if (!ipResponse.ok) {
    await releaseBudget(
      environment.ASSET_BUDGETS,
      sessionName,
      sessionValue.reservation,
    );
    return { response: ipResponse };
  }
  const ipValue = await ipResponse.json();
  return {
    sessionName,
    sessionReservation: sessionValue.reservation,
    ipName,
    ipReservation: ipValue.reservation,
  };
}

function guardedBody(body, release) {
  const source = new Response(body).body;
  if (!source) return null;
  const reader = source.getReader();
  let released = false;
  const finish = async () => {
    if (released) return;
    released = true;
    await release();
  };
  return new ReadableStream({
    async pull(controller) {
      try {
        const value = await reader.read();
        if (value.done) {
          controller.close();
          await finish();
          return;
        }
        controller.enqueue(value.value);
      } catch (error) {
        controller.error(error);
        await finish();
      }
    },
    async cancel(reason) {
      try {
        await reader.cancel(reason);
      } finally {
        await finish();
      }
    },
  });
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

    let reservation;
    if (request.method === "GET") {
      const clientIp = request.headers.get("cf-connecting-ip") || "";
      if (!clientIp || clientIp.length > 64) {
        return text(403, "Client identity unavailable");
      }
      reservation = await reserveAsset(
        environment,
        session,
        await digestText(clientIp),
        await digestText(match[1]),
        ticket.expectedBytes,
      );
      if (reservation.response) {
        return new Response(reservation.response.body, {
          status: reservation.response.status,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "private, no-store",
            "Retry-After": "60",
            "X-Content-Type-Options": "nosniff",
          },
        });
      }
    }

    const object = request.method === "HEAD"
      ? await environment.ASSETS.head(ticket.objectKey)
      : await environment.ASSETS.get(ticket.objectKey);
    if (!object || object.size !== ticket.expectedBytes) {
      if (reservation) {
        await Promise.all([
          releaseBudget(
            environment.ASSET_BUDGETS,
            reservation.sessionName,
            reservation.sessionReservation,
          ),
          releaseBudget(
            environment.ASSET_BUDGETS,
            reservation.ipName,
            reservation.ipReservation,
          ),
        ]);
      }
      return text(object ? 409 : 404, object
        ? "Asset metadata mismatch"
        : "Asset not found");
    }

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
    const release = reservation
      ? () => Promise.all([
        releaseBudget(
          environment.ASSET_BUDGETS,
          reservation.sessionName,
          reservation.sessionReservation,
        ),
        releaseBudget(
          environment.ASSET_BUDGETS,
          reservation.ipName,
          reservation.ipReservation,
        ),
      ])
      : async () => {};
    return new Response(
      request.method === "HEAD" ? null : guardedBody(object.body, release),
      {
      status: 200,
      headers,
      // R2 stores the .gz representation exactly as uploaded. Cloudflare's
      // default automatic response encoding would gzip those bytes a second
      // time, leaving browsers with a still-compressed WASM/data payload after
      // their normal Content-Encoding decode.
      encodeBody: ticket.contentEncoding === "gzip" ? "manual" : "automatic",
      },
    );
  },
};

export class AssetBudget {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    if (request.method !== "POST") return text(405, "Method not allowed");
    const url = new URL(request.url);
    let body;
    try {
      body = await request.json();
    } catch {
      return json(400, { error: "invalid-request" });
    }
    const now = Date.now();
    const value = await this.state.storage.get("budget") || {
      windowStarted: now,
      bytes: 0,
      active: 0,
      ticketUses: {},
      reservations: {},
    };
    for (const [id, entry] of Object.entries(value.reservations)) {
      if (!entry || entry.expiresAt <= now) {
        delete value.reservations[id];
        value.active = Math.max(0, value.active - 1);
      }
    }
    if (now - value.windowStarted >= BUDGET_WINDOW_MILLISECONDS) {
      value.windowStarted = now;
      value.bytes = 0;
      value.ticketUses = {};
    }
    if (url.pathname === "/release") {
      const reservation = value.reservations[body.reservation];
      if (reservation) {
        delete value.reservations[body.reservation];
        value.active = Math.max(0, value.active - 1);
        await this.state.storage.put("budget", value);
      }
      return json(200, { released: Boolean(reservation) });
    }
    if (url.pathname !== "/reserve") {
      return json(404, { error: "not-found" });
    }
    const bytes = body.bytes;
    if (!Number.isSafeInteger(bytes) || bytes < 1) {
      return json(400, { error: "invalid-bytes" });
    }
    const sessionScope = body.scope === "session";
    if (!sessionScope && body.scope !== "ip") {
      return json(400, { error: "invalid-scope" });
    }
    const byteLimit = sessionScope ? SESSION_BYTE_BUDGET : IP_BYTE_BUDGET;
    const concurrencyLimit = sessionScope
      ? SESSION_CONCURRENCY
      : IP_CONCURRENCY;
    if (value.bytes + bytes > byteLimit || value.active >= concurrencyLimit) {
      return json(429, { error: "asset-budget-exceeded" });
    }
    if (sessionScope) {
      if (
        typeof body.ticket !== "string" ||
        !/^[a-f0-9]{64}$/.test(body.ticket)
      ) {
        return json(400, { error: "invalid-ticket" });
      }
      const uses = value.ticketUses[body.ticket] || 0;
      if (uses >= MAX_TICKET_USES) {
        return json(429, { error: "ticket-replay-limit" });
      }
      value.ticketUses[body.ticket] = uses + 1;
    }
    const reservation = crypto.randomUUID();
    value.bytes += bytes;
    value.active += 1;
    value.reservations[reservation] = {
      bytes,
      expiresAt: now + RESERVATION_TTL_MILLISECONDS,
    };
    await this.state.storage.put("budget", value);
    return json(200, { reservation });
  }
}
