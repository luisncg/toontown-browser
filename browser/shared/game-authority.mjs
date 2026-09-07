import {
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

export const GAME_AUTHORITY_PROTOCOL = 2;
export const GAME_CONTENT_EPOCH = "gameplay-v2";
export const GAME_STATE_TTL_SECONDS = 6 * 60 * 60;
export const GAME_TRANSITION_TTL_SECONDS = 45;

const STATE_PREFIX = "gs2";
const TRANSITION_PREFIX = "gt2";
const FEATURE_PREFIX = "gf2";
const SECRET_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const HEX_32_PATTERN = /^[a-f0-9]{32}$/;
const HEX_64_PATTERN = /^[a-f0-9]{64}$/;
const MARKER_PATTERN = /^[A-Za-z0-9_-]{22}$/;
const TOKEN_PART_PATTERN = /^[A-Za-z0-9_-]+$/;
const ACTIONS = new Set([
  "battle.attack",
  "building.board",
  "door.enter",
  "estate.enter",
  "fishing.cast",
  "fishing.enter",
  "fish-bingo.claim",
  "npc.interact",
  "catalog.purchase",
  "boss.reward",
  "minigame.finish",
  "race.finish",
  "trolley.board",
]);

function decodeSecret(value) {
  if (typeof value !== "string" || !SECRET_PATTERN.test(value)) {
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

function signingKey(secret) {
  return createHmac("sha256", decodeSecret(secret))
    .update("toontown-browser-game-authority-signing-key-v1", "utf8")
    .digest();
}

function encodePayload(value) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

function seal(prefix, payload, secret) {
  const encoded = encodePayload(payload);
  const signed = `${prefix}.${encoded}`;
  const signature = createHmac("sha256", signingKey(secret))
    .update(signed, "utf8")
    .digest("base64url");
  return `${signed}.${signature}`;
}

function open(prefix, token, secret) {
  if (typeof token !== "string" || token.length < 80 || token.length > 4_096) {
    return null;
  }
  const parts = token.split(".");
  if (
    parts.length !== 3 ||
    parts[0] !== prefix ||
    !TOKEN_PART_PATTERN.test(parts[1] ?? "") ||
    !TOKEN_PART_PATTERN.test(parts[2] ?? "")
  ) {
    return null;
  }
  let supplied;
  let payloadBytes;
  try {
    supplied = Buffer.from(parts[2], "base64url");
    payloadBytes = Buffer.from(parts[1], "base64url");
  } catch {
    return null;
  }
  if (
    supplied.length !== 32 ||
    supplied.toString("base64url") !== parts[2] ||
    payloadBytes.toString("base64url") !== parts[1]
  ) {
    return null;
  }
  const expected = createHmac("sha256", signingKey(secret))
    .update(`${parts[0]}.${parts[1]}`, "utf8")
    .digest();
  if (!timingSafeEqual(supplied, expected)) return null;
  try {
    return JSON.parse(payloadBytes.toString("utf8"));
  } catch {
    return null;
  }
}

function validLifetime(payload, now, maximumSeconds) {
  const current = Math.floor(now / 1_000);
  return (
    Number.isSafeInteger(payload?.iat) &&
    Number.isSafeInteger(payload?.exp) &&
    payload.iat <= current + 60 &&
    payload.exp >= current - 60 &&
    payload.exp > payload.iat &&
    payload.exp - payload.iat <= maximumSeconds
  );
}

function integer(value, minimum, maximum, label) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function object(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Transition target is invalid");
  }
  return value;
}

export function normalizeGameTransitionTarget(action, target) {
  if (!ACTIONS.has(action)) {
    throw new Error("Game transition action is invalid");
  }
  const value = object(target);
  if (action === "battle.attack") {
    return Object.freeze({
      battle: integer(value.battle, 1, 0xffff_ffff, "Battle id"),
      track: integer(value.track, -128, 127, "Battle track"),
      level: integer(value.level, -128, 127, "Battle level"),
      target: integer(
        value.target,
        -0x8000_0000,
        0x7fff_ffff,
        "Battle target",
      ),
    });
  }
  if (action === "fish-bingo.claim") {
    return Object.freeze({
      manager: integer(value.manager, 1, 0xffff_ffff, "Bingo manager id"),
      card: integer(value.card, 0, 0xffff, "Bingo card id"),
    });
  }
  if (action === "estate.enter") {
    return Object.freeze({
      manager: integer(value.manager, 1, 0xffff_ffff, "Estate manager id"),
      owner: integer(value.owner, 1, 0xffff_ffff, "Estate owner id"),
    });
  }
  if (action === "fishing.cast" || action === "fishing.enter") {
    return Object.freeze({
      spot: integer(value.spot, 1, 0xffff_ffff, "Fishing spot id"),
      zone: integer(value.zone, 1, 0xffff_ffff, "Fishing zone"),
    });
  }
  if (action === "trolley.board") {
    return Object.freeze({
      trolley: integer(value.trolley, 1, 0xffff_ffff, "Trolley id"),
      zone: integer(value.zone, 1, 0xffff_ffff, "Trolley zone"),
    });
  }
  if (action === "door.enter") {
    return Object.freeze({
      door: integer(value.door, 1, 0xffff_ffff, "Door id"),
      zone: integer(value.zone, 1, 0xffff_ffff, "Door zone"),
    });
  }
  if (action === "building.board") {
    return Object.freeze({
      elevator: integer(value.elevator, 1, 0xffff_ffff, "Elevator id"),
      zone: integer(value.zone, 1, 0xffff_ffff, "Elevator zone"),
    });
  }
  if (action === "npc.interact") {
    return Object.freeze({
      npc: integer(value.npc, 1, 0xffff_ffff, "NPC id"),
      zone: integer(value.zone, 1, 0xffff_ffff, "NPC zone"),
    });
  }
  if (action === "catalog.purchase") {
    return Object.freeze({
      phone: integer(value.phone, 1, 0xffff_ffff, "Phone id"),
      context: integer(value.context, 0, 0xffff_ffff, "Catalog context"),
      gift: integer(value.gift, 0, 1, "Catalog gift flag"),
    });
  }
  if (action === "boss.reward") {
    return Object.freeze({
      boss: integer(value.boss, 1, 0xffff_ffff, "Boss id"),
      reward: integer(value.reward, 0, 0xffff_ffff, "Boss reward id"),
    });
  }
  if (action === "minigame.finish") {
    return Object.freeze({
      game: integer(value.game, 1, 0xffff_ffff, "Minigame id"),
    });
  }
  if (action === "race.finish") {
    return Object.freeze({
      race: integer(value.race, 1, 0xffff_ffff, "Race id"),
      laps: integer(value.laps, 1, 0x7f, "Race lap count"),
    });
  }
  throw new Error("Game transition action is invalid");
}

function validStatePayload(payload, {
  now,
  release,
  thumbprint,
  officialBuildId,
} = {}) {
  return (
    payload?.v === GAME_AUTHORITY_PROTOCOL &&
    payload?.t === "state" &&
    HEX_64_PATTERN.test(payload.pk ?? "") &&
    HEX_64_PATTERN.test(payload.r ?? "") &&
    HEX_32_PATTERN.test(payload.sid ?? "") &&
    HEX_32_PATTERN.test(payload.st ?? "") &&
    HEX_32_PATTERN.test(payload.ob ?? "") &&
    MARKER_PATTERN.test(payload.m ?? "") &&
    typeof payload.ce === "string" &&
    /^[a-z0-9][a-z0-9_.-]{0,63}$/.test(payload.ce) &&
    Number.isSafeInteger(payload.sq) &&
    payload.sq >= 0 &&
    validLifetime(payload, now, GAME_STATE_TTL_SECONDS) &&
    (!release || payload.r === release) &&
    (!thumbprint || payload.pk === thumbprint) &&
    (!officialBuildId || payload.ob === officialBuildId)
  );
}

export function createGameSessionState({
  secret,
  release,
  thumbprint,
  officialBuildId,
  now = Date.now(),
  ttlSeconds = GAME_STATE_TTL_SECONDS,
}) {
  if (!HEX_64_PATTERN.test(release ?? "")) {
    throw new Error("A valid runtime release is required");
  }
  if (!HEX_64_PATTERN.test(thumbprint ?? "")) {
    throw new Error("A valid runtime key thumbprint is required");
  }
  if (!HEX_32_PATTERN.test(officialBuildId ?? "")) {
    throw new Error("A valid official build attestation id is required");
  }
  if (
    !Number.isInteger(ttlSeconds) ||
    ttlSeconds < 5 * 60 ||
    ttlSeconds > GAME_STATE_TTL_SECONDS
  ) {
    throw new Error("Game session state TTL is invalid");
  }
  const issuedAt = Math.floor(now / 1_000);
  const payload = {
    v: GAME_AUTHORITY_PROTOCOL,
    t: "state",
    pk: thumbprint,
    r: release,
    sid: randomBytes(16).toString("hex"),
    st: randomBytes(16).toString("hex"),
    ob: officialBuildId,
    sq: 0,
    ce: GAME_CONTENT_EPOCH,
    m: randomBytes(16).toString("base64url"),
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
  };
  return Object.freeze({
    version: GAME_AUTHORITY_PROTOCOL,
    release,
    contentEpoch: payload.ce,
    marker: payload.m,
    officialBuildId,
    sequence: payload.sq,
    stateToken: seal(STATE_PREFIX, payload, secret),
    expiresAt: payload.exp * 1_000,
  });
}

export function verifyGameSessionState({
  secret,
  stateToken,
  release,
  thumbprint,
  officialBuildId,
  now = Date.now(),
}) {
  try {
    const payload = open(STATE_PREFIX, stateToken, secret);
    return validStatePayload(payload, {
      now,
      release,
      thumbprint,
      officialBuildId,
    })
      ? Object.freeze({ ...payload })
      : null;
  } catch {
    return null;
  }
}

export function createGameTransitionCapability({
  secret,
  stateToken,
  release,
  thumbprint,
  officialBuildId,
  action,
  target,
  now = Date.now(),
  ttlSeconds = GAME_TRANSITION_TTL_SECONDS,
}) {
  const state = verifyGameSessionState({
    secret,
    stateToken,
    release,
    thumbprint,
    officialBuildId,
    now,
  });
  if (!state) throw new Error("Game session state is invalid");
  if (
    !Number.isInteger(ttlSeconds) ||
    ttlSeconds < 10 ||
    ttlSeconds > 2 * 60
  ) {
    throw new Error("Game transition TTL is invalid");
  }
  const normalizedTarget = normalizeGameTransitionTarget(action, target);
  const issuedAt = Math.floor(now / 1_000);
  const nextState = randomBytes(16).toString("hex");
  const payload = {
    v: GAME_AUTHORITY_PROTOCOL,
    t: "transition",
    pk: state.pk,
    r: state.r,
    sid: state.sid,
    ps: state.st,
    ns: nextState,
    sq: state.sq + 1,
    ce: state.ce,
    m: state.m,
    ob: state.ob,
    a: action,
    x: normalizedTarget,
    n: randomBytes(16).toString("base64url"),
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
  };
  return Object.freeze({
    version: GAME_AUTHORITY_PROTOCOL,
    release: state.r,
    action,
    target: normalizedTarget,
    sequence: payload.sq,
    marker: state.m,
    officialBuildId: state.ob,
    capability: seal(TRANSITION_PREFIX, payload, secret),
    expiresAt: payload.exp * 1_000,
  });
}

export function verifyGameTransitionCapability({
  secret,
  capability,
  release,
  officialBuildId,
  action,
  target,
  now = Date.now(),
}) {
  try {
    const payload = open(TRANSITION_PREFIX, capability, secret);
    const normalized = normalizeGameTransitionTarget(
      action ?? payload?.a,
      target ?? payload?.x,
    );
    const valid = (
      payload?.v === GAME_AUTHORITY_PROTOCOL &&
      payload?.t === "transition" &&
      HEX_64_PATTERN.test(payload.pk ?? "") &&
      HEX_64_PATTERN.test(payload.r ?? "") &&
      HEX_32_PATTERN.test(payload.sid ?? "") &&
      HEX_32_PATTERN.test(payload.ps ?? "") &&
      HEX_32_PATTERN.test(payload.ns ?? "") &&
      HEX_32_PATTERN.test(payload.ob ?? "") &&
      MARKER_PATTERN.test(payload.m ?? "") &&
      MARKER_PATTERN.test(payload.n ?? "") &&
      Number.isSafeInteger(payload.sq) &&
      payload.sq > 0 &&
      payload.a === (action ?? payload.a) &&
      JSON.stringify(payload.x) === JSON.stringify(normalized) &&
      validLifetime(payload, now, 2 * 60) &&
      (!release || payload.r === release)
      && (!officialBuildId || payload.ob === officialBuildId)
    );
    return valid ? Object.freeze({ ...payload, x: normalized }) : null;
  } catch {
    return null;
  }
}

export function advanceGameSessionState({
  secret,
  transition,
  now = Date.now(),
  ttlSeconds = GAME_STATE_TTL_SECONDS,
}) {
  if (
    !transition ||
    transition.v !== GAME_AUTHORITY_PROTOCOL ||
    transition.t !== "transition"
  ) {
    throw new Error("Verified game transition is required");
  }
  const issuedAt = Math.floor(now / 1_000);
  const payload = {
    v: GAME_AUTHORITY_PROTOCOL,
    t: "state",
    pk: transition.pk,
    r: transition.r,
    sid: transition.sid,
    st: transition.ns,
    sq: transition.sq,
    ce: transition.ce,
    m: transition.m,
    ob: transition.ob,
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
  };
  const stateToken = seal(STATE_PREFIX, payload, secret);
  const receiptId = createHash("sha256")
    .update([
      "toontown-browser-transition-receipt-v1",
      transition.sid,
      transition.ps,
      transition.ns,
      transition.a,
      String(transition.sq),
    ].join("\n"), "utf8")
    .digest("hex");
  return Object.freeze({
    version: GAME_AUTHORITY_PROTOCOL,
    release: transition.r,
    contentEpoch: transition.ce,
    marker: transition.m,
    officialBuildId: transition.ob,
    sequence: transition.sq,
    stateToken,
    receipt: Object.freeze({
      id: receiptId,
      action: transition.a,
      sequence: transition.sq,
      marker: transition.m,
    }),
    expiresAt: payload.exp * 1_000,
  });
}

export function createSignedFeatureModule({
  secret,
  stateToken,
  release,
  thumbprint,
  officialBuildId,
  moduleId,
  module,
  now = Date.now(),
  ttlSeconds = 10 * 60,
}) {
  const state = verifyGameSessionState({
    secret,
    stateToken,
    release,
    thumbprint,
    officialBuildId,
    now,
  });
  if (!state) throw new Error("Game session state is invalid");
  if (
    typeof moduleId !== "string" ||
    !/^[a-z0-9][a-z0-9_.-]{0,63}$/.test(moduleId) ||
    !module ||
    typeof module !== "object" ||
    Array.isArray(module)
  ) {
    throw new Error("Feature module is invalid");
  }
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 60 || ttlSeconds > 1800) {
    throw new Error("Feature module TTL is invalid");
  }
  const canonical = JSON.stringify(module);
  const moduleDigest = createHash("sha256")
    .update(canonical, "utf8")
    .digest("hex");
  const issuedAt = Math.floor(now / 1_000);
  const payload = {
    v: GAME_AUTHORITY_PROTOCOL,
    t: "feature",
    pk: state.pk,
    r: state.r,
    sid: state.sid,
    st: state.st,
    sq: state.sq,
    ce: state.ce,
    m: state.m,
    ob: state.ob,
    id: moduleId,
    d: moduleDigest,
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
  };
  return Object.freeze({
    version: GAME_AUTHORITY_PROTOCOL,
    release: state.r,
    contentEpoch: state.ce,
    marker: state.m,
    officialBuildId: state.ob,
    moduleId,
    moduleDigest,
    module,
    signature: seal(FEATURE_PREFIX, payload, secret),
    expiresAt: payload.exp * 1_000,
  });
}

export function verifySignedFeatureModule({
  secret,
  signature,
  moduleId,
  module,
  release,
  thumbprint,
  officialBuildId,
  now = Date.now(),
}) {
  try {
    const payload = open(FEATURE_PREFIX, signature, secret);
    const moduleDigest = createHash("sha256")
      .update(JSON.stringify(module), "utf8")
      .digest("hex");
    const valid = (
      payload?.v === GAME_AUTHORITY_PROTOCOL &&
      payload?.t === "feature" &&
      HEX_64_PATTERN.test(payload.pk ?? "") &&
      HEX_64_PATTERN.test(payload.r ?? "") &&
      HEX_32_PATTERN.test(payload.sid ?? "") &&
      HEX_32_PATTERN.test(payload.st ?? "") &&
      HEX_32_PATTERN.test(payload.ob ?? "") &&
      MARKER_PATTERN.test(payload.m ?? "") &&
      Number.isSafeInteger(payload.sq) &&
      payload.sq >= 0 &&
      payload.id === moduleId &&
      payload.d === moduleDigest &&
      validLifetime(payload, now, 1800) &&
      (!release || payload.r === release) &&
      (!thumbprint || payload.pk === thumbprint) &&
      (!officialBuildId || payload.ob === officialBuildId)
    );
    return valid ? Object.freeze({ ...payload }) : null;
  } catch {
    return null;
  }
}
