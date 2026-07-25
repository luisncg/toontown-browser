"""Enter the local Toon's generated estate and return to a playground."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-go-home-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_GO_HOME_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_GO_HOME_PASSWORD", "test")


def wait_for_console_count(page, lines, marker, count, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    raise AssertionError(
        "Timed out waiting for %r occurrence %d. Console tail:\n%s"
        % (marker, count, "\n".join(lines[-160:]))
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
    initial_teleport_count = sum(
        "teleportInDone:" in line for line in console_lines
    )
    initial_walk_count = sum(
        "teleportInDone: walk" in line for line in console_lines
    )
    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    # Map page icon in the Shtiker Book's right-hand tab strip.
    canvas.click(position={"x": 1000, "y": 168})
    page.wait_for_timeout(600)
    # Native Go Home button at the bottom of the map page.
    canvas.click(position={"x": 653, "y": 512})

    wait_for_console_count(page, console_lines, "Entered estate zone", 1, timeout=45)
    wait_for_console_count(
        page,
        console_lines,
        "teleportInDone: walk",
        initial_walk_count + 1,
        timeout=45,
    )
    wait_for_console_count(
        page, console_lines, "Fishing pond ready in area", 1, timeout=45
    )
    page.wait_for_timeout(1_000)
    page.screenshot(path=str(SCREENSHOT), full_page=True)

    # The estate map replaces Go Home with Back to Playground.
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    canvas.click(position={"x": 1000, "y": 168})
    page.wait_for_timeout(600)
    canvas.click(position={"x": 800, "y": 512})
    popup_count_before_return = sum(
        "teleportInDone: popup" in line for line in console_lines
    )
    wait_for_console_count(
        page,
        console_lines,
        "teleportInDone:",
        initial_teleport_count + 2,
        timeout=45,
    )
    if sum(
        "teleportInDone: popup" in line for line in console_lines
    ) > popup_count_before_return:
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "AttributeError:" in line
        or "Exception occurred in PythonTask" in line
    ]
    result = {
        "viewport": "1280x900",
        "entered_estate": any(
            "Entered estate zone" in line for line in console_lines
        ),
        "garden_root_ready": any(
            "Estate garden root ready" in line for line in console_lines
        ),
        "fishing_pond_ready": any(
            "Fishing pond ready in area" in line for line in console_lines
        ),
        "fish_bingo_managers_seen": sum(
            "Fish Bingo manager ready" in line for line in console_lines
        ),
        "returned_to_playground": sum(
            "teleportInDone:" in line for line in console_lines
        )
        >= initial_teleport_count + 2,
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["entered_estate"]
assert result["garden_root_ready"]
assert result["fishing_pond_ready"]
if os.environ.get("FISH_BINGO_EXPECT_ACTIVE") == "1":
    assert result["fish_bingo_managers_seen"] >= 2
assert result["returned_to_playground"]
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
