"""Exercise sprint animation and camera tuning against the native runtime."""

import builtins
from types import SimpleNamespace

from panda3d.core import Filename, get_model_path, load_prc_file_data


load_prc_file_data(
    '',
    'window-type none\ndefault-directnotify-level warning\n'
    'default-model-extension .bam',
)
get_model_path().prepend_directory(Filename.from_os_specific('resources'))

builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.showbase.ShowBase import ShowBase  # noqa: E402


base = ShowBase(windowType='none')

from otp.avatar import LocalAvatar  # noqa: E402
from toontown.toon import Toon, ToonDNA  # noqa: E402


dna = ToonDNA.ToonDNA()
dna.newToonFromProperties(
    'dss', 'ms', 'm', 'm', 2, 0, 2, 2, 1, 8, 1, 8, 1, 14)
toon = Toon.Toon()
toon.setDNA(dna)
toon.reparentTo(base.render)
base.localAvatar = toon
toon.animFSM.request('Happy')
toon.setSpeed(20.0, 0.0)
assert abs(toon.playingRate - 1.0) < 1e-06
toon.setSpeed(30.0, 0.0)
assert abs(toon.playingRate - 1.2) < 1e-06


cameraTransitions = []
avatar = SimpleNamespace(
    fov=52.0,
    sprintCameraActive=False,
    sprintCameraFovBoost=6.0,
    sprintCameraFovInTime=0.18,
    sprintCameraFovOutTime=0.24,
    isPageDown=False,
    isPageUp=False,
)
avatar.getMovementCameraFov = lambda: (
    LocalAvatar.LocalAvatar.getMovementCameraFov(avatar)
)
avatar.lerpCameraFov = lambda fov, duration: cameraTransitions.append(
    (fov, duration)
)

LocalAvatar.LocalAvatar.setSprintCameraActive(avatar, True)
assert cameraTransitions[-1] == (58.0, 0.18)
LocalAvatar.LocalAvatar.setSprintCameraActive(avatar, False)
assert cameraTransitions[-1] == (52.0, 0.24)

toon.cleanup()
base.destroy()
print({
    'movement_speed': 30.0,
    'animation_rate': 1.2,
    'sprint_fov': 58.0,
    'normal_fov': 52.0,
})
