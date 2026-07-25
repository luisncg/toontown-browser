"""Verify playground phases stream after Toon selection and reuse IndexedDB."""

import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parents[2]
GAME_URL = os.environ.get("OPEN_TOONTOWN_URL", "http://127.0.0.1:8180")
ACCOUNT = os.environ.get("OPEN_TOONTOWN_PHASE_ACCOUNT", "test")
PASSWORD = os.environ.get("OPEN_TOONTOWN_PHASE_PASSWORD", "test")
SCREENSHOT = PROJECT_DIR / ".build-wasm" / "phase-streaming-playground.png"
BOOT_PHASES = ("4",)
BACKGROUND_PHASES = (
    "5", "5.5", "6", "8", "7", "9", "10", "11", "12", "13",
)
ON_DEMAND_PHASES = ("news",)
STREAMED_PHASES = BOOT_PHASES + BACKGROUND_PHASES + ON_DEMAND_PHASES


def wait_for_console(page, lines, marker, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in lines):
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        "Timed out waiting for %r. Console tail:\n%s"
        % (marker, "\n".join(lines[-200:]))
    )


def phase_data_names(urls):
    return [
        Path(urlparse(url).path).name
        for url in urls
        if Path(urlparse(url).path).name.startswith("phase-")
        and Path(urlparse(url).path).suffix == ".data"
    ]


def package_data_names(urls):
    return [
        Path(urlparse(url).path).name
        for url in urls
        if Path(urlparse(url).path).suffix == ".data"
    ]


def summarize_failed_responses(responses):
    counts = Counter((item["status"], item["url"]) for item in responses)
    return [
        {"status": status, "url": url, "count": count}
        for (status, url), count in sorted(counts.items())
    ]


def summarize_diagnostics(diagnostics):
    return {
        phase: {
            "state": details["state"],
            "fromCache": details["fromCache"],
            "partsReady": details.get("partsReady"),
            "partsTotal": details.get("partsTotal"),
            "prefetchState": details.get("prefetchState"),
            "prefetchFromCache": details.get("prefetchFromCache"),
            "directHandoff": details.get("directHandoff"),
        }
        for phase, details in diagnostics.items()
    }


def open_game(
    context,
    request_urls,
    failed_responses,
    console_lines,
    console_errors,
    page_errors,
):
    page = context.new_page()
    page.on("request", lambda request: request_urls.append(request.url))
    page.on(
        "response",
        lambda response: failed_responses.append({
            "status": response.status,
            "url": response.url,
        }) if response.status >= 400 else None,
    )

    def capture_console(message):
        console_lines.append(message.text)
        if message.type == "error":
            console_errors.append(message.text)

    page.on("console", capture_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=120_000)
    page.locator("#loading.is-done").wait_for(state="attached", timeout=60_000)
    return page


def login_and_select(page, console_lines):
    canvas = page.locator("#canvas")
    canvas.click(position={"x": 660, "y": 410})
    page.keyboard.type(ACCOUNT)
    canvas.click(position={"x": 660, "y": 466})
    page.keyboard.type(PASSWORD)
    canvas.click(position={"x": 590, "y": 532})
    wait_for_console(page, console_lines, "AvatarChooser.enter", timeout=45)
    canvas.click(position={"x": 235, "y": 265})
    return canvas


