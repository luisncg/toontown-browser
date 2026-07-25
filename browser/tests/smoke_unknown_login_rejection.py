"""Verify ordinary Login cannot silently register an unknown username."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / '.build-wasm/unknown-login-rejection.png'
GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
ACCOUNT = 'unknown-login-must-not-register'
PASSWORD = 'not-a-real-account-password'


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=['--enable-webgl', '--ignore-gpu-blocklist'],
    )
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    console_lines = []
    console_errors = []
    page_errors = []

    def capture_console(message):
        console_lines.append(message.text)
        if message.type == 'error':
            console_errors.append(message.text)

    page.on('console', capture_console)
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.goto(GAME_URL, wait_until='networkidle', timeout=120_000)
    page.locator('#loading.is-done').wait_for(state='attached', timeout=45_000)

    canvas = page.locator('#canvas')
    canvas.click(position={'x': 660, 'y': 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={'x': 660, 'y': 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={'x': 590, 'y': 532})

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if any('Login failed:' in line for line in console_lines):
            break
        page.wait_for_timeout(250)

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    browser.close()

result = {
    'unknown_login_rejected': any(
        'Login failed: The account name or password is incorrect.' in line
        for line in console_lines),
    'avatar_chooser_entered': any(
        'AvatarChooser.enter' in line for line in console_lines),
    'console_errors': console_errors,
    'page_errors': page_errors,
    'screenshot': str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert result['unknown_login_rejected']
assert not result['avatar_chooser_entered']
assert not result['console_errors']
assert not result['page_errors']
