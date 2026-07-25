"""Exercise the reactive-gag picker through the real in-game inventory UI."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
ACCOUNT = os.environ.get('OPEN_TOONTOWN_REACTIVE_ACCOUNT', 'test')
PASSWORD = os.environ.get('OPEN_TOONTOWN_REACTIVE_PASSWORD', 'test')
REGULAR_SCREENSHOT = PROJECT_DIR / '.build-wasm' / 'reactive-ui-regular.png'
REACTIVE_SCREENSHOT = PROJECT_DIR / '.build-wasm' / 'reactive-ui-picker.png'


def wait_for(lines, marker, page, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(50)
    raise AssertionError('Timed out waiting for %r. Tail:\n%s' % (
        marker, '\n'.join(lines[-180:])))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=['--enable-webgl', '--ignore-gpu-blocklist'],
    )
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    console_lines = []
    page_errors = []
    page.on('console', lambda message: console_lines.append(message.text))
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.add_init_script(
        "localStorage.setItem('open-toontown.reactive-gag-smoke', '1');"
    )
    page.goto(GAME_URL, wait_until='networkidle', timeout=120_000)
    page.locator('#loading.is-done').wait_for(state='attached', timeout=45_000)
    canvas = page.locator('#canvas')
    canvas.click(position={'x': 660, 'y': 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={'x': 660, 'y': 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={'x': 590, 'y': 532})
    wait_for(console_lines, 'AvatarChooser.enter', page)
    canvas.click(position={'x': 235, 'y': 265})
    wait_for(console_lines, 'teleportInDone:', page)
    if any('teleportInDone: popup' in line for line in console_lines):
        canvas.click(position={'x': 590, 'y': 540})
    wait_for(console_lines, '[BrowserReactiveGagTest] battle-menu-ready', page)
    page.wait_for_timeout(800)
    canvas.screenshot(path=str(REGULAR_SCREENSHOT))
    canvas.click(position={'x': 300, 'y': 442})
    page.wait_for_timeout(400)
    canvas.screenshot(path=str(REACTIVE_SCREENSHOT))
    count_marker = '[BrowserReactiveGagTest] counts=10:10'
    refill_updates = sum(
        count_marker in line for line in console_lines
    )
    canvas.click(position={'x': 490, 'y': 379})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and sum(
            count_marker in line for line in console_lines) < refill_updates + 1:
        page.wait_for_timeout(50)
    canvas.click(position={'x': 715, 'y': 379})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and sum(
            count_marker in line for line in console_lines) < refill_updates + 2:
        page.wait_for_timeout(50)
    refill_buttons_work = sum(
        count_marker in line for line in console_lines
    ) >= refill_updates + 2
    selection_marker = '[BrowserReactiveGagTest] selected='
    # The second Decoy slot is a future gag and must remain inert.
    canvas.click(position={'x': 410, 'y': 230})
    page.wait_for_timeout(250)
    disabled_slot_inert = not any(
        selection_marker in line for line in console_lines
    )
    canvas.click(position={'x': 336, 'y': 230})
    wait_for(console_lines, selection_marker + '101:0', page)
    canvas.click(position={'x': 336, 'y': 294})
    wait_for(console_lines, selection_marker + '102:0', page)

    crash_lines = [
        line for line in console_lines
        if 'Traceback (most recent call last)' in line
        or 'Exception occurred in PythonTask' in line
        or 'AssertionError:' in line
        or 'WebGL: INVALID_OPERATION' in line
        or 'GL error 0x502' in line
    ]
    result = {
        'viewport': '1280x900',
        'battle_menu_ready': any(
            '[BrowserReactiveGagTest] battle-menu-ready' in line
            for line in console_lines
        ),
        'disabled_slot_inert': disabled_slot_inert,
        'initial_counts': any(
            'battle-menu-ready counts=10:10' in line
            for line in console_lines
        ),
        'refill_buttons_work': refill_buttons_work,
        'fake_moustache_selected': any(
            selection_marker + '101:0' in line for line in console_lines
        ),
        'whoopee_cushion_selected': any(
            selection_marker + '102:0' in line for line in console_lines
        ),
        'active_element': page.evaluate('document.activeElement.id'),
        'crash_lines': crash_lines,
        'page_errors': page_errors,
        'screenshot': str(REGULAR_SCREENSHOT),
        'reactive_screenshot': str(REACTIVE_SCREENSHOT),
        'console_tail': console_lines[-80:],
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result['battle_menu_ready']
assert result['disabled_slot_inert']
assert result['initial_counts']
assert result['refill_buttons_work']
assert result['fake_moustache_selected']
assert result['whoopee_cushion_selected']
assert result['active_element'] == 'canvas'
assert not result['crash_lines']
assert not result['page_errors']
