import assert from "node:assert/strict";
import {
  advanceGameSessionState,
  createGameSessionState,
  createSignedFeatureModule,
  createGameTransitionCapability,
  normalizeGameTransitionTarget,
  verifyGameSessionState,
  verifyGameTransitionCapability,
  verifySignedFeatureModule,
} from "../shared/game-authority.mjs";

const secret = Buffer.alloc(32, 7).toString("base64url");
const release = "a".repeat(64);
const thumbprint = "b".repeat(64);
const officialBuildId = "c".repeat(32);
const now = 1_800_000_000_000;

const initial = createGameSessionState({
  secret,
  release,
  thumbprint,
  officialBuildId,
  now,
});
const state = verifyGameSessionState({
  secret,
  stateToken: initial.stateToken,
  release,
  thumbprint,
  officialBuildId,
  now,
});
assert.equal(state.sq, 0);
assert.equal(state.st.length, 32);
assert.equal(state.ob, officialBuildId);

const issued = createGameTransitionCapability({
  secret,
  stateToken: initial.stateToken,
  release,
  thumbprint,
  officialBuildId,
  action: "battle.attack",
  target: { battle: 42, track: 4, level: 0, target: 99 },
  now,
});
const transition = verifyGameTransitionCapability({
  secret,
  capability: issued.capability,
  release,
  officialBuildId,
  action: "battle.attack",
  target: { battle: 42, track: 4, level: 0, target: 99 },
  now,
});
assert.equal(transition.ps, state.st);
assert.equal(transition.sq, 1);
assert.equal(
  verifyGameTransitionCapability({
    secret,
    capability: issued.capability,
    release,
    officialBuildId,
    action: "battle.attack",
    target: { battle: 42, track: 5, level: 0, target: 99 },
    now,
  }),
  null,
);

const advanced = advanceGameSessionState({ secret, transition, now });
const nextState = verifyGameSessionState({
  secret,
  stateToken: advanced.stateToken,
  release,
  thumbprint,
  officialBuildId,
  now,
});
assert.equal(nextState.st, transition.ns);
assert.equal(nextState.sq, 1);
assert.equal(advanced.receipt.action, "battle.attack");
assert.equal(advanced.receipt.id.length, 64);

assert.deepEqual(
  normalizeGameTransitionTarget("npc.interact", { npc: 41, zone: 2000 }),
  { npc: 41, zone: 2000 },
);
assert.deepEqual(
  normalizeGameTransitionTarget("catalog.purchase", {
    phone: 51,
    context: 7,
    gift: 1,
  }),
  { phone: 51, context: 7, gift: 1 },
);
assert.deepEqual(
  normalizeGameTransitionTarget("boss.reward", { boss: 61, reward: 3 }),
  { boss: 61, reward: 3 },
);
assert.deepEqual(
  normalizeGameTransitionTarget("minigame.finish", { game: 71 }),
  { game: 71 },
);
assert.deepEqual(
  normalizeGameTransitionTarget("race.finish", { race: 81, laps: 3 }),
  { race: 81, laps: 3 },
);
assert.throws(
  () => normalizeGameTransitionTarget(
    "race.finish", { race: 81, laps: 0 }),
  /lap count/i,
);

const featureModule = createSignedFeatureModule({
  secret,
  stateToken: initial.stateToken,
  release,
  thumbprint,
  officialBuildId,
  moduleId: "custom-features-v1",
  module: { version: 1, authority: "ai" },
  now,
});
assert.ok(verifySignedFeatureModule({
  secret,
  signature: featureModule.signature,
  moduleId: featureModule.moduleId,
  module: featureModule.module,
  release,
  thumbprint,
  officialBuildId,
  now,
}));
assert.equal(verifySignedFeatureModule({
  secret,
  signature: featureModule.signature,
  moduleId: featureModule.moduleId,
  module: { version: 1, authority: "client" },
  release,
  thumbprint,
  officialBuildId,
  now,
}), null);

assert.equal(
  verifyGameSessionState({
    secret: Buffer.alloc(32, 8).toString("base64url"),
    stateToken: initial.stateToken,
    release,
    thumbprint,
    officialBuildId,
    now,
  }),
  null,
);

console.log("game authority tests passed");
