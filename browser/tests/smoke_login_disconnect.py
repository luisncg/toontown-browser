"""Verify a pre-login gateway disconnect shows UI without crashing WASM."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-login-disconnect-smoke.png"
RECONNECTED_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-login-disconnect-reconnected-smoke.png"
)
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


def wait_for_console(page, lines, marker, count=1, timeout=30):
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

    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    wait_for_console(
        page,
        console_lines,
        "Lost connection to server. Notifying user.",
        timeout=30,
    )
    page.wait_for_timeout(500)
    page.screenshot(path=str(SCREENSHOT), full_page=True)

    connect_marker = "Connecting through browser gateway"
    connect_count = sum(connect_marker in line for line in console_lines)
    # The OK button is centered just left of the dialog's Cancel button.
    canvas = page.locator("#canvas")
    canvas.click(position={"x": 540, "y": 434})
    wait_for_console(
        page,
        console_lines,
        connect_marker,
        count=connect_count + 1,
        timeout=15,
    )
    page.wait_for_timeout(1_000)
    page.screenshot(path=str(RECONNECTED_SCREENSHOT), full_page=True)

    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "Exception occurred in PythonTask" in line
        or "AttributeError:" in line
    ]
    result = {
        "viewport": "1280x900",
        "disconnect_dialog_entered": any(
            "Lost connection to server. Notifying user." in line
            for line in console_lines
        ),
        "reconnected": sum(
            connect_marker in line for line in console_lines
        ) >= connect_count + 1,
        "loading_classes": page.locator("#loading").get_attribute("class"),
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "screenshot": str(SCREENSHOT),
        "reconnected_screenshot": str(RECONNECTED_SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["disconnect_dialog_entered"]
assert result["reconnected"]
assert "is-done" in result["loading_classes"].split()
assert "is-error" not in result["loading_classes"].split()
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
