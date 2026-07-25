"""Prove Astron startup does not depend on browser localStorage."""

import json
import os
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
SESSION = os.environ.get("TOONTOWN_BOOTSTRAP_SESSION", "")
GATEWAY_HEALTH_URL = os.environ.get(
    "OPEN_TOONTOWN_GATEWAY_HEALTH_URL",
    "http://127.0.0.1:7200/health",
)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = browser.new_context(viewport={"width": 440, "height": 796})
    game_origin = urlparse(GAME_URL)
    if SESSION:
        context.add_cookies(
            [{
                "name": "__Host-toontown_bootstrap",
                "value": SESSION,
                "domain": game_origin.hostname,
                "path": "/",
                "secure": game_origin.scheme == "https",
                "httpOnly": True,
                "sameSite": "Strict",
            }]
        )
    context.add_init_script(
        """
        for (const method of ["getItem", "setItem", "removeItem", "clear"]) {
          Object.defineProperty(Storage.prototype, method, {
            configurable: true,
            value() {
              throw new DOMException("Storage blocked by smoke test", "SecurityError");
            },
          });
        }
        """
    )
    page = context.new_page()
    console_lines = []
    page_errors = []
    page.on("console", lambda message: console_lines.append(message.text))
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    # The game intentionally overlaps long-lived phase streams with runtime
    # startup, so a true network-idle point is not part of the boot contract.
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=60_000)
    page.wait_for_timeout(1_000)

    gateway_active_connections = None
    if GATEWAY_HEALTH_URL:
        with urlopen(GATEWAY_HEALTH_URL, timeout=5) as response:
            gateway_active_connections = json.load(response)[
                "activeConnections"
            ]

    connect_lines = [
        line for line in console_lines
        if "Connecting through browser gateway" in line
    ]
    localhost_failure = [
        line for line in console_lines
        if "Could not connect to 127.0.0.1:7198" in line
        or "WebSocket gateway unavailable" in line
    ]
    runtime_gateway = page.evaluate("window.__toontownGameServer")
    parsed_runtime_gateway = urlparse(runtime_gateway)
    runtime_query = {
        name for name, _value in (
            item.split("=", 1) for item in parsed_runtime_gateway.query.split("&")
            if "=" in item
        )
    }
    result = {
        "viewport": "440x796px",
        "runtime_gateway_origin": (
            f"{parsed_runtime_gateway.scheme}://"
            f"{parsed_runtime_gateway.netloc}{parsed_runtime_gateway.path}"
        ),
        "runtime_gateway_parameters": sorted(runtime_query),
        "connect_lines": connect_lines,
        "gateway_active_connections": gateway_active_connections,
        "localhost_failure": localhost_failure,
        "page_errors": page_errors,
    }
    browser.close()

print(json.dumps(result, indent=2))
expected_gateway = (
    "ws://127.0.0.1:7200"
    if game_origin.hostname in {"127.0.0.1", "localhost", "::1"}
    else f"{'wss' if game_origin.scheme == 'https' else 'ws'}://"
         f"{game_origin.netloc}"
)
assert result["runtime_gateway_origin"] == f"{expected_gateway}/astron"
assert result["runtime_gateway_parameters"] in (["resume"], ["lease", "resume"])
if game_origin.hostname not in {"127.0.0.1", "localhost", "::1"}:
    assert result["runtime_gateway_parameters"] == ["lease", "resume"]
assert result["connect_lines"]
if result["gateway_active_connections"] is not None:
    assert result["gateway_active_connections"] >= 1
assert not result["localhost_failure"]
assert not result["page_errors"]
