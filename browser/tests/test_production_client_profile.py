import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIGURE = (
    PROJECT_DIR / "browser" / "scripts" / "configure-browser-profile.py"
)
VERIFY = (
    PROJECT_DIR / "browser" / "scripts" / "verify-production-client.py"
)
WEB_SOURCE = PROJECT_DIR / "browser" / "web"
CLIENT_SOURCE = PROJECT_DIR / "browser" / "client" / "browser_game.py"
DIRECT_SOURCE = (
    PROJECT_DIR
    / ".toolchain"
    / "build"
    / "panda3d-emscripten"
    / "direct"
    / "distributed"
    / "ConnectionRepository.py"
)
LOCAL_ENDPOINT = "ws://127.0.0.1:7200/astron"


class ProductionClientProfileTests(unittest.TestCase):
    def make_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        web = root / "dist-web"
        client = root / "client"
        web.mkdir()
        client.mkdir()
        for name in ("app.js", "runtime-authority.js"):
            shutil.copy2(WEB_SOURCE / name, web / name)
        shutil.copy2(CLIENT_SOURCE, client / "browser_game.py")
        direct = root / "direct"
        (direct / "distributed").mkdir(parents=True)
        shutil.copy2(
            DIRECT_SOURCE,
            direct / "distributed" / "ConnectionRepository.py",
        )
        return temporary, root, web, client, direct

    def configure(self, web, client, direct, profile):
        subprocess.run(
            [
                "python3",
                str(CONFIGURE),
                "--web-dir",
                str(web),
                "--client-dir",
                str(client),
                "--direct-dir",
                str(direct),
                "--local-astron-development",
                profile,
            ],
            check=True,
        )

    def test_release_profile_removes_local_astron_escape_hatch(self):
        temporary, _root, web, client, direct = self.make_fixture()
        with temporary:
            self.configure(web, client, direct, "disabled")
            app = (web / "app.js").read_text(encoding="utf-8")
            authority = (
                web / "runtime-authority.js"
            ).read_text(encoding="utf-8")
            browser_game = (
                client / "browser_game.py"
            ).read_text(encoding="utf-8")
            connection_repository = (
                direct / "distributed" / "ConnectionRepository.py"
            ).read_text(encoding="utf-8")

            for source in (app, authority):
                self.assertNotIn("127.0.0.1", source)
                self.assertNotIn("localhost", source)
                self.assertNotIn("::1", source)
                self.assertNotIn("isLocalDevelopmentPage", source)
                self.assertNotIn(
                    "TOONTOWN_LOCAL_ASTRON_DEVELOPMENT",
                    source,
                )
            self.assertIn(
                'signedRequest("/api/gateway/lease", {})',
                app,
            )
            self.assertIn("LOCAL_ASTRON_DEVELOPMENT = False", browser_game)
            self.assertIn('DEFAULT_BROWSER_GAME_SERVER = ""', browser_game)
            self.assertNotIn(LOCAL_ENDPOINT, browser_game)
            self.assertNotIn(LOCAL_ENDPOINT, connection_repository)

            (web / "open-toontown.data").write_bytes(
                (browser_game + connection_repository).encode("utf-8")
            )
            subprocess.run(["node", "--check", str(web / "app.js")], check=True)
            subprocess.run(
                ["node", "--check", str(web / "runtime-authority.js")],
                check=True,
            )
            subprocess.run(
                ["python3", str(VERIFY), str(web)],
                check=True,
            )

    def test_explicit_development_profile_retains_local_astron(self):
        temporary, _root, web, client, direct = self.make_fixture()
        with temporary:
            self.configure(web, client, direct, "enabled")
            app = (web / "app.js").read_text(encoding="utf-8")
            authority = (
                web / "runtime-authority.js"
            ).read_text(encoding="utf-8")
            browser_game = (
                client / "browser_game.py"
            ).read_text(encoding="utf-8")
            connection_repository = (
                direct / "distributed" / "ConnectionRepository.py"
            ).read_text(encoding="utf-8")

            self.assertIn(LOCAL_ENDPOINT, app)
            self.assertIn("isLocalDevelopmentPage", app)
            self.assertIn("isLocalDevelopmentPage", authority)
            self.assertIn("LOCAL_ASTRON_DEVELOPMENT = True", browser_game)
            self.assertIn(LOCAL_ENDPOINT, browser_game)
            self.assertIn(LOCAL_ENDPOINT, connection_repository)
            self.assertNotIn(
                "TOONTOWN_LOCAL_ASTRON_DEVELOPMENT_START",
                app,
            )

    def test_release_verifier_rejects_reintroduced_endpoint(self):
        temporary, _root, web, client, direct = self.make_fixture()
        with temporary:
            self.configure(web, client, direct, "disabled")
            browser_game = (
                client / "browser_game.py"
            ).read_text(encoding="utf-8")
            (web / "open-toontown.data").write_bytes(
                browser_game.encode("utf-8")
            )
            with (web / "app.js").open("a", encoding="utf-8") as handle:
                handle.write(f'\nconst unsafe = "{LOCAL_ENDPOINT}";\n')
            result = subprocess.run(
                ["python3", str(VERIFY), str(web)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("local Astron escape hatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
