"""Exercise all Advanced Settings tabs and their live controls in Chromium."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-advanced-settings-smoke.png"
RESET_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-advanced-settings-reset-smoke.png"
)
CONTROLS_SCROLLED_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-advanced-controls-scrolled-smoke.png"
)
FAILURE_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-advanced-settings-failure.png"
)
GAMEPLAY_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-advanced-gameplay-smoke.png"
)
AUDIO_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-advanced-audio-smoke.png"
VIDEO_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-advanced-video-smoke.png"
VIDEO_FPS_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-advanced-video-fps-smoke.png"
)
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_ADVANCED_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_ADVANCED_PASSWORD", "test")


def read_settings(page):
    raw = page.evaluate("localStorage.getItem('open-toontown.useropt.v1')")
    return json.loads(raw) if raw else {}


def wait_for_console(page, console_lines, needle, count=1, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(needle in line for line in console_lines) >= count:
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"Timed out waiting for console marker: {needle}")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_lines = []
    page_errors = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")

    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any("AvatarChooser.enter" in line for line in console_lines):
            break
        page.wait_for_timeout(250)
    assert any("AvatarChooser.enter" in line for line in console_lines)

    canvas.click(position={"x": 235, "y": 265})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any("teleportInDone:" in line for line in console_lines):
            break
        page.wait_for_timeout(250)
    assert any("teleportInDone:" in line for line in console_lines)

    # A fresh or task-bearing Toon may enter with the reminder popup active.
    # Acknowledge it before opening the Options page.
    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    page.keyboard.press("Escape")
    page.wait_for_timeout(750)
    canvas.click(position={"x": 595, "y": 38})
    page.wait_for_timeout(750)
    wait_for_console(page, console_lines, "ADVANCED TAB: GAMEPLAY")
    page.screenshot(path=str(GAMEPLAY_SCREENSHOT), full_page=True)

    original_mouse_look = bool(
        read_settings(page).get("experimental-mouse-look", False)
    )
    canvas.click(position={"x": 775, "y": 282})
    page.wait_for_function(
        "expected => {"
        "  const raw = localStorage.getItem('open-toontown.useropt.v1');"
        "  return raw && JSON.parse(raw)['experimental-mouse-look'] === expected;"
        "}",
        arg=not original_mouse_look,
        timeout=5_000,
    )
    toggled_mouse_look = read_settings(page)["experimental-mouse-look"]
    canvas.click(position={"x": 775, "y": 282})
    page.wait_for_function(
        "expected => {"
        "  const raw = localStorage.getItem('open-toontown.useropt.v1');"
        "  return raw && JSON.parse(raw)['experimental-mouse-look'] === expected;"
        "}",
        arg=original_mouse_look,
        timeout=5_000,
    )
    restored_mouse_look = read_settings(page)["experimental-mouse-look"]

    # Controls is the second internal tab.
    canvas.click(position={"x": 505, "y": 150})
    wait_for_console(page, console_lines, "ADVANCED TAB: CONTROLS")

    # Remap Move Forward from the default W to Up Arrow.
    canvas.click(position={"x": 765, "y": 253})
    # DirectGUI processes the pointer click on the next Panda frame. Waiting
    # here prevents the synthetic keydown from racing ahead of capture setup.
    page.wait_for_timeout(100)
    page.keyboard.down("ArrowUp")
    page.wait_for_timeout(25)
    observed_browser_key = page.evaluate(
        "localStorage.getItem('open-toontown.captured-key')"
    )
    page.wait_for_timeout(75)
    page.keyboard.up("ArrowUp")
    try:
        page.wait_for_function(
            "(() => {"
            "  const raw = localStorage.getItem('open-toontown.useropt.v1');"
            "  if (!raw) return false;"
            "  const settings = JSON.parse(raw);"
            "  return settings['key-bindings']?.forward === 'arrow_up';"
            "})()",
            timeout=5_000,
        )
    except Exception:
        page.screenshot(path=str(FAILURE_SCREENSHOT), full_page=True)
        print(json.dumps({
            "captured_key": page.evaluate(
                "localStorage.getItem('open-toontown.captured-key')"
            ),
            "observed_browser_key": observed_browser_key,
            "settings": read_settings(page),
            "active_element": page.evaluate("document.activeElement.id"),
            "console_tail": console_lines[-30:],
            "failure_screenshot": str(FAILURE_SCREENSHOT),
        }, indent=2))
        raise
    remapped = read_settings(page)

    # S is already Move Backward, so it must be rejected.
    canvas.click(position={"x": 765, "y": 253})
    page.wait_for_timeout(100)
    page.keyboard.down("s")
    page.wait_for_timeout(100)
    page.keyboard.up("s")
    page.wait_for_timeout(750)
    duplicate = read_settings(page)
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)

    # The expanded Controls list overflows the viewport. Scroll to its final
    # rows and Reset Defaults button, exercising the per-tab scrollbar.
    box = canvas.bounding_box()
    page.mouse.move(box["x"] + 600, box["y"] + 420)
    for _index in range(8):
        page.mouse.wheel(0, 320)
        page.wait_for_timeout(50)
    # Drag the native DirectGUI thumb to the bottom as a deterministic
    # fallback in headless Chromium, where synthetic wheel delivery can vary.
    scrollbar_x = box["x"] + box["width"] * 0.782
    page.mouse.move(scrollbar_x, box["y"] + 270)
    page.mouse.down()
    page.mouse.move(scrollbar_x, box["y"] + 445, steps=12)
    page.mouse.up()
    page.wait_for_timeout(300)
    page.screenshot(path=str(CONTROLS_SCROLLED_SCREENSHOT), full_page=True)

    # Reset also cancels an active capture after a duplicate rejection.
    canvas.click(position={"x": 590, "y": 470})
    page.wait_for_function(
        "JSON.parse(localStorage.getItem('open-toontown.useropt.v1'))"
        "['key-bindings'].forward === 'w'",
        timeout=5_000,
    )
    reset = read_settings(page)
    page.wait_for_timeout(300)
    page.screenshot(path=str(RESET_SCREENSHOT), full_page=True)

    # Verify that the remaining Audio tab surface is reachable.
    canvas.click(position={"x": 673, "y": 150})
    wait_for_console(page, console_lines, "ADVANCED TAB: AUDIO")
    page.screenshot(path=str(AUDIO_SCREENSHOT), full_page=True)

    original_audio = read_settings(page)
    original_music = bool(original_audio.get("music", True))
    original_sfx = bool(original_audio.get("sfx", True))
    original_chat_sounds = bool(original_audio.get("toon-chat-sounds", True))
    audio_controls = (
        ("music", original_music, 238),
        ("toon-chat-sounds", original_chat_sounds, 358),
        ("sfx", original_sfx, 298),
    )
    for setting, original_value, y in audio_controls:
        canvas.click(position={"x": 775, "y": y})
        page.wait_for_function(
            "([setting, expected]) => {"
            "  const raw = localStorage.getItem('open-toontown.useropt.v1');"
            "  return raw && JSON.parse(raw)[setting] === expected;"
            "}",
            arg=[setting, not original_value],
            timeout=5_000,
        )
        canvas.click(position={"x": 775, "y": y})
        page.wait_for_function(
            "([setting, expected]) => {"
            "  const raw = localStorage.getItem('open-toontown.useropt.v1');"
            "  return raw && JSON.parse(raw)[setting] === expected;"
            "}",
            arg=[setting, original_value],
            timeout=5_000,
        )

    canvas.click(position={"x": 840, "y": 150})
    wait_for_console(page, console_lines, "ADVANCED TAB: VIDEO")
    page.screenshot(path=str(VIDEO_SCREENSHOT), full_page=True)

    original_show_fps = bool(read_settings(page).get("show-fps", False))
    canvas.click(position={"x": 775, "y": 384})
    page.wait_for_function(
        "JSON.parse(localStorage.getItem('open-toontown.useropt.v1'))"
        f"['show-fps'] === {str(not original_show_fps).lower()}",
        timeout=5_000,
    )
    page.wait_for_timeout(1_000)
    toggled_show_fps = read_settings(page)["show-fps"]
    page.screenshot(path=str(VIDEO_FPS_SCREENSHOT), full_page=True)

    canvas.click(position={"x": 775, "y": 384})
    page.wait_for_function(
        "JSON.parse(localStorage.getItem('open-toontown.useropt.v1'))"
        f"['show-fps'] === {str(original_show_fps).lower()}",
        timeout=5_000,
    )
    restored_show_fps = read_settings(page)["show-fps"]

    canvas.click(position={"x": 338, "y": 150})
    wait_for_console(page, console_lines, "ADVANCED TAB: GAMEPLAY", count=2)

    result = {
        "viewport": "1280x900",
        "advanced_page_rendered": True,
        "remapped_forward": remapped["key-bindings"]["forward"],
        "duplicate_kept_forward": duplicate["key-bindings"]["forward"],
        "reset_forward": reset["key-bindings"]["forward"],
        "reset_sprint": reset["key-bindings"]["sprint"],
        "reset_jump": reset["key-bindings"]["jump"],
        "reset_view_gags": reset["key-bindings"]["viewGags"],
        "reset_view_toontasks": reset["key-bindings"]["viewToonTasks"],
        "reset_perform_action": reset["key-bindings"]["performAction"],
        "reset_exit_activity": reset["key-bindings"]["exitActivity"],
        "reset_view_street_map": reset["key-bindings"]["viewStreetMap"],
        "tabs_visited": sorted({
            line.rsplit("ADVANCED TAB: ", 1)[1].strip().lower()
            for line in console_lines
            if "ADVANCED TAB: " in line
        }),
        "show_fps_toggled": toggled_show_fps,
        "show_fps_restored": restored_show_fps,
        "mouse_look_toggled": toggled_mouse_look,
        "mouse_look_restored": restored_mouse_look,
        "audio_restored": {
            setting: read_settings(page).get(setting)
            for setting, _original, _y in audio_controls
        },
        "python_tracebacks": [
            line for line in console_lines if "Traceback (most recent call last)" in line
        ],
        "page_errors": page_errors,
        "screenshot": str(SCREENSHOT),
        "reset_screenshot": str(RESET_SCREENSHOT),
        "controls_scrolled_screenshot": str(CONTROLS_SCROLLED_SCREENSHOT),
        "gameplay_screenshot": str(GAMEPLAY_SCREENSHOT),
        "audio_screenshot": str(AUDIO_SCREENSHOT),
        "video_screenshot": str(VIDEO_SCREENSHOT),
        "video_fps_screenshot": str(VIDEO_FPS_SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["remapped_forward"] == "arrow_up"
assert result["duplicate_kept_forward"] == "arrow_up"
assert result["reset_forward"] == "w"
assert result["reset_sprint"] == "shift"
assert result["reset_jump"] == "space"
assert result["reset_view_gags"] == "home"
assert result["reset_view_toontasks"] == "end"
assert result["reset_perform_action"] == "delete"
assert result["reset_exit_activity"] == "escape"
assert result["reset_view_street_map"] == "alt"
assert result["tabs_visited"] == ["audio", "controls", "gameplay", "video"]
assert result["show_fps_toggled"] is not result["show_fps_restored"]
assert result["mouse_look_toggled"] is not result["mouse_look_restored"]
assert result["mouse_look_restored"] is original_mouse_look
assert result["audio_restored"] == {
    "music": original_music,
    "toon-chat-sounds": original_chat_sounds,
    "sfx": original_sfx,
}
assert not result["python_tracebacks"]
assert not result["page_errors"]
