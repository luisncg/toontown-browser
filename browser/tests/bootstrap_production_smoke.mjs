import assert from "node:assert/strict";
import {
  generateKeyPairSync,
  randomBytes,
  sign as signValue,
} from "node:crypto";
import { once } from "node:events";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { gzipSync } from "node:zlib";
import {
  bootstrapSessionDigest,
  BOOTSTRAP_COOKIE,
  createBootstrapSession,
} from "../shared/bootstrap-session.mjs";
import { verifyGatewayLease } from "../shared/gateway-lease.mjs";
import {
  runtimeRegistrationMessage,
  runtimeRequestMessage,
} from "../shared/runtime-authority.mjs";
import {
  verifyGameSessionState,
  verifyGameTransitionCapability,
  verifySignedFeatureModule,
} from "../shared/game-authority.mjs";

async function availablePort() {
  const probe = createServer();
  probe.listen(0, "127.0.0.1");
  await once(probe, "listening");
  const port = probe.address().port;
  probe.close();
  await once(probe, "close");
  return port;
}

async function waitForServer(url, child) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error("Web server exited during startup");
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The loopback listener may not be ready yet.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 25));
  }
  throw new Error("Web server did not become ready");
}

async function waitForOutput(output, marker) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (output().includes(marker)) return;
    await new Promise((resolveWait) => setTimeout(resolveWait, 25));
  }
  throw new Error(`Server output did not include ${marker}`);
}

const fixture = await mkdtemp(join(tmpdir(), "toontown-bootstrap-"));
const privateManifest = `${fixture}-private-r2-assets.json`;
const port = await availablePort();
const origin = `http://127.0.0.1:${port}`;
const publicOrigin = "https://toontown.lui.ss";
const secret = "production-smoke-secret-with-at-least-thirty-two-characters";
const assetTicketSecret = Buffer.alloc(32, 13).toString("base64url");
const gatewayLeaseSecret = Buffer.alloc(32, 23).toString("base64url");
const runtimeAuthoritySecret = Buffer.alloc(32, 31).toString("base64url");
await writeFile(join(fixture, "index.html"), "bootstrap");
await writeFile(join(fixture, "app.js"), "bootstrap-app");
await writeFile(
  join(fixture, "runtime-authority.js"),
  "bootstrap-runtime-authority",
);
await writeFile(
  join(fixture, "secure-asset-cache.js"),
  "bootstrap-secure-cache",
);
await writeFile(
  join(fixture, "short-audio-banks.js"),
  "bootstrap-short-audio",
);
await writeFile(join(fixture, "styles.css"), "bootstrap-style");
await writeFile(
  join(fixture, "toontownbrowserogimage2.png"),
  "public-og-image",
);
await writeFile(join(fixture, "open-toontown.js"), "protected-runtime");
await writeFile(join(fixture, "phase-manifest.json"), "protected-manifest");
await writeFile(join(fixture, "phase-4-part-1.js"), "protected-phase-loader");
await writeFile(join(fixture, "phase-4-part-1.data"), "protected-phase-data");
await writeFile(
  join(fixture, "phase-4-part-1.data.gz"),
  gzipSync("protected-phase-data", { level: 1 }),
);
const release = "a".repeat(64);
const checksum = "b".repeat(64);
await writeFile(privateManifest, JSON.stringify({
  version: 1,
  release,
  files: {
    "phase-4-part-1.data": {
      identity: {
        objectKey: `releases/${release}/phase-4-part-1.data`,
        size: 20,
        sha256: checksum,
      },
      gzip: {
        objectKey: `releases/${release}/phase-4-part-1.data.gz`,
        size: 40,
        sha256: checksum,
      },
    },
  },
}));

const protectedAssets = [
  ["open-toontown.js", "protected-runtime"],
  ["phase-manifest.json", "protected-manifest"],
  ["phase-4-part-1.js", "protected-phase-loader"],
];

