"""Proves CConnectionRepository ↔ WebSocket gateway ↔ live Astron framing."""

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    lines = []
    errors = []
    page.on("console", lambda message: lines.append(message.text))
    page.on("pageerror", lambda error: errors.append(str(error)))

    page.goto(
        "http://127.0.0.1:8180/?network-test=1",
        wait_until="domcontentloaded",
        timeout=120_000,
    )
    page.wait_for_function(
        "() => window.__networkTestComplete === true || "
        "document.body.innerText.includes('Runtime error')",
        timeout=30_000,
    )
    browser.close()

assert not errors, errors
assert any("[BrowserNetworkTest] roundtrip-ok" in line for line in lines), lines
print("Browser transport smoke test passed: CConnectionRepository ↔ WebSocket ↔ Astron TCP")
