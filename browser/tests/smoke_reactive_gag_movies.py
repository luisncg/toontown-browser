"""Render both reactive gag movies in WebGL and verify complete cleanup."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
WHOOP_SNAPSHOT = PROJECT_DIR / '.build-wasm' / 'reactive-whoopee-active.png'
DECOY_PUTTING_SNAPSHOT = PROJECT_DIR / '.build-wasm' / 'reactive-decoy-putting-on.png'
DECOY_SNAPSHOT = PROJECT_DIR / '.build-wasm' / 'reactive-decoy-active.png'


def wait_for(lines, marker, page, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(50)
    raise AssertionError('Timed out waiting for %r. Tail:\n%s' % (
        marker, '\n'.join(lines[-120:])))


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
    page.goto(
        '%s/?reactive-test=1' % GAME_URL,
        wait_until='networkidle',
        timeout=120_000,
    )
    page.locator('#loading.is-done').wait_for(state='attached', timeout=45_000)
    wait_for(console_lines, '[BrowserReactiveGagMovie] whoopee-active', page)
    page.locator('#canvas').screenshot(path=str(WHOOP_SNAPSHOT))
    wait_for(console_lines, '[BrowserReactiveGagMovie] decoy-success-putting-active', page)
    page.locator('#canvas').screenshot(path=str(DECOY_PUTTING_SNAPSHOT))
    wait_for(console_lines, '[BrowserReactiveGagMovie] decoy-success-active', page)
    page.locator('#canvas').screenshot(path=str(DECOY_SNAPSHOT))
    wait_for(console_lines, '[BrowserReactiveGagMovie] complete', page)
    browser.close()

movie_lines = [
    line for line in console_lines if '[BrowserReactiveGagMovie]' in line
]
cleanup_lines = [line for line in movie_lines if '-clean ' in line]
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
    'whoopee_active': any('whoopee-active' in line for line in movie_lines),
    'decoy_active': any('decoy-success-active' in line for line in movie_lines),
    'cleanup_lines': cleanup_lines,
    'cancel_contract': any(
        'complete skips=True failureSkips=False' in line
        for line in movie_lines
    ),
    'crash_lines': crash_lines,
    'page_errors': page_errors,
    'whoopee_screenshot': str(WHOOP_SNAPSHOT),
    'decoy_putting_screenshot': str(DECOY_PUTTING_SNAPSHOT),
    'decoy_screenshot': str(DECOY_SNAPSHOT),
    'console_tail': console_lines[-80:],
}
print(json.dumps(result, indent=2))

assert result['whoopee_active']
assert result['decoy_active']
assert any(
    'decoy-success-putting-active moustache=False handMoustache=True glassesUnchanged=True' in line
    for line in movie_lines
)
assert any(
    'decoy-success-active moustache=True handMoustache=False glassesUnchanged=True' in line
    for line in movie_lines
)
assert len(cleanup_lines) == 3
assert all(
    'cushion=True punctuation=True moustache=True handMoustache=True glasses=True flustered=True' in line
    for line in cleanup_lines
)
assert any(
    'whoopee-active' in line and 'flusterTurns=2' in line
    for line in movie_lines
)
assert result['cancel_contract']
assert not crash_lines
assert not page_errors
