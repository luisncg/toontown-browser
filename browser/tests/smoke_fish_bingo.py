"""Exercise a live Fish Bingo card from a real browser fishing pier."""

import json
import math
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-fish-bingo-smoke.png"
APP_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-fish-bingo-approach.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")

# The second Toon is a fixture created through the normal Make-a-Toon flow.
ACCOUNT = "wasmbrowsersmoke"
PASSWORD = "localbrowser"
TOON_SLOT = (590, 265)
TTC_SPOTS = (
    (-63.5335, 41.6480),
    (-90.2253, 42.5202),
    (-94.9218, 31.4153),
    (-77.5199, 46.9817),
)
POSITION_RE = re.compile(
    r"Fish Bingo (?:local|settled|navigation) position (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) "
    r"heading (-?[\d.]+)"
)


def wait_for(page, lines, marker, count=1, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-180:]))
    )


def normalize_heading(value):
    return (value + 180.0) % 360.0 - 180.0


def latest_position(lines):
    for line in reversed(lines):
        match = POSITION_RE.search(line)
        if match:
            return tuple(map(float, match.groups()))
    return None


def wait_for_position(page, lines, previous_count, timeout=5):
    wait_for(
        page,
        lines,
        "Fish Bingo navigation position",
        count=previous_count + 1,
        timeout=timeout,
    )
    return latest_position(lines)


def drive_to(page, lines, target_x, target_y, occupied_marker):
    metrics = []
    for _attempt in range(8):
        x, y, _z, heading = latest_position(lines)
        dx = target_x - x
        dy = target_y - y
        distance = math.hypot(dx, dy)
        if distance <= 2.5 or any(occupied_marker in line for line in lines):
            break
        desired_heading = math.degrees(math.atan2(-dx, dy))
        turn = normalize_heading(desired_heading - heading)
        turn_key = "ArrowLeft" if turn > 0 else "ArrowRight"
        position_count = sum(
            "Fish Bingo navigation position" in line for line in lines
        )
        page.keyboard.down(turn_key)
        page.wait_for_timeout(max(50, int(abs(turn) / 80.0 * 1_000)))
        page.keyboard.up(turn_key)
        wait_for_position(page, lines, position_count)

        position_count = sum(
            "Fish Bingo navigation position" in line for line in lines
        )
        page.keyboard.down("ArrowUp")
        page.wait_for_timeout(min(1_500, max(150, int(distance / 16.0 * 1_000))))
        page.keyboard.up("ArrowUp")
        wait_for_position(page, lines, position_count)
        actual = latest_position(lines)
        metrics.append(
            {
                "distance": round(distance, 2),
                "turn": round(turn, 2),
                "actual": [round(value, 2) for value in actual],
            }
        )
    return metrics


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_lines = []
    page_errors = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.add_init_script(
        "localStorage.setItem('open-toontown.fish-bingo-navigation', '1')"
    )

    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")
    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for(page, console_lines, "AvatarChooser.enter")
    canvas.click(position={"x": TOON_SLOT[0], "y": TOON_SLOT[1]})

    wait_for(page, console_lines, "Fish Bingo manager ready", timeout=60)
    wait_for(page, console_lines, "teleportInDone: popup", timeout=60)
    # Starter quest acknowledgement shown by this isolated fixture Toon.
    canvas.click(position={"x": 590, "y": 540})
    wait_for(page, console_lines, "Fish Bingo settled position", timeout=15)

    wait_for(page, console_lines, "Fish Bingo navigation position", timeout=15)
    x, y, _z, heading = latest_position(console_lines)
    target_x, target_y = min(
        TTC_SPOTS,
        key=lambda spot: math.hypot(spot[0] - x, spot[1] - y),
    )
    start = (x, y, heading)
    # Toon position persists and WebAssembly frame cadence varies.  Use the
    # actual position telemetry after every bounded movement segment instead
    # of assuming keyboard hold time equals exact movement distance.
    route_metrics = drive_to(
        page,
        console_lines,
        target_x,
        target_y,
        "Local Toon occupied fishing spot",
    )
    page.screenshot(path=str(APP_SCREENSHOT), full_page=True)

    page.wait_for_timeout(2_000)

    occupied = any("Local Toon occupied fishing spot" in line for line in console_lines)
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "Exception occurred in PythonTask" in line
        or "AttributeError:" in line
    ]
    result = {
        "viewport": "1280x900",
        "start": list(start),
        "target": [target_x, target_y],
        "route": route_metrics,
        "manager_ready": any(
            "Fish Bingo manager ready" in line for line in console_lines
        ),
        "card_ready": any("Fish Bingo card" in line for line in console_lines),
        "playing": any("Fish Bingo state:" in line for line in console_lines),
        "occupied_pier": occupied,
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "console_tail": console_lines[-180:],
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["manager_ready"]
assert result["card_ready"]
assert result["playing"]
assert result["occupied_pier"]
assert not result["crash_lines"]
assert not result["page_errors"]
