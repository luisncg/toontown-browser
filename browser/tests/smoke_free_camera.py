"""Verify the browser POV camera can enter, fly, change FOV, copy, and exit."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
ACCOUNT = os.environ.get('OPEN_TOONTOWN_FREE_CAMERA_ACCOUNT', 'test')
PASSWORD = os.environ.get('OPEN_TOONTOWN_FREE_CAMERA_PASSWORD', 'test')
ACTIVE_KEY = 'open-toontown.free-camera-active'
PAYLOAD_KEY = 'open-toontown.free-camera-pov'
COPY_STATUS_KEY = 'open-toontown.free-camera-copy-status'
SCREENSHOT = Path(
    os.environ.get(
        'OPEN_TOONTOWN_FREE_CAMERA_SCREENSHOT',
        '.build-wasm/screenshots/free-camera-lab.png',
    )
)


def wait_for_console(page, lines, marker, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(100)
    raise AssertionError('Timed out waiting for %r' % marker)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=['--enable-webgl', '--ignore-gpu-blocklist'],
    )
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    context.grant_permissions(
        ['clipboard-read', 'clipboard-write'],
        origin=GAME_URL,
    )
    page = context.new_page()
    console_lines = []
    page_errors = []
    page.on('console', lambda message: console_lines.append(message.text))
    page.on('pageerror', lambda error: page_errors.append(str(error)))

    page.goto(GAME_URL, wait_until='networkidle', timeout=120_000)
    page.locator('#loading.is-done').wait_for(state='attached', timeout=45_000)
    canvas = page.locator('#canvas')
    canvas.click(position={'x': 660, 'y': 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={'x': 660, 'y': 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={'x': 590, 'y': 532})
    wait_for_console(page, console_lines, 'AvatarChooser.enter')
    canvas.click(position={'x': 235, 'y': 265})
    wait_for_console(page, console_lines, 'teleportInDone:')
    if any('teleportInDone: popup' in line for line in console_lines):
        canvas.click(position={'x': 590, 'y': 540})
        page.wait_for_timeout(500)

    # teleportInDone is emitted just before the walk state finishes enabling
    # controls and the smart camera; wait for that final state transition.
    page.wait_for_timeout(1_000)
    canvas.press('Shift+F8')
    try:
        page.wait_for_function(
            "key => localStorage.getItem(key) === '1'",
            arg=ACTIVE_KEY,
            timeout=5_000,
        )
    except Exception:
        print(json.dumps({
            'active': page.evaluate(
                'key => localStorage.getItem(key)', ACTIVE_KEY),
            'recent_console': console_lines[-100:],
            'page_errors': page_errors,
        }, indent=2))
        raise
    initial_payload = page.evaluate(
        'key => localStorage.getItem(key)', PAYLOAD_KEY)
    assert initial_payload.startswith('TOONTOWN_POV ')

    canvas.press('KeyW', delay=450)
    page.wait_for_timeout(250)
    moved_payload = page.evaluate(
        'key => localStorage.getItem(key)', PAYLOAD_KEY)
    assert moved_payload != initial_payload

    fov_before = float(initial_payload.split('hfov=')[1].split()[0])
    canvas.hover(position={'x': 640, 'y': 400})
    page.mouse.wheel(0, 100)
    page.wait_for_timeout(250)
    zoomed_payload = page.evaluate(
        'key => localStorage.getItem(key)', PAYLOAD_KEY)
    fov_after = float(zoomed_payload.split('hfov=')[1].split()[0])
    assert fov_after > fov_before
    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOT))

    canvas.press('KeyC')
    page.wait_for_function(
        "key => localStorage.getItem(key).startsWith('POV copied')",
        arg=COPY_STATUS_KEY,
        timeout=5_000,
    )
    clipboard_payload = page.evaluate('navigator.clipboard.readText()')
    assert clipboard_payload == zoomed_payload

    canvas.press('Shift+F8')
    page.wait_for_function(
        "key => localStorage.getItem(key) === '0'",
        arg=ACTIVE_KEY,
        timeout=5_000,
    )
    assert not page_errors

    result = {
        'viewport': '1280x900',
        'entered': True,
        'moved': moved_payload != initial_payload,
        'fov_before': fov_before,
        'fov_after': fov_after,
        'clipboard_matches': clipboard_payload == zoomed_payload,
        'screenshot': str(SCREENSHOT),
        'exited': page.evaluate(
            'key => localStorage.getItem(key)', ACTIVE_KEY) == '0',
    }
    browser.close()

print(json.dumps(result, indent=2))
