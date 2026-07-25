"""Exercise the owner's mailbox and furniture-director estate surfaces."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
MAILBOX_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-mailbox-smoke.png"
FURNITURE_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-furniture-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_ESTATE_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_ESTATE_PASSWORD", "test")


def wait_for_console_count(page, lines, marker, count, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    raise AssertionError(
        "Timed out waiting for %r occurrence %d. Console tail:\n%s"
        % (marker, count, "\n".join(lines[-200:]))
    )


def enter_estate(page, canvas, console_lines):
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
    wait_for_console_count(page, console_lines, "Mailbox ready for house", 1)
    page.wait_for_timeout(500)


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
    enter_estate(page, canvas, console_lines)

    # The mailbox sits just behind and to the side of the estate arrival point.
    page.keyboard.down("ArrowLeft")
    page.wait_for_timeout(850)
    page.keyboard.up("ArrowLeft")
    page.keyboard.down("ArrowUp")
    page.wait_for_timeout(650)
    page.keyboard.up("ArrowUp")
    wait_for_console_count(
        page, console_lines, "Local avatar entered mailbox collision", 1, timeout=8
    )
    wait_for_console_count(
        page, console_lines, "Local mailbox movie mode 3", 1, timeout=8
    )
    page.screenshot(path=str(MAILBOX_SCREENSHOT), full_page=True)

    # Use a fresh game session for the furniture check. This deliberately
    # isolates the preserved DirectGUI modal from the 3D navigation assertion.
    mailbox_console_lines = console_lines[:]
    mailbox_page_errors = page_errors[:]
    page.close()

    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_lines = []
    page_errors = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")
    enter_estate(page, canvas, console_lines)

    # Proven front-door approach from the house traversal smoke test.
    page.keyboard.down("ArrowRight")
    page.wait_for_timeout(300)
    page.keyboard.up("ArrowRight")
    page.keyboard.down("ArrowUp")
    page.wait_for_timeout(2_000)
    page.keyboard.up("ArrowUp")
    wait_for_console_count(page, console_lines, "Entered house interior zone", 1)
    wait_for_console_count(page, console_lines, "exitCompleted", 1)
    page.wait_for_timeout(300)

    # The preserved Move Furniture button is the attic icon in the upper-left.
    canvas.click(position={"x": 70, "y": 100})
    wait_for_console_count(page, console_lines, "Furniture director is now", 1)
    page.wait_for_timeout(1_200)
    page.screenshot(path=str(FURNITURE_SCREENSHOT), full_page=True)
    canvas.click(position={"x": 70, "y": 155})
    wait_for_console_count(page, console_lines, "Furniture director is now 0", 1)

    crash_lines = [
        line
        for line in mailbox_console_lines + console_lines
        if "Traceback (most recent call last)" in line
        or "AttributeError:" in line
        or "NameError:" in line
        or "Exception occurred in PythonTask" in line
    ]
    result = {
        "viewport": "1280x900",
        "mailbox_opened": any(
            "Local mailbox movie mode 3" in line
            for line in mailbox_console_lines
        ),
        "entered_house": any(
            "Entered house interior zone" in line for line in console_lines
        ),
        "furniture_director_started": any(
            "Furniture director is now " in line
            and not line.rstrip().endswith("now 0")
            for line in console_lines
        ),
        "furniture_director_released": any(
            "Furniture director is now 0" in line for line in console_lines
        ),
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": mailbox_page_errors + page_errors,
        "mailbox_screenshot": str(MAILBOX_SCREENSHOT),
        "furniture_screenshot": str(FURNITURE_SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["mailbox_opened"]
assert result["entered_house"]
assert result["furniture_director_started"]
assert result["furniture_director_released"]
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
