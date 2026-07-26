"""Exercise a real local account login through WebSocket and Astron."""

import hashlib
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-login-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_TEST_ACCOUNT", "wasmbrowsersmoke")
PASSWORD = os.environ.get("OPEN_TOONTOWN_TEST_PASSWORD", "localbrowser")


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
    page.wait_for_timeout(750)
    welcome = page.locator("#welcome-overlay")
    if welcome.is_visible():
        page.locator("#welcome-accept").click()
        welcome.wait_for(state="hidden", timeout=5_000)

    canvas = page.locator("#canvas")
    before = canvas.screenshot()
    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any("AvatarChooser.enter" in line for line in console_lines):
            break
        page.wait_for_timeout(250)

    after = canvas.screenshot()
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    audio_contexts = page.evaluate(
        """typeof AL === 'undefined'
        ? []
        : Object.values(AL.contexts).map(context => context.audioCtx.state)"""
    )
    browser.close()

result = {
    "account": ACCOUNT,
    "avatar_chooser_entered": any(
        "AvatarChooser.enter" in line for line in console_lines
    ),
    "canvas_changed": hashlib.sha256(before).digest() != hashlib.sha256(after).digest(),
    "web_audio_contexts": audio_contexts,
    "console_errors": console_errors,
    "page_errors": page_errors,
    "console_tail": console_lines[-80:],
    "screenshot": str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert result["canvas_changed"], "Login submission did not change the game surface"
assert result["avatar_chooser_entered"], "Login did not reach the avatar chooser"
assert "running" in result["web_audio_contexts"], "Web Audio did not unlock after input"
assert not console_errors
assert not page_errors
