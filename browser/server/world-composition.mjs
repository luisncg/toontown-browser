import { createHash } from "node:crypto";

export const WORLD_COMPOSITION_PROTOCOL = 1;
export const WORLD_COMPOSITION_EPOCH = "world-composition-v1";
export const CUSTOM_RULE_EPOCH = "custom-rules-v1";

const PLAYGROUND_PHASES = Object.freeze({
  1_000: Object.freeze(["4", "5", "5.5"]),
  2_000: Object.freeze(["4", "5", "5.5"]),
  3_000: Object.freeze(["4", "5", "5.5", "6"]),
  4_000: Object.freeze(["4", "5", "5.5", "6"]),
  5_000: Object.freeze(["4", "5", "5.5", "6"]),
  8_000: Object.freeze(["4", "5", "5.5", "6"]),
  9_000: Object.freeze(["4", "5", "5.5", "6"]),
});

function hoodZone(zoneId) {
  if (zoneId < 1_000) return zoneId;
  return Math.floor(zoneId / 1_000) * 1_000;
}

function stableDigest(value) {
  return createHash("sha256")
    .update(JSON.stringify(value), "utf8")
    .digest("hex");
}

export function worldCompositionForZone(zoneId, requiredPhases) {
  const hood = hoodZone(zoneId);
  const phases = PLAYGROUND_PHASES[hood] ?? requiredPhases;
  const composition = {
    protocol: WORLD_COMPOSITION_PROTOCOL,
    epoch: WORLD_COMPOSITION_EPOCH,
    zoneId,
    hood,
    requiredPhases: [...new Set(phases.map(String))],
    catalogs: {
      dna: `dna-${hood || zoneId}-v1`,
      npcs: `npcs-${hood || zoneId}-v1`,
      dialogue: "dialogue-classic-v1",
      cogs: "cog-populations-v1",
    },
    presentationModules: [
      "classic-world-v1",
      "browser-input-v1",
      "custom-features-v1",
    ],
  };
  return Object.freeze({
    ...composition,
    digest: stableDigest(composition),
  });
}

const FEATURE_MODULES = Object.freeze({
  "classic-world-v1": Object.freeze({
    version: 1,
    kind: "world-presentation",
    npcCatalog: "npcs-classic-v1",
    dialogueCatalog: "dialogue-classic-v1",
    buildingCatalog: "buildings-classic-v1",
  }),
  "browser-input-v1": Object.freeze({
    version: 1,
    kind: "input-presentation",
    bindings: "account-configured",
    touchProfile: "portrait-v1",
  }),
  "custom-features-v1": Object.freeze({
    version: 1,
    kind: "custom-presentation",
    ruleEpoch: CUSTOM_RULE_EPOCH,
    features: Object.freeze({
      reactiveGags: Object.freeze({
        authority: "ai",
        transition: "battle.attack",
      }),
      megaBuildings: Object.freeze({
        authority: "ai",
        transitions: Object.freeze(["building.board", "mega.vote", "mega.join"]),
      }),
      fishBingo: Object.freeze({
        authority: "ai",
        transition: "fish-bingo.claim",
      }),
      fishing: Object.freeze({
        authority: "ai",
        transitions: Object.freeze(["fishing.enter", "fishing.cast"]),
      }),
      trolley: Object.freeze({
        authority: "ai",
        transition: "trolley.board",
      }),
      estates: Object.freeze({
        authority: "ai",
        transition: "estate.enter",
      }),
    }),
  }),
});

export function featureModuleById(moduleId) {
  return FEATURE_MODULES[moduleId] ?? null;
}
