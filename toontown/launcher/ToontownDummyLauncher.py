import sys

from direct.directnotify import DirectNotifyGlobal
from direct.showbase.MessengerGlobal import messenger
from direct.task.Task import Task
from direct.task.TaskManagerGlobal import taskMgr
from otp.launcher.DummyLauncherBase import DummyLauncherBase
from toontown.launcher.ToontownLauncher import ToontownLauncher

class ToontownDummyLauncher(DummyLauncherBase, ToontownLauncher):
    notify = DirectNotifyGlobal.directNotify.newCategory('ToontownDummyLauncher')

    def __init__(self):
        DummyLauncherBase.__init__(self)
        self.setPhaseComplete(1, 100)
        self.setPhaseComplete(2, 100)
        self.setPhaseComplete(3, 100)
        self.windowOpen = 0
        self.firstPhase = 3.5
        self.goUserName = ''
        self.periodTimeRemainingKey = 'PERIOD_TIME_REMAINING'
        self.reg = {}
        self._browserStreaming = sys.platform == 'emscripten'
        if self._browserStreaming:
            import browser_assets
            self._browserAssets = browser_assets
            self._downloadComplete = False
            self._browserPhaseProgress = {}
            self._browserPhaseErrors = set()
            self._browserPlaygroundReadySent = False
            for phase in self.LauncherPhases:
                self.setPhaseComplete(phase, 100 if phase == 3 else 0)
            taskMgr.doMethodLater(
                0.1,
                self.__pollBrowserPhases,
                'browser-phase-download-poll')
        else:
            self.startFakeDownload()

    @staticmethod
    def __phaseKey(phase):
        numeric = float(phase)
        if numeric.is_integer():
            return str(int(numeric))
        return str(numeric)

    def isBrowserStreaming(self):
        return self._browserStreaming

    def prepareForPlayground(self):
        if not self._browserStreaming:
            return False
        return self._browserAssets.prepare_playground()

    def requestPhase(self, phase):
        if not self._browserStreaming:
            return False
        return self._browserAssets.request_phase(self.__phaseKey(phase))

    def startBackgroundDownloads(self):
        if not self._browserStreaming:
            return False
        return self._browserAssets.start_background()

    def __pollBrowserPhases(self, task):
        for phase in self.LauncherPhases[1:]:
            phaseKey = self.__phaseKey(phase)
            state = self._browserAssets.phase_state(phaseKey)
            percent = self._browserAssets.phase_progress(phaseKey)
            previous = self._browserPhaseProgress.get(phase)
            if previous != percent:
                self._browserPhaseProgress[phase] = percent
                messenger.send(
                    'launcherPercentPhaseComplete',
                    [phase, percent, 0, 0])
            if state == 2 and not self.getPhaseComplete(phase):
                self.setPhaseComplete(phase, 100)
                messenger.send('phaseComplete-' + repr(phase))
                self.notify.info('Browser phase %s is ready.' % phaseKey)
            elif state == 3 and phase not in self._browserPhaseErrors:
                self._browserPhaseErrors.add(phase)
                messenger.send('browser-phase-failed', [phase])
                self.notify.warning('Browser phase %s failed to load.' % phaseKey)

        playgroundReady = (
            self.getPhaseComplete(3.5)
            and self.getPhaseComplete(4))
        if playgroundReady and not self._browserPlaygroundReadySent:
            self._browserPlaygroundReadySent = True
            messenger.send('browser-playground-phases-ready')

        if all(self.getPhaseComplete(phase)
               for phase in self.LauncherPhases):
            if not self._downloadComplete:
                self.downloadDoneTask(None)
            return Task.done
        return Task.again

    def getReferrerCode(self):
        return None

    def setRegistry(self, name, value):
        print('setRegistry[%s] = %s' % (name, value))
        self.reg[name] = value

    def getRegistry(self, name, defaultValue = None):
        if name in self.reg:
            value = self.reg[name]
        else:
            value = defaultValue
        print('getRegistry[%s] = %s' % (name, value))
        return value

    def getGame2Done(self):
        return 1

    def recordPeriodTimeRemaining(self, secondsRemaining):
        self.setRegistry(self.periodTimeRemainingKey, secondsRemaining)

    def getGoUserName(self):
        return self.goUserName

    def setGoUserName(self, userName):
        self.goUserName = userName

    def getParentPasswordSet(self):
        return 0

    def getNeedPwForSecretKey(self):
        return 0
