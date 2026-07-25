"""Verify production visibility rules from portrait login into live gameplay."""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
CHOOSER_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-mobile-portrait-chooser.png"
)
GAMEPLAY_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-mobile-portrait-gameplay.png"
)
FAILURE_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-mobile-portrait-gameplay-failure.png"
)
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_MOBILE_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_MOBILE_PASSWORD", "test")
BOOTSTRAP_SESSION = os.environ.get("TOONTOWN_BOOTSTRAP_SESSION", "")
WELCOME_ACKNOWLEDGEMENT = """
localStorage.setItem('toontown-browser.welcome-acknowledged.v1', '1');
"""


def wait_for_console(page, lines, marker, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(200)
    raise AssertionError(f"Timed out waiting for console marker: {marker}")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    )
    context.add_init_script(WELCOME_ACKNOWLEDGEMENT)
    if BOOTSTRAP_SESSION:
        parsed_game_url = urlparse(GAME_URL)
        context.add_cookies([
            {
                "name": "__Host-toontown_bootstrap",
                "value": BOOTSTRAP_SESSION,
                "domain": parsed_game_url.hostname,
                "path": "/",
                "secure": parsed_game_url.scheme == "https",
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ])
    page = context.new_page()
    console_lines = []
    page_errors = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        # Toontown keeps telemetry and its game socket alive, so production
        # deliberately never guarantees Playwright's network-idle heuristic.
        # The game-specific loading and console markers below are the real
        # readiness contract.
        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=30_000)
        page.locator("#loading.is-done").wait_for(
            state="attached", timeout=45_000
        )
        page.locator("#loading.is-done").wait_for(state="hidden", timeout=5_000)
        controls = page.locator("#mobile-controls")
        assert not controls.is_visible()
        page.evaluate(
            "localStorage.setItem('open-toontown.mobile-controls-smoke', '1')"
        )

        page.locator('#mobile-form-proxy[data-mode="login"]').wait_for(
            state="visible", timeout=10_000
        )
        account_input = page.locator("#mobile-account-name")
        password_input = page.locator("#mobile-account-password")
        account_input.fill(ACCOUNT)
        password_input.fill(PASSWORD)
        password_input.press("Enter")
        wait_for_console(page, console_lines, "AvatarChooser.enter")
        assert not controls.is_visible()
        page.screenshot(path=str(CHOOSER_SCREENSHOT), full_page=True)

        canvas = page.locator("#canvas")
        canvas.tap(position={"x": 75, "y": 138})
        wait_for_console(page, console_lines, "teleportInDone:")
        if any("teleportInDone: popup" in line for line in console_lines):
            canvas.tap(position={"x": 195, "y": 459})
        page.locator("#mobile-controls.is-visible").wait_for(
            state="visible", timeout=10_000
        )
        page.locator('[data-mobile-action="exitActivity"]').tap()
        page.wait_for_timeout(750)
        assert controls.is_visible(), (
            "mobile controls disappeared while the Shticker Book was open"
        )
        page.locator('[data-mobile-action="exitActivity"]').tap()
        page.screenshot(path=str(GAMEPLAY_SCREENSHOT), full_page=True)
    except Exception:
        page.screenshot(path=str(FAILURE_SCREENSHOT), full_page=True)
        print(json.dumps({
            "console_tail": console_lines[-50:],
            "page_errors": page_errors,
            "failure_screenshot": str(FAILURE_SCREENSHOT),
        }, indent=2))
        raise

    result = {
        "viewport": "390x844",
        "controls_hidden_at_login": True,
        "controls_hidden_at_chooser": True,
        "controls_visible_in_gameplay": controls.is_visible(),
        "controls_visible_with_book_open": True,
        "chooser_screenshot": str(CHOOSER_SCREENSHOT),
        "gameplay_screenshot": str(GAMEPLAY_SCREENSHOT),
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["controls_visible_in_gameplay"]
assert not page_errors
