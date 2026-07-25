"""Keep the untouched login screen alive beyond the former gateway timeout."""

import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-login-idle-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
IDLE_MS = int(os.environ.get("OPEN_TOONTOWN_LOGIN_IDLE_MS", "125000"))


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
    page.wait_for_timeout(IDLE_MS)
    page.screenshot(path=str(SCREENSHOT), full_page=True)

    with urlopen("http://127.0.0.1:7200/health", timeout=5) as response:
        gateway_health = json.load(response)

    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "Exception occurred in PythonTask" in line
        or "AttributeError:" in line
    ]
    result = {
        "viewport": "1280x900",
        "idle_seconds": round(IDLE_MS / 1000, 1),
        "loading_classes": page.locator("#loading").get_attribute("class"),
        "gateway_active_connections": gateway_health["activeConnections"],
        "lost_connection": any(
            "Lost connection" in line for line in console_lines
        ),
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["idle_seconds"] > 120
assert "is-done" in result["loading_classes"].split()
assert "is-error" not in result["loading_classes"].split()
assert result["gateway_active_connections"] >= 1
assert not result["lost_connection"]
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
