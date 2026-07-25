import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";


class FakeAudioParam {
  constructor() {
    this.value = 0;
  }
}

class FakeNode {
  connect() {}
  disconnect() {}
}

class FakeSource extends FakeNode {
  constructor() {
    super();
    this.loop = false;
    this.playbackRate = new FakeAudioParam();
    this.started = false;
    this.stopped = false;
    this.onended = null;
  }

  start() {
    this.started = true;
  }

  stop() {
    this.stopped = true;
  }
}

class FakeBuffer {
  constructor(channels, frames, sampleRate) {
    this.numberOfChannels = channels;
    this.length = frames;
    this.sampleRate = sampleRate;
    this.channels = Array.from(
      { length: channels },
      () => new Float32Array(frames),
    );
  }

  copyToChannel(source, channel) {
    this.channels[channel].set(source);
  }
}

class FakeAudioContext {
  constructor() {
    this.state = "suspended";
    this.destination = {};
    this.resumeCalls = 0;
    this.suspendCalls = 0;
    this.resumeFailuresRemaining = 0;
    this.listeners = new Map();
  }

  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) ?? [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }

  emit(name) {
    for (const callback of this.listeners.get(name) ?? []) callback();
  }

  createGain() {
    const gain = new FakeNode();
    gain.gain = new FakeAudioParam();
    return gain;
  }

  createStereoPanner() {
    const panner = new FakeNode();
    panner.pan = new FakeAudioParam();
    return panner;
  }

  createBufferSource() {
    return new FakeSource();
  }

  createBuffer(channels, frames, sampleRate) {
    return new FakeBuffer(channels, frames, sampleRate);
  }

  resume() {
    this.resumeCalls += 1;
    if (this.resumeFailuresRemaining > 0) {
      this.resumeFailuresRemaining -= 1;
      return Promise.reject(new Error("User gesture required"));
    }
    this.state = "running";
    this.emit("statechange");
    return Promise.resolve();
  }

  suspend() {
    this.suspendCalls += 1;
    this.state = "suspended";
    this.emit("statechange");
    return Promise.resolve();
  }
}

const listeners = new Map();
function addListener(target, name, callback) {
  const callbacks = target.get(name) ?? [];
  callbacks.push(callback);
  target.set(name, callbacks);
}

function removeListener(target, name, callback) {
  const callbacks = target.get(name) ?? [];
  target.set(
    name,
    callbacks.filter((candidate) => candidate !== callback),
  );
}

function emit(target, name) {
  for (const callback of [...(target.get(name) ?? [])]) callback();
}

const document = {
  hidden: false,
  addEventListener(name, callback) {
    addListener(listeners, name, callback);
  },
  removeEventListener(name, callback) {
    removeListener(listeners, name, callback);
  },
};
const windowListeners = new Map();
let nextTimer = 1;
const timers = new Map();
const intervals = new Map();
const context = {
  console,
  document,
  window: undefined,
  AudioContext: FakeAudioContext,
  performance,
  Date,
  Map,
  Set,
  Object,
  Array,
  Number,
  String,
  Boolean,
  Math,
  RegExp,
  Promise,
  Error,
  JSON,
  setTimeout(callback) {
    const id = nextTimer++;
    timers.set(id, callback);
    return id;
  },
  clearTimeout(id) {
    timers.delete(id);
  },
  setInterval(callback) {
    const id = nextTimer++;
    intervals.set(id, callback);
    return id;
  },
  clearInterval(id) {
    intervals.delete(id);
  },
  addEventListener(name, callback) {
    addListener(windowListeners, name, callback);
  },
  removeEventListener(name, callback) {
    removeListener(windowListeners, name, callback);
  },
};
context.window = context;
vm.createContext(context);
const source = await readFile(
  new URL("../web/short-audio-banks.js", import.meta.url),
  "utf8",
);
vm.runInContext(source, context);

