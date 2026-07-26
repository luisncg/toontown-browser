#!/usr/bin/env python3
"""Real-browser smoke test for the asynchronous short-audio pilot bank."""

import os

from playwright.sync_api import sync_playwright


URL = os.environ.get("SHORT_AUDIO_URL", "http://127.0.0.1:8180/")
BROWSER_NAME = os.environ.get("SHORT_AUDIO_BROWSER", "chromium")
BOOTSTRAP_SESSION = os.environ.get("TOONTOWN_BOOTSTRAP_SESSION", "")


def main():
    console_errors = []
    console_messages = []
    bank_responses = []
    error_responses = []
    failed_requests = []
    with sync_playwright() as playwright:
        browser_type = getattr(playwright, BROWSER_NAME)
        browser = browser_type.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        if BOOTSTRAP_SESSION:
            context.add_cookies([{
                "name": "__Host-toontown_bootstrap",
                "value": BOOTSTRAP_SESSION,
                "url": URL,
                "httpOnly": True,
                "secure": URL.startswith("https://"),
                "sameSite": "Strict",
            }])
        page = context.new_page()
        page.on(
            "console",
            lambda message: (
                console_messages.append((message.type, message.text)),
                console_errors.append(message.text)
                if message.type == "error"
                else None,
            ),
        )
        def capture_response(response):
            if (
                "audio-bank-" in response.url
                and ".data" in response.url
            ):
                bank_responses.append((response.url, response.status))
            if response.status >= 400:
                error_responses.append((response.url, response.status))

        page.on("response", capture_response)
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                (request.url, request.failure)
            ),
        )
        page.goto(
            URL,
            wait_until="domcontentloaded" if BOOTSTRAP_SESSION else "networkidle",
            timeout=60_000,
        )
        try:
            page.wait_for_function(
                """
                () => window.ToontownShortAudioBanks?.diagnostics()
                  .decodedSounds === 47
                """,
                timeout=60_000,
            )
        except Exception:
            page.screenshot(
                path="/tmp/toontown-short-audio-smoke-failure.png",
                full_page=True,
            )
            print("Audio diagnostics:", page.evaluate(
                "() => window.ToontownShortAudioBanks?.diagnostics()"
            ))
            print("Boot diagnostics:", page.evaluate(
                "() => window.__toontownBootDiagnostics"
            ))
            print("Bank responses:", bank_responses)
            print("Failed requests:", failed_requests[-10:])
            print("Console tail:", console_messages[-30:])
            raise
        page.wait_for_function(
            """
            () => {
              try {
                const value = JSON.parse(
                  new TextDecoder().decode(
                    window.Module.FS.readFile(
                      "/browser-short-audio-banks.json"
                    )
                  )
                );
                return value.version === 1 &&
                  Object.keys(value.sounds).length === 47 &&
                  value.sounds["sa_shred.ogg"] &&
                  value.sounds["sa_pick_pocket.ogg"] &&
                  value.sounds["enc_win.ogg"];
              } catch {
                return false;
              }
            }
            """,
            timeout=60_000,
        )
        canvas_box = page.locator("#canvas").bounding_box()
        assert canvas_box
        page.mouse.click(
            canvas_box["x"] + canvas_box["width"] / 2,
            canvas_box["y"] + canvas_box["height"] / 2,
        )
        played = page.evaluate(
            """
            () => [
              window.ToontownShortAudioBanks.handleCommand(
                "[BrowserWebAudioCommand] play 998 " +
                "enc_win.ogg 0.000000 0 " +
                "0.050000 1.000000 0.000000 -"
              ),
              window.ToontownShortAudioBanks.handleCommand(
                "[BrowserWebAudioCommand] play 999 " +
                "sa_pick_pocket.ogg 0.000000 0 " +
                "0.050000 1.000000 0.000000 -"
              ),
            ]
            """
        )
        assert all(played), played
        page.wait_for_function(
            """
            () => {
              const value =
                window.ToontownShortAudioBanks.diagnostics();
              return value.plays >= 2 &&
                value.contextState === "running";
            }
            """,
            timeout=10_000,
        )
        lifecycle_before = page.evaluate(
            "() => window.ToontownAudioLifecycle.diagnostics()"
        )
        assert len(lifecycle_before["contexts"]) >= 2, lifecycle_before
        assert {
            context["label"] for context in lifecycle_before["contexts"]
        }.issuperset({"panda-openal", "short-audio-bank"}), lifecycle_before
        forced_restart = page.evaluate(
            """
            () => window.ToontownAudioLifecycle.resumeAll(
              "browser_smoke",
              false,
              true
            )
            """
        )
        assert forced_restart["attempted"] >= 1, forced_restart
        assert forced_restart["recovered"] == forced_restart["attempted"], (
            forced_restart
        )
        lifecycle_after_forced_restart = page.evaluate(
            "() => window.ToontownAudioLifecycle.diagnostics()"
        )
        assert (
            lifecycle_after_forced_restart["forcedRestarts"] >
            lifecycle_before["forcedRestarts"]
        ), lifecycle_after_forced_restart
        page.evaluate(
            """
            async () => {
              await window.ToontownShortAudioBanks.context.suspend();
              window.ToontownAudioLifecycle.handleForeground(
                "browser_smoke"
              );
            }
            """
        )
        page.wait_for_function(
            """
            () => window.ToontownShortAudioBanks.diagnostics()
              .contextState === "running"
            """,
            timeout=10_000,
        )
        page.evaluate(
            """
            () => {
              window.ToontownShortAudioBanks.handleCommand(
                "[BrowserWebAudioCommand] stop 998"
              );
              window.ToontownShortAudioBanks.handleCommand(
                "[BrowserWebAudioCommand] stop 999"
              );
            }
            """
        )
        page.wait_for_function(
            """
            () => window.ToontownShortAudioBanks.diagnostics()
              .contextState === "suspended"
            """,
            timeout=10_000,
        )
        diagnostics = page.evaluate(
            "() => window.ToontownShortAudioBanks.diagnostics()"
        )
        lifecycle = page.evaluate(
            "() => window.ToontownAudioLifecycle.diagnostics()"
        )
        assert lifecycle["successfulRecoveries"] >= 1, lifecycle
        assert any(
            event["stage"] == "resume"
            and event["trigger"] == "browser_smoke"
            for event in lifecycle["history"]
        ), lifecycle
        assert diagnostics["bankFailures"] == 0, diagnostics
        assert diagnostics["decodedSounds"] == 47, diagnostics
        assert diagnostics["banks"]["tutorial-battle"]["state"] == "ready"
        assert diagnostics["banks"]["cog-attacks"]["state"] == "ready"
        if not BOOTSTRAP_SESSION:
            assert len(bank_responses) == 2, bank_responses
        assert all(
            status == 200 for _url, status in bank_responses
        ), bank_responses
        relevant_errors = [
            error
            for error in console_errors
            if (
                "favicon" not in error.lower()
                and "ws://127.0.0.1:7200/astron" not in error
            )
        ]
        assert not relevant_errors, {
            "console": relevant_errors,
            "responses": error_responses,
        }
        browser.close()
    print(
        "Short-audio browser smoke passed: "
        f"browser={BROWSER_NAME} "
        "tutorial="
        f"{diagnostics['banks']['tutorial-battle']['fetchMs']}ms/"
        f"{diagnostics['banks']['tutorial-battle']['decodeMs']}ms "
        "cog-attacks="
        f"{diagnostics['banks']['cog-attacks']['fetchMs']}ms/"
        f"{diagnostics['banks']['cog-attacks']['decodeMs']}ms"
    )


if __name__ == "__main__":
    main()
