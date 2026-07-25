"""Exercise the portrait game surface and semantic touch-input bridge."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-mobile-portrait-controls.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
BOOTSTRAP_COOKIE = os.environ.get("OPEN_TOONTOWN_BOOTSTRAP_COOKIE")
WELCOME_ACKNOWLEDGEMENT = """
localStorage.setItem('toontown-browser.welcome-acknowledged.v1', '1');
"""


def wait_for_mobile_log(page, action, pressed, timeout=5_000):
    marker = f"action={action} pressed={pressed}"
    page.wait_for_function(
        "marker => (window.__mobileInputLog ?? []).some(line => "
        "line.includes(marker))",
        arg=marker,
        timeout=timeout,
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    )
    context.add_init_script(WELCOME_ACKNOWLEDGEMENT)
    if BOOTSTRAP_COOKIE:
        context.add_cookies([{
            "name": "__Host-toontown_bootstrap",
            "value": BOOTSTRAP_COOKIE,
            "url": GAME_URL,
            "httpOnly": True,
            "secure": GAME_URL.startswith("https://"),
            "sameSite": "Strict",
        }])
    page = context.new_page()
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
        f"{GAME_URL}/?mobile-controls-test=1",
        wait_until="domcontentloaded",
        timeout=120_000,
    )
    page.locator("#loading:not(.is-done)").wait_for(
        state="visible", timeout=5_000
    )
    page.locator("#mobile-controls.is-visible").wait_for(
        state="visible", timeout=5_000
    )
    assert page.locator("#mobile-controls").get_attribute("aria-hidden") == "false"
    assert page.locator("html.mobile-gameplay").count() == 1

    page.locator("#loading.is-done").wait_for(state="attached", timeout=45_000)
    page.locator("#loading.is-done").wait_for(state="hidden", timeout=5_000)
    page.locator("#mobile-controls.is-visible").wait_for(
        state="visible", timeout=5_000
    )
    page.wait_for_function(
        "document.querySelector('#canvas').width === 768 && "
        "document.querySelector('#canvas').height === 953",
        timeout=10_000,
    )

    stage_box = page.locator(".stage").bounding_box()
    canvas_box = page.locator("#canvas").bounding_box()
    controls_box = page.locator("#mobile-controls").bounding_box()
    assert stage_box and canvas_box and controls_box
    assert abs(stage_box["width"] - 390) <= 1
    assert abs(stage_box["height"] - 844) <= 1
    assert abs(canvas_box["y"]) <= 1
    assert 480 <= canvas_box["height"] <= 488
    assert abs(canvas_box["width"] / canvas_box["height"] - 768 / 953) < 0.01
    assert abs(controls_box["y"] - canvas_box["height"]) <= 1
    assert controls_box["height"] >= 350
    assert page.locator(".mobile-stick-ring").count() == 0
    viewport_policy = page.locator('meta[name="viewport"]').get_attribute(
        "content"
    )
    assert "maximum-scale=1" in viewport_policy
    assert "user-scalable=no" in viewport_policy
    assert page.evaluate(
        "getComputedStyle(document.documentElement).touchAction"
    ) == "none"
    assert page.evaluate(
        "getComputedStyle(document.body).touchAction"
    ) == "none"

    touchend_guard = page.locator(
        '[data-mobile-action="performAction"]'
    ).evaluate(
        """element => {
          const first = new Event('touchend', {
            bubbles: true,
            cancelable: true,
          });
          const second = new Event('touchend', {
            bubbles: true,
            cancelable: true,
          });
          element.dispatchEvent(first);
          element.dispatchEvent(second);
          return {
            firstPrevented: first.defaultPrevented,
            secondPrevented: second.defaultPrevented,
          };
        }"""
    )
    assert touchend_guard == {
        "firstPrevented": False,
        "secondPrevented": True,
    }

    stick_box = page.locator("#mobile-stick").bounding_box()
    run_box = page.locator(
        '[data-mobile-action="sprint"]'
    ).bounding_box()
    jump_box = page.locator(
        '[data-mobile-action="jump"]'
    ).bounding_box()
    action_box = page.locator(
        '[data-mobile-action="performAction"]'
    ).bounding_box()
    assert stick_box and run_box and jump_box and action_box
    assert 174 <= run_box["x"] <= 178
    assert 224 <= jump_box["x"] <= 228
    assert jump_box["y"] <= 616
    assert 320 <= action_box["x"] <= 323
    assert (
        run_box["y"] + run_box["height"] <=
        controls_box["y"] + controls_box["height"] - 4
    )

    cdp = context.new_cdp_session(page)
    stick_x = stick_box["x"] + stick_box["width"] * 0.78
    stick_y = stick_box["y"] + stick_box["height"] * 0.22
    cdp.send(
        "Input.dispatchTouchEvent",
        {
            "type": "touchStart",
            "touchPoints": [{"x": stick_x, "y": stick_y, "id": 1}],
        },
    )
    wait_for_mobile_log(page, "forward", "True")
    wait_for_mobile_log(page, "turnRight", "True")
    cdp.send(
        "Input.dispatchTouchEvent",
        {
            "type": "touchEnd",
            "touchPoints": [],
        },
    )
    wait_for_mobile_log(page, "forward", "False")
    wait_for_mobile_log(page, "turnRight", "False")

    for action in (
        "sprint",
        "jump",
        "performAction",
        "viewGags",
        "switchPov",
    ):
        page.locator(f'[data-mobile-action="{action}"]').tap()
        wait_for_mobile_log(page, action, "True")
        wait_for_mobile_log(page, action, "False")

    def dispatch_pointer(selector, event_name, pointer_id):
        page.locator(selector).evaluate(
            """(element, detail) => {
              element.setPointerCapture = () => {};
              element.dispatchEvent(new PointerEvent(detail.eventName, {
                bubbles: true,
                cancelable: true,
                button: 0,
                buttons: detail.eventName === 'pointerdown' ? 1 : 0,
                pointerId: detail.pointerId,
                pointerType: 'touch',
              }));
            }""",
            {"eventName": event_name, "pointerId": pointer_id},
        )

    run_selector = '[data-mobile-action="sprint"]'
    jump_selector = '[data-mobile-action="jump"]'
    initial_log_length = page.evaluate("window.__mobileInputLog.length")

    # A second finger on the same control must not own or release the first
    # finger's held action.
    dispatch_pointer(run_selector, "pointerdown", 41)
    dispatch_pointer(run_selector, "pointerdown", 42)
    dispatch_pointer(run_selector, "pointerup", 42)
    assert page.locator(run_selector).evaluate(
        "element => element.classList.contains('is-pressed')"
    )
    dispatch_pointer(run_selector, "pointerup", 41)
    assert not page.locator(run_selector).evaluate(
        "element => element.classList.contains('is-pressed')"
    )

    # Independent fingers may hold Run and Jump together; releasing one must
    # not cancel the other.
    dispatch_pointer(run_selector, "pointerdown", 51)
    dispatch_pointer(jump_selector, "pointerdown", 52)
    dispatch_pointer(run_selector, "pointerup", 51)
    assert page.locator(jump_selector).evaluate(
        "element => element.classList.contains('is-pressed')"
    )
    dispatch_pointer(jump_selector, "pointerup", 52)

    held_log = page.evaluate(
        "start => window.__mobileInputLog.slice(start)",
        initial_log_length,
    )
    assert sum("action=sprint pressed=True" in line for line in held_log) == 2
    assert sum("action=sprint pressed=False" in line for line in held_log) == 2
    assert sum("action=jump pressed=True" in line for line in held_log) == 1
    assert sum("action=jump pressed=False" in line for line in held_log) == 1

    # Losing the page while a finger is down must never strand a held action.
    dispatch_pointer(run_selector, "pointerdown", 61)
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    assert not page.locator(run_selector).evaluate(
        "element => element.classList.contains('is-pressed')"
    )

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    mobile_log = page.evaluate("window.__mobileInputLog")

    page.set_viewport_size({"width": 390, "height": 700})
    page.wait_for_timeout(100)
    short_run_box = page.locator(
        '[data-mobile-action="sprint"]'
    ).bounding_box()
    short_controls_box = page.locator("#mobile-controls").bounding_box()
    assert short_run_box and short_controls_box
    assert short_run_box["x"] >= 0
    assert (
        short_run_box["y"] + short_run_box["height"] <=
        short_controls_box["y"] + short_controls_box["height"] - 4
    )

    result = {
        "viewport": "390x844",
        "stage": {
            "width": round(stage_box["width"]),
            "height": round(stage_box["height"]),
        },
        "canvas_css": {
            "width": round(canvas_box["width"]),
            "height": round(canvas_box["height"]),
        },
        "canvas_buffer": page.evaluate(
            "(() => { const canvas = document.querySelector('#canvas'); "
            "return {width: canvas.width, height: canvas.height}; })()"
        ),
        "control_deck_height": round(controls_box["height"]),
        "button_positions": {
            "run": {
                "x": round(run_box["x"]),
                "y": round(run_box["y"]),
            },
            "jump": {
                "x": round(jump_box["x"]),
                "y": round(jump_box["y"]),
            },
            "action": {
                "x": round(action_box["x"]),
                "y": round(action_box["y"]),
            },
        },
        "input_events": len(mobile_log),
        "short_viewport_run": {
            "viewport": "390x700",
            "x": round(short_run_box["x"]),
            "y": round(short_run_box["y"]),
            "bottom": round(short_run_box["y"] + short_run_box["height"]),
        },
        "screenshot": str(SCREENSHOT),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
assert result["canvas_buffer"] == {"width": 768, "height": 953}
assert result["input_events"] >= 22
assert not console_errors
assert not page_errors
