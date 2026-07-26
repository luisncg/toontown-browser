import { createHash } from "node:crypto";
import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { isIP } from "node:net";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  bootstrapSessionDigest,
  bootstrapCookieHeader,
  createBootstrapSession,
  verifyBootstrapSession,
} from "../shared/bootstrap-session.mjs";
import {
  createGatewayLease,
  createGatewayResumeToken,
  DEFAULT_GATEWAY_LEASE_TTL_SECONDS,
  validateGatewayLeaseSecret,
} from "../shared/gateway-lease.mjs";
import { createR2AssetStoreFromEnvironment } from "../shared/r2-assets.mjs";
import {
  createRuntimeAuthorization,
  createRuntimeChallenge,
  createWorldCapability,
  RUNTIME_AUTHORITY_PROTOCOL,
  validateRuntimeAuthoritySecret,
  verifyRuntimeRegistration,
  verifyRuntimeRequestProof,
} from "../shared/runtime-authority.mjs";
import {
  createGameSessionState,
  createSignedFeatureModule,
  createGameTransitionCapability,
  GAME_AUTHORITY_PROTOCOL,
  verifyGameSessionState,
} from "../shared/game-authority.mjs";
import {
  featureModuleById,
  worldCompositionForZone,
} from "../server/world-composition.mjs";

const root = resolve(process.argv[2] ?? "dist-web");
const projectRoot = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const resourcesRoot = join(projectRoot, "resources");
const port = Number(process.env.PORT ?? 8180);
const production = process.env.TOONTOWN_PRODUCTION === "1";
const publicOrigin = process.env.PUBLIC_ORIGIN ?? "";
const turnstileSiteKey = process.env.TURNSTILE_SITE_KEY ?? "";
const turnstileSecretKey = process.env.TURNSTILE_SECRET_KEY ?? "";
const sessionSecret = process.env.TURNSTILE_SESSION_SECRET ?? "";
const gatewayLeaseSecret = process.env.GATEWAY_LEASE_SECRET ?? "";
const runtimeAuthoritySecret = process.env.RUNTIME_AUTHORITY_SECRET ?? "";
const gameAuthoritySecret = production
  ? runtimeAuthoritySecret
  : createHash("sha256")
      .update("toontown-browser-local-game-authority-v1", "utf8")
      .digest("base64url");
const VERIFY_WINDOW_MS = 60_000;
const VERIFY_LIMIT = 10;
const MAX_REQUEST_BODY_BYTES = 16 * 1024;
const PERFORMANCE_WINDOW_MS = 60_000;
const PERFORMANCE_LIMIT = 30;
const MAX_PERFORMANCE_BODY_BYTES = 8 * 1024;
const MAX_PERFORMANCE_EVENTS = 16;
const ASSET_TICKET_WINDOW_MS = 60_000;
const ASSET_TICKET_LIMIT = 20;
const MAX_ASSET_TICKET_BODY_BYTES = 8 * 1024;
const MAX_ASSET_TICKET_BATCH = 32;
const GATEWAY_LEASE_WINDOW_MS = 60_000;
const GATEWAY_LEASE_LIMIT = 12;
const RUNTIME_CHALLENGE_WINDOW_MS = 60_000;
const RUNTIME_CHALLENGE_LIMIT = 20;
const RUNTIME_AUTHORIZE_WINDOW_MS = 60_000;
const RUNTIME_AUTHORIZE_LIMIT = 12;
const WORLD_CAPABILITY_WINDOW_MS = 60_000;
const WORLD_CAPABILITY_LIMIT = 30;
const GAME_SESSION_WINDOW_MS = 60_000;
const GAME_SESSION_LIMIT = 12;
const GAME_TRANSITION_WINDOW_MS = 60_000;
const GAME_TRANSITION_LIMIT = 90;
const FEATURE_MODULE_WINDOW_MS = 60_000;
const FEATURE_MODULE_LIMIT = 30;
const MAX_FEATURE_MODULE_BATCH = 8;
const MAX_RUNTIME_BODY_BYTES = 16 * 1024;
const MAX_WORLD_CAPABILITY_ZONES = 16;
const PRIVATE_ASSET_NAME =
  /^(?:open-toontown\.(?:data|wasm)|phase-[a-z0-9.-]+\.data|audio-bank-[a-z0-9.-]+\.data)$/;
const verifyWindows = new Map();
const performanceWindows = new Map();
const assetTicketWindows = new Map();
const gatewayLeaseWindows = new Map();
const runtimeChallengeWindows = new Map();
const runtimeAuthorizeWindows = new Map();
const worldCapabilityWindows = new Map();
const gameSessionWindows = new Map();
const gameTransitionWindows = new Map();
const featureModuleWindows = new Map();
const runtimeChallengeUses = new Map();
const runtimeProofUses = new Map();
const r2AssetStore = createR2AssetStoreFromEnvironment({
  environment: process.env,
  webRoot: root,
  requireExternalManifest: production,
  requireWorkerGateway: production,
});
const mime = {
  ".css": "text/css; charset=utf-8",
  ".data": "application/octet-stream",
  ".html": "text/html; charset=utf-8",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".ogg": "audio/ogg",
  ".png": "image/png",
  ".wasm": "application/wasm",
};

if (!Number.isInteger(port) || port < 1 || port > 65_535) {
  throw new Error("PORT must be an integer between 1 and 65535");
}

let expectedHostname = "";
if (production) {
  let parsedOrigin;
  try {
    parsedOrigin = new URL(publicOrigin);
  } catch {
    throw new Error("PUBLIC_ORIGIN must be a valid HTTPS origin in production");
  }
  if (
    parsedOrigin.protocol !== "https:" ||
    parsedOrigin.origin !== publicOrigin ||
    parsedOrigin.pathname !== "/"
  ) {
    throw new Error("PUBLIC_ORIGIN must be an exact HTTPS origin in production");
  }
  expectedHostname = parsedOrigin.hostname;
  if (!turnstileSiteKey || !turnstileSecretKey) {
    throw new Error("Turnstile site and secret keys are required in production");
  }
  if (sessionSecret.length < 32) {
    throw new Error(
      "TURNSTILE_SESSION_SECRET is required in production and must be at least 32 characters",
    );
  }
  validateGatewayLeaseSecret(gatewayLeaseSecret);
  validateRuntimeAuthoritySecret(runtimeAuthoritySecret);
}

function assetFallbacks(relative) {
  if (!relative.startsWith("resources/")) return [];

  const candidates = [resolve(join(projectRoot, relative))];
  const duplicatePhase = relative.match(
    /^resources\/(phase_[^/]+)\/.*\/(phase_[^/]+)\/(.+)$/,
  );
  if (duplicatePhase && duplicatePhase[1] === duplicatePhase[2]) {
    candidates.unshift(
      resolve(join(resourcesRoot, duplicatePhase[2], duplicatePhase[3])),
    );
  }

  return candidates.flatMap((candidate) =>
    extname(candidate) ? [candidate] : [candidate, `${candidate}.bam`],
  );
}

function safeFile(candidate, allowedRoot) {
  if (candidate !== allowedRoot && !candidate.startsWith(`${allowedRoot}/`)) {
    return null;
  }
  try {
    return statSync(candidate).isFile() ? candidate : null;
  } catch {
    return null;
  }
}

