const loading = document.querySelector("#loading");
const status = document.querySelector("#status");
const progress = document.querySelector("#progress");
const transfer = document.querySelector("#transfer");
const canvas = document.querySelector("#canvas");
const browserCheck = document.querySelector("#browser-check");
const turnstileWidget = document.querySelector("#turnstile-widget");
const mobileControlsElement = document.querySelector("#mobile-controls");
const mobileStick = document.querySelector("#mobile-stick");
const mobileStickKnob = document.querySelector("#mobile-stick-knob");
const mobileFormElement = document.querySelector("#mobile-form-proxy");
const shell = document.querySelector(".shell");
const welcomeOverlay = document.querySelector("#welcome-overlay");
const welcomeAccept = document.querySelector("#welcome-accept");
const mobileFormInputs = Object.fromEntries(
  [...mobileFormElement.querySelectorAll("[data-mobile-form-field]")].map(
    (input) => [input.dataset.mobileFormField, input],
  ),
);
const runtimeAssetVersion = "__TOONTOWN_RUNTIME_VERSION__";
// Four Phase 4 streams plus the main data and WASM streams keep the entire
// overlapped boot inside the previously chosen 4-6 concurrent range.
const phasePartConcurrency = 4;

function initializeWelcomeGate() {
  const gate = window.ToontownWelcomeGate ?? {
    required: true,
    storageKey: "toontown-browser.welcome-acknowledged.v1",
  };
  window.ToontownWelcomeGate = gate;
  const required = gate.required !== false;
  welcomeOverlay.setAttribute("aria-hidden", required ? "false" : "true");
  shell.inert = required;
  if (!required) return;

  const accept = () => {
    try {
      localStorage.setItem(gate.storageKey, "1");
    } catch {
      // Dismiss for this page even when private storage is unavailable.
    }
    gate.required = false;
    shell.inert = false;
    welcomeOverlay.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("welcome-required");
    focusGameCanvas();
  };
  welcomeAccept.addEventListener("click", accept, { once: true });
  requestAnimationFrame(() => welcomeAccept.focus({ preventScroll: true }));
}

initializeWelcomeGate();

const browserGameServerStorageKey = "open-toontown.game-server";
const capturedKeyStorageKey = "open-toontown.captured-key";
const experimentalMouseLookAvailableKey =
  "open-toontown.experimental-mouse-look-available";
const freeCameraActiveKey = "open-toontown.free-camera-active";
const freeCameraPayloadKey = "open-toontown.free-camera-pov";
const freeCameraCopyStatusKey = "open-toontown.free-camera-copy-status";
const mobilePortraitRenderKey = "open-toontown.mobile-portrait-render";
const mobileControlsSmokeKey = "open-toontown.mobile-controls-smoke";
const mobileFormSmokeKey = "open-toontown.mobile-form-smoke";
const mobileControlsTestRequested =
  new URLSearchParams(window.location.search).get("mobile-controls-test") === "1";
const mobileFormTestRequested =
  new URLSearchParams(window.location.search).get("mobile-form-test") === "1";
const mobileInputCapable =
  mobileControlsTestRequested ||
  navigator.maxTouchPoints > 0 ||
  window.matchMedia("(pointer: coarse)").matches;
const portraitOrientation = window.matchMedia("(orientation: portrait)");
let capturedKeyGeneration = 0;

function syncMobilePortraitLayout() {
  const active = mobileInputCapable && portraitOrientation.matches;
  document.documentElement.classList.toggle("mobile-portrait", active);
  try {
    localStorage.setItem(mobilePortraitRenderKey, active ? "1" : "0");
  } catch {
    // The Python client keeps its regular render resolution without storage.
  }
  if (!active) window.ToontownMobileControls?.releaseAll();
  window.ToontownMobileForm?.setPortraitActive(active);
}

syncMobilePortraitLayout();
portraitOrientation.addEventListener?.("change", syncMobilePortraitLayout);
window.addEventListener("orientationchange", syncMobilePortraitLayout);

