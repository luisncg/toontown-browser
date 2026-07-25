#!/usr/bin/env python3
"""Build deterministic, independently cached Emscripten phase packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_CHUNK_TARGET_BYTES = 4 * 1024 * 1024
# Phase 4 is the only streamed phase on the critical path into the first
# playground/tutorial. Safari showed that halving its package target doubled
# the sequential request count and stretched this gate from seconds to 37.5
# seconds, so keep the standard 4 MiB target here deliberately.
PHASE_CHUNK_TARGET_BYTES = {"4": DEFAULT_CHUNK_TARGET_BYTES}
# Phase 4 previously shipped as 49 two-MiB parts using the untagged names.
# Keep those URLs valid for already-open browser sessions while the 23-part
# layout rolls out under a distinct namespace.
PHASE_PACKAGE_PREFIXES = {"4": "phase-4-4m-v1"}
COLD_START_PHASES = {"phase_3", "phase_3.5"}
PHASE_35_NEWS_PACKAGE = "news"


def phase_sort_key(path: Path) -> float:
    return float(path.name.removeprefix("phase_"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_phase_callbacks(loader_path: Path, phase: str, part: int) -> None:
    source = loader_path.read_text(encoding="utf-8")
    completion_pattern = re.compile(
        r"(?P<indent>\s*)Module\['removeRunDependency'\]"
        r"\('datafile_[^']+'\);"
    )
    completion = completion_pattern.search(source)
    if completion is None:
        raise RuntimeError(
            f"Could not locate data-file completion in {loader_path.name}"
        )
    indent = completion.group("indent")
    completion_callback = (
        completion.group(0)
        + "\n"
        + indent
        + "window.ToontownAssetLoader?.phasePackagePartLoaded("
        + json.dumps(phase)
        + ", "
        + str(part)
        + ", window.ToontownSecureAssetCache?.wasCacheHit("
        + json.dumps(loader_path.name.removesuffix(".js") + ".data")
        + ") === true);"
    )
    source = (
        source[: completion.start()]
        + completion_callback
        + source[completion.end() :]
    )

    error_line = "console.error('package error:', error);"
    if source.count(error_line) != 1:
        raise RuntimeError(
            f"Could not locate the unique package error handler in {loader_path.name}"
        )
    source = source.replace(
        error_line,
        error_line
        + "\n        window.ToontownAssetLoader?.phasePackagePartFailed("
        + json.dumps(phase)
        + ", "
        + str(part)
        + ", error);",
    )
    loader_path.write_text(source, encoding="utf-8")


def partition_phase_files(
    files: list[Path], target_bytes: int
) -> list[list[Path]]:
    parts: list[list[Path]] = []
    current: list[Path] = []
    current_bytes = 0
    for path in sorted(files):
        size = path.stat().st_size
        if current and current_bytes + size > target_bytes:
            parts.append(current)
            current = []
            current_bytes = 0
        current.append(path)
        current_bytes += size
    if current:
        parts.append(current)
    return parts


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: build-phase-packages.py PROJECT_DIR DIST_DIR FILE_PACKAGER",
            file=sys.stderr,
        )
        return 2

    project_dir = Path(sys.argv[1]).resolve()
    dist_dir = Path(sys.argv[2]).resolve()
    file_packager = Path(sys.argv[3]).resolve()
    resources_dir = project_dir / "resources"
    phase_dirs = sorted(
        (
            path
            for path in resources_dir.glob("phase_*")
            if path.is_dir() and path.name not in COLD_START_PHASES
        ),
        key=phase_sort_key,
    )
    if not phase_dirs:
        raise RuntimeError("No streamed resource phases were found")

    package_groups = [
        (
            phase_dir.name.removeprefix("phase_"),
            phase_dir,
            [path for path in phase_dir.rglob("*") if path.is_file()],
        )
        for phase_dir in phase_dirs
    ]
    phase_35_dir = resources_dir / "phase_3.5"
    phase_35_news_dir = phase_35_dir / "models" / "news"
    phase_35_news_files = [
        path for path in phase_35_news_dir.rglob("*") if path.is_file()
    ]
    if not phase_35_news_files:
        raise RuntimeError("Phase 3.5 news assets were not found")
    package_groups.append(
        (PHASE_35_NEWS_PACKAGE, phase_35_dir, phase_35_news_files)
    )

    manifest_phases = []
    build_dir = project_dir / ".build-wasm"
    build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="phase-package-staging-",
        dir=build_dir,
    ) as staging_directory:
        staging_root = Path(staging_directory)
        for phase, phase_dir, phase_files in package_groups:
            manifest_parts = []
            chunk_target_bytes = PHASE_CHUNK_TARGET_BYTES.get(
                phase, DEFAULT_CHUNK_TARGET_BYTES
            )
            package_prefix = PHASE_PACKAGE_PREFIXES.get(
                phase, f"phase-{phase}"
            )
            for part, files in enumerate(
                partition_phase_files(phase_files, chunk_target_bytes),
                start=1,
            ):
                package_staging = (
                    staging_root
                    / f"phase-{phase}-part-{part}"
                    / phase_dir.name
                )
                for source in files:
                    destination = package_staging / source.relative_to(phase_dir)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.link(source, destination)

                data_name = f"{package_prefix}-part-{part}.data"
                loader_name = f"{package_prefix}-part-{part}.js"
                data_path = dist_dir / data_name
                loader_path = dist_dir / loader_name
                subprocess.run(
                    [
                        sys.executable,
                        str(file_packager),
                        data_name,
                        "--preload",
                        f"{package_staging}@/resources/{phase_dir.name}",
                        f"--js-output={loader_name}",
                        "--no-node",
                    ],
                    cwd=dist_dir,
                    check=True,
                )
                add_phase_callbacks(loader_path, phase, part)
                manifest_parts.append(
                    {
                        "part": part,
                        "data": data_name,
                        "loader": loader_name,
                        "bytes": data_path.stat().st_size,
                        "sha256": sha256(data_path),
                        "loaderSha256": sha256(loader_path),
                    }
                )

            manifest_phases.append(
                {
                    "phase": phase,
                    "bytes": sum(item["bytes"] for item in manifest_parts),
                    "chunkTargetBytes": chunk_target_bytes,
                    "parts": manifest_parts,
                }
            )

    manifest = {
        "version": 2,
        "cacheDatabase": "TOONTOWN_SECURE_ASSET_CACHE_V1",
        "chunkTargetBytes": DEFAULT_CHUNK_TARGET_BYTES,
        "phaseChunkTargetBytes": PHASE_CHUNK_TARGET_BYTES,
        "phases": manifest_phases,
    }
    (dist_dir / "phase-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