function json(response, status, value, extraHeaders = {}) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    ...extraHeaders,
  });
  response.end(body);
}

function requestIp(request) {
  const sanitized = request.headers["x-toontown-client-ip"];
  if (typeof sanitized === "string" && isIP(sanitized)) {
    return sanitized;
  }
  return (request.socket.remoteAddress ?? "unknown").slice(0, 64);
}

function consumeVerifyAttempt(ip, now = Date.now()) {
  let window = verifyWindows.get(ip);
  if (!window || now - window.startedAt >= VERIFY_WINDOW_MS) {
    window = { startedAt: now, count: 0 };
    verifyWindows.set(ip, window);
  }
  window.count += 1;
  if (verifyWindows.size > 5_000) {
    for (const [key, value] of verifyWindows) {
      if (now - value.startedAt >= VERIFY_WINDOW_MS) verifyWindows.delete(key);
    }
  }
  return window.count <= VERIFY_LIMIT;
}

function consumeWindow(windows, key, duration, limit, now = Date.now()) {
  let window = windows.get(key);
  if (!window || now - window.startedAt >= duration) {
    window = { startedAt: now, count: 0 };
    windows.set(key, window);
  }
  window.count += 1;
  if (windows.size > 5_000) {
    for (const [candidate, value] of windows) {
      if (now - value.startedAt >= duration) windows.delete(candidate);
    }
  }
  return window.count <= limit;
}

function readJsonBodyWithRaw(request, maximumBytes = MAX_REQUEST_BODY_BYTES) {
  return new Promise((resolveBody, rejectBody) => {
    let size = 0;
    let tooLarge = false;
    const chunks = [];
    request.on("data", (chunk) => {
      if (tooLarge) return;
      size += chunk.length;
      if (size > maximumBytes) {
        tooLarge = true;
        chunks.length = 0;
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (tooLarge) {
        rejectBody(new Error("request body too large"));
        return;
      }
      try {
        const raw = Buffer.concat(chunks);
        resolveBody({
          value: JSON.parse(raw.toString("utf8")),
          raw,
        });
      } catch {
        rejectBody(new Error("invalid JSON"));
      }
    });
    request.on("error", rejectBody);
  });
}

async function readJsonBody(request, maximumBytes = MAX_REQUEST_BODY_BYTES) {
  return (await readJsonBodyWithRaw(request, maximumBytes)).value;
}

function bootstrapCookieValue(headers) {
  const cookieHeader = headers.cookie ?? "";
  for (const part of cookieHeader.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() === "__Host-toontown_bootstrap") {
      return part.slice(separator + 1).trim();
    }
  }
  return "";
}

function performanceSessionId(request) {
  const session = bootstrapCookieValue(request.headers);
  const source = session || `local:${requestIp(request)}`;
  return createHash("sha256").update(source).digest("hex").slice(0, 16);
}

function privateAssetSessionId(request) {
  const session = bootstrapCookieValue(request.headers);
  const source = session || `local:${requestIp(request)}`;
  return createHash("sha256").update(source).digest("hex").slice(0, 32);
}

function runtimeRelease() {
  return r2AssetStore?.release ?? "0".repeat(64);
}

function runtimeContext(request, sessionKey = bootstrapSessionDigest(
  request.headers,
)) {
  const requestOrigin = String(request.headers.origin ?? "").trim();
  return {
    sessionKey,
    release: runtimeRelease(),
    clientAddress: requestIp(request),
    userAgent: String(request.headers["user-agent"] ?? "").slice(0, 1_024),
    origin: production
      ? publicOrigin
      : requestOrigin || `http://127.0.0.1:${port}`,
  };
}

function consumeOneUse(store, key, expiresAt, now = Date.now()) {
  for (const [candidate, expiry] of store) {
    if (expiry <= now) store.delete(candidate);
  }
  if (store.has(key)) return false;
  store.set(key, expiresAt);
  return true;
}

function runtimeChallengeFor(request, sessionKey) {
  return createRuntimeChallenge({
    secret: runtimeAuthoritySecret,
    ...runtimeContext(request, sessionKey),
  });
}

function verifyRuntimeProof(request, pathname, rawBody) {
  if (!production) {
    return Object.freeze({
      authorizationId: "0".repeat(32),
      thumbprint: "0".repeat(64),
      release: runtimeRelease(),
      expiresAt: Number.MAX_SAFE_INTEGER,
    });
  }
  const proof = verifyRuntimeRequestProof({
    secret: runtimeAuthoritySecret,
    authorization: request.headers["x-toontown-authority"],
    signature: request.headers["x-toontown-proof"],
    timestamp: request.headers["x-toontown-proof-time"],
    nonce: request.headers["x-toontown-proof-nonce"],
    method: request.method,
    pathname,
    body: rawBody,
    context: runtimeContext(request),
  });
  if (
    !proof ||
    request.headers["x-toontown-authority-id"] !== proof.authorizationId ||
    !consumeOneUse(runtimeProofUses, proof.replayKey, proof.expiresAt)
  ) {
    return null;
  }
  return proof;
}

function requiredPhasesForZone(zoneId) {
  // This is deliberately conservative during the observe-only foundation
  // rollout. More specific phase/content composition moves server-side as
  // individual world systems are migrated.
  const phases = ["4"];
  if (zoneId >= 20_000 && zoneId < 23_000) phases.push("5");
  return phases;
}

function finiteNumber(value, minimum, maximum, precision = 0) {
  if (!Number.isFinite(value)) return undefined;
  const clamped = Math.max(minimum, Math.min(maximum, value));
  const scale = 10 ** precision;
  return Math.round(clamped * scale) / scale;
}

function copyNumber(target, source, key, minimum, maximum, precision = 0) {
  const value = finiteNumber(source[key], minimum, maximum, precision);
  if (value !== undefined) target[key] = value;
}

function copyEnum(target, source, key, allowed) {
  if (typeof source[key] === "string" && allowed.has(source[key])) {
    target[key] = source[key];
  }
}

function copyPerformanceToken(target, source, key) {
  if (
    typeof source[key] === "string" &&
    /^[a-z0-9][a-z0-9_.-]{0,63}$/.test(source[key])
  ) target[key] = source[key];
}

