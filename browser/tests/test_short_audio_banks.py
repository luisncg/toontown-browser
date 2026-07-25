import contextlib
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace


PROJECT_DIR = Path(__file__).resolve().parents[2]
GENERATOR = (
    PROJECT_DIR / "browser" / "scripts" / "build-short-audio-banks.py"
)


def _write_wave(path, frames, sample_rate=22050):
    samples = struct.pack("<%sh" % frames, *range(frames))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples)


class ShortAudioBankBuildTests(unittest.TestCase):
    def test_generator_preserves_exact_frame_boundaries_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.wav"
            second = root / "second.wav"
            _write_wave(first, 12)
            _write_wave(second, 7)
            config = {
                "version": 1,
                "banks": [
                    {
                        "id": "test-bank",
                        "asset": "audio-bank-test-v1.data",
                        "kind": "short-effects",
                        "phase": "boot",
                        "relevance": ["test"],
                        "sampleRate": 22050,
                        "channels": 1,
                        "sounds": [
                            {
                                "logicalName": "first.ogg",
                                "source": "first.wav",
                                "fallbackPandaAsset": "FIRST.ogg",
                                "defaultGain": 0.75,
                                "loopPoints": None,
                            },
                            {
                                "logicalName": "second.ogg",
                                "source": "second.wav",
                                "fallbackPandaAsset": "SECOND.ogg",
                                "defaultGain": 1.0,
                                "loopPoints": {
                                    "startFrame": 1,
                                    "endFrame": 6,
                                },
                            },
                        ],
                    }
                ],
            }
            config_path = root / "banks.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output_dir = root / "output"
            manifest_path = output_dir / "audio-bank-manifest.json"

            subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--project-root",
                    str(root),
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--manifest",
                    str(manifest_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            bank = manifest["banks"][0]
            bank_path = output_dir / bank["asset"]
            self.assertEqual(bank["sampleRate"], 22050)
            self.assertEqual(bank["channels"], 1)
            self.assertEqual(bank["totalFrames"], 19)
            self.assertEqual(
                bank["contentHash"],
                hashlib.sha256(bank_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                bank["sounds"]["first.ogg"]["startFrame"],
                0,
            )
            self.assertEqual(
                bank["sounds"]["first.ogg"]["frameCount"],
                12,
            )
            self.assertEqual(
                bank["sounds"]["second.ogg"]["startFrame"],
                12,
            )
            self.assertEqual(
                bank["sounds"]["second.ogg"]["frameCount"],
                7,
            )
            self.assertEqual(
                bank["sounds"]["second.ogg"]["loopPoints"],
                {"startFrame": 1, "endFrame": 6},
            )
            with wave.open(str(bank_path), "rb") as combined:
                self.assertEqual(combined.getnframes(), 19)
                self.assertEqual(combined.getframerate(), 22050)


class BrowserAudioProxyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PROJECT_DIR / "browser" / "client"))
        import builtins

        builtins.base = SimpleNamespace(
            sfxActive=True,
            AppHasAudioFocus=True,
        )
        global browser_audio
        import browser_audio

    def test_proxy_supports_sound_interval_and_sfx_player_methods(self):
        sound = browser_audio.BrowserAudioSound(
            "test.ogg",
            {
                "length": 1.25,
                "defaultGain": 1.0,
            },
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sound.setTime(0.1)
            sound.setLoop(False)
            sound.setVolume(0.5)
            sound.setPlayRate(1.25)
            sound.setBalance(-0.2)
            sound.play()
            self.assertEqual(sound.status(), browser_audio.AudioSound.PLAYING)
            sound.stop()

        self.assertAlmostEqual(sound.length(), 1.25)
        self.assertEqual(sound.getName(), "test.ogg")
        self.assertFalse(sound.getLoop())
        self.assertAlmostEqual(sound.getVolume(), 0.5)
        self.assertAlmostEqual(sound.getPlayRate(), 1.25)
        self.assertAlmostEqual(sound.getBalance(), -0.2)
        self.assertEqual(sound.status(), browser_audio.AudioSound.READY)
        commands = output.getvalue()
        self.assertIn("[BrowserWebAudioCommand] play", commands)
        self.assertIn("[BrowserWebAudioCommand] stop", commands)
        self.assertIn("[BrowserWebAudioCommand] volume", commands)
        self.assertIn("[BrowserWebAudioCommand] balance", commands)


if __name__ == "__main__":
    unittest.main()
