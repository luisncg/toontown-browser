from panda3d.core import *
from toontown.toonbase import ToontownGlobals
from . import AvatarChoice
from direct.fsm import StateData
from direct.fsm import ClassicFSM, State
from direct.fsm import State
from toontown.launcher import DownloadForceAcknowledge
from direct.gui.DirectGui import *
from panda3d.core import *
from toontown.toonbase import TTLocalizer
from toontown.toonbase import DisplayOptions
from direct.directnotify import DirectNotifyGlobal
from direct.interval.IntervalGlobal import *
from direct.task.Task import Task
from direct.task.TaskManagerGlobal import taskMgr
from toontown.toon import ToonDNA
from toontown.toon import Toon
import random
MAX_AVATARS = 6
POSITIONS = (Vec3(-0.840167, 0, 0.359333),
 Vec3(0.00933349, 0, 0.306533),
 Vec3(0.862, 0, 0.3293),
 Vec3(-0.863554, 0, -0.445659),
 Vec3(0.00999999, 0, -0.5181),
 Vec3(0.864907, 0, -0.445659))
COLORS = (Vec4(0.917, 0.164, 0.164, 1),
 Vec4(0.152, 0.75, 0.258, 1),
 Vec4(0.598, 0.402, 0.875, 1),
 Vec4(0.133, 0.59, 0.977, 1),
 Vec4(0.895, 0.348, 0.602, 1),
 Vec4(0.977, 0.816, 0.133, 1))
MAKE_A_TOON_PRELOAD_MODELS = (
 'phase_3/models/gui/create_a_toon',
 'phase_3/models/gui/create_a_toon_gui',
 'phase_3/models/gui/quit_button',
 'phase_3/models/gui/tt_m_gui_mat_mainGui',
 'phase_3/models/gui/tt_m_gui_mat_nameShop',
 'phase_3/models/gui/tt_m_gui_ups_mainGui',
 'phase_3/models/makeatoon/roomAnim_model',
 'phase_3/models/makeatoon/roomAnim_propSquish',
 'phase_3/models/makeatoon/roomAnim_roomDrop',
 'phase_3/models/makeatoon/roomAnim_roomSquish',
 'phase_3/models/makeatoon/roomAnim_spotlightShake',
 'phase_3/models/makeatoon/tt_m_ara_mat_room',
 'phase_3/models/makeatoon/tt_m_ara_mat_smoke',
 'phase_3/models/props/chatbox_input')
MAKE_A_TOON_PRELOAD_SOUNDS = (
 'phase_3/audio/bgm/create_a_toon.ogg',
 'phase_3/audio/sfx/GUI_create_toon_back.ogg',
 'phase_3/audio/sfx/tt_s_ara_mat_crash_boing.ogg',
 'phase_3/audio/sfx/tt_s_ara_mat_crash_glassBoing.ogg',
 'phase_3/audio/sfx/tt_s_ara_mat_crash_wood.ogg',
 'phase_3/audio/sfx/tt_s_ara_mat_crash_woodBoing.ogg',
 'phase_3/audio/sfx/tt_s_ara_mat_crash_woodGlass.ogg')
chooser_notify = DirectNotifyGlobal.directNotify.newCategory('AvatarChooser')

