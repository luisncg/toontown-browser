"""Exercise free-camera POV math against the native Panda3D runtime."""

import builtins

from panda3d.core import NodePath, PerspectiveLens, load_prc_file_data


load_prc_file_data('', 'window-type none\ndefault-directnotify-level warning')
builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.showbase.ShowBase import ShowBase  # noqa: E402


base = ShowBase(windowType='none')
base.camera = NodePath('camera')
base.cam = base.camera
base.camLens = PerspectiveLens()
builtins.camera = base.camera

from toontown.toon import FreeCamera  # noqa: E402


class TestAvatar(NodePath):
    def getZoneId(self):
        return 2200


avatar = TestAvatar('avatar')
avatar.reparentTo(base.render)
avatar.setPosHpr(10, 20, 3, 30, 0, 0)

manager = FreeCamera.FreeCamera.__new__(FreeCamera.FreeCamera)
manager.avatar = avatar
manager.active = True

base.camera.reparentTo(base.render)
base.camera.setPosHpr(14, 11, 8, -25, 12, 0)
base.camLens.setFov(61)

data = manager.getPovData()
payload = manager.getPovPayload()
assert data['zone'] == 2200
assert tuple(round(value, 3) for value in data['worldPos']) == (14.0, 11.0, 8.0)
assert tuple(round(value, 3) for value in data['worldHpr']) == (-25.0, 12.0, 0.0)
assert 'TOONTOWN_POV zone=2200' in payload
assert 'worldPos=(14.000,11.000,8.000)' in payload
assert 'toonPos=' in payload
assert 'lookAt10=' in payload
assert 'hfov=61.000' in payload

oldHpr = base.camera.getHpr(base.render)
manager.applyMouseDelta(100, -50)
newHpr = base.camera.getHpr(base.render)
assert abs(newHpr[0] - (oldHpr[0] - 14.0)) < 1e-5
assert abs(newHpr[1] - (oldHpr[1] + 7.0)) < 1e-5

avatar.removeNode()
base.destroy()
print({
    'zone': data['zone'],
    'worldPos': tuple(data['worldPos']),
    'mouseHeadingDelta': -14.0,
    'mousePitchDelta': 7.0,
    'payload': payload,
})
