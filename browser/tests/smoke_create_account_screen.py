"""Verify the classic Create Account button opens a usable screen."""

import hashlib
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / '.build-wasm/create-account-screen.png'
REJECTION_SCREENSHOT = PROJECT_DIR / '.build-wasm/create-account-duplicate.png'
GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
ACCOUNT = os.environ.get('OPEN_TOONTOWN_TEST_ACCOUNT', 'wasmbrowsersmoke')
PASSWORD = os.environ.get('OPEN_TOONTOWN_TEST_PASSWORD', 'localbrowser')


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
    before = canvas.screenshot()
    canvas.click(position={'x': 590, 'y': 575})

    # Release builds suppress the CreateAccountScreen debug category, so use
    # the rendered canvas transition as the stable signal instead of relying
    # on a development-only log line.
    deadline = time.monotonic() + 10
    after = before
    while time.monotonic() < deadline:
        page.wait_for_timeout(250)
        after = canvas.screenshot()
        if hashlib.sha256(before).digest() != hashlib.sha256(after).digest():
            break

    after = canvas.screenshot(path=str(SCREENSHOT))

    canvas.click(position={'x': 660, 'y': 371})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={'x': 660, 'y': 426})
    page.keyboard.type(PASSWORD)
    canvas.click(position={'x': 660, 'y': 482})
    page.keyboard.type(PASSWORD)
    canvas.click(position={'x': 496, 'y': 538})

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if any('Account creation failed:' in line for line in console_lines):
            break
        if any('Traceback' in line or 'NameError' in line
               or 'AttributeError' in line for line in console_lines):
            break
        page.wait_for_timeout(250)

    canvas.screenshot(path=str(REJECTION_SCREENSHOT))
    browser.close()

canvas_changed = hashlib.sha256(before).digest() != hashlib.sha256(after).digest()
result = {
    'create_account_loaded': canvas_changed,
    'canvas_changed': canvas_changed,
    'traceback': any('Traceback' in line for line in console_lines),
    'name_error': any('NameError' in line for line in console_lines),
    'attribute_error': any('AttributeError' in line for line in console_lines),
    'duplicate_rejected': any(
        'Account creation failed: That user name is already taken.' in line
        for line in console_lines),
    'avatar_chooser_entered': any(
        'AvatarChooser.enter' in line for line in console_lines),
    'console_errors': console_errors,
    'page_errors': page_errors,
    'console_tail': console_lines[-80:],
    'screenshots': {
        'form': str(SCREENSHOT),
        'duplicate_rejection': str(REJECTION_SCREENSHOT),
    },
}
print(json.dumps(result, indent=2))

assert result['create_account_loaded']
assert result['canvas_changed']
assert not result['traceback']
assert not result['name_error']
assert not result['attribute_error']
assert result['duplicate_rejected']
assert not result['avatar_chooser_entered']
assert not result['console_errors']
assert not result['page_errors']
