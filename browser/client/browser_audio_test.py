"""OpenAL/Web Audio playback probe for the complete browser package."""

import builtins

from panda3d.core import AudioSound

import browser_client


manager = builtins.base.musicManager
if manager is None or not manager.isValid():
    raise RuntimeError("The browser OpenAL audio manager is not valid")

sound = manager.getSound("/resources/phase_3/audio/bgm/tt_theme.ogg")
if sound is None:
    raise RuntimeError("The browser audio test music could not be decoded")

sound.setLoop(True)
sound.setVolume(0.2)
sound.play()
reported = False


def frame():
    global reported
    browser_client.frame()
    if not reported and sound.status() == AudioSound.PLAYING:
        reported = True
        print(
            "[BrowserAudioTest] playing "
            f"manager={manager.getType().getName()} sound={sound.getName()}"
        )