class AvatarChooser(StateData.StateData):

    def __init__(self, avatarList, parentFSM, doneEvent):
        StateData.StateData.__init__(self, doneEvent)
        self.choice = None
        self.avatarList = avatarList
        self.eagerMakeAToonAvatarPreload = len(avatarList) == 0
        self.displayOptions = None
        self.makeAToonPending = False
        self.makeAToonPreloadTaskName = (
            'make-a-toon-preload-%s' % id(self))
        self.fsm = ClassicFSM.ClassicFSM('AvatarChooser', [State.State('Choose', self.enterChoose, self.exitChoose, ['CheckDownload']), State.State('CheckDownload', self.enterCheckDownload, self.exitCheckDownload, ['Choose'])], 'Choose', 'Choose')
        self.fsm.enterInitialState()
        self.parentFSM = parentFSM
        self.parentFSM.getCurrentState().addChild(self.fsm)
        return

    def enter(self):
        self.notify.info('AvatarChooser.enter')
        if not self.displayOptions:
            self.displayOptions = DisplayOptions.DisplayOptions()
        self.notify.info('calling self.displayOptions.restrictToEmbedded(False)')
        if base.appRunner:
            self.displayOptions.loadFromSettings()
            self.displayOptions.restrictToEmbedded(False)
        if self.isLoaded == 0:
            self.load()
        base.disableMouse()
        self.title.reparentTo(aspect2d)
        if base.cr.loginInterface.supportsRelogin():
            self.logoutButton.show()
        self.pickAToonBG.reparentTo(base.camera)
        choice = base.config.GetInt('auto-avatar-choice', -1)
        for panel in self.panelList:
            panel.show()
            self.accept(panel.doneEvent, self.__handlePanelDone)
            if panel.position == choice and panel.mode == AvatarChoice.AvatarChoice.MODE_CHOOSE:
                self.__handlePanelDone('chose', panelChoice=choice)
        if any(panel.mode == AvatarChoice.AvatarChoice.MODE_CREATE
               for panel in self.panelList):
            self.__startMakeAToonPreload()

    def exit(self):
        if self.isLoaded == 0:
            return None
        for panel in self.panelList:
            panel.hide()

        self.ignoreAll()
        self.title.reparentTo(hidden)
        self.quitButton.hide()
        self.logoutButton.hide()
        self.pickAToonBG.reparentTo(hidden)
        return None

    def load(self, isPaid):
        if self.isLoaded == 1:
            return None
        self.isPaid = isPaid
        gui = loader.loadModel('phase_3/models/gui/pick_a_toon_gui')
        gui2 = loader.loadModel('phase_3/models/gui/quit_button')
        newGui = loader.loadModel('phase_3/models/gui/tt_m_gui_pat_mainGui')
        self.pickAToonBG = newGui.find('**/tt_t_gui_pat_background')
        self.pickAToonBG.reparentTo(hidden)
        self.pickAToonBG.setPos(0.0, 2.73, 0.0)
        self.pickAToonBG.setScale(1, 1, 1)
        self.title = OnscreenText(TTLocalizer.AvatarChooserPickAToon, scale=TTLocalizer.ACtitle, parent=hidden, font=ToontownGlobals.getSignFont(), fg=(1, 0.9, 0.1, 1), pos=(0.0, 0.82))
        quitHover = gui.find('**/QuitBtn_RLVR')
        self.quitButton = DirectButton(image=(quitHover, quitHover, quitHover), relief=None, text=TTLocalizer.AvatarChooserQuit, text_font=ToontownGlobals.getSignFont(), text_fg=(0.977, 0.816, 0.133, 1), text_pos=TTLocalizer.ACquitButtonPos, text_scale=TTLocalizer.ACquitButton, image_scale=1, image1_scale=1.05, image2_scale=1.05, scale=1.05, pos=(1.08, 0, -0.907), command=self.__handleQuit)
        self.quitButton.hide()
        self.logoutButton = DirectButton(relief=None, image=(quitHover, quitHover, quitHover), text=TTLocalizer.OptionsPageLogout, text_font=ToontownGlobals.getSignFont(), text_fg=(0.977, 0.816, 0.133, 1), text_scale=TTLocalizer.AClogoutButton, text_pos=(0, -0.035), pos=(-1.17, 0, -0.914), image_scale=1.15, image1_scale=1.15, image2_scale=1.18, scale=0.5, command=self.__handleLogoutWithoutConfirm)
        self.logoutButton.hide()
        gui.removeNode()
        gui2.removeNode()
        newGui.removeNode()
        self.panelList = []
        used_position_indexs = []
        for av in self.avatarList:
            if base.cr.isPaid():
                okToLockout = 0
            else:
                okToLockout = 1
                if av.position in AvatarChoice.AvatarChoice.OLD_TRIALER_OPEN_POS:
                    okToLockout = 0
            panel = AvatarChoice.AvatarChoice(av, position=av.position, paid=isPaid, okToLockout=okToLockout)
            panel.setPos(POSITIONS[av.position])
            used_position_indexs.append(av.position)
            self.panelList.append(panel)

        for panelNum in range(0, MAX_AVATARS):
            if panelNum not in used_position_indexs:
                panel = AvatarChoice.AvatarChoice(position=panelNum, paid=isPaid)
                panel.setPos(POSITIONS[panelNum])
                self.panelList.append(panel)

        if len(self.avatarList) > 0:
            self.initLookAtInfo()
        self.isLoaded = 1

    def getLookAtPosition(self, toonHead, toonidx):
        lookAtChoice = random.random()
        if len(self.used_panel_indexs) == 1:
            lookFwdPercent = 0.33
            lookAtOthersPercent = 0
        else:
            lookFwdPercent = 0.2
            if len(self.used_panel_indexs) == 2:
                lookAtOthersPercent = 0.4
            else:
                lookAtOthersPercent = 0.65
        lookRandomPercent = 1.0 - lookFwdPercent - lookAtOthersPercent
        if lookAtChoice < lookFwdPercent:
            self.IsLookingAt[toonidx] = 'f'
            return Vec3(0, 1.5, 0)
        elif lookAtChoice < lookRandomPercent + lookFwdPercent or len(self.used_panel_indexs) == 1:
            self.IsLookingAt[toonidx] = 'r'
            return toonHead.getRandomForwardLookAtPoint()
        else:
            other_toon_idxs = []
            for i in range(len(self.IsLookingAt)):
                if self.IsLookingAt[i] == toonidx:
                    other_toon_idxs.append(i)

            if len(other_toon_idxs) == 1:
                IgnoreStarersPercent = 0.4
            else:
                IgnoreStarersPercent = 0.2
            NoticeStarersPercent = 0.5
            bStareTargetTurnsToMe = 0
            if len(other_toon_idxs) == 0 or random.random() < IgnoreStarersPercent:
                other_toon_idxs = []
                for i in self.used_panel_indexs:
                    if i != toonidx:
                        other_toon_idxs.append(i)

                if random.random() < NoticeStarersPercent:
                    bStareTargetTurnsToMe = 1
            if len(other_toon_idxs) == 0:
                return toonHead.getRandomForwardLookAtPoint()
            else:
                lookingAtIdx = random.choice(other_toon_idxs)
            if bStareTargetTurnsToMe:
                self.IsLookingAt[lookingAtIdx] = toonidx
                otherToonHead = None
                for panel in self.panelList:
                    if panel.position == lookingAtIdx:
                        otherToonHead = panel.headModel

                otherToonHead.doLookAroundToStareAt(otherToonHead, self.getLookAtToPosVec(lookingAtIdx, toonidx))
            self.IsLookingAt[toonidx] = lookingAtIdx
            return self.getLookAtToPosVec(toonidx, lookingAtIdx)
        return

    def getLookAtToPosVec(self, fromIdx, toIdx):
        x = -(POSITIONS[toIdx][0] - POSITIONS[fromIdx][0])
        y = POSITIONS[toIdx][1] - POSITIONS[fromIdx][1]
        z = POSITIONS[toIdx][2] - POSITIONS[fromIdx][2]
        return Vec3(x, y, z)

    def initLookAtInfo(self):
        self.used_panel_indexs = []
        for panel in self.panelList:
            if panel.dna != None:
                self.used_panel_indexs.append(panel.position)

        if len(self.used_panel_indexs) == 0:
            return
        self.IsLookingAt = []
        for i in range(MAX_AVATARS):
            self.IsLookingAt.append('f')

        for panel in self.panelList:
            if panel.dna != None:
                panel.headModel.setLookAtPositionCallbackArgs((self, panel.headModel, panel.position))

        return

    def unload(self):
        if self.isLoaded == 0:
            return None
        taskMgr.remove(self.makeAToonPreloadTaskName)
        cache = getattr(base.cr, '_makeAToonPreloadCache', None)
        if cache and cache['state'] == 'loading':
            cache['state'] = 'idle'
        cleanupDialog('globalDialog')
        for panel in self.panelList:
            panel.destroy()

        del self.panelList
        self.title.removeNode()
        del self.title
        self.quitButton.destroy()
        del self.quitButton
        self.logoutButton.destroy()
        del self.logoutButton
        self.pickAToonBG.removeNode()
        del self.pickAToonBG
        del self.avatarList
        self.parentFSM.getCurrentState().removeChild(self.fsm)
        del self.parentFSM
        del self.fsm
        self.ignoreAll()
        self.isLoaded = 0
        ModelPool.garbageCollect()
        TexturePool.garbageCollect()
        return None

    def __handlePanelDone(self, panelDoneStatus, panelChoice = 0):
        self.doneStatus = {}
        self.doneStatus['mode'] = panelDoneStatus
        self.choice = panelChoice
        if panelDoneStatus == 'chose':
            # This is the first game-side boundary after a populated Toon slot
            # accepts the player's click.  Keep the browser marker deliberately
            # free of account, Toon, slot, and avatar identifiers.
            print('[BrowserPerformanceJourney] toon_selected')
            self.__handleChoice()
        elif panelDoneStatus == 'nameIt':
            self.__handleCreate()
        elif panelDoneStatus == 'delete':
            self.__handleDelete()
        elif panelDoneStatus == 'create':
            self.__handleCreate()

    def getChoice(self):
        return self.choice

    def __handleChoice(self):
        self.fsm.request('CheckDownload')

    def __handleCreate(self):
        if self.makeAToonPending:
            return
        self.makeAToonPending = True
        for panel in self.panelList:
            panel['state'] = DGG.DISABLED
        self.title.setText(TTLocalizer.AvatarChooserPreparingMakeAToon)
        cache = self.__getMakeAToonPreloadCache()
        if cache['state'] == 'ready':
            self.__finishMakeAToonPreload()
        else:
            self.__startMakeAToonPreload()

    def __getMakeAToonPreloadCache(self):
        cache = getattr(base.cr, '_makeAToonPreloadCache', None)
        if cache is None:
            avatarDna = {}
            avatarAssets = []
            for gender in ('m', 'f'):
                dna = ToonDNA.ToonDNA()
                dna.newToonRandom(gender=gender, stage=1)
                avatarDna[gender] = dna
                for asset in Toon.getMakeAToonAvatarPreloadAssets(dna):
                    if asset not in avatarAssets:
                        avatarAssets.append(asset)
            cache = {
                'state': 'idle',
                'remaining': (
                    [('model', path)
                     for path in MAKE_A_TOON_PRELOAD_MODELS]
                    + [('sound', path)
                       for path in MAKE_A_TOON_PRELOAD_SOUNDS]),
                'avatarAssets': avatarAssets,
                'actorsQueued': False,
                'models': [],
                'sounds': [],
                'textures': [],
                'avatarDna': avatarDna,
                'avatars': {'m': None, 'f': None},
                'errors': []}
            base.cr._makeAToonPreloadCache = cache
        return cache

    def __startMakeAToonPreload(self):
        cache = self.__getMakeAToonPreloadCache()
        if (self.eagerMakeAToonAvatarPreload
                and cache['state'] == 'idle'
                and not cache['actorsQueued']):
            self.__queueMakeAToonActors(cache)
        if cache['state'] == 'ready':
            if self.makeAToonPending:
                self.__finishMakeAToonPreload()
            return
        if cache['state'] == 'room-ready':
            if not self.makeAToonPending:
                return
            self.__queueMakeAToonActors(cache)
        elif cache['state'] == 'loading':
            return
        cache['state'] = 'loading'
        taskMgr.add(
            self.__preloadMakeAToonStep,
            self.makeAToonPreloadTaskName)

    def __preloadMakeAToonStep(self, task):
        cache = self.__getMakeAToonPreloadCache()
        if not cache['remaining']:
            if self.makeAToonPending and not cache['actorsQueued']:
                self.__queueMakeAToonActors(cache)
                return Task.cont
            if not cache['actorsQueued']:
                cache['state'] = 'room-ready'
                self.notify.info(
                    'Make-a-Toon room preload ready (%s errors).' %
                    len(cache['errors']))
                return Task.done
            cache['state'] = 'ready'
            self.notify.info(
                'Make-a-Toon preload ready (%s errors).' %
                len(cache['errors']))
            if self.makeAToonPending:
                self.__finishMakeAToonPreload()
            return Task.done
        kind, path = cache['remaining'].pop(0)
        try:
            if kind == 'model':
                cache['models'].append(loader.loadModel(path))
            elif kind == 'sound':
                cache['sounds'].append(base.loader.loadSfx(path))
            elif kind == 'texture':
                cache['textures'].append(loader.loadTexture(path))
            else:
                toon = Toon.Toon()
                toon.setDNA(cache['avatarDna'][path])
                toon.useLOD(1000)
                toon.setNameVisible(0)
                toon.loop('neutral')
                cache['avatars'][path] = toon
        except Exception as error:
            cache['errors'].append(path)
            self.notify.warning(
                'Could not preload Make-a-Toon asset %s: %s' %
                (path, error))
        return Task.cont

    def __queueMakeAToonActors(self, cache):
        if cache['actorsQueued']:
            return
        cache['actorsQueued'] = True
        cache['remaining'].extend(cache['avatarAssets'])
        cache['remaining'].extend(
            [('actor', gender) for gender in ('m', 'f')])

    def __finishMakeAToonPreload(self):
        if not self.makeAToonPending:
            return
        self.makeAToonPending = False
        self.notify.info('Entering Make-a-Toon after preloading.')
        base.transitions.fadeOut(
            finishIval=EventInterval(self.doneEvent, [self.doneStatus]))

    def __handleDelete(self):
        messenger.send(self.doneEvent, [self.doneStatus])

    def __handleQuit(self):
        cleanupDialog('globalDialog')
        self.doneStatus = {'mode': 'exit'}
        messenger.send(self.doneEvent, [self.doneStatus])

    def enterChoose(self):
        pass

    def exitChoose(self):
        pass

    def enterCheckDownload(self):
        # The preserved chooser waits for phase 4 before it reports a Toon
        # choice.  In the browser build that phase is streamed, so start the
        # playground package request here instead of waiting for the later
        # avatar-choice callback (which would otherwise deadlock).
        if (
            hasattr(launcher, 'isBrowserStreaming')
            and launcher.isBrowserStreaming()
            and not launcher.getPhaseComplete(4)
        ):
            self.downloadAck = None
            self.acceptOnce(
                'browser-playground-phases-ready',
                self.__handleBrowserPlaygroundReady)
            self.acceptOnce(
                'browser-phase-failed',
                self.__handleBrowserPlaygroundFailed)
            launcher.prepareForPlayground()
            return
        self.accept('downloadAck-response', self.__handleDownloadAck)
        self.downloadAck = DownloadForceAcknowledge.DownloadForceAcknowledge('downloadAck-response')
        self.downloadAck.enter(4)

    def exitCheckDownload(self):
        if self.downloadAck:
            self.downloadAck.exit()
        self.downloadAck = None
        self.ignore('downloadAck-response')
        self.ignore('browser-playground-phases-ready')
        self.ignore('browser-phase-failed')
        return

    def __handleBrowserPlaygroundReady(self):
        self.ignore('browser-phase-failed')
        self.__handleDownloadAck({'mode': 'complete'})

    def __handleBrowserPlaygroundFailed(self, phase):
        self.notify.warning(
            'Could not load browser playground phase %s.' % phase)
        self.ignore('browser-playground-phases-ready')
        self.fsm.request('Choose')

    def __handleDownloadAck(self, doneStatus):
        if doneStatus['mode'] == 'complete':
            base.transitions.fadeOut(finishIval=EventInterval(self.doneEvent, [self.doneStatus]))
        else:
            self.fsm.request('Choose')

    def __handleLogoutWithoutConfirm(self):
        base.cr.reconnectForAccountLogout()
