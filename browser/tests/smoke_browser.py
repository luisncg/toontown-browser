"""Browser smoke test for the embedded CPython + Panda3D WebAssembly build."""

import json
import os
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-smoke.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    console_errors = []
    console_lines = []
    page_errors = []
    failed_requests = []
    bad_responses = []

    def capture_console(message):
        console_lines.append(message.text)
        if message.type == "error":
            console_errors.append(message.text)

    page.on("console", capture_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "requestfailed",
        lambda request: failed_requests.append(
            f"{request.url}: {request.failure or 'request failed'}"
        ),
    )
    page.on(
        "response",
        lambda response: bad_responses.append(f"{response.status} {response.url}")
        if response.status >= 400
        else None,
    )

    # The phase-streamed Emscripten package can keep an HTTP request open after
    # the page is usable, so the runtime-ready event is the authoritative gate.
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)
    ready = True
    try:
        page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
        page.wait_for_timeout(1_000)
    except PlaywrightTimeoutError:
        ready = False

    canvas = page.locator("#canvas")
    bounds = canvas.bounding_box()
    image_length = canvas.evaluate("node => node.toDataURL('image/png').length")
    title = page.title()
    heading = page.locator("h1").inner_text()
    shell_text = page.locator("body").inner_text()
    runtime_badge_count = page.locator(".runtime-badge").count()
    status = page.locator("#status").inner_text()
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    # Snapshot diagnostics while the page is live. Closing Chromium aborts its
    # retained streamed response for Emscripten's mounted .data package even
    # though the package has already been consumed successfully.
    captured_console_errors = list(console_errors)
    captured_console_lines = list(console_lines)
    captured_page_errors = list(page_errors)
    captured_failed_requests = list(failed_requests)
    captured_bad_responses = list(bad_responses)
    browser.close()

result = {
    "viewport": "1280x900",
    "ready": ready,
    "title": title,
    "heading": heading,
    "runtime_badge_count": runtime_badge_count,
    "status": status,
    "canvas": bounds,
    "canvas_png_data_url_length": image_length,
    "console_errors": captured_console_errors,
    "console_tail": captured_console_lines[-120:] if not ready else [],
    "page_errors": captured_page_errors,
    "failed_requests": captured_failed_requests,
    "bad_responses": captured_bad_responses,
    "screenshot": str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

unexpected_failed_requests = [
    request
    for request in captured_failed_requests
    if not (
        ready
        and request.endswith("/open-toontown.data: net::ERR_ABORTED")
        and image_length > 10_000
    )
]

assert bounds and bounds["width"] >= 900 and bounds["height"] >= 500
assert ready, "Runtime did not dispatch its ready event"
assert image_length > 10_000, "Canvas did not contain a rendered WebGL frame"
assert title == "Toontown Browser"
assert heading == "Toontown Browser"
assert runtime_badge_count == 0
for removed_copy in (
    "A real Panda3D browser port",
    "WebAssembly",
    "WebGL runtime ready",
    "Browser milestone:",
    "Open Toontown",
):
    assert removed_copy not in shell_text
assert not captured_console_errors
assert not captured_page_errors
assert not unexpected_failed_requests