function versionedAssetUrl(path, version = runtimeAssetVersion) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}v=${encodeURIComponent(version)}`;
}

function createBrowserPerformanceTelemetry() {
  // Safari's small default Resource Timing buffer filled during the original
  // cold tutorial trace, which hid the late package request timings.  Phase
  // packages can legitimately create hundreds of resource entries.
  performance.setResourceTimingBufferSize?.(5_000);
  const endpoint = "/api/performance";
  const pending = [];
  const history = [];
  const maximumPending = 48;
  const maximumBatch = 12;
  const frameWindowMs = 15_000;
  let active = false;
  let activatedOnce = false;
  let flushTimer;
  let flushPromise;
  let currentState = "boot";
  let activePhase = "";
  let frameWindowStartedAt;
  let lastFrameAt;
  let frameCount = 0;
  let maxFrameGap = 0;
  let gaps100 = 0;
  let gaps250 = 0;
  let gaps1000 = 0;
  let watchdogWorker;
  let watchdogHeartbeatTimer;
  let sendWatchdogHeartbeat = () => {};
  let lastRuntimeErrorAt = -Infinity;
  let npcContext = { stage: "idle", movie: "other" };
  let scriptContext = { script: "other", command: "idle", step: 0 };
  let maxGapScript = "other";
  let maxGapCommand = "idle";
  let maxGapStep = 0;
  let hiddenStartedAt;
  let toonEntryStartedAt;
  let toonEntryGeneration = 0;
  let toonEntryTutorialGeneration = 0;
  let toonEntryFramePending;

  function browserFamily() {
    const userAgent = navigator.userAgent;
    if (/Edg|Chrome|Chromium|CriOS/i.test(userAgent)) return "chromium";
    if (/Firefox|FxiOS/i.test(userAgent)) return "firefox";
    if (/Safari/i.test(userAgent) && !/Chrome|Chromium|CriOS/i.test(userAgent)) {
      return "safari";
    }
    if (/AppleWebKit/i.test(userAgent)) return "webkit";
    return "other";
  }

  function deviceClass() {
    if (!mobileInputCapable) return "desktop";
    return Math.min(window.innerWidth, window.innerHeight) >= 600
      ? "tablet"
      : "mobile";
  }

  function coarseHardwareConcurrency() {
    const cores = Number(navigator.hardwareConcurrency);
    if (!Number.isFinite(cores) || cores < 1) return undefined;
    return [1, 2, 4, 8, 16, 32].find((bucket) => cores <= bucket) ?? 32;
  }

  function clientInfo() {
    const connection = navigator.connection;
    const effectiveType = ["slow-2g", "2g", "3g", "4g"].includes(
      connection?.effectiveType,
    ) ? connection.effectiveType : "unknown";
    return {
      browser: browserFamily(),
      device: deviceClass(),
      connection: effectiveType,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      dpr: window.devicePixelRatio,
      touch: mobileInputCapable,
      cores: coarseHardwareConcurrency(),
      memoryGb: Number.isFinite(navigator.deviceMemory)
        ? navigator.deviceMemory
        : undefined,
      rttMs: Number.isFinite(connection?.rtt) ? connection.rtt : undefined,
      downlinkMbps: Number.isFinite(connection?.downlink)
        ? connection.downlink
        : undefined,
      saveData: connection?.saveData === true,
    };
  }

  function scheduleFlush(delay = 1_000) {
    if (!active || flushTimer || !pending.length) return;
    flushTimer = window.setTimeout(() => {
      flushTimer = undefined;
      flush();
    }, delay);
  }

  function record(type, fields = {}) {
    const event = {
      type,
      atMs: Math.round(performance.now()),
      ...fields,
    };
    history.push(event);
    if (history.length > 100) history.shift();
    pending.push(event);
    if (pending.length > maximumPending) pending.shift();
    scheduleFlush();
  }

  function recordToonEntry(stage, now = performance.now()) {
    if (stage === "selected") {
      toonEntryStartedAt = now;
      toonEntryGeneration += 1;
      toonEntryTutorialGeneration = 0;
      toonEntryFramePending = undefined;
    } else if (toonEntryStartedAt === undefined) {
      return;
    }
    record("toon_entry", {
      stage,
      durationMs: Math.max(0, Math.round(now - toonEntryStartedAt)),
      state: currentState,
    });
  }

  function recordTutorialEntry() {
    if (
      toonEntryStartedAt === undefined ||
      toonEntryTutorialGeneration === toonEntryGeneration
    ) return;
    toonEntryTutorialGeneration = toonEntryGeneration;
    const markedAt = performance.now();
    recordToonEntry("tutorial_state", markedAt);
    toonEntryFramePending = {
      generation: toonEntryGeneration,
      markedAt,
    };
  }

  function startMainThreadWatchdog() {
    if (watchdogWorker || typeof Worker === "undefined") return;
    const workerSource = `
      let endpoint = "";
      let lastHeartbeat = Date.now();
      let lastWorkerTick = Date.now();
      let visible = true;
      let reported = false;
      let state = "boot";
      let npcStage = "idle";
      let movie = "other";
      let script = "other";
      let command = "idle";
      let step = 0;
      self.onmessage = ({ data }) => {
        if (!data || typeof data !== "object") return;
        if (data.type === "init") endpoint = data.endpoint;
        if (data.type !== "heartbeat") return;
        lastHeartbeat = Date.now();
        visible = data.visible === true;
        state = data.state;
        npcStage = data.npcStage;
        movie = data.movie;
        script = data.script;
        command = data.command;
        step = data.step;
        reported = false;
      };
      setInterval(() => {
        const now = Date.now();
        const workerGap = now - lastWorkerTick;
        lastWorkerTick = now;
        if (!endpoint || !visible || workerGap > 2500) {
          lastHeartbeat = now;
          reported = false;
          return;
        }
        const durationMs = now - lastHeartbeat;
        if (durationMs < 4000 || reported) return;
        reported = true;
        fetch(endpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ events: [{
            type: "main_thread_stall",
            atMs: Math.round(performance.now()),
            durationMs,
            state,
            npcStage,
            movie,
            script,
            command,
            step,
          }] }),
        }).catch(() => {});
      }, 1000);
    `;
    const workerUrl = URL.createObjectURL(
      new Blob([workerSource], { type: "text/javascript" }),
    );
    watchdogWorker = new Worker(workerUrl);
    URL.revokeObjectURL(workerUrl);
    // A blob worker cannot reliably resolve a root-relative URL because its
    // own location uses the blob: scheme. Give it an absolute same-origin URL.
    watchdogWorker.postMessage({
      type: "init",
      endpoint: new URL(endpoint, window.location.href).href,
    });
    sendWatchdogHeartbeat = () => watchdogWorker?.postMessage({
      type: "heartbeat",
      visible: document.visibilityState === "visible",
      state: currentState,
      npcStage: npcContext.stage,
      movie: npcContext.movie,
      script: scriptContext.script,
      command: scriptContext.command,
      step: scriptContext.step,
    });
    sendWatchdogHeartbeat();
    watchdogHeartbeatTimer = window.setInterval(sendWatchdogHeartbeat, 500);
    document.addEventListener("visibilitychange", sendWatchdogHeartbeat);
  }

  async function flush() {
    if (!active || !pending.length) return true;
    if (flushPromise) return flushPromise;
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = undefined;
    }
    const events = pending.splice(0, maximumBatch);
    flushPromise = fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
      keepalive: true,
    }).then((response) => {
      if (!response.ok) throw new Error(`Performance log rejected: ${response.status}`);
      return true;
    }).catch(() => {
      pending.unshift(...events);
      if (pending.length > maximumPending) pending.length = maximumPending;
      return false;
    }).finally(() => {
      flushPromise = undefined;
      if (pending.length) scheduleFlush(10_000);
    });
    return flushPromise;
  }

  function flushWithBeacon() {
    if (!active || !pending.length || !navigator.sendBeacon) return;
    const events = pending.splice(0, maximumBatch);
    const body = new Blob(
      [JSON.stringify({ events })],
      { type: "application/json" },
    );
    if (!navigator.sendBeacon(endpoint, body)) pending.unshift(...events);
  }

  function resetFrameWindow(now) {
    frameWindowStartedAt = now;
    lastFrameAt = now;
    frameCount = 0;
    maxFrameGap = 0;
    gaps100 = 0;
    gaps250 = 0;
    gaps1000 = 0;
    maxGapScript = "other";
    maxGapCommand = "idle";
    maxGapStep = 0;
  }

  function recordLifecycle(visibility, awayMs = 0) {
    record("lifecycle", {
      visibility,
      awayMs: Math.max(0, Math.round(awayMs)),
      state: currentState,
    });
  }

  function handleVisibilityChange() {
    const now = performance.now();
    const visible = document.visibilityState === "visible";
    if (!active) {
      if (visible) resetFrameWindow(now);
      return;
    }
    if (visible) {
      const awayMs = hiddenStartedAt === undefined
        ? 0
        : Math.max(0, now - hiddenStartedAt);
      hiddenStartedAt = undefined;
      // requestAnimationFrame is suspended on iOS. Reset before its first
      // resumed callback so app switching is not misreported as a game stall.
      resetFrameWindow(now);
      recordLifecycle("visible", awayMs);
      scheduleFlush(0);
    } else {
      hiddenStartedAt = now;
      recordLifecycle("hidden", 0);
      flushWithBeacon();
    }
    sendWatchdogHeartbeat();
  }

  function sampleFrame(now) {
    if (!active || document.visibilityState !== "visible") {
      resetFrameWindow(now);
      window.requestAnimationFrame(sampleFrame);
      return;
    }
    if (frameWindowStartedAt === undefined) resetFrameWindow(now);
    if (
      toonEntryFramePending &&
      toonEntryFramePending.generation === toonEntryGeneration &&
      // A rAF timestamp belongs to the start of its frame.  Requiring it to
      // follow the Tutorial marker prevents a callback from the same frame
      // being counted before the newly rendered canvas has been presented.
      now > toonEntryFramePending.markedAt
    ) {
      toonEntryFramePending = undefined;
      recordToonEntry("first_frame", now);
      toonEntryStartedAt = undefined;
    }
    const gap = Math.max(0, now - lastFrameAt);
    lastFrameAt = now;
    frameCount += 1;
    if (gap > maxFrameGap) {
      maxFrameGap = gap;
      maxGapScript = scriptContext.script;
      maxGapCommand = scriptContext.command;
      maxGapStep = scriptContext.step;
    }
    if (gap >= 100) gaps100 += 1;
    if (gap >= 250) {
      gaps250 += 1;
      record("frame_gap", {
        durationMs: gap,
        state: currentState,
        script: scriptContext.script,
        command: scriptContext.command,
        step: scriptContext.step,
        ...(activePhase ? { phase: activePhase } : {}),
      });
    }
    if (gap >= 1_000) gaps1000 += 1;

    const elapsed = now - frameWindowStartedAt;
    if (elapsed >= frameWindowMs) {
      const fps = elapsed > 0 ? frameCount * 1_000 / elapsed : 0;
      if (fps < 50 || maxFrameGap >= 120) {
        record("frame_degraded", {
          windowMs: Math.round(elapsed),
          fps,
          maxGapMs: maxFrameGap,
          gaps100,
          gaps250,
          gaps1000,
          state: currentState,
          script: maxGapScript,
          command: maxGapCommand,
          step: maxGapStep,
          ...(activePhase ? { phase: activePhase } : {}),
        });
      }
      resetFrameWindow(now);
    }
    window.requestAnimationFrame(sampleFrame);
  }

  window.requestAnimationFrame(sampleFrame);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("pagehide", flushWithBeacon);

  return {
    activate() {
      active = true;
      startMainThreadWatchdog();
      if (activatedOnce) {
        scheduleFlush(0);
        return;
      }
      activatedOnce = true;
      resetFrameWindow(performance.now());
      record("session", clientInfo());
      record("state", { state: currentState });
    },
    flush,
    recordPhaseStart(fields) {
      activePhase = String(fields.phase);
      record("phase_start", fields);
    },
    recordPhaseComplete(fields) {
      if (activePhase === String(fields.phase)) activePhase = "";
      record("phase_complete", fields);
    },
    recordPhasePrefetchStart(fields) {
      activePhase = String(fields.phase);
      record("phase_prefetch_start", fields);
    },
    recordPhasePrefetchComplete(fields) {
      if (activePhase === String(fields.phase)) activePhase = "";
      record("phase_prefetch_complete", fields);
    },
    recordPhaseHandoff(fields) {
      record("phase_handoff", fields);
    },
    recordRuntimeReady(durationMs) {
      record("runtime_ready", {
        durationMs,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
      });
    },
    recordState(state) {
      if (state === currentState) return;
      currentState = state;
      record("state", { state });
    },
    recordToonSelection() {
      recordToonEntry("selected");
    },
    recordTutorialEntry,
    recordLifecycle,
    recordNpcMovie(stage, movie, elapsedMs = 0) {
      npcContext = { stage, movie };
      record("npc_movie", { stage, movie, elapsedMs, state: currentState });
    },
    recordGcPause(generation, durationMs) {
      record("gc_pause", {
        generation,
        durationMs,
        state: currentState,
      });
    },
    recordScriptStep(stage, script, durationMs) {
      record("script_step", {
        stage,
        script,
        durationMs,
        state: currentState,
      });
    },
    recordAvatarSetup(stage, durationMs) {
      record("avatar_setup", {
        stage,
        durationMs,
        state: currentState,
      });
    },
    recordInterfaceSetup(stage, durationMs) {
      record("interface_setup", {
        stage,
        durationMs,
        state: currentState,
      });
    },
    recordFrameStage(stage, durationMs) {
      record("frame_stage", {
        stage,
        durationMs,
        state: currentState,
        script: scriptContext.script,
        command: scriptContext.command,
        step: scriptContext.step,
      });
    },
    recordFrameCall(durationMs) {
      record("frame_call", {
        durationMs,
        state: currentState,
        script: scriptContext.script,
        command: scriptContext.command,
        step: scriptContext.step,
      });
    },
    recordIntervalPhase(phase, durationMs) {
      record("interval_phase", {
        phase,
        durationMs,
        state: currentState,
        script: scriptContext.script,
        command: scriptContext.command,
        step: scriptContext.step,
      });
    },
    recordIntervalFunction(callback, durationMs) {
      record("interval_function", {
        callback,
        durationMs,
        state: currentState,
        script: scriptContext.script,
        command: scriptContext.command,
        step: scriptContext.step,
      });
    },
    recordActorAnimation(operation, controls, lookupMs, controlMs) {
      record("actor_animation", {
        operation,
        controls,
        lookupMs,
        controlMs,
        state: currentState,
        script: scriptContext.script,
        command: scriptContext.command,
        step: scriptContext.step,
      });
    },
    recordBattleBuild(track, stage, attacks, durationMs) {
      record("battle_build", {
        track,
        stage,
        attacks,
        durationMs,
        state: currentState,
      });
    },
    recordBattleStage(stage, durationMs) {
      record("battle_stage", {
        stage,
        durationMs,
        state: currentState,
      });
    },
    recordBattleAsset(kind, asset, status, durationMs) {
      record("battle_asset", {
        kind,
        asset,
        status,
        durationMs,
        state: currentState,
      });
    },
    recordBattleSound(
      sound,
      requestStatus,
      requestCount,
      lookupStatus,
      resolveMs,
      managerMs,
      totalMs,
    ) {
      record("battle_sound", {
        sound,
        requestStatus,
        requestCount,
        lookupStatus,
        resolveMs,
        managerMs,
        totalMs,
        state: currentState,
      });
    },
    recordAudioBank(fields) {
      record("audio_bank", fields);
      scheduleFlush(0);
    },
    recordAudioLifecycle(fields) {
      record("audio_lifecycle", {
        ...fields,
        state: currentState,
      });
      scheduleFlush(0);
    },
    recordAnimationBind(actor, animation, controls, durationMs) {
      record("animation_bind", {
        actor,
        animation,
        controls,
        durationMs,
        state: currentState,
      });
    },
    recordActorIntervalBuild(actor, animation, durationMs) {
      record("actor_interval_build", {
        actor,
        animation,
        durationMs,
        state: currentState,
      });
    },
    setScriptCommand(script, command, step) {
      scriptContext = { script, command, step };
      sendWatchdogHeartbeat();
    },
    recordRuntimeError(category) {
      const now = performance.now();
      if (now - lastRuntimeErrorAt < 5_000) return;
      lastRuntimeErrorAt = now;
      record("runtime_error", { category, state: currentState });
      scheduleFlush(0);
    },
    snapshot() {
      return {
        active,
        state: currentState,
        phase: activePhase,
        pending: pending.map((event) => ({ ...event })),
        history: history.map((event) => ({ ...event })),
      };
    },
  };
}

window.ToontownPerformanceTelemetry = createBrowserPerformanceTelemetry();
window.ToontownAudioLifecycle?.setReporter((fields) => {
  window.ToontownPerformanceTelemetry.recordAudioLifecycle(fields);
});

function createTransportResumeToken() {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function isLocalDevelopmentPage() {
  const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(
    window.location.hostname,
  );
  return isLoopback && ["8080", "8180"].includes(window.location.port);
}

function localBrowserGameServerForPage() {
  const url = new URL("ws://127.0.0.1:7200/astron");
  // This token identifies only the lifetime of this loaded page. It is not an
  // account credential. Panda reuses it solely to rebind a backgrounded local
  // WebSocket to the same short-lived Astron transport.
  url.searchParams.set("resume", createTransportResumeToken());
  return url.href;
}

let browserGameServer = "";
let browserGameServerPromise;

function rememberBrowserGameServer(value) {
  browserGameServer = value;
  window.__toontownGameServer = value;
  try {
    localStorage.setItem(browserGameServerStorageKey, value);
  } catch {
    // The direct in-memory handoff is authoritative. Safari may deny storage
    // in private/backgrounded contexts without preventing gameplay.
  }
  return value;
}

async function prepareBrowserGameServer() {
  if (browserGameServer) return browserGameServer;
  if (browserGameServerPromise) return browserGameServerPromise;
  browserGameServerPromise = (async () => {
    if (isLocalDevelopmentPage()) {
      return rememberBrowserGameServer(localBrowserGameServerForPage());
    }
    const response = await fetch("/api/gateway/lease", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error("The secure game connection could not be prepared");
    }
    const material = await response.json();
    if (
      material?.version !== 1 ||
      typeof material.resume !== "string" ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(material.resume) ||
      typeof material.lease !== "string" ||
      material.lease.length > 2_048 ||
      !/^v1(?:\.[A-Za-z0-9_-]+){3}$/.test(material.lease) ||
      !Number.isFinite(material.expiresAt) ||
      material.expiresAt <= Date.now()
    ) {
      throw new Error("The secure game connection response was invalid");
    }
    const websocketProtocol =
      window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(
      `${websocketProtocol}//${window.location.host}/astron`,
    );
    url.searchParams.set("resume", material.resume);
    url.searchParams.set("lease", material.lease);
    return rememberBrowserGameServer(url.href);
  })().catch((error) => {
    browserGameServerPromise = undefined;
    throw error;
  });
  return browserGameServerPromise;
}