const performanceEventTypes = new Set([
  "session",
  "runtime_ready",
  "phase_start",
  "phase_complete",
  "phase_prefetch_start",
  "phase_prefetch_complete",
  "phase_handoff",
  "frame_degraded",
  "frame_gap",
  "frame_call",
  "frame_stage",
  "interval_function",
  "interval_phase",
  "actor_animation",
  "audio_bank",
  "audio_lifecycle",
  "battle_build",
  "battle_stage",
  "battle_asset",
  "battle_sound",
  "animation_bind",
  "actor_interval_build",
  "main_thread_stall",
  "npc_movie",
  "gc_pause",
  "script_step",
  "avatar_setup",
  "interface_setup",
  "runtime_error",
  "state",
  "lifecycle",
  "toon_entry",
]);
const performanceBrowsers = new Set([
  "chromium",
  "firefox",
  "safari",
  "webkit",
  "other",
]);
const performanceDevices = new Set(["desktop", "mobile", "tablet"]);
const performanceConnections = new Set([
  "slow-2g",
  "2g",
  "3g",
  "4g",
  "unknown",
]);
const performanceStates = new Set([
  "boot",
  "login",
  "create_account",
  "avatar_chooser",
  "make_a_toon",
  "tutorial",
  "gameplay",
]);
const performanceLifecycleVisibilities = new Set(["hidden", "visible"]);
const performanceToonEntryStages = new Set([
  "selected",
  "tutorial_state",
  "first_frame",
]);
const performancePhaseHandoffStages = new Set([
  "part",
  "complete",
  "fallback",
  "error",
]);
const performancePhaseHandoffSources = new Set([
  "network",
  "encrypted_cache",
]);
const performancePhaseHandoffReasons = new Set([
  "unsupported",
  "length",
  "checksum",
  "other",
]);
const performanceNpcStages = new Set([
  "idle",
  "start",
  "ready",
  "finish",
  "timeout",
  "stale",
  "missing",
  "clear",
]);
const performanceNpcMovies = new Set([
  "complete",
  "incomplete",
  "assign",
  "choice",
  "track_choice",
  "cancel",
  "reject",
  "other",
]);
const performanceScriptStages = new Set([
  "preload",
  "prepare",
  "setup",
  "chapter",
]);
const performanceAvatarSetupStages = new Set([
  "loading",
  "construct",
  "identity",
  "generate",
  "required_fields",
  "announce",
  "interface",
  "playing",
  "total",
]);
const performanceInterfaceSetupStages = new Set([
  "news_button",
  "book",
  "options",
  "shard",
  "map",
  "inventory",
  "quest",
  "track",
  "suit",
  "photo",
  "fish",
  "optional_pages",
  "golf",
  "events",
  "news",
  "book_page",
  "laff_meter",
  "quest_map",
  "purchase",
  "controls",
  "tutorial_assets",
  "total",
]);
const performanceScripts = new Set([
  "tutorial_assets",
  "tutorial_intro",
  "tutorial_tom",
  "tutorial_book",
  "tutorial_blocker",
  "tutorial_reward",
  "tutorial_gag_shop",
  "other",
]);
const performanceScriptCommands = new Set([
  "idle",
  "dialogue",
  "visibility",
  "transform",
  "animation",
  "inventory",
  "interface",
  "audio",
  "load",
  "controls",
  "finish",
]);
const performanceFrameStages = new Set([
  "tasks",
  "interval",
  "collision",
  "render",
  "audio_late",
]);
const performanceIntervalPhases = new Set(["core", "callbacks"]);
const performanceIntervalFunctions = new Set([
  "loop",
  "play",
  "request",
  "setChatAbsolute",
  "setLocalPageChat",
  "setPageChat",
  "setPlayRate",
  "marker",
  "scene",
  "other",
]);
const performanceActorAnimationOperations = new Set([
  "setPlayRate",
  "play",
  "loop",
]);
const performanceBattleTracks = new Set([
  "fire",
  "sos",
  "npc_sos",
  "pet_sos",
  "toon_up",
  "trap",
  "lure",
  "sound",
  "throw",
  "squirt",
  "drop",
  "all",
]);
const performanceBattleBuildStages = new Set([
  "select",
  "construct",
  "total",
]);
const performanceBattleStages = new Set([
  "attack_dicts",
  "toon_movie",
  "suit_movie",
  "play_total",
]);
const performanceAudioBanks = new Set(["tutorial-battle"]);
const performanceAudioBankStages = new Set([
  "ready",
  "published",
  "play",
  "error",
]);
const performanceAudioBankErrors = new Set([
  "fetch",
  "length",
  "checksum",
  "format",
  "other",
]);
const performanceAudioLifecycleStages = new Set([
  "context_registered",
  "hidden",
  "resume",
]);
const performanceAudioLifecycleTriggers = new Set([
  "visibility",
  "visibility_retry",
  "pageshow",
  "pageshow_retry",
  "focus",
  "focus_retry",
  "user_gesture",
  "browser_smoke",
]);
const performanceAudioContextLabels = new Set([
  "panda-openal",
  "short-audio-bank",
]);
const performanceAudioContextStates = new Set([
  "running",
  "suspended",
  "interrupted",
  "closed",
]);
const performanceBattleAssetKinds = new Set([
  "prop",
  "sound",
  "model",
  "anims",
]);
const performanceBattleAssetStatuses = new Set([
  "cold",
  "cached",
  "lookup",
  "load",
]);
const performanceBattleSoundRequestStatuses = new Set([
  "first",
  "repeat",
]);
const performanceBattleSoundLookupStatuses = new Set([
  "web_audio",
  "retained",
  "indexed",
  "fallback",
]);
const performanceActorCategories = new Set([
  "toon",
  "suit",
  "prop",
  "actor",
]);
const performanceErrorCategories = new Set([
  "python",
  "javascript",
  "abort",
  "promise",
]);

