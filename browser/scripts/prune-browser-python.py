#!/usr/bin/env python3
"""Remove server-role Python modules from the disposable browser package.

The native AI and UberDOG processes continue to use the source tree.  This
script only mutates the staging copies embedded by Emscripten.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SERVER_ONLY_MODULES = frozenset(
    {
        "otp/ai/AIBase.py",
        "otp/ai/AIBaseGlobal.py",
        "otp/ai/AIMsgTypes.py",
        "otp/ai/AIZoneData.py",
        "otp/ai/Barrier.py",
        "otp/distributed/GameServerTestSuite.py",
        "otp/distributed/OTPInternalRepository.py",
        "otp/login/LoginAttemptLimiter.py",
        "otp/login/PasswordCredentialDB.py",
        "toontown/ai/AIStart.py",
        "toontown/ai/DatabaseObject.py",
        "toontown/ai/ServerEventBuffer.py",
        "toontown/ai/ToonBarrier.py",
        "toontown/ai/ToontownAIMsgTypes.py",
        "toontown/ai/ToontownAIRepository.py",
        "toontown/distributed/ToontownInternalRepository.py",
        "toontown/pets/PetActionFSM.py",
        "toontown/pets/PetBrain.py",
        "toontown/pets/PetGoal.py",
        "toontown/pets/PetGoalMgr.py",
        "toontown/pets/PetObserve.py",
        "toontown/uberdog/DataStore.py",
        "toontown/uberdog/DataStoreGlobals.py",
        "toontown/uberdog/ScavengerHuntDataStore.py",
        "toontown/uberdog/ToontownUDRepository.py",
        "toontown/uberdog/UDStart.py",
    }
)

SERVER_ROLE_STEM = re.compile(r"(?:AI|UD)$")


def is_server_only(relative_path: str) -> bool:
    relative_path = relative_path.replace("\\", "/")
    if relative_path in SERVER_ONLY_MODULES:
        return True
    path = Path(relative_path)
    if path.suffix == ".py":
        return bool(SERVER_ROLE_STEM.search(path.stem))
    if path.suffix == ".pyc":
        source_stem = path.name.split(".cpython-", 1)[0]
        return bool(SERVER_ROLE_STEM.search(source_stem)) or any(
            relative_path.endswith(
                f"/__pycache__/{Path(entry).stem}.cpython-312.pyc"
            )
            for entry in SERVER_ONLY_MODULES
        )
    return False


def package_files(otp_root: Path, toontown_root: Path):
    for package, root in (("otp", otp_root), ("toontown", toontown_root)):
        if not root.is_dir():
            raise SystemExit(f"Browser package root does not exist: {root}")
        for path in root.rglob("*"):
            if path.is_file():
                yield path, f"{package}/{path.relative_to(root).as_posix()}"


def prune(otp_root: Path, toontown_root: Path) -> tuple[int, int]:
    removed_count = 0
    removed_bytes = 0
    for path, relative in list(package_files(otp_root, toontown_root)):
        if not is_server_only(relative):
            continue
        removed_count += 1
        removed_bytes += path.stat().st_size
        path.unlink()
    for root in (otp_root, toontown_root):
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
    return removed_count, removed_bytes


def verify_staging(otp_root: Path, toontown_root: Path) -> None:
    forbidden = [
        relative
        for _path, relative in package_files(otp_root, toontown_root)
        if is_server_only(relative)
    ]
    if forbidden:
        sample = ", ".join(forbidden[:8])
        raise SystemExit(f"Server-only Python remains in browser staging: {sample}")


def verify_emscripten_index(index_path: Path) -> None:
    if not index_path.is_file():
        raise SystemExit(f"Emscripten package index does not exist: {index_path}")
    index = index_path.read_text("utf-8", errors="replace")
    forbidden = []
    for relative in sorted(SERVER_ONLY_MODULES):
        package, rest = relative.split("/", 1)
        source = f"/game/{package}/{rest}"
        bytecode = (
            f"/game/{package}/{Path(rest).parent.as_posix()}/__pycache__/"
            f"{Path(rest).stem}.cpython-312.pyc"
        )
        if source in index:
            forbidden.append(source)
        if bytecode in index:
            forbidden.append(bytecode)
    role_path = re.compile(
        r"/game/(?:otp|toontown)/[^\"']*/(?:[^/\"']*(?:AI|UD))"
        r"(?:\.py|\.cpython-312\.pyc)"
    )
    forbidden.extend(match.group(0) for match in role_path.finditer(index))
    if forbidden:
        sample = ", ".join(sorted(set(forbidden))[:8])
        raise SystemExit(f"Server-only Python leaked into Emscripten index: {sample}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("otp_root", type=Path)
    parser.add_argument("toontown_root", type=Path)
    parser.add_argument("--verify-index", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if not args.verify_only:
        removed_count, removed_bytes = prune(args.otp_root, args.toontown_root)
        print(
            "Browser Python pruning removed "
            f"{removed_count} server-role files ({removed_bytes} bytes)."
        )
    verify_staging(args.otp_root, args.toontown_root)
    if args.verify_index:
        verify_emscripten_index(args.verify_index)


if __name__ == "__main__":
    main()
