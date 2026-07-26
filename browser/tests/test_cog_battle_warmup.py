import ast
import re
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
BROWSER_GAME = PROJECT_DIR / "browser" / "client" / "browser_game.py"
BATTLE_PARTICLES = PROJECT_DIR / "toontown" / "battle" / "BattleParticles.py"
MOVIE_SUIT_ATTACKS = (
    PROJECT_DIR / "toontown" / "battle" / "MovieSuitAttacks.py"
)
PHASE_5_PARTICLES = PROJECT_DIR / "resources" / "phase_5" / "etc"


def assigned_literal(source, name):
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        return ast.literal_eval(node.value)
    raise AssertionError(f"{name} was not found")


class CogBattleWarmupTests(unittest.TestCase):
    def test_all_phase_5_cog_attack_particle_configs_are_warmed(self):
        browser_game = BROWSER_GAME.read_text(encoding="utf-8")
        battle_particles = BATTLE_PARTICLES.read_text(encoding="utf-8")
        movie = MOVIE_SUIT_ATTACKS.read_text(encoding="utf-8")
        warmup = set(
            assigned_literal(browser_game, "_BROWSER_COG_PARTICLE_WARMUP")
        )
        phase_5 = {path.name for path in PHASE_5_PARTICLES.glob("*.ptf")}

        direct_files = {
            f"{name}.ptf"
            for name in re.findall(
                r"""createParticleEffect\(file=['"]([^'"]+)""",
                movie,
            )
        }
        named_calls = set(
            re.findall(
                r"""createParticleEffect\(['"]([^'"]+)['"]""",
                movie,
            )
        )
        named_mapping = dict(
            re.findall(
                r"""(?:if|elif) name == ['"]([^'"]+)['"]:\n"""
                r"""\s+return loadParticleFile\(['"]([^'"]+)['"]\)""",
                battle_particles,
            )
        )
        named_files = {
            named_mapping[name]
            for name in named_calls
            if name in named_mapping
        }
        # These two named effects delegate through private builders.
        named_files.update(("demotionUnFreeze.ptf", "pixieDrop.ptf"))
        required = (direct_files | named_files) & phase_5

        self.assertTrue(required.issubset(warmup), required - warmup)
        self.assertEqual(
            assigned_literal(
                browser_game,
                "_BROWSER_COG_PARTICLE_WARMUP",
            )[0],
            "fingerwag.ptf",
        )

    def test_warmup_is_bounded_and_preserves_the_shared_atlas(self):
        browser_game = BROWSER_GAME.read_text(encoding="utf-8")
        animations = assigned_literal(
            browser_game,
            "_BROWSER_COG_ANIMATION_WARMUP",
        )

        self.assertEqual(len(animations), 3)
        self.assertTrue(all("finger" in path for path in animations))
        self.assertIn(
            "if not builtins.launcher.getPhaseComplete(5):",
            browser_game,
        )
        self.assertIn(
            "return localAvatar is None or not "
            "getattr(localAvatar, 'battleId', 0)",
            browser_game,
        )
        self.assertIn(
            "BattleParticles.unloadParticles = "
            "_preserve_browser_battle_particles",
            browser_game,
        )
        self.assertIn(
            "_browser_particle_config_code[token] = compile(",
            browser_game,
        )
        self.assertIn(
            "'/resources/phase_5/etc/' + name",
            browser_game,
        )
        self.assertIn(
            "effect.loadConfig(Filename(indexedPath))",
            browser_game,
        )
        self.assertIn(
            "[BrowserPerformanceBattleParticle]",
            browser_game,
        )


if __name__ == "__main__":
    unittest.main()
