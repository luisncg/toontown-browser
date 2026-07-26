import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
GENERATOR = (
    PROJECT_DIR / "browser" / "scripts" / "generate-battle-sound-index.py"
)


class BattleSoundIndexTests(unittest.TestCase):
    def test_generator_preserves_search_order_and_exact_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "resources"
            for phase in ("phase_3", "phase_3.5", "phase_4", "phase_5"):
                (resources / phase / "audio" / "sfx").mkdir(parents=True)
            (resources / "phase_3.5" / "audio" / "sfx" / "Pie.ogg").write_bytes(
                b"phase-3.5")
            (resources / "phase_5" / "audio" / "sfx" / "PowerTie.ogg").write_bytes(
                b"phase-5")
            (resources / "phase_3" / "audio" / "sfx" / "Duplicate.ogg").write_bytes(
                b"phase-3")
            (resources / "phase_5" / "audio" / "sfx" / "duplicate.ogg").write_bytes(
                b"phase-5")
            (resources / "phase_4" / "audio" / "sfx" / "ignore.txt").write_text(
                "not audio", encoding="utf-8")
            output = root / "generated_index.py"

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATOR),
                    "--resources-root",
                    str(resources),
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            namespace = {}
            exec(output.read_text(encoding="utf-8"), namespace)
            self.assertEqual(
                namespace["BATTLE_SOUND_PATHS"],
                {
                    "duplicate.ogg":
                        "resources/phase_3/audio/sfx/Duplicate.ogg",
                    "pie.ogg": "resources/phase_3.5/audio/sfx/Pie.ogg",
                    "powertie.ogg":
                        "resources/phase_5/audio/sfx/PowerTie.ogg",
                },
            )
            self.assertIn("Generated 3 browser battle-sound paths", result.stdout)

    def test_battle_buffers_use_async_web_audio_banks(self):
        battle_sounds = (
            PROJECT_DIR / "toontown" / "battle" / "BattleSounds.py"
        ).read_text(encoding="utf-8")
        town_loader = (
            PROJECT_DIR / "toontown" / "town" / "TownLoader.py"
        ).read_text(encoding="utf-8")

        bank_config = json.loads(
            (PROJECT_DIR / "browser" / "audio-banks.json").read_text(
                encoding="utf-8"
            )
        )
        logical_names = {
            sound["logicalName"]
            for bank in bank_config["banks"]
            for sound in bank["sounds"]
        }
        movie_suit_attacks = (
            PROJECT_DIR / "toontown" / "battle" / "MovieSuitAttacks.py"
        ).read_text(encoding="utf-8")
        suit_attack_sounds = {
            name.lower()
            for name in re.findall(
                r"""['"]([^'"]+\.ogg)['"]""",
                movie_suit_attacks,
            )
        }
        self.assertTrue(
            suit_attack_sounds.issubset(logical_names),
            suit_attack_sounds - logical_names,
        )
        self.assertIn("sa_pick_pocket.ogg", logical_names)
        self.assertIn("enc_win.ogg", logical_names)
        self.assertEqual(len(logical_names), 47)
        self.assertNotIn("warmBrowserStarterBattleSounds", battle_sounds)
        self.assertNotIn("warmBrowserStarterBattleSounds()", town_loader)

        browser_game = (
            PROJECT_DIR / "browser" / "client" / "browser_game.py"
        ).read_text(encoding="utf-8")
        self.assertIn("browser_audio.get_sound(name)", browser_game)
        self.assertIn("lookupStatus = 'web_audio'", browser_game)
        self.assertIn("_browser_battle_sound_refs = OrderedDict()", browser_game)
        self.assertIn("_BROWSER_BATTLE_SOUND_REF_LIMIT = 32", browser_game)
        self.assertIn("lookupStatus = 'retained'", browser_game)
        self.assertIn("popitem(last=False)", browser_game)

        movie = (
            PROJECT_DIR / "toontown" / "battle" / "Movie.py"
        ).read_text(encoding="utf-8")
        self.assertIn("acquire_battle_lease", movie)
        self.assertIn("release_battle_lease", movie)
        self.assertIn("_finishBrowserBattleMovie", movie)


if __name__ == "__main__":
    unittest.main()
