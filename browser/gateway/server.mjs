import { createServer } from "node:http";
import { createConnection, isIP } from "node:net";
import { pathToFileURL } from "node:url";
import { WebSocket, WebSocketServer } from "ws";
import {
  bootstrapSessionDigest,
  verifyBootstrapSession,
} from "../shared/bootstrap-session.mjs";
import {
  gatewayReconnectIdentity,
  validateGatewayLeaseSecret,
  verifyGatewayLease,
} from "../shared/gateway-lease.mjs";

const LOOPBACK_HOST = "127.0.0.1";
const DEFAULT_ORIGINS = [
  "http://127.0.0.1:8180",
  "http://localhost:8180",
  "http://127.0.0.1:8080",
  "http://localhost:8080",
];
const MAX_DATAGRAM_BYTES = 65_535;
const MAX_BUFFERED_BYTES = 2 * 1024 * 1024;
const MAX_CONNECT_QUEUE_BYTES = 1024 * 1024;
export const DEFAULT_MAX_ATTACHED_CONNECTIONS_PER_IP = 6;
export const DEFAULT_MAX_RETAINED_SESSIONS_PER_IP = 18;
const MAX_HANDSHAKES_PER_MINUTE = 20;
const DEFAULT_HEARTBEAT_INTERVAL_MS = 30_000;
const DEFAULT_BROWSER_SUSPEND_GRACE_MS = 15 * 60_000;
const DEFAULT_BROWSER_RESUME_GRACE_MS = 5 * 60_000;
const DEFAULT_ASTRON_HEARTBEAT_INTERVAL_MS = 10_000;
const RESUME_TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;
const AUTHORITY_KEY_PATTERN = /^[a-f0-9]{32}$/;
const BUILD_ID_PATTERN = /^[a-f0-9]{64}$/;
const VISIBILITY_HIDDEN = "toontown:visibility:hidden";
const VISIBILITY_VISIBLE = "toontown:visibility:visible";
const CLIENT_HELLO = 1;
const CLIENT_HEARTBEAT = 5;
const ASTRON_CLIENT_HEARTBEAT = Buffer.from([CLIENT_HEARTBEAT, 0]);

function rejectUpgrade(socket, status, message) {
  const body = `${message}\n`;
  socket.end(
    `HTTP/1.1 ${status}\r\n` +
    "Connection: close\r\n" +
    "Content-Type: text/plain; charset=utf-8\r\n" +
    `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`,
  );
}

function rejectOfficialUpgrade(socket) {
  const body = `${JSON.stringify({
    error: "OFFICIAL_ORIGIN_REQUIRED",
    officialUrl: "https://toontown.lui.ss/",
  })}\n`;
  socket.end(
    "HTTP/1.1 403 Forbidden\r\n" +
    "Connection: close\r\n" +
    "Content-Type: application/json; charset=utf-8\r\n" +
    "Cache-Control: private, no-store\r\n" +
    "X-Toontown-Official-Error: 1\r\n" +
    `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`,
  );
}

function rejectGatewayUpgrade(
  request,
  socket,
  status,
  message,
  reason,
) {
  let parameterNames = [];
  try {
    parameterNames = [
      ...new URL(request.url ?? "", "http://gateway.invalid").searchParams.keys(),
    ].sort();
  } catch {
    // The rejection reason already records an invalid route.
  }
  console.warn(`[GatewayReject] ${JSON.stringify({
    reason,
    status,
    origin: String(request.headers.origin ?? "").slice(0, 256),
    parameters: parameterNames,
    bootstrapCookie: String(request.headers.cookie ?? "").includes(
      "__Host-toontown_bootstrap=",
    ),
  })}`);
  rejectUpgrade(socket, status, message);
}

function normalizeForwardedAddress(value) {
  const header = Array.isArray(value) ? value[0] : value;
  if (typeof header !== "string") return "";
  const candidate = header.split(",", 1)[0].trim();
  return isIP(candidate) ? candidate : "";
}

function isLoopbackAddress(address) {
  return (
    address === "127.0.0.1" ||
    address === "::1" ||
    address === "::ffff:127.0.0.1"
  );
}

