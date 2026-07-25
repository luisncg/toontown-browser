#!/usr/bin/env python3
"""Remove server-only direct imports from the browser copies of DC files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


IMPORT_LINE = re.compile(
    r"^from\s+(?P<module>\S+)\s+import\s+(?P<symbols>.+?)\s*$"
)
SERVER_ROLE_NAME = re.compile(r"(?:AI|UD)$")


def is_explicit_server_import(line: str) -> bool:
    match = IMPORT_LINE.match(line.strip())
    if not match:
        return False
    module = match.group("module")
    symbols = [item.strip() for item in match.group("symbols").split(",")]
    if "/" in module or any("/" in item for item in symbols):
        return False
    module_name = module.rsplit(".", 1)[-1]
    return bool(SERVER_ROLE_NAME.search(module_name)) or any(
        SERVER_ROLE_NAME.search(item) for item in symbols
    )


def prune_file(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    kept = [line for line in lines if not is_explicit_server_import(line)]
    removed = len(lines) - len(kept)
    if removed:
        path.write_text("".join(kept), encoding="utf-8")
    return removed


def verify_file(path: Path) -> None:
    forbidden = [
        (number, line.strip())
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if is_explicit_server_import(line)
    ]
    if forbidden:
        sample = ", ".join(f"{path.name}:{line}" for line, _ in forbidden[:5])
        raise SystemExit(f"Server-only DC imports remain in browser package: {sample}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("etc_root", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    paths = sorted(args.etc_root.glob("*.dc"))
    if not paths:
        raise SystemExit(f"No DC files found in browser package: {args.etc_root}")
    removed = 0
    if not args.verify_only:
        removed = sum(prune_file(path) for path in paths)
        print(f"Browser DC pruning removed {removed} explicit server-role imports.")
    for path in paths:
        verify_file(path)


if __name__ == "__main__":
    main()
