"""Verify the official-build fatal warning for copied and embedded clients."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_SOURCE = (
    PROJECT_DIR / "browser" / "web" / "runtime-authority.js"
).read_text(encoding="utf-8").replace("</script", r"<\/script")
STYLE_SOURCE = (
    PROJECT_DIR / "browser" / "web" / "styles.css"
).read_text(encoding="utf-8")


def guarded_document():
    return f"""<!doctype html>
<html>
  <head><style>{STYLE_SOURCE}</style></head>
  <body>
    <main class="shell">Copied game surface</main>
    <section id="official-build-overlay" aria-hidden="true">
      <div class="official-build-card" role="alertdialog" aria-modal="true">
        <p class="official-build-eyebrow">UNOFFICIAL COPY</p>
        <h1>This version of Toontown Browser is not running from its official website.</h1>
        <p>Please play at:</p>
        <a href="https://toontown.lui.ss/">toontown.lui.ss</a>
      </div>
    </section>
    <canvas id="canvas" tabindex="0"></canvas>
    <script>{RUNTIME_SOURCE}</script>
  </body>
</html>"""


def assert_fatal(frame):
    overlay = frame.locator("#official-build-overlay")
    overlay.wait_for(state="visible", timeout=5_000)
    assert overlay.get_attribute("aria-hidden") == "false"
    assert frame.locator("html").evaluate(
        "element => element.classList.contains('official-build-fatal')"
    )
    assert frame.locator(".shell").evaluate("element => element.inert")
    assert frame.locator("#canvas").get_attribute("tabindex") == "-1"
    assert frame.locator(".official-build-eyebrow").inner_text() == (
        "UNOFFICIAL COPY"
    )
    assert frame.locator(".official-build-card a").get_attribute("href") == (
        "https://toontown.lui.ss/"
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    telemetry = []

    def route_request(route):
        request = route.request
        if request.url == "https://toontown.lui.ss/api/security/telemetry":
            telemetry.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=202, body='{"ok":true}')
        elif request.url == "https://copied.example/client":
            route.fulfill(
                status=200,
                content_type="text/html",
                body=guarded_document(),
            )
        elif request.url == "https://toontown.lui.ss/embedded-client":
            route.fulfill(
                status=200,
                content_type="text/html",
                body=guarded_document(),
            )
        elif request.url == "https://wrapper.example/":
            route.fulfill(
                status=200,
                content_type="text/html",
                body=(
                    '<iframe id="game" '
                    'src="https://toontown.lui.ss/embedded-client"></iframe>'
                ),
            )
        else:
            route.abort()

    context.route("**/*", route_request)

    copied = context.new_page()
    copied.goto("https://copied.example/client", wait_until="domcontentloaded")
    assert_fatal(copied)

    wrapper = context.new_page()
    wrapper.goto("https://wrapper.example/", wait_until="domcontentloaded")
    frame_element = wrapper.locator("#game")
    frame_element.wait_for(state="attached", timeout=5_000)
    embedded = frame_element.element_handle().content_frame()
    assert embedded is not None
    assert_fatal(embedded)

    copied.wait_for_timeout(100)
    assert {entry["reason"] for entry in telemetry} == {
        "wrong-origin",
        "embedded-client",
    }
    assert all(set(entry).issubset({"reason", "build"}) for entry in telemetry)
    browser.close()

print("Official-build guard smoke test passed")
