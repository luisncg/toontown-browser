(() => {
  "use strict";

  const PROTOCOL = 2;
  const GAME_PROTOCOL = 2;
  const OFFICIAL_BUILD_PROTOCOL = 1;
  const OFFICIAL_ORIGIN = "https://toontown.lui.ss";
  const AUTHORIZATION_REFRESH_MS = 60_000;
  const RELEASE = /^[a-f0-9]{64}$/;
  const AUTHORIZATION_ID = /^[a-f0-9]{32}$/;
  const OPAQUE_TOKEN = /^ra2(?:\.[A-Za-z0-9_-]+){3}$/;
  const CHALLENGE_TOKEN = /^rc2(?:\.[A-Za-z0-9_-]+){3}$/;
  const OFFICIAL_BUILD_TOKEN = /^ob1(?:\.[A-Za-z0-9_-]+){3}$/;
  const GAME_STATE_TOKEN = /^gs2(?:\.[A-Za-z0-9_-]+){2}$/;
  const GAME_TRANSITION_TOKEN = /^gt2(?:\.[A-Za-z0-9_-]+){2}$/;
  const FEATURE_MODULE_TOKEN = /^gf2(?:\.[A-Za-z0-9_-]+){2}$/;
  const CHALLENGE = /^[A-Za-z0-9_-]{43}$/;
  const nativeFetch = window.fetch.bind(window);
  const encoder = new TextEncoder();
  const worldCapabilities = new Map();
  const transitionResults = new Map();
  const featureModules = new Map();
  const diagnostics = {
    configuredAt: 0,
    keyReadyAt: 0,
    authorizedAt: 0,
    authorizationMs: 0,
    signedRequests: 0,
    refreshes: 0,
    worldRequests: 0,
    worldHits: 0,
    gameSessions: 0,
    gameTransitions: 0,
    gameTransitionCommits: 0,
    featureModuleRequests: 0,
    featureModuleHits: 0,
    officialFailures: 0,
    errors: 0,
  };

  let required = false;
  let release = "";
  let pendingChallenge;
  let authorization;
  let authorizationPromise;
  let gameSession;
  let gameSessionPromise;
  let fatalReason = "";

  /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_START */
  function isLocalDevelopmentPage() {
    return ["127.0.0.1", "localhost", "::1"].includes(
      window.location.hostname,
    ) && ["8080", "8180"].includes(window.location.port);
  }
  /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_END */

  function reportSecurityReason(reason) {
    if (![
      "wrong-origin",
      "embedded-client",
      "invalid-build",
      "invalid-attestation",
    ].includes(reason)) return;
    const payload = JSON.stringify({
      reason,
      ...(RELEASE.test(release) ? { build: release } : {}),
    });
    nativeFetch(`${OFFICIAL_ORIGIN}/api/security/telemetry`, {
      method: "POST",
      mode: "no-cors",
      cache: "no-store",
      credentials: "omit",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: payload,
      keepalive: true,
    }).catch(() => {});
  }

  function failOfficialBuild(reason = "invalid-attestation") {
    if (fatalReason) return false;
    fatalReason = reason;
    diagnostics.officialFailures += 1;
    document.documentElement.classList.add("official-build-fatal");
    const overlay = document.querySelector("#official-build-overlay");
    overlay?.setAttribute("aria-hidden", "false");
    const pageShell = document.querySelector(".shell");
    if (pageShell) pageShell.inert = true;
    const gameCanvas = document.querySelector("#canvas");
    gameCanvas?.setAttribute("tabindex", "-1");
    reportSecurityReason(reason);
    return true;
  }

  function officialResponse(response, reason = "invalid-attestation") {
    if (
      response?.status === 403 &&
      response.headers.get("x-toontown-official-error") === "1"
    ) {
      failOfficialBuild(reason);
      return false;
    }
    return true;
  }

  function bootstrapHeaders(buildId) {
    if (!RELEASE.test(buildId ?? "")) {
      failOfficialBuild("invalid-build");
      return {};
    }
    return { "X-Toontown-Build": buildId };
  }

  let officialPageContext = true;
  /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_START */
  if (isLocalDevelopmentPage()) officialPageContext = false;
  /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_END */
  if (officialPageContext) {
    if (window.location.origin !== OFFICIAL_ORIGIN) {
      failOfficialBuild("wrong-origin");
    } else {
      try {
        if (window.top !== window.self) failOfficialBuild("embedded-client");
      } catch {
        failOfficialBuild("embedded-client");
      }
    }
  }

  function base64url(bytes) {
    let binary = "";
    for (const byte of new Uint8Array(bytes)) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary)
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replaceAll("=", "");
  }

  function randomNonce() {
    return base64url(crypto.getRandomValues(new Uint8Array(16)));
  }

  async function sha256Hex(value) {
    const bytes = typeof value === "string" ? encoder.encode(value) : value;
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(
      new Uint8Array(digest),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
  }

  const keyPromise = crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign", "verify"],
  ).then((keyPair) => {
    diagnostics.keyReadyAt = performance.now();
    return keyPair;
  });

  function validChallenge(value) {
    return (
      value?.version === PROTOCOL &&
      RELEASE.test(value.release ?? "") &&
      CHALLENGE.test(value.challenge ?? "") &&
      CHALLENGE_TOKEN.test(value.challengeToken ?? "") &&
      Number.isFinite(value.expiresAt) &&
      value.expiresAt > Date.now()
    );
  }

  function configure(value = {}) {
    required = value.required === true;
    if (
      required &&
      (
        value.officialOrigin !== OFFICIAL_ORIGIN ||
        !RELEASE.test(value.buildId ?? "") ||
        value.buildId !== value.release ||
        value.attestationRequired !== true ||
        value.attestationProtocol !== OFFICIAL_BUILD_PROTOCOL
      )
    ) {
      failOfficialBuild("invalid-build");
      return false;
    }
    if (typeof value.release === "string" && RELEASE.test(value.release)) {
      if (release && release !== value.release) {
        authorization = undefined;
        authorizationPromise = undefined;
        gameSession = undefined;
        gameSessionPromise = undefined;
        transitionResults.clear();
        featureModules.clear();
        worldCapabilities.clear();
      }
      release = value.release;
    }
    if (validChallenge(value.challenge)) {
      pendingChallenge = value.challenge;
    }
    diagnostics.configuredAt = performance.now();
    return !fatalReason;
  }

  function primeChallenge(value) {
    if (!validChallenge(value)) return false;
    if (release && value.release !== release) return false;
    release = value.release;
    pendingChallenge = value;
    return true;
  }

  async function fetchChallenge() {
    const response = await nativeFetch("/api/runtime/challenge", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...bootstrapHeaders(release),
      },
      body: "{}",
    });
    if (!officialResponse(response, "invalid-build")) {
      throw new Error("Official build attestation is required");
    }
    if (!response.ok) {
      throw new Error(`Runtime challenge failed with ${response.status}`);
    }
    const value = await response.json();
    if (!validChallenge(value) || (release && value.release !== release)) {
      throw new Error("Runtime challenge response is invalid");
    }
    release = value.release;
    return value;
  }

  async function createAuthorization(challenge) {
    const startedAt = performance.now();
    const keyPair = await keyPromise;
    const publicKey = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
    const message = encoder.encode([
      "toontown-browser-runtime-registration-v2",
      challenge.challenge,
      challenge.release,
      window.location.origin,
    ].join("\n"));
    const signature = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      keyPair.privateKey,
      message,
    );
    const response = await nativeFetch("/api/runtime/authorize", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...bootstrapHeaders(release),
      },
      body: JSON.stringify({
        challengeToken: challenge.challengeToken,
        publicKey: {
          kty: publicKey.kty,
          crv: publicKey.crv,
          x: publicKey.x,
          y: publicKey.y,
        },
        signature: base64url(signature),
      }),
    });
    if (!officialResponse(response, "invalid-attestation")) {
      throw new Error("Official build attestation is required");
    }
    if (!response.ok) {
      throw new Error(`Runtime authorization failed with ${response.status}`);
    }
    const value = await response.json();
    if (
      value?.version !== PROTOCOL ||
      value.release !== release ||
      !OPAQUE_TOKEN.test(value.authorization ?? "") ||
      !AUTHORIZATION_ID.test(value.authorizationId ?? "") ||
      value.officialBuild?.version !== OFFICIAL_BUILD_PROTOCOL ||
      value.officialBuild.buildId !== release ||
      !OFFICIAL_BUILD_TOKEN.test(value.officialBuild.attestation ?? "") ||
      !AUTHORIZATION_ID.test(value.officialBuild.attestationId ?? "") ||
      !Number.isFinite(value.officialBuild.expiresAt) ||
      value.officialBuild.expiresAt <= Date.now() + AUTHORIZATION_REFRESH_MS ||
      !Number.isFinite(value.expiresAt) ||
      value.expiresAt <= Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      throw new Error("Runtime authorization response is invalid");
    }
    diagnostics.authorizedAt = performance.now();
    diagnostics.authorizationMs = diagnostics.authorizedAt - startedAt;
    return Object.freeze(value);
  }

  async function prepare({ force = false } = {}) {
    if (fatalReason) {
      throw new Error("Official build attestation is required");
    }
    if (
      !required
      /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_START */
      || isLocalDevelopmentPage()
      /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_END */
    ) {
      return Object.freeze({
        version: PROTOCOL,
        release,
        local: true,
        authorizationId: "0".repeat(32),
        officialBuild: Object.freeze({
          version: OFFICIAL_BUILD_PROTOCOL,
          buildId: release,
          attestation: "",
          attestationId: "0".repeat(32),
          expiresAt: Number.MAX_SAFE_INTEGER,
        }),
        expiresAt: Number.MAX_SAFE_INTEGER,
      });
    }
    if (
      !force &&
      authorization &&
      authorization.expiresAt > Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      return authorization;
    }
    if (
      authorization &&
      authorization.expiresAt <= Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      authorization = undefined;
      authorizationPromise = undefined;
    }
    if (authorizationPromise && !force) return authorizationPromise;
    if (force) {
      authorization = undefined;
      authorizationPromise = undefined;
      pendingChallenge = undefined;
      diagnostics.refreshes += 1;
    }
    authorizationPromise = (async () => {
      const challenge = pendingChallenge && pendingChallenge.expiresAt > Date.now()
        ? pendingChallenge
        : await fetchChallenge();
      pendingChallenge = undefined;
      authorization = await createAuthorization(challenge);
      return authorization;
    })().catch((error) => {
      diagnostics.errors += 1;
      authorizationPromise = undefined;
      throw error;
    });
    return authorizationPromise;
  }

  async function signedRequest(pathname, bodyObject, { retry = true } = {}) {
    if (fatalReason) {
      throw new Error("Official build attestation is required");
    }
    if (
      !required
      /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_START */
      || isLocalDevelopmentPage()
      /* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_END */
    ) {
      return nativeFetch(pathname, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bodyObject),
      });
    }
    const current = await prepare();
    const body = JSON.stringify(bodyObject);
    const timestamp = String(Math.floor(Date.now() / 1_000));
    const nonce = randomNonce();
    const officialBuildId = current.officialBuild.attestationId;
    const bodyHash = await sha256Hex(encoder.encode(body));
    const message = encoder.encode([
      "toontown-browser-request-proof-v2",
      "POST",
      pathname,
      timestamp,
      nonce,
      bodyHash,
      current.authorizationId,
      officialBuildId,
    ].join("\n"));
    const keyPair = await keyPromise;
    const signature = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      keyPair.privateKey,
      message,
    );
    diagnostics.signedRequests += 1;
    const response = await nativeFetch(pathname, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Toontown-Authority": current.authorization,
        "X-Toontown-Authority-Id": current.authorizationId,
        "X-Toontown-Official-Build":
          current.officialBuild.attestation,
        "X-Toontown-Official-Build-Id": officialBuildId,
        "X-Toontown-Build": current.officialBuild.buildId,
        "X-Toontown-Proof-Time": timestamp,
        "X-Toontown-Proof-Nonce": nonce,
        "X-Toontown-Proof": base64url(signature),
      },
      body,
    });
    if (!officialResponse(response, "invalid-attestation")) return response;
    if (retry && [401, 403, 409].includes(response.status)) {
      await prepare({ force: true });
      return signedRequest(pathname, bodyObject, { retry: false });
    }
    return response;
  }

  async function prefetchWorld(zoneIds) {
    const currentGameSession = await prepareGameSession();
    const requested = [...new Set(
      (Array.isArray(zoneIds) ? zoneIds : [zoneIds])
        .map(Number)
        .filter((zoneId) => Number.isSafeInteger(zoneId) && zoneId >= 0),
    )].slice(0, 16);
    const now = Date.now();
    const missing = requested.filter((zoneId) => {
      const current = worldCapabilities.get(zoneId);
      if (current?.expiresAt > now + AUTHORIZATION_REFRESH_MS) {
        diagnostics.worldHits += 1;
        return false;
      }
      return true;
    });
    if (!missing.length) {
      return requested.map((zoneId) => worldCapabilities.get(zoneId));
    }
    diagnostics.worldRequests += 1;
    const response = await signedRequest(
      "/api/runtime/world-capabilities",
      {
        zoneIds: missing,
        ...(currentGameSession?.stateToken
          ? { stateToken: currentGameSession.stateToken }
          : {}),
      },
    );
    if (!response.ok) {
      throw new Error(`World capability request failed with ${response.status}`);
    }
    const value = await response.json();
    if (
      value?.version !== PROTOCOL ||
      value.release !== release ||
      value.officialBuildId !== authorization?.officialBuild.attestationId ||
      !Array.isArray(value.capabilities) ||
      value.capabilities.length !== missing.length
    ) {
      throw new Error("World capability response is invalid");
    }
    for (const capability of value.capabilities) {
      if (
        !Number.isSafeInteger(capability?.zoneId) ||
        !missing.includes(capability.zoneId) ||
        typeof capability.capability !== "string" ||
        !/^rw2(?:\.[A-Za-z0-9_-]+){3}$/.test(capability.capability) ||
        capability.officialBuildId !==
          authorization?.officialBuild.attestationId ||
        !Number.isFinite(capability.expiresAt) ||
        capability.expiresAt <= Date.now() ||
        !Array.isArray(capability.requiredPhases)
      ) {
        throw new Error("World capability entry is invalid");
      }
      if (
        capability.composition &&
        (
          capability.composition.zoneId !== capability.zoneId ||
          capability.composition.digest !== capability.compositionDigest ||
          !Array.isArray(capability.composition.presentationModules)
        )
      ) {
        throw new Error("World composition manifest is invalid");
      }
      worldCapabilities.set(capability.zoneId, Object.freeze(capability));
    }
    const moduleIds = [...new Set(value.capabilities.flatMap(
      (capability) => capability.composition?.presentationModules ?? [],
    ))];
    if (moduleIds.length) await prefetchFeatureModules(moduleIds);
    return requested.map((zoneId) => worldCapabilities.get(zoneId));
  }

  function getWorldCapability(zoneId) {
    const value = worldCapabilities.get(Number(zoneId));
    return value?.expiresAt > Date.now() ? value : undefined;
  }

  async function prefetchFeatureModules(moduleIds) {
    const requested = [...new Set(
      (Array.isArray(moduleIds) ? moduleIds : [moduleIds])
        .filter((moduleId) => (
          typeof moduleId === "string" &&
          /^[a-z0-9][a-z0-9_.-]{0,63}$/.test(moduleId)
        )),
    )].slice(0, 8);
    const now = Date.now();
    const missing = requested.filter((moduleId) => {
      const current = featureModules.get(moduleId);
      if (current?.expiresAt > now + AUTHORIZATION_REFRESH_MS) {
        diagnostics.featureModuleHits += 1;
        return false;
      }
      return true;
    });
    if (!missing.length) {
      return requested.map((moduleId) => featureModules.get(moduleId));
    }
    const state = await prepareGameSession();
    diagnostics.featureModuleRequests += 1;
    const response = await signedRequest("/api/runtime/feature-modules", {
      stateToken: state.stateToken,
      moduleIds: missing,
    });
    if (!response.ok) {
      throw new Error(`Feature module request failed with ${response.status}`);
    }
    const value = await response.json();
    if (
      value?.version !== GAME_PROTOCOL ||
      value.release !== release ||
      value.officialBuildId !== authorization?.officialBuild.attestationId ||
      !Array.isArray(value.modules) ||
      value.modules.length !== missing.length
    ) {
      throw new Error("Feature module response is invalid");
    }
    for (const module of value.modules) {
      const calculatedDigest = module?.module
        ? await sha256Hex(encoder.encode(JSON.stringify(module.module)))
        : "";
      if (
        !missing.includes(module?.moduleId) ||
        !FEATURE_MODULE_TOKEN.test(module.signature ?? "") ||
        typeof module.moduleDigest !== "string" ||
        !/^[a-f0-9]{64}$/.test(module.moduleDigest) ||
        module.moduleDigest !== calculatedDigest ||
        module.marker !== state.marker ||
        module.officialBuildId !== state.officialBuildId ||
        !module.module ||
        typeof module.module !== "object" ||
        !Number.isFinite(module.expiresAt) ||
        module.expiresAt <= Date.now()
      ) {
        throw new Error("Feature module entry is invalid");
      }
      featureModules.set(module.moduleId, Object.freeze(module));
    }
    return requested.map((moduleId) => featureModules.get(moduleId));
  }

  function validGameSession(value) {
    return (
      value?.version === GAME_PROTOCOL &&
      value.release === release &&
      value.officialBuildId === authorization?.officialBuild.attestationId &&
      AUTHORIZATION_ID.test(value.officialBuildId ?? "") &&
      GAME_STATE_TOKEN.test(value.stateToken ?? "") &&
      /^[A-Za-z0-9_-]{22}$/.test(value.marker ?? "") &&
      Number.isSafeInteger(value.sequence) &&
      value.sequence >= 0 &&
      Number.isFinite(value.expiresAt) &&
      value.expiresAt > Date.now()
    );
  }

  async function prepareGameSession({ force = false } = {}) {
    if (
      !force &&
      validGameSession(gameSession) &&
      gameSession.expiresAt > Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      return gameSession;
    }
    if (
      gameSession &&
      gameSession.expiresAt <= Date.now() + AUTHORIZATION_REFRESH_MS
    ) {
      gameSession = undefined;
      gameSessionPromise = undefined;
    }
    if (gameSessionPromise && !force) return gameSessionPromise;
    if (force) {
      gameSession = undefined;
      gameSessionPromise = undefined;
      transitionResults.clear();
    }
    gameSessionPromise = (async () => {
      const response = await signedRequest("/api/runtime/game-session", {});
      if (!response.ok) {
        throw new Error(`Game session request failed with ${response.status}`);
      }
      const value = await response.json();
      if (!validGameSession(value)) {
        throw new Error("Game session response is invalid");
      }
      gameSession = Object.freeze(value);
      diagnostics.gameSessions += 1;
      return gameSession;
    })().catch((error) => {
      diagnostics.errors += 1;
      gameSessionPromise = undefined;
      throw error;
    });
    return gameSessionPromise;
  }

  function gameSessionSnapshot() {
    return validGameSession(gameSession) ? gameSession : undefined;
  }

  function requestGameTransition(requestId, action, target) {
    const id = String(requestId ?? "");
    if (!/^[1-9]\d{0,9}$/.test(id) || transitionResults.has(id)) {
      return false;
    }
    transitionResults.set(id, Object.freeze({ pending: true }));
    (async () => {
      const state = await prepareGameSession();
      const response = await signedRequest("/api/runtime/game-transitions", {
        stateToken: state.stateToken,
        action,
        target,
      });
      if (!response.ok) {
        throw new Error(
          `Game transition request failed with ${response.status}`,
        );
      }
      const value = await response.json();
      if (
        value?.version !== GAME_PROTOCOL ||
        value.release !== release ||
        value.officialBuildId !== state.officialBuildId ||
        value.action !== action ||
        !GAME_TRANSITION_TOKEN.test(value.capability ?? "") ||
        !Number.isFinite(value.expiresAt) ||
        value.expiresAt <= Date.now()
      ) {
        throw new Error("Game transition response is invalid");
      }
      diagnostics.gameTransitions += 1;
      transitionResults.set(id, Object.freeze({
        ok: true,
        capability: value.capability,
        expiresAt: value.expiresAt,
      }));
    })().catch((error) => {
      diagnostics.errors += 1;
      transitionResults.set(id, Object.freeze({
        ok: false,
        error: String(error?.message ?? "transition request failed").slice(
          0,
          160,
        ),
      }));
    });
    return true;
  }

  function pollGameTransition(requestId) {
    const id = String(requestId ?? "");
    const value = transitionResults.get(id);
    if (!value || value.pending) return undefined;
    transitionResults.delete(id);
    return value;
  }

  function commitGameSessionState(value) {
    if (!validGameSession(value)) return false;
    if (
      gameSession &&
      (
        value.marker !== gameSession.marker ||
        value.sequence !== gameSession.sequence + 1
      )
    ) {
      return false;
    }
    gameSession = Object.freeze(value);
    gameSessionPromise = Promise.resolve(gameSession);
    diagnostics.gameTransitionCommits += 1;
    return true;
  }

  window.ToontownRuntimeAuthority = Object.freeze({
    configure,
    primeChallenge,
    prepare,
    signedRequest,
    prepareGameSession,
    gameSessionSnapshot,
    requestGameTransition,
    pollGameTransition,
    commitGameSessionState,
    prefetchWorld,
    prefetchFeatureModules,
    getWorldCapability,
    diagnostics: () => ({
      ...diagnostics,
      required,
      release,
      authorized: Boolean(
        authorization?.expiresAt > Date.now() + AUTHORIZATION_REFRESH_MS,
      ),
      authorizationExpiresAt: authorization?.expiresAt,
      officialBuildId: authorization?.officialBuild.attestationId,
      fatalReason,
      worldCapabilities: worldCapabilities.size,
      gameSessionReady: validGameSession(gameSession),
      gameSequence: gameSession?.sequence,
      transitionResults: transitionResults.size,
      featureModules: featureModules.size,
    }),
    bootstrapHeaders,
    failOfficialBuild,
    inspectOfficialResponse: officialResponse,
    isFatal: () => Boolean(fatalReason),
  });
})();