const runtime = context.ToontownShortAudioBanks;
const lifecycle = context.ToontownAudioLifecycle;
const pandaContext = new context.AudioContext();
runtime.ensureContext();
assert.equal(lifecycle.diagnostics().contexts.length, 2);
assert.equal(
  lifecycle.diagnostics().contexts.map((item) => item.label).join(","),
  "panda-openal,short-audio-bank",
);
runtime.sounds.set("test.ogg", {
  logicalName: "test.ogg",
  bankId: "test",
  frameCount: 22_050,
  sampleRate: 22_050,
  channels: 1,
  defaultGain: 0.5,
  loopPoints: null,
  channelData: [new Float32Array(22_050)],
});

assert.equal(
  runtime.handleCommand(
    "[BrowserWebAudioLease] acquire b1_battle-1 battle-1",
  ),
  true,
);
assert.equal(runtime.diagnostics().leases.length, 1);
assert.equal(
  runtime.handleCommand(
    "[BrowserWebAudioCommand] play 1 test.ogg 0.000000 0 " +
    "0.800000 1.000000 0.000000 b1_battle-1",
  ),
  true,
);
assert.equal(runtime.diagnostics().activeSources, 1);
assert.equal(runtime.context.state, "running");
assert.equal(runtime.activeSources.get(1).gain.gain.value, 0.4);
assert.equal(runtime.diagnostics().materializedBuffers, 1);

runtime.handleCommand("[BrowserWebAudioCommand] volume 1 0.500000");
assert.equal(runtime.activeSources.get(1).gain.gain.value, 0.25);
runtime.handleCommand("[BrowserWebAudioCommand] stop 1");
assert.equal(runtime.diagnostics().activeSources, 0);
runtime.handleCommand(
  "[BrowserWebAudioLease] release b1_battle-1 finish",
);
assert.equal(runtime.diagnostics().leases.length, 0);

runtime.handleCommand(
  "[BrowserWebAudioLease] acquire b2_battle-2 battle-2",
);
runtime.handleCommand(
  "[BrowserWebAudioLease] acquire b3_battle-3 battle-3",
);
runtime.releaseLease("b2_battle-2", "late-cleanup");
assert.equal(
  runtime.diagnostics().leases.map((lease) => lease.token).join(","),
  "b3_battle-3",
);

const lease = runtime.leases.get("b3_battle-3");
lease.lastHeartbeatAt = Date.now() - 60_000;
runtime.visibleSince = Date.now() - 30_000;
runtime.runWatchdog();
assert.equal(runtime.diagnostics().leases.length, 0);
assert.equal(runtime.diagnostics().orphanedLeases, 1);

document.hidden = true;
emit(listeners, "visibilitychange");
await pandaContext.suspend();
assert.equal(runtime.context.state, "suspended");
document.hidden = false;
emit(listeners, "visibilitychange");
await Promise.resolve();
await Promise.resolve();
assert.equal(
  runtime.context.state,
  "suspended",
  "an idle short-audio context should remain suspended",
);
assert.equal(
  pandaContext.state,
  "running",
  "foregrounding should restore Panda/OpenAL audio",
);

const resumeCallsBeforeRunningRecovery = pandaContext.resumeCalls;
const suspendCallsBeforeRunningRecovery = pandaContext.suspendCalls;
document.hidden = true;
emit(listeners, "visibilitychange");
document.hidden = false;
emit(listeners, "visibilitychange");
await new Promise((resolve) => setImmediate(resolve));
assert.equal(
  pandaContext.suspendCalls,
  suspendCallsBeforeRunningRecovery + 1,
  "foregrounding must reset a context that only claims to be running",
);
assert.equal(
  pandaContext.resumeCalls,
  resumeCallsBeforeRunningRecovery + 1,
);
assert.equal(pandaContext.state, "running");
assert.ok(lifecycle.diagnostics().forcedRestarts >= 1);

await pandaContext.suspend();
pandaContext.resumeFailuresRemaining = 1;
await lifecycle.resumeAll("failed-foreground");
assert.equal(pandaContext.state, "suspended");
assert.equal(lifecycle.diagnostics().needsGestureRetry, true);
emit(listeners, "pointerdown");
await new Promise((resolve) => setImmediate(resolve));
assert.equal(
  pandaContext.state,
  "running",
  "the next gesture should recover Safari-blocked audio",
);
assert.equal(lifecycle.diagnostics().gestureRecoveries, 1);

console.log("Short-audio bank runtime lifecycle tests passed");
