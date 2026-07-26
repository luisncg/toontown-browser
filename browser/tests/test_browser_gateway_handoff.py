"""Regression coverage for the browser shell's Astron gateway handoff."""

import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROWSER_GAME = PROJECT_ROOT / "browser" / "client" / "browser_game.py"


def load_gateway_function():
    """Load only the gateway constants/function without starting Panda3D."""
    source = BROWSER_GAME.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BROWSER_GAME))
    selected = []
    wanted_assignments = {
        "DEFAULT_BROWSER_GAME_SERVER",
        "BROWSER_GAME_SERVER_STORAGE_KEY",
        "_BROWSER_RESUME_TOKEN_RE",
        "_BROWSER_GATEWAY_LEASE_RE",
        "_BROWSER_AUTHORITY_RE",
    }
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = {
                alias.asname or alias.name.split(".")[0]
                for alias in node.names
            }
            if imported & {"re", "parse_qs", "urlsplit"}:
                selected.append(node)
        elif isinstance(node, ast.Assign):
            targets = {
                target.id for target in node.targets
                if isinstance(target, ast.Name)
            }
            if targets & wanted_assignments:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and (
            node.name == "_get_browser_game_server"
        ):
            selected.append(node)
    namespace = {}
    exec(compile(ast.Module(selected, type_ignores=[]), str(BROWSER_GAME), "exec"),
         namespace)
    return namespace["_get_browser_game_server"]


class BrowserGatewayHandoffTests(unittest.TestCase):
    def setUp(self):
        self.get_gateway = load_gateway_function()
        self.production = (
            "wss://toontown.lui.ss/astron?"
            "resume=abcdefghijklmnopqrstuvwxyzABCDEF&"
            "lease=v1.AAAAAAAAAAAAAAAA.ciphertext.auth_tag&"
            "authority=0123456789abcdef0123456789abcdef"
        )

    def test_runtime_handoff_does_not_need_local_storage(self):
        storage = types.SimpleNamespace(
            get_runtime_game_server=lambda: self.production,
            get_item=lambda _key: (_ for _ in ()).throw(
                RuntimeError("localStorage blocked")),
        )
        with patch.dict(sys.modules, {"browser_storage": storage}):
            self.assertEqual(self.get_gateway(), self.production)

    def test_older_launcher_can_still_use_local_storage(self):
        storage = types.SimpleNamespace(
            get_item=lambda _key: self.production,
        )
        with patch.dict(sys.modules, {"browser_storage": storage}):
            self.assertEqual(self.get_gateway(), self.production)

    def test_invalid_runtime_value_falls_back_safely(self):
        storage = types.SimpleNamespace(
            get_runtime_game_server=lambda: "ws://127.0.0.1:7198",
            get_item=lambda _key: None,
        )
        with patch.dict(sys.modules, {"browser_storage": storage}):
            self.assertEqual(
                self.get_gateway(),
                "ws://127.0.0.1:7200/astron",
            )

    def test_invalid_runtime_authority_falls_back_safely(self):
        invalid = self.production.replace(
            "0123456789abcdef0123456789abcdef",
            "not-a-valid-authority",
        )
        storage = types.SimpleNamespace(
            get_runtime_game_server=lambda: invalid,
            get_item=lambda _key: None,
        )
        with patch.dict(sys.modules, {"browser_storage": storage}):
            self.assertEqual(
                self.get_gateway(),
                "ws://127.0.0.1:7200/astron",
            )


if __name__ == "__main__":
    unittest.main()
