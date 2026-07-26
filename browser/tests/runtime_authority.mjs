import assert from "node:assert/strict";
import {
  generateKeyPairSync,
  sign as signValue,
} from "node:crypto";
import {
  createOfficialBuildAttestation,
  createRuntimeAuthorization,
  createRuntimeChallenge,
  createWorldCapability,
  runtimeRegistrationMessage,
  runtimeRequestMessage,
  verifyOfficialBuildAttestation,
  verifyRuntimeRegistration,
  verifyRuntimeRequestProof,
} from "../shared/runtime-authority.mjs";

const secret = Buffer.alloc(32, 29).toString("base64url");
const now = Date.UTC(2026, 6, 25, 12, 0, 0);
const context = {
  sessionKey: "a".repeat(32),
  release: "b".repeat(64),
  clientAddress: "198.51.100.41",
  userAgent: "Toontown Runtime Authority Test/1.0",
  origin: "https://toontown.lui.ss",
};
const { privateKey, publicKey } = generateKeyPairSync("ec", {
  namedCurve: "prime256v1",
});
const publicJwk = publicKey.export({ format: "jwk" });

const challenge = createRuntimeChallenge({
  secret,
  now,
  ...context,
});
assert.equal(challenge.version, 2);
assert.equal(challenge.release, context.release);
assert.match(challenge.challengeToken, /^rc2(?:\.[A-Za-z0-9_-]+){3}$/);

const registrationSignature = signValue(
  "sha256",
  runtimeRegistrationMessage({
    challenge: challenge.challenge,
    release: challenge.release,
    origin: context.origin,
  }),
  { key: privateKey, dsaEncoding: "ieee-p1363" },
).toString("base64url");
const registration = verifyRuntimeRegistration({
  challengeToken: challenge.challengeToken,
  publicKey: publicJwk,
  signature: registrationSignature,
  secret,
  context,
  now,
});
assert.ok(registration);
assert.match(registration.thumbprint, /^[a-f0-9]{64}$/);
assert.equal(
  verifyRuntimeRegistration({
    challengeToken: challenge.challengeToken,
    publicKey: publicJwk,
    signature: registrationSignature,
    secret,
    context: { ...context, origin: "https://copied.example" },
    now,
  }),
  null,
);
assert.equal(
  verifyRuntimeRegistration({
    challengeToken: challenge.challengeToken,
    publicKey: publicJwk,
    signature: registrationSignature,
    secret,
    context: { ...context, release: "c".repeat(64) },
    now,
  }),
  null,
);

const authorization = createRuntimeAuthorization({
  secret,
  publicKey: registration.publicKey,
  now,
  ...context,
});
assert.match(
  authorization.authorization,
  /^ra2(?:\.[A-Za-z0-9_-]+){3}$/,
);
assert.match(authorization.authorizationId, /^[a-f0-9]{32}$/);
const officialBuild = createOfficialBuildAttestation({
  secret,
  authorizationId: authorization.authorizationId,
  thumbprint: registration.thumbprint,
  now,
  ...context,
});
assert.equal(officialBuild.version, 1);
assert.equal(officialBuild.buildId, context.release);
assert.match(officialBuild.attestation, /^ob1(?:\.[A-Za-z0-9_-]+){3}$/);
assert.match(officialBuild.attestationId, /^[a-f0-9]{32}$/);
assert.ok(verifyOfficialBuildAttestation({
  secret,
  attestation: officialBuild.attestation,
  attestationId: officialBuild.attestationId,
  authorizationId: authorization.authorizationId,
  thumbprint: registration.thumbprint,
  context,
  now,
}));
assert.equal(verifyOfficialBuildAttestation({
  secret,
  attestation: officialBuild.attestation,
  attestationId: officialBuild.attestationId,
  authorizationId: authorization.authorizationId,
  thumbprint: registration.thumbprint,
  context: { ...context, origin: "https://copied.example" },
  now,
}), null);

const body = Buffer.from(JSON.stringify({
  names: ["phase-4-part-1.data"],
}));
const timestamp = String(Math.floor(now / 1_000));
const nonce = Buffer.alloc(16, 5).toString("base64url");
const proofSignature = signValue(
  "sha256",
  runtimeRequestMessage({
    authorizationId: authorization.authorizationId,
    officialBuildId: officialBuild.attestationId,
    method: "POST",
    pathname: "/api/assets/tickets",
    timestamp,
    nonce,
    body,
  }),
  { key: privateKey, dsaEncoding: "ieee-p1363" },
).toString("base64url");
const proof = verifyRuntimeRequestProof({
  secret,
  authorization: authorization.authorization,
  signature: proofSignature,
  timestamp,
  nonce,
  method: "POST",
  pathname: "/api/assets/tickets",
  body,
  officialBuildId: officialBuild.attestationId,
  context,
  now,
});
assert.ok(proof);
assert.equal(proof.authorizationId, authorization.authorizationId);
assert.equal(
  verifyRuntimeRequestProof({
    secret,
    authorization: authorization.authorization,
    signature: proofSignature,
    timestamp,
    nonce,
    method: "POST",
    pathname: "/api/gateway/lease",
    body,
    officialBuildId: officialBuild.attestationId,
    context,
    now,
  }),
  null,
);
assert.equal(
  verifyRuntimeRequestProof({
    secret,
    authorization: authorization.authorization,
    signature: proofSignature,
    timestamp,
    nonce,
    method: "POST",
    pathname: "/api/assets/tickets",
    body: Buffer.from("{}"),
    officialBuildId: officialBuild.attestationId,
    context,
    now,
  }),
  null,
);

const world = createWorldCapability({
  secret,
  authorizationId: authorization.authorizationId,
  officialBuildId: officialBuild.attestationId,
  zoneId: 2_000,
  requiredPhases: ["4"],
  contentEpoch: "world-v1-test",
  now,
  ...context,
});
assert.equal(world.zoneId, 2_000);
assert.deepEqual(world.requiredPhases, ["4"]);
assert.equal(world.officialBuildId, officialBuild.attestationId);
assert.match(world.capability, /^rw2(?:\.[A-Za-z0-9_-]+){3}$/);

console.log(
  "Runtime authority tests passed: PoP, release/context binding, and capabilities",
);
