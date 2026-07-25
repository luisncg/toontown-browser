"""Play and capture the universal animation-only 67 SpeedChat emotion."""

import hashlib
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
ENTRY_SCREENSHOT = PROJECT_DIR / '.build-wasm' / 'browser-emote-67-entry.png'
LEFT_SCREENSHOT = PROJECT_DIR / '.build-wasm' / 'browser-emote-67-left-high.png'
RIGHT_SCREENSHOT = PROJECT_DIR / '.build-wasm' / 'browser-emote-67-right-high.png'
MENU_SCREENSHOT = PROJECT_DIR / '.build-wasm' / 'browser-emote-67-menu.png'
SELECTED_SCREENSHOT = (
    PROJECT_DIR / '.build-wasm' / 'browser-emote-67-menu-selected.png'
)
GAME_URL = os.environ.get('OPEN_TOONTOWN_URL', 'http://127.0.0.1:8180')
ACCOUNT = os.environ.get('OPEN_TOONTOWN_EMOTE_ACCOUNT', 'test')
PASSWORD = os.environ.get('OPEN_TOONTOWN_EMOTE_PASSWORD', 'test')


def wait_for_console(page, lines, marker, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(50)
    raise AssertionError(
        'Timed out waiting for %r. Console tail:\n%s'
        % (marker, '\n'.join(lines[-180:]))
    )


def wait_for_console_count(page, lines, marker, count, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(
        'Timed out waiting for %r occurrence %d. Console tail:\n%s'
        % (marker, count, '\n'.join(lines[-180:]))
    )


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
        "localStorage.setItem('open-toontown.emote-67-smoke', '1');"
        "localStorage.setItem('open-toontown.emote-67-trigger', '0');"
    )

    # The phase-streamed Emscripten package can keep an HTTP request open after
    # the page is usable, so networkidle is not a reliable readiness signal.
    page.goto(GAME_URL, wait_until='domcontentloaded', timeout=120_000)
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
        page.wait_for_timeout(300)
    # Let the playground-title overlay clear so it cannot obscure the gloves in
    # the left-high/right-high calibration captures.
    page.wait_for_timeout(3000)

    page.evaluate(
        "localStorage.setItem('open-toontown.emote-67-trigger', '1')"
    )

    wait_for_console(page, console_lines, '[BrowserEmote67Test] registered=')
    page.wait_for_timeout(120)
    page.screenshot(path=str(ENTRY_SCREENSHOT), full_page=True)
    wait_for_console(page, console_lines, '[BrowserEmote67Test] left-high')
    page.screenshot(path=str(LEFT_SCREENSHOT), full_page=True)
    wait_for_console(page, console_lines, '[BrowserEmote67Test] right-high')
    page.screenshot(path=str(RIGHT_SCREENSHOT), full_page=True)
    wait_for_console(page, console_lines, '[BrowserEmote67Test] cleanup')
    assert sum(
        '[BrowserEmote67Test] left-high' in line for line in console_lines
    ) == 5
    assert sum(
        '[BrowserEmote67Test] right-high' in line for line in console_lines
    ) == 5
    page.wait_for_timeout(500)

    # The green top-left button opens SpeedChat; retain a visual artifact proving
    # the universal entry is exposed through the real in-game menu.
    canvas.click(position={'x': 90, 'y': 25})
    page.wait_for_timeout(300)
    canvas.click(position={'x': 200, 'y': 25})
    page.wait_for_timeout(500)
    page.screenshot(path=str(MENU_SCREENSHOT), full_page=True)
    # Select the visible sixth emotion row (67) through SpeedChat itself and
    # require a second synchronized animation run.
    canvas.click(position={'x': 320, 'y': 133})
    wait_for_console_count(
        page,
        console_lines,
        '[BrowserEmote67Test] left-high',
        6,
    )
    page.screenshot(path=str(SELECTED_SCREENSHOT), full_page=True)
    wait_for_console_count(
        page,
        console_lines,
        '[BrowserEmote67Test] cleanup',
        2,
    )

    emote_lines = [
        line for line in console_lines if '[BrowserEmote67Test]' in line
    ]
    paused_idle_frames = [
        int(line.rsplit('=', 1)[1])
        for line in emote_lines if 'idle-frame-paused=' in line
    ]
    resumed_idle_frames = [
        int(line.rsplit('=', 1)[1])
        for line in emote_lines if 'idle-frame-resumed=' in line
    ]
    crash_lines = [
        line
        for line in console_lines
        if 'Traceback (most recent call last)' in line
        or 'Exception occurred in PythonTask' in line
        or 'AttributeError:' in line
    ]
    actor_animation_lines = [
        line for line in console_lines
        if '[BrowserPerformanceActorAnimation]' in line
    ]
    hashes = {
        'left': hashlib.sha256(LEFT_SCREENSHOT.read_bytes()).hexdigest(),
        'right': hashlib.sha256(RIGHT_SCREENSHOT.read_bytes()).hexdigest(),
    }
    result = {
        'viewport': '1280x900',
        'registered': any('registered=67 access=True' in line for line in emote_lines),
        'left_high': any('left-high' in line for line in emote_lines),
        'right_high': any('right-high' in line for line in emote_lines),
        'cleaned_up': any('cleanup' in line for line in emote_lines),
        'selected_from_speedchat': sum(
            'left-high' in line for line in emote_lines
        ) >= 10,
        'five_cycles_per_run': (
            sum('left-high' in line for line in emote_lines) == 10
            and sum('right-high' in line for line in emote_lines) == 10
        ),
        'idle_frame_continuity': (
            len(paused_idle_frames) == 2
            and len(resumed_idle_frames) == 2
            and all(
                abs(paused - resumed) <= 1
                for paused, resumed in zip(
                    paused_idle_frames, resumed_idle_frames)
            )
        ),
        'paused_idle_frames': paused_idle_frames,
        'resumed_idle_frames': resumed_idle_frames,
        'distinct_pose_frames': hashes['left'] != hashes['right'],
        'active_element': page.evaluate('document.activeElement.id'),
        'crash_lines': crash_lines,
        'actor_animation_lines': actor_animation_lines,
        'page_errors': page_errors,
        'entry_screenshot': str(ENTRY_SCREENSHOT),
        'left_screenshot': str(LEFT_SCREENSHOT),
        'right_screenshot': str(RIGHT_SCREENSHOT),
        'menu_screenshot': str(MENU_SCREENSHOT),
        'selected_screenshot': str(SELECTED_SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result['registered']
assert result['left_high'] and result['right_high']
assert result['cleaned_up']
assert result['selected_from_speedchat']
assert result['five_cycles_per_run']
assert result['idle_frame_continuity']
assert result['distinct_pose_frames']
assert result['active_element'] == 'canvas'
assert not result['crash_lines']
assert not result['page_errors']