const child = spawn(
  process.execPath,
  [resolve("browser/scripts/serve.mjs"), fixture],
  {
    cwd: resolve("."),
    env: {
      ...process.env,
      PORT: String(port),
      TOONTOWN_PRODUCTION: "1",
      PUBLIC_ORIGIN: publicOrigin,
      TURNSTILE_SITE_KEY: "test-public-site-key",
      TURNSTILE_SECRET_KEY: "test-private-secret-key",
      TURNSTILE_SESSION_SECRET: secret,
      GATEWAY_LEASE_SECRET: gatewayLeaseSecret,
      RUNTIME_AUTHORITY_SECRET: runtimeAuthoritySecret,
      ASSET_GATEWAY_ORIGIN: "https://assets.invalid",
      ASSET_GATEWAY_TOKEN_SECRET: assetTicketSecret,
      ASSET_GATEWAY_TTL_SECONDS: "180",
      R2_ASSET_MANIFEST_PATH: privateManifest,
      R2_ASSET_RELEASE: release,
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let serverStdout = "";
child.stdout.on("data", (chunk) => {
  serverStdout += chunk.toString("utf8");
});

try {
  await waitForServer(`${origin}/api/bootstrap/config`, child);

  const config = await fetch(`${origin}/api/bootstrap/config`).then((response) =>
    response.json()
  );
  assert.deepEqual(config, {
    required: true,
    authorityRequired: true,
    authorityProtocol: 1,
    release,
    siteKey: "test-public-site-key",
  });
  assert.deepEqual(
    await fetch(`${origin}/api/bootstrap/session`).then((response) =>
      response.json()
    ),
    { valid: false },
  );
  assert.equal((await fetch(`${origin}/app.js`)).status, 200);
  assert.equal((await fetch(`${origin}/runtime-authority.js`)).status, 200);
  assert.equal((await fetch(`${origin}/secure-asset-cache.js`)).status, 200);
  const shortAudioRuntime = await fetch(
    `${origin}/short-audio-banks.js`,
  );
  assert.equal(shortAudioRuntime.status, 200);
  assert.equal(await shortAudioRuntime.text(), "bootstrap-short-audio");
  assert.equal(shortAudioRuntime.headers.get("cache-control"), "no-store");
  const ogImage = await fetch(
    `${origin}/toontownbrowserogimage2.png`,
  );
  assert.equal(ogImage.status, 200);
  assert.equal(await ogImage.text(), "public-og-image");
  assert.equal(ogImage.headers.get("content-type"), "image/png");
  assert.equal(ogImage.headers.get("cache-control"), "no-store");
  for (const [asset] of protectedAssets) {
    assert.equal((await fetch(`${origin}/${asset}`)).status, 401);
  }

  const session = createBootstrapSession(secret);
  const sessionCookie = `${BOOTSTRAP_COOKIE}=${session}`;
  const gatewayClientIp = "198.51.100.77";
  const gatewayUserAgent = "Toontown Browser production smoke/1.0";
  async function createAuthorityClient(
    cookie,
    clientIp = gatewayClientIp,
    userAgent = gatewayUserAgent,
  ) {
    const { privateKey, publicKey } = generateKeyPairSync("ec", {
      namedCurve: "prime256v1",
    });
    const challengeResponse = await fetch(
      `${origin}/api/bootstrap/session`,
      {
        headers: {
          Cookie: `${BOOTSTRAP_COOKIE}=${cookie}`,
          "X-Toontown-Client-IP": clientIp,
          "User-Agent": userAgent,
        },
      },
    );
    assert.equal(challengeResponse.status, 200);
    const sessionState = await challengeResponse.json();
    assert.equal(sessionState.valid, true);
    assert.equal(sessionState.runtime.release, release);
    const signature = signValue(
      "sha256",
      runtimeRegistrationMessage({
        challenge: sessionState.runtime.challenge,
        release,
        origin: publicOrigin,
      }),
      { key: privateKey, dsaEncoding: "ieee-p1363" },
    ).toString("base64url");
    const authorizationResponse = await fetch(
      `${origin}/api/runtime/authorize`,
      {
        method: "POST",
        headers: {
          Cookie: `${BOOTSTRAP_COOKIE}=${cookie}`,
          Origin: publicOrigin,
          "Content-Type": "application/json",
          "X-Toontown-Client-IP": clientIp,
          "User-Agent": userAgent,
        },
        body: JSON.stringify({
          challengeToken: sessionState.runtime.challengeToken,
          publicKey: publicKey.export({ format: "jwk" }),
          signature,
        }),
      },
    );
    assert.equal(authorizationResponse.status, 200);
    const material = await authorizationResponse.json();
    assert.equal(material.version, 1);
    assert.equal(material.release, release);
    assert.match(material.authorizationId, /^[a-f0-9]{32}$/);

    return {
      material,
      async request(
        pathname,
        bodyValue,
        {
          originHeader = publicOrigin,
          fetchSite = "same-origin",
          cookieValue = cookie,
          acceptEncoding,
        } = {},
      ) {
        const body = JSON.stringify(bodyValue);
        const timestamp = String(Math.floor(Date.now() / 1_000));
        const nonce = randomBytes(16).toString("base64url");
        const proof = signValue(
          "sha256",
          runtimeRequestMessage({
            authorizationId: material.authorizationId,
            method: "POST",
            pathname,
            timestamp,
            nonce,
            body: Buffer.from(body),
          }),
          { key: privateKey, dsaEncoding: "ieee-p1363" },
        ).toString("base64url");
        return fetch(`${origin}${pathname}`, {
          method: "POST",
          headers: {
            Cookie: cookieValue
              ? `${BOOTSTRAP_COOKIE}=${cookieValue}`
              : "",
            Origin: originHeader,
            "Sec-Fetch-Site": fetchSite,
            "Content-Type": "application/json",
            "X-Toontown-Client-IP": clientIp,
            "User-Agent": userAgent,
            "X-Toontown-Authority": material.authorization,
            "X-Toontown-Authority-Id": material.authorizationId,
            "X-Toontown-Proof-Time": timestamp,
            "X-Toontown-Proof-Nonce": nonce,
            "X-Toontown-Proof": proof,
            ...(acceptEncoding
              ? { "Accept-Encoding": acceptEncoding }
              : {}),
          },
          body,
        });
      },
    };
  }
  const authorityClient = await createAuthorityClient(session);
  assert.equal(
    (
      await fetch(`${origin}/api/gateway/lease`, {
        method: "POST",
        headers: {
          Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
          Origin: publicOrigin,
          "Sec-Fetch-Site": "same-origin",
          "Content-Type": "application/json",
          "X-Toontown-Client-IP": gatewayClientIp,
          "User-Agent": gatewayUserAgent,
        },
        body: "{}",
      })
    ).status,
    403,
  );
  assert.equal(
    (
      await fetch(`${origin}/api/assets/tickets`, {
        method: "POST",
        headers: {
          Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
          Origin: publicOrigin,
          "Content-Type": "application/json",
          "X-Toontown-Client-IP": gatewayClientIp,
          "User-Agent": gatewayUserAgent,
        },
        body: JSON.stringify({ names: ["phase-4-part-1.data"] }),
      })
    ).status,
    403,
  );
  const leaseRequest = (
    cookie,
    originHeader,
    fetchSite = "same-origin",
  ) => authorityClient.request(
    "/api/gateway/lease",
    {},
    {
      cookieValue: cookie,
      originHeader,
      fetchSite,
    },
  );
  assert.equal((await leaseRequest("", publicOrigin)).status, 401);
  assert.equal(
    (await leaseRequest(session, "https://copied.example")).status,
    403,
  );
  assert.equal(
    (await leaseRequest(session, publicOrigin, "cross-site")).status,
    403,
  );
  const gatewayLeaseResponse = await leaseRequest(session, publicOrigin);
  assert.equal(gatewayLeaseResponse.status, 200);
  assert.equal(gatewayLeaseResponse.headers.get("cache-control"), "no-store");
  const gatewayMaterial = await gatewayLeaseResponse.json();
  assert.equal(gatewayMaterial.version, 2);
  assert.equal(
    gatewayMaterial.authority,
    authorityClient.material.authorizationId,
  );
  assert.match(gatewayMaterial.resume, /^[A-Za-z0-9_-]{32}$/);
  assert.match(
    gatewayMaterial.lease,
    /^v1(?:\.[A-Za-z0-9_-]+){3}$/,
  );
  assert.ok(gatewayMaterial.expiresAt > Date.now());
  assert.ok(!gatewayMaterial.lease.includes(session));
  assert.equal(
    verifyGatewayLease(
      gatewayMaterial.lease,
      gatewayLeaseSecret,
      {
        sessionKey: bootstrapSessionDigest({ cookie: sessionCookie }),
        resumeToken: gatewayMaterial.resume,
        clientAddress: gatewayClientIp,
        userAgent: gatewayUserAgent,
        origin: publicOrigin,
        authorityKey: authorityClient.material.authorizationId,
      },
    ),
    true,
  );

  const ticketRequest = (
    cookie,
    originHeader,
    names,
    client = authorityClient,
  ) => client.request(
    "/api/assets/tickets",
    { names },
    {
      cookieValue: cookie,
      originHeader,
      acceptEncoding: "gzip",
    },
  );
  assert.equal(
    (await ticketRequest("", publicOrigin, ["phase-4-part-1.data"])).status,
    401,
  );
  assert.equal(
    (await ticketRequest(
      session,
      "https://wrong.example",
      ["phase-4-part-1.data"],
    )).status,
    403,
  );
  assert.equal(
    (await ticketRequest(
      session,
      publicOrigin,
      ["phase-4-part-1.data", "phase-4-part-1.data"],
    )).status,
    400,
  );
  assert.equal(
    (await ticketRequest(
      session,
      publicOrigin,
      ["phase-does-not-exist.data"],
    )).status,
    400,
  );
  const ticketBatchResponse = await ticketRequest(
    session,
    publicOrigin,
    ["phase-4-part-1.data"],
  );
  assert.equal(ticketBatchResponse.status, 200);
  assert.equal(ticketBatchResponse.headers.get("cache-control"), "no-store");
  assert.equal(ticketBatchResponse.headers.get("vary"), "Accept-Encoding");
  const ticketBatch = await ticketBatchResponse.json();
  assert.equal(ticketBatch.version, 2);
  assert.equal(ticketBatch.release, release);
  assert.equal(ticketBatch.tickets.length, 1);
  assert.equal(ticketBatch.tickets[0].name, "phase-4-part-1.data");
  assert.equal(
    ticketBatch.tickets[0].authority,
    authorityClient.material.authorizationId,
  );
  assert.match(ticketBatch.tickets[0].url, /^https:\/\/assets\.invalid\/assets\/v1\./);
  assert.ok(!ticketBatch.tickets[0].url.includes("phase-4"));
  assert.ok(!ticketBatch.tickets[0].url.includes(release));

  const gameSessionResponse = await authorityClient.request(
    "/api/runtime/game-session",
    {},
  );
  assert.equal(gameSessionResponse.status, 200);
  const gameSession = await gameSessionResponse.json();
  assert.equal(gameSession.version, 1);
  assert.equal(gameSession.release, release);
  assert.match(gameSession.stateToken, /^gs1(?:\.[A-Za-z0-9_-]+){2}$/);
  assert.match(gameSession.marker, /^[A-Za-z0-9_-]{22}$/);
  const verifiedGameState = verifyGameSessionState({
    secret: runtimeAuthoritySecret,
    stateToken: gameSession.stateToken,
    release,
  });
  assert.equal(verifiedGameState.sq, 0);

  const transitionResponse = await authorityClient.request(
    "/api/runtime/game-transitions",
    {
      stateToken: gameSession.stateToken,
      action: "estate.enter",
      target: { manager: 1001, owner: 2002 },
    },
  );
  assert.equal(transitionResponse.status, 200);
  const transition = await transitionResponse.json();
  assert.match(transition.capability, /^gt1(?:\.[A-Za-z0-9_-]+){2}$/);
  assert.ok(verifyGameTransitionCapability({
    secret: runtimeAuthoritySecret,
    capability: transition.capability,
    release,
    action: "estate.enter",
    target: { manager: 1001, owner: 2002 },
  }));

  const otherAuthorityClient = await createAuthorityClient(session);
  assert.equal(
    (await otherAuthorityClient.request(
      "/api/runtime/game-transitions",
      {
        stateToken: gameSession.stateToken,
        action: "estate.enter",
        target: { manager: 1001, owner: 2002 },
      },
    )).status,
    409,
  );

  const featureModuleResponse = await authorityClient.request(
    "/api/runtime/feature-modules",
    {
      stateToken: gameSession.stateToken,
      moduleIds: ["custom-features-v1"],
    },
  );
  assert.equal(featureModuleResponse.status, 200);
  const featureModules = await featureModuleResponse.json();
  assert.equal(featureModules.modules.length, 1);
  assert.equal(
    featureModules.modules[0].marker,
    gameSession.marker,
  );
  assert.ok(verifySignedFeatureModule({
    secret: runtimeAuthoritySecret,
    signature: featureModules.modules[0].signature,
    moduleId: featureModules.modules[0].moduleId,
    module: featureModules.modules[0].module,
    release,
  }));

  const worldCapabilityResponse = await authorityClient.request(
    "/api/runtime/world-capabilities",
    { zoneIds: [2_000, 22_000], stateToken: gameSession.stateToken },
  );
  assert.equal(worldCapabilityResponse.status, 200);
  const worldCapabilities = await worldCapabilityResponse.json();
  assert.equal(worldCapabilities.version, 1);
  assert.equal(worldCapabilities.release, release);
  assert.deepEqual(
    worldCapabilities.capabilities.map((entry) => entry.zoneId),
    [2_000, 22_000],
  );
  assert.deepEqual(
    worldCapabilities.capabilities[0].requiredPhases,
    ["4", "5", "5.5"],
  );
  assert.deepEqual(
    worldCapabilities.capabilities[1].requiredPhases,
    ["4", "5"],
  );
  for (const capability of worldCapabilities.capabilities) {
    assert.match(capability.capability, /^rw1(?:\.[A-Za-z0-9_-]+){3}$/);
    assert.ok(capability.expiresAt > Date.now());
    assert.equal(capability.forensicMarker, gameSession.marker);
    assert.equal(
      capability.composition.digest,
      capability.compositionDigest,
    );
    assert.ok(capability.composition.presentationModules.length >= 1);
  }

  const rateSession = createBootstrapSession(secret, Date.now() + 1_000);
  const rateAuthorityClient = await createAuthorityClient(rateSession);
  for (let attempt = 0; attempt < 20; attempt += 1) {
    assert.equal(
      (await ticketRequest(
        rateSession,
        publicOrigin,
        ["phase-4-part-1.data"],
        rateAuthorityClient,
      )).status,
      200,
    );
  }
  assert.equal(
    (await ticketRequest(
      rateSession,
      publicOrigin,
      ["phase-4-part-1.data"],
      rateAuthorityClient,
    )).status,
    429,
  );
  const performancePayload = {
    events: [
      {
        type: "session",
        atMs: 123,
        browser: "safari",
        device: "mobile",
        connection: "unknown",
        viewportWidth: 390,
        viewportHeight: 844,
        dpr: 3,
        touch: true,
        account: "private-account-value",
        password: "private-password-value",
      },
      {
        type: "phase_complete",
        atMs: 456,
        phase: "4",
        parts: 23,
        assetBytes: 54_000_000,
        durationMs: 3_200,
        fromCache: false,
        requests: 46,
        transferBytes: 18_000_000,
        resourceMs: 2_700,
        processingMs: 500,
        chat: "private-chat-value",
      },
      {
        type: "npc_movie",
        atMs: 900,
        stage: "ready",
        movie: "complete",
        elapsedMs: 24,
        state: "gameplay",
        account: "private-account-value",
      },
      {
        type: "gc_pause",
        atMs: 950,
        generation: 2,
        durationMs: 87,
        state: "tutorial",
        password: "private-password-value",
      },
      {
        type: "script_step",
        atMs: 980,
        stage: "chapter",
        script: "tutorial_tom",
        durationMs: 143,
        state: "tutorial",
        chat: "private-chat-value",
      },
      {
        type: "avatar_setup",
        atMs: 990,
        stage: "interface",
        durationMs: 2_194,
        state: "tutorial",
        account: "private-account-value",
      },
      {
        type: "interface_setup",
        atMs: 995,
        stage: "quest_map",
        durationMs: 731,
        state: "tutorial",
        password: "private-password-value",
      },
      {
        type: "frame_stage",
        atMs: 4_900,
        stage: "render",
        durationMs: 867,
        state: "tutorial",
        script: "tutorial_tom",
        command: "transform",
        step: 42,
      },
      {
        type: "frame_call",
        atMs: 4_950,
        durationMs: 734,
        state: "tutorial",
        script: "tutorial_tom",
        command: "animation",
        step: 92,
      },
      {
        type: "interval_phase",
        atMs: 4_960,
        phase: "callbacks",
        durationMs: 691,
        state: "tutorial",
        script: "tutorial_tom",
        command: "animation",
        step: 92,
      },
      {
        type: "interval_function",
        atMs: 4_965,
        callback: "play",
        durationMs: 677,
        state: "tutorial",
        script: "tutorial_tom",
        command: "animation",
        step: 92,
      },
      {
        type: "actor_animation",
        atMs: 4_970,
        operation: "play",
        controls: 6,
        lookupMs: 654,
        controlMs: 23,
        state: "tutorial",
        script: "tutorial_tom",
        command: "animation",
        step: 92,
      },
      {
        type: "frame_gap",
        atMs: 4_975,
        durationMs: 1_917,
        state: "tutorial",
        script: "tutorial_reward",
        command: "interface",
        step: 8,
        phase: "4",
      },
      {
        type: "main_thread_stall",
        atMs: 5_000,
        durationMs: 4_100,
        state: "gameplay",
        npcStage: "ready",
        movie: "complete",
        script: "tutorial_tom",
        command: "transform",
        step: 42,
      },
      {
        type: "runtime_error",
        atMs: 5_100,
        category: "python",
        state: "gameplay",
      },
    ],
  };
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(performancePayload),
    })).status,
    401,
  );
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: "https://wrong.example",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(performancePayload),
    })).status,
    403,
  );
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(performancePayload),
    })).status,
    202,
  );
  await waitForOutput(() => serverStdout, "[BrowserPerformance]");
  const performanceLine = serverStdout.split("\n").find(
    (line) => line.startsWith("[BrowserPerformance] "),
  );
  assert.ok(performanceLine);
  const loggedPerformance = JSON.parse(
    performanceLine.slice("[BrowserPerformance] ".length),
  );
  assert.match(loggedPerformance.session, /^[a-f0-9]{16}$/);
  assert.equal(loggedPerformance.events.length, 15);
  assert.equal(loggedPerformance.events[0].browser, "safari");
  assert.equal(loggedPerformance.events[1].phase, "4");
  assert.equal(loggedPerformance.events[2].stage, "ready");
  assert.equal(loggedPerformance.events[3].generation, 2);
  assert.equal(loggedPerformance.events[3].durationMs, 87);
  assert.equal(loggedPerformance.events[4].script, "tutorial_tom");
  assert.equal(loggedPerformance.events[4].durationMs, 143);
  assert.equal(loggedPerformance.events[5].type, "avatar_setup");
  assert.equal(loggedPerformance.events[5].stage, "interface");
  assert.equal(loggedPerformance.events[5].durationMs, 2_194);
  assert.equal(loggedPerformance.events[6].type, "interface_setup");
  assert.equal(loggedPerformance.events[6].stage, "quest_map");
  assert.equal(loggedPerformance.events[6].durationMs, 731);
  assert.equal(loggedPerformance.events[7].stage, "render");
  assert.equal(loggedPerformance.events[7].durationMs, 867);
  assert.equal(loggedPerformance.events[7].step, 42);
  assert.equal(loggedPerformance.events[8].type, "frame_call");
  assert.equal(loggedPerformance.events[8].durationMs, 734);
  assert.equal(loggedPerformance.events[8].step, 92);
  assert.equal(loggedPerformance.events[9].phase, "callbacks");
  assert.equal(loggedPerformance.events[9].durationMs, 691);
  assert.equal(loggedPerformance.events[10].callback, "play");
  assert.equal(loggedPerformance.events[10].durationMs, 677);
  assert.equal(loggedPerformance.events[11].type, "actor_animation");
  assert.equal(loggedPerformance.events[11].operation, "play");
  assert.equal(loggedPerformance.events[11].controls, 6);
  assert.equal(loggedPerformance.events[11].lookupMs, 654);
  assert.equal(loggedPerformance.events[11].controlMs, 23);
  assert.equal(loggedPerformance.events[12].type, "frame_gap");
  assert.equal(loggedPerformance.events[12].durationMs, 1_917);
  assert.equal(loggedPerformance.events[12].script, "tutorial_reward");
  assert.equal(loggedPerformance.events[12].phase, "4");
  assert.equal(loggedPerformance.events[13].durationMs, 4_100);
  assert.equal(loggedPerformance.events[13].script, "tutorial_tom");
  assert.equal(loggedPerformance.events[13].command, "transform");
  assert.equal(loggedPerformance.events[13].step, 42);
  assert.equal(loggedPerformance.events[14].category, "python");
  assert.ok(!performanceLine.includes("private-account-value"));
  assert.ok(!performanceLine.includes("private-password-value"));
  assert.ok(!performanceLine.includes("private-chat-value"));
  const toonEntryPerformancePayload = {
    events: [
      {
        type: "toon_entry",
        atMs: 7_000,
        stage: "selected",
        durationMs: 0,
        state: "avatar_chooser",
        account: "private-account-value",
      },
      {
        type: "toon_entry",
        atMs: 13_900,
        stage: "tutorial_state",
        durationMs: 6_900,
        state: "tutorial",
        toonName: "private-toon-value",
      },
      {
        type: "toon_entry",
        atMs: 14_150,
        stage: "first_frame",
        durationMs: 7_150,
        state: "tutorial",
        avatarId: "private-avatar-value",
      },
    ],
  };
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(toonEntryPerformancePayload),
    })).status,
    202,
  );
  await waitForOutput(() => serverStdout, "\"toon_entry\"");
  const toonEntryPerformanceLine = serverStdout.split("\n").find(
    (line) => line.includes("\"toon_entry\""),
  );
  assert.ok(toonEntryPerformanceLine);
  const loggedToonEntryPerformance = JSON.parse(
    toonEntryPerformanceLine.slice("[BrowserPerformance] ".length),
  );
  assert.equal(loggedToonEntryPerformance.events.length, 3);
  assert.deepEqual(
    loggedToonEntryPerformance.events.map((event) => event.stage),
    ["selected", "tutorial_state", "first_frame"],
  );
  assert.equal(loggedToonEntryPerformance.events[0].durationMs, 0);
  assert.equal(loggedToonEntryPerformance.events[1].durationMs, 6_900);
  assert.equal(loggedToonEntryPerformance.events[2].durationMs, 7_150);
  assert.ok(!toonEntryPerformanceLine.includes("private-account-value"));
  assert.ok(!toonEntryPerformanceLine.includes("private-toon-value"));
  assert.ok(!toonEntryPerformanceLine.includes("private-avatar-value"));
  const phaseHandoffPerformancePayload = {
    events: [
      {
        type: "phase_handoff",
        atMs: 5_600,
        phase: "4",
        stage: "part",
        part: 7,
        bytes: 3_926_935,
        source: "network",
        readMs: 145,
        verifyMs: 4,
        mountMs: 52,
        persistMs: 88,
        durationMs: 241,
        activeParts: 4,
        activeBytes: 15_637_362,
        cacheStored: true,
        account: "private-account-value",
      },
      {
        type: "phase_handoff",
        atMs: 8_299,
        phase: "4",
        stage: "complete",
        parts: 23,
        bytes: 90_583_459,
        durationMs: 8_175,
        peakActiveParts: 4,
        peakActiveBytes: 15_637_362,
        networkParts: 23,
        cacheParts: 0,
        cacheFailures: 0,
        claims: 23,
        password: "private-password-value",
      },
    ],
  };
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(phaseHandoffPerformancePayload),
    })).status,
    202,
  );
  await waitForOutput(() => serverStdout, "\"phase_handoff\"");
  const phaseHandoffPerformanceLine = serverStdout.split("\n").find(
    (line) => line.includes("\"phase_handoff\""),
  );
  assert.ok(phaseHandoffPerformanceLine);
  const loggedPhaseHandoffPerformance = JSON.parse(
    phaseHandoffPerformanceLine.slice("[BrowserPerformance] ".length),
  );
  assert.equal(loggedPhaseHandoffPerformance.events.length, 2);
  assert.equal(loggedPhaseHandoffPerformance.events[0].stage, "part");
  assert.equal(loggedPhaseHandoffPerformance.events[0].source, "network");
  assert.equal(loggedPhaseHandoffPerformance.events[0].part, 7);
  assert.equal(loggedPhaseHandoffPerformance.events[0].cacheStored, true);
  assert.equal(loggedPhaseHandoffPerformance.events[1].stage, "complete");
  assert.equal(loggedPhaseHandoffPerformance.events[1].peakActiveParts, 4);
  assert.equal(loggedPhaseHandoffPerformance.events[1].networkParts, 23);
  assert.equal(loggedPhaseHandoffPerformance.events[1].claims, 23);
  assert.ok(!phaseHandoffPerformanceLine.includes("private-account-value"));
  assert.ok(!phaseHandoffPerformanceLine.includes("private-password-value"));
  const battlePerformancePayload = {
    events: [
      {
        type: "battle_build",
        atMs: 6_000,
        track: "throw",
        stage: "construct",
        attacks: 1,
        durationMs: 6_429,
        state: "tutorial",
        account: "private-account-value",
      },
      {
        type: "battle_stage",
        atMs: 6_025,
        stage: "toon_movie",
        durationMs: 6_438,
        state: "tutorial",
      },
      {
        type: "battle_asset",
        atMs: 6_050,
        kind: "prop",
        asset: "splat-tart",
        status: "cold",
        durationMs: 3_800,
        state: "tutorial",
        password: "private-password-value",
      },
      {
        type: "battle_sound",
        atMs: 6_075,
        sound: "aa_tart_only.ogg",
        requestStatus: "first",
        requestCount: 1,
        lookupStatus: "indexed",
        resolveMs: 0,
        managerMs: 979,
        totalMs: 980,
        state: "tutorial",
        account: "private-account-value",
      },
      {
        type: "battle_sound",
        atMs: 6_080,
        sound: "aa_tart_only.ogg",
        requestStatus: "repeat",
        requestCount: 2,
        lookupStatus: "fallback",
        resolveMs: 1,
        managerMs: 3,
        totalMs: 4,
        state: "tutorial",
      },
      {
        type: "lifecycle",
        atMs: 6_090,
        visibility: "visible",
        awayMs: 4_080,
        state: "tutorial",
        username: "private-account-value",
      },
      {
        type: "audio_lifecycle",
        atMs: 6_095,
        stage: "resume",
        trigger: "visibility",
        gesture: false,
        attempted: 2,
        recovered: 2,
        failed: 0,
        needsGestureRetry: false,
        state: "tutorial",
        account: "private-account-value",
        beforeStates: "private-browser-audio-state",
      },
      {
        type: "animation_bind",
        atMs: 6_100,
        actor: "toon",
        animation: "throw",
        controls: 1,
        durationMs: 2_100,
        state: "tutorial",
        chat: "private-chat-value",
      },
      {
        type: "actor_interval_build",
        atMs: 6_150,
        actor: "toon",
        animation: "throw",
        durationMs: 2_110,
        state: "tutorial",
      },
    ],
  };
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(battlePerformancePayload),
    })).status,
    202,
  );
  await waitForOutput(() => serverStdout, "\"splat-tart\"");
  const battlePerformanceLine = serverStdout.split("\n").find(
    (line) => line.includes("\"splat-tart\""),
  );
  assert.ok(battlePerformanceLine);
  const loggedBattlePerformance = JSON.parse(
    battlePerformanceLine.slice("[BrowserPerformance] ".length),
  );
  assert.equal(loggedBattlePerformance.events.length, 9);
  assert.equal(loggedBattlePerformance.events[0].type, "battle_build");
  assert.equal(loggedBattlePerformance.events[0].track, "throw");
  assert.equal(loggedBattlePerformance.events[0].durationMs, 6_429);
  assert.equal(loggedBattlePerformance.events[1].type, "battle_stage");
  assert.equal(loggedBattlePerformance.events[1].stage, "toon_movie");
  assert.equal(loggedBattlePerformance.events[1].durationMs, 6_438);
  assert.equal(loggedBattlePerformance.events[2].type, "battle_asset");
  assert.equal(loggedBattlePerformance.events[2].asset, "splat-tart");
  assert.equal(loggedBattlePerformance.events[2].status, "cold");
  assert.equal(loggedBattlePerformance.events[3].type, "battle_sound");
  assert.equal(loggedBattlePerformance.events[3].sound, "aa_tart_only.ogg");
  assert.equal(loggedBattlePerformance.events[3].requestStatus, "first");
  assert.equal(loggedBattlePerformance.events[3].requestCount, 1);
  assert.equal(loggedBattlePerformance.events[3].lookupStatus, "indexed");
  assert.equal(loggedBattlePerformance.events[3].resolveMs, 0);
  assert.equal(loggedBattlePerformance.events[3].managerMs, 979);
  assert.equal(loggedBattlePerformance.events[3].totalMs, 980);
  assert.equal(loggedBattlePerformance.events[4].type, "battle_sound");
  assert.equal(loggedBattlePerformance.events[4].requestStatus, "repeat");
  assert.equal(loggedBattlePerformance.events[4].requestCount, 2);
  assert.equal(loggedBattlePerformance.events[4].lookupStatus, "fallback");
  assert.equal(loggedBattlePerformance.events[4].managerMs, 3);
  assert.equal(loggedBattlePerformance.events[5].type, "lifecycle");
  assert.equal(loggedBattlePerformance.events[5].visibility, "visible");
  assert.equal(loggedBattlePerformance.events[5].awayMs, 4_080);
  assert.equal(
    loggedBattlePerformance.events[6].type,
    "audio_lifecycle",
  );
  assert.equal(loggedBattlePerformance.events[6].stage, "resume");
  assert.equal(loggedBattlePerformance.events[6].trigger, "visibility");
  assert.equal(loggedBattlePerformance.events[6].recovered, 2);
  assert.equal(loggedBattlePerformance.events[6].gesture, false);
  assert.ok(!("beforeStates" in loggedBattlePerformance.events[6]));
  assert.equal(loggedBattlePerformance.events[7].type, "animation_bind");
  assert.equal(loggedBattlePerformance.events[7].animation, "throw");
  assert.equal(loggedBattlePerformance.events[7].controls, 1);
  assert.equal(
    loggedBattlePerformance.events[8].type,
    "actor_interval_build",
  );
  assert.ok(!battlePerformanceLine.includes("private-account-value"));
  assert.ok(!battlePerformanceLine.includes("private-password-value"));
  assert.ok(!battlePerformanceLine.includes("private-chat-value"));
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ events: [{ type: "arbitrary" }] }),
    })).status,
    400,
  );
  assert.equal(
    (await fetch(`${origin}/api/performance`, {
      method: "POST",
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        Origin: publicOrigin,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ events: [], padding: "x".repeat(9_000) }),
    })).status,
    413,
  );
  const refreshedSessionState =
    await fetch(`${origin}/api/bootstrap/session`, {
      headers: { Cookie: `${BOOTSTRAP_COOKIE}=${session}` },
    }).then((response) => response.json());
  assert.equal(refreshedSessionState.valid, true);
  assert.equal(refreshedSessionState.runtime.release, release);
  let runtimeEtag;
  for (const [asset, expectedBody] of protectedAssets) {
    const protectedResponse = await fetch(`${origin}/${asset}`, {
      headers: { Cookie: `${BOOTSTRAP_COOKIE}=${session}` },
    });
    assert.equal(protectedResponse.status, 200);
    assert.equal(await protectedResponse.text(), expectedBody);
    assert.equal(
      protectedResponse.headers.get("cache-control"),
      "private, no-cache, must-revalidate",
    );
    assert.ok(protectedResponse.headers.get("etag"));
    if (asset === "open-toontown.js") {
      runtimeEtag = protectedResponse.headers.get("etag");
    }
  }
  const versionHash = "a".repeat(64);
  const compressedData = await fetch(
    `${origin}/phase-4-part-1.data?v=${versionHash}`,
    {
      headers: {
        Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
        "Accept-Encoding": "gzip",
      },
      redirect: "manual",
    },
  );
  assert.equal(compressedData.status, 401);
  assert.equal(compressedData.headers.get("location"), null);
  assert.equal(
    compressedData.headers.get("cache-control"),
    "no-store",
  );
  const identityData = await fetch(`${origin}/phase-4-part-1.data`, {
    headers: {
      Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
      "Accept-Encoding": "identity",
    },
    redirect: "manual",
  });
  assert.equal(identityData.status, 401);
  assert.equal(identityData.headers.get("location"), null);
  const etag = runtimeEtag;
  assert.ok(etag);

  const notModified = await fetch(`${origin}/open-toontown.js`, {
    headers: {
      Cookie: `${BOOTSTRAP_COOKIE}=${session}`,
      "If-None-Match": etag,
    },
  });
  assert.equal(notModified.status, 304);
} finally {
  child.kill("SIGTERM");
  if (child.exitCode === null) await once(child, "exit");
  await rm(fixture, { recursive: true, force: true });
  await rm(privateManifest, { force: true });
}

console.log("Production bootstrap gate smoke test passed");
