"""Verify corrupt Phase 4 bytes are rejected before Emscripten can mount them."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
MANIFEST = json.loads(
    (PROJECT_DIR / "dist-web" / "phase-manifest.json").read_text()
)
PHASE_4 = next(
    phase for phase in MANIFEST["phases"] if str(phase["phase"]) == "4"
)
TARGET = PHASE_4["parts"][0]
TARGET_PATH = PROJECT_DIR / "dist-web" / TARGET["data"]


original = TARGET_PATH.read_bytes()
assert len(original) == TARGET["bytes"]
corrupt = bytearray(original)
corrupt[len(corrupt) // 2] ^= 0x01


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    intercepted = []

    def corrupt_target(route):
        request_name = Path(urlparse(route.request.url).path).name
        if request_name != TARGET["data"]:
            route.continue_()
            return
        intercepted.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/octet-stream",
            body=bytes(corrupt),
        )

    page.route("**/*", corrupt_target)
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_function(
        """() => (
            window.ToontownAssetLoader?.diagnostics?.()['4']?.state ===
            'error'
        )""",
        timeout=120_000,
    )
    page.wait_for_function(
        """() => window.ToontownPerformanceTelemetry
            ?.snapshot?.().history.some((event) => (
                event.type === 'phase_handoff' &&
                event.stage === 'error' &&
                event.reason === 'checksum'
            ))""",
        timeout=30_000,
    )

    diagnostics = page.evaluate(
        "window.ToontownAssetLoader.diagnostics()['4']"
    )
    error_event = page.evaluate(
        """window.ToontownPerformanceTelemetry.snapshot().history.find(
            (event) => (
                event.type === 'phase_handoff' &&
                event.stage === 'error'
            ),
        )"""
    )
    target_loader_count = page.locator(
        "script[data-toontown-phase='4']"
        f"[data-toontown-phase-part='{TARGET['part']}']"
    ).count()
    browser.close()


result = {
    "viewport": "1280x900px",
    "target": TARGET["data"],
    "intercepted_requests": len(intercepted),
    "phase_state": diagnostics["state"],
    "parts_ready": diagnostics["partsReady"],
    "parts_total": diagnostics["partsTotal"],
    "target_loader_count": target_loader_count,
    "registered_packages": diagnostics["directHandoff"][
        "registeredPackages"
    ],
    "error_reason": error_event["reason"],
}
print(json.dumps(result, indent=2))

assert result["intercepted_requests"] == 1
assert result["phase_state"] == "error"
assert result["error_reason"] == "checksum"
assert result["target_loader_count"] == 0
assert result["parts_ready"] < len(PHASE_4["parts"])
assert result["registered_packages"] == 0
