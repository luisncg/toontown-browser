"""Verify native portrait login inputs summon browser keyboards and sync."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "browser-mobile-keyboard.png"
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
BOOTSTRAP_COOKIE = os.environ.get("OPEN_TOONTOWN_BOOTSTRAP_COOKIE")
WELCOME_ACKNOWLEDGEMENT = """
localStorage.setItem('toontown-browser.welcome-acknowledged.v1', '1');
"""


def mobile_context(browser):
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
    return context


def assert_native_focus(page, selector):
    field = page.locator(selector)
    field.tap()
    assert page.evaluate(
        "selector => document.activeElement === document.querySelector(selector)",
        selector,
    )
    return field


def smoke_webkit_native_focus(playwright):
    """WebKit does not need the full game runtime to prove keyboard eligibility."""
    browser = playwright.webkit.launch(headless=True)
    context = mobile_context(browser)
    page = context.new_page()
    page.route("**/open-toontown.js*", lambda route: route.abort())
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=30_000)
    page.evaluate("""
        window.dispatchEvent(new CustomEvent('toontownmobileform', {
          detail: {mode: 'login', username: ''},
        }));
    """)
    username = assert_native_focus(page, "#mobile-account-name")
    username.type("ioswebkit")
    assert username.input_value() == "ioswebkit"
    password = assert_native_focus(page, "#mobile-account-password")
    assert password.get_attribute("type") == "password"
    assert password.get_attribute("autocomplete") == "current-password"

    username_box = username.bounding_box()
    canvas_box = page.locator("#canvas").bounding_box()
    assert username_box and canvas_box
    dialog_ok_x = canvas_box["x"] + canvas_box["width"] / 2
    dialog_ok_y = canvas_box["y"] + canvas_box["height"] * 0.622
    assert username_box["x"] <= dialog_ok_x <= (
        username_box["x"] + username_box["width"]
    )
    assert username_box["y"] <= dialog_ok_y <= (
        username_box["y"] + username_box["height"]
    )
    page.evaluate("""
        document.querySelector('#loading').style.pointerEvents = 'none';
        document.querySelector('#loading').style.visibility = 'hidden';
        window.__mobileDialogCanvasTaps = 0;
        document.querySelector('#canvas').addEventListener(
          'pointerdown',
          () => { window.__mobileDialogCanvasTaps += 1; },
        );
        window.dispatchEvent(new CustomEvent('toontownmobileform', {
          detail: {
            mode: 'login',
            username: '',
            interactive: false,
          },
        }));
    """)
    assert password.is_disabled()
    assert page.evaluate(
        "document.activeElement !== "
        "document.querySelector('#mobile-account-password')"
    )
    page.touchscreen.tap(dialog_ok_x, dialog_ok_y)
    hit_target = page.evaluate(
        """([x, y]) => {
          const target = document.elementFromPoint(x, y);
          return target ? `${target.tagName}#${target.id}.${target.className}` : '';
        }""",
        [
            dialog_ok_x,
            dialog_ok_y,
        ],
    )
    assert page.evaluate("window.__mobileDialogCanvasTaps") == 1, hit_target
    assert page.evaluate(
        "document.activeElement !== "
        "document.querySelector('#mobile-account-password')"
    )

    page.evaluate("""
        window.dispatchEvent(new CustomEvent('toontownmobileform', {
          detail: {
            mode: 'login',
            username: '',
            interactive: true,
          },
        }));
    """)
    assert not password.is_disabled()
    browser.close()


def smoke_chromium_runtime(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = mobile_context(browser)
    page = context.new_page()
    console_lines = []
    console_errors = []
    page_errors = []
    def capture_console(message):
        console_lines.append(message.text)
        if message.type == "error":
            console_errors.append(message.text)

    page.on("console", capture_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(
        f"{GAME_URL}/?mobile-form-test=1",
        wait_until="domcontentloaded",
        timeout=120_000,
    )
    page.locator("#loading.is-done").wait_for(
        state="attached", timeout=45_000
    )
    page.locator("#loading.is-done").wait_for(state="hidden", timeout=5_000)
    form = page.locator('#mobile-form-proxy[data-mode="login"]')
    try:
        form.wait_for(state="visible", timeout=10_000)
    except Exception:
        print(json.dumps({
            "mobile_form_mode": page.locator(
                "#mobile-form-proxy"
            ).get_attribute("data-mode"),
            "mobile_portrait": page.evaluate(
                "document.documentElement.classList.contains('mobile-portrait')"
            ),
            "console_tail": console_lines[-80:],
            "console_errors": console_errors,
            "page_errors": page_errors,
        }, indent=2))
        raise

    assert page.locator("#mobile-form-proxy").get_attribute(
        "data-interactive"
    ) == "true"
    submit_result = page.evaluate(
        "() => window.Module?._browser_mobile_action?.(23, 1)"
    )
    assert submit_result
    page.locator(
        '#mobile-form-proxy[data-interactive="false"]'
    ).wait_for(state="attached", timeout=5_000)
    password = page.locator("#mobile-account-password")
    username = page.locator("#mobile-account-name")
    username_box = username.bounding_box()
    canvas_box = page.locator("#canvas").bounding_box()
    assert username_box and canvas_box
    dialog_ok_x = canvas_box["x"] + canvas_box["width"] / 2
    dialog_ok_y = canvas_box["y"] + canvas_box["height"] * 0.622
    assert username_box["x"] <= dialog_ok_x <= (
        username_box["x"] + username_box["width"]
    )
    assert username_box["y"] <= dialog_ok_y <= (
        username_box["y"] + username_box["height"]
    )
    assert password.is_disabled()
    assert username.is_disabled()
    page.touchscreen.tap(dialog_ok_x, dialog_ok_y)
    page.locator(
        '#mobile-form-proxy[data-interactive="true"]'
    ).wait_for(state="attached", timeout=5_000)
    assert not password.is_disabled()

    username = assert_native_focus(page, "#mobile-account-name")
    assert username.get_attribute("autocomplete") == "username"
    assert username.get_attribute("autocapitalize") == "none"
    username.fill("")
    username.type("mobileproxy")
    page.wait_for_function(
        "() => (window.__mobileFormLog ?? []).some(line => "
        "line.includes('field=username length=11'))",
        timeout=5_000,
    )

    username.press("Enter")
    assert page.evaluate(
        "document.activeElement === "
        "document.querySelector('#mobile-account-password')"
    )
    password = page.locator("#mobile-account-password")
    password.type("keyboard")
    page.wait_for_function(
        "() => (window.__mobileFormLog ?? []).some(line => "
        "line.includes('field=password length=8'))",
        timeout=5_000,
    )

    canvas = page.locator("#canvas")
    canvas_box = canvas.bounding_box()
    form_box = page.locator("#mobile-form-proxy").bounding_box()
    assert canvas_box and form_box
    assert abs(canvas_box["y"]) <= 1
    assert 556 <= canvas_box["height"] <= 566
    assert abs(canvas_box["x"] - form_box["x"]) <= 1
    assert abs(canvas_box["y"] - form_box["y"]) <= 1
    assert abs(canvas_box["width"] - form_box["width"]) <= 1
    assert abs(canvas_box["height"] - form_box["height"]) <= 1

    canvas.tap(position={"x": 195, "y": 486})
    create_form = page.locator(
        '#mobile-form-proxy[data-mode="createAccount"]'
    )
    create_form.wait_for(state="visible", timeout=10_000)
    confirm = assert_native_focus(page, "#mobile-account-password-confirm")
    assert confirm.get_attribute("type") == "password"
    assert confirm.get_attribute("autocomplete") == "new-password"

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    result = {
        "viewport": "390x844",
        "login_native_focus": True,
        "password_native_focus": True,
        "create_account_confirm_native_focus": True,
        "python_sync_events": len(page.evaluate("window.__mobileFormLog ?? []")),
        "screenshot": str(SCREENSHOT),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    browser.close()
    assert not console_errors
    assert not page_errors
    return result


with sync_playwright() as playwright:
    smoke_webkit_native_focus(playwright)
    result = smoke_chromium_runtime(playwright)

print(json.dumps(result, indent=2))
