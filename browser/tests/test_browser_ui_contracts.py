import ast
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


class BrowserUiContractTests(unittest.TestCase):
    def test_browser_enables_exact_district_population(self):
        browser_game = (
            PROJECT_DIR / 'browser' / 'client' / 'browser_game.py'
        ).read_text(encoding='utf-8')
        shard_page = (
            PROJECT_DIR / 'toontown' / 'shtiker' / 'ShardPage.py'
        ).read_text(encoding='utf-8')

        self.assertIn('show-total-population true', browser_game)
        self.assertIn("popText = str(shardPop)", shard_page)
        self.assertIn("buttonTuple[1]['text'] = str(pop)", shard_page)

    def test_clarabelle_news_button_uses_uncropped_height(self):
        path = PROJECT_DIR / 'toontown' / 'toon' / 'LocalToon.py'
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        z_position = None
        for statement in tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and
                target.id == 'ClaraBaseZPos'
                for target in statement.targets
            ):
                z_position = ast.literal_eval(statement.value)
                break

        self.assertEqual(z_position, 0.37)
        self.assertGreaterEqual(
            source.count('(claraXPos - 0.1, 1.0, ClaraBaseZPos)'),
            2,
        )
        self.assertNotIn('(claraXPos - 0.1, 1.0, 0.45)', source)


if __name__ == '__main__':
    unittest.main()
