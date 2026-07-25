"""Browser-friendly camera lab for authoring reproducible gameplay POVs."""

from direct.gui.DirectGui import DirectFrame, DirectLabel
from direct.showbase.DirectObject import DirectObject
from direct.task import Task
from panda3d.core import Point3, TextNode, Vec3, Vec4

from toontown.toonbase import KeybindSettings

try:
    import browser_storage
except ImportError:
    browser_storage = None


class FreeCamera(DirectObject):
    ActiveStorageKey = 'open-toontown.free-camera-active'
    PayloadStorageKey = 'open-toontown.free-camera-pov'
    CopyStatusStorageKey = 'open-toontown.free-camera-copy-status'

    MoveSpeed = 18.0
    BoostMultiplier = 3.0
    KeyboardLookSpeed = 75.0
    MouseSensitivity = 0.14
    MinimumFov = 20.0
    MaximumFov = 100.0
    FovStep = 2.0

    MovementBindings = {
        'w': 'forward',
        's': 'backward',
        'a': 'left',
        'd': 'right',
        'q': 'down',
        'e': 'up',
        'shift': 'boost',
        'arrow_left': 'lookLeft',
        'arrow_right': 'lookRight',
        'arrow_up': 'lookUp',
        'arrow_down': 'lookDown',
    }

    def __init__(self, avatar):
        DirectObject.__init__(self)
        self.avatar = avatar
        self.active = False
        self.hud = None
        self.hudText = None
        self.crosshair = None
        self.inputs = {}
        self.savedSmartCamera = False
        self.savedControls = False
        self.startWorldPos = Point3(0)
        self.startWorldHpr = Vec3(0)
        self.startFov = 52.0
        self.lastHudUpdate = -1.0
        self.lastCopyStatus = ''
        self._publishBrowserState(False)

    def toggle(self):
        if self.active:
            self.exit()
        else:
            self.enter()

    def canEnter(self):
        return bool(
            self.avatar.avatarControlsEnabled
            and self.avatar.controlManager.currentControlsName == 'walk'
            and self.avatar._smartCamEnabled
        )

    def enter(self):
        if self.active:
            return True
        if not self.canEnter():
            print(
                '[FreeCamera] Shift+F8 is available during normal walk gameplay.'
            )
            return False

        self.avatar.wakeUp()
        self.avatar.setSprintCameraActive(False, immediate=True)
        if self.avatar.posCameraSeq:
            self.avatar.posCameraSeq.finish()
            self.avatar.posCameraSeq = None

        self.savedSmartCamera = bool(self.avatar._smartCamEnabled)
        self.savedControls = bool(self.avatar.avatarControlsEnabled)
        self.startWorldPos = Point3(camera.getPos(render))
        self.startWorldHpr = Vec3(camera.getHpr(render))
        self.startFov = float(base.camLens.getHfov())

        self.active = True
        KeybindSettings.setFreeCameraInputActive(True)
        try:
            self.avatar.chatMgr.fsm.request('mainMenu')
        except (AttributeError, TypeError):
            pass

        self.avatar.controlManager.disable()
        if self.avatar._smartCamEnabled:
            self.avatar.stopUpdateSmartCamera()
        camera.wrtReparentTo(render)
        base.disableMouse()

        self._bindInputs()
        self._createHud()
        self._publishBrowserState(True)
        self.avatar.refreshExperimentalMouseLook()
        taskMgr.add(
            self._update,
            self.avatar.taskName('freeCamera'),
            priority=46,
        )
        print('[FreeCamera] Camera lab enabled. Press Shift+F8 to exit.')
        return True

    def exit(self):
        if not self.active:
            return

        self.active = False
        taskMgr.remove(self.avatar.taskName('freeCamera'))
        self._unbindInputs()
        self._destroyHud()
        KeybindSettings.setFreeCameraInputActive(False)
        self._publishBrowserState(False)
        self.avatar.releaseExperimentalMouseLookPointer()

        base.camLens.setFov(self.avatar.getMovementCameraFov())
        camera.reparentTo(self.avatar)
        base.enableMouse()
        base.setMouseOnNode(self.avatar.node())
        self.avatar.ignoreMouse = not self.avatar.wantMouse

        if self.savedSmartCamera and not self.avatar._smartCamEnabled:
            shouldPush = 1
            if self.avatar.cameraPositions:
                shouldPush = not self.avatar.cameraPositions[
                    self.avatar.cameraIndex
                ][4]
            self.avatar.startUpdateSmartCamera(shouldPush)
        if self.savedControls and self.avatar.avatarControlsEnabled:
            self.avatar.controlManager.enable()
        self.avatar.refreshExperimentalMouseLook()
        print('[FreeCamera] Camera lab disabled.')

    def destroy(self):
        if self.active:
            self.exit()
        self.ignoreAll()
        self._destroyHud()
        KeybindSettings.setFreeCameraInputActive(False)
        self._publishBrowserState(False)
        self.avatar = None

    def _bindInputs(self):
        self.inputs = {
            action: False for action in self.MovementBindings.values()
        }
        for event, action in self.MovementBindings.items():
            self.accept(event, self._setInput, [action, True])
            self.accept(event + '-up', self._setInput, [action, False])
        self.accept('wheel_up', self.adjustFov, [-self.FovStep])
        self.accept('wheel_down', self.adjustFov, [self.FovStep])
        self.accept('r', self.resetView)

    def _unbindInputs(self):
        for event in self.MovementBindings:
            self.ignore(event)
            self.ignore(event + '-up')
        self.ignore('wheel_up')
        self.ignore('wheel_down')
        self.ignore('r')
        self.inputs = {}

    def _setInput(self, action, pressed):
        if self.active:
            self.inputs[action] = bool(pressed)

    def _update(self, task):
        if not self.active:
            return Task.done

        dt = min(max(globalClock.getDt(), 0.0), 0.1)
        self._applyKeyboardLook(dt)
        self._applyMovement(dt)
        if self.lastHudUpdate < 0 or task.time - self.lastHudUpdate >= 0.1:
            self.lastHudUpdate = task.time
            self._refreshHud()
        return Task.cont

    def _applyMovement(self, dt):
        forwardAmount = (
            int(self.inputs.get('forward', False))
            - int(self.inputs.get('backward', False))
        )
        rightAmount = (
            int(self.inputs.get('right', False))
            - int(self.inputs.get('left', False))
        )
        verticalAmount = (
            int(self.inputs.get('up', False))
            - int(self.inputs.get('down', False))
        )
        if not (forwardAmount or rightAmount or verticalAmount):
            return

        cameraQuat = camera.getQuat(render)
        movement = (
            cameraQuat.getForward() * forwardAmount
            + cameraQuat.getRight() * rightAmount
            + Vec3(0, 0, verticalAmount)
        )
        if movement.lengthSquared() > 1.0:
            movement.normalize()
        speed = self.MoveSpeed
        if self.inputs.get('boost', False):
            speed *= self.BoostMultiplier
        camera.setPos(render, camera.getPos(render) + movement * speed * dt)

    def _applyKeyboardLook(self, dt):
        headingAmount = (
            int(self.inputs.get('lookLeft', False))
            - int(self.inputs.get('lookRight', False))
        )
        pitchAmount = (
            int(self.inputs.get('lookUp', False))
            - int(self.inputs.get('lookDown', False))
        )
        if not (headingAmount or pitchAmount):
            return
        hpr = camera.getHpr(render)
        camera.setHpr(
            render,
            hpr[0] + headingAmount * self.KeyboardLookSpeed * dt,
            max(-89.0, min(89.0,
                hpr[1] + pitchAmount * self.KeyboardLookSpeed * dt)),
            hpr[2],
        )

    def applyMouseDelta(self, deltaX, deltaY):
        if not self.active or not (deltaX or deltaY):
            return
        hpr = camera.getHpr(render)
        camera.setHpr(
            render,
            hpr[0] - deltaX * self.MouseSensitivity,
            max(-89.0, min(89.0,
                hpr[1] - deltaY * self.MouseSensitivity)),
            hpr[2],
        )

    def adjustFov(self, amount):
        if not self.active:
            return
        fov = max(
            self.MinimumFov,
            min(self.MaximumFov, base.camLens.getHfov() + amount),
        )
        base.camLens.setFov(fov)
        self._refreshHud()

    def resetView(self):
        if not self.active:
            return
        camera.setPosHpr(
            render,
            self.startWorldPos,
            self.startWorldHpr,
        )
        base.camLens.setFov(self.startFov)
        self._refreshHud()

    def getPovData(self):
        worldPos = camera.getPos(render)
        worldHpr = camera.getHpr(render)
        toonPos = camera.getPos(self.avatar)
        toonHpr = camera.getHpr(self.avatar)
        lookWorld = (
            worldPos + camera.getQuat(render).getForward() * 10.0
        )
        lookToon = self.avatar.getRelativePoint(render, lookWorld)
        return {
            'zone': int(self.avatar.getZoneId()),
            'worldPos': tuple(worldPos),
            'worldHpr': tuple(worldHpr),
            'toonPos': tuple(toonPos),
            'toonHpr': tuple(toonHpr),
            'lookToon': tuple(lookToon),
            'hfov': float(base.camLens.getHfov()),
            'vfov': float(base.camLens.getVfov()),
        }

    def getPovPayload(self):
        data = self.getPovData()
        return (
            'TOONTOWN_POV zone=%(zone)d '
            'worldPos=(%(wpx).3f,%(wpy).3f,%(wpz).3f) '
            'worldHpr=(%(wh).3f,%(wp).3f,%(wr).3f) '
            'toonPos=(%(tpx).3f,%(tpy).3f,%(tpz).3f) '
            'toonHpr=(%(th).3f,%(tp).3f,%(tr).3f) '
            'lookAt10=(%(lx).3f,%(ly).3f,%(lz).3f) '
            'hfov=%(hfov).3f vfov=%(vfov).3f'
        ) % {
            'zone': data['zone'],
            'wpx': data['worldPos'][0],
            'wpy': data['worldPos'][1],
            'wpz': data['worldPos'][2],
            'wh': data['worldHpr'][0],
            'wp': data['worldHpr'][1],
            'wr': data['worldHpr'][2],
            'tpx': data['toonPos'][0],
            'tpy': data['toonPos'][1],
            'tpz': data['toonPos'][2],
            'th': data['toonHpr'][0],
            'tp': data['toonHpr'][1],
            'tr': data['toonHpr'][2],
            'lx': data['lookToon'][0],
            'ly': data['lookToon'][1],
            'lz': data['lookToon'][2],
            'hfov': data['hfov'],
            'vfov': data['vfov'],
        }

    def _createHud(self):
        self._destroyHud()
        self.hud = DirectFrame(
            parent=base.a2dTopLeft,
            relief='flat',
            frameColor=Vec4(0.015, 0.025, 0.05, 0.88),
            frameSize=(0, 1.36, -0.64, 0),
            pos=(0.035, 0, -0.13),
            sortOrder=100,
        )
        self.hudText = DirectLabel(
            parent=self.hud,
            relief=None,
            text='',
            text_align=TextNode.ALeft,
            text_scale=0.038,
            text_fg=Vec4(0.92, 0.97, 1.0, 1.0),
            text_shadow=Vec4(0, 0, 0, 1),
            text_pos=(0.028, -0.045),
            textMayChange=1,
        )
        self.crosshair = DirectLabel(
            parent=aspect2d,
            relief=None,
            text='+',
            text_scale=0.055,
            text_fg=Vec4(1.0, 0.95, 0.25, 0.8),
            text_shadow=Vec4(0, 0, 0, 0.8),
            pos=(0, 0, -0.02),
            sortOrder=99,
        )
        self._refreshHud()

    def _destroyHud(self):
        if self.crosshair is not None:
            self.crosshair.destroy()
            self.crosshair = None
        if self.hudText is not None:
            self.hudText.destroy()
            self.hudText = None
        if self.hud is not None:
            self.hud.destroy()
            self.hud = None

    @staticmethod
    def _vectorText(vector):
        return '(%8.3f, %8.3f, %8.3f)' % tuple(vector)

    def _refreshHud(self):
        if not self.active or self.hudText is None:
            return
        data = self.getPovData()
        copyStatus = self._getBrowserCopyStatus()
        if copyStatus:
            self.lastCopyStatus = copyStatus
        copyLine = self.lastCopyStatus or 'Press C to copy this POV'
        self.hudText['text'] = '\n'.join((
            '\1yellow\1POV FREE CAMERA\2',
            'Shift+F8 exit | WASD fly | Q/E vertical | Shift boost',
            'Mouse/Arrows look  |  Wheel FOV  |  R reset  |  C copy',
            '',
            'Zone       %d' % data['zone'],
            'World Pos  %s' % self._vectorText(data['worldPos']),
            'World HPR  %s' % self._vectorText(data['worldHpr']),
            'Toon Pos   %s' % self._vectorText(data['toonPos']),
            'Toon HPR   %s' % self._vectorText(data['toonHpr']),
            'Look@10    %s' % self._vectorText(data['lookToon']),
            'FOV        H %6.2f   V %6.2f' % (
                data['hfov'], data['vfov']),
            '',
            copyLine,
        ))
        self._publishPayload(self.getPovPayload())

    def _publishBrowserState(self, active):
        if browser_storage is None:
            return
        try:
            browser_storage.set_item(
                self.ActiveStorageKey,
                '1' if active else '0',
            )
            if active:
                browser_storage.set_item(self.CopyStatusStorageKey, '')
        except RuntimeError:
            pass

    def _publishPayload(self, payload):
        if browser_storage is None:
            return
        try:
            browser_storage.set_item(self.PayloadStorageKey, payload)
        except RuntimeError:
            pass

    def _getBrowserCopyStatus(self):
        if browser_storage is None:
            return ''
        try:
            return browser_storage.get_item(self.CopyStatusStorageKey) or ''
        except RuntimeError:
            return ''