with sync_playwright() as playwright:
    phase_manifest = json.loads(
        (PROJECT_DIR / "dist-web" / "phase-manifest.json").read_text()
    )
    audio_manifest = json.loads(
        (PROJECT_DIR / "dist-web" / "audio-bank-manifest.json").read_text()
    )
    expected_phase_data = [
        part["data"]
        for phase in STREAMED_PHASES
        for manifest_phase in phase_manifest["phases"]
        if str(manifest_phase["phase"]) == phase
        for part in manifest_phase["parts"]
    ]
    expected_background_phase_data = [
        part["data"]
        for phase in BOOT_PHASES + BACKGROUND_PHASES
        for manifest_phase in phase_manifest["phases"]
        if str(manifest_phase["phase"]) == phase
        for part in manifest_phase["parts"]
    ]
    browser = playwright.chromium.launch(
        headless=True,
        args=["--enable-webgl", "--ignore-gpu-blocklist"],
    )
    context = browser.new_context(viewport={"width": 1280, "height": 900})

    first_requests = []
    first_failed_responses = []
    first_console = []
    first_console_errors = []
    first_page_errors = []
    first_page = open_game(
        context,
        first_requests,
        first_failed_responses,
        first_console,
        first_console_errors,
        first_page_errors,
    )
    first_boot_diagnostics = first_page.evaluate(
        "window.__toontownBootDiagnostics"
    )
    first_ticket_diagnostics = first_page.evaluate(
        "window.ToontownAssetTicketPool.diagnostics()"
    )
    first_boot_events = first_page.evaluate(
        "window.ToontownPerformanceTelemetry.snapshot().history"
    )
    phase_4_data = [
        part["data"]
        for phase in BOOT_PHASES
        for manifest_phase in phase_manifest["phases"]
        if str(manifest_phase["phase"]) == phase
        for part in manifest_phase["parts"]
    ]
    phase_4_prefetch_concurrency = first_page.evaluate(
        """(names) => {
            const wanted = new Set(names);
            const boundaries = performance.getEntriesByType('resource')
                .filter((entry) => {
                    const name = new URL(entry.name).pathname.split('/').pop();
                    return wanted.has(name);
                })
                .flatMap((entry) => [
                    { at: entry.startTime, change: 1 },
                    { at: entry.startTime + entry.duration, change: -1 },
                ])
                .sort((left, right) => (
                    left.at - right.at || left.change - right.change
                ));
            let active = 0;
            let maximum = 0;
            for (const boundary of boundaries) {
                active += boundary.change;
                maximum = Math.max(maximum, active);
            }
            return maximum;
        }""",
        phase_4_data,
    )
    boot_request_overlap = first_page.evaluate(
        """(phaseNames) => {
            const phase = new Set(phaseNames);
            const entries = performance.getEntriesByType('resource').map(
                (entry) => ({
                    name: new URL(entry.name).pathname.split('/').pop(),
                    start: entry.startTime,
                    end: entry.startTime + entry.duration,
                }),
            );
            const phaseEntries = entries.filter((entry) => phase.has(entry.name));
            const runtimeEntries = entries.filter((entry) => (
                entry.name === 'open-toontown.data' ||
                entry.name === 'open-toontown.wasm'
            ));
            const range = (items) => ({
                start: Math.min(...items.map((item) => item.start)),
                end: Math.max(...items.map((item) => item.end)),
            });
            const phaseRange = range(phaseEntries);
            const runtimeRange = range(runtimeEntries);
            return {
                phaseRequests: phaseEntries.length,
                runtimeRequests: runtimeEntries.length,
                overlapMs: Math.max(
                    0,
                    Math.min(phaseRange.end, runtimeRange.end) -
                        Math.max(phaseRange.start, runtimeRange.start),
                ),
            };
        }""",
        phase_4_data,
    )
    first_canvas = first_page.locator("#canvas")
    first_canvas.click(position={"x": 660, "y": 410})
    first_page.keyboard.type(ACCOUNT)
    first_canvas.click(position={"x": 660, "y": 466})
    first_page.keyboard.type(PASSWORD)
    first_canvas.click(position={"x": 590, "y": 532})
    wait_for_console(first_page, first_console, "AvatarChooser.enter", timeout=45)
    first_page.wait_for_function(
        "window.ToontownAssetLoader.diagnostics()['4'].state === 'ready'",
        timeout=120_000,
    )
    # Capture complete boot metrics only after the background Phase 4 mount
    # settles. The login UI itself became usable earlier.
    first_boot_diagnostics = first_page.evaluate(
        "window.__toontownBootDiagnostics"
    )
    first_boot_events = first_page.evaluate(
        "window.ToontownPerformanceTelemetry.snapshot().history"
    )
    phase_4_prefetch_concurrency = first_page.evaluate(
        """(names) => {
            const wanted = new Set(names);
            const boundaries = performance.getEntriesByType('resource')
                .filter((entry) => {
                    const name = new URL(entry.name).pathname.split('/').pop();
                    return wanted.has(name);
                })
                .flatMap((entry) => [
                    { at: entry.startTime, change: 1 },
                    { at: entry.startTime + entry.duration, change: -1 },
                ])
                .sort((left, right) => (
                    left.at - right.at || left.change - right.change
                ));
            let active = 0;
            let maximum = 0;
            for (const boundary of boundaries) {
                active += boundary.change;
                maximum = Math.max(maximum, active);
            }
            return maximum;
        }""",
        phase_4_data,
    )
    boot_request_overlap = first_page.evaluate(
        """(phaseNames) => {
            const phase = new Set(phaseNames);
            const entries = performance.getEntriesByType('resource').map(
                (entry) => ({
                    name: new URL(entry.name).pathname.split('/').pop(),
                    start: entry.startTime,
                    end: entry.startTime + entry.duration,
                }),
            );
            const phaseEntries = entries.filter((entry) => phase.has(entry.name));
            const runtimeEntries = entries.filter((entry) => (
                entry.name === 'open-toontown.data' ||
                entry.name === 'open-toontown.wasm'
            ));
            const range = (items) => ({
                start: Math.min(...items.map((item) => item.start)),
                end: Math.max(...items.map((item) => item.end)),
            });
            const phaseRange = range(phaseEntries);
            const runtimeRange = range(runtimeEntries);
            return {
                phaseRequests: phaseEntries.length,
                runtimeRequests: runtimeEntries.length,
                overlapMs: Math.max(
                    0,
                    Math.min(phaseRange.end, runtimeRange.end) -
                        Math.max(phaseRange.start, runtimeRange.start),
                ),
            };
        }""",
        phase_4_data,
    )
    phase_data_before_selection = phase_data_names(first_requests)
    first_canvas.click(position={"x": 235, "y": 265})
    try:
        first_page.wait_for_function(
            """() => {
                const phases = window.__toontownPhaseDiagnostics;
                return phases?.['3.5']?.state === 'ready'
                    && phases?.['4']?.state === 'ready';
            }""",
            timeout=120_000,
        )
        first_page.evaluate(
            """() => {
                const probe = {
                    active: true,
                    started: false,
                    count: 0,
                    maxGapMs: 0,
                    maxGapContext: undefined,
                };
                window.__toontownPhaseFrameProbe = probe;
                let previous = performance.now();
                const tick = (now) => {
                    if (window.__toontownBackgroundStartedAt !== undefined) {
                        if (!probe.started) {
                            probe.started = true;
                            previous = now;
                        } else {
                            const gap = now - previous;
                            previous = now;
                            probe.count += 1;
                            if (gap > probe.maxGapMs) {
                                probe.maxGapMs = gap;
                                probe.maxGapContext = {
                                    backgroundElapsedMs:
                                        now - window.__toontownBackgroundStartedAt,
                                    phases: window.ToontownAssetLoader
                                        ?.diagnostics?.(),
                                };
                            }
                        }
                    }
                    if (probe.active) requestAnimationFrame(tick);
                };
                requestAnimationFrame(tick);
            }"""
        )
        wait_for_console(first_page, first_console, "teleportInDone:", timeout=90)
        if any("teleportInDone: popup" in line for line in first_console):
            first_canvas.click(position={"x": 590, "y": 540})
            first_page.wait_for_timeout(500)
        first_page.wait_for_function(
            """() => {
                const phases = window.__toontownPhaseDiagnostics;
                return phases
                    && Object.entries(phases).every(
                        ([name, phase]) => name === 'news'
                            || phase.state === 'ready',
                    );
            }""",
            timeout=240_000,
        )
    except Exception:
        print(json.dumps({
            "phase_data_before_selection": phase_data_before_selection,
            "phase_data_after_selection": phase_data_names(first_requests),
            "diagnostics": first_page.evaluate(
                "window.__toontownPhaseDiagnostics ?? "
                "window.ToontownAssetLoader?.diagnostics()"
            ),
            "console_tail": first_console[-240:],
            "console_errors": first_console_errors,
            "page_errors": first_page_errors,
        }, indent=2))
        raise

    first_news_state_before_request = first_page.evaluate(
        "window.ToontownAssetLoader.diagnostics().news.state"
    )
    first_background_phase_data = phase_data_names(first_requests)
    first_frame_probe = first_page.evaluate(
        """() => {
            window.__toontownPhaseFrameProbe.active = false;
            return window.__toontownPhaseFrameProbe;
        }"""
    )
    first_page.evaluate(
        "window.ToontownAssetLoader.requestPhase('news')"
    )
    first_page.wait_for_function(
        "window.ToontownAssetLoader.diagnostics().news.state === 'ready'",
        timeout=120_000,
    )
    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    first_page.screenshot(path=str(SCREENSHOT), full_page=True)
    storage_estimate = first_page.evaluate(
        "navigator.storage?.estimate?.() ?? Promise.resolve({})"
    )
    first_diagnostics = first_page.evaluate(
        "window.ToontownAssetLoader.diagnostics()"
    )
    first_phase_data = phase_data_names(first_requests)
    first_page.close()

    second_requests = []
    second_failed_responses = []
    second_console = []
    second_console_errors = []
    second_page_errors = []
    second_page = open_game(
        context,
        second_requests,
        second_failed_responses,
        second_console,
        second_console_errors,
        second_page_errors,
    )
    second_boot_diagnostics = second_page.evaluate(
        "window.__toontownBootDiagnostics"
    )
    second_ticket_diagnostics = second_page.evaluate(
        "window.ToontownAssetTicketPool.diagnostics()"
    )
    second_boot_events = second_page.evaluate(
        "window.ToontownPerformanceTelemetry.snapshot().history"
    )
    login_and_select(second_page, second_console)
    try:
        second_page.wait_for_function(
            """() => {
                const phases = window.__toontownPhaseDiagnostics;
                return phases?.['3.5']?.state === 'ready'
                    && phases?.['4']?.state === 'ready';
            }""",
            timeout=60_000,
        )
        second_boot_events = second_page.evaluate(
            "window.ToontownPerformanceTelemetry.snapshot().history"
        )
        wait_for_console(second_page, second_console, "teleportInDone:", timeout=90)
        if any("teleportInDone: popup" in line for line in second_console):
            second_page.locator("#canvas").click(position={"x": 590, "y": 540})
            second_page.wait_for_timeout(500)
        second_page.wait_for_function(
            """() => {
                const phases = window.__toontownPhaseDiagnostics;
                return phases
                    && Object.entries(phases).every(
                        ([name, phase]) => name === 'news'
                            || phase.state === 'ready',
                    );
            }""",
            timeout=180_000,
        )
    except Exception:
        print(json.dumps({
            "second_phase_data": phase_data_names(second_requests),
            "diagnostics": second_page.evaluate(
                "window.__toontownPhaseDiagnostics ?? "
                "window.ToontownAssetLoader?.diagnostics()"
            ),
            "console_tail": second_console[-240:],
            "console_errors": second_console_errors,
            "page_errors": second_page_errors,
        }, indent=2))
        raise

    second_news_state_before_request = second_page.evaluate(
        "window.ToontownAssetLoader.diagnostics().news.state"
    )
    second_page.evaluate(
        "window.ToontownAssetLoader.requestPhase('news')"
    )
    second_page.wait_for_function(
        "window.ToontownAssetLoader.diagnostics().news.state === 'ready'",
        timeout=120_000,
    )
    second_diagnostics = second_page.evaluate(
        "window.ToontownAssetLoader.diagnostics()"
    )
    second_phase_data = phase_data_names(second_requests)
    browser.close()


