from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from direct.task.TaskManagerGlobal import taskMgr
from toontown.estate import CannonGlobals


class DistributedTargetAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedTargetAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.enabled = 0
        self.power = 0
        self.time = 0
        self.highScore = 0
        self.highScorer = ''

    def announceGenerate(self):
        DistributedObjectAI.announceGenerate(self)
        taskMgr.doMethodLater(
            2.0, self._startGame, self.uniqueName('start-game'))

    def delete(self):
        taskMgr.remove(self.uniqueName('start-game'))
        taskMgr.remove(self.uniqueName('end-game'))
        DistributedObjectAI.delete(self)

    def getPosition(self):
        return 0, 0, 40

    def getPinballHiScorer(self):
        return self.highScorer

    def setPinballHiScorer(self, name):
        self.highScorer = name

    def getPinballHiScore(self):
        return self.highScore

    def setPinballHiScore(self, score):
        self.highScore = score

    def setResult(self, claimedAvId):
        sender = self.air.getAvatarIdFromSender()
        if claimedAvId == 0 and self._avatarInZone(sender):
            return
        if sender != claimedAvId or not self._avatarInZone(sender):
            self.air.writeServerEvent(
                'suspicious', sender,
                'Invalid estate cannon target result for %s' % claimedAvId)
            return
        if not self.enabled:
            return
        self.power = min(self.power + 1, 8)
        self.time = max(1, int(CannonGlobals.CANNON_TIMEOUT / self.power))
        taskMgr.remove(self.uniqueName('end-game'))
        taskMgr.doMethodLater(
            self.time, self._endGame, self.uniqueName('end-game'))
        self._sendState()

    def setBonus(self, bonus):
        # The client reports decorative collision bonuses. Scoring remains
        # server bounded and the target result is the only power increase.
        return

    def setCurPinballScore(self, claimedAvId, score, multiplier):
        sender = self.air.getAvatarIdFromSender()
        if sender != claimedAvId or not self._avatarInZone(sender):
            self.air.writeServerEvent(
                'suspicious', sender,
                'Invalid estate pinball score for %s' % claimedAvId)
            return
        score = max(0, min(int(score), 1000000))
        multiplier = max(1, min(int(multiplier), 100))
        newScore = score * multiplier
        if newScore <= self.highScore:
            return
        avatar = self.air.doId2do.get(sender)
        self.highScore = newScore
        self.highScorer = avatar.getName() if avatar is not None else ''
        self.sendUpdate('setPinballHiScorer', [self.highScorer])
        self.sendUpdate('setPinballHiScore', [self.highScore])

    def _startGame(self, task):
        self.enabled = 1
        self.power = 1
        self.time = CannonGlobals.CANNON_TIMEOUT
        self._sendState()
        taskMgr.doMethodLater(
            self.time, self._endGame, self.uniqueName('end-game'))
        return task.done

    def _endGame(self, task):
        reward = self.getToonUpAmount()
        for avatar in list(self.air.doId2do.values()):
            if (getattr(avatar, 'zoneId', 0) == self.zoneId and
                    hasattr(avatar, 'toonUp')):
                avatar.toonUp(reward)
        self.enabled = 0
        self.power = 0
        self.time = 0
        self.sendUpdate('setReward', [reward])
        self._sendState()
        taskMgr.doMethodLater(
            10.0, self._startGame, self.uniqueName('start-game'))
        return task.done

    def _sendState(self):
        self.sendUpdate(
            'setState', [self.enabled, self.getToonUpAmount(), self.time])

    def getToonUpAmount(self):
        return 2 ** self.power if self.power else 0

    def _avatarInZone(self, avId):
        avatar = self.air.doId2do.get(avId)
        return avatar is not None and getattr(avatar, 'zoneId', 0) == self.zoneId
