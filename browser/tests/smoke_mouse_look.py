"""Exercise browser wiring for experimental mouse steering in walk gameplay.

Headless Chromium does not implement Pointer Lock, returning WrongDocumentError
even for a bare, focused canvas.  This smoke therefore verifies the real game
reaches walk-mode availability and attempts capture.  The actual heading math
is covered by test_mouse_look_native.py.
"""

import json
import os
import time

from playwright.sync_api import sync_playwright


GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_MOUSE_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_MOUSE_PASSWORD", "test")
SETTINGS_KEY = "open-toontown.useropt.v1"
AVAILABLE_KEY = "open-toontown.experimental-mouse-look-available"
HEADING_KEY = "open-toontown.experimental-mouse-look-heading"
SMOKE_KEY = "open-toontown.experimental-mouse-look-smoke"
REGION_KEY = "open-toontown.experimental-mouse-look-region"


def wait_for_console(page, lines, marker, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(100)
    raise AssertionError("Timed out waiting for %r" % marker)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_lines = []
    console_errors = []
    page_errors = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    settings = json.dumps(
        {"experimental-mouse-look": True}, separators=(",", ":"))
    page.add_init_script(
        "localStorage.setItem(%s, %s);"
        "localStorage.setItem(%s, '1');"
        "localStorage.removeItem(%s);"
        % tuple(map(json.dumps, (
            SETTINGS_KEY, settings, SMOKE_KEY, HEADING_KEY)))
    )

    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")

    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for_console(page, console_lines, "AvatarChooser.enter")
    canvas.click(position={"x": 235, "y": 265})
    wait_for_console(page, console_lines, "teleportInDone:", timeout=60)
    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    page.wait_for_function(
        "key => localStorage.getItem(key) === '1'",
        arg=AVAILABLE_KEY,
        timeout=5_000,
    )
    box = canvas.bounding_box()
    candidate_points = [
        (0.95, 0.08), (0.90, 0.08), (0.05, 0.08),
        (0.95, 0.92), (0.05, 0.92),
    ]
    candidate_points.extend(
        (x / 10.0, y / 10.0)
        for y in range(1, 10)
        for x in range(1, 10)
    )
    blocked_point = None
    allowed_point = None
    region_samples = []
    for x_ratio, y_ratio in candidate_points:
        x = box["x"] + box["width"] * x_ratio
        y = box["y"] + box["height"] * y_ratio
        page.mouse.move(x, y)
        page.wait_for_timeout(35)
        capture_allowed = page.evaluate(
            "window.Module._browser_mouse_look_capture_allowed() !== 0")
        region_samples.append({
            "point": [round(x_ratio, 2), round(y_ratio, 2)],
            "allowed": capture_allowed,
            "region": page.evaluate(
                "key => localStorage.getItem(key)", REGION_KEY),
        })
        if capture_allowed and allowed_point is None:
            allowed_point = (x, y)
        if not capture_allowed and blocked_point is None:
            blocked_point = (x, y)
        if blocked_point is not None and allowed_point is not None:
            break
    assert blocked_point is not None, (
        "No live DirectGUI region was detected: %s" % region_samples)
    assert allowed_point is not None, (
        "No gameplay capture point was detected: %s" % region_samples)

    page.evaluate(
        "window.__experimentalMouseLookPointerLock = 'gui-gate-not-requested'")
    page.mouse.move(*blocked_point)
    page.mouse.down()
    page.wait_for_timeout(250)
    gui_capture_status = page.evaluate(
        "window.__experimentalMouseLookPointerLock ?? null")
    # Release outside the widget so this input-only regression does not open
    # the Friends panel (or another discovered HUD control).
    page.mouse.move(*allowed_point)
    page.mouse.up()
    page.wait_for_timeout(100)

    page.mouse.click(*allowed_point)
    page.wait_for_function(
        "window.__experimentalMouseLookPointerLock !== 'requesting'",
        timeout=5_000,
    )
    capture_status = page.evaluate(
        "window.__experimentalMouseLookPointerLock ?? null")
    captured_pointer = page.evaluate(
        "document.pointerLockElement === document.querySelector('#canvas')")
    headless_pointer_lock_blocked = (
        not captured_pointer
        and capture_status is not None
        and capture_status.startswith("error: ")
        and "root document" in capture_status
        and "not valid for pointer lock" in capture_status
    )

    if captured_pointer:
        box = canvas.bounding_box()
        page.mouse.move(box["x"] + 560, box["y"] + 330)
        page.mouse.move(box["x"] + 760, box["y"] + 330, steps=8)
        page.wait_for_function(
            "key => localStorage.getItem(key) !== null",
            arg=HEADING_KEY,
            timeout=5_000,
        )
        turned_heading = float(page.evaluate(
            "key => localStorage.getItem(key)", HEADING_KEY))
        page.keyboard.press("Escape")
        page.wait_for_function(
            "document.pointerLockElement === null", timeout=5_000)
    else:
        turned_heading = None

    unexpected_console_errors = [
        error for error in console_errors
        if error != (
            "Failed to load resource: the server responded with a status of "
            "404 (Not Found)"
        )
    ]
    result = {
        "viewport": "1280x900",
        "available_in_walk": page.evaluate(
            "key => localStorage.getItem(key)", AVAILABLE_KEY) == "1",
        "direct_gui_capture_status": gui_capture_status,
        "direct_gui_capture_blocked": (
            gui_capture_status == "gui-gate-not-requested"),
        "capture_status": capture_status,
        "captured_pointer": captured_pointer,
        "headless_pointer_lock_blocked": headless_pointer_lock_blocked,
        "turned_heading": turned_heading,
        "released_with_escape": page.evaluate(
            "document.pointerLockElement === null"),
        "unexpected_console_errors": unexpected_console_errors,
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["available_in_walk"]
assert result["direct_gui_capture_blocked"]
assert result["captured_pointer"] or result["headless_pointer_lock_blocked"]
if result["captured_pointer"]:
    assert abs(result["turned_heading"]) > 0.1
assert result["released_with_escape"]
assert not result["unexpected_console_errors"]
assert not result["page_errors"]
