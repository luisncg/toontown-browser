"""Capture the TTC tunnel sign through every TAB camera position."""

import json
import os
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_TUNNEL_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_TUNNEL_PASSWORD", "test")


def wait_for_console(page, lines, marker, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(50)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-180:]))
    )


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
    wait_for_console(page, console_lines, "teleportInDone:")
    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
    page.wait_for_timeout(3000)

    screenshots = []
    for camera_index in range(6):
        path = (
            PROJECT_DIR
            / ".build-wasm"
            / ("browser-tunnel-sign-camera-%d.png" % camera_index)
        )
        canvas.screenshot(path=str(path))
        screenshots.append(str(path))
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)

    far_image = Image.open(screenshots[3]).convert("RGB")
    width, height = far_image.size
    far_sign_crop = far_image.crop(
        (
            round(width * 0.34),
            round(height * 0.045),
            round(width * 0.66),
            round(height * 0.22),
        )
    )
    far_sign_pixels = far_sign_crop.load()
    far_sign_green_pixels = 0
    for y in range(far_sign_crop.height):
        for x in range(far_sign_crop.width):
            red, green, blue = far_sign_pixels[x, y]
            if (
                green >= 35
                and green >= red * 1.8
                and green >= blue * 1.8
                and red < 80
                and blue < 80
            ):
                far_sign_green_pixels += 1

    result = {
        "viewport": "1280x900",
        "canvas": "%dx%d" % (width, height),
        "screenshots": screenshots,
        "far_sign_green_pixels": far_sign_green_pixels,
        "page_errors": page_errors,
        "crash_lines": [
            line
            for line in console_lines
            if "Traceback (most recent call last)" in line
            or "Exception occurred in PythonTask" in line
        ],
        "console_tail": console_lines[-80:],
    }
    browser.close()

print(json.dumps(result, indent=2))
assert not result["page_errors"]
assert not result["crash_lines"]
assert result["far_sign_green_pixels"] > 500
