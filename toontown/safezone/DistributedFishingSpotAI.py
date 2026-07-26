import math

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from direct.task.TaskManagerGlobal import taskMgr
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.fishing import FishGlobals
from toontown.toonbase import ToontownGlobals


class DistributedFishingSpotAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedFishingSpotAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.pondDoId = 0
        self.posHpr = [0, 0, 0, 0, 0, 0]
        self.avId = 0
        self.cast = False
        self.lastFish = [FishGlobals.Nothing, 0, 0, 0]
        self._operationInFlight = False

    def generate(self):
        DistributedObjectAI.generate(self)
        pond = self.air.doId2do.get(self.pondDoId)
        if pond is not None:
            pond.addSpot(self)

    def delete(self):
        self._removeTasks()
        if self.avId:
            self.ignore(self.air.getAvatarExitEvent(self.avId))
        pond = self.air.doId2do.get(self.pondDoId)
        if pond is not None:
            pond.removeSpot(self)
        DistributedObjectAI.delete(self)

    def setPondDoId(self, pondDoId):
        self.pondDoId = pondDoId

    def getPondDoId(self):
        return self.pondDoId

    def setPosHpr(self, x, y, z, h, p, r):
        self.posHpr = [x, y, z, h, p, r]

    def getPosHpr(self):
        return self.posHpr

    def requestEnter(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        pond = self.air.doId2do.get(self.pondDoId)
        if (not avId or avatar is None or pond is None or
                getattr(avatar, 'zoneId', 0) != self.zoneId):
            self._record(avId, 'entered fishing spot from another zone')
            self.sendUpdateToAvatarId(avId, 'rejectEnter', [])
            return
        if (self.avId or self._operationInFlight or
                pond.hasToon(avId) is not None):
            if self.avId == avId:
                self._record(avId, 'entered fishing spot twice')
            self.sendUpdateToAvatarId(avId, 'rejectEnter', [])
            return
        from toontown.authority.BrowserAuthorityManagerAI import (
            consumeProtectedTransition)
        if not consumeProtectedTransition(
                self.air,
                avId,
                'fishing.enter',
                {'spot': self.doId, 'zone': self.zoneId}):
            return
        self.acceptOnce(
            self.air.getAvatarExitEvent(avId), self._unexpectedExit)
        self.b_setOccupied(avId)
        if pond.getPondBingoManager() is not None:
            pond.getPondBingoManager().activateForPlayer(avId)
        self.cast = False
        self.lastFish = [FishGlobals.Nothing, 0, 0, 0]
        self.d_setMovie(FishGlobals.EnterMovie, 0, 0, 0, 0, 0, 0)
        self._scheduleMovieClear()
        self._scheduleTimeout(FishGlobals.CastTimeout + 2.5)

    def requestExit(self):
        avId = self.air.getAvatarIdFromSender()
        if self.avId != avId:
            self._record(avId, 'exited a fishing spot owned by another Toon')
            return
        self.ignore(self.air.getAvatarExitEvent(avId))
        self.removeFromFishingSpotWithAnim()

    def setOccupied(self, avId):
        self.avId = avId

    def d_setOccupied(self, avId):
        self.sendUpdate('setOccupied', [avId])

    def b_setOccupied(self, avId):
        self.setOccupied(avId)
        self.d_setOccupied(avId)

    def doCast(self, p, h):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (self.avId != avId or avatar is None or self.cast or
                self._operationInFlight or
                getattr(avatar, 'zoneId', 0) != self.zoneId or
                not math.isfinite(p) or not math.isfinite(h)):
            self._record(avId, 'sent an invalid fishing cast')
            return
        if len(avatar.fishTank) >= avatar.getMaxFishTank():
            self.d_setMovie(
                FishGlobals.PullInMovie, FishGlobals.OverTankLimit,
                0, 0, 0, 0, 0)
            return
        cost = FishGlobals.getCastCost(avatar.getFishingRod())
        oldMoney = avatar.getMoney()
        if oldMoney < cost:
            self._record(avId, 'cast without enough pocket jellybeans')
            return
        from toontown.authority.BrowserAuthorityManagerAI import (
            consumeProtectedTransition)
        if not consumeProtectedTransition(
                self.air,
                avId,
                'fishing.cast',
                {'spot': getattr(self, 'doId', 0), 'zone': self.zoneId}):
            return
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._operationInFlight = True
        taskMgr.remove(self.uniqueName('timeout'))

        def committed(success, conflicts):
            self._operationInFlight = False
            if not success:
                if conflicts and 'setMoney' in conflicts:
                    avatar.setMoney(conflicts['setMoney'])
                    avatar.d_setMoney(conflicts['setMoney'])
                if self.avId == avId:
                    self._scheduleTimeout(FishGlobals.CastTimeout)
                return
            avatar.setMoney(oldMoney - cost)
            avatar.d_setMoney(oldMoney - cost)
            authority = getattr(self.air, 'browserAuthorityManager', None)
            if authority is not None:
                authority.recordProgressionMutation(
                    avId,
                    'fishing.cast.debit',
                    {
                        'cost': int(cost),
                        'balance': int(oldMoney - cost),
                        'pond': int(self.pondDoId),
                    })
            if self.avId != avId:
                return
            self.cast = True
            self.d_setMovie(FishGlobals.CastMovie, 0, 0, 0, 0, p, h)
            self._scheduleMovieClear()
            self._scheduleTimeout(FishGlobals.CastTimeout)

        transaction.commit(
            {'setMoney': oldMoney}, {'setMoney': oldMoney - cost}, committed)

    def considerReward(self, targetId):
        if not self.avId or not self.cast or self._operationInFlight:
            self._record(self.avId, 'claimed a fish without an active cast')
            return
        avatar = self.air.doId2do.get(self.avId)
        pond = self.air.doId2do.get(self.pondDoId)
        if avatar is None or pond is None:
            return
        rewardAvId = self.avId
        self.cast = False
        self._operationInFlight = True
        taskMgr.remove(self.uniqueName('timeout'))

        def rewarded(catch):
            self._operationInFlight = False
            if self.avId != rewardAvId:
                return
            self.lastFish = list(catch)
            self.d_setMovie(FishGlobals.PullInMovie, *catch, 0, 0)
            self._scheduleMovieClear()
            self._scheduleTimeout(FishGlobals.CastTimeout)

        self.air.fishManager.generateCatch(
            avatar, pond.getArea(), rewarded)

    def sellFish(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        pond = self.air.doId2do.get(self.pondDoId)
        if (self.avId != avId or avatar is None or pond is None or
                pond.getArea() != ToontownGlobals.MyEstate or
                self._operationInFlight):
            self._record(avId, 'sent an invalid estate fish sale')
            return
        self._operationInFlight = True
        taskMgr.remove(self.uniqueName('timeout'))

        def sold(trophy):
            self._operationInFlight = False
            if self.avId != avId:
                return
            self.sendUpdateToAvatarId(
                avId, 'sellFishComplete',
                [int(bool(trophy)), len(avatar.fishCollection)])
            self._scheduleTimeout(FishGlobals.CastTimeout)

        self.air.fishManager.creditFishTank(avatar, sold)

    def d_setMovie(self, mode, code, genus, species, weight, p, h):
        self.sendUpdate(
            'setMovie', [mode, code, genus, species, weight, p, h])

    def removeFromFishingSpot(self, task=None):
        self._removeTasks()
        oldAvId = self.avId
        pond = self.air.doId2do.get(self.pondDoId)
        if pond is not None and pond.getPondBingoManager() is not None:
            pond.getPondBingoManager().removePlayer(oldAvId)
        if self.avId:
            self.ignore(self.air.getAvatarExitEvent(self.avId))
        self.cast = False
        self.d_setMovie(FishGlobals.NoMovie, 0, 0, 0, 0, 0, 0)
        self.b_setOccupied(0)
        return task.done if task is not None else None

    def consumeBingoCatch(self):
        self.lastFish = [FishGlobals.Nothing, 0, 0, 0]

    def removeFromFishingSpotWithAnim(self, task=None):
        taskMgr.remove(self.uniqueName('clear-movie'))
        taskMgr.remove(self.uniqueName('timeout'))
        self.cast = False
        self.d_setMovie(FishGlobals.ExitMovie, 0, 0, 0, 0, 0, 0)
        taskMgr.doMethodLater(
            1.5, self.removeFromFishingSpot,
            self.uniqueName('remove'))
        return task.done if task is not None else None

    def _unexpectedExit(self, *args):
        self.removeFromFishingSpot()

    def _scheduleMovieClear(self):
        taskMgr.remove(self.uniqueName('clear-movie'))
        taskMgr.doMethodLater(
            2.0, self._clearMovie, self.uniqueName('clear-movie'))

    def _clearMovie(self, task):
        self.d_setMovie(FishGlobals.NoMovie, 0, 0, 0, 0, 0, 0)
        return task.done

    def _scheduleTimeout(self, delay):
        taskMgr.remove(self.uniqueName('timeout'))
        taskMgr.doMethodLater(
            delay, self.removeFromFishingSpotWithAnim,
            self.uniqueName('timeout'))

    def _removeTasks(self):
        for suffix in ('clear-movie', 'timeout', 'remove'):
            taskMgr.remove(self.uniqueName(suffix))

    def _record(self, avId, message):
        self.air.writeServerEvent('suspicious', avId or 0, message)
