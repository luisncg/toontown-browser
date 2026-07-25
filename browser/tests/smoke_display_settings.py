"""Regress browser display-resolution confirmation and pointer scaling."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-display-settings-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = "wasmbrowsersmoke"
PASSWORD = "localbrowser"


def wait_for(page, lines, marker, count=1, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-120:]))
    )


def canvas_size(canvas):
    return canvas.evaluate(
        "canvas => ({"
        "  css: [canvas.clientWidth, canvas.clientHeight],"
        "  buffer: [canvas.width, canvas.height],"
        "  inline: [canvas.style.width, canvas.style.height]"
        "})"
    )


def click_many(page, canvas, x, y, count):
    for _index in range(count):
        canvas.click(position={"x": x, "y": y})
        page.wait_for_timeout(80)


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
    wait_for(page, console_lines, "AvatarChooser.enter")
    canvas.click(position={"x": 590, "y": 265})
    wait_for(page, console_lines, "teleportInDone:", timeout=60)
    # This isolated Toon still has a starter quest acknowledgement.
    canvas.click(position={"x": 590, "y": 540})
    page.wait_for_timeout(700)

    page.keyboard.press("Escape")
    page.wait_for_timeout(700)
    initial = canvas_size(canvas)

    # Display settings now live under Advanced > Video.
    canvas.click(position={"x": 595, "y": 38})
    wait_for(page, console_lines, "ADVANCED TAB: GAMEPLAY")
    canvas.click(position={"x": 840, "y": 150})
    wait_for(page, console_lines, "ADVANCED TAB: VIDEO")

    # Set a deterministic 640x480 baseline.  Extra left-arrow clicks are safe
    # after the minimum entry is reached.
    canvas.click(position={"x": 775, "y": 278})
    wait_for(page, console_lines, "DISPLAY SETTINGS OPENED FROM VIDEO", count=1)
    page.wait_for_timeout(400)
    click_many(page, canvas, 608, 260, 6)
    canvas.click(position={"x": 819, "y": 408})
    page.wait_for_timeout(300)
    canvas.click(position={"x": 540, "y": 469})
    wait_for(page, console_lines, "DISPLAY CHANGE VERIFIED", count=1)
    page.wait_for_function(
        "document.querySelector('#canvas').width === 640 && "
        "document.querySelector('#canvas').height === 480",
        timeout=5_000,
    )
    at_640_before_confirm = canvas_size(canvas)
    canvas.click(position={"x": 540, "y": 443})
    wait_for(page, console_lines, "DISPLAY CHANGE ACCEPTED", count=1)

    # Reopen at 640x480 and select 1024x768.  Both the apply-warning button
    # and the final keep-settings button now depend on scaled pointer input.
    canvas.click(position={"x": 775, "y": 278})
    wait_for(page, console_lines, "DISPLAY SETTINGS OPENED FROM VIDEO", count=2)
    page.wait_for_timeout(350)
    click_many(page, canvas, 829, 260, 2)
    canvas.click(position={"x": 819, "y": 408})
    page.wait_for_timeout(300)
    canvas.click(position={"x": 540, "y": 469})
    wait_for(page, console_lines, "DISPLAY CHANGE VERIFIED", count=2)
    page.wait_for_function(
        "document.querySelector('#canvas').width === 1024 && "
        "document.querySelector('#canvas').height === 768",
        timeout=5_000,
    )
    at_1024_before_confirm = canvas_size(canvas)
    canvas.click(position={"x": 540, "y": 443})
    wait_for(page, console_lines, "DISPLAY CHANGE ACCEPTED", count=2)

    # Exercise the same post-resize mapping on Cancel and verify restoration.
    canvas.click(position={"x": 775, "y": 278})
    wait_for(page, console_lines, "DISPLAY SETTINGS OPENED FROM VIDEO", count=3)
    page.wait_for_timeout(350)
    canvas.click(position={"x": 608, "y": 260})
    canvas.click(position={"x": 819, "y": 408})
    page.wait_for_timeout(300)
    canvas.click(position={"x": 540, "y": 469})
    wait_for(page, console_lines, "DISPLAY CHANGE VERIFIED", count=3)
    canvas.click(position={"x": 638, "y": 443})
    wait_for(page, console_lines, "DISPLAY CHANGE REVERTED", count=1)
    page.wait_for_function(
        "document.querySelector('#canvas').width === 1024 && "
        "document.querySelector('#canvas').height === 768",
        timeout=5_000,
    )

    final = canvas_size(canvas)
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "Exception occurred in PythonTask" in line
        or "AttributeError:" in line
    ]
    result = {
        "viewport": "1280x900",
        "initial": initial,
        "at_640_before_confirm": at_640_before_confirm,
        "at_1024_before_confirm": at_1024_before_confirm,
        "final_after_cancel": final,
        "accepted_changes": sum(
            "DISPLAY CHANGE ACCEPTED" in line for line in console_lines
        ),
        "reverted_changes": sum(
            "DISPLAY CHANGE REVERTED" in line for line in console_lines
        ),
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["at_640_before_confirm"]["buffer"] == [640, 480]
assert result["initial"]["buffer"] == [1024, 768]
assert result["at_1024_before_confirm"]["buffer"] == [1024, 768]
assert result["final_after_cancel"]["buffer"] == [1024, 768]
assert result["accepted_changes"] == 2
assert result["reverted_changes"] == 1
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