function sanitizePerformanceEvent(event) {
  if (
    !event ||
    typeof event !== "object" ||
    Array.isArray(event) ||
    !performanceEventTypes.has(event.type)
  ) return null;

  const sanitized = { type: event.type };
  copyNumber(sanitized, event, "atMs", 0, 24 * 60 * 60 * 1_000);

  if (event.type === "session") {
    copyEnum(sanitized, event, "browser", performanceBrowsers);
    copyEnum(sanitized, event, "device", performanceDevices);
    copyEnum(sanitized, event, "connection", performanceConnections);
    copyNumber(sanitized, event, "viewportWidth", 1, 16_384);
    copyNumber(sanitized, event, "viewportHeight", 1, 16_384);
    copyNumber(sanitized, event, "dpr", 0.5, 8, 2);
    copyNumber(sanitized, event, "cores", 1, 32);
    copyNumber(sanitized, event, "memoryGb", 0.25, 64, 2);
    copyNumber(sanitized, event, "rttMs", 0, 10_000);
    copyNumber(sanitized, event, "downlinkMbps", 0, 10_000, 2);
    if (typeof event.touch === "boolean") sanitized.touch = event.touch;
    if (typeof event.saveData === "boolean") sanitized.saveData = event.saveData;
  } else if (event.type === "runtime_ready") {
    for (const key of [
      "durationMs",
      "canvasWidth",
      "canvasHeight",
      "viewportWidth",
      "viewportHeight",
    ]) copyNumber(sanitized, event, key, 0, 120_000);
  } else if ([
    "phase_start",
    "phase_complete",
    "phase_prefetch_start",
    "phase_prefetch_complete",
  ].includes(event.type)) {
    if (
      typeof event.phase !== "string" ||
      !/^(?:3\.5|5\.5|[4-9]|1[0-3]|news)$/.test(event.phase)
    ) return null;
    sanitized.phase = event.phase;
    copyNumber(sanitized, event, "parts", 1, 256);
    copyNumber(sanitized, event, "assetBytes", 0, 1024 * 1024 * 1024);
    copyNumber(sanitized, event, "concurrency", 1, 16);
    if (["phase_complete", "phase_prefetch_complete"].includes(event.type)) {
      copyNumber(sanitized, event, "durationMs", 0, 30 * 60 * 1_000);
      copyNumber(sanitized, event, "requests", 0, 512);
      copyNumber(sanitized, event, "transferBytes", 0, 1024 * 1024 * 1024);
      copyNumber(sanitized, event, "encodedBytes", 0, 1024 * 1024 * 1024);
      copyNumber(sanitized, event, "decodedBytes", 0, 1024 * 1024 * 1024);
      copyNumber(sanitized, event, "resourceMs", 0, 30 * 60 * 1_000);
      copyNumber(sanitized, event, "maxRequestMs", 0, 30 * 60 * 1_000);
      copyNumber(sanitized, event, "processingMs", 0, 30 * 60 * 1_000);
      if (typeof event.fromCache === "boolean") {
        sanitized.fromCache = event.fromCache;
      }
    }
  } else if (event.type === "phase_handoff") {
    if (event.phase !== "4") return null;
    sanitized.phase = "4";
    copyEnum(
      sanitized,
      event,
      "stage",
      performancePhaseHandoffStages,
    );
    copyEnum(
      sanitized,
      event,
      "source",
      performancePhaseHandoffSources,
    );
    copyEnum(
      sanitized,
      event,
      "reason",
      performancePhaseHandoffReasons,
    );
    for (const key of [
      "readMs",
      "verifyMs",
      "mountMs",
      "persistMs",
      "durationMs",
    ]) copyNumber(sanitized, event, key, 0, 30 * 60 * 1_000, 1);
    for (const key of [
      "part",
      "parts",
      "activeParts",
      "peakActiveParts",
      "networkParts",
      "cacheParts",
      "cacheFailures",
      "claims",
    ]) copyNumber(sanitized, event, key, 0, 256);
    for (const key of [
      "bytes",
      "activeBytes",
      "peakActiveBytes",
    ]) copyNumber(sanitized, event, key, 0, 1024 * 1024 * 1024);
    if (typeof event.cacheStored === "boolean") {
      sanitized.cacheStored = event.cacheStored;
    }
    if (!sanitized.stage) return null;
    if (
      sanitized.stage === "part" &&
      (
        sanitized.part === undefined ||
        !sanitized.source ||
        sanitized.durationMs === undefined
      )
    ) return null;
    if (
      ["fallback", "error"].includes(sanitized.stage) &&
      !sanitized.reason
    ) return null;
  } else if (event.type === "frame_degraded") {
    copyNumber(sanitized, event, "windowMs", 1_000, 120_000);
    copyNumber(sanitized, event, "fps", 0, 240, 2);
    copyNumber(sanitized, event, "maxGapMs", 0, 120_000, 1);
    copyNumber(sanitized, event, "gaps100", 0, 100_000);
    copyNumber(sanitized, event, "gaps250", 0, 100_000);
    copyNumber(sanitized, event, "gaps1000", 0, 100_000);
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
    if (
      typeof event.phase === "string" &&
      /^(?:3\.5|5\.5|[4-9]|1[0-3]|news)$/.test(event.phase)
    ) sanitized.phase = event.phase;
  } else if (["frame_gap", "frame_call"].includes(event.type)) {
    copyNumber(
      sanitized,
      event,
      "durationMs",
      event.type === "frame_gap" ? 250 : 100,
      120_000,
      1,
    );
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
    if (
      event.type === "frame_gap" &&
      typeof event.phase === "string" &&
      /^(?:3\.5|5\.5|[4-9]|1[0-3]|news)$/.test(event.phase)
    ) sanitized.phase = event.phase;
    if (sanitized.durationMs === undefined) return null;
  } else if (event.type === "main_thread_stall") {
    copyNumber(sanitized, event, "durationMs", 4_000, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "npcStage", performanceNpcStages);
    copyEnum(sanitized, event, "movie", performanceNpcMovies);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
  } else if (event.type === "frame_stage") {
    copyEnum(sanitized, event, "stage", performanceFrameStages);
    copyNumber(sanitized, event, "durationMs", 100, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
    if (!sanitized.stage || sanitized.durationMs === undefined) return null;
  } else if (event.type === "interval_phase") {
    copyEnum(sanitized, event, "phase", performanceIntervalPhases);
    copyNumber(sanitized, event, "durationMs", 50, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
    if (!sanitized.phase || sanitized.durationMs === undefined) return null;
  } else if (event.type === "interval_function") {
    copyEnum(sanitized, event, "callback", performanceIntervalFunctions);
    copyNumber(sanitized, event, "durationMs", 50, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
    if (!sanitized.callback || sanitized.durationMs === undefined) return null;
  } else if (event.type === "actor_animation") {
    copyEnum(
      sanitized,
      event,
      "operation",
      performanceActorAnimationOperations,
    );
    copyNumber(sanitized, event, "controls", 0, 256);
    copyNumber(sanitized, event, "lookupMs", 0, 120_000);
    copyNumber(sanitized, event, "controlMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyEnum(sanitized, event, "command", performanceScriptCommands);
    copyNumber(sanitized, event, "step", 0, 2_048);
    if (
      !sanitized.operation ||
      sanitized.controls === undefined ||
      sanitized.lookupMs === undefined ||
      sanitized.controlMs === undefined
    ) return null;
  } else if (event.type === "audio_bank") {
    copyEnum(sanitized, event, "bank", performanceAudioBanks);
    copyEnum(sanitized, event, "stage", performanceAudioBankStages);
    copyEnum(sanitized, event, "error", performanceAudioBankErrors);
    copyNumber(sanitized, event, "fetchMs", 0, 120_000);
    copyNumber(sanitized, event, "parseMs", 0, 120_000);
    copyNumber(sanitized, event, "materializeMs", 0, 120_000);
    copyNumber(sanitized, event, "sounds", 0, 256);
    if (typeof event.metadataPublished === "boolean") {
      sanitized.metadataPublished = event.metadataPublished;
    }
    if (!sanitized.bank || !sanitized.stage) return null;
  } else if (event.type === "audio_lifecycle") {
    copyEnum(
      sanitized,
      event,
      "stage",
      performanceAudioLifecycleStages,
    );
    copyEnum(
      sanitized,
      event,
      "trigger",
      performanceAudioLifecycleTriggers,
    );
    copyEnum(
      sanitized,
      event,
      "label",
      performanceAudioContextLabels,
    );
    copyEnum(
      sanitized,
      event,
      "contextState",
      performanceAudioContextStates,
    );
    copyEnum(sanitized, event, "state", performanceStates);
    for (const key of [
      "contextId",
      "attempted",
      "recovered",
      "failed",
    ]) copyNumber(sanitized, event, key, 0, 64);
    if (typeof event.gesture === "boolean") {
      sanitized.gesture = event.gesture;
    }
    if (typeof event.needsGestureRetry === "boolean") {
      sanitized.needsGestureRetry = event.needsGestureRetry;
    }
    if (!sanitized.stage) return null;
    if (
      sanitized.stage === "context_registered" &&
      (
        !sanitized.label ||
        !sanitized.contextState ||
        sanitized.contextId === undefined
      )
    ) return null;
    if (
      sanitized.stage === "resume" &&
      (
        !sanitized.trigger ||
        sanitized.attempted === undefined ||
        sanitized.recovered === undefined ||
        sanitized.failed === undefined
      )
    ) return null;
  } else if (event.type === "battle_build") {
    copyEnum(sanitized, event, "track", performanceBattleTracks);
    copyEnum(sanitized, event, "stage", performanceBattleBuildStages);
    copyNumber(sanitized, event, "attacks", 0, 64);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (
      !sanitized.track ||
      !sanitized.stage ||
      sanitized.attacks === undefined ||
      sanitized.durationMs === undefined
    ) return null;
  } else if (event.type === "battle_stage") {
    copyEnum(sanitized, event, "stage", performanceBattleStages);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.stage || sanitized.durationMs === undefined) return null;
  } else if (event.type === "battle_asset") {
    copyEnum(sanitized, event, "kind", performanceBattleAssetKinds);
    copyPerformanceToken(sanitized, event, "asset");
    copyEnum(sanitized, event, "status", performanceBattleAssetStatuses);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (
      !sanitized.kind ||
      !sanitized.asset ||
      !sanitized.status ||
      sanitized.durationMs === undefined
    ) return null;
  } else if (event.type === "battle_sound") {
    copyPerformanceToken(sanitized, event, "sound");
    copyEnum(
      sanitized,
      event,
      "requestStatus",
      performanceBattleSoundRequestStatuses,
    );
    copyEnum(
      sanitized,
      event,
      "lookupStatus",
      performanceBattleSoundLookupStatuses,
    );
    copyNumber(sanitized, event, "requestCount", 1, 10_000);
    copyNumber(sanitized, event, "resolveMs", 0, 120_000);
    copyNumber(sanitized, event, "managerMs", 0, 120_000);
    copyNumber(sanitized, event, "totalMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (
      !sanitized.sound ||
      !sanitized.requestStatus ||
      !sanitized.lookupStatus ||
      sanitized.requestCount === undefined ||
      sanitized.resolveMs === undefined ||
      sanitized.managerMs === undefined ||
      sanitized.totalMs === undefined
    ) return null;
  } else if (event.type === "animation_bind") {
    copyEnum(sanitized, event, "actor", performanceActorCategories);
    copyPerformanceToken(sanitized, event, "animation");
    copyNumber(sanitized, event, "controls", 0, 256);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (
      !sanitized.actor ||
      !sanitized.animation ||
      sanitized.controls === undefined ||
      sanitized.durationMs === undefined
    ) return null;
  } else if (event.type === "actor_interval_build") {
    copyEnum(sanitized, event, "actor", performanceActorCategories);
    copyPerformanceToken(sanitized, event, "animation");
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (
      !sanitized.actor ||
      !sanitized.animation ||
      sanitized.durationMs === undefined
    ) return null;
  } else if (event.type === "npc_movie") {
    copyEnum(sanitized, event, "stage", performanceNpcStages);
    copyEnum(sanitized, event, "movie", performanceNpcMovies);
    copyNumber(sanitized, event, "elapsedMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.stage || !sanitized.movie) return null;
  } else if (event.type === "gc_pause") {
    copyNumber(sanitized, event, "generation", 0, 2);
    copyNumber(sanitized, event, "durationMs", 50, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (sanitized.generation === undefined || !sanitized.durationMs) return null;
  } else if (event.type === "script_step") {
    copyEnum(sanitized, event, "stage", performanceScriptStages);
    copyEnum(sanitized, event, "script", performanceScripts);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.stage || !sanitized.script ||
        sanitized.durationMs === undefined) return null;
  } else if (event.type === "avatar_setup") {
    copyEnum(sanitized, event, "stage", performanceAvatarSetupStages);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.stage || sanitized.durationMs === undefined) return null;
  } else if (event.type === "interface_setup") {
    copyEnum(sanitized, event, "stage", performanceInterfaceSetupStages);
    copyNumber(sanitized, event, "durationMs", 0, 120_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.stage || sanitized.durationMs === undefined) return null;
  } else if (event.type === "runtime_error") {
    copyEnum(sanitized, event, "category", performanceErrorCategories);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.category) return null;
  } else if (event.type === "state") {
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.state) return null;
  } else if (event.type === "toon_entry") {
    copyEnum(sanitized, event, "stage", performanceToonEntryStages);
    copyNumber(sanitized, event, "durationMs", 0, 30 * 60 * 1_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (!sanitized.stage || sanitized.durationMs === undefined) return null;
  } else if (event.type === "lifecycle") {
    copyEnum(
      sanitized,
      event,
      "visibility",
      performanceLifecycleVisibilities,
    );
    copyNumber(sanitized, event, "awayMs", 0, 24 * 60 * 60 * 1_000);
    copyEnum(sanitized, event, "state", performanceStates);
    if (
      !sanitized.visibility ||
      sanitized.awayMs === undefined
    ) return null;
  }

  return sanitized;
}

async function receivePerformance(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    production &&
    !verifyBootstrapSession(request.headers, sessionSecret)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  if (production && request.headers.origin !== publicOrigin) {
    json(response, 403, { ok: false });
    return;
  }
  if (!String(request.headers["content-type"] ?? "").startsWith(
    "application/json",
  )) {
    json(response, 415, { ok: false });
    return;
  }
  const contentLength = Number(request.headers["content-length"]);
  if (
    Number.isFinite(contentLength) &&
    contentLength > MAX_PERFORMANCE_BODY_BYTES
  ) {
    request.resume();
    json(response, 413, { ok: false });
    return;
  }

  const session = performanceSessionId(request);
  if (!consumeWindow(
    performanceWindows,
    session,
    PERFORMANCE_WINDOW_MS,
    PERFORMANCE_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }

  let body;
  try {
    body = await readJsonBody(request, MAX_PERFORMANCE_BODY_BYTES);
  } catch {
    if (!response.headersSent) json(response, 400, { ok: false });
    return;
  }
  if (
    !body ||
    typeof body !== "object" ||
    !Array.isArray(body.events) ||
    body.events.length < 1 ||
    body.events.length > MAX_PERFORMANCE_EVENTS
  ) {
    json(response, 400, { ok: false });
    return;
  }
  const events = body.events.map(sanitizePerformanceEvent);
  if (events.some((event) => event === null)) {
    json(response, 400, { ok: false });
    return;
  }

  console.log(`[BrowserPerformance] ${JSON.stringify({
    receivedAt: new Date().toISOString(),
    session,
    events,
  })}`);
  json(response, 202, { ok: true });
}

async function verifyTurnstile(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (request.headers.origin !== publicOrigin) {
    json(response, 403, { ok: false });
    return;
  }

  const ip = requestIp(request);
  if (!consumeVerifyAttempt(ip)) {
    json(response, 429, { ok: false });
    return;
  }

  let body;
  try {
    body = await readJsonBody(request);
  } catch {
    if (!response.headersSent) json(response, 400, { ok: false });
    return;
  }
  if (
    !body ||
    typeof body.token !== "string" ||
    body.token.length < 20 ||
    body.token.length > 4_096
  ) {
    json(response, 400, { ok: false });
    return;
  }

  let result;
  try {
    const turnstileResponse = await fetch(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          secret: turnstileSecretKey,
          response: body.token,
          remoteip: ip,
        }),
        signal: AbortSignal.timeout(8_000),
      },
    );
    if (!turnstileResponse.ok) throw new Error("Turnstile rejected the request");
    result = await turnstileResponse.json();
  } catch {
    json(response, 503, { ok: false });
    return;
  }

  if (
    result.success !== true ||
    result.hostname !== expectedHostname ||
    result.action !== "bootstrap"
  ) {
    json(response, 403, { ok: false });
    return;
  }

  const sessionValue = createBootstrapSession(sessionSecret);
  const sessionKey = createHash("sha256")
    .update(sessionValue)
    .digest("hex")
    .slice(0, 32);
  const cookie = bootstrapCookieHeader(sessionValue);
  json(
    response,
    200,
    {
      ok: true,
      runtime: runtimeChallengeFor(request, sessionKey),
    },
    { "Set-Cookie": cookie },
  );
}