result = {
    "viewport": "1280x900px",
    "initial_archive_bytes": (
        PROJECT_DIR / "dist-web" / "open-toontown.data"
    ).stat().st_size,
    "phase_manifest_version": phase_manifest["version"],
    "phase_chunk_target_bytes": phase_manifest["chunkTargetBytes"],
    "phase_part_count": len(expected_phase_data),
    "phase_4_chunk_target_bytes": phase_manifest[
        "phaseChunkTargetBytes"
    ]["4"],
    "phase_data_before_selection": phase_data_before_selection,
    "phase_4_prefetch_concurrency": phase_4_prefetch_concurrency,
    "boot_request_overlap": boot_request_overlap,
    "first_boot_diagnostics": first_boot_diagnostics,
    "first_ticket_diagnostics": first_ticket_diagnostics,
    "second_boot_diagnostics": second_boot_diagnostics,
    "second_ticket_diagnostics": second_ticket_diagnostics,
    "second_boot_events": second_boot_events,
    "first_news_state_before_request": first_news_state_before_request,
    "first_background_phase_data_count": len(first_background_phase_data),
    "first_package_data_count": len(package_data_names(first_requests)),
    "first_phase_data_count": len(first_phase_data),
    "first_diagnostics": summarize_diagnostics(first_diagnostics),
    "second_phase_data_count": len(second_phase_data),
    "second_news_state_before_request": second_news_state_before_request,
    "second_package_data_count": len(package_data_names(second_requests)),
    "second_diagnostics": summarize_diagnostics(second_diagnostics),
    "first_console_errors": sorted(set(first_console_errors)),
    "first_failed_responses": summarize_failed_responses(
        first_failed_responses
    ),
    "first_page_errors": first_page_errors,
    "second_console_errors": sorted(set(second_console_errors)),
    "second_failed_responses": summarize_failed_responses(
        second_failed_responses
    ),
    "second_page_errors": second_page_errors,
    "first_frame_probe": first_frame_probe,
    "storage_estimate": storage_estimate,
    "screenshot": str(SCREENSHOT),
}
print(json.dumps(result, indent=2))

