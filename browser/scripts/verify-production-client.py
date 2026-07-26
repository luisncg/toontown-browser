#!/usr/bin/env python3
"""Fail a release build if direct local Astron support is still packaged."""

import argparse
from pathlib import Path


FORBIDDEN_JAVASCRIPT = (
    "127.0.0.1",
    "localhost",
    "::1",
    "ws://127.0.0.1:7200/astron",
    "isLocalDevelopmentPage",
    "localBrowserGameServerForPage",
    "TOONTOWN_LOCAL_ASTRON_DEVELOPMENT",
)
LOCAL_ASTRON_ENDPOINT = b"ws://127.0.0.1:7200/astron"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    javascript_files = sorted(args.dist_dir.glob("*.js"))
    if not javascript_files:
        raise SystemExit("Production client verification found no JavaScript")
    failures = []
    for path in javascript_files:
        source = path.read_text(encoding="utf-8", errors="replace")
        for token in FORBIDDEN_JAVASCRIPT:
            if token in source:
                failures.append(f"{path.name}: contains {token!r}")

    app = (args.dist_dir / "app.js").read_text(encoding="utf-8")
    authority = (
        args.dist_dir / "runtime-authority.js"
    ).read_text(encoding="utf-8")
    if 'signedRequest("/api/gateway/lease", {})' not in app:
        failures.append("app.js: signed gateway lease path is missing")
    if "async function createAuthorization" not in authority:
        failures.append("runtime-authority.js: proof-of-possession path is missing")

    package = args.dist_dir / "open-toontown.data"
    if not package.is_file():
        failures.append("open-toontown.data: production package is missing")
    elif LOCAL_ASTRON_ENDPOINT in package.read_bytes():
        failures.append(
            "open-toontown.data: contains the direct local Astron endpoint"
        )

    if failures:
        raise SystemExit(
            "Production client contains a local Astron escape hatch:\n- "
            + "\n- ".join(failures)
        )
    print(
        "Production client verification passed: "
        "signed gateway only, no loopback Astron bypass"
    )


if __name__ == "__main__":
    main()
