#!/usr/bin/env python3
"""Generate exact browser VFS paths for battle sound filenames."""

import argparse
from pathlib import Path


PHASES = ("phase_3", "phase_3.5", "phase_4", "phase_5")
SOUND_EXTENSIONS = frozenset((".mp3", ".ogg", ".wav"))


def build_index(resources_root):
    """Return the legacy-search-order mapping of lowercase names to VFS paths."""
    resources_root = Path(resources_root)
    index = {}
    for phase in PHASES:
        sound_root = resources_root / phase / "audio" / "sfx"
        if not sound_root.is_dir():
            raise FileNotFoundError(
                "Missing battle sound directory: %s" % sound_root)
        for sound_path in sorted(sound_root.rglob("*")):
            if (
                not sound_path.is_file()
                or sound_path.suffix.lower() not in SOUND_EXTENSIONS
            ):
                continue
            # setdefault preserves BattleSounds' Phase 3 -> 3.5 -> 4 -> 5
            # behavior if a legacy/custom resource ever duplicates a basename.
            index.setdefault(
                sound_path.name.lower(),
                sound_path.relative_to(resources_root.parent).as_posix(),
            )
    return index


def render_index(index):
    lines = [
        '"""Generated browser battle-sound paths; do not edit."""',
        "",
        "BATTLE_SOUND_PATHS = {",
    ]
    lines.extend(
        "    %r: %r," % (name, path)
        for name, path in sorted(index.items())
    )
    lines.extend(("}", ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index = build_index(args.resources_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_index(index), encoding="utf-8")
    print("Generated %s browser battle-sound paths" % len(index))


if __name__ == "__main__":
    main()
