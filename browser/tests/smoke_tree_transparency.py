"""Render a TTC tree and verify its legacy cutout card stays transparent."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-tree-transparency-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


def matching_fraction(image, box, expected, tolerance=3):
    matching = 0
    patch = image.crop(box)
    pixels = patch.load()
    for y in range(patch.height):
        for x in range(patch.width):
            if all(
                abs(actual - target) <= tolerance
                for actual, target in zip(pixels[x, y], expected)
            ):
                matching += 1
    return matching / (patch.width * patch.height)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_errors = []
    page_errors = []
    failed_responses = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: failed_responses.append(
            {"status": response.status, "url": response.url}
        )
        if response.status >= 400
        else None,
    )

    page.goto(
        f"{GAME_URL}/?tree-alpha-test=1",
        wait_until="networkidle",
        timeout=120_000,
    )
    page.locator("#loading.is-done").wait_for(
        state="hidden",
        timeout=45_000,
    )
    page.wait_for_timeout(1_000)
    page.locator("#canvas").screenshot(path=str(SCREENSHOT))
    browser.close()

image = Image.open(SCREENSHOT).convert("RGB")
width, height = image.size
background = image.getpixel((20, 20))

# These patches sit inside the rectangular foliage card, but outside the
# painted tree silhouette.  A working cutout must reveal the clear color.
card_corner_patches = (
    (width * 0.37, height * 0.06, width * 0.41, height * 0.12),
    (width * 0.66, height * 0.06, width * 0.70, height * 0.12),
    (width * 0.36, height * 0.53, width * 0.38, height * 0.58),
    (width * 0.695, height * 0.53, width * 0.703, height * 0.58),
)
card_corner_patches = tuple(
    tuple(round(value) for value in box) for box in card_corner_patches
)
background_fractions = [
    matching_fraction(image, box, background) for box in card_corner_patches
]
tree_center = image.getpixel((width // 2, height // 2))

# This old BAM also references its shadow texture relative to the BAM folder,
# causing a harmless fallback request in the isolated scene.  Keep it explicit
# so any other missing asset still fails the smoke test.
expected_missing_suffixes = {
    "/resources/phase_3.5/models/props/phase_3/maps/drop-shadow.png",
    "/resources/phase_3.5/models/props/phase_3/maps/drop-shadow.png.pz",
}
actual_missing_suffixes = {
    urlsplit(response["url"]).path
    for response in failed_responses
}
unexpected_console_errors = [
    error
    for error in console_errors
    if error != "Failed to load resource: the server responded with a status of 404 (Not Found)"
]

result = {
    "viewport": "1280x900",
    "canvas": f"{width}x{height}",
    "background_rgb": background,
    "tree_center_rgb": tree_center,
    "transparent_patch_matches": background_fractions,
    "expected_missing_assets": sorted(actual_missing_suffixes),
    "unexpected_console_errors": unexpected_console_errors,
    "page_errors": page_errors,
    "screenshot": str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert all(fraction > 0.99 for fraction in background_fractions)
assert sum(
    abs(actual - expected)
    for actual, expected in zip(tree_center, background)
) > 80
assert actual_missing_suffixes == expected_missing_suffixes
assert not unexpected_console_errors
assert not page_errors
