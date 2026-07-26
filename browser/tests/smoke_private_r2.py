import os
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ORIGIN = "https://toontown.lui.ss"
SESSION = os.environ.get("TOONTOWN_BOOTSTRAP_SESSION", "")
READY_TIMEOUT_MS = int(os.environ.get("TOONTOWN_READY_TIMEOUT_MS", "180000"))
EDGE_IP = os.environ.get("TOONTOWN_EDGE_IP", "")
if not SESSION:
    raise SystemExit("TOONTOWN_BOOTSTRAP_SESSION is required")


with sync_playwright() as playwright:
    launch_arguments = (
        [f"--host-resolver-rules=MAP toontown.lui.ss {EDGE_IP}"]
        if EDGE_IP
        else []
    )
    browser = playwright.chromium.launch(headless=True, args=launch_arguments)
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    context.add_cookies(
        [
            {
                "name": "__Host-toontown_bootstrap",
                "value": SESSION,
                "domain": "toontown.lui.ss",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ]
    )
    assert context.request.get(f"{ORIGIN}/r2-assets.json").status == 404
    assert context.request.get(f"{ORIGIN}/open-toontown.data.gz").status == 404
    assert context.request.get(f"{ORIGIN}/open-toontown.wasm.gz").status == 404
    phase_manifest_response = context.request.get(
        f"{ORIGIN}/phase-manifest.json"
    )
    audio_manifest_response = context.request.get(
        f"{ORIGIN}/audio-bank-manifest.json"
    )
    assert phase_manifest_response.status == 200
    assert audio_manifest_response.status == 200
    phase_manifest = phase_manifest_response.json()
    audio_manifest = audio_manifest_response.json()
    phase_4 = next(
        phase for phase in phase_manifest["phases"] if phase["phase"] == "4"
    )
    expected_boot_tickets = (
        2
        + len(phase_4["parts"])
        + sum(
            bank["phase"] == "boot"
            for bank in audio_manifest["banks"]
        )
    )

    def load_and_record():
        page = context.new_page()
        gateway_responses = []
        ticket_batch_responses = []
        origin_heavy_responses = []
        direct_r2_responses = []
        page_errors = []
        console_errors = []
        failed_requests = []

        def record_response(response):
            parsed = urlparse(response.url)
            path = parsed.path
            if parsed.hostname and parsed.hostname.endswith("r2.cloudflarestorage.com"):
                direct_r2_responses.append(response.url)
            elif (
                parsed.hostname == "toontown.lui.ss"
                and path == "/api/assets/tickets"
            ):
                ticket_batch_responses.append(response.status)
            elif parsed.hostname == "toontown.lui.ss" and path.startswith("/assets/"):
                gateway_responses.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "cache": response.headers.get("cache-control", ""),
                        "encoding": response.headers.get("content-encoding", ""),
                        "disposition": response.headers.get("content-disposition", ""),
                    }
                )
            elif parsed.hostname == "toontown.lui.ss" and path.endswith(
                (".data", ".wasm")
            ):
                origin_heavy_responses.append((path.rsplit("/", 1)[-1], response.status))

        page.on("response", record_response)
        page.on("pageerror", lambda error: page_errors.append(type(error).__name__))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                (request.url, request.failure or "unknown failure")
            ),
        )
        # The game intentionally keeps a WebSocket and background phase
        # streaming active, so it never reaches Playwright network-idle.
        page.goto(ORIGIN, wait_until="domcontentloaded", timeout=30_000)
        ready_deadline = time.monotonic() + READY_TIMEOUT_MS / 1000
        while time.monotonic() < ready_deadline:
            if page.locator("#transfer").text_content() == "Toontown is ready!":
                break
            page.wait_for_timeout(100)
        else:
            print(
                "Production asset smoke startup diagnostics: "
                f"gateway={gateway_responses}, "
                f"originHeavy={origin_heavy_responses}, "
                f"pageErrors={page_errors}, "
                f"consoleErrors={console_errors[-12:]}, "
                f"failedRequests={failed_requests[-12:]}, "
                f"transfer={page.locator('#transfer').text_content()!r}"
            )
            raise AssertionError("production asset startup did not become ready")
        page.evaluate("window.ToontownSecureAssetCache.waitForIdle()")
        # Let Playwright deliver any response events whose bodies completed
        # during the final direct-handoff/cache write before taking counts.
        page.wait_for_timeout(250)
        diagnostics = page.evaluate("window.ToontownSecureAssetCache.diagnostics()")
        return (
            page,
            gateway_responses,
            ticket_batch_responses,
            origin_heavy_responses,
            direct_r2_responses,
            page_errors,
            diagnostics,
        )

    (
        cold_page,
        cold_gateway,
        cold_ticket_batches,
        cold_origin_heavy,
        cold_direct_r2,
        cold_errors,
        cold_cache,
    ) = load_and_record()
    assert not cold_errors, f"cold runtime raised {len(cold_errors)} page errors"
    assert not cold_direct_r2, "the browser must never receive a direct R2 URL"
    assert cold_ticket_batches == [200], "cold boot must use one ticket batch"
    assert cold_gateway, "cold startup did not use the private Worker gateway"
    assert all(item["status"] == 200 for item in cold_gateway)
    assert all(item["cache"] == "private, no-store" for item in cold_gateway)
    assert all(item["encoding"] == "gzip" for item in cold_gateway)
    assert all(item["disposition"].startswith("inline; filename=\"") for item in cold_gateway)
    assert all(
        not re.search(r"open-toontown|phase-|releases/|[a-f0-9]{64}", item["url"])
        for item in cold_gateway
    ), "opaque Worker tickets leaked asset names or release identifiers"
    assert not cold_origin_heavy, (
        "batched cold boot unexpectedly made per-asset origin requests"
    )
    assert cold_cache["writes"] >= 2
    assert cold_cache["disabled"] is False
    cold_phase_4_before = cold_page.evaluate(
        "window.ToontownAssetLoader.diagnostics()['4']"
    )
    assert cold_phase_4_before["state"] in {"loading", "ready"}
    cold_mount_ms = cold_page.evaluate(
        """async () => {
            const startedAt = performance.now();
            await window.ToontownAssetLoader.requestPhase('4');
            return performance.now() - startedAt;
        }"""
    )
    cold_page.wait_for_timeout(100)
    cold_phase_4 = cold_page.evaluate(
        "window.ToontownAssetLoader.diagnostics()['4']"
    )
    assert cold_phase_4["state"] == "ready"
    assert cold_phase_4["fromCache"] is False
    cold_handoff = cold_phase_4["directHandoff"]
    assert cold_handoff["networkParts"] == 23
    assert cold_handoff["cacheParts"] == 0
    assert cold_handoff["claims"] == 23
    assert 1 <= cold_handoff["peakActiveParts"] <= 4
    assert cold_handoff["cacheFailures"] == 0
    cold_ticket_diagnostics = cold_page.evaluate(
        "window.ToontownAssetTicketPool.diagnostics()"
    )
    cold_boot_diagnostics = cold_page.evaluate(
        "window.__toontownBootDiagnostics"
    )
    assert cold_ticket_diagnostics["batches"] == 1
    assert (
        cold_ticket_diagnostics["requested"] == expected_boot_tickets
    ), cold_ticket_diagnostics
    assert (
        cold_ticket_diagnostics["issued"] == expected_boot_tickets
    ), cold_ticket_diagnostics
    assert (
        cold_ticket_diagnostics["uses"] == expected_boot_tickets
    ), cold_ticket_diagnostics
    assert (
        cold_boot_diagnostics["phase4StartedAt"]
        <= cold_boot_diagnostics["runtimeStartedAt"]
        < cold_boot_diagnostics["phase4CompletedAt"]
    ), "the production runtime and Phase 4 downloads did not overlap"

    deferred_gateway_before = len(cold_gateway)
    deferred_origin_before = len(cold_origin_heavy)
    deferred_ticket_batches_before = len(cold_ticket_batches)
    deferred_phase_ms = cold_page.evaluate(
        """async () => {
            const startedAt = performance.now();
            await window.ToontownAssetLoader.requestPhase('5');
            await window.ToontownSecureAssetCache.waitForIdle();
            return performance.now() - startedAt;
        }"""
    )
    cold_page.wait_for_timeout(250)
    deferred_gateway = cold_gateway[deferred_gateway_before:]
    deferred_origin = cold_origin_heavy[deferred_origin_before:]
    assert len(cold_ticket_batches) == deferred_ticket_batches_before + 1
    assert cold_ticket_batches[-1] == 200
    assert deferred_gateway, "deferred Phase 5 did not use opaque Worker tickets"
    assert all(item["status"] == 200 for item in deferred_gateway)
    assert not deferred_origin, (
        "deferred Phase 5 attempted a direct origin heavy-asset request"
    )
    assert cold_page.evaluate(
        "window.ToontownAssetLoader.diagnostics()['5'].state"
    ) == "ready"
    cold_page.close()

    (
        warm_page,
        warm_gateway,
        warm_ticket_batches,
        _warm_origin_heavy,
        warm_direct_r2,
        warm_errors,
        warm_cache,
    ) = load_and_record()
    assert not warm_errors, f"warm runtime raised {len(warm_errors)} page errors"
    assert not warm_direct_r2
    assert not warm_ticket_batches, "warm boot unnecessarily requested tickets"
    assert warm_cache["hits"] >= 2, "warm startup did not use encrypted IndexedDB"
    assert not warm_gateway, "warm startup unnecessarily downloaded cached heavy assets"
    warm_mount_ms = warm_page.evaluate(
        """async () => {
            const startedAt = performance.now();
            await window.ToontownAssetLoader.requestPhase('4');
            return performance.now() - startedAt;
        }"""
    )
    warm_phase_4 = warm_page.evaluate(
        "window.ToontownAssetLoader.diagnostics()['4']"
    )
    assert warm_phase_4["state"] == "ready"
    assert warm_phase_4["fromCache"] is True
    assert not warm_gateway
    warm_page.close()

    print(
        "Production private asset smoke passed: "
        f"one batch + {len(cold_gateway)} direct opaque Worker streams, "
        f"{warm_cache['hits']} encrypted-cache hits, "
        "engine/WASM started before Phase 4 completed, "
        f"Phase 4 reused direct handoff in {cold_mount_ms:.0f}ms cold / "
        f"encrypted cache in {warm_mount_ms:.0f}ms warm, "
        f"deferred Phase 5 used {len(deferred_gateway)} opaque streams in "
        f"{deferred_phase_ms:.0f}ms, no direct R2 URLs"
    )
    browser.close()
