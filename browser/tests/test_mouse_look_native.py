"""Exercise experimental mouse-steering contracts in the native runtime."""

import builtins
from types import SimpleNamespace

from panda3d.core import load_prc_file_data


load_prc_file_data(
    '',
    'window-type none\ndefault-directnotify-level warning',
)
builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.showbase.ShowBase import ShowBase  # noqa: E402


base = ShowBase(windowType='none')

from otp.avatar import LocalAvatar  # noqa: E402


movementEvents = []
movementListener = SimpleNamespace()
base.messenger.accept(
    'avatarMoving', movementListener, lambda: movementEvents.append('moving')
)

avatar = SimpleNamespace(
    heading=12.0,
    experimentalMouseLookSensitivity=0.16,
)
avatar.getH = lambda: avatar.heading
avatar.setH = lambda heading: setattr(avatar, 'heading', heading)

LocalAvatar.LocalAvatar.applyExperimentalMouseLookDelta(avatar, 100)
assert abs(avatar.heading - (-4.0)) < 1e-06
assert movementEvents == ['moving']

LocalAvatar.LocalAvatar.applyExperimentalMouseLookDelta(avatar, -50)
assert abs(avatar.heading - 4.0) < 1e-06
assert movementEvents == ['moving', 'moving']

LocalAvatar.LocalAvatar.applyExperimentalMouseLookDelta(avatar, 0)
assert abs(avatar.heading - 4.0) < 1e-06
assert movementEvents == ['moving', 'moving']

controls = SimpleNamespace(currentControlsName='walk')
avatar.experimentalMouseLookEnabled = True
avatar.avatarControlsEnabled = 1
avatar.controlManager = controls
assert LocalAvatar.LocalAvatar.isExperimentalMouseLookAvailable(avatar)
controls.currentControlsName = 'swim'
assert not LocalAvatar.LocalAvatar.isExperimentalMouseLookAvailable(avatar)
controls.currentControlsName = 'walk'
avatar.avatarControlsEnabled = 0
assert not LocalAvatar.LocalAvatar.isExperimentalMouseLookAvailable(avatar)
avatar.avatarControlsEnabled = 1
avatar.experimentalMouseLookEnabled = False
assert not LocalAvatar.LocalAvatar.isExperimentalMouseLookAvailable(avatar)

avatar.experimentalMouseLookEnabled = True
avatar.isExperimentalMouseLookAvailable = lambda: True
avatar.isExperimentalMouseLookPointerLocked = lambda: False
mouseSuppressFlags = SimpleNamespace(value=0)
hoverRegion = SimpleNamespace(
    getSuppressFlags=lambda: mouseSuppressFlags.value,
)
mouseWatcher = SimpleNamespace(
    hasMouse=lambda: True,
    getOverRegion=lambda: hoverRegion,
)
originalMouseWatcher = base.mouseWatcherNode
base.mouseWatcherNode = mouseWatcher
assert LocalAvatar.LocalAvatar.isExperimentalMouseLookCaptureAllowed(avatar)
mouseSuppressFlags.value = LocalAvatar.MouseWatcherRegion.SFMouseButton
assert not LocalAvatar.LocalAvatar.isExperimentalMouseLookCaptureAllowed(avatar)
avatar.isExperimentalMouseLookPointerLocked = lambda: True
assert LocalAvatar.LocalAvatar.isExperimentalMouseLookCaptureAllowed(avatar)
base.mouseWatcherNode = originalMouseWatcher

lockedWindow = SimpleNamespace(
    getProperties=lambda: SimpleNamespace(
        getMouseMode=lambda: LocalAvatar.WindowProperties.M_relative
    )
)
originalWindow = base.win
base.win = lockedWindow
assert LocalAvatar.LocalAvatar.isExperimentalMouseLookPointerLocked(avatar)
base.win = originalWindow

base.destroy()
print({
    'sensitivity_degrees_per_pixel': 0.16,
    'right_100px_heading': -4.0,
    'left_50px_heading': 4.0,
    'walk_only': True,
    'direct_gui_capture_blocked': True,
})
