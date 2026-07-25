"""Verify the first-cold-boot welcome gate on desktop and portrait mobile."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
BOOTSTRAP_COOKIE = os.environ.get("OPEN_TOONTOWN_BOOTSTRAP_COOKIE")
STORAGE_KEY = "toontown-browser.welcome-acknowledged.v1"
DESKTOP_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-first-visit-desktop.png"
)
MOBILE_SCREENSHOT = (
    PROJECT_DIR / ".build-wasm" / "browser-first-visit-mobile.png"
)

EXPECTED_DESCRIPTION = (
    "Before you enter, you should know that Toontown Browser is a fan-made "
    "revival of Disney's Toontown Online, running entirely in a web browser. "
    "Toontown Browser was created using publicly available downloads and "
    "information made freely available to the general public."
)
EXPECTED_DISCLAIMER = (
    "By using Toontown Browser, you certify that you understand that Toontown "
    'Browser is not affiliated with The Walt Disney Company and/or Disney '
    'Interactive (collectively referred to as "Disney") and you hereby release '
    "Disney, as well as any employees or agents of Disney, from any and all "
    "liability, corporate, or personal loss caused to you or others by the use "
    "of Toontown Browser."
)


def normalized_text(locator):
    return " ".join((locator.text_content() or "").split())


def add_bootstrap_cookie(context):
    if not BOOTSTRAP_COOKIE:
        return
    context.add_cookies([{
        "name": "__Host-toontown_bootstrap",
        "value": BOOTSTRAP_COOKIE,
        "url": GAME_URL,
        "httpOnly": True,
        "secure": GAME_URL.startswith("https://"),
        "sameSite": "Strict",
    }])


def assert_copy_and_gate(page):
    overlay = page.locator("#welcome-overlay")
    overlay.wait_for(state="visible", timeout=10_000)
    assert page.locator(".welcome-card-accent").count() == 0
    assert normalized_text(page.locator("#welcome-title")) == (
        "Welcome to Toontown Browser."
    )
    assert normalized_text(page.locator("#welcome-description")) == (
        EXPECTED_DESCRIPTION
    )
    assert normalized_text(page.locator("#welcome-disclaimer")) == (
        EXPECTED_DISCLAIMER
    )
    assert normalized_text(page.locator("#welcome-accept")) == "Sounds Good!"
    assert page.locator("#welcome-leave").get_attribute("href") == (
        "https://games.disney.com/"
    )
    assert page.locator(".shell").evaluate("element => element.inert")
    assert overlay.get_attribute("aria-hidden") == "false"
    page.wait_for_function(
        "() => performance.getEntriesByName("
        "'/api/bootstrap/config').length > 0 || "
        "performance.getEntriesByType('resource').some("
        "entry => entry.name.endsWith('/api/bootstrap/config'))",
        timeout=10_000,
    )


def assert_card_fits_viewport(page):
    box = page.locator(".welcome-card").bounding_box()
    viewport = page.viewport_size
    assert box and viewport
    assert box["x"] >= 0
    assert box["y"] >= 0
    assert box["x"] + box["width"] <= viewport["width"] + 1
    assert box["y"] + min(box["height"], viewport["height"]) <= (
        viewport["height"] + 1
    )


def run_desktop(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    add_bootstrap_cookie(context)
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
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60_000)
    assert_copy_and_gate(page)
    assert_card_fits_viewport(page)
    card_box = page.locator(".welcome-card").bounding_box()
    title_box = page.locator("#welcome-title").bounding_box()
    title_line_height = page.locator("#welcome-title").evaluate(
        "element => parseFloat(getComputedStyle(element).lineHeight)"
    )
    assert card_box and title_box
    assert card_box["width"] >= 955
    assert title_box["height"] <= title_line_height * 1.15
    page.screenshot(path=str(DESKTOP_SCREENSHOT), full_page=True)

    page.locator("#welcome-accept").click()
    page.locator("#welcome-overlay").wait_for(state="hidden", timeout=5_000)
    assert not page.locator(".shell").evaluate("element => element.inert")
    assert page.evaluate("key => localStorage.getItem(key)", STORAGE_KEY) == "1"

    page.reload(wait_until="domcontentloaded", timeout=60_000)
    page.locator("#welcome-overlay").wait_for(state="hidden", timeout=5_000)
    assert not page.locator("html").evaluate(
        "element => element.classList.contains('welcome-required')"
    )
    assert not page.locator(".shell").evaluate("element => element.inert")
    result = {
        "viewport": "1280x900",
        "first_visit_visible": True,
        "refresh_hidden": True,
        "boot_started_under_dialog": True,
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    browser.close()
    assert not console_errors, console_errors
    assert not page_errors, page_errors
    return result


def run_mobile(playwright):
    browser = playwright.webkit.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    )
    add_bootstrap_cookie(context)
    page = context.new_page()
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60_000)
    assert_copy_and_gate(page)
    assert_card_fits_viewport(page)
    card_box = page.locator(".welcome-card").bounding_box()
    assert card_box
    assert card_box["width"] <= 352
    assert card_box["height"] <= 662
    button_box = page.locator("#welcome-accept").bounding_box()
    assert button_box and button_box["height"] >= 44
    page.screenshot(path=str(MOBILE_SCREENSHOT), full_page=True)

    page.locator("#welcome-accept").tap()
    page.locator("#welcome-overlay").wait_for(state="hidden", timeout=5_000)
    page.reload(wait_until="domcontentloaded", timeout=60_000)
    page.locator("#welcome-overlay").wait_for(state="hidden", timeout=5_000)
    result = {
        "viewport": "390x844",
        "first_visit_visible": True,
        "refresh_hidden": True,
        "button_touch_height": round(button_box["height"], 1),
        "leave_url": "https://games.disney.com/",
    }
    browser.close()
    return result


with sync_playwright() as playwright:
    print(json.dumps({
        "desktop": run_desktop(playwright),
        "mobile": run_mobile(playwright),
        "screenshots": {
            "desktop": str(DESKTOP_SCREENSHOT),
            "mobile": str(MOBILE_SCREENSHOT),
        },
    }, indent=2))
