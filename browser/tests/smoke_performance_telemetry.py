"""Verify privacy-safe browser performance batches without loading the game."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    batches = []
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def capture_performance(route):
        batches.append(route.request.post_data_json)
        route.fulfill(
            status=202,
            content_type="application/json",
            body='{"ok":true}',
        )

    page.route("**/api/performance", capture_performance)
    page.route(
        "**/*.data*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/octet-stream",
            body=b"prefetch-fixture",
        ),
    )
    page.route("**/open-toontown.js*", lambda route: route.abort())
    page.goto(GAME_URL, wait_until="networkidle", timeout=30_000)
    page.wait_for_function(
        "window.ToontownPerformanceTelemetry?.snapshot().active === true",
        timeout=10_000,
    )
    page.evaluate("""
        async () => {
          const telemetry = window.ToontownPerformanceTelemetry;
          telemetry.recordState('avatar_chooser');
          console.log('[BrowserPerformanceJourney] toon_selected');
          await new Promise((resolve) => setTimeout(resolve, 25));
          console.log('[BrowserPerformanceState] tutorial');
          await new Promise((resolve) => setTimeout(resolve, 75));
          telemetry.recordPhaseStart({
            phase: '4',
            parts: 23,
            assetBytes: 54000000,
          });
          telemetry.recordPhaseComplete({
            phase: '4',
            parts: 23,
            assetBytes: 54000000,
            durationMs: 3200,
            fromCache: false,
            requests: 46,
            transferBytes: 18000000,
            encodedBytes: 17500000,
            decodedBytes: 54000000,
            resourceMs: 2700,
            maxRequestMs: 400,
            processingMs: 500,
          });
          telemetry.recordPhasePrefetchStart({
            phase: '4',
            parts: 23,
            assetBytes: 90583459,
            concurrency: 4,
          });
          telemetry.recordPhasePrefetchComplete({
            phase: '4',
            parts: 23,
            assetBytes: 90583459,
            concurrency: 4,
            durationMs: 6400,
            fromCache: false,
            requests: 23,
            transferBytes: 81418208,
            encodedBytes: 81404408,
            decodedBytes: 90980697,
            resourceMs: 5900,
            maxRequestMs: 1194,
            processingMs: 500,
          });
          telemetry.recordPhaseHandoff({
            phase: '4',
            stage: 'part',
            part: 7,
            bytes: 3926935,
            source: 'network',
            readMs: 145,
            verifyMs: 4,
            mountMs: 52,
            persistMs: 88,
            durationMs: 241,
            activeParts: 4,
            activeBytes: 15637362,
            cacheStored: true,
          });
          telemetry.recordPhaseHandoff({
            phase: '4',
            stage: 'complete',
            parts: 23,
            bytes: 90583459,
            durationMs: 8175,
            peakActiveParts: 4,
            peakActiveBytes: 15637362,
            networkParts: 23,
            cacheParts: 0,
            cacheFailures: 0,
            claims: 23,
          });
          telemetry.recordNpcMovie('start', 'complete', 12);
          telemetry.recordNpcMovie('ready', 'complete', 28);
          console.log('[BrowserPerformanceGC] 2 87');
          console.log('[BrowserPerformanceScript] chapter tutorial_tom 143');
          console.log('[BrowserPerformanceAvatar] interface 2194');
          console.log('[BrowserPerformanceInterface] quest_map 731');
          console.log('[BrowserPerformanceCommand] tutorial_tom transform 42');
          console.log('[BrowserPerformanceFrameStage] render 867');
          console.log('[BrowserPerformanceFrameCall] 734');
          console.log('[BrowserPerformanceIntervalPhase] callbacks 691');
          console.log('[BrowserPerformanceIntervalFunction] play 677');
          console.log('[BrowserPerformanceActorAnimation] play 6 654 23');
          console.log('[BrowserPerformanceBattleBuild] throw construct 1 6429');
          console.log('[BrowserPerformanceBattleStage] toon_movie 6438');
          console.log('[BrowserPerformanceBattleAsset] prop splat-tart cold 3800');
          console.log('[BrowserPerformanceBattleSound] aa_tart_only.ogg first 1 web_audio 0 0 1');
          console.log('[BrowserPerformanceBattleSound] aa_tart_only.ogg repeat 2 retained 0 3 3');
          console.log('[BrowserPerformanceAnimationBind] toon throw 1 2100');
          console.log('[BrowserPerformanceActorIntervalBuild] toon throw 2110');
          telemetry.recordRuntimeError('python');
          await telemetry.flush();
        }
    """)
    page.evaluate("""
        () => {
          window.__toontownTestVisibility = 'hidden';
          Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            get: () => window.__toontownTestVisibility,
          });
          document.dispatchEvent(new Event('visibilitychange'));
        }
    """)
    page.wait_for_timeout(350)
    page.evaluate("""
        () => {
          window.__toontownTestVisibility = 'visible';
          document.dispatchEvent(new Event('visibilitychange'));
        }
    """)
    page.wait_for_timeout(700)
    page.evaluate("""
        () => {
          const startedAt = performance.now();
          while (performance.now() - startedAt < 5200) {
            // The dedicated telemetry worker must detect this independently.
          }
        }
    """)
    page.wait_for_timeout(1200)
    page.evaluate("""
        async () => {
          const telemetry = window.ToontownPerformanceTelemetry;
          for (let attempt = 0; attempt < 10; attempt += 1) {
            await telemetry.flush();
            if (telemetry.snapshot().pending.length === 0) break;
          }
        }
    """)
    browser.close()

events = [event for batch in batches for event in batch["events"]]
event_types = [event["type"] for event in events]
session = next(event for event in events if event["type"] == "session")
phase = next(event for event in events if event["type"] == "phase_complete")
prefetch = next(
    event for event in events if event["type"] == "phase_prefetch_complete"
)
handoff_part = next(
    event
    for event in events
    if event["type"] == "phase_handoff" and event["stage"] == "part"
)
handoff_complete = next(
    event
    for event in events
    if event["type"] == "phase_handoff" and event["stage"] == "complete"
)
npc_ready = next(
    event
    for event in events
    if event["type"] == "npc_movie" and event["stage"] == "ready"
)
stall = next(event for event in events if event["type"] == "main_thread_stall")
gc_pause = next(event for event in events if event["type"] == "gc_pause")
script_step = next(event for event in events if event["type"] == "script_step")
avatar_setup = next(event for event in events if event["type"] == "avatar_setup")
interface_setup = next(
    event for event in events if event["type"] == "interface_setup"
)
frame_stage = next(event for event in events if event["type"] == "frame_stage")
frame_call = next(event for event in events if event["type"] == "frame_call")
interval_phase = next(event for event in events if event["type"] == "interval_phase")
interval_function = next(
    event for event in events if event["type"] == "interval_function"
)
actor_animation = next(
    event for event in events if event["type"] == "actor_animation"
)
battle_build = next(event for event in events if event["type"] == "battle_build")
battle_stage = next(event for event in events if event["type"] == "battle_stage")
battle_asset = next(event for event in events if event["type"] == "battle_asset")
battle_sound_first = next(
    event
    for event in events
    if event["type"] == "battle_sound" and event["requestStatus"] == "first"
)
battle_sound_repeat = next(
    event
    for event in events
    if event["type"] == "battle_sound" and event["requestStatus"] == "repeat"
)
lifecycle_hidden = next(
    event
    for event in events
    if event["type"] == "lifecycle" and event["visibility"] == "hidden"
)
lifecycle_visible = next(
    event
    for event in events
    if event["type"] == "lifecycle" and event["visibility"] == "visible"
)
animation_bind = next(
    event for event in events if event["type"] == "animation_bind"
)
actor_interval_build = next(
    event for event in events if event["type"] == "actor_interval_build"
)
toon_entry_selected = next(
    event
    for event in events
    if event["type"] == "toon_entry" and event["stage"] == "selected"
)
toon_entry_state = next(
    event
    for event in events
    if event["type"] == "toon_entry" and event["stage"] == "tutorial_state"
)
toon_entry_frame = next(
    event
    for event in events
    if event["type"] == "toon_entry" and event["stage"] == "first_frame"
)
frame_gap = next(event for event in events if event["type"] == "frame_gap")
serialized = json.dumps(batches).lower()

result = {
    "batches": len(batches),
    "event_types": event_types,
    "browser": session["browser"],
    "device": session["device"],
    "phase_duration_ms": phase["durationMs"],
    "phase_processing_ms": phase["processingMs"],
    "prefetch_concurrency": prefetch["concurrency"],
    "handoff_source": handoff_part["source"],
    "handoff_peak_parts": handoff_complete["peakActiveParts"],
    "npc_movie": npc_ready["movie"],
    "stall_duration_ms": stall["durationMs"],
    "gc_pause_ms": gc_pause["durationMs"],
    "script_step_ms": script_step["durationMs"],
    "avatar_setup_stage": avatar_setup["stage"],
    "interface_setup_stage": interface_setup["stage"],
    "frame_stage": frame_stage["stage"],
    "frame_call_ms": frame_call["durationMs"],
    "interval_phase": interval_phase["phase"],
    "interval_function": interval_function["callback"],
    "actor_animation": actor_animation["operation"],
    "battle_build": battle_build["track"],
    "battle_stage": battle_stage["stage"],
    "battle_asset": battle_asset["asset"],
    "battle_sound_first_ms": battle_sound_first["managerMs"],
    "battle_sound_repeat_ms": battle_sound_repeat["managerMs"],
    "background_away_ms": lifecycle_visible["awayMs"],
    "animation_bind": animation_bind["animation"],
    "actor_interval_build": actor_interval_build["animation"],
    "toon_entry_state_ms": toon_entry_state["durationMs"],
    "toon_entry_frame_ms": toon_entry_frame["durationMs"],
    "frame_gap_ms": frame_gap["durationMs"],
    "page_errors": page_errors,
}
print(json.dumps(result, indent=2))

assert batches
assert session["browser"] == "chromium"
assert session["device"] == "mobile"
assert "tutorial" in [
    event.get("state") for event in events if event["type"] == "state"
]
assert phase["phase"] == "4"
assert phase["durationMs"] == 3200
assert phase["processingMs"] == 500
assert prefetch["phase"] == "4"
assert prefetch["concurrency"] == 4
assert handoff_part["source"] == "network"
assert handoff_part["part"] == 7
assert handoff_part["cacheStored"] is True
assert handoff_complete["peakActiveParts"] == 4
assert handoff_complete["networkParts"] == 23
assert handoff_complete["claims"] == 23
assert npc_ready["movie"] == "complete"
assert stall["durationMs"] >= 4000
assert stall["script"] == "tutorial_tom"
assert stall["command"] == "transform"
assert stall["step"] == 42
assert gc_pause["generation"] == 2
assert gc_pause["durationMs"] == 87
assert script_step["stage"] == "chapter"
assert script_step["script"] == "tutorial_tom"
assert script_step["durationMs"] == 143
assert avatar_setup["stage"] == "interface"
assert avatar_setup["durationMs"] == 2194
assert interface_setup["stage"] == "quest_map"
assert interface_setup["durationMs"] == 731
assert frame_stage["stage"] == "render"
assert frame_stage["durationMs"] == 867
assert frame_stage["script"] == "tutorial_tom"
assert frame_stage["command"] == "transform"
assert frame_stage["step"] == 42
assert frame_call["durationMs"] == 734
assert frame_call["script"] == "tutorial_tom"
assert frame_call["command"] == "transform"
assert frame_call["step"] == 42
assert interval_phase["phase"] == "callbacks"
assert interval_phase["durationMs"] == 691
assert interval_phase["script"] == "tutorial_tom"
assert interval_phase["step"] == 42
assert interval_function["callback"] == "play"
assert interval_function["durationMs"] == 677
assert interval_function["script"] == "tutorial_tom"
assert interval_function["step"] == 42
assert actor_animation["operation"] == "play"
assert actor_animation["controls"] == 6
assert actor_animation["lookupMs"] == 654
assert actor_animation["controlMs"] == 23
assert actor_animation["script"] == "tutorial_tom"
assert actor_animation["step"] == 42
assert battle_build["track"] == "throw"
assert battle_build["stage"] == "construct"
assert battle_build["attacks"] == 1
assert battle_build["durationMs"] == 6429
assert battle_stage["stage"] == "toon_movie"
assert battle_stage["durationMs"] == 6438
assert battle_asset["kind"] == "prop"
assert battle_asset["asset"] == "splat-tart"
assert battle_asset["status"] == "cold"
assert battle_asset["durationMs"] == 3800
assert battle_sound_first["sound"] == "aa_tart_only.ogg"
assert battle_sound_first["lookupStatus"] == "web_audio"
assert battle_sound_repeat["lookupStatus"] == "retained"
assert battle_sound_first["requestCount"] == 1
assert battle_sound_first["resolveMs"] == 0
assert battle_sound_first["managerMs"] == 0
assert battle_sound_first["totalMs"] == 1
assert battle_sound_repeat["sound"] == "aa_tart_only.ogg"
assert battle_sound_repeat["requestCount"] == 2
assert battle_sound_repeat["resolveMs"] == 0
assert battle_sound_repeat["managerMs"] == 3
assert battle_sound_repeat["totalMs"] == 3
assert lifecycle_hidden["awayMs"] == 0
assert lifecycle_visible["awayMs"] >= 300
assert not any(
    event["type"] == "frame_gap"
    and lifecycle_hidden["atMs"] <= event["atMs"] <= lifecycle_visible["atMs"] + 100
    for event in events
)
assert animation_bind["actor"] == "toon"
assert animation_bind["animation"] == "throw"
assert animation_bind["controls"] == 1
assert animation_bind["durationMs"] == 2100
assert actor_interval_build["actor"] == "toon"
assert actor_interval_build["animation"] == "throw"
assert actor_interval_build["durationMs"] == 2110
assert toon_entry_selected["durationMs"] == 0
assert toon_entry_selected["state"] == "avatar_chooser"
assert toon_entry_state["durationMs"] >= 20
assert toon_entry_state["state"] == "tutorial"
assert toon_entry_frame["durationMs"] >= toon_entry_state["durationMs"]
assert toon_entry_frame["state"] == "tutorial"
assert frame_gap["durationMs"] >= 250
assert frame_gap["script"] == "tutorial_tom"
assert "runtime_error" in event_types
for event in events:
    assert not set(event).intersection({
        "username", "account", "password", "chat", "useragent", "ip",
    })
for forbidden_value in [
    "private-account-value", "private-password-value", "private-chat-value",
]:
    assert forbidden_value not in serialized
assert not page_errors
