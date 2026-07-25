"""Create a Toon through the real browser UI for state-changing smoke tests.

This script is intentionally opt-in and only targets the task-owned
``wasmbrowsersmoke`` account.  It never edits Astron's backing files.
"""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = "wasmbrowsersmoke"
PASSWORD = "localbrowser"
SLOT = int(os.environ.get("OPEN_TOONTOWN_MAKE_SLOT", "0"))
FINALIZE = os.environ.get("OPEN_TOONTOWN_MAKE_FINALIZE", "1") == "1"
SKIP_TUTORIAL = os.environ.get("OPEN_TOONTOWN_SKIP_TUTORIAL", "0") == "1"
PROMPT_ONLY = os.environ.get("OPEN_TOONTOWN_PROMPT_ONLY", "0") == "1"
SCREENSHOT = PROJECT_DIR / ".build-wasm" / ("make-toon-slot-%d.png" % SLOT)

SLOT_POSITIONS = {
    0: (235, 265),
    1: (590, 265),
    2: (945, 265),
    3: (235, 500),
    4: (590, 500),
    5: (945, 500),
}


def wait_for(page, lines, marker, count=1, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-160:]))
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_lines = []
    console_errors = []
    page_errors = []

    def capture_console(message):
        console_lines.append(message.text)
        if message.type == "error":
            console_errors.append(message.text)

    page.on("console", capture_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(GAME_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    canvas = page.locator("#canvas")

    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for(page, console_lines, "AvatarChooser.enter")

    slot_x, slot_y = SLOT_POSITIONS[SLOT]
    canvas.click(position={"x": slot_x, "y": slot_y})
    page.wait_for_timeout(4_500)

    # Boy, then the shared Next button through body, color and clothes.
    canvas.click(position={"x": 413, "y": 595})
    for _shop in range(4):
        page.wait_for_timeout(750)
        canvas.click(position={"x": 1_109, "y": 620})
        page.wait_for_timeout(3_000)

    if FINALIZE:
        canvas.click(position={"x": 1_109, "y": 620})
        page.wait_for_timeout(2_500)
        if SKIP_TUTORIAL and not PROMPT_ONLY:
            # The right-hand choice in the standard two-choice dialog.
            canvas.click(position={"x": 710, "y": 437})
            page.wait_for_timeout(8_000)
        elif not PROMPT_ONLY:
            wait_for(page, console_lines, "teleportInDone: walk", timeout=45)

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    result = {
        "account": ACCOUNT,
        "slot": SLOT,
        "finalized": FINALIZE,
        "skip_tutorial": SKIP_TUTORIAL,
        "avatar_chooser_entries": sum(
            "AvatarChooser.enter" in line for line in console_lines
        ),
        "console_errors": console_errors,
        "page_errors": page_errors,
        "console_tail": console_lines[-100:],
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert not [
    line
    for line in result["console_errors"]
    if "Failed to load resource" not in line
]
assert not result["page_errors"]