window.__toontownGameServer = "";
if (isLocalDevelopmentPage()) {
  rememberBrowserGameServer(localBrowserGameServerForPage());
}

function clearCapturedKey() {
  capturedKeyGeneration += 1;
  try {
    localStorage.setItem(capturedKeyStorageKey, "");
  } catch {
    // Browser storage may be unavailable in hardened/private contexts.
  }
}
try {
  localStorage.setItem(capturedKeyStorageKey, "");
  localStorage.setItem(experimentalMouseLookAvailableKey, "0");
  localStorage.setItem(freeCameraActiveKey, "0");
  localStorage.setItem(
    mobileControlsSmokeKey,
    mobileControlsTestRequested ? "1" : "0",
  );
  localStorage.setItem(
    mobileFormSmokeKey,
    mobileFormTestRequested ? "1" : "0",
  );
} catch {
  // The Python settings layer will fall back gracefully if storage is blocked.
}

window.addEventListener(
  "keydown",
  (event) => {
    if (mobileFormElement.contains(event.target)) {
      window.ToontownMobileForm?.handleKeyDown(event);
      event.stopImmediatePropagation();
      return;
    }
    try {
      if (event.repeat) return;

      if (
        localStorage.getItem(freeCameraActiveKey) === "1" &&
        event.key.toLowerCase() === "c" &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const payload = localStorage.getItem(freeCameraPayloadKey) ?? "";
        if (payload && navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(payload).then(
            () => localStorage.setItem(
              freeCameraCopyStatusKey,
              "POV copied to clipboard!",
            ),
            (error) => localStorage.setItem(
              freeCameraCopyStatusKey,
              `Copy failed: ${error?.message ?? error}`,
            ),
          );
        } else {
          localStorage.setItem(
            freeCameraCopyStatusKey,
            "Copy unavailable; send a screenshot of this panel.",
          );
        }
        return;
      }

      let key = "unsupported";
      if (event.key === "ArrowUp") key = "arrow_up";
      else if (event.key === "ArrowDown") key = "arrow_down";
      else if (event.key === "ArrowLeft") key = "arrow_left";
      else if (event.key === "ArrowRight") key = "arrow_right";
      else if (event.key === " ") key = "space";
      else if (event.key === "Control") key = "control";
      else if (event.key === "Shift") key = "shift";
      else if (event.key === "Alt") key = "alt";
      else if (event.key === "Escape") key = "escape";
      else if (event.key === "Home") key = "home";
      else if (event.key === "End") key = "end";
      else if (event.key === "Delete") key = "delete";
      else if (/^[a-zA-Z0-9]$/.test(event.key)) key = event.key.toLowerCase();

      localStorage.setItem(capturedKeyStorageKey, key);
      const generation = ++capturedKeyGeneration;
      setTimeout(() => {
        if (generation === capturedKeyGeneration) clearCapturedKey();
      }, 750);
    } catch {
      // Let Panda3D handle the key normally when browser storage is unavailable.
    }
  },
  { capture: true },
);

for (const eventName of ["keypress", "keyup"]) {
  window.addEventListener(
    eventName,
    (event) => {
      if (mobileFormElement.contains(event.target)) {
        event.stopImmediatePropagation();
      }
    },
    { capture: true },
  );
}

let lastLoaded = 0;
const classicLoadingTitle = "LOADING TOONTOWN...";
const bootShownAt = performance.now();
const bootMinimumVisibleMs = 1_400;
const bootDownloadProgress = {
  active: false,
  phase4: 0,
  runtime: 0,
};

function renderBootDownloadProgress() {
  if (!bootDownloadProgress.active) return;
  const combined =
    Math.min(1, bootDownloadProgress.phase4) * 32 +
    Math.min(1, bootDownloadProgress.runtime) * 40;
  progress.style.width = `${8 + combined}%`;
}

function focusGameCanvas() {
  if (document.activeElement === canvas) return;
  try {
    canvas.focus({ preventScroll: true });
  } catch {
    canvas.focus();
  }
}

function pandaAllowsMouseCapture() {
  const captureGate = window.Module?._browser_mouse_look_capture_allowed;
  if (typeof captureGate !== "function") return true;
  try {
    return captureGate() !== 0;
  } catch {
    // Keyboard turning remains available if the optional bridge is absent.
    return true;
  }
}

// Panda's Emscripten mousedown callback consumes the browser event. That can
// suppress the canvas element's native click-to-focus behavior, so restore
// focus during pointerdown, before Panda handles the following mousedown.
canvas.addEventListener("pointerdown", focusGameCanvas, { capture: true });
canvas.addEventListener("pointerdown", clearCapturedKey, { capture: true });
canvas.addEventListener(
  "pointerdown",
  (event) => {
    if (
      event.button !== 0 ||
      document.pointerLockElement === canvas
    ) return;
    try {
      if (localStorage.getItem(experimentalMouseLookAvailableKey) !== "1") {
        return;
      }
      if (!pandaAllowsMouseCapture()) return;
      window.__experimentalMouseLookPointerLock = "requesting";
      const request = canvas.requestPointerLock();
      if (request && typeof request.catch === "function") {
        request.catch((error) => {
          window.__experimentalMouseLookPointerLock =
            `error: ${error?.message ?? error}`;
        });
      }
    } catch (error) {
      window.__experimentalMouseLookPointerLock =
        `error: ${error?.message ?? error}`;
      // Pointer lock is optional; keyboard turning remains available.
    }
  },
  { capture: true },
);
document.addEventListener("pointerlockchange", () => {
  window.__experimentalMouseLookPointerLock =
    document.pointerLockElement === canvas ? "locked" : "released";
});
canvas.addEventListener("touchstart", focusGameCanvas, {
  capture: true,
  passive: true,
});

// Keep gameplay keys from scrolling the surrounding page while the canvas is
// focused. preventDefault does not stop the event from reaching Panda3D.
const browserScrollKeys = new Set([
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "End",
  "Home",
  " ",
]);
canvas.addEventListener(
  "keydown",
  (event) => {
    if (browserScrollKeys.has(event.key)) event.preventDefault();
  },
  { capture: true },
);

const mobileActionCodes = Object.freeze({
  forward: 1,
  reverse: 2,
  turnLeft: 3,
  turnRight: 4,
  sprint: 5,
  jump: 6,
  performAction: 7,
  exitActivity: 8,
  viewGags: 9,
  viewToonTasks: 10,
  viewStreetMap: 11,
  switchPov: 12,
});

const mobileFormActionCodes = Object.freeze({
  username: 20,
  password: 21,
  confirmPassword: 22,
  submit: 23,
  focusUsername: 24,
  focusPassword: 25,
  focusConfirmPassword: 26,
});

function callMobileBridge(actionCode) {
  const bridge = window.Module?._browser_mobile_action;
  if (typeof bridge !== "function") return false;
  try {
    return bridge(actionCode, 1) !== 0;
  } catch {
    return false;
  }
}

function createMobileFormProxy() {
  let mode = "none";
  let interactive = false;
  let portraitActive = mobileInputCapable && portraitOrientation.matches;

  function blurInputs() {
    for (const input of Object.values(mobileFormInputs)) input.blur();
  }

  function clearPasswords() {
    mobileFormInputs.password.value = "";
    mobileFormInputs.confirmPassword.value = "";
  }

  function render() {
    const visible =
      portraitActive && (mode === "login" || mode === "createAccount");
    const inputEnabled = visible && interactive;
    mobileFormElement.dataset.mode = visible ? mode : "none";
    mobileFormElement.dataset.interactive = inputEnabled ? "true" : "false";
    mobileFormElement.setAttribute(
      "aria-hidden",
      inputEnabled ? "false" : "true",
    );
    if (!inputEnabled) blurInputs();
    for (const input of Object.values(mobileFormInputs)) {
      input.disabled = !inputEnabled;
    }
    if (!visible) clearPasswords();
  }

  function setMode(nextMode, username = "", nextInteractive = true) {
    const normalizedMode = ["login", "createAccount"].includes(nextMode)
      ? nextMode
      : "none";
    const normalizedInteractive = Boolean(nextInteractive);
    if (
      normalizedMode !== mode ||
      (!interactive && normalizedInteractive)
    ) {
      blurInputs();
      clearPasswords();
    }
    mode = normalizedMode;
    interactive = normalizedInteractive;
    if (document.activeElement !== mobileFormInputs.username) {
      mobileFormInputs.username.value = username ?? "";
    }
    mobileFormInputs.password.autocomplete =
      mode === "createAccount" ? "new-password" : "current-password";
    mobileFormInputs.password.enterKeyHint =
      mode === "createAccount" ? "next" : "go";
    render();
  }

  function setPortraitActive(active) {
    portraitActive = Boolean(active);
    render();
  }

  function sendField(field) {
    const actionCode = mobileFormActionCodes[field];
    if (!actionCode) return false;
    return callMobileBridge(actionCode);
  }

  function focusField(field) {
    const focusAction = {
      username: mobileFormActionCodes.focusUsername,
      password: mobileFormActionCodes.focusPassword,
      confirmPassword: mobileFormActionCodes.focusConfirmPassword,
    }[field];
    if (focusAction) callMobileBridge(focusAction);
    mobileFormInputs[field]?.focus({ preventScroll: true });
  }

  function handleKeyDown(event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const field = event.target.dataset.mobileFormField;
    if (field === "username") {
      focusField("password");
    } else if (mode === "createAccount" && field === "password") {
      focusField("confirmPassword");
    } else {
      sendField(field);
      callMobileBridge(mobileFormActionCodes.submit);
    }
  }

  for (const [field, input] of Object.entries(mobileFormInputs)) {
    input.addEventListener("focus", () => focusField(field));
    input.addEventListener("input", () => sendField(field));
    input.addEventListener("change", () => sendField(field));
    input.addEventListener("paste", () => {
      window.setTimeout(() => sendField(field), 0);
    });
  }

  return {
    handleKeyDown,
    setMode,
    setPortraitActive,
    valueForField(field) {
      return mobileFormInputs[field]?.value ?? "";
    },
  };
}

