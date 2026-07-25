"""Verify OpenAL decoding, playback, and an unlocked Web Audio context."""

import json
import os

from playwright.sync_api import sync_playwright


GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")


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

    # The game deliberately keeps live transport and telemetry requests open,
    # so network-idle is not a meaningful readiness signal.
    page.goto(
        f"{GAME_URL}/?audio-test=1",
        wait_until="domcontentloaded",
        timeout=120_000,
    )
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    page.wait_for_timeout(750)
    page.locator("#canvas").click(position={"x": 400, "y": 300})
    page.wait_for_function("() => window.__audioTestPlaying === true", timeout=10_000)
    page.wait_for_function(
        """() => typeof AL !== 'undefined' &&
        Object.values(AL.contexts).some(context => context.audioCtx.state === 'running')""",
        timeout=10_000,
    )

    context_states = page.evaluate(
        "Object.values(AL.contexts).map(context => context.audioCtx.state)"
    )
    result = {
        "openal_playing": page.evaluate("window.__audioTestPlaying"),
        "web_audio_contexts": context_states,
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["openal_playing"]
assert "running" in result["web_audio_contexts"]
assert not console_errors
assert not page_errors
