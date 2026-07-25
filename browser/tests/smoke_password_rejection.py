"""Verify a bad password is rejected without crashing or entering an account."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / '.build-wasm/browser-password-rejection.png'
GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
ACCOUNT = os.environ.get('OPEN_TOONTOWN_TEST_ACCOUNT', 'wasmbrowsersmoke')


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
    page.keyboard.type('definitely-the-wrong-password')
    canvas.click(position={'x': 590, 'y': 532})

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if any('Login failed:' in line for line in console_lines):
            break
        page.wait_for_timeout(250)

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    browser.close()

result = {
    'password_rejected': any(
        'Login failed:' in line for line in console_lines),
    'avatar_chooser_entered': any(
        'AvatarChooser.enter' in line for line in console_lines),
    'runtime_error': any(
        'Runtime error' in line for line in console_lines),
    'console_errors': console_errors,
    'page_errors': page_errors,
    'screenshot': str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert result['password_rejected']
assert not result['avatar_chooser_entered']
assert not result['runtime_error']
assert not console_errors
assert not page_errors