async function issueRuntimeChallenge(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    !production ||
    !verifyBootstrapSession(request.headers, sessionSecret)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  if (request.headers.origin !== publicOrigin) {
    json(response, 403, { ok: false });
    return;
  }
  const sessionKey = bootstrapSessionDigest(request.headers);
  if (!consumeWindow(
    runtimeChallengeWindows,
    sessionKey,
    RUNTIME_CHALLENGE_WINDOW_MS,
    RUNTIME_CHALLENGE_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }
  try {
    const { value } = await readJsonBodyWithRaw(
      request,
      MAX_RUNTIME_BODY_BYTES,
    );
    if (
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      Object.keys(value).length !== 0
    ) {
      json(response, 400, { ok: false });
      return;
    }
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  try {
    json(response, 200, runtimeChallengeFor(request, sessionKey));
  } catch {
    json(response, 503, { ok: false });
  }
}

async function issueRuntimeAuthorization(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    !production ||
    !verifyBootstrapSession(request.headers, sessionSecret)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  if (request.headers.origin !== publicOrigin) {
    json(response, 403, { ok: false });
    return;
  }
  const sessionKey = bootstrapSessionDigest(request.headers);
  if (!consumeWindow(
    runtimeAuthorizeWindows,
    sessionKey,
    RUNTIME_AUTHORIZE_WINDOW_MS,
    RUNTIME_AUTHORIZE_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }
  let body;
  try {
    body = await readJsonBody(request, MAX_RUNTIME_BODY_BYTES);
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  if (
    !body ||
    typeof body.challengeToken !== "string" ||
    !body.publicKey ||
    typeof body.signature !== "string"
  ) {
    json(response, 400, { ok: false });
    return;
  }
  const registration = verifyRuntimeRegistration({
    challengeToken: body.challengeToken,
    publicKey: body.publicKey,
    signature: body.signature,
    secret: runtimeAuthoritySecret,
    context: runtimeContext(request, sessionKey),
  });
  if (
    !registration ||
    !consumeOneUse(
      runtimeChallengeUses,
      registration.challengeId,
      registration.expiresAt,
    )
  ) {
    json(response, 403, { ok: false });
    return;
  }
  try {
    json(response, 200, createRuntimeAuthorization({
      secret: runtimeAuthoritySecret,
      publicKey: registration.publicKey,
      ...runtimeContext(request, sessionKey),
    }));
  } catch {
    json(response, 503, { ok: false });
  }
}

async function issueWorldCapabilities(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    production &&
    !verifyBootstrapSession(request.headers, sessionSecret)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  if (production && request.headers.origin !== publicOrigin) {
    json(response, 403, { ok: false });
    return;
  }
  let body;
  let raw;
  try {
    ({ value: body, raw } = await readJsonBodyWithRaw(
      request,
      MAX_RUNTIME_BODY_BYTES,
    ));
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  const proof = verifyRuntimeProof(
    request,
    "/api/runtime/world-capabilities",
    raw,
  );
  if (!proof) {
    json(response, 403, { ok: false });
    return;
  }
  if (
    !body ||
    !Array.isArray(body.zoneIds) ||
    body.zoneIds.length < 1 ||
    body.zoneIds.length > MAX_WORLD_CAPABILITY_ZONES ||
    body.zoneIds.some((zoneId) => (
      !Number.isSafeInteger(zoneId) || zoneId < 0 || zoneId > 99_999_999
    )) ||
    new Set(body.zoneIds).size !== body.zoneIds.length
  ) {
    json(response, 400, { ok: false });
    return;
  }
  if (!consumeWindow(
    worldCapabilityWindows,
    proof.authorizationId,
    WORLD_CAPABILITY_WINDOW_MS,
    WORLD_CAPABILITY_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }
  const context = runtimeContext(request);
  try {
    let state = null;
    if (typeof body.stateToken === "string") {
      state = verifyGameSessionState({
        secret: gameAuthoritySecret,
        stateToken: body.stateToken,
        release: proof.release,
        thumbprint: proof.thumbprint,
      });
      if (!state) {
        json(response, 403, { ok: false });
        return;
      }
    }
    const capabilities = body.zoneIds.map((zoneId) => {
      const requiredPhases = requiredPhasesForZone(zoneId);
      const composition = worldCompositionForZone(zoneId, requiredPhases);
      return {
        ...createWorldCapability({
        secret: production ? runtimeAuthoritySecret : gameAuthoritySecret,
        authorizationId: proof.authorizationId,
        zoneId,
          requiredPhases: composition.requiredPhases,
          contentEpoch: composition.epoch,
          compositionDigest: composition.digest,
          forensicMarker: state?.m ?? "",
        ...context,
        }),
        composition,
      };
    });
    json(response, 200, {
      version: RUNTIME_AUTHORITY_PROTOCOL,
      release: context.release,
      capabilities,
    });
  } catch {
    json(response, 503, { ok: false });
  }
}

async function issueGameSession(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    production &&
    (!verifyBootstrapSession(request.headers, sessionSecret) ||
      request.headers.origin !== publicOrigin)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  let body;
  let raw;
  try {
    ({ value: body, raw } = await readJsonBodyWithRaw(
      request,
      MAX_RUNTIME_BODY_BYTES,
    ));
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  const proof = verifyRuntimeProof(request, "/api/runtime/game-session", raw);
  if (
    !proof ||
    !body ||
    typeof body !== "object" ||
    Array.isArray(body) ||
    Object.keys(body).length !== 0
  ) {
    json(response, 403, { ok: false });
    return;
  }
  if (!consumeWindow(
    gameSessionWindows,
    proof.thumbprint,
    GAME_SESSION_WINDOW_MS,
    GAME_SESSION_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }
  try {
    json(response, 200, createGameSessionState({
      secret: gameAuthoritySecret,
      release: proof.release,
      thumbprint: proof.thumbprint,
    }));
  } catch {
    json(response, 503, { ok: false });
  }
}

async function issueGameTransition(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    production &&
    (!verifyBootstrapSession(request.headers, sessionSecret) ||
      request.headers.origin !== publicOrigin)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  let body;
  let raw;
  try {
    ({ value: body, raw } = await readJsonBodyWithRaw(
      request,
      MAX_RUNTIME_BODY_BYTES,
    ));
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  const proof = verifyRuntimeProof(
    request,
    "/api/runtime/game-transitions",
    raw,
  );
  if (
    !proof ||
    !body ||
    typeof body.stateToken !== "string" ||
    typeof body.action !== "string" ||
    !body.target
  ) {
    json(response, 403, { ok: false });
    return;
  }
  const state = verifyGameSessionState({
    secret: gameAuthoritySecret,
    stateToken: body.stateToken,
    release: proof.release,
    thumbprint: proof.thumbprint,
  });
  if (!state) {
    json(response, 409, { ok: false });
    return;
  }
  if (!consumeWindow(
    gameTransitionWindows,
    state.sid,
    GAME_TRANSITION_WINDOW_MS,
    GAME_TRANSITION_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }
  try {
    json(response, 200, createGameTransitionCapability({
      secret: gameAuthoritySecret,
      stateToken: body.stateToken,
      release: proof.release,
      thumbprint: proof.thumbprint,
      action: body.action,
      target: body.target,
    }));
  } catch {
    json(response, 400, { ok: false });
  }
}

async function issueFeatureModules(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    production &&
    (!verifyBootstrapSession(request.headers, sessionSecret) ||
      request.headers.origin !== publicOrigin)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  let body;
  let raw;
  try {
    ({ value: body, raw } = await readJsonBodyWithRaw(
      request,
      MAX_RUNTIME_BODY_BYTES,
    ));
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  const proof = verifyRuntimeProof(
    request,
    "/api/runtime/feature-modules",
    raw,
  );
  if (
    !proof ||
    !body ||
    typeof body.stateToken !== "string" ||
    !Array.isArray(body.moduleIds) ||
    body.moduleIds.length < 1 ||
    body.moduleIds.length > MAX_FEATURE_MODULE_BATCH ||
    new Set(body.moduleIds).size !== body.moduleIds.length
  ) {
    json(response, 403, { ok: false });
    return;
  }
  const state = verifyGameSessionState({
    secret: gameAuthoritySecret,
    stateToken: body.stateToken,
    release: proof.release,
    thumbprint: proof.thumbprint,
  });
  if (!state) {
    json(response, 409, { ok: false });
    return;
  }
  const definitions = body.moduleIds.map((moduleId) => ({
    moduleId,
    module: featureModuleById(moduleId),
  }));
  if (definitions.some(({ moduleId, module }) => (
    typeof moduleId !== "string" || module === null
  ))) {
    json(response, 400, { ok: false });
    return;
  }
  if (!consumeWindow(
    featureModuleWindows,
    state.sid,
    FEATURE_MODULE_WINDOW_MS,
    FEATURE_MODULE_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }
  try {
    const modules = definitions.map(({ moduleId, module }) =>
      createSignedFeatureModule({
        secret: gameAuthoritySecret,
        stateToken: body.stateToken,
        release: proof.release,
        thumbprint: proof.thumbprint,
        moduleId,
        module,
      })
    );
    json(response, 200, {
      version: GAME_AUTHORITY_PROTOCOL,
      release: proof.release,
      modules,
    });
  } catch {
    json(response, 503, { ok: false });
  }
}

async function issueAssetTickets(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    production &&
    !verifyBootstrapSession(request.headers, sessionSecret)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  if (production && request.headers.origin !== publicOrigin) {
    json(response, 403, { ok: false });
    return;
  }

  const session = privateAssetSessionId(request);
  if (!consumeWindow(
    assetTicketWindows,
    session,
    ASSET_TICKET_WINDOW_MS,
    ASSET_TICKET_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }

  let body;
  let raw;
  try {
    ({ value: body, raw } = await readJsonBodyWithRaw(
      request,
      MAX_ASSET_TICKET_BODY_BYTES,
    ));
  } catch (error) {
    json(
      response,
      error?.message === "request body too large" ? 413 : 400,
      { ok: false },
    );
    return;
  }
  const proof = verifyRuntimeProof(request, "/api/assets/tickets", raw);
  if (!proof) {
    json(response, 403, { ok: false });
    return;
  }
  if (
    !body ||
    !Array.isArray(body.names) ||
    body.names.length < 1 ||
    body.names.length > MAX_ASSET_TICKET_BATCH ||
    body.names.some((name) => (
      typeof name !== "string" || !PRIVATE_ASSET_NAME.test(name)
    )) ||
    new Set(body.names).size !== body.names.length
  ) {
    json(response, 400, { ok: false });
    return;
  }

  if (!r2AssetStore) {
    json(response, 200, { version: 1, tickets: [] });
    return;
  }

  try {
    const tickets = await Promise.all(body.names.map(async (name) => {
      const url = await r2AssetStore.redirect(
        `/${name}`,
        "GET",
        request.headers["accept-encoding"],
        session,
        proof.authorizationId,
      );
      if (!url) throw new Error("unknown asset");
      return {
        name,
        url,
        authority: proof.authorizationId,
      };
    }));
    json(
      response,
      200,
      {
        version: production ? 2 : 1,
        release: runtimeRelease(),
        tickets,
      },
      { Vary: "Accept-Encoding" },
    );
  } catch (error) {
    if (error?.message === "unknown asset") {
      json(response, 400, { ok: false });
      return;
    }
    console.error(`[R2Assets] Batch ticket signing failed: ${error?.name ?? "Error"}`);
    json(response, 503, { ok: false });
  }
}

async function issueGatewayLease(request, response) {
  if (request.method !== "POST") {
    json(response, 405, { ok: false }, { Allow: "POST" });
    return;
  }
  if (
    !production ||
    !verifyBootstrapSession(request.headers, sessionSecret)
  ) {
    json(response, 401, { ok: false });
    return;
  }
  if (
    request.headers.origin !== publicOrigin ||
    request.headers["sec-fetch-site"] !== "same-origin"
  ) {
    json(response, 403, { ok: false });
    return;
  }

  let body;
  let raw;
  try {
    ({ value: body, raw } = await readJsonBodyWithRaw(
      request,
      MAX_RUNTIME_BODY_BYTES,
    ));
  } catch {
    json(response, 400, { ok: false });
    return;
  }
  if (
    !body ||
    typeof body !== "object" ||
    Array.isArray(body) ||
    Object.keys(body).length !== 0
  ) {
    json(response, 400, { ok: false });
    return;
  }
  const proof = verifyRuntimeProof(request, "/api/gateway/lease", raw);
  if (!proof) {
    json(response, 403, { ok: false });
    return;
  }

  const sessionKey = bootstrapSessionDigest(request.headers);
  if (!consumeWindow(
    gatewayLeaseWindows,
    sessionKey,
    GATEWAY_LEASE_WINDOW_MS,
    GATEWAY_LEASE_LIMIT,
  )) {
    json(response, 429, { ok: false });
    return;
  }

  const userAgent = String(request.headers["user-agent"] ?? "").slice(0, 1_024);
  if (!userAgent) {
    json(response, 400, { ok: false });
    return;
  }
  const issuedAt = Date.now();
  const resume = createGatewayResumeToken();
  try {
    const lease = createGatewayLease({
      secret: gatewayLeaseSecret,
      sessionKey,
      resumeToken: resume,
      clientAddress: requestIp(request),
      userAgent,
      origin: publicOrigin,
      authorityKey: proof.authorizationId,
      now: issuedAt,
    });
    json(response, 200, {
      version: 2,
      resume,
      lease,
      authority: proof.authorizationId,
      expiresAt:
        issuedAt + DEFAULT_GATEWAY_LEASE_TTL_SECONDS * 1_000,
    });
  } catch {
    json(response, 503, { ok: false });
  }
}

function isPublicBootstrapPath(pathname) {
  return new Set([
    "/",
    "/favicon.ico",
    "/index.html",
    "/app.js",
    "/runtime-authority.js",
    "/welcome-gate.js",
    "/secure-asset-cache.js",
    "/short-audio-banks.js",
    "/styles.css",
    "/resources/phase_3/maps/loading_bg_clouds.png",
    "/resources/phase_3/maps/toontown-logo.png",
    "/toontownbrowserogimage2.png",
  ]).has(pathname);
}

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

function serveFile(request, response, pathname, versionedAsset = false) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    response.writeHead(400).end("Bad request");
    return;
  }
  const relative = normalize(decoded).replace(/^[/\\]+/, "");
  let file = resolve(join(root, relative || "index.html"));

  if (file !== root && !file.startsWith(`${root}/`)) {
    response.writeHead(403).end("Forbidden");
    return;
  }

  try {
    if (statSync(file).isDirectory()) file = join(file, "index.html");
  } catch {
    file = assetFallbacks(relative)
      .map((candidate) => safeFile(candidate, resourcesRoot))
      .find(Boolean);
  }

  try {
    if (!file) throw new Error("not found");
    const contentType = mime[extname(file)] ?? "application/octet-stream";
    let responseFile = file;
    let contentEncoding;
    const gzipFile = `${file}.gz`;
    let hasGzipSidecar = false;
    try {
      hasGzipSidecar = statSync(gzipFile).isFile();
    } catch {
      hasGzipSidecar = false;
    }
    if (
      hasGzipSidecar &&
      acceptsEncoding(request.headers["accept-encoding"], "gzip")
    ) {
      responseFile = gzipFile;
      contentEncoding = "gzip";
    }
    const fileStat = statSync(responseFile);
    const encodingTag = contentEncoding ? `-${contentEncoding}` : "";
    const etag = `W/\"${fileStat.size.toString(16)}-${Math.trunc(fileStat.mtimeMs).toString(16)}${encodingTag}\"`;
    const bootstrapAsset = isPublicBootstrapPath(pathname);
    const cacheControl =
      bootstrapAsset || extname(file) === ".html"
        ? "no-store"
        : versionedAsset
          ? "private, max-age=31536000, immutable"
          : "private, no-cache, must-revalidate";
    const representationHeaders = {
      ETag: etag,
      "Cache-Control": cacheControl,
      ...(hasGzipSidecar ? { Vary: "Accept-Encoding" } : {}),
      ...(contentEncoding ? { "Content-Encoding": contentEncoding } : {}),
    };
    if (request.headers["if-none-match"] === etag && !bootstrapAsset) {
      response.writeHead(304, representationHeaders);
      response.end();
      return;
    }
    const headers = {
      "Content-Type": contentType,
      "Content-Length": fileStat.size,
      "X-Content-Type-Options": "nosniff",
      ...representationHeaders,
    };
    response.writeHead(200, headers);
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    createReadStream(responseFile).pipe(response);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
}

export function createWebServer() {
  return createServer(async (request, response) => {
    let url;
    try {
      url = new URL(request.url, "http://localhost");
    } catch {
      response.writeHead(400).end("Bad request");
      return;
    }
    const pathname = url.pathname;

    if (pathname === "/api/bootstrap/config") {
      json(response, 200, {
        required: production,
        authorityRequired: production,
        authorityProtocol: RUNTIME_AUTHORITY_PROTOCOL,
        release: runtimeRelease(),
        ...(production ? { siteKey: turnstileSiteKey } : {}),
      });
      return;
    }
    if (pathname === "/api/bootstrap/session") {
      const valid =
        !production ||
        verifyBootstrapSession(request.headers, sessionSecret);
      json(response, 200, {
        valid,
        ...(production && valid
          ? {
            runtime: runtimeChallengeFor(
              request,
              bootstrapSessionDigest(request.headers),
            ),
          }
          : {}),
      });
      return;
    }
    if (pathname === "/api/bootstrap/verify") {
      if (!production) {
        json(response, 404, { ok: false });
      } else {
        await verifyTurnstile(request, response);
      }
      return;
    }
    if (pathname === "/api/runtime/challenge") {
      await issueRuntimeChallenge(request, response);
      return;
    }
    if (pathname === "/api/runtime/authorize") {
      await issueRuntimeAuthorization(request, response);
      return;
    }
    if (pathname === "/api/runtime/world-capabilities") {
      await issueWorldCapabilities(request, response);
      return;
    }
    if (pathname === "/api/runtime/game-session") {
      await issueGameSession(request, response);
      return;
    }
    if (pathname === "/api/runtime/game-transitions") {
      await issueGameTransition(request, response);
      return;
    }
    if (pathname === "/api/runtime/feature-modules") {
      await issueFeatureModules(request, response);
      return;
    }
    if (pathname === "/api/performance") {
      await receivePerformance(request, response);
      return;
    }
    if (pathname === "/api/assets/tickets") {
      await issueAssetTickets(request, response);
      return;
    }
    if (pathname === "/api/gateway/lease") {
      await issueGatewayLease(request, response);
      return;
    }

    // The private R2 manifest is server configuration, never a web asset.
    if (pathname === "/r2-assets.json") {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    if (!["GET", "HEAD"].includes(request.method)) {
      response.writeHead(405, { Allow: "GET, HEAD" }).end("Method not allowed");
      return;
    }
    if (
      production &&
      !isPublicBootstrapPath(pathname) &&
      !verifyBootstrapSession(request.headers, sessionSecret)
    ) {
      json(response, 401, { ok: false });
      return;
    }
    if (
      production &&
      r2AssetStore &&
      PRIVATE_ASSET_NAME.test(pathname.slice(1))
    ) {
      json(response, 401, {
        ok: false,
        error: "opaque asset ticket required",
      });
      return;
    }
    // Gzip sidecars are an internal representation selected from the base
    // asset request. Never let a verified client bypass the private gateway
    // by spelling the physical .gz filename directly.
    if (/\.(?:data|wasm)\.gz$/.test(pathname)) {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }
    const versionedAsset = /^[a-f0-9]{16,64}$/.test(
      url.searchParams.get("v") ?? "",
    );
    if (r2AssetStore) {
      try {
        const location = await r2AssetStore.redirect(
          pathname,
          request.method,
          request.headers["accept-encoding"],
          privateAssetSessionId(request),
          "0".repeat(32),
        );
        if (location) {
          response.writeHead(307, {
            Location: location,
            "Cache-Control": "private, no-store",
            Vary: "Accept-Encoding",
            "X-Content-Type-Options": "nosniff",
          });
          response.end();
          return;
        }
      } catch (error) {
        console.error(`[R2Assets] Signing failed: ${error?.name ?? "Error"}`);
        json(response, 503, { ok: false });
        return;
      }
    }
    serveFile(request, response, pathname, versionedAsset);
  });
}

const server = createWebServer();
server.listen(port, "127.0.0.1", () => {
  console.log(`Toontown Browser: http://127.0.0.1:${port}`);
  if (r2AssetStore) {
    console.log(
      `[R2Assets] Serving ${r2AssetStore.assetCount} heavy assets through ${r2AssetStore.deliveryMode} from private release ${r2AssetStore.release.slice(0, 12)}`,
    );
  }
});
