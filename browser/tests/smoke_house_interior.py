"""Enter the owner's house from an estate and return outside."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-house-interior-smoke.png"
APPROACH_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-house-approach-smoke.png"
EXIT_APPROACH_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-house-exit-approach-smoke.png"
)
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_HOUSE_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_HOUSE_PASSWORD", "test")


def wait_for_console_count(page, lines, marker, count, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    door_lines = [
        line for line in lines if "door" in line.lower() or "house" in line.lower()
    ]
    raise AssertionError(
        "Timed out waiting for %r occurrence %d. Door/house log:\n%s\n"
        "Console tail:\n%s"
        % (
            marker,
            count,
            "\n".join(door_lines[-120:]),
            "\n".join(lines[-180:]),
        )
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

    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")

    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for_console_count(page, console_lines, "AvatarChooser.enter", 1)
    canvas.click(position={"x": 235, "y": 265})
    wait_for_console_count(page, console_lines, "teleportInDone:", 1)
    initial_walk_count = sum(
        "teleportInDone: walk" in line for line in console_lines
    )
    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    canvas.click(position={"x": 1000, "y": 168})
    page.wait_for_timeout(600)
    canvas.click(position={"x": 653, "y": 512})
    wait_for_console_count(page, console_lines, "Entered estate zone", 1)
    wait_for_console_count(
        page,
        console_lines,
        "teleportInDone: walk",
        initial_walk_count + 1,
    )
    page.wait_for_timeout(800)

    # The estate spawn point is just left of the owner's front door.
    page.keyboard.down("ArrowRight")
    page.wait_for_timeout(300)
    page.keyboard.up("ArrowRight")
    page.keyboard.down("ArrowUp")
    page.wait_for_timeout(2_000)
    page.keyboard.up("ArrowUp")
    page.screenshot(path=str(APPROACH_SCREENSHOT), full_page=True)
    wait_for_console_count(page, console_lines, "Entered house interior zone", 1)
    # The zone marker arrives while the preserved door-in movie is still playing.
    # Synchronize on the actual destination-door completion, not a wall-clock
    # delay, so turning begins on the same simulation frame every run.
    wait_for_console_count(page, console_lines, "exitCompleted", 1)
    page.wait_for_timeout(250)
    page.screenshot(path=str(SCREENSHOT), full_page=True)

    # The exit movie places the Toon on one half of the double door, facing
    # into the room. Back into the trigger, then turn to face it; the preserved
    # door task deliberately waits for a front-facing approach before entering.
    page.keyboard.down("ArrowDown")
    page.wait_for_timeout(1_000)
    page.keyboard.up("ArrowDown")
    wait_for_console_count(page, console_lines, "collision trigger", 2)
    page.keyboard.down("ArrowRight")
    page.wait_for_timeout(2_000)
    page.keyboard.up("ArrowRight")
    page.screenshot(path=str(EXIT_APPROACH_SCREENSHOT), full_page=True)
    wait_for_console_count(page, console_lines, "Entered estate zone", 2, timeout=12)

    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "AttributeError:" in line
        or "NameError:" in line
        or "Exception occurred in PythonTask" in line
    ]
    result = {
        "viewport": "1280x900",
        "entered_house": any(
            "Entered house interior zone" in line for line in console_lines
        ),
        "returned_to_estate": sum(
            "Entered estate zone" in line for line in console_lines
        )
        >= 2,
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["entered_house"]
assert result["returned_to_estate"]
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
