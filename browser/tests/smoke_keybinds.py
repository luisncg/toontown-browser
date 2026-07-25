"""Verify persisted browser keybinds drive Panda3D's real InputState."""

import json
import os

from playwright.sync_api import sync_playwright


GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
SETTINGS = {
    "key-bindings": {
        "forward": "w",
        "reverse": "s",
        "turnLeft": "a",
        "turnRight": "d",
        "sprint": "shift",
        "jump": "space",
    }
}


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_errors = []
    page_errors = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    serialized_settings = json.dumps(SETTINGS, separators=(",", ":"))
    page.add_init_script(
        "localStorage.setItem('open-toontown.useropt.v1', %s);"
        % json.dumps(serialized_settings)
    )

    page.goto(f"{GAME_URL}/?input-test=1", wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")
    canvas.click(position={"x": 400, "y": 300})

    page.keyboard.press("ArrowUp")
    page.wait_for_timeout(250)
    arrow_forward_count = page.evaluate("window.__keybindForwardCount ?? 0")

    page.keyboard.press("w")
    page.wait_for_function(
        "window.__keybindForwardCount === 1",
        timeout=5_000,
    )

    page.keyboard.press("Control")
    page.wait_for_timeout(250)
    control_jump_count = page.evaluate("window.__keybindJumpCount ?? 0")

    page.keyboard.press("Space")
    page.wait_for_function(
        "window.__keybindJumpCount === 1",
        timeout=5_000,
    )

    page.keyboard.down("Shift")
    page.wait_for_function(
        "window.__keybindSprintOnCount === 1",
        timeout=5_000,
    )
    page.keyboard.up("Shift")
    page.wait_for_function(
        "window.__keybindSprintOffCount === 1",
        timeout=5_000,
    )

    # Losing canvas focus while Sprint is held must synthesize its release;
    # otherwise returning from a macOS shortcut can leave the Toon sprinting.
    page.keyboard.down("Shift")
    page.wait_for_function(
        "window.__keybindSprintOnCount === 2",
        timeout=5_000,
    )
    page.evaluate("document.querySelector('#canvas').blur()")
    page.wait_for_function(
        "window.__keybindSprintOffCount === 2",
        timeout=5_000,
    )
    page.keyboard.up("Shift")
    canvas.click(position={"x": 400, "y": 300})
    stored = json.loads(
        page.evaluate("localStorage.getItem('open-toontown.useropt.v1')")
    )

    result = {
        "viewport": "1280x900",
        "arrow_forward_count": arrow_forward_count,
        "w_forward_count": page.evaluate("window.__keybindForwardCount"),
        "control_jump_count": control_jump_count,
        "space_jump_count": page.evaluate("window.__keybindJumpCount"),
        "shift_sprint_on_count": page.evaluate("window.__keybindSprintOnCount"),
        "shift_sprint_off_count": page.evaluate("window.__keybindSprintOffCount"),
        "stored_forward": stored["key-bindings"]["forward"],
        "stored_sprint": stored["key-bindings"]["sprint"],
        "stored_jump": stored["key-bindings"]["jump"],
        "active_element": page.evaluate("document.activeElement.id"),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["arrow_forward_count"] == 0
assert result["w_forward_count"] == 1
assert result["control_jump_count"] == 0
assert result["space_jump_count"] == 1
assert result["shift_sprint_on_count"] == 2
assert result["shift_sprint_off_count"] == 2
assert result["stored_forward"] == "w"
assert result["stored_sprint"] == "shift"
assert result["stored_jump"] == "space"
assert result["active_element"] == "canvas"
assert not console_errors
assert not page_errors
