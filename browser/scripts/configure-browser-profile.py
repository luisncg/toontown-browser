#!/usr/bin/env python3
"""Apply build-time browser features to disposable package copies."""

import argparse
import re
from pathlib import Path


START = "/* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_START */"
END = "/* TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_END */"
LOCAL_ASTRON_ENDPOINT = "ws://127.0.0.1:7200/astron"


def configure_javascript(path, enabled):
    source = path.read_text(encoding="utf-8")
    if source.count(START) != source.count(END) or START not in source:
        raise ValueError(f"Local Astron build markers are invalid in {path}")
    if enabled:
        configured = source.replace(START, "").replace(END, "")
    else:
        configured = re.sub(
            rf"^[ \t]*{re.escape(START)}[ \t]*\n"
            rf".*?"
            rf"^[ \t]*{re.escape(END)}[ \t]*\n?",
            "",
            source,
            flags=re.MULTILINE | re.DOTALL,
        )
    if START in configured or END in configured:
        raise ValueError(f"Local Astron build markers survived in {path}")
    forbidden = (
            "127.0.0.1",
            "localhost",
            "::1",
            LOCAL_ASTRON_ENDPOINT,
            "isLocalDevelopmentPage",
            "localBrowserGameServerForPage",
    )
    survivors = [
        token for token in forbidden
        if not enabled and token in configured
    ]
    if survivors:
        raise ValueError(
            f"Local Astron bypass survived in {path}: {survivors}"
        )
    path.write_text(configured, encoding="utf-8")


def replace_once(source, old, new, path):
    if source.count(old) != 1:
        raise ValueError(f"Expected one {old!r} assignment in {path}")
    return source.replace(old, new, 1)


def configure_python(path, enabled):
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "LOCAL_ASTRON_DEVELOPMENT = True",
        f"LOCAL_ASTRON_DEVELOPMENT = {enabled!r}",
        path,
    )
    source = replace_once(
        source,
        f'DEFAULT_BROWSER_GAME_SERVER = "{LOCAL_ASTRON_ENDPOINT}"',
        (
            f'DEFAULT_BROWSER_GAME_SERVER = "{LOCAL_ASTRON_ENDPOINT}"'
            if enabled
            else 'DEFAULT_BROWSER_GAME_SERVER = ""'
        ),
        path,
    )
    if not enabled and LOCAL_ASTRON_ENDPOINT in source:
        raise ValueError(f"Local Astron endpoint survived in {path}")
    path.write_text(source, encoding="utf-8")


def configure_direct(path, enabled):
    source = path.read_text(encoding="utf-8")
    quoted_endpoint = f'"{LOCAL_ASTRON_ENDPOINT}"'
    replacement = quoted_endpoint if enabled else '""'
    source = replace_once(
        source,
        quoted_endpoint,
        replacement,
        path,
    )
    if not enabled and LOCAL_ASTRON_ENDPOINT in source:
        raise ValueError(f"Local Astron endpoint survived in {path}")
    path.write_text(source, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-dir", type=Path)
    parser.add_argument("--client-dir", type=Path)
    parser.add_argument("--direct-dir", type=Path)
    parser.add_argument(
        "--local-astron-development",
        choices=("enabled", "disabled"),
        required=True,
    )
    args = parser.parse_args()
    if (
        args.web_dir is None
        and args.client_dir is None
        and args.direct_dir is None
    ):
        parser.error("at least one package directory is required")

    enabled = args.local_astron_development == "enabled"
    if args.client_dir is not None:
        configure_python(args.client_dir / "browser_game.py", enabled)
    if args.direct_dir is not None:
        configure_direct(
            args.direct_dir / "distributed" / "ConnectionRepository.py",
            enabled,
        )
    if args.web_dir is not None:
        for name in ("app.js", "runtime-authority.js"):
            configure_javascript(args.web_dir / name, enabled)


if __name__ == "__main__":
    main()
