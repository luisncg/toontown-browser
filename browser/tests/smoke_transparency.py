"""Render the TTC ice-cream treasure and verify its card stays transparent."""

import json
import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-transparency-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


def matching_fraction(image, box, expected, tolerance=3):
    matching = 0
    total = 0
    patch = image.crop(box)
    pixels = patch.load()
    for y in range(patch.height):
        for x in range(patch.width):
            total += 1
            if all(
                abs(actual - target) <= tolerance
                for actual, target in zip(pixels[x, y], expected)
            ):
                matching += 1
    return matching / total


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_errors = []
    page_errors = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(
        f"{GAME_URL}/?alpha-test=1",
        wait_until="networkidle",
        timeout=120_000,
    )
    page.locator("#loading.is-done").wait_for(
        state="hidden",
        timeout=45_000,
    )
    page.wait_for_timeout(1_000)
    canvas = page.locator("#canvas")
    canvas.screenshot(path=str(SCREENSHOT))
    browser.close()

image = Image.open(SCREENSHOT).convert("RGB")
width, height = image.size
background = image.getpixel((20, 20))

# With the fixed 7x5 orthographic framing, these patches are inside the
# ice-cream card's rectangular geometry but outside its painted silhouette.
# They must therefore show the clear-color background, not black texture RGB.
corner_patches = (
    (width * 0.35, height * 0.19, width * 0.38, height * 0.27),
    (width * 0.62, height * 0.19, width * 0.65, height * 0.27),
    (width * 0.35, height * 0.73, width * 0.40, height * 0.81),
    (width * 0.60, height * 0.73, width * 0.65, height * 0.81),
)
corner_patches = tuple(tuple(round(value) for value in box) for box in corner_patches)
background_fractions = [
    matching_fraction(image, box, background) for box in corner_patches
]
center = image.getpixel((width // 2, height // 2))

result = {
    "viewport": "1280x900",
    "canvas": f"{width}x{height}",
    "background_rgb": background,
    "center_rgb": center,
    "transparent_patch_matches": background_fractions,
    "console_errors": console_errors,
    "page_errors": page_errors,
    "screenshot": str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert all(fraction > 0.99 for fraction in background_fractions)
assert sum(abs(actual - expected) for actual, expected in zip(center, background)) > 80
assert not console_errors
assert not page_errors
