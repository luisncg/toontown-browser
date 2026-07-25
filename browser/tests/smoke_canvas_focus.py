"""Regress canvas focus recovery and real Panda3D keyboard/mouse delivery."""

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

    page.goto(f"{GAME_URL}/?input-test=1", wait_until="networkidle", timeout=120_000)
    # Wait for the loading overlay's visibility transition to finish.  Merely
    # waiting for the class leaves the transparent overlay hit-testable for
    # another 500 ms, which makes Playwright scroll before it can click the
    # canvas and does not represent a real post-load user click.
    loading_done = page.locator("#loading.is-done")
    loading_done.wait_for(state="attached", timeout=45_000)
    loading_done.wait_for(state="hidden", timeout=5_000)
    canvas = page.locator("#canvas")

    for expected_count in (1, 2):
        page.evaluate("document.querySelector('#canvas').blur()")
        assert page.evaluate("document.activeElement.id") != "canvas"
        canvas.click(position={"x": 400, "y": 300})
        assert page.evaluate("document.activeElement.id") == "canvas"
        page.wait_for_function(
            "count => window.__inputTestMouseCount === count",
            arg=expected_count,
            timeout=5_000,
        )
        page.keyboard.press("ArrowUp")
        page.wait_for_function(
            "count => window.__inputTestCount === count",
            arg=expected_count,
            timeout=5_000,
        )

    # macOS screenshot/recording shortcuts press Command+Shift, then move
    # keyboard focus to a system overlay. Their key-up events never reach the
    # canvas. Panda must flush the held modifiers on blur so an ordinary click
    # and movement key work as soon as the player returns.
    page.keyboard.down("Meta")
    page.keyboard.down("Shift")
    page.evaluate("document.querySelector('#canvas').blur()")
    assert page.evaluate("document.activeElement.id") != "canvas"
    page.keyboard.up("Shift")
    page.keyboard.up("Meta")

    canvas.click(position={"x": 400, "y": 300})
    assert page.evaluate("document.activeElement.id") == "canvas"
    page.wait_for_function(
        "window.__inputTestMouseCount === 3",
        timeout=5_000,
    )
    page.keyboard.press("ArrowUp")
    page.wait_for_function(
        "window.__inputTestCount === 3",
        timeout=5_000,
    )

    result = {
        "refocus_cycles": 3,
        "shortcut_interruption_recovered": True,
        "panda_arrow_events": page.evaluate("window.__inputTestCount"),
        "panda_mouse_events": page.evaluate("window.__inputTestMouseCount"),
        "active_element": page.evaluate("document.activeElement.id"),
        "scroll_y": page.evaluate("window.scrollY"),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["panda_arrow_events"] == 3
assert result["panda_mouse_events"] == 3
assert result["active_element"] == "canvas"
assert result["scroll_y"] == 0
assert not console_errors
assert not page_errors
