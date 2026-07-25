"""Measure and guard the browser Make-a-Toon avatar warm-up path."""

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_TEST_ACCOUNT", "wasmbrowsersmoke")
PASSWORD = os.environ.get("OPEN_TOONTOWN_TEST_PASSWORD", "localbrowser")


def wait_for_console(page, lines, marker, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-100:]))
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
    request_urls = []
    responses = []

    def capture_console(message):
        console_lines.append(message.text)
        if message.type == "error":
            console_errors.append(message.text)

    page.on("console", capture_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("request", lambda request: request_urls.append(request.url))
    page.on(
        "response",
        lambda response: responses.append((response.status, response.url)),
    )
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=60_000)

    canvas = page.locator("#canvas")
    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for_console(page, console_lines, "AvatarChooser.enter", timeout=45)

    # The top-right slot is empty in the browser smoke account.
    empty_slot_started = time.monotonic()
    canvas.click(position={"x": 1000, "y": 220})
    wait_for_console(
        page,
        console_lines,
        "Entering Make-a-Toon after preloading.",
        timeout=45,
    )
    empty_slot_handoff_ms = (time.monotonic() - empty_slot_started) * 1_000
    wait_for_console(
        page,
        console_lines,
        "Using Pick-a-Toon prewarmed avatar for f.",
        timeout=45,
    )
    page.wait_for_timeout(250)

    before_click_requests = len(request_urls)
    before_click_responses = len(responses)
    before_click = canvas.screenshot()
    phase_states_before = page.evaluate(
        """() => Object.fromEntries(
            Object.entries(window.__toontownPhaseDiagnostics ?? {}).map(
                ([phase, details]) => [phase, details.state],
            ),
        )"""
    )
    page.evaluate(
        """() => {
            const probe = {largestGapMs: 0, samples: 0};
            window.__makeAToonFrameProbe = probe;
            let previous = performance.now();
            probe.timer = setInterval(() => {
                const now = performance.now();
                probe.largestGapMs = Math.max(
                    probe.largestGapMs,
                    now - previous,
                );
                probe.samples += 1;
                previous = now;
            }, 10);
        }"""
    )

    click_started = time.monotonic()
    canvas_box = canvas.bounding_box()
    page.mouse.click(canvas_box["x"] + 425, canvas_box["y"] + 610)
    click_returned_ms = (time.monotonic() - click_started) * 1_000

    first_visual_change_ms = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        after_click = canvas.screenshot()
        if hashlib.sha256(before_click).digest() != hashlib.sha256(after_click).digest():
            first_visual_change_ms = (time.monotonic() - click_started) * 1_000
            break
        page.wait_for_timeout(50)

    page.wait_for_timeout(250)
    frame_probe = page.evaluate(
        """() => {
            clearInterval(window.__makeAToonFrameProbe.timer);
            const {largestGapMs, samples} = window.__makeAToonFrameProbe;
            return {largestGapMs, samples};
        }"""
    )
    phase_states_after = page.evaluate(
        """() => Object.fromEntries(
            Object.entries(window.__toontownPhaseDiagnostics ?? {}).map(
                ([phase, details]) => [phase, details.state],
            ),
        )"""
    )
    new_requests = request_urls[before_click_requests:]
    new_responses = responses[before_click_responses:]
    new_phase_requests = [
        Path(urlparse(url).path).name
        for url in new_requests
        if Path(urlparse(url).path).name.startswith("phase-")
    ]
    browser.close()

result = {
    "empty_slot_handoff_ms": round(empty_slot_handoff_ms, 1),
    "click_returned_ms": round(click_returned_ms, 1),
    "first_visual_change_ms": (
        round(first_visual_change_ms, 1)
        if first_visual_change_ms is not None else None
    ),
    "largest_main_thread_gap_ms": round(frame_probe["largestGapMs"], 1),
    "main_thread_samples": frame_probe["samples"],
    "new_network_request_count": len(new_requests),
    "new_request_paths": sorted({urlparse(url).path for url in new_requests}),
    "new_response_statuses": dict(
        sorted(Counter(status for status, _ in new_responses).items())
    ),
    "new_phase_requests": new_phase_requests,
    "phase_states_before": phase_states_before,
    "phase_states_after": phase_states_after,
    "traceback": any("Traceback" in line for line in console_lines),
    "warmup_logs": [
        line for line in console_lines
        if "prewarm" in line.lower() or "preload ready" in line.lower()
    ],
    "console_errors": console_errors,
    "page_errors": page_errors,
}
print(json.dumps(result, indent=2))

assert first_visual_change_ms is not None
assert not result["new_phase_requests"]
assert phase_states_before == phase_states_after
assert not result["traceback"]
assert not result["console_errors"]
assert not result["page_errors"]
