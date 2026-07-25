"""Verify Pick-a-Toon hides Quit and Logout starts a fresh login session."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = PROJECT_DIR / ".build-wasm"
PICK_A_TOON_SCREENSHOT = SCREENSHOT_DIR / "pick-a-toon-without-quit.png"
LOGOUT_SCREENSHOT = SCREENSHOT_DIR / "pick-a-toon-logged-out.png"
RELOGIN_SCREENSHOT = SCREENSHOT_DIR / "pick-a-toon-after-relogin.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_TEST_ACCOUNT", "wasmbrowsersmoke")
PASSWORD = os.environ.get("OPEN_TOONTOWN_TEST_PASSWORD", "localbrowser")


def wait_for_console_count(page, lines, needle, count, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(needle in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    raise AssertionError(
        f"Timed out waiting for {count} occurrence(s) of {needle!r}; "
        f"console tail: {json.dumps(lines[-80:])}")


def replace_entry(page, canvas, position, value):
    canvas.click(position=position)
    page.keyboard.press("Control+A")
    page.keyboard.type(value)


def submit_login(page, canvas, replace_account=True):
    if replace_account:
        replace_entry(page, canvas, {"x": 660, "y": 410}, ACCOUNT)
    replace_entry(page, canvas, {"x": 660, "y": 466}, PASSWORD)
    canvas.click(position={"x": 590, "y": 532})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_lines = []
    console_errors = []
    page_errors = []

    def capture_console(message):
        console_lines.append(message.text)
        if message.type == "error":
            console_errors.append(message.text)

    page.on("console", capture_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)

    canvas = page.locator("#canvas")
    submit_login(page, canvas)
    wait_for_console_count(page, console_lines, "AvatarChooser.enter", 1)
    canvas.screenshot(path=str(PICK_A_TOON_SCREENSHOT))
    canvas_box = canvas.bounding_box()
    assert canvas_box is not None
    button_y = canvas_box["height"] - 31

    # This is the old Quit button's lower-right location.  It must be inert.
    canvas.click(position={"x": canvas_box["width"] - 70, "y": button_y})
    page.wait_for_timeout(750)
    assert sum("AvatarChooser.enter" in line for line in console_lines) == 1

    # Logout remains in the lower-left and must return to the account screen.
    canvas.click(position={"x": 75, "y": button_y})
    wait_for_console_count(
        page,
        console_lines,
        "Logging out and reconnecting to the account screen.",
        1,
    )
    page.wait_for_timeout(1_000)
    canvas.screenshot(path=str(LOGOUT_SCREENSHOT))

    submit_login(page, canvas, replace_account=False)
    wait_for_console_count(page, console_lines, "AvatarChooser.enter", 2)
    canvas.screenshot(path=str(RELOGIN_SCREENSHOT))
    browser.close()

result = {
    "logout_reconnect_started": any(
        "Logging out and reconnecting to the account screen." in line
        for line in console_lines
    ),
    "avatar_chooser_entries": sum(
        "AvatarChooser.enter" in line for line in console_lines
    ),
    "lost_connection_dialog": any(
        "Lost connection to server. Notifying user." in line
        for line in console_lines
    ),
    "traceback": any("Traceback" in line for line in console_lines),
    "console_errors": console_errors,
    "page_errors": page_errors,
    "screenshots": {
        "pick_a_toon": str(PICK_A_TOON_SCREENSHOT),
        "logged_out": str(LOGOUT_SCREENSHOT),
        "relogin": str(RELOGIN_SCREENSHOT),
    },
    "console_tail": console_lines[-100:],
}
print(json.dumps(result, indent=2))

assert result["logout_reconnect_started"]
assert result["avatar_chooser_entries"] == 2
assert not result["lost_connection_dialog"]
assert not result["traceback"]
assert not result["console_errors"]
assert not result["page_errors"]
