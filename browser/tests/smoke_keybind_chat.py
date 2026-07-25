"""Verify printable gameplay bindings do not leak into background type-to-chat."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SUPPRESSED_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-keybind-chat-suppressed-smoke.png"
)
ACTIVE_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-keybind-chat-active-smoke.png"
)
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_KEYBIND_CHAT_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_KEYBIND_CHAT_PASSWORD", "test")
SETTINGS = {
    "key-bindings": {
        "forward": "w",
        "reverse": "s",
        "turnLeft": "a",
        "turnRight": "d",
        "jump": "space",
    }
}


def wait_for_console(page, lines, marker, count=1, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-160:]))
    )


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

    serialized_settings = json.dumps(SETTINGS, separators=(",", ":"))
    page.add_init_script(
        "localStorage.setItem('open-toontown.useropt.v1', %s);"
        "localStorage.setItem('open-toontown.keybind-chat-smoke', '1');"
        % json.dumps(serialized_settings)
    )

    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")

    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for_console(page, console_lines, "AvatarChooser.enter")
    canvas.click(position={"x": 235, "y": 265})
    wait_for_console(page, console_lines, "teleportInDone:", timeout=60)

    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    for key in ("w", "a", "s", "d"):
        page.keyboard.press(key)
        wait_for_console(
            page,
            console_lines,
            "[BrowserChatInputTest] suppressed %s" % key,
            timeout=5,
        )
    page.screenshot(path=str(SUPPRESSED_SCREENSHOT), full_page=True)

    # A non-gameplay letter still intentionally starts type-to-chat. Once the
    # entry is open, bound letters must remain available as ordinary text.
    page.keyboard.press("h")
    wait_for_console(page, console_lines, "[BrowserChatInputTest] opening h", timeout=5)
    page.keyboard.type("wasd")
    wait_for_console(
        page,
        console_lines,
        "[BrowserChatInputTest] active hwasd",
        timeout=5,
    )
    page.screenshot(path=str(ACTIVE_SCREENSHOT), full_page=True)

    smoke_lines = [
        line for line in console_lines if "[BrowserChatInputTest]" in line
    ]
    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "Exception occurred in PythonTask" in line
        or "AttributeError:" in line
    ]
    result = {
        "viewport": "1280x900",
        "suppressed": [
            key
            for key in ("w", "a", "s", "d")
            if any("suppressed %s" % key in line for line in smoke_lines)
        ],
        "intentional_chat_text": "hwasd"
        if any("active hwasd" in line for line in smoke_lines)
        else None,
        "opened_from_bound_key": any(
            "opening %s" % key in line
            for key in ("w", "a", "s", "d")
            for line in smoke_lines
        ),
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "suppressed_screenshot": str(SUPPRESSED_SCREENSHOT),
        "active_screenshot": str(ACTIVE_SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["suppressed"] == ["w", "a", "s", "d"]
assert result["intentional_chat_text"] == "hwasd"
assert not result["opened_from_bound_key"]
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