function createMobileControls() {
  const pressedActions = new Set();
  const pressedButtons = new Map();
  const pointerButtons = new Map();
  const stickActions = new Set();
  let stickPointerId = null;
  let gameVisible = false;

  function sendAction(action, pressed) {
    const actionCode = mobileActionCodes[action];
    if (!actionCode) return false;
    if (pressed === pressedActions.has(action)) return true;

    const bridge = window.Module?._browser_mobile_action;
    if (typeof bridge !== "function") return false;
    try {
      if (bridge(actionCode, pressed ? 1 : 0) === 0) return false;
    } catch {
      return false;
    }

    if (pressed) pressedActions.add(action);
    else pressedActions.delete(action);
    return true;
  }

  function setButtonPressed(button, pressed, pointerId = null) {
    const action = button.dataset.mobileAction;
    if (!action) return;
    if (!sendAction(action, pressed)) return;
    button.classList.toggle("is-pressed", pressed);
    if (pressed) {
      pressedButtons.set(button, { action, pointerId });
      pointerButtons.set(pointerId, button);
      if (navigator.vibrate && action !== "sprint") navigator.vibrate(8);
    } else {
      pressedButtons.delete(button);
      if (pointerButtons.get(pointerId) === button) {
        pointerButtons.delete(pointerId);
      }
    }
  }

  function releaseButton(button, pointerId = null) {
    const activePress = pressedButtons.get(button);
    if (!activePress) return;
    if (
      pointerId !== null &&
      pointerId !== undefined &&
      activePress.pointerId !== pointerId
    ) return;
    setButtonPressed(button, false, activePress.pointerId);
  }

  function safelyCapturePointer(element, pointerId) {
    try {
      element.setPointerCapture?.(pointerId);
    } catch {
      // Global pointer-up recovery still prevents a stranded action when
      // Safari refuses capture during a rapidly changing multi-touch gesture.
    }
  }

  document.querySelectorAll("[data-mobile-action]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      if (
        pressedButtons.has(button) ||
        pointerButtons.has(event.pointerId)
      ) return;
      safelyCapturePointer(button, event.pointerId);
      setButtonPressed(button, true, event.pointerId);
    });
    for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
      button.addEventListener(eventName, (event) => {
        event.preventDefault();
        event.stopPropagation();
        releaseButton(button, event.pointerId);
      });
    }
    button.addEventListener("click", (event) => event.preventDefault());
    button.addEventListener("dblclick", (event) => event.preventDefault());
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  });

  function setStickActions(nextActions) {
    for (const action of stickActions) {
      if (!nextActions.has(action)) sendAction(action, false);
    }
    for (const action of nextActions) {
      if (!stickActions.has(action)) sendAction(action, true);
    }
    stickActions.clear();
    for (const action of nextActions) stickActions.add(action);
  }

  function updateStick(clientX, clientY) {
    const bounds = mobileStick.getBoundingClientRect();
    const centerX = bounds.left + bounds.width / 2;
    const centerY = bounds.top + bounds.height / 2;
    const maxDistance = bounds.width * 0.32;
    const rawX = clientX - centerX;
    const rawY = clientY - centerY;
    const distance = Math.hypot(rawX, rawY);
    const scale = distance > maxDistance ? maxDistance / distance : 1;
    const x = rawX * scale;
    const y = rawY * scale;
    const normalizedX = x / maxDistance;
    const normalizedY = y / maxDistance;
    const threshold = 0.28;
    const nextActions = new Set();
    if (normalizedY < -threshold) nextActions.add("forward");
    if (normalizedY > threshold) nextActions.add("reverse");
    if (normalizedX < -threshold) nextActions.add("turnLeft");
    if (normalizedX > threshold) nextActions.add("turnRight");
    setStickActions(nextActions);
    mobileStickKnob.style.transform =
      `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
  }

  function releaseStick(pointerId = null) {
    if (
      pointerId !== null &&
      pointerId !== undefined &&
      pointerId !== stickPointerId
    ) return;
    stickPointerId = null;
    setStickActions(new Set());
    mobileStickKnob.style.transform = "translate(-50%, -50%)";
  }

  mobileStick.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || stickPointerId !== null) return;
    event.preventDefault();
    event.stopPropagation();
    stickPointerId = event.pointerId;
    safelyCapturePointer(mobileStick, event.pointerId);
    updateStick(event.clientX, event.clientY);
  });
  mobileStick.addEventListener("pointermove", (event) => {
    if (event.pointerId !== stickPointerId) return;
    event.preventDefault();
    event.stopPropagation();
    updateStick(event.clientX, event.clientY);
  });
  for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
    mobileStick.addEventListener(eventName, (event) => {
      if (
        eventName !== "lostpointercapture" &&
        event.pointerId !== stickPointerId
      ) return;
      event.preventDefault();
      event.stopPropagation();
      releaseStick(event.pointerId);
    });
  }

  function releaseAll() {
    releaseStick();
    for (const button of [...pressedButtons.keys()]) releaseButton(button);
    for (const action of [...pressedActions]) sendAction(action, false);
    pointerButtons.clear();
  }

  // Pointer capture can be interrupted when iOS Safari starts a browser
  // gesture, changes apps, or retargets a fast multi-touch sequence. Recover
  // at the document boundary as well as on the individual control.
  for (const eventName of ["pointerup", "pointercancel"]) {
    document.addEventListener(
      eventName,
      (event) => {
        const button = pointerButtons.get(event.pointerId);
        if (button) releaseButton(button, event.pointerId);
        releaseStick(event.pointerId);
      },
      { capture: true },
    );
  }

  // lui.ss uses manipulation on its complete mobile surface to remove the
  // double-tap delay/zoom path. Keep that policy for the page, and use stricter
  // gesture suppression inside this full-screen game surface.
  for (const eventName of ["gesturestart", "gesturechange", "gestureend"]) {
    document.addEventListener(
      eventName,
      (event) => {
        if (
          mobileInputCapable &&
          portraitOrientation.matches &&
          event.cancelable
        ) event.preventDefault();
      },
      { capture: true, passive: false },
    );
  }

  // WebKit can still recognize a rapid pair of touchend events as a zoom
  // gesture even when the touched control declares touch-action: none. Cancel
  // only the second touchend on the game surface. Form controls remain exempt
  // so tapping an account field can continue to summon the software keyboard.
  let lastGameTouchEndAt = Number.NEGATIVE_INFINITY;
  document.addEventListener(
    "touchend",
    (event) => {
      if (!mobileInputCapable || !portraitOrientation.matches) return;
      if (
        event.target instanceof Element &&
        event.target.closest(
          "input, textarea, select, [contenteditable='true'], .welcome-overlay",
        )
      ) return;
      const now = performance.now();
      if (now - lastGameTouchEndAt < 450 && event.cancelable) {
        event.preventDefault();
      }
      lastGameTouchEndAt = now;
    },
    { capture: true, passive: false },
  );
  mobileControlsElement.addEventListener(
    "dblclick",
    (event) => event.preventDefault(),
    { capture: true },
  );

  function renderVisibility() {
    const visible =
      mobileInputCapable &&
      portraitOrientation.matches;
    mobileControlsElement.classList.toggle("is-visible", visible);
    mobileControlsElement.setAttribute("aria-hidden", visible ? "false" : "true");
    mobileControlsElement.dataset.gameReady = gameVisible ? "true" : "false";
    document.documentElement.classList.toggle("mobile-gameplay", visible);
    if (!visible) releaseAll();
  }

  function setGameVisible(visible) {
    gameVisible = Boolean(visible);
    renderVisibility();
  }

  window.addEventListener("blur", releaseAll);
  window.addEventListener("pagehide", releaseAll);
  document.addEventListener("freeze", releaseAll);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) releaseAll();
  });
  portraitOrientation.addEventListener?.("change", renderVisibility);
  renderVisibility();

  return { releaseAll, setGameVisible, renderVisibility };
}

window.ToontownMobileControls = createMobileControls();
window.addEventListener("toontownmobilecontrols", ({ detail }) => {
  window.ToontownMobileControls.setGameVisible(detail?.visible === true);
  // Mobile controls become visible during both the tutorial and ordinary
  // gameplay. Preserve the more specific tutorial state until Python emits
  // the exact tutorial_complete marker.
  if (
    detail?.visible === true &&
    window.ToontownPerformanceTelemetry.snapshot().state !== "tutorial"
  ) {
    window.ToontownPerformanceTelemetry.recordState("gameplay");
  }
});
window.ToontownMobileForm = createMobileFormProxy();
window.addEventListener("toontownmobileform", ({ detail }) => {
  window.ToontownMobileForm.setMode(
    detail?.mode,
    detail?.username ?? "",
    detail?.interactive !== false,
  );
  if (detail?.mode === "login") {
    window.ToontownPerformanceTelemetry.recordState("login");
  } else if (detail?.mode === "createAccount") {
    window.ToontownPerformanceTelemetry.recordState("create_account");
  }
});

const streamedPhaseOrder = [
  "3.5",
  "4",
  "5",
  "5.5",
  "6",
  "7",
  "8",
  "9",
  "10",
  "11",
  "12",
  "13",
  "news",
];
const coldStartPhaseOrder = new Set(["3.5"]);
const backgroundPhaseOrder = [
  "5",
  "5.5",
  "6",
  "8",
  "7",
  "9",
  "10",
  "11",
  "12",
  "13",
];
const streamedPhaseSource = new Map([
  ["news", "3.5"],
]);
let resolvePhaseFileSystemReady;
const phaseFileSystemReady = new Promise((resolve) => {
  resolvePhaseFileSystemReady = resolve;
});

class ToontownPhaseAssetLoader {
  constructor() {
    this.phases = new Map(
      streamedPhaseOrder.map((phase) => [phase, {
        state: coldStartPhaseOrder.has(phase) ? "ready" : "idle",
        fromCache: coldStartPhaseOrder.has(phase),
        promise: undefined,
        parts: new Map(),
        startedAt: undefined,
        prefetchState: "idle",
        prefetchPromise: undefined,
        prefetchFromCache: false,
        prefetchDurationMs: undefined,
      }]),
    );
    this.manifestPromise = undefined;
    this.playgroundPromise = undefined;
    this.backgroundPromise = undefined;
    this.persistenceRequested = false;
    this.aliasedSourcePhases = new Set();
    this.preloadedPackages = new Map();
    this.directHandoff = {
      activeParts: 0,
      activeBytes: 0,
      peakActiveParts: 0,
      peakActiveBytes: 0,
      networkParts: 0,
      cacheParts: 0,
      cacheFailures: 0,
      claims: 0,
      unclaimed: 0,
      phaseDurationMs: undefined,
      fallbackReason: undefined,
    };
  }

  normalizePhase(phase) {
    const normalized = String(phase);
    if (!this.phases.has(normalized)) {
      throw new Error(`Unknown Toontown phase: ${normalized}`);
    }
    return normalized;
  }

  phaseState(phase) {
    const state = this.phases.get(String(phase))?.state ?? "idle";
    return { idle: 0, loading: 1, ready: 2, error: 3 }[state];
  }

  phaseProgress(phase) {
    const normalized = String(phase);
    const record = this.phases.get(normalized);
    if (!record) return 0;
    if (record.state === "ready") return 100;
    const parts = [...record.parts.values()];
    const total = parts.reduce((sum, part) => sum + part.bytes, 0);
    if (!total) return 0;
    const downloads = window.Module?.dataFileDownloads ?? {};
    const loaded = parts.reduce((sum, part) => {
      if (part.state === "ready") return sum + part.bytes;
      const download = Object.entries(downloads).find(
        ([name]) => (
          name === part.data || name.endsWith(`/${part.data}`)
        ),
      )?.[1];
      return sum + Math.min(part.bytes, download?.loaded ?? 0);
    }, 0);
    return Math.max(
      0,
      Math.min(99, Math.floor((loaded / total) * 100)),
    );
  }

  getManifest() {
    if (!this.manifestPromise) {
      this.manifestPromise = fetch(
        versionedAssetUrl("phase-manifest.json"),
      ).then(
        async (response) => {
          if (!response.ok) {
            throw new Error(
              `Phase manifest request failed with ${response.status}`,
            );
          }
          const manifest = await response.json();
          if (manifest.version !== 2 || !Array.isArray(manifest.phases)) {
            throw new Error("Unsupported Toontown phase manifest");
          }
          return manifest;
        },
      );
    }
    return this.manifestPromise;
  }

  async getPhaseManifest(phase) {
    const normalized = this.normalizePhase(phase);
    const manifest = await this.getManifest();
    const phaseManifest = manifest.phases.find(
      (item) => String(item.phase) === normalized,
    );
    if (!phaseManifest?.parts?.length) {
      throw new Error(`Phase ${normalized} is missing from the manifest`);
    }
    return phaseManifest;
  }

  yieldToBrowser() {
    return new Promise((resolve) => {
      window.requestAnimationFrame(() => setTimeout(resolve, 0));
    });
  }

  async runConcurrent(items, task, concurrency = phasePartConcurrency) {
    let nextIndex = 0;
    const workerCount = Math.min(
      Math.max(1, Number(concurrency) || 1),
      items.length,
    );
    const workers = Array.from({ length: workerCount }, async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        await task(items[index], index);
      }
    });
    await Promise.all(workers);
  }

  async consumeResponse(response, onChunk) {
    if (!response.body) {
      const bytes = await response.arrayBuffer();
      onChunk(bytes.byteLength);
      return;
    }
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      onChunk(value.byteLength);
    }
  }

  supportsDirectHandoff() {
    return (
      typeof window.ToontownSecureAssetCache?.readPackageBuffer ===
        "function" &&
      typeof window.ToontownSecureAssetCache?.persistPackageBuffer ===
        "function" &&
      typeof window.crypto?.subtle?.digest === "function"
    );
  }

  async sha256Hex(buffer) {
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return Array.from(
      new Uint8Array(digest),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
  }

  registerPreloadedPackage(packageName, buffer, expectedBytes, source) {
    if (!(buffer instanceof ArrayBuffer)) {
      throw new Error("Direct phase handoff requires an ArrayBuffer");
    }
    if (buffer.byteLength !== expectedBytes) {
      throw new Error(
        `Direct phase handoff length mismatch for ${packageName}`,
      );
    }
    if (this.preloadedPackages.has(packageName)) {
      throw new Error(`Duplicate direct phase handoff for ${packageName}`);
    }
    this.preloadedPackages.set(packageName, {
      buffer,
      expectedBytes,
      source,
      registeredAt: performance.now(),
    });
  }

  claimPreloadedPackage(packageName, expectedBytes) {
    const entry = this.preloadedPackages.get(String(packageName));
    if (!entry) return null;
    if (
      Number(expectedBytes) !== entry.expectedBytes ||
      entry.buffer.byteLength !== entry.expectedBytes
    ) {
      this.preloadedPackages.delete(String(packageName));
      throw new Error(
        `Direct phase handoff claim mismatch for ${packageName}`,
      );
    }
    this.preloadedPackages.delete(String(packageName));
    this.directHandoff.claims += 1;
    return entry.buffer;
  }

  async handoffPhasePart(phase, part, onProgress) {
    const secureCache = window.ToontownSecureAssetCache;
    const partStartedAt = performance.now();
    const expectedBytes = Number(part.bytes);
    const packageName = versionedAssetUrl(part.data);
    this.directHandoff.activeParts += 1;
    this.directHandoff.peakActiveParts = Math.max(
      this.directHandoff.peakActiveParts,
      this.directHandoff.activeParts,
    );
    let packageRead;
    let readMs = 0;
    let verifyMs = 0;
    let mountMs = 0;
    let persistMs = 0;
    let cacheResult = { stored: false, skipped: true };
    try {
      const readStartedAt = performance.now();
      packageRead = await secureCache.readPackageBuffer(packageName);
      readMs = performance.now() - readStartedAt;
      if (!(packageRead.buffer instanceof ArrayBuffer)) {
        throw new Error(
          `Phase ${phase} part ${part.part} returned invalid package bytes`,
        );
      }
      if (packageRead.buffer.byteLength !== expectedBytes) {
        throw new Error(
          `Phase ${phase} part ${part.part} length mismatch: expected ` +
          `${expectedBytes}, received ${packageRead.buffer.byteLength}`,
        );
      }

      this.directHandoff.activeBytes += packageRead.buffer.byteLength;
      this.directHandoff.peakActiveBytes = Math.max(
        this.directHandoff.peakActiveBytes,
        this.directHandoff.activeBytes,
      );

      const verifyStartedAt = performance.now();
      const actualHash = await this.sha256Hex(packageRead.buffer);
      verifyMs = performance.now() - verifyStartedAt;
      if (actualHash !== part.sha256) {
        throw new Error(
          `Phase ${phase} part ${part.part} checksum mismatch`,
        );
      }

      if (packageRead.source === "encrypted_cache") {
        this.directHandoff.cacheParts += 1;
      } else {
        this.directHandoff.networkParts += 1;
      }

      const persistStartedAt = performance.now();
      const persistPromise = secureCache
        .persistPackageBuffer(packageRead)
        .then((result) => {
          persistMs = performance.now() - persistStartedAt;
          cacheResult = result;
          if (result.error) this.directHandoff.cacheFailures += 1;
          return result;
        });

      // Download, integrity verification, and cache encryption may overlap
      // engine startup. Loader execution waits for Panda's initialized
      // filesystem so no Phase 4 package becomes an Emscripten startup gate.
      await phaseFileSystemReady;
      this.registerPreloadedPackage(
        packageName,
        packageRead.buffer,
        expectedBytes,
        packageRead.source,
      );
      const mountStartedAt = performance.now();
      const mountPromise = this.requestPhasePart(phase, part, {
        expectedPreloadedName: packageName,
        source: packageRead.source,
      }).then((result) => {
        mountMs = performance.now() - mountStartedAt;
        return result;
      });
      await Promise.all([mountPromise, persistPromise]);

      onProgress(packageRead.buffer.byteLength);
      window.ToontownPerformanceTelemetry.recordPhaseHandoff({
        phase,
        stage: "part",
        part: part.part,
        bytes: packageRead.buffer.byteLength,
        source: packageRead.source,
        readMs,
        verifyMs,
        mountMs,
        persistMs,
        durationMs: performance.now() - partStartedAt,
        activeParts: this.directHandoff.activeParts,
        activeBytes: this.directHandoff.activeBytes,
        cacheStored: cacheResult.stored === true,
      });
    } finally {
      // Claimed packages are already removed synchronously by
      // getPreloadedPackage. This also releases an unclaimed registration
      // after a loader error, so a failed part cannot retain its buffer.
      this.preloadedPackages.delete(packageName);
      if (packageRead?.buffer instanceof ArrayBuffer) {
        this.directHandoff.activeBytes = Math.max(
          0,
          this.directHandoff.activeBytes - packageRead.buffer.byteLength,
        );
      }
      this.directHandoff.activeParts = Math.max(
        0,
        this.directHandoff.activeParts - 1,
      );
    }
  }

  handoffPhase(phase, onProgress = () => {}) {
    const normalized = this.normalizePhase(phase);
    const record = this.phases.get(normalized);
    if (record.state === "ready") return Promise.resolve(record);
    if (record.promise) return record.promise;
    if (!this.supportsDirectHandoff()) {
      this.directHandoff.fallbackReason = "unsupported";
      window.ToontownPerformanceTelemetry.recordPhaseHandoff({
        phase: normalized,
        stage: "fallback",
        reason: "unsupported",
      });
      return this.prefetchPhaseData(normalized, onProgress);
    }

    record.state = "loading";
    record.startedAt = performance.now();
    record.promise = (async () => {
      const phaseManifest = await this.getPhaseManifest(normalized);
      const assetBytes = phaseManifest.parts.reduce(
        (total, part) => total + Number(part.bytes ?? 0),
        0,
      );
      let loadedBytes = 0;
      let completedParts = 0;
      window.ToontownPerformanceTelemetry.recordPhaseStart({
        phase: normalized,
        parts: phaseManifest.parts.length,
        assetBytes,
        concurrency: phasePartConcurrency,
      });
      onProgress({
        loadedBytes,
        assetBytes,
        completedParts,
        parts: phaseManifest.parts.length,
      });
      await this.runConcurrent(
        phaseManifest.parts,
        async (part) => {
          await this.handoffPhasePart(
            normalized,
            part,
            (partBytes) => {
              loadedBytes = Math.min(assetBytes, loadedBytes + partBytes);
              completedParts += 1;
              onProgress({
                loadedBytes,
                assetBytes,
                completedParts,
                parts: phaseManifest.parts.length,
              });
            },
          );
          await this.yieldToBrowser();
        },
        phasePartConcurrency,
      );
      this.installFileSystemAliases(normalized);
      record.state = "ready";
      record.fromCache = this.directHandoff.networkParts === 0;
      const durationMs = performance.now() - record.startedAt;
      this.directHandoff.phaseDurationMs = durationMs;
      window.ToontownPerformanceTelemetry.recordPhaseComplete({
        phase: normalized,
        parts: phaseManifest.parts.length,
        assetBytes,
        concurrency: phasePartConcurrency,
        durationMs,
        fromCache: record.fromCache,
        processingMs: durationMs,
      });
      window.ToontownPerformanceTelemetry.recordPhaseHandoff({
        phase: normalized,
        stage: "complete",
        parts: phaseManifest.parts.length,
        bytes: assetBytes,
        durationMs,
        peakActiveParts: this.directHandoff.peakActiveParts,
        peakActiveBytes: this.directHandoff.peakActiveBytes,
        networkParts: this.directHandoff.networkParts,
        cacheParts: this.directHandoff.cacheParts,
        cacheFailures: this.directHandoff.cacheFailures,
        claims: this.directHandoff.claims,
      });
      window.__toontownPhaseDiagnostics = this.diagnostics();
      return record;
    })().catch((error) => {
      this.phasePackageFailed(normalized, error);
      window.ToontownPerformanceTelemetry.recordPhaseHandoff({
        phase: normalized,
        stage: "error",
        reason: /checksum/i.test(String(error))
          ? "checksum"
          : /length/i.test(String(error))
            ? "length"
            : "other",
      });
      throw error;
    });
    return record.promise;
  }

  prefetchPhaseData(phase, onProgress = () => {}) {
    const normalized = this.normalizePhase(phase);
    const record = this.phases.get(normalized);
    if (record.prefetchState === "ready") return Promise.resolve(record);
    if (record.prefetchPromise) return record.prefetchPromise;

    record.prefetchState = "loading";
    record.prefetchPromise = (async () => {
      const startedAt = performance.now();
      const phaseManifest = await this.getPhaseManifest(normalized);
      const assetBytes = phaseManifest.parts.reduce(
        (total, part) => total + Number(part.bytes ?? 0),
        0,
      );
      let loadedBytes = 0;
      let completedParts = 0;
      window.ToontownPerformanceTelemetry.recordPhasePrefetchStart({
        phase: normalized,
        parts: phaseManifest.parts.length,
        assetBytes,
        concurrency: phasePartConcurrency,
      });
      onProgress({
        loadedBytes,
        assetBytes,
        completedParts,
        parts: phaseManifest.parts.length,
      });
      await this.runConcurrent(phaseManifest.parts, async (part) => {
        const response = await fetch(versionedAssetUrl(part.data));
        if (!response.ok) {
          throw new Error(
            `Phase ${normalized} part ${part.part} data request failed with ` +
            `${response.status}`,
          );
        }
        await this.consumeResponse(response, (chunkBytes) => {
          loadedBytes = Math.min(assetBytes, loadedBytes + chunkBytes);
          onProgress({
            loadedBytes,
            assetBytes,
            completedParts,
            parts: phaseManifest.parts.length,
          });
        });
        completedParts += 1;
        onProgress({
          loadedBytes,
          assetBytes,
          completedParts,
          parts: phaseManifest.parts.length,
        });
        await this.yieldToBrowser();
      });
      await window.ToontownSecureAssetCache?.waitForIdle?.();

      const durationMs = performance.now() - startedAt;
      const resource = this.phaseResourceMetrics(
        startedAt,
        phaseManifest.parts,
      );
      record.prefetchState = "ready";
      record.prefetchFromCache = phaseManifest.parts.every(
        (part) => window.ToontownSecureAssetCache?.wasCacheHit(part.data),
      );
      record.prefetchDurationMs = durationMs;
      window.ToontownPerformanceTelemetry.recordPhasePrefetchComplete({
        phase: normalized,
        parts: phaseManifest.parts.length,
        assetBytes,
        concurrency: phasePartConcurrency,
        durationMs,
        fromCache: record.prefetchFromCache,
        ...resource,
        processingMs: Math.max(0, durationMs - resource.resourceMs),
      });
      window.__toontownPhaseDiagnostics = this.diagnostics();
      return record;
    })().catch((error) => {
      record.prefetchState = "error";
      window.__toontownPhaseDiagnostics = this.diagnostics();
      throw error;
    });
    return record.prefetchPromise;
  }

  requestPhase(phase) {
    const normalized = this.normalizePhase(phase);
    const record = this.phases.get(normalized);
    if (record.state === "ready") return Promise.resolve(record);
    if (record.promise) return record.promise;

    record.state = "loading";
    record.startedAt = performance.now();
    record.promise = (async () => {
      const phaseManifest = await this.getPhaseManifest(normalized);
      window.ToontownPerformanceTelemetry.recordPhaseStart({
        phase: normalized,
        parts: phaseManifest.parts.length,
        assetBytes: phaseManifest.parts.reduce(
          (total, part) => total + Number(part.bytes ?? 0),
          0,
        ),
      });
      await this.runConcurrent(phaseManifest.parts, async (part) => {
        await this.requestPhasePart(normalized, part);
        await this.yieldToBrowser();
      }, normalized === "4" ? phasePartConcurrency : 1);
      this.installFileSystemAliases(normalized);
      record.state = "ready";
      record.fromCache = [...record.parts.values()].every(
        (part) => part.fromCache,
      );
      const durationMs = performance.now() - record.startedAt;
      const resource = this.phaseResourceMetrics(
        record.startedAt,
        phaseManifest.parts,
      );
      window.ToontownPerformanceTelemetry.recordPhaseComplete({
        phase: normalized,
        parts: phaseManifest.parts.length,
        assetBytes: phaseManifest.parts.reduce(
          (total, part) => total + Number(part.bytes ?? 0),
          0,
        ),
        durationMs,
        fromCache: record.fromCache,
        ...resource,
        processingMs: Math.max(0, durationMs - resource.resourceMs),
      });
      window.__toontownPhaseDiagnostics = this.diagnostics();
      return record;
    })().catch((error) => {
      this.phasePackageFailed(normalized, error);
      throw error;
    });
    return record.promise;
  }

  requestPhasePart(phase, part, options = {}) {
    const record = this.phases.get(phase);
    const partRecord = {
      ...part,
      state: "loading",
      fromCache: false,
      resolve: undefined,
      reject: undefined,
      source: options.source,
    };
    record.parts.set(part.part, partRecord);
    const promise = new Promise((resolve, reject) => {
      partRecord.resolve = resolve;
      partRecord.reject = reject;
    });
    const script = document.createElement("script");
    script.async = true;
    // The loader and data archive are separate immutable HTTP resources. Use
    // a loader-specific version so a corrected/precompressed loader can never
    // be masked by a cached response keyed only to the data archive hash. The
    // fallback suffix also busts manifests cached before loaderSha256 existed.
    const loaderVersion = part.loaderSha256 ?? `${part.sha256}-loader-v2`;
    script.src = versionedAssetUrl(part.loader, loaderVersion);
    script.dataset.toontownPhase = phase;
    script.dataset.toontownPhasePart = String(part.part);
    script.addEventListener(
      "load",
      () => {
        const expectedName = options.expectedPreloadedName;
        if (!expectedName || !this.preloadedPackages.has(expectedName)) return;
        this.preloadedPackages.delete(expectedName);
        this.directHandoff.unclaimed += 1;
        this.phasePackagePartFailed(
          phase,
          part.part,
          new Error(
            `Phase ${phase} part ${part.part} did not claim its package`,
          ),
        );
      },
      { once: true },
    );
    script.addEventListener(
      "error",
      () => this.phasePackagePartFailed(
        phase,
        part.part,
        new Error(
          `Phase ${phase} part ${part.part} loader could not be downloaded`,
        ),
      ),
      { once: true },
    );
    document.body.append(script);
    return promise;
  }

  phaseResourceMetrics(startedAt, parts) {
    const names = new Set(
      parts.flatMap((part) => [part.loader, part.data]),
    );
    const resources = performance.getEntriesByType("resource").filter(
      (entry) => {
        if (entry.startTime < startedAt - 50) return false;
        try {
          const name = new URL(entry.name).pathname.split("/").pop();
          return names.has(name);
        } catch {
          return false;
        }
      },
    );
    const firstStartedAt = resources.reduce(
      (minimum, entry) => Math.min(minimum, Number(entry.startTime ?? Infinity)),
      Infinity,
    );
    const lastFinishedAt = resources.reduce(
      (maximum, entry) => Math.max(
        maximum,
        Number(entry.startTime ?? 0) + Number(entry.duration ?? 0),
      ),
      0,
    );
    return {
      requests: resources.length,
      transferBytes: resources.reduce(
        (total, entry) => total + Number(entry.transferSize ?? 0),
        0,
      ),
      encodedBytes: resources.reduce(
        (total, entry) => total + Number(entry.encodedBodySize ?? 0),
        0,
      ),
      decodedBytes: resources.reduce(
        (total, entry) => total + Number(entry.decodedBodySize ?? 0),
        0,
      ),
      resourceMs: Number.isFinite(firstStartedAt)
        ? Math.max(0, lastFinishedAt - firstStartedAt)
        : 0,
      maxRequestMs: resources.reduce(
        (maximum, entry) => Math.max(maximum, Number(entry.duration ?? 0)),
        0,
      ),
    };
  }

  phasePackagePartLoaded(phase, part, fromCache = false) {
    const normalized = this.normalizePhase(phase);
    const record = this.phases.get(normalized);
    const partRecord = record.parts.get(Number(part));
    if (!partRecord || partRecord.state === "ready") return;
    partRecord.state = "ready";
    partRecord.fromCache = Boolean(fromCache);
    partRecord.resolve?.(partRecord);
    partRecord.resolve = undefined;
    partRecord.reject = undefined;
    window.__toontownPhaseDiagnostics = this.diagnostics();
  }

  phasePackagePartFailed(phase, part, error) {
    const normalized = this.normalizePhase(phase);
    const partRecord = this.phases.get(normalized).parts.get(Number(part));
    if (!partRecord || partRecord.state === "error") return;
    partRecord.state = "error";
    partRecord.reject?.(error);
    partRecord.resolve = undefined;
    partRecord.reject = undefined;
  }

  installFileSystemAliases(phase) {
    const fileSystem = window.Module?.FS;
    if (!fileSystem) return;
    const ensureSymlink = (target, link) => {
      try {
        fileSystem.symlink(target, link);
      } catch (error) {
        try {
          fileSystem.lstat(link);
        } catch {
          throw error;
        }
      }
    };

    const phaseNames = ["phase_3", ...streamedPhaseOrder.filter(
      (item) => !streamedPhaseSource.has(item),
    ).map(
      (item) => `phase_${item}`,
    )];
    for (const phaseName of phaseNames) {
      ensureSymlink(`/resources/${phaseName}`, `/${phaseName}`);
    }

    const sourcePhase = streamedPhaseSource.get(phase) ?? phase;
    const sourceRoots = [
      ["3", "/resources/phase_3"],
      phase === "news"
        ? ["news", "/resources/phase_3.5/models/news"]
        : [sourcePhase, `/resources/phase_${sourcePhase}`],
    ];
    for (const [sourceKey, sourceRoot] of sourceRoots) {
      if (this.aliasedSourcePhases.has(sourceKey)) continue;
      const modelDirectories = [];
      const pending = [sourceRoot];
      while (pending.length) {
        const directory = pending.pop();
        const entries = fileSystem.readdir(directory).filter(
          (entry) => entry !== "." && entry !== "..",
        );
        if (entries.some((entry) => entry.endsWith(".bam"))) {
          modelDirectories.push(directory);
        }
        for (const entry of entries) {
          const child = `${directory}/${entry}`;
          if (fileSystem.isDir(fileSystem.stat(child).mode)) {
            pending.push(child);
          }
        }
      }

      for (const directory of modelDirectories) {
        for (const phaseName of phaseNames) {
          ensureSymlink(
            `/resources/${phaseName}`,
            `${directory}/${phaseName}`,
          );
        }
      }
      this.aliasedSourcePhases.add(sourceKey);
    }
  }

  phasePackageFailed(phase, error) {
    const normalized = this.normalizePhase(phase);
    const record = this.phases.get(normalized);
    if (record.state === "error") return;
    record.state = "error";
    console.error(`[Toontown phases] Phase ${normalized} failed`, error);
    window.__toontownPhaseDiagnostics = this.diagnostics();
  }

  requestPersistentStorage() {
    if (this.persistenceRequested) return;
    this.persistenceRequested = true;
    if (!navigator.storage?.persist) return;
    navigator.storage.persisted?.().then((persisted) => {
      if (!persisted) return navigator.storage.persist();
      return persisted;
    }).then((persisted) => {
      window.__toontownPhaseStoragePersistent = Boolean(persisted);
    }).catch(() => {
      window.__toontownPhaseStoragePersistent = false;
    });
  }

  preparePlayground() {
    this.requestPersistentStorage();
    if (!this.playgroundPromise) {
      this.playgroundPromise = (async () => {
        await this.requestPhase("3.5");
        await this.requestPhase("4");
      })();
      this.playgroundPromise.catch((error) => {
        console.error("[Toontown phases] Playground assets failed", error);
      });
    }
    return this.playgroundPromise;
  }

  startBackgroundDownloads() {
    this.requestPersistentStorage();
    if (!this.backgroundPromise) {
      window.__toontownBackgroundStartedAt = performance.now();
      this.backgroundPromise = (async () => {
        await this.preparePlayground();
        for (const phase of backgroundPhaseOrder) {
          await this.requestPhase(phase);
          await this.yieldToBrowser();
        }
      })();
      this.backgroundPromise.catch((error) => {
        console.error("[Toontown phases] Background download stopped", error);
      });
    }
    return this.backgroundPromise;
  }

  diagnostics() {
    return Object.fromEntries(
      [...this.phases].map(([phase, record]) => [phase, {
        state: record.state,
        progress: this.phaseProgress(phase),
        fromCache: record.fromCache,
        partsReady: [...record.parts.values()].filter(
          (part) => part.state === "ready",
        ).length,
        partsTotal: record.parts.size,
        prefetchState: record.prefetchState,
        prefetchFromCache: record.prefetchFromCache,
      prefetchDurationMs: record.prefetchDurationMs,
        ...(phase === "4" ? {
          directHandoff: {
            ...this.directHandoff,
            registeredPackages: this.preloadedPackages.size,
          },
        } : {}),
      }]),
    );
  }
}

window.ToontownAssetLoader = new ToontownPhaseAssetLoader();

window.Module = {
  canvas,
  getPreloadedPackage(packageName, packageSize) {
    return window.ToontownAssetLoader.claimPreloadedPackage(
      packageName,
      packageSize,
    );
  },
  locateFile(path, prefix = "") {
    const located = `${prefix}${path}`;
    if (/\.(?:data|wasm)$/.test(path)) {
      return versionedAssetUrl(located);
    }
    return located;
  },
  onRuntimeInitialized() {
    // Phase 3 and the early-game core of phase 3.5 are part of the blocking
    // cold-start package. Build the same cross-phase model aliases that
    // streamed packages install when they finish mounting.
    window.ToontownAssetLoader.installFileSystemAliases("3.5");
    window.ToontownShortAudioBanks?.attachModule(window.Module);
    resolvePhaseFileSystemReady();
  },
  print(...parts) {
    console.log("[Open Toontown]", ...parts);
  },
  printErr(...parts) {
    const message = parts.join(" ");
    const isError = /\(error\)|Assertion failed|Traceback|Aborted\(/i.test(message);
    if (isError) {
      window.ToontownPerformanceTelemetry.recordRuntimeError("python");
    }
    (isError ? console.error : console.warn)("[Open Toontown]", ...parts);
  },
  setStatus(message) {
    if (!message) return;
    status.textContent = classicLoadingTitle;

    const match = message.match(/\((\d+(?:\.\d+)?)\/(\d+)\)/);
    if (match) {
      const loaded = Number(match[1]);
      const total = Number(match[2]);
      if (total > 0 && loaded >= lastLoaded) {
        lastLoaded = loaded;
        bootDownloadProgress.runtime = loaded / total;
        renderBootDownloadProgress();
        transfer.textContent = "Downloading game files";
      }
    }
  },
  monitorRunDependencies(remaining) {
    if (remaining === 0) {
      progress.style.width = "82%";
      transfer.textContent = "Opening Toontown";
    }
  },
  onAbort(reason) {
    window.ToontownPerformanceTelemetry.recordRuntimeError("abort");
    showError(`Game runtime aborted: ${reason}`);
  },
};

function showError(message) {
  status.textContent = message;
  progress.style.width = "100%";
  loading.classList.add("is-error");
}

let runtimeReadyFinalized = false;

function finalizeRuntimeReady() {
  if (runtimeReadyFinalized) return;
  runtimeReadyFinalized = true;
  // The browser shell scales the canvas responsively while Panda owns the
  // drawing-buffer resolution selected in Video settings.  Panda's generic
  // ResizeObserver otherwise replaces that buffer with the CSS dimensions
  // once during startup (and again whenever the page layout changes).
  canvas._p3d_resizeObserver?.disconnect();
  progress.style.width = "100%";
  transfer.textContent = "Toontown is ready!";
  const elapsed = performance.now() - bootShownAt;
  window.ToontownPerformanceTelemetry.recordRuntimeReady(elapsed);
  const finishDelay = Math.max(450, bootMinimumVisibleMs - elapsed);
  setTimeout(() => loading.classList.add("is-done"), finishDelay);
  window.ToontownMobileControls.renderVisibility();
  focusGameCanvas();
}

window.addEventListener("toontownwasmstatus", ({ detail }) => {
  status.textContent = classicLoadingTitle;

  if (detail.phase === "python") {
    progress.style.width = "86%";
    transfer.textContent = "Starting the game";
  }
  if (detail.phase === "engine") {
    progress.style.width = "94%";
    transfer.textContent = "Entering Toontown";
  }
  if (detail.phase === "ready") {
    // Phase 4 continues mounting in the background while the player logs in.
    // Toon selection reuses that in-flight promise and waits only if the
    // player reaches it before the mount has completed.
    finalizeRuntimeReady();
  }
  if (detail.phase === "error") showError(detail.message);
});

window.addEventListener("error", (event) => {
  if (event.filename?.includes("open-toontown")) {
    window.ToontownPerformanceTelemetry.recordRuntimeError("javascript");
    showError(event.message || "The game runtime failed to load.");
  }
});

window.addEventListener("unhandledrejection", () => {
  window.ToontownPerformanceTelemetry.recordRuntimeError("promise");
});

const originalLog = console.log.bind(console);
console.log = (...parts) => {
  const line = parts.join(" ");
  window.ToontownShortAudioBanks?.handleCommand(line);
  const npcMovie = line.match(
    /\[BrowserPerformanceNPC\]\s+(start|ready|finish|timeout|stale|missing|clear)\s+(complete|incomplete|assign|choice|track_choice|cancel|reject|other)\s+(\d+)/,
  );
  if (npcMovie) {
    window.ToontownPerformanceTelemetry.recordNpcMovie(
      npcMovie[1],
      npcMovie[2],
      Number(npcMovie[3]),
    );
  }
  const gcPause = line.match(
    /\[BrowserPerformanceGC\]\s+([0-2])\s+(\d+)/,
  );
  if (gcPause) {
    window.ToontownPerformanceTelemetry.recordGcPause(
      Number(gcPause[1]),
      Number(gcPause[2]),
    );
  }
  const scriptStep = line.match(
    /\[BrowserPerformanceScript\]\s+(preload|prepare|setup|chapter)\s+(tutorial_assets|tutorial_intro|tutorial_tom|tutorial_book|tutorial_blocker|tutorial_reward|tutorial_gag_shop|other)\s+(\d+)/,
  );
  if (scriptStep) {
    window.ToontownPerformanceTelemetry.recordScriptStep(
      scriptStep[1],
      scriptStep[2],
      Number(scriptStep[3]),
    );
  }
  const avatarSetup = line.match(
    /\[BrowserPerformanceAvatar\]\s+(loading|construct|identity|generate|required_fields|announce|interface|playing|total)\s+(\d+)/,
  );
  if (avatarSetup) {
    window.ToontownPerformanceTelemetry.recordAvatarSetup(
      avatarSetup[1],
      Number(avatarSetup[2]),
    );
  }
  const interfaceSetup = line.match(
    /\[BrowserPerformanceInterface\]\s+(news_button|book|options|shard|map|inventory|quest|track|suit|photo|fish|optional_pages|golf|events|news|book_page|laff_meter|quest_map|purchase|controls|tutorial_assets|total)\s+(\d+)/,
  );
  if (interfaceSetup) {
    window.ToontownPerformanceTelemetry.recordInterfaceSetup(
      interfaceSetup[1],
      Number(interfaceSetup[2]),
    );
  }
  const scriptCommand = line.match(
    /\[BrowserPerformanceCommand\]\s+(tutorial_intro|tutorial_tom|tutorial_book|tutorial_blocker|tutorial_reward|tutorial_gag_shop|other)\s+(idle|dialogue|visibility|transform|animation|inventory|interface|audio|load|controls|finish)\s+(\d+)/,
  );
  if (scriptCommand) {
    window.ToontownPerformanceTelemetry.setScriptCommand(
      scriptCommand[1],
      scriptCommand[2],
      Number(scriptCommand[3]),
    );
  }
  const frameStage = line.match(
    /\[BrowserPerformanceFrameStage\]\s+(tasks|interval|collision|render|audio_late)\s+(\d+)/,
  );
  if (frameStage) {
    window.ToontownPerformanceTelemetry.recordFrameStage(
      frameStage[1],
      Number(frameStage[2]),
    );
  }
  const frameCall = line.match(
    /\[BrowserPerformanceFrameCall\]\s+(\d+)/,
  );
  if (frameCall) {
    window.ToontownPerformanceTelemetry.recordFrameCall(
      Number(frameCall[1]),
    );
  }
  const intervalPhase = line.match(
    /\[BrowserPerformanceIntervalPhase\]\s+(core|callbacks)\s+(\d+)/,
  );
  if (intervalPhase) {
    window.ToontownPerformanceTelemetry.recordIntervalPhase(
      intervalPhase[1],
      Number(intervalPhase[2]),
    );
  }
  const intervalFunction = line.match(
    /\[BrowserPerformanceIntervalFunction\]\s+(loop|play|request|setChatAbsolute|setLocalPageChat|setPageChat|setPlayRate|marker|scene|other)\s+(\d+)/,
  );
  if (intervalFunction) {
    window.ToontownPerformanceTelemetry.recordIntervalFunction(
      intervalFunction[1],
      Number(intervalFunction[2]),
    );
  }
  const actorAnimation = line.match(
    /\[BrowserPerformanceActorAnimation\]\s+(setPlayRate|play|loop)\s+(\d+)\s+(\d+)\s+(\d+)/,
  );
  if (actorAnimation) {
    window.ToontownPerformanceTelemetry.recordActorAnimation(
      actorAnimation[1],
      Number(actorAnimation[2]),
      Number(actorAnimation[3]),
      Number(actorAnimation[4]),
    );
  }
  const battleBuild = line.match(
    /\[BrowserPerformanceBattleBuild\]\s+(fire|sos|npc_sos|pet_sos|toon_up|trap|lure|sound|throw|squirt|drop|all)\s+(select|construct|total)\s+(\d+)\s+(\d+)/,
  );
  if (battleBuild) {
    window.ToontownPerformanceTelemetry.recordBattleBuild(
      battleBuild[1],
      battleBuild[2],
      Number(battleBuild[3]),
      Number(battleBuild[4]),
    );
  }
  const battleStage = line.match(
    /\[BrowserPerformanceBattleStage\]\s+(attack_dicts|toon_movie|suit_movie|play_total)\s+(\d+)/,
  );
  if (battleStage) {
    window.ToontownPerformanceTelemetry.recordBattleStage(
      battleStage[1],
      Number(battleStage[2]),
    );
  }
  const battleAsset = line.match(
    /\[BrowserPerformanceBattleAsset\]\s+(prop|sound|model|anims)\s+([a-z0-9][a-z0-9_.-]{0,63})\s+(cold|cached|lookup|load)\s+(\d+)/,
  );
  if (battleAsset) {
    window.ToontownPerformanceTelemetry.recordBattleAsset(
      battleAsset[1],
      battleAsset[2],
      battleAsset[3],
      Number(battleAsset[4]),
    );
  }
  const battleSound = line.match(
    /\[BrowserPerformanceBattleSound\]\s+([a-z0-9][a-z0-9_.-]{0,63})\s+(first|repeat)\s+(\d+)\s+(web_audio|retained|indexed|fallback)\s+(\d+)\s+(\d+)\s+(\d+)/,
  );
  if (battleSound) {
    window.ToontownPerformanceTelemetry.recordBattleSound(
      battleSound[1],
      battleSound[2],
      Number(battleSound[3]),
      battleSound[4],
      Number(battleSound[5]),
      Number(battleSound[6]),
      Number(battleSound[7]),
    );
  }
  const animationBind = line.match(
    /\[BrowserPerformanceAnimationBind\]\s+(toon|suit|prop|actor)\s+([a-z0-9][a-z0-9_.-]{0,63})\s+(\d+)\s+(\d+)/,
  );
  if (animationBind) {
    window.ToontownPerformanceTelemetry.recordAnimationBind(
      animationBind[1],
      animationBind[2],
      Number(animationBind[3]),
      Number(animationBind[4]),
    );
  }
  const actorIntervalBuild = line.match(
    /\[BrowserPerformanceActorIntervalBuild\]\s+(toon|suit|prop|actor)\s+([a-z0-9][a-z0-9_.-]{0,63})\s+(\d+)/,
  );
  if (actorIntervalBuild) {
    window.ToontownPerformanceTelemetry.recordActorIntervalBuild(
      actorIntervalBuild[1],
      actorIntervalBuild[2],
      Number(actorIntervalBuild[3]),
    );
  }
  if (line.includes("[BrowserPerformanceJourney] toon_selected")) {
    window.ToontownPerformanceTelemetry.recordToonSelection();
  }
  if (line.includes("[BrowserPerformanceState] tutorial_complete")) {
    window.ToontownPerformanceTelemetry.recordState("gameplay");
  } else if (line.includes("[BrowserPerformanceState] tutorial")) {
    window.ToontownPerformanceTelemetry.recordState("tutorial");
    window.ToontownPerformanceTelemetry.recordTutorialEntry();
  } else if (line.includes("[BrowserPerformanceState] make_a_toon")) {
    window.ToontownPerformanceTelemetry.recordState("make_a_toon");
  } else if (line.includes("AvatarChooser.enter")) {
    window.ToontownPerformanceTelemetry.recordState("avatar_chooser");
  } else if (
    line.includes("MAT - startingMakeAToon") ||
    line.includes("MakeAToon: enter")
  ) {
    window.ToontownPerformanceTelemetry.recordState("make_a_toon");
  } else if (
    line.includes("Tutorial movie:") ||
    line.includes("enterTutorialInterior") ||
    line.includes("TutorialStreet")
  ) {
    window.ToontownPerformanceTelemetry.recordState("tutorial");
  }
  if (line.includes("[BrowserNetworkTest] roundtrip-ok")) {
    window.__networkTestComplete = true;
  }
  if (line.includes("[BrowserInputTest] arrow-up")) {
    window.__inputTestCount = (window.__inputTestCount ?? 0) + 1;
  }
  if (line.includes("[BrowserInputTest] mouse1")) {
    window.__inputTestMouseCount = (window.__inputTestMouseCount ?? 0) + 1;
  }
  if (line.includes("[BrowserInputTest] forward-on")) {
    window.__keybindForwardCount = (window.__keybindForwardCount ?? 0) + 1;
  }
  if (line.includes("[BrowserInputTest] jump-on")) {
    window.__keybindJumpCount = (window.__keybindJumpCount ?? 0) + 1;
  }
  if (line.includes("[BrowserInputTest] sprint-on")) {
    window.__keybindSprintOnCount = (window.__keybindSprintOnCount ?? 0) + 1;
  }
  if (line.includes("[BrowserInputTest] sprint-off")) {
    window.__keybindSprintOffCount = (window.__keybindSprintOffCount ?? 0) + 1;
  }
  if (line.includes("[BrowserAudioTest] playing")) {
    window.__audioTestPlaying = true;
  }
  if (line.includes("[BrowserMobileInputTest]")) {
    window.__mobileInputLog = [...(window.__mobileInputLog ?? []), line];
  }
  if (line.includes("[BrowserMobileFormTest]")) {
    window.__mobileFormLog = [...(window.__mobileFormLog ?? []), line];
  }
  originalLog(...parts);
};

let gameRuntimePromise;

async function prepareBootAssetTickets(phaseManifest, audioManifest) {
  const names = [
    "open-toontown.data",
    "open-toontown.wasm",
    ...phaseManifest.parts.map((part) => part.data),
    ...(audioManifest
      ? window.ToontownShortAudioBanks.bootAssetNames(audioManifest)
      : []),
  ];
  const secureCache = window.ToontownSecureAssetCache;
  const ticketPool = window.ToontownAssetTicketPool;
  if (!secureCache || !ticketPool) {
    console.warn(
      "[Toontown boot] Secure asset helper unavailable; using redirects",
    );
    return { requested: names.length, issued: 0, fromCache: false };
  }
  const versioned = names.map((name) => versionedAssetUrl(name));
  const missing = await secureCache.missingAssetNames(versioned);
  if (!missing.length) {
    return { requested: 0, issued: 0, fromCache: true };
  }
  try {
    const result = await ticketPool.prepare(missing);
    return { ...result, fromCache: false };
  } catch (error) {
    console.warn(
      "[Toontown boot] Batched asset tickets unavailable; using redirects",
      error,
    );
    return { requested: missing.length, issued: 0, fromCache: false };
  }
}

function loadRuntimeScript() {
  const runtime = document.createElement("script");
  runtime.async = true;
  runtime.src = versionedAssetUrl("open-toontown.js");
  runtime.dataset.toontownRuntime = "true";
  return new Promise((resolve, reject) => {
    runtime.addEventListener("load", resolve, { once: true });
    runtime.addEventListener(
      "error",
      () => reject(new Error("The game runtime could not be downloaded")),
      { once: true },
    );
    document.body.append(runtime);
  });
}

function loadGameRuntime() {
  if (gameRuntimePromise) return gameRuntimePromise;
  if (document.querySelector('script[data-toontown-runtime]')) {
    return Promise.resolve(true);
  }
  window.ToontownPerformanceTelemetry.activate();
  browserCheck.hidden = true;
  loading.classList.remove("is-error");
  status.textContent = classicLoadingTitle;
  transfer.textContent = "Preparing game files";
  progress.style.width = "8%";
  gameRuntimePromise = (async () => {
    const [phaseManifest, audioManifest] = await Promise.all([
      window.ToontownAssetLoader.getPhaseManifest("4"),
      window.ToontownShortAudioBanks
        ?.loadManifest(versionedAssetUrl("audio-bank-manifest.json"))
        .catch((error) => {
          console.warn(
            "[Toontown audio] Manifest unavailable; Panda fallback remains active",
            error,
          );
          return undefined;
        }),
    ]);
    const tickets = await prepareBootAssetTickets(
      phaseManifest,
      audioManifest,
    );
    window.__toontownBootDiagnostics = {
      ticketBatch: tickets,
      phase4StartedAt: performance.now(),
      audioStartedAt: audioManifest ? performance.now() : undefined,
    };
    const audioPromise = audioManifest
      ? window.ToontownShortAudioBanks
        .prepareBootBanks((name) => versionedAssetUrl(name))
        .then((result) => {
          window.__toontownBootDiagnostics.audioCompletedAt =
            performance.now();
          window.__toontownBootDiagnostics.audio = result;
          return result;
        })
        .catch((error) => {
          window.__toontownBootDiagnostics.audioError =
            String(error?.message || error).slice(0, 240);
          // The original Panda/OpenAL path is deliberately retained.
          return undefined;
        })
      : Promise.resolve(undefined);
    window.__toontownAudioBankPromise = audioPromise;
    window.__toontownAudioDiagnostics = () =>
      window.ToontownShortAudioBanks?.diagnostics();
    bootDownloadProgress.active = true;
    const phasePromise = window.ToontownAssetLoader.handoffPhase(
      "4",
      ({ loadedBytes, assetBytes }) => {
        bootDownloadProgress.phase4 = assetBytes > 0
          ? loadedBytes / assetBytes
          : 0;
        renderBootDownloadProgress();
      },
    ).then((record) => {
      bootDownloadProgress.phase4 = 1;
      renderBootDownloadProgress();
      window.__toontownBootDiagnostics.phase4CompletedAt = performance.now();
      return record;
    });
    window.__toontownRequiredPhasePromise = phasePromise;
    window.__toontownBootDiagnostics.runtimeStartedAt = performance.now();
    const runtimePromise = loadRuntimeScript();
    await Promise.all([phasePromise, runtimePromise]);
    return true;
  })().catch((error) => {
    console.error("[Toontown boot] Required game files failed", error);
    showError("Required game files could not be downloaded.");
    gameRuntimePromise = undefined;
    return false;
  });
  return gameRuntimePromise;
}

async function launchGameRuntime() {
  await prepareBrowserGameServer();
  return loadGameRuntime();
}

function loadTurnstileScript() {
  return new Promise((resolve, reject) => {
    if (window.turnstile) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src =
      "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", reject, { once: true });
    document.head.append(script);
  });
}

async function startVerifiedRuntime() {
  try {
    const configResponse = await fetch("/api/bootstrap/config", {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!configResponse.ok) throw new Error("Bootstrap configuration failed");
    const config = await configResponse.json();
    if (!config.required) {
      await launchGameRuntime();
      return;
    }

    const sessionResponse = await fetch("/api/bootstrap/session", {
      cache: "no-store",
      credentials: "same-origin",
    });
    const session = sessionResponse.ok
      ? await sessionResponse.json()
      : { valid: false };
    if (session.valid === true) {
      await launchGameRuntime();
      return;
    }

    browserCheck.hidden = false;
    status.textContent = "VERIFYING BROWSER...";
    transfer.textContent = "This protects accounts and game bandwidth";
    await loadTurnstileScript();
    let turnstileWidgetId;
    let retryTimer;
    const retryTurnstile = (message) => {
      loading.classList.remove("is-error");
      status.textContent = "VERIFYING BROWSER...";
      transfer.textContent = message;
      if (retryTimer || turnstileWidgetId === undefined) return;
      retryTimer = setTimeout(() => {
        retryTimer = undefined;
        window.turnstile.reset(turnstileWidgetId);
      }, 2_500);
    };
    turnstileWidgetId = window.turnstile.render(turnstileWidget, {
      sitekey: config.siteKey,
      action: "bootstrap",
      appearance: "interaction-only",
      retry: "never",
      theme: "light",
      callback: async (token) => {
        try {
          const response = await fetch("/api/bootstrap/verify", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
          });
          if (!response.ok) throw new Error("Verification failed");
          if (retryTimer) clearTimeout(retryTimer);
        } catch {
          retryTurnstile("Verification needs another try");
          return;
        }
        try {
          await launchGameRuntime();
        } catch (error) {
          console.error("[Toontown boot] Secure game session failed", error);
          showError("The secure game connection could not be prepared.");
        }
      },
      "error-callback": (errorCode) => {
        const code = String(errorCode);
        const family = code.slice(0, 3);
        const retryable =
          ["300", "600"].includes(family) ||
          ["110600", "110620", "200500"].includes(code);
        if (retryable) {
          retryTurnstile("Cloudflare asked us to retry the check");
        } else {
          showError("Browser verification needs attention. Please refresh and try again.");
        }
        return true;
      },
      "expired-callback": () => {
        retryTurnstile("Verification expired; trying again");
      },
      "timeout-callback": () => {
        retryTurnstile("Verification timed out; trying again");
      },
      "unsupported-callback": () => {
        showError("This browser cannot run the verification check.");
      },
    });
  } catch (error) {
    if (String(error?.message ?? "").includes("secure game connection")) {
      showError("The secure game connection could not be prepared.");
    } else {
      showError("The browser verification service is unavailable.");
    }
  }
}

startVerifiedRuntime();
