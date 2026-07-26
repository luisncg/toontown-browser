"""Exercise the live proof-of-possession gameplay transition endpoint."""

import json
import os
import time

from playwright.sync_api import sync_playwright


ORIGIN = os.environ.get(
    "OPEN_TOONTOWN_URL",
    "https://toontown.lui.ss",
).rstrip("/")
SESSION = os.environ.get("TOONTOWN_BOOTSTRAP_SESSION", "")
if not SESSION:
    raise SystemExit("TOONTOWN_BOOTSTRAP_SESSION is required")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_cookies([{
        "name": "__Host-toontown_bootstrap",
        "value": SESSION,
        "url": ORIGIN,
        "httpOnly": True,
        "secure": ORIGIN.startswith("https://"),
        "sameSite": "Strict",
    }])
    page = context.new_page()
    failed_responses = []
    page_errors = []
    page.on(
        "response",
        lambda response: failed_responses.append({
            "status": response.status,
            "url": response.url,
        })
        if response.status >= 400
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(ORIGIN, wait_until="domcontentloaded", timeout=120_000)
    authority_deadline = time.monotonic() + 60
    while time.monotonic() < authority_deadline:
        if page.evaluate(
            "() => window.ToontownRuntimeAuthority"
            "?.diagnostics?.()?.gameSessionReady === true"
        ):
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError("production gameplay authority did not become ready")
    result = page.evaluate(
        """async () => {
          const authority = window.ToontownRuntimeAuthority;
          const requestId = '900000001';
          if (!authority.requestGameTransition(
            requestId,
            'estate.enter',
            { manager: 1, owner: 1 },
          )) {
            throw new Error('browser rejected the production smoke request');
          }
          const deadline = performance.now() + 15_000;
          while (performance.now() < deadline) {
            const value = authority.pollGameTransition(requestId);
            if (value) {
              return {
                value,
                diagnostics: authority.diagnostics(),
              };
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
          }
          throw new Error('production gameplay transition timed out');
        }"""
    )
    browser.close()

summary = {
    "transitionIssued": result["value"].get("ok") is True,
    "capabilityPrefix": (
        result["value"].get("capability", "").split(".", 1)[0]
    ),
    "gameSessions": result["diagnostics"]["gameSessions"],
    "gameTransitions": result["diagnostics"]["gameTransitions"],
    "gameSequence": result["diagnostics"]["gameSequence"],
    "authorityErrors": result["diagnostics"]["errors"],
    "failedResponses": failed_responses,
    "pageErrors": page_errors,
}
print(json.dumps(summary, indent=2))

assert summary["transitionIssued"]
assert summary["capabilityPrefix"] == "gt1"
assert summary["gameSessions"] == 1
assert summary["gameTransitions"] == 1
assert summary["gameSequence"] == 0
assert summary["authorityErrors"] == 0
assert not summary["failedResponses"]
assert not summary["pageErrors"]
