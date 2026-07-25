"""Verify the classic browser boot, login screen, and Pick-a-Toon handoff."""

import hashlib
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
BUILD_DIR = PROJECT_DIR / ".build-wasm"
BOOT_SCREENSHOT = BUILD_DIR / "classic-toontown-boot.png"
LOGIN_SCREENSHOT = BUILD_DIR / "classic-toontown-login.png"
SUCCESS_SCREENSHOT = BUILD_DIR / "classic-toontown-pick-a-toon.png"
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
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)

    boot_logo = page.locator(".boot-logo")
    boot_logo.wait_for(state="visible", timeout=5_000)
    boot_src = boot_logo.get_attribute("src")
    boot_title = page.locator("#status").inner_text()
    page.locator(".stage").screenshot(path=str(BOOT_SCREENSHOT))

    loading = page.locator("#loading.is-done")
    loading.wait_for(state="attached", timeout=45_000)
    loading.wait_for(state="hidden", timeout=5_000)
    page.wait_for_timeout(500)

    canvas = page.locator("#canvas")
    login_image = canvas.screenshot(path=str(LOGIN_SCREENSHOT))
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

    success_image = canvas.screenshot(path=str(SUCCESS_SCREENSHOT))
    browser.close()

result = {
    "boot_title": boot_title,
    "boot_logo": boot_src,
    "avatar_chooser_entered": any(
        "AvatarChooser.enter" in line for line in console_lines
    ),
    "login_changed_to_pick_a_toon": (
        hashlib.sha256(login_image).digest()
        != hashlib.sha256(success_image).digest()
    ),
    "console_errors": console_errors,
    "page_errors": page_errors,
    "screenshots": {
        "boot": str(BOOT_SCREENSHOT),
        "login": str(LOGIN_SCREENSHOT),
        "pick_a_toon": str(SUCCESS_SCREENSHOT),
    },
}
print(json.dumps(result, indent=2))

assert result["boot_title"] == "LOADING TOONTOWN..."
assert result["boot_logo"] == "resources/phase_3/maps/toontown-logo.png"
assert result["avatar_chooser_entered"]
assert result["login_changed_to_pick_a_toon"]
assert not result["console_errors"]
assert not result["page_errors"]
