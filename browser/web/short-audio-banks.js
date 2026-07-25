(() => {
  "use strict";

  const MANIFEST_VERSION = 1;
  const READY_FILE = "/browser-short-audio-banks.json";
  const IDLE_SUSPEND_MS = 3_000;
  const LEASE_HEARTBEAT_TIMEOUT_MS = 45_000;
  const VISIBLE_WATCHDOG_GRACE_MS = 20_000;
  const SAFE_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
  const SAFE_SOUND = /^[a-z0-9][a-z0-9_.-]{0,127}$/;
  const SAFE_ASSET = /^audio-bank-[a-z0-9.-]+\.data$/;
  const SAFE_HASH = /^[a-f0-9]{64}$/;

  function createBrowserAudioLifecycle() {
    const NativeAudioContext =
      window.AudioContext || window.webkitAudioContext;
    const contexts = new Map();
    const history = [];
    const foregroundTimers = new Set();
    let nextContextId = 1;
    let foregroundGeneration = 0;
    let hiddenGeneration = 0;
    let recoveredHiddenGeneration = 0;
    let postBackgroundGesturePending = false;
    let foregroundRecoveryPromise;
    let needsGestureRetry = false;
    let reporter;
    const stats = {
      contextsCreated: 0,
      foregrounds: 0,
      resumeAttempts: 0,
      successfulRecoveries: 0,
      gestureRecoveries: 0,
      forcedRestarts: 0,
      resumeFailures: 0,
    };

    function pageIsVisible() {
      return !document.hidden;
    }

    function contextShouldResume(record) {
      try {
        return record.shouldResume();
      } catch {
        return true;
      }
    }

    function resumableRecords() {
      return [...contexts.values()].filter(
        (record) =>
          record.context.state !== "closed" &&
          contextShouldResume(record),
      );
    }

    function updateGestureRetry() {
      needsGestureRetry = pageIsVisible() && resumableRecords().some(
        (record) => record.context.state !== "running",
      );
    }

    function report(stage, fields = {}) {
      const event = {
        stage,
        atMs: Math.round(performance.now()),
        ...fields,
      };
      history.push(event);
      if (history.length > 24) history.shift();
      try {
        reporter?.(event);
      } catch {
        // Audio recovery must never depend on optional telemetry.
      }
    }

    function register(
      context,
      label = "panda-openal",
      shouldResume = () => true,
    ) {
      if (!context || typeof context.resume !== "function") return context;
      let record = contexts.get(context);
      if (record) {
        record.label = label;
        record.shouldResume = shouldResume;
        updateGestureRetry();
        return context;
      }
      record = {
        id: nextContextId,
        label,
        context,
        shouldResume,
        registeredAt: Date.now(),
      };
      nextContextId += 1;
      contexts.set(context, record);
      stats.contextsCreated += 1;
      context.addEventListener?.("statechange", () => {
        updateGestureRetry();
      });
      updateGestureRetry();
      report("context_registered", {
        contextId: record.id,
        label: record.label,
        contextState: context.state,
      });
      return context;
    }

    async function resumeAll(
      trigger,
      fromGesture = false,
      forceRestartRunning = false,
    ) {
      if (!pageIsVisible()) {
        return { attempted: 0, recovered: 0, failed: 0 };
      }
      const candidates = resumableRecords().filter(
        (record) =>
          record.context.state !== "running" ||
          forceRestartRunning,
      );
      if (!candidates.length) {
        needsGestureRetry = false;
        return { attempted: 0, recovered: 0, failed: 0 };
      }
      stats.resumeAttempts += candidates.length;
      const beforeStates = candidates
        .map((record) => `${record.label}:${record.context.state}`)
        .join(",");
      const results = await Promise.all(candidates.map(async (record) => {
        try {
          let restarted = false;
          if (
            forceRestartRunning &&
            record.context.state === "running" &&
            typeof record.context.suspend === "function"
          ) {
            await record.context.suspend();
            restarted = true;
          }
          await record.context.resume();
          return {
            record,
            recovered: record.context.state === "running",
            failed: record.context.state !== "running",
            restarted,
          };
        } catch {
          return {
            record,
            recovered: false,
            failed: true,
            restarted: false,
          };
        }
      }));
      const recovered = results.filter((result) => result.recovered).length;
      const failed = results.filter((result) => result.failed).length;
      const restarted = results.filter((result) => result.restarted).length;
      stats.successfulRecoveries += recovered;
      stats.resumeFailures += failed;
      stats.forcedRestarts += restarted;
      if (fromGesture) stats.gestureRecoveries += recovered;
      updateGestureRetry();
      report("resume", {
        trigger,
        gesture: fromGesture,
        attempted: candidates.length,
        recovered,
        failed,
        forcedRestart: forceRestartRunning,
        restarted,
        beforeStates,
        afterStates: candidates
          .map((record) => `${record.label}:${record.context.state}`)
          .join(","),
        needsGestureRetry,
      });
      return { attempted: candidates.length, recovered, failed };
    }

    function clearForegroundTimers() {
      for (const timer of foregroundTimers) clearTimeout(timer);
      foregroundTimers.clear();
    }

    function handleForeground(trigger) {
      if (!pageIsVisible()) return;
      stats.foregrounds += 1;
      foregroundGeneration += 1;
      const generation = foregroundGeneration;
      const forceRestartRunning =
        hiddenGeneration > recoveredHiddenGeneration;
      if (forceRestartRunning) {
        recoveredHiddenGeneration = hiddenGeneration;
      }
      clearForegroundTimers();
      foregroundRecoveryPromise = resumeAll(
        trigger,
        false,
        forceRestartRunning,
      );
      for (const delay of [120, 500]) {
        const timer = setTimeout(() => {
          foregroundTimers.delete(timer);
          if (
            generation === foregroundGeneration &&
            pageIsVisible() &&
            needsGestureRetry
          ) {
            void resumeAll(`${trigger}_retry`);
          }
        }, delay);
        foregroundTimers.add(timer);
      }
    }

    function handleHidden() {
      foregroundGeneration += 1;
      hiddenGeneration += 1;
      postBackgroundGesturePending = true;
      clearForegroundTimers();
      report("hidden", {
        contextStates: [...contexts.values()]
          .map((record) => `${record.label}:${record.context.state}`)
          .join(","),
      });
    }

    function handleGesture() {
      if (postBackgroundGesturePending && pageIsVisible()) {
        postBackgroundGesturePending = false;
        const retryAfterForeground = () =>
          resumeAll("user_gesture", true, true);
        void (
          foregroundRecoveryPromise
            ? foregroundRecoveryPromise.then(
                retryAfterForeground,
                retryAfterForeground,
              )
            : retryAfterForeground()
        );
        return;
      }
      updateGestureRetry();
      if (needsGestureRetry) void resumeAll("user_gesture", true);
    }

    if (NativeAudioContext) {
      function TrackedAudioContext(...args) {
        return register(
          Reflect.construct(NativeAudioContext, args),
          "panda-openal",
        );
      }
      TrackedAudioContext.prototype = NativeAudioContext.prototype;
      try {
        Object.setPrototypeOf(TrackedAudioContext, NativeAudioContext);
      } catch {
        // Native static fields are not used by Panda3D's OpenAL bridge.
      }
      try {
        window.AudioContext = TrackedAudioContext;
        if (window.webkitAudioContext) {
          window.webkitAudioContext = TrackedAudioContext;
        }
      } catch {
        // Explicit registration still covers the short-audio bank. Browsers
        // used by this build expose writable constructors, including WebKit.
      }
    }

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) handleHidden();
      else handleForeground("visibility");
    });
    document.addEventListener("touchstart", handleGesture, {
      capture: true,
      passive: true,
    });
    document.addEventListener("pointerdown", handleGesture, {
      capture: true,
    });
    document.addEventListener("keydown", handleGesture, {
      capture: true,
    });
    window.addEventListener?.("pageshow", () => handleForeground("pageshow"));
    window.addEventListener?.("focus", () => handleForeground("focus"));

    return {
      register,
      handleForeground,
      resumeAll,
      setReporter(callback) {
        reporter = typeof callback === "function" ? callback : undefined;
      },
      diagnostics() {
        return {
          ...stats,
          pageVisible: pageIsVisible(),
          needsGestureRetry,
          contexts: [...contexts.values()].map((record) => ({
            id: record.id,
            label: record.label,
            state: record.context.state,
            ageMs: Date.now() - record.registeredAt,
            shouldResume: contextShouldResume(record),
          })),
          history: history.map((event) => ({ ...event })),
        };
      },
    };
  }

  window.ToontownAudioLifecycle =
    window.ToontownAudioLifecycle || createBrowserAudioLifecycle();

  function finiteNumber(value, minimum, maximum) {
    return (
      typeof value === "number" &&
      Number.isFinite(value) &&
      value >= minimum &&
      value <= maximum
    );
  }

  function validateLoopPoints(value, frameCount) {
    if (value === null) return null;
    if (
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      !Number.isSafeInteger(value.startFrame) ||
      !Number.isSafeInteger(value.endFrame) ||
      value.startFrame < 0 ||
      value.endFrame > frameCount ||
      value.startFrame >= value.endFrame
    ) {
      throw new Error("Short-audio bank loop points are invalid");
    }
    return Object.freeze({
      startFrame: value.startFrame,
      endFrame: value.endFrame,
    });
  }

  function validateManifest(value) {
    if (
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      value.version !== MANIFEST_VERSION ||
      !Array.isArray(value.banks) ||
      !value.banks.length
    ) {
      throw new Error("Short-audio bank manifest is invalid");
    }
    const ids = new Set();
    const logicalNames = new Set();
    const banks = value.banks.map((bank) => {
      if (
        !bank ||
        typeof bank !== "object" ||
        Array.isArray(bank) ||
        !SAFE_ID.test(bank.id || "") ||
        ids.has(bank.id) ||
        !SAFE_ASSET.test(bank.asset || "") ||
        !SAFE_HASH.test(bank.contentHash || "") ||
        !Number.isSafeInteger(bank.contentBytes) ||
        bank.contentBytes < 44 ||
        !Number.isSafeInteger(bank.sampleRate) ||
        bank.sampleRate < 8_000 ||
        bank.sampleRate > 192_000 ||
        !Number.isSafeInteger(bank.channels) ||
        ![1, 2].includes(bank.channels) ||
        !Number.isSafeInteger(bank.totalFrames) ||
        bank.totalFrames < 1 ||
        bank.kind !== "short-effects" ||
        bank.streaming !== false ||
        typeof bank.phase !== "string" ||
        !Array.isArray(bank.relevance) ||
        !bank.sounds ||
        typeof bank.sounds !== "object" ||
        Array.isArray(bank.sounds)
      ) {
        throw new Error("Short-audio bank entry is invalid");
      }
      ids.add(bank.id);
      const sounds = {};
      for (const [logicalName, sound] of Object.entries(bank.sounds)) {
        if (
          !SAFE_SOUND.test(logicalName) ||
          logicalNames.has(logicalName) ||
          !sound ||
          typeof sound !== "object" ||
          Array.isArray(sound) ||
          !Number.isSafeInteger(sound.startFrame) ||
          sound.startFrame < 0 ||
          !Number.isSafeInteger(sound.frameCount) ||
          sound.frameCount < 1 ||
          sound.startFrame + sound.frameCount > bank.totalFrames ||
          !finiteNumber(sound.defaultGain, 0, 4) ||
          typeof sound.fallbackPandaAsset !== "string" ||
          !sound.fallbackPandaAsset ||
          sound.fallbackPandaAsset.length > 256
        ) {
          throw new Error("Short-audio sound entry is invalid");
        }
        logicalNames.add(logicalName);
        sounds[logicalName] = Object.freeze({
          startFrame: sound.startFrame,
          frameCount: sound.frameCount,
          defaultGain: sound.defaultGain,
          loopPoints: validateLoopPoints(
            sound.loopPoints,
            sound.frameCount,
          ),
          fallbackPandaAsset: sound.fallbackPandaAsset,
        });
      }
      if (!Object.keys(sounds).length) {
        throw new Error("Short-audio bank has no sounds");
      }
      return Object.freeze({
        id: bank.id,
        asset: bank.asset,
        contentHash: bank.contentHash,
        contentBytes: bank.contentBytes,
        sampleRate: bank.sampleRate,
        channels: bank.channels,
        totalFrames: bank.totalFrames,
        kind: bank.kind,
        phase: bank.phase,
        relevance: Object.freeze([...bank.relevance]),
        streaming: false,
        sounds: Object.freeze(sounds),
      });
    });
    return Object.freeze({
      version: MANIFEST_VERSION,
      banks: Object.freeze(banks),
    });
  }

  async function sha256Hex(buffer) {
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return Array.from(
      new Uint8Array(digest),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
  }

  function readFourCc(view, offset) {
    if (offset < 0 || offset + 4 > view.byteLength) return "";
    return String.fromCharCode(
      view.getUint8(offset),
      view.getUint8(offset + 1),
      view.getUint8(offset + 2),
      view.getUint8(offset + 3),
    );
  }

  function decodePcm16Wave(bytes, bank) {
    const view = new DataView(bytes);
    if (
      view.byteLength < 44 ||
      readFourCc(view, 0) !== "RIFF" ||
      readFourCc(view, 8) !== "WAVE"
    ) {
      throw new Error(`${bank.id} audio bank is not a RIFF/WAVE file`);
    }
    let format;
    let dataOffset = -1;
    let dataBytes = -1;
    let offset = 12;
    while (offset + 8 <= view.byteLength) {
      const chunkId = readFourCc(view, offset);
      const chunkBytes = view.getUint32(offset + 4, true);
      const chunkOffset = offset + 8;
      const chunkEnd = chunkOffset + chunkBytes;
      if (chunkEnd > view.byteLength) {
        throw new Error(`${bank.id} audio bank has a truncated WAV chunk`);
      }
      if (chunkId === "fmt ") {
        if (chunkBytes < 16) {
          throw new Error(`${bank.id} audio bank format chunk is invalid`);
        }
        format = {
          encoding: view.getUint16(chunkOffset, true),
          channels: view.getUint16(chunkOffset + 2, true),
          sampleRate: view.getUint32(chunkOffset + 4, true),
          byteRate: view.getUint32(chunkOffset + 8, true),
          blockAlign: view.getUint16(chunkOffset + 12, true),
          bitsPerSample: view.getUint16(chunkOffset + 14, true),
        };
      } else if (chunkId === "data") {
        dataOffset = chunkOffset;
        dataBytes = chunkBytes;
      }
      offset = chunkEnd + (chunkBytes & 1);
    }
    const expectedBlockAlign = bank.channels * 2;
    if (
      !format ||
      format.encoding !== 1 ||
      format.channels !== bank.channels ||
      format.sampleRate !== bank.sampleRate ||
      format.bitsPerSample !== 16 ||
      format.blockAlign !== expectedBlockAlign ||
      format.byteRate !== bank.sampleRate * expectedBlockAlign ||
      dataOffset < 0 ||
      dataBytes !== bank.totalFrames * expectedBlockAlign
    ) {
      throw new Error(`${bank.id} PCM audio bank format is invalid`);
    }
    const channels = Array.from(
      { length: bank.channels },
      () => new Float32Array(bank.totalFrames),
    );
    for (let frame = 0; frame < bank.totalFrames; frame += 1) {
      const frameOffset = dataOffset + frame * expectedBlockAlign;
      for (let channel = 0; channel < bank.channels; channel += 1) {
        channels[channel][frame] =
          view.getInt16(frameOffset + channel * 2, true) / 32768;
      }
    }
    return channels;
  }

  function classifyBankError(error) {
    const message = String(error?.message || error).toLowerCase();
    if (message.includes("failed with")) return "fetch";
    if (message.includes("length")) return "length";
    if (message.includes("checksum")) return "checksum";
    if (
      message.includes("riff") ||
      message.includes("wave") ||
      message.includes("pcm") ||
      message.includes("format") ||
      message.includes("chunk")
    ) return "format";
    return "other";
  }

  class ShortAudioBankRuntime {
    constructor() {
      this.manifest = undefined;
      this.manifestPromise = undefined;
      this.context = undefined;
      this.masterGain = undefined;
      this.banks = new Map();
      this.sounds = new Map();
      this.audioBuffers = new Map();
      this.activeSources = new Map();
      this.leases = new Map();
      this.enabled = true;
      this.idleTimer = undefined;
      this.watchdogTimer = undefined;
      this.module = undefined;
      this.visibleSince = document.hidden ? 0 : Date.now();
      this.lastSoundRequestAt = 0;
      this.lastPlaybackAt = 0;
      this.unlockPromise = undefined;
      this.unlockGestureHandler = () => this.unlockFromGesture();
      this.stats = {
        bankFetches: 0,
        bankFailures: 0,
        decodedSounds: 0,
        plays: 0,
        stops: 0,
        leaseAcquires: 0,
        leaseReleases: 0,
        orphanedLeases: 0,
        suspends: 0,
        resumes: 0,
        metadataPublishes: 0,
        metadataPublishFailures: 0,
      };
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
          this.visibleSince = 0;
          this.clearIdleTimer();
          this.suspend("hidden");
        } else {
          this.visibleSince = Date.now();
          // Playback, rather than foregrounding alone, resumes the context.
        }
      });
      document.addEventListener("pointerdown", this.unlockGestureHandler, {
        capture: true,
      });
      document.addEventListener("keydown", this.unlockGestureHandler, {
        capture: true,
      });
    }

    async loadManifest(url) {
      if (this.manifest) return this.manifest;
      if (!this.manifestPromise) {
        this.manifestPromise = fetch(url, {
          credentials: "same-origin",
          cache: "no-cache",
        }).then(async (response) => {
          if (!response.ok) {
            throw new Error(
              `Short-audio manifest failed with ${response.status}`,
            );
          }
          this.manifest = validateManifest(await response.json());
          return this.manifest;
        }).catch((error) => {
          this.manifestPromise = undefined;
          throw error;
        });
      }
      return this.manifestPromise;
    }

    bootAssetNames(manifest = this.manifest) {
      if (!manifest) return [];
      return manifest.banks
        .filter((bank) => bank.phase === "boot")
        .map((bank) => bank.asset);
    }

    ensureContext() {
      if (this.context) return this.context;
      const AudioContextClass =
        window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        throw new Error("Web Audio is unavailable");
      }
      this.context = new AudioContextClass({ latencyHint: "interactive" });
      window.ToontownAudioLifecycle?.register(
        this.context,
        "short-audio-bank",
        () =>
          this.enabled &&
          (this.activeSources.size > 0 || this.leases.size > 0),
      );
      this.masterGain = this.context.createGain();
      this.masterGain.gain.value = this.enabled ? 1 : 0;
      this.masterGain.connect(this.context.destination);
      return this.context;
    }

    unlockFromGesture() {
      if (document.hidden || this.unlockPromise) return;
      const context = this.ensureContext();
      const finish = () => {
        this.unlockPromise = undefined;
        if (context.state !== "running") return;
        document.removeEventListener(
          "pointerdown",
          this.unlockGestureHandler,
          { capture: true },
        );
        document.removeEventListener(
          "keydown",
          this.unlockGestureHandler,
          { capture: true },
        );
        this.scheduleIdleSuspend();
      };
      if (context.state === "running") {
        finish();
        return;
      }
      this.stats.resumes += 1;
      this.unlockPromise = context.resume().then(finish).catch(() => {
        this.unlockPromise = undefined;
      });
    }

    async prepareBootBanks(resolveAssetUrl) {
      if (!this.manifest) {
        throw new Error("Short-audio manifest has not been loaded");
      }
      const banks = this.manifest.banks.filter(
        (bank) => bank.phase === "boot",
      );
      await Promise.all(
        banks.map((bank) => this.prepareBank(bank, resolveAssetUrl)),
      );
      this.publishReadyFile();
      return {
        banks: banks.length,
        sounds: banks.reduce(
          (count, bank) => count + Object.keys(bank.sounds).length,
          0,
        ),
      };
    }

    async prepareBank(bank, resolveAssetUrl) {
      const existing = this.banks.get(bank.id);
      if (existing?.state === "ready") return existing;
      if (existing?.promise) return existing.promise;
      const record = { state: "loading", promise: undefined };
      this.banks.set(bank.id, record);
      record.promise = (async () => {
        const startedAt = performance.now();
        const response = await fetch(resolveAssetUrl(bank.asset), {
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error(
            `${bank.id} audio bank failed with ${response.status}`,
          );
        }
        const bytes = await response.arrayBuffer();
        const fetchedAt = performance.now();
        if (bytes.byteLength !== bank.contentBytes) {
          throw new Error(`${bank.id} audio bank length is invalid`);
        }
        const checksum = await sha256Hex(bytes);
        if (checksum !== bank.contentHash) {
          throw new Error(`${bank.id} audio bank checksum is invalid`);
        }
        // The generated bank is signed, PCM16 RIFF/WAVE. Parse it directly
        // instead of asking Safari to initialize an OfflineAudioContext before
        // a user gesture. iOS may reject or defer that context, which would
        // silently leave the synchronous Panda fallback active.
        const decodedChannels = decodePcm16Wave(bytes, bank);
        const decodedAt = performance.now();

        for (const [logicalName, sound] of Object.entries(bank.sounds)) {
          const channelData = decodedChannels.map((frames) =>
            frames.slice(
              sound.startFrame,
              sound.startFrame + sound.frameCount,
            )
          );
          this.sounds.set(logicalName, Object.freeze({
            ...sound,
            bankId: bank.id,
            logicalName,
            sampleRate: bank.sampleRate,
            channels: bank.channels,
            channelData: Object.freeze(channelData),
          }));
        }
        record.state = "ready";
        record.fetchMs = Math.round(fetchedAt - startedAt);
        record.decodeMs = Math.round(decodedAt - fetchedAt);
        record.soundCount = Object.keys(bank.sounds).length;
        delete record.promise;
        this.stats.bankFetches += 1;
        this.stats.decodedSounds += record.soundCount;
        console.log(
          `[Toontown audio] Bank ${bank.id} ready: ` +
          `${record.soundCount} sounds, fetch ${record.fetchMs} ms, ` +
          `parse ${record.decodeMs} ms`,
        );
        this.publishReadyFile();
        window.ToontownPerformanceTelemetry?.recordAudioBank?.({
          bank: bank.id,
          stage: "ready",
          fetchMs: record.fetchMs,
          parseMs: record.decodeMs,
          sounds: record.soundCount,
          metadataPublished: record.metadataPublished === true,
        });
        this.scheduleIdleSuspend();
        return record;
      })().catch((error) => {
        record.state = "error";
        record.error = String(error?.message || error).slice(0, 240);
        delete record.promise;
        this.stats.bankFailures += 1;
        console.warn(
          `[Toontown audio] Bank ${bank.id} unavailable; ` +
          "Panda audio fallback remains active",
          error,
        );
        window.ToontownPerformanceTelemetry?.recordAudioBank?.({
          bank: bank.id,
          stage: "error",
          error: classifyBankError(error),
        });
        throw error;
      });
      return record.promise;
    }

    attachModule(module) {
      this.module = module;
      this.publishReadyFile();
    }

    publishReadyFile() {
      const FS = this.module?.FS;
      if (!FS || !this.sounds.size) return;
      const sounds = {};
      for (const [logicalName, sound] of this.sounds) {
        sounds[logicalName] = {
          bankId: sound.bankId,
          frameCount: sound.frameCount,
          sampleRate: sound.sampleRate,
          channels: sound.channels,
          length: sound.frameCount / sound.sampleRate,
          defaultGain: sound.defaultGain,
          loopPoints: sound.loopPoints,
          fallbackPandaAsset: sound.fallbackPandaAsset,
        };
      }
      try {
        FS.writeFile(
          READY_FILE,
          JSON.stringify({ version: MANIFEST_VERSION, sounds }),
          { encoding: "utf8" },
        );
        this.stats.metadataPublishes += 1;
        for (const [bankId, record] of this.banks) {
          if (record.state !== "ready") continue;
          record.metadataPublished = true;
          if (!record.metadataTelemetryPublished) {
            record.metadataTelemetryPublished = true;
            window.ToontownPerformanceTelemetry?.recordAudioBank?.({
              bank: bankId,
              stage: "published",
              sounds: record.soundCount,
              metadataPublished: true,
            });
          }
        }
      } catch (error) {
        this.stats.metadataPublishFailures += 1;
        this.metadataLastError =
          String(error?.message || error).slice(0, 160);
        console.warn("[Toontown audio] Could not publish bank metadata", error);
      }
    }

    clearIdleTimer() {
      if (this.idleTimer !== undefined) {
        clearTimeout(this.idleTimer);
        this.idleTimer = undefined;
      }
    }

    scheduleIdleSuspend() {
      this.clearIdleTimer();
      if (
        !this.context ||
        this.activeSources.size ||
        this.leases.size ||
        document.hidden
      ) {
        return;
      }
      this.idleTimer = setTimeout(() => {
        this.idleTimer = undefined;
        if (!this.activeSources.size && !this.leases.size) {
          this.suspend("idle");
        }
      }, IDLE_SUSPEND_MS);
    }

    suspend(_reason) {
      if (!this.context || this.context.state !== "running") return;
      this.stats.suspends += 1;
      void this.context.suspend().catch(() => {});
    }

    resumeForPlayback() {
      if (!this.context || document.hidden || !this.enabled) return;
      if (this.context.state === "suspended") {
        this.stats.resumes += 1;
        void this.context.resume().catch(() => {});
      }
    }

    stopProxy(proxyId) {
      const active = this.activeSources.get(proxyId);
      if (!active) return;
      this.activeSources.delete(proxyId);
      active.source.onended = null;
      try {
        active.source.stop();
      } catch {
        // A source may already have ended between the map lookup and stop.
      }
      try {
        active.source.disconnect();
        active.gain.disconnect();
        active.panner?.disconnect();
      } catch {
        // Disconnect is best-effort cleanup.
      }
      this.stats.stops += 1;
      this.scheduleIdleSuspend();
    }

    pruneExpiredSources() {
      const now = Date.now();
      for (const [proxyId, active] of this.activeSources) {
        if (!active.loop && active.expectedEndAt <= now) {
          this.stopProxy(proxyId);
        }
      }
    }

    play({
      proxyId,
      logicalName,
      offset,
      loop,
      volume,
      rate,
      balance,
      leaseToken,
    }) {
      this.lastSoundRequestAt = Date.now();
      const sound = this.sounds.get(logicalName);
      if (!sound || !this.enabled || document.hidden) return;
      this.pruneExpiredSources();
      this.stopProxy(proxyId);
      const context = this.ensureContext();
      this.clearIdleTimer();
      this.resumeForPlayback();

      const materializeStartedAt = performance.now();
      let audioBuffer = this.audioBuffers.get(logicalName);
      if (!audioBuffer) {
        audioBuffer = context.createBuffer(
          sound.channels,
          sound.frameCount,
          sound.sampleRate,
        );
        for (let channel = 0; channel < sound.channels; channel += 1) {
          audioBuffer.copyToChannel(sound.channelData[channel], channel);
        }
        this.audioBuffers.set(logicalName, audioBuffer);
      }
      const source = context.createBufferSource();
      source.buffer = audioBuffer;
      source.loop = loop;
      if (loop && sound.loopPoints) {
        source.loopStart =
          sound.loopPoints.startFrame / sound.sampleRate;
        source.loopEnd = sound.loopPoints.endFrame / sound.sampleRate;
      }
      source.playbackRate.value = rate;
      const gain = context.createGain();
      gain.gain.value = volume * sound.defaultGain;
      let panner;
      source.connect(gain);
      if (typeof context.createStereoPanner === "function") {
        panner = context.createStereoPanner();
        panner.pan.value = balance;
        gain.connect(panner);
        panner.connect(this.masterGain);
      } else {
        gain.connect(this.masterGain);
      }

      const duration = sound.frameCount / sound.sampleRate;
      const safeOffset = loop
        ? Math.max(0, offset) % duration
        : Math.min(Math.max(0, offset), Math.max(0, duration - 0.001));
      const active = {
        source,
        gain,
        panner,
        logicalName,
        leaseToken: leaseToken === "-" ? undefined : leaseToken,
        loop,
        startedAt: Date.now(),
        expectedEndAt: loop
          ? Number.POSITIVE_INFINITY
          : Date.now() + ((duration - safeOffset) / rate) * 1_000,
      };
      this.activeSources.set(proxyId, active);
      source.onended = () => {
        if (this.activeSources.get(proxyId)?.source === source) {
          this.activeSources.delete(proxyId);
          this.scheduleIdleSuspend();
        }
        try {
          source.disconnect();
          gain.disconnect();
          panner?.disconnect();
        } catch {
          // The graph is already disconnected.
        }
      };
      if (active.leaseToken) {
        const lease = this.leases.get(active.leaseToken);
        if (lease) lease.lastSoundAt = Date.now();
      }
      source.start(0, safeOffset);
      this.lastPlaybackAt = Date.now();
      this.stats.plays += 1;
      window.ToontownPerformanceTelemetry?.recordAudioBank?.({
        bank: sound.bankId,
        stage: "play",
        materializeMs: Math.round(
          performance.now() - materializeStartedAt,
        ),
      });
    }

    setProxyVolume(proxyId, volume) {
      const active = this.activeSources.get(proxyId);
      if (!active) return;
      const sound = this.sounds.get(active.logicalName);
      active.gain.gain.value = volume * (sound?.defaultGain ?? 1);
    }

    setProxyBalance(proxyId, balance) {
      const active = this.activeSources.get(proxyId);
      if (active?.panner) active.panner.pan.value = balance;
    }

    setEnabled(enabled) {
      this.enabled = enabled;
      if (this.masterGain) this.masterGain.gain.value = enabled ? 1 : 0;
      if (!enabled) {
        this.clearIdleTimer();
        this.suspend("disabled");
      }
      // Enabling does not resume the context; the next play request does.
    }

    acquireLease(token, movieId) {
      if (this.leases.has(token)) return;
      const now = Date.now();
      this.leases.set(token, {
        token,
        movieId,
        acquiredAt: now,
        lastHeartbeatAt: now,
        lastSoundAt: 0,
      });
      this.clearIdleTimer();
      this.stats.leaseAcquires += 1;
      this.ensureWatchdog();
    }

    releaseLease(token, _reason) {
      if (!this.leases.delete(token)) return;
      this.stats.leaseReleases += 1;
      if (!this.leases.size) this.stopWatchdog();
      this.scheduleIdleSuspend();
    }

    heartbeatLease(token) {
      const lease = this.leases.get(token);
      if (lease) lease.lastHeartbeatAt = Date.now();
    }

    ensureWatchdog() {
      if (this.watchdogTimer !== undefined) return;
      this.watchdogTimer = setInterval(() => this.runWatchdog(), 5_000);
    }

    stopWatchdog() {
      if (this.watchdogTimer === undefined) return;
      clearInterval(this.watchdogTimer);
      this.watchdogTimer = undefined;
    }

    runWatchdog() {
      if (
        document.hidden ||
        !this.visibleSince ||
        Date.now() - this.visibleSince < VISIBLE_WATCHDOG_GRACE_MS
      ) {
        return;
      }
      const now = Date.now();
      const tokensInUse = new Set(
        [...this.activeSources.values()]
          .map((source) => source.leaseToken)
          .filter(Boolean),
      );
      for (const [token, lease] of this.leases) {
        if (
          now - lease.lastHeartbeatAt > LEASE_HEARTBEAT_TIMEOUT_MS &&
          !tokensInUse.has(token)
        ) {
          this.leases.delete(token);
          this.stats.orphanedLeases += 1;
          console.warn(
            `[Toontown audio] Cleared orphaned battle lease ${token} ` +
            `for ${lease.movieId}`,
          );
        }
      }
      if (!this.leases.size) this.stopWatchdog();
      this.scheduleIdleSuspend();
    }

    handleCommand(line) {
      let match = line.match(
        /\[BrowserWebAudioCommand\]\s+play\s+(\d+)\s+([a-z0-9][a-z0-9_.-]{0,127})\s+([0-9.]+)\s+([01])\s+([0-9.]+)\s+([0-9.]+)\s+(-?[0-9.]+)\s+([a-z0-9_-]+|-)/,
      );
      if (match) {
        this.play({
          proxyId: Number(match[1]),
          logicalName: match[2],
          offset: Number(match[3]),
          loop: match[4] === "1",
          volume: Math.min(4, Math.max(0, Number(match[5]))),
          rate: Math.min(4, Math.max(0.05, Number(match[6]))),
          balance: Math.min(1, Math.max(-1, Number(match[7]))),
          leaseToken: match[8],
        });
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioCommand\]\s+stop\s+(\d+)/,
      );
      if (match) {
        this.stopProxy(Number(match[1]));
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioCommand\]\s+volume\s+(\d+)\s+([0-9.]+)/,
      );
      if (match) {
        this.setProxyVolume(
          Number(match[1]),
          Math.min(4, Math.max(0, Number(match[2]))),
        );
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioCommand\]\s+balance\s+(\d+)\s+(-?[0-9.]+)/,
      );
      if (match) {
        this.setProxyBalance(
          Number(match[1]),
          Math.min(1, Math.max(-1, Number(match[2]))),
        );
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioCommand\]\s+enabled\s+([01])/,
      );
      if (match) {
        this.setEnabled(match[1] === "1");
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioLease\]\s+acquire\s+([a-z0-9_-]+)\s+([a-z0-9_-]+)/,
      );
      if (match) {
        this.acquireLease(match[1], match[2]);
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioLease\]\s+release\s+([a-z0-9_-]+)\s+([a-z0-9_-]+)/,
      );
      if (match) {
        this.releaseLease(match[1], match[2]);
        return true;
      }
      match = line.match(
        /\[BrowserWebAudioLease\]\s+heartbeat\s+([a-z0-9_-]+)/,
      );
      if (match) {
        this.heartbeatLease(match[1]);
        return true;
      }
      return false;
    }

    diagnostics() {
      const now = Date.now();
      return {
        ...this.stats,
        contextState: this.context?.state ?? "uninitialized",
        enabled: this.enabled,
        pageVisible: !document.hidden,
        activeSources: this.activeSources.size,
        scheduledSources: 0,
        decodedSounds: this.sounds.size,
        materializedBuffers: this.audioBuffers.size,
        metadataLastError: this.metadataLastError,
        lastSoundRequestAt: this.lastSoundRequestAt,
        lastPlaybackAt: this.lastPlaybackAt,
        leases: [...this.leases.values()].map((lease) => ({
          token: lease.token,
          movieId: lease.movieId,
          ageMs: now - lease.acquiredAt,
          heartbeatAgeMs: now - lease.lastHeartbeatAt,
          lastSoundAgeMs: lease.lastSoundAt
            ? now - lease.lastSoundAt
            : null,
        })),
        banks: Object.fromEntries(
          [...this.banks].map(([id, record]) => [id, {
            state: record.state,
            fetchMs: record.fetchMs,
            decodeMs: record.decodeMs,
            soundCount: record.soundCount,
            error: record.error,
          }]),
        ),
      };
    }
  }

  window.ToontownShortAudioBanks = new ShortAudioBankRuntime();
})();
