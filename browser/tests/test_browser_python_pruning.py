import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prune-browser-python.py"
SPEC = importlib.util.spec_from_file_location("prune_browser_python", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BrowserPythonPruningTests(unittest.TestCase):
    def test_prunes_roles_and_known_server_helpers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            otp = root / "otp"
            toontown = root / "toontown"
            files = {
                otp / "avatar" / "Avatar.py": "client",
                otp / "avatar" / "DistributedAvatarAI.py": "server",
                otp / "login" / "PasswordCredentialDB.py": "secret",
                toontown / "toon" / "Toon.py": "client",
                toontown / "uberdog" / "ToontownUDRepository.py": "server",
                toontown / "pets" / "PetBrain.py": "server",
            }
            for path, content in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)

            count, _size = MODULE.prune(otp, toontown)
            MODULE.verify_staging(otp, toontown)

            self.assertEqual(count, 4)
            self.assertTrue((otp / "avatar" / "Avatar.py").is_file())
            self.assertTrue((toontown / "toon" / "Toon.py").is_file())
            self.assertFalse(
                (otp / "login" / "PasswordCredentialDB.py").exists()
            )

    def test_rejects_forbidden_emscripten_index_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / "open-toontown.js"
            index.write_text(
                '"/game/toontown/ai/ToontownAIRepository.py"',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                MODULE.verify_emscripten_index(index)


if __name__ == "__main__":
    unittest.main()