assert Counter(result["phase_data_before_selection"]) == Counter(phase_4_data)
assert result["phase_4_prefetch_concurrency"] == 4
assert result["boot_request_overlap"]["phaseRequests"] == len(phase_4_data)
assert result["boot_request_overlap"]["runtimeRequests"] == 2
assert result["boot_request_overlap"]["overlapMs"] > 0
assert (
    result["first_boot_diagnostics"]["runtimeStartedAt"] <
    result["first_boot_diagnostics"]["phase4CompletedAt"]
)
expected_ticket_names = 2 + len(phase_4_data) + len(audio_manifest["banks"])
assert result["first_boot_diagnostics"]["ticketBatch"] == {
    "requested": expected_ticket_names,
    "issued": 0,
    "fromCache": False,
}
assert result["first_ticket_diagnostics"]["batches"] == 1
assert (
    result["first_ticket_diagnostics"]["requested"] == expected_ticket_names
)
assert result["second_boot_diagnostics"]["ticketBatch"] == {
    "requested": 0,
    "issued": 0,
    "fromCache": True,
}
assert result["second_ticket_diagnostics"]["batches"] == 0
phase_handoff_complete = next(
    event for event in first_boot_events
    if event["type"] == "phase_handoff" and event["stage"] == "complete"
)
runtime_ready = next(
    event for event in first_boot_events if event["type"] == "runtime_ready"
)
assert runtime_ready["atMs"] < phase_handoff_complete["atMs"]
assert phase_handoff_complete["peakActiveParts"] == 4
assert phase_handoff_complete["claims"] == len(phase_4_data)
assert phase_handoff_complete["networkParts"] == len(phase_4_data)
assert phase_handoff_complete["cacheParts"] == 0
assert phase_handoff_complete["cacheFailures"] == 0
assert result["phase_manifest_version"] == 2
assert result["phase_4_chunk_target_bytes"] == 4 * 1024 * 1024
assert Counter(first_background_phase_data) == Counter(
    expected_background_phase_data
)
assert result["first_news_state_before_request"] == "idle"
assert Counter(first_phase_data) == Counter(expected_phase_data)
assert all(
    phase["state"] == "ready"
    for phase in result["first_diagnostics"].values()
)
assert all(
    phase["state"] == "ready" and phase["fromCache"]
    for phase in result["second_diagnostics"].values()
)
assert result["first_diagnostics"]["4"]["prefetchState"] == "idle"
assert (
    result["first_diagnostics"]["4"]["directHandoff"]["peakActiveParts"] == 4
)
assert (
    result["first_diagnostics"]["4"]["directHandoff"]["networkParts"] ==
    len(phase_4_data)
)
assert result["second_diagnostics"]["4"]["prefetchState"] == "idle"
assert (
    result["second_diagnostics"]["4"]["directHandoff"]["cacheParts"] ==
    len(phase_4_data)
)
assert (
    result["second_diagnostics"]["4"]["directHandoff"]["networkParts"] == 0
)
second_handoff_complete = next(
    event for event in second_boot_events
    if event["type"] == "phase_handoff" and event["stage"] == "complete"
)
assert second_handoff_complete["cacheParts"] == len(phase_4_data)
assert second_handoff_complete["networkParts"] == 0
assert second_handoff_complete["claims"] == len(phase_4_data)
assert result["second_news_state_before_request"] == "idle"
assert not second_phase_data
assert Counter(first_phase_data)[phase_4_data[0]] == 1
assert all(Counter(first_phase_data)[name] == 1 for name in phase_4_data)
assert "open-toontown.data" in package_data_names(first_requests)
assert not package_data_names(second_requests)
assert not result["first_console_errors"]
assert not result["first_failed_responses"]
assert not result["first_page_errors"]
assert not result["second_console_errors"]
assert not result["second_failed_responses"]
assert not result["second_page_errors"]
