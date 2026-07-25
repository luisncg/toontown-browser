#!/usr/bin/env python3
"""Build independently loadable Web Audio banks for short sound effects."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


def _bounded_string(value, label, pattern_chars):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(character not in pattern_chars for character in value)
    ):
        raise ValueError(f"{label} is invalid")
    return value


def _load_configuration(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("audio bank configuration version is unsupported")
    banks = value.get("banks")
    if not isinstance(banks, list) or not banks:
        raise ValueError("audio bank configuration must contain banks")
    return banks


def _decode_source(ffmpeg, source, output, sample_rate, channels):
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        check=True,
    )


def _build_bank(project_root, output_dir, ffmpeg, bank, seen_names):
    safe_id = _bounded_string(
        bank.get("id"), "bank id",
        "abcdefghijklmnopqrstuvwxyz0123456789-",
    )
    asset = _bounded_string(
        bank.get("asset"), "bank asset",
        "abcdefghijklmnopqrstuvwxyz0123456789.-",
    )
    if not asset.startswith("audio-bank-") or not asset.endswith(".data"):
        raise ValueError(f"{safe_id} bank asset must use audio-bank-*.data")
    sample_rate = bank.get("sampleRate")
    channels = bank.get("channels")
    if (
        not isinstance(sample_rate, int)
        or sample_rate < 8000
        or sample_rate > 192000
        or channels not in (1, 2)
    ):
        raise ValueError(f"{safe_id} bank audio format is invalid")
    sounds = bank.get("sounds")
    if not isinstance(sounds, list) or not sounds:
        raise ValueError(f"{safe_id} bank must contain sounds")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / asset
    sound_manifest = {}
    frame_cursor = 0
    with tempfile.TemporaryDirectory(prefix=f"toontown-{safe_id}-") as temp:
        decoded_paths = []
        for index, sound in enumerate(sounds):
            if not isinstance(sound, dict):
                raise ValueError(f"{safe_id} contains an invalid sound")
            logical_name = _bounded_string(
                sound.get("logicalName"), "logical sound name",
                "abcdefghijklmnopqrstuvwxyz0123456789_.-",
            )
            if logical_name in seen_names:
                raise ValueError(f"duplicate logical sound name: {logical_name}")
            seen_names.add(logical_name)
            source_value = sound.get("source")
            if not isinstance(source_value, str) or not source_value:
                raise ValueError(f"{logical_name} source is invalid")
            source = (project_root / source_value).resolve()
            try:
                source.relative_to(project_root)
            except ValueError as error:
                raise ValueError(
                    f"{logical_name} source escapes the project"
                ) from error
            if not source.is_file():
                raise FileNotFoundError(source)
            decoded = Path(temp) / f"{index:03d}.wav"
            _decode_source(
                ffmpeg, source, decoded, sample_rate, channels,
            )
            decoded_paths.append((logical_name, sound, decoded))

        with wave.open(str(output_path), "wb") as combined:
            combined.setnchannels(channels)
            combined.setsampwidth(2)
            combined.setframerate(sample_rate)
            for logical_name, sound, decoded in decoded_paths:
                with wave.open(str(decoded), "rb") as source_wave:
                    if (
                        source_wave.getnchannels() != channels
                        or source_wave.getsampwidth() != 2
                        or source_wave.getframerate() != sample_rate
                        or source_wave.getcomptype() != "NONE"
                    ):
                        raise ValueError(
                            f"{logical_name} did not decode to the bank format"
                        )
                    frame_count = source_wave.getnframes()
                    combined.writeframes(source_wave.readframes(frame_count))
                default_gain = sound.get("defaultGain", 1.0)
                if (
                    not isinstance(default_gain, (int, float))
                    or default_gain < 0
                    or default_gain > 4
                ):
                    raise ValueError(
                        f"{logical_name} default gain is invalid"
                    )
                loop_points = sound.get("loopPoints")
                if loop_points is not None:
                    if (
                        not isinstance(loop_points, dict)
                        or not isinstance(loop_points.get("startFrame"), int)
                        or not isinstance(loop_points.get("endFrame"), int)
                        or loop_points["startFrame"] < 0
                        or loop_points["endFrame"] > frame_count
                        or loop_points["startFrame"] >= loop_points["endFrame"]
                    ):
                        raise ValueError(
                            f"{logical_name} loop points are invalid"
                        )
                fallback = sound.get("fallbackPandaAsset")
                if not isinstance(fallback, str) or not fallback:
                    raise ValueError(
                        f"{logical_name} Panda fallback is invalid"
                    )
                sound_manifest[logical_name] = {
                    "startFrame": frame_cursor,
                    "frameCount": frame_count,
                    "defaultGain": float(default_gain),
                    "loopPoints": loop_points,
                    "fallbackPandaAsset": fallback,
                }
                frame_cursor += frame_count

    content = output_path.read_bytes()
    return {
        "id": safe_id,
        "asset": asset,
        "contentHash": hashlib.sha256(content).hexdigest(),
        "contentBytes": len(content),
        "sampleRate": sample_rate,
        "channels": channels,
        "totalFrames": frame_cursor,
        "kind": bank.get("kind", "short-effects"),
        "phase": bank.get("phase", "on-demand"),
        "relevance": bank.get("relevance", []),
        "streaming": False,
        "sounds": sound_manifest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    arguments = parser.parse_args()

    project_root = arguments.project_root.resolve()
    ffmpeg = shutil.which(arguments.ffmpeg)
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to build short audio banks")
    banks = _load_configuration(arguments.config)
    seen_names = set()
    output_banks = [
        _build_bank(
            project_root,
            arguments.output_dir,
            ffmpeg,
            bank,
            seen_names,
        )
        for bank in banks
    ]
    manifest = {
        "version": 1,
        "banks": output_banks,
    }
    arguments.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Built %s short-audio bank(s) with %s sound(s)"
        % (len(output_banks), len(seen_names))
    )


if __name__ == "__main__":
    main()
