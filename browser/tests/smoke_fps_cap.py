"""Measure the browser-managed Panda3D frame loop and enforce its 60 FPS cap."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-fps-cap-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


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

    page.goto(f"{GAME_URL}/?fps-test=1", wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    page.wait_for_function(
        "window.__openToontownFpsTest?.elapsedMs >= 2500",
        timeout=15_000,
    )
    timing = page.evaluate("window.__openToontownFpsTest")
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    browser.close()

result = {
    "viewport": "1280x900",
    "target_fps": timing["targetFps"],
    "measured_fps": round(timing["measuredFps"], 2),
    "measured_frames": timing["frameCount"],
    "elapsed_ms": round(timing["elapsedMs"], 2),
    "console_errors": console_errors,
    "page_errors": page_errors,
    "screenshot": str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert result["target_fps"] == 60
assert 45 <= result["measured_fps"] <= 61.5
assert not result["console_errors"]
assert not result["page_errors"]
