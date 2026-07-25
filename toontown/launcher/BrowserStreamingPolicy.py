"""Small, engine-independent policy for browser background asset loading."""


def startBackgroundDownloadsForToon(launcher, toon):
    """Start optional downloads only after this Toon's tutorial is done."""
    if not launcher or not toon or not getattr(toon, 'tutorialAck', 0):
        return False
    if (not hasattr(launcher, 'isBrowserStreaming')
            or not launcher.isBrowserStreaming()):
        return False
    return bool(launcher.startBackgroundDownloads())
