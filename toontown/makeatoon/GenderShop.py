from panda3d.core import *
from direct.fsm import StateData
from direct.gui.DirectGui import *
from toontown.toonbase import TTLocalizer
from toontown.toonbase import ToontownGlobals
from toontown.toon import ToonDNA
from toontown.toon import Toon
from .MakeAToonGlobals import *
from direct.directnotify import DirectNotifyGlobal
from direct.task.Task import Task
from direct.task.TaskManagerGlobal import taskMgr
import random
import time

class GenderShop(StateData.StateData):
    notify = DirectNotifyGlobal.directNotify.newCategory('GenderShop')

    def __init__(self, makeAToon, doneEvent):
        StateData.StateData.__init__(self, doneEvent)
        self.shopsVisited = []
        self.toon = None
        self.gender = 'm'
        self.makeAToon = makeAToon
        self.avatarPreloadTaskName = 'make-a-toon-avatar-preload-%s' % id(self)
        self.avatarPreloadTaskRunning = False
        self.avatarPreloadQueue = []
        self.avatarPreloadQueued = set()
        self.avatarPreloadFinished = set()
        self.avatarPreloadAssets = []
        self.avatarPreparations = {'m': None, 'f': None}
        self.pendingGender = None
        return

    def enter(self):
        base.disableMouse()
        self.accept('next', self.__handleForward)
        return None

    def showButtons(self):
        return None

    def exit(self):
        self.ignore('next')

    def load(self):
        gui = loader.loadModel('phase_3/models/gui/tt_m_gui_mat_mainGui')
        guiBoyUp = gui.find('**/tt_t_gui_mat_boyUp')
        guiBoyDown = gui.find('**/tt_t_gui_mat_boyDown')
        guiGirlUp = gui.find('**/tt_t_gui_mat_girlUp')
        guiGirlDown = gui.find('**/tt_t_gui_mat_girlDown')
        self.boyButton = DirectButton(relief=None, image=(guiBoyUp,
         guiBoyDown,
         guiBoyUp,
         guiBoyDown), image_scale=halfButtonScale, image1_scale=halfButtonHoverScale, image2_scale=halfButtonHoverScale, pos=(-0.4, 0, -0.8), command=self.createRandomBoy, text=('',
         TTLocalizer.GenderShopBoyButtonText,
         TTLocalizer.GenderShopBoyButtonText,
         ''), text_font=ToontownGlobals.getInterfaceFont(), text_scale=0.08, text_pos=(0, 0.19), text_fg=(1, 1, 1, 1), text_shadow=(0, 0, 0, 1))
        self.boyButton.hide()
        self.girlButton = DirectButton(relief=None, image=(guiGirlUp,
         guiGirlDown,
         guiGirlUp,
         guiGirlDown), image_scale=halfButtonScale, image1_scale=halfButtonHoverScale, image2_scale=halfButtonHoverScale, pos=(0.4, 0, -0.8), command=self.createRandomGirl, text=('',
         TTLocalizer.GenderShopGirlButtonText,
         TTLocalizer.GenderShopGirlButtonText,
         ''), text_font=ToontownGlobals.getInterfaceFont(), text_scale=0.08, text_pos=(0, 0.19), text_fg=(1, 1, 1, 1), text_shadow=(0, 0, 0, 1))
        self.girlButton.hide()
        self.preparingText = OnscreenText(
            text='',
            parent=aspect2d,
            font=ToontownGlobals.getSignFont(),
            fg=(1, 0.9, 0.1, 1),
            shadow=(0, 0, 0, 1),
            scale=0.065,
            pos=(0, -0.58))
        self.preparingText.hide()
        gui.removeNode()
        del gui
        self.toon = None
        cache = getattr(base.cr, '_makeAToonPreloadCache', None)
        for gender in ('m', 'f'):
            if (cache is not None and cache.get('state') == 'ready'
                    and cache.get('avatars', {}).get(gender) is not None):
                dna = cache['avatarDna'][gender]
                assets = tuple(Toon.getMakeAToonAvatarPreloadAssets(dna))
                self.avatarPreloadFinished.update(assets)
                self.avatarPreparations[gender] = {
                    'dna': dna,
                    'assets': assets,
                    'toon': cache['avatars'][gender],
                    'readyLogged': True}
                self.notify.info(
                    'Using Pick-a-Toon prewarmed avatar for %s.' % gender)
            else:
                self.__prepareGender(gender)
        self.__startAvatarPreload()
        return

    def unload(self):
        taskMgr.remove(self.avatarPreloadTaskName)
        self.avatarPreloadTaskRunning = False
        self.boyButton.destroy()
        self.girlButton.destroy()
        self.preparingText.removeNode()
        del self.boyButton
        del self.girlButton
        del self.preparingText
        if self.toon:
            self.toon.delete()
        self.makeAToon = None
        return

    def setGender(self, choice):
        self.__setGender(choice)

    def __setGender(self, choice):
        self.gender = 'm'
        if self.toon:
            self.gender = self.toon.style.gender
        messenger.send(self.doneEvent)

    def hideButtons(self):
        self.boyButton.hide()
        self.girlButton.hide()

    def showButtons(self):
        self.boyButton.show()
        self.girlButton.show()

    def createRandomBoy(self):
        self._createRandomToon('m')

    def createRandomGirl(self):
        self._createRandomToon('f')

    def _createRandomToon(self, gender):
        if self.pendingGender is not None:
            return
        preparation = self.avatarPreparations[gender]
        if preparation is None:
            preparation = self.__prepareGender(gender)
        if not self.__isPreparationReady(preparation):
            self.pendingGender = gender
            self.boyButton['state'] = DGG.DISABLED
            self.girlButton['state'] = DGG.DISABLED
            self.preparingText.setText(TTLocalizer.GenderShopPreparingToon)
            self.preparingText.show()
            self.__prioritizePreparation(preparation)
            self.__startAvatarPreload()
            return
        self.__createPreparedToon(gender)

    def __createPreparedToon(self, gender):
        preparation = self.avatarPreparations[gender]
        if preparation is None or not self.__isPreparationReady(preparation):
            return
        started = time.perf_counter()
        if self.toon:
            self.toon.stopBlink()
            self.toon.stopLookAroundNow()
            self.toon.delete()
        self.dna = preparation['dna']
        self.avatarPreparations[gender] = None
        self.toon = preparation.get('toon')
        if self.toon is None:
            self.toon = Toon.Toon()
            self.toon.setDNA(self.dna)
        else:
            cache = getattr(base.cr, '_makeAToonPreloadCache', None)
            if cache is not None:
                cache['avatars'][gender] = None
        self.toon.useLOD(1000)
        self.toon.setNameVisible(0)
        self.toon.startBlink()
        self.toon.startLookAround()
        self.toon.reparentTo(render)
        self.toon.setPos(self.makeAToon.toonPosition)
        self.toon.setHpr(self.makeAToon.toonHpr)
        self.toon.setScale(self.makeAToon.toonScale)
        self.toon.loop('neutral')
        self.makeAToon.setNextButtonState(DGG.NORMAL)
        self.makeAToon.setToon(self.toon)
        messenger.send('MAT-newToonCreated')
        elapsed = (time.perf_counter() - started) * 1000.0
        self.notify.info(
            'Created prewarmed %s Toon in %.1f ms.' % (gender, elapsed))
        self.pendingGender = None
        self.boyButton['state'] = DGG.NORMAL
        self.girlButton['state'] = DGG.NORMAL
        self.preparingText.hide()

    def __prepareGender(self, gender):
        dna = ToonDNA.ToonDNA()
        dna.newToonRandom(gender=gender, stage=1)
        preparation = {
            'dna': dna,
            'assets': tuple(Toon.getMakeAToonAvatarPreloadAssets(dna)),
            'readyLogged': False}
        self.avatarPreparations[gender] = preparation
        for asset in preparation['assets']:
            if asset in self.avatarPreloadFinished:
                continue
            if asset not in self.avatarPreloadQueued:
                self.avatarPreloadQueue.append(asset)
                self.avatarPreloadQueued.add(asset)
        return preparation

    def __isPreparationReady(self, preparation):
        return all(asset in self.avatarPreloadFinished
                   for asset in preparation['assets'])

    def __prioritizePreparation(self, preparation):
        required = set(preparation['assets'])
        self.avatarPreloadQueue.sort(
            key=lambda asset: 0 if asset in required else 1)

    def __startAvatarPreload(self):
        if self.avatarPreloadTaskRunning or not self.avatarPreloadQueue:
            return
        self.avatarPreloadTaskRunning = True
        taskMgr.add(self.__avatarPreloadStep, self.avatarPreloadTaskName)

    def __avatarPreloadStep(self, task):
        if not self.avatarPreloadQueue:
            self.avatarPreloadTaskRunning = False
            return Task.done
        kind, path = self.avatarPreloadQueue.pop(0)
        asset = (kind, path)
        self.avatarPreloadQueued.discard(asset)
        try:
            if kind == 'model':
                self.avatarPreloadAssets.append(loader.loadModel(path))
            else:
                self.avatarPreloadAssets.append(loader.loadTexture(path))
        except Exception as error:
            self.notify.warning(
                'Could not prewarm Toon asset %s: %s' % (path, error))
        self.avatarPreloadFinished.add(asset)

        for gender, preparation in self.avatarPreparations.items():
            if (preparation is not None
                    and not preparation['readyLogged']
                    and self.__isPreparationReady(preparation)):
                preparation['readyLogged'] = True
                self.notify.info(
                    'Make-a-Toon avatar prewarm ready for %s.' % gender)

        if self.pendingGender is not None:
            preparation = self.avatarPreparations[self.pendingGender]
            if self.__isPreparationReady(preparation):
                gender = self.pendingGender
                self.__createPreparedToon(gender)
        return Task.cont

    def __handleForward(self):
        self.doneStatus = 'next'
        messenger.send(self.doneEvent)
