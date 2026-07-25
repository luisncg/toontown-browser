import unittest

from toontown.launcher.BrowserStreamingPolicy import (
    startBackgroundDownloadsForToon,
)


class _Toon:
    def __init__(self, tutorialAck):
        self.tutorialAck = tutorialAck


class _Launcher:
    def __init__(self, browser=True):
        self.browser = browser
        self.starts = 0

    def isBrowserStreaming(self):
        return self.browser

    def startBackgroundDownloads(self):
        self.starts += 1
        return True


class BrowserStreamingPolicyTests(unittest.TestCase):
    def test_new_toon_does_not_start_optional_downloads(self):
        launcher = _Launcher()
        self.assertFalse(startBackgroundDownloadsForToon(launcher, _Toon(0)))
        self.assertEqual(launcher.starts, 0)

    def test_acknowledged_toon_starts_optional_downloads(self):
        launcher = _Launcher()
        self.assertTrue(startBackgroundDownloadsForToon(launcher, _Toon(1)))
        self.assertEqual(launcher.starts, 1)

    def test_native_launcher_is_untouched(self):
        launcher = _Launcher(browser=False)
        self.assertFalse(startBackgroundDownloadsForToon(launcher, _Toon(1)))
        self.assertEqual(launcher.starts, 0)


if __name__ == '__main__':
    unittest.main()