export function resolveGatewayClientAddress(request) {
  const directAddress = request?.socket?.remoteAddress ?? "unknown";
  if (!isLoopbackAddress(directAddress)) return directAddress;
  return (
    normalizeForwardedAddress(
      request?.headers?.["x-toontown-client-ip"],
    ) ||
    directAddress
  );
}

function frameDatagram(payload) {
  if (payload.length === 0 || payload.length > MAX_DATAGRAM_BYTES) {
    throw new RangeError(`Astron datagram must be 1-${MAX_DATAGRAM_BYTES} bytes`);
  }
  const framed = Buffer.allocUnsafe(payload.length + 2);
  framed.writeUInt16LE(payload.length, 0);
  payload.copy(framed, 2);
  return framed;
}

export function createGateway({
  port = 7200,
  targetPort = 7198,
  allowedOrigins = DEFAULT_ORIGINS,
  heartbeatIntervalMs = DEFAULT_HEARTBEAT_INTERVAL_MS,
  browserSuspendGraceMs = DEFAULT_BROWSER_SUSPEND_GRACE_MS,
  browserResumeGraceMs = DEFAULT_BROWSER_RESUME_GRACE_MS,
  astronHeartbeatIntervalMs = DEFAULT_ASTRON_HEARTBEAT_INTERVAL_MS,
  testCloseMs = 0,
  requireBootstrapSession = false,
  bootstrapSessionSecret = "",
  requireGatewayLease = false,
  gatewayLeaseSecret = "",
  maxAttachedConnectionsPerIp = DEFAULT_MAX_ATTACHED_CONNECTIONS_PER_IP,
  maxRetainedSessionsPerIp = DEFAULT_MAX_RETAINED_SESSIONS_PER_IP,
} = {}) {
  if (!Number.isInteger(port) || port < 0 || port > 65_535) {
    throw new TypeError("Gateway port must be an integer between 0 and 65535");
  }
  if (!Number.isInteger(targetPort) || targetPort < 1 || targetPort > 65_535) {
    throw new TypeError("Astron port must be an integer between 1 and 65535");
  }
  if (!Number.isInteger(heartbeatIntervalMs) || heartbeatIntervalMs < 1) {
    throw new TypeError("Gateway heartbeat interval must be a positive integer");
  }
  if (
    !Number.isInteger(browserSuspendGraceMs) ||
    browserSuspendGraceMs < heartbeatIntervalMs
  ) {
    throw new TypeError(
      "Browser suspension grace must be an integer at least as large as " +
      "the gateway heartbeat interval",
    );
  }
  if (!Number.isInteger(browserResumeGraceMs) || browserResumeGraceMs < 1) {
    throw new TypeError("Browser resume grace must be a positive integer");
  }
  if (
    !Number.isInteger(astronHeartbeatIntervalMs) ||
    astronHeartbeatIntervalMs < 1
  ) {
    throw new TypeError(
      "Astron heartbeat interval must be a positive integer",
    );
  }
  if (!Number.isInteger(testCloseMs) || testCloseMs < 0) {
    throw new TypeError("Gateway test close delay must be a non-negative integer");
  }
  if (
    !Number.isInteger(maxAttachedConnectionsPerIp) ||
    maxAttachedConnectionsPerIp < 1
  ) {
    throw new TypeError(
      "Gateway attached connection limit must be a positive integer",
    );
  }
  if (
    !Number.isInteger(maxRetainedSessionsPerIp) ||
    maxRetainedSessionsPerIp < maxAttachedConnectionsPerIp
  ) {
    throw new TypeError(
      "Gateway retained session limit must be an integer at least as large " +
      "as the attached connection limit",
    );
  }
  if (requireGatewayLease) {
    validateGatewayLeaseSecret(gatewayLeaseSecret);
    if (!requireBootstrapSession) {
      throw new Error(
        "Gateway leases require verified production bootstrap sessions",
      );
    }
  }

  const originSet = new Set(allowedOrigins);
  const activeByIp = new Map();
  const attachedByIp = new Map();
  const handshakeWindows = new Map();
  const resumableSessions = new Map();
  let activeConnections = 0;
  let attachedConnections = 0;
  let nextConnectionId = 1;
  let testClosePending = testCloseMs > 0;

  const httpServer = createServer((request, response) => {
    if (request.url !== "/health") {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }
    response.writeHead(200, {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    });
    response.end(JSON.stringify({
      ok: true,
      activeConnections,
      attachedConnections,
      target: `${LOOPBACK_HOST}:${targetPort}`,
    }));
  });

  const webSockets = new WebSocketServer({
    noServer: true,
    clientTracking: true,
    maxPayload: MAX_DATAGRAM_BYTES,
    perMessageDeflate: false,
  });

  function logUpgradeRejection(reason, clientAddress) {
    console.warn(`[GatewayReject] ${JSON.stringify({
      reason,
      status: 429,
      attachedForClient: attachedByIp.get(clientAddress) ?? 0,
      retainedForClient: activeByIp.get(clientAddress) ?? 0,
    })}`);
  }

  httpServer.on("upgrade", (request, socket, head) => {
    let requestUrl;
    try {
      requestUrl = new URL(request.url ?? "", "http://gateway.invalid");
    } catch {
      rejectGatewayUpgrade(
        request,
        socket,
        "400 Bad Request",
        "Invalid WebSocket route",
        "invalid_route",
      );
      return;
    }
    if (requestUrl.pathname !== "/astron") {
      rejectGatewayUpgrade(
        request,
        socket,
        "404 Not Found",
        "Unknown WebSocket route",
        "unknown_route",
      );
      return;
    }

    const resumeToken = requestUrl.searchParams.get("resume") ?? "";
    const authorityKey = requestUrl.searchParams.get("authority") ?? "";
    const buildId = requestUrl.searchParams.get("build") ?? "";
    const officialBuildId =
      requestUrl.searchParams.get("attestation") ?? "";
    const reconnect = requestUrl.searchParams.get("reconnect") === "1";
    if (!RESUME_TOKEN_PATTERN.test(resumeToken)) {
      rejectGatewayUpgrade(
        request,
        socket,
        "400 Bad Request",
        "A valid resume token is required",
        "invalid_resume",
      );
      return;
    }
    if (requireGatewayLease && !AUTHORITY_KEY_PATTERN.test(authorityKey)) {
      rejectGatewayUpgrade(
        request,
        socket,
        "400 Bad Request",
        "A valid runtime authority is required",
        "invalid_authority",
      );
      return;
    }
    if (
      requireGatewayLease &&
      (
        !BUILD_ID_PATTERN.test(buildId) ||
        !AUTHORITY_KEY_PATTERN.test(officialBuildId)
      )
    ) {
      console.warn(`[GatewayReject] ${JSON.stringify({
        reason: "invalid_official_build",
        status: 403,
      })}`);
      rejectOfficialUpgrade(socket);
      return;
    }

    const origin = request.headers.origin;
    if (!origin || !originSet.has(origin)) {
      rejectOfficialUpgrade(socket);
      return;
    }
    if (
      requireBootstrapSession &&
      !verifyBootstrapSession(request.headers, bootstrapSessionSecret)
    ) {
      rejectGatewayUpgrade(
        request,
        socket,
        "401 Unauthorized",
        "Browser verification is required",
        "invalid_bootstrap",
      );
      return;
    }

    const ip = resolveGatewayClientAddress(request);
    const now = Date.now();
    let window = handshakeWindows.get(ip);
    if (!window || now - window.startedAt >= 60_000) {
      window = { startedAt: now, count: 0 };
      handshakeWindows.set(ip, window);
    }
    window.count += 1;

    if (window.count > MAX_HANDSHAKES_PER_MINUTE) {
      logUpgradeRejection("handshake_limit", ip);
      rejectUpgrade(socket, "429 Too Many Requests", "Handshake rate limit exceeded");
      return;
    }

    const sessionKey = requireBootstrapSession
      ? bootstrapSessionDigest(request.headers)
      : "";
    const userAgent = String(request.headers["user-agent"] ?? "").slice(0, 1_024);
    const reconnectIdentity = requireBootstrapSession
      ? gatewayReconnectIdentity({
        sessionKey,
        userAgent,
        origin,
        authorityKey,
        buildId,
        officialBuildId,
      })
      : null;
    if (requireBootstrapSession && !reconnectIdentity) {
      rejectGatewayUpgrade(
        request,
        socket,
        "401 Unauthorized",
        "Browser identity is required",
        "invalid_identity",
      );
      return;
    }

    const retainedSession = resumableSessions.get(resumeToken);
    if (reconnect) {
      if (!retainedSession || !retainedSession.canResume()) {
        rejectGatewayUpgrade(
          request,
          socket,
          "409 Conflict",
          "Browser session cannot be resumed",
          "resume_unavailable",
        );
        return;
      }
      if (
        requireBootstrapSession &&
        !retainedSession.matchesReconnect(reconnectIdentity)
      ) {
        rejectGatewayUpgrade(
          request,
          socket,
          "403 Forbidden",
          "Browser session does not match",
          "resume_identity_mismatch",
        );
        return;
      }
    } else if (retainedSession) {
      rejectGatewayUpgrade(
        request,
        socket,
        "409 Conflict",
        "Resume token is already active",
        "resume_already_active",
      );
      return;
    } else if (
      requireGatewayLease &&
      !verifyGatewayLease(
        requestUrl.searchParams.get("lease") ?? "",
        gatewayLeaseSecret,
        {
          sessionKey,
          resumeToken,
          clientAddress: ip,
          userAgent,
          origin,
          authorityKey,
          buildId,
          officialBuildId,
        },
      )
    ) {
      console.warn(`[GatewayReject] ${JSON.stringify({
        reason: "invalid_official_lease",
        status: 403,
      })}`);
      rejectOfficialUpgrade(socket);
      return;
    }

    const sessionIp = reconnect ? retainedSession.clientAddress : ip;
    if (
      (attachedByIp.get(sessionIp) ?? 0) >= maxAttachedConnectionsPerIp
    ) {
      logUpgradeRejection("attached_limit", sessionIp);
      rejectUpgrade(
        socket,
        "429 Too Many Requests",
        "Attached connection limit exceeded",
      );
      return;
    }
    if (
      !reconnect &&
      (activeByIp.get(ip) ?? 0) >= maxRetainedSessionsPerIp
    ) {
      logUpgradeRejection("retained_limit", ip);
      rejectUpgrade(
        socket,
        "429 Too Many Requests",
        "Retained session limit exceeded",
      );
      return;
    }

    webSockets.handleUpgrade(request, socket, head, (webSocket) => {
      webSockets.emit("connection", webSocket, request, {
        clientAddress: ip,
        reconnect,
        reconnectIdentity,
        resumeToken,
      });
    });
  });

  function logConnection(connectionId, event, fields = {}) {
    console.log(`[GatewayConnection] ${JSON.stringify({
      connectionId,
      event,
      ...fields,
    })}`);
  }

  function createAstronSession(
    initialWebSocket,
    resumeToken,
    clientAddress,
    reconnectIdentity,
  ) {
    const ip = clientAddress;
    const connectionId = `gateway-${nextConnectionId++}`;
    const createdAt = Date.now();
    activeByIp.set(ip, (activeByIp.get(ip) ?? 0) + 1);
    activeConnections += 1;

    let currentWebSocket = null;
    let tcpBuffer = Buffer.alloc(0);
    let queuedBytes = 0;
    const connectQueue = [];
    const detachedDatagrams = [];
    let detachedBytes = 0;
    let closed = false;
    let detachedAt = 0;
    let resumeExpiryTimer;
    let browserHeartbeatTimer;
    let lastBrowserActivityAt = Date.now();
    let lastHiddenAt = 0;
    let browserHidden = false;
    let trafficWindowStarted = Date.now();
    let trafficWindowBytes = 0;
    let trafficWindowMessages = 0;
    let browserDatagramCount = 0;
    let astronHelloSeen = false;

    const astron = createConnection({ host: LOOPBACK_HOST, port: targetPort });
    astron.setNoDelay(true);

    const releaseAttachmentCount = (webSocket) => {
      if (!webSocket.__toontownAttachmentCounted) return;
      webSocket.__toontownAttachmentCounted = false;
      attachedConnections -= 1;
      const remaining = (attachedByIp.get(ip) ?? 1) - 1;
      if (remaining > 0) attachedByIp.set(ip, remaining);
      else attachedByIp.delete(ip);
    };

    const finalize = (
      code = 1011,
      reason = "Gateway connection closed",
      source = "gateway",
    ) => {
      if (closed) return;
      closed = true;
      resumableSessions.delete(resumeToken);
      if (resumeExpiryTimer) clearTimeout(resumeExpiryTimer);
      if (browserHeartbeatTimer) clearInterval(browserHeartbeatTimer);
      astron.destroy();

      const webSocket = currentWebSocket;
      currentWebSocket = null;
      if (webSocket) {
        releaseAttachmentCount(webSocket);
        if (
          webSocket.readyState === WebSocket.OPEN ||
          webSocket.readyState === WebSocket.CONNECTING
        ) {
          webSocket.close(code, reason.slice(0, 123));
        }
      }

      activeConnections -= 1;
      const remaining = (activeByIp.get(ip) ?? 1) - 1;
      if (remaining > 0) activeByIp.set(ip, remaining);
      else activeByIp.delete(ip);
      logConnection(connectionId, "closed", {
        source,
        code,
        lifetimeMs: Date.now() - createdAt,
        astronHelloSeen,
      });
    };

    const queueOrWriteAstron = (frame) => {
      if (astron.connecting) {
        queuedBytes += frame.length;
        if (queuedBytes > MAX_CONNECT_QUEUE_BYTES) {
          finalize(1013, "Astron connection queue is full", "astron_queue");
          return false;
        }
        connectQueue.push(frame);
        return true;
      }
      if (astron.destroyed) return false;
      if (astron.writableLength > MAX_BUFFERED_BYTES) {
        finalize(1013, "Astron send buffer is full", "astron_buffer");
        return false;
      }
      astron.write(frame);
      return true;
    };

    const bufferOrSendToBrowser = (datagram) => {
      const webSocket = currentWebSocket;
      if (webSocket?.readyState === WebSocket.OPEN) {
        if (webSocket.bufferedAmount > MAX_BUFFERED_BYTES) {
          finalize(1013, "Browser receive buffer is full", "browser_buffer");
          return false;
        }
        webSocket.send(datagram, { binary: true });
        return true;
      }

      detachedBytes += datagram.length;
      if (detachedBytes > MAX_BUFFERED_BYTES) {
        finalize(
          1013,
          "Detached browser receive buffer is full",
          "resume_buffer",
        );
        return false;
      }
      detachedDatagrams.push(Buffer.from(datagram));
      return true;
    };

    const startBrowserHeartbeat = () => {
      if (browserHeartbeatTimer) clearInterval(browserHeartbeatTimer);
      browserHeartbeatTimer = setInterval(() => {
        const webSocket = currentWebSocket;
        if (!webSocket || webSocket.readyState !== WebSocket.OPEN) return;
        if (Date.now() - lastBrowserActivityAt >= browserSuspendGraceMs) {
          finalize(1001, "Connection heartbeat timed out", "browser_timeout");
          return;
        }
        webSocket.ping();
      }, heartbeatIntervalMs);
      browserHeartbeatTimer.unref();
    };

    const attach = (webSocket, isResume = false) => {
      if (closed || currentWebSocket) return false;
      currentWebSocket = webSocket;
      webSocket.__toontownAttachmentCounted = true;
      attachedConnections += 1;
      attachedByIp.set(ip, (attachedByIp.get(ip) ?? 0) + 1);
      lastBrowserActivityAt = Date.now();
      browserHidden = false;
      if (resumeExpiryTimer) {
        clearTimeout(resumeExpiryTimer);
        resumeExpiryTimer = undefined;
      }

      webSocket.on("message", (data, isBinary) => {
        if (webSocket !== currentWebSocket || closed) return;
        lastBrowserActivityAt = Date.now();
        if (!isBinary) {
          const control = Buffer.from(data).toString("utf8");
          if (control === VISIBILITY_HIDDEN) {
            browserHidden = true;
            lastHiddenAt = Date.now();
            return;
          }
          if (control === VISIBILITY_VISIBLE) {
            browserHidden = false;
            return;
          }
          finalize(1003, "Unsupported gateway control message", "control");
          return;
        }

        const now = Date.now();
        if (now - trafficWindowStarted >= 10_000) {
          trafficWindowStarted = now;
          trafficWindowBytes = 0;
          trafficWindowMessages = 0;
        }
        trafficWindowBytes += data.length;
        trafficWindowMessages += 1;
        if (
          trafficWindowBytes > 8 * 1024 * 1024 ||
          trafficWindowMessages > 512
        ) {
          finalize(1008, "Datagram rate limit exceeded", "rate_limit");
          return;
        }

        let frame;
        try {
          const datagram = Buffer.from(data);
          if (
            browserDatagramCount === 0 &&
            datagram.length >= 2 &&
            datagram.readUInt16LE(0) === CLIENT_HELLO
          ) {
            astronHelloSeen = true;
          }
          browserDatagramCount += 1;
          frame = frameDatagram(datagram);
        } catch {
          finalize(1009, "Datagram is too large", "datagram");
          return;
        }
        queueOrWriteAstron(frame);
      });

      webSocket.on("pong", () => {
        if (webSocket === currentWebSocket) {
          lastBrowserActivityAt = Date.now();
        }
      });

      webSocket.on("close", (code) => {
        releaseAttachmentCount(webSocket);
        if (webSocket !== currentWebSocket || closed) return;
        currentWebSocket = null;
        if (browserHeartbeatTimer) {
          clearInterval(browserHeartbeatTimer);
          browserHeartbeatTimer = undefined;
        }

        const recentlyBackgrounded =
          lastHiddenAt > 0 &&
          Date.now() - lastHiddenAt <= browserResumeGraceMs;
        if (
          astronHelloSeen &&
          code !== 1000 &&
          (browserHidden || recentlyBackgrounded)
        ) {
          detachedAt = Date.now();
          resumeExpiryTimer = setTimeout(
            () => finalize(
              1001,
              "Browser resume window expired",
              "resume_timeout",
            ),
            browserResumeGraceMs,
          );
          resumeExpiryTimer.unref();
          logConnection(connectionId, "detached", {
            code,
            browserHidden,
            lifetimeMs: detachedAt - createdAt,
          });
          return;
        }
        finalize(code || 1001, "Browser closed the connection", "browser_close");
      });

      webSocket.on("error", () => {
        // The close event supplies the actionable outcome. Do not destroy a
        // hidden-page session here before it has a chance to enter resume mode.
      });

      startBrowserHeartbeat();
      if (isResume) {
        logConnection(connectionId, "resumed", {
          detachedMs: Math.max(0, Date.now() - detachedAt),
          bufferedDatagrams: detachedDatagrams.length,
          bufferedBytes: detachedBytes,
        });
      } else {
        logConnection(connectionId, "opened");
      }

      while (detachedDatagrams.length) {
        const datagram = detachedDatagrams.shift();
        detachedBytes -= datagram.length;
        if (!bufferOrSendToBrowser(datagram)) break;
      }
      return true;
    };

    astron.on("connect", () => {
      for (const frame of connectQueue) astron.write(frame);
      connectQueue.length = 0;
      queuedBytes = 0;
    });

    astron.on("data", (chunk) => {
      tcpBuffer = tcpBuffer.length ? Buffer.concat([tcpBuffer, chunk]) : chunk;
      while (tcpBuffer.length >= 2) {
        const length = tcpBuffer.readUInt16LE(0);
        if (length === 0) {
          finalize(1002, "Astron sent an empty datagram", "astron_datagram");
          return;
        }
        if (tcpBuffer.length < length + 2) break;
        const datagram = tcpBuffer.subarray(2, length + 2);
        tcpBuffer = tcpBuffer.subarray(length + 2);
        if (!bufferOrSendToBrowser(datagram)) return;
      }
    });

    astron.on(
      "end",
      () => finalize(1001, "Astron closed the connection", "astron_end"),
    );
    astron.on(
      "error",
      () => finalize(1011, "Astron is unavailable", "astron_error"),
    );

    // Rendering and Python tasks can be throttled or suspended in a hidden
    // browser tab. Once the gateway has forwarded a valid first CLIENT_HELLO,
    // keep Astron's authenticated TCP session alive independently of frames.
    const astronHeartbeatFrame = frameDatagram(ASTRON_CLIENT_HEARTBEAT);
    const astronHeartbeatTimer = setInterval(() => {
      if (!closed && astronHelloSeen) {
        queueOrWriteAstron(astronHeartbeatFrame);
      }
    }, astronHeartbeatIntervalMs);
    astronHeartbeatTimer.unref();
    astron.once("close", () => clearInterval(astronHeartbeatTimer));

    let testCloseTimer;
    if (testClosePending) {
      testClosePending = false;
      testCloseTimer = setTimeout(
        () => finalize(1001, "Test connection close", "test"),
        testCloseMs,
      );
      testCloseTimer.unref();
      astron.once("close", () => clearTimeout(testCloseTimer));
    }

    const session = {
      attach,
      canResume: () => !closed && currentWebSocket === null,
      clientAddress: ip,
      matchesReconnect: (candidate) => (
        reconnectIdentity === null
          ? candidate === null
          : candidate !== null &&
            candidate.sessionKey === reconnectIdentity.sessionKey &&
            candidate.userAgentDigest === reconnectIdentity.userAgentDigest &&
            candidate.origin === reconnectIdentity.origin &&
            candidate.authorityKey === reconnectIdentity.authorityKey &&
            candidate.buildId === reconnectIdentity.buildId &&
            candidate.officialBuildId ===
              reconnectIdentity.officialBuildId
      ),
      close: () => finalize(1001, "Gateway is shutting down", "shutdown"),
    };
    resumableSessions.set(resumeToken, session);
    attach(initialWebSocket);
    return session;
  }

  webSockets.on("connection", (webSocket, request, context) => {
    if (context.reconnect) {
      const session = resumableSessions.get(context.resumeToken);
      if (!session?.attach(webSocket, true)) {
        webSocket.close(4409, "Browser session cannot be resumed");
      }
      return;
    }
    createAstronSession(
      webSocket,
      context.resumeToken,
      context.clientAddress,
      context.reconnectIdentity,
    );
  });

  httpServer.on("close", () => {
    for (const session of resumableSessions.values()) session.close();
    webSockets.close();
  });
  httpServer.listen(port, LOOPBACK_HOST);
  return httpServer;
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const port = Number(process.env.GATEWAY_PORT ?? 7200);
  const targetPort = Number(process.env.ASTRON_PORT ?? 7198);
  const heartbeatIntervalMs = Number(
    process.env.GATEWAY_HEARTBEAT_INTERVAL_MS ?? DEFAULT_HEARTBEAT_INTERVAL_MS,
  );
  const browserSuspendGraceMs = Number(
    process.env.GATEWAY_BROWSER_SUSPEND_GRACE_MS ??
      DEFAULT_BROWSER_SUSPEND_GRACE_MS,
  );
  const browserResumeGraceMs = Number(
    process.env.GATEWAY_BROWSER_RESUME_GRACE_MS ??
      DEFAULT_BROWSER_RESUME_GRACE_MS,
  );
  const astronHeartbeatIntervalMs = Number(
    process.env.ASTRON_HEARTBEAT_INTERVAL_MS ??
      DEFAULT_ASTRON_HEARTBEAT_INTERVAL_MS,
  );
  const testCloseMs = Number(process.env.GATEWAY_TEST_CLOSE_MS ?? 0);
  const requireBootstrapSession = process.env.TOONTOWN_PRODUCTION === "1";
  const requireGatewayLease = process.env.TOONTOWN_PRODUCTION === "1";
  const bootstrapSessionSecret = process.env.TURNSTILE_SESSION_SECRET ?? "";
  const gatewayLeaseSecret = process.env.GATEWAY_LEASE_SECRET ?? "";
  if (requireBootstrapSession && bootstrapSessionSecret.length < 32) {
    throw new Error(
      "TURNSTILE_SESSION_SECRET is required in production and must be at least 32 characters",
    );
  }
  const allowedOrigins = (process.env.ALLOWED_ORIGINS ?? DEFAULT_ORIGINS.join(","))
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
  const server = createGateway({
    port,
    targetPort,
    allowedOrigins,
    heartbeatIntervalMs,
    browserSuspendGraceMs,
    browserResumeGraceMs,
    astronHeartbeatIntervalMs,
    testCloseMs,
    requireBootstrapSession,
    bootstrapSessionSecret,
    requireGatewayLease,
    gatewayLeaseSecret,
  });
  server.on("listening", () => {
    console.log(`WebSocket gateway: ws://${LOOPBACK_HOST}:${port}/astron`);
    console.log(`Astron target: ${LOOPBACK_HOST}:${targetPort}`);
  });
}

export { frameDatagram };
