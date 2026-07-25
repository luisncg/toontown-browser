import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prune-browser-dc.py"
SPEC = importlib.util.spec_from_file_location("prune_browser_dc", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BrowserDcPruningTests(unittest.TestCase):
    def test_removes_explicit_server_imports_but_keeps_suffix_mappings(self):
        contents = (
            "from toontown.toon import DistributedToon/AI/UD\n"
            "from toontown.distributed.NonRepeatableRandomSourceAI "
            "import NonRepeatableRandomSourceAI\n"
            "from toontown.distributed.NonRepeatableRandomSourceUD "
            "import NonRepeatableRandomSourceUD\n"
            "from toontown.ai import NewsManager/AI\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "toon.dc"
            path.write_text(contents)
            self.assertEqual(MODULE.prune_file(path), 2)
            MODULE.verify_file(path)
            result = path.read_text()
            self.assertIn("DistributedToon/AI/UD", result)
            self.assertIn("NewsManager/AI", result)
            self.assertNotIn("NonRepeatableRandomSourceAI import", result)
            self.assertNotIn("NonRepeatableRandomSourceUD import", result)


if __name__ == "__main__":
    unittest.main()
