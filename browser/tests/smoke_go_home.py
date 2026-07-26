"""Enter the local Toon's generated estate and return to a playground."""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-go-home-smoke.png"
MAP_SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-go-home-map.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_GO_HOME_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_GO_HOME_PASSWORD", "test")
BOOTSTRAP_SESSION = os.environ.get("TOONTOWN_BOOTSTRAP_SESSION", "")


def wait_for_console_count(page, lines, marker, count, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(marker in line for line in lines) >= count:
            return
        page.wait_for_timeout(250)
    authority = page.evaluate(
        """window.ToontownRuntimeAuthority?.diagnostics?.() ?? null"""
    )
    raise AssertionError(
        "Timed out waiting for %r occurrence %d. Authority: %s. "
        "Console tail:\n%s"
        % (marker, count, authority, "\n".join(lines[-160:]))
    )


def wait_for_authority_transition(page, minimum, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        diagnostics = page.evaluate(
            """window.ToontownRuntimeAuthority?.diagnostics?.() ?? null"""
        )
        if diagnostics and diagnostics.get("gameTransitions", 0) >= minimum:
            return diagnostics
        page.wait_for_timeout(200)
    return page.evaluate(
        """window.ToontownRuntimeAuthority?.diagnostics?.() ?? null"""
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    if BOOTSTRAP_SESSION:
        context.add_cookies([{
            "name": "__Host-toontown_bootstrap",
            "value": BOOTSTRAP_SESSION,
            "url": GAME_URL,
            "httpOnly": True,
            "secure": GAME_URL.startswith("https://"),
            "sameSite": "Strict",
        }])
    page = context.new_page()
    console_lines = []
    page_errors = []
    failed_responses = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: failed_responses.append({
            "status": response.status,
            "url": response.url,
        })
        if response.status >= 400
        else None,
    )

    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    welcome = page.locator("#welcome-overlay")
    if welcome.is_visible():
        page.locator("#welcome-accept").click()
        welcome.wait_for(state="hidden", timeout=5_000)
    canvas = page.locator("#canvas")

    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})

    wait_for_console_count(page, console_lines, "AvatarChooser.enter", 1)
    canvas.click(position={"x": 235, "y": 265})
    wait_for_console_count(
        page,
        console_lines,
        "BrowserAuthorityManager: Runtime authority ready",
        1,
        timeout=45,
    )
    wait_for_console_count(page, console_lines, "teleportInDone:", 1)
    initial_teleport_count = sum(
        "teleportInDone:" in line for line in console_lines
    )
    initial_walk_count = sum(
        "teleportInDone: walk" in line for line in console_lines
    )
    if any("teleportInDone: popup" in line for line in console_lines):
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    # Map page icon in the Shtiker Book's right-hand tab strip.
    canvas.click(position={"x": 1035, "y": 170})
    page.wait_for_timeout(600)
    page.screenshot(path=str(MAP_SCREENSHOT), full_page=True)
    # Native Go Home button at the bottom of the map page.
    authority_before_go_home = page.evaluate(
        """window.ToontownRuntimeAuthority?.diagnostics?.() ?? null"""
    )
    transition_count_before = (
        authority_before_go_home or {}
    ).get("gameTransitions", 0)
    canvas.click(position={"x": 653, "y": 512})
    authority_after_go_home_click = wait_for_authority_transition(
        page, transition_count_before + 1, timeout=3
    )
    if (
        not authority_after_go_home_click
        or authority_after_go_home_click.get("gameTransitions", 0)
        < transition_count_before + 1
    ):
        phase_5 = page.evaluate(
            """window.ToontownAssetLoader?.diagnostics?.()?.['5'] ?? null"""
        )
        if phase_5 and phase_5.get("state") == "loading":
            page.wait_for_function(
                """window.ToontownAssetLoader
                    ?.diagnostics?.()?.['5']?.state === 'ready'""",
                timeout=120_000,
            )
        else:
            # A final retry tolerates a single frame of UI motion while the
            # map opens. Do not double-click while a real phase load is active.
            canvas.click(position={"x": 653, "y": 512})
        authority_after_go_home_click = wait_for_authority_transition(
            page, transition_count_before + 1, timeout=15
        )
    if (
        not authority_after_go_home_click
        or authority_after_go_home_click.get("gameTransitions", 0)
        < transition_count_before + 1
    ):
        raise AssertionError(
            "Go Home did not request a protected transition. "
            "Before=%s After=%s Failed responses=%s Console tail:\n%s"
            % (
                authority_before_go_home,
                authority_after_go_home_click,
                failed_responses[-20:],
                "\n".join(console_lines[-160:]),
            )
        )

    wait_for_console_count(page, console_lines, "Entered estate zone", 1, timeout=45)
    wait_for_console_count(
        page,
        console_lines,
        "teleportInDone: walk",
        initial_walk_count + 1,
        timeout=45,
    )
    wait_for_console_count(
        page, console_lines, "Fishing pond ready in area", 1, timeout=45
    )
    page.wait_for_timeout(1_000)
    page.screenshot(path=str(SCREENSHOT), full_page=True)

    # The estate map replaces Go Home with Back to Playground.
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    canvas.click(position={"x": 1035, "y": 170})
    page.wait_for_timeout(600)
    canvas.click(position={"x": 800, "y": 512})
    popup_count_before_return = sum(
        "teleportInDone: popup" in line for line in console_lines
    )
    wait_for_console_count(
        page,
        console_lines,
        "teleportInDone:",
        initial_teleport_count + 2,
        timeout=45,
    )
    if sum(
        "teleportInDone: popup" in line for line in console_lines
    ) > popup_count_before_return:
        canvas.click(position={"x": 590, "y": 540})
        page.wait_for_timeout(500)

    crash_lines = [
        line
        for line in console_lines
        if "Traceback (most recent call last)" in line
        or "AttributeError:" in line
        or "Exception occurred in PythonTask" in line
    ]
    result = {
        "viewport": "1280x900",
        "entered_estate": any(
            "Entered estate zone" in line for line in console_lines
        ),
        "garden_root_ready": any(
            "Estate garden root ready" in line for line in console_lines
        ),
        "fishing_pond_ready": any(
            "Fishing pond ready in area" in line for line in console_lines
        ),
        "fish_bingo_managers_seen": sum(
            "Fish Bingo manager ready" in line for line in console_lines
        ),
        "returned_to_playground": sum(
            "teleportInDone:" in line for line in console_lines
        )
        >= initial_teleport_count + 2,
        "active_element": page.evaluate("document.activeElement.id"),
        "crash_lines": crash_lines,
        "page_errors": page_errors,
        "failed_responses": failed_responses,
        "authority_before_go_home": authority_before_go_home,
        "authority_after_go_home_click": authority_after_go_home_click,
        "screenshot": str(SCREENSHOT),
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["entered_estate"]
assert result["garden_root_ready"]
assert result["fishing_pond_ready"]
if os.environ.get("FISH_BINGO_EXPECT_ACTIVE") == "1":
    assert result["fish_bingo_managers_seen"] >= 2
assert result["returned_to_playground"]
assert result["active_element"] == "canvas"
assert not result["crash_lines"]
assert not result["page_errors"]
