from otp.ai.AIBaseGlobal import *
from panda3d.core import *
from .DistributedNPCToonBaseAI import *
from toontown.toonbase import TTLocalizer
from direct.task import Task
from toontown.fishing import FishGlobals
from toontown.pets import PetUtil, PetDNA, PetConstants

class DistributedNPCPetclerkAI(DistributedNPCToonBaseAI):

    def __init__(self, air, npcId):
        DistributedNPCToonBaseAI.__init__(self, air, npcId)
        self.givesQuests = 0
        self.busy = 0
        self._pendingAction = False
        self._transactionDonePending = False

    def delete(self):
        taskMgr.remove(self.uniqueName('clearMovie'))
        self.ignoreAll()
        DistributedNPCToonBaseAI.delete(self)

    def avatarEnter(self):
        avId = self.air.getAvatarIdFromSender()
        if not self.canAvatarInteract(avId):
            return
        if avId not in self.air.doId2do:
            self.notify.warning('Avatar: %s not found' % avId)
            return
        if self.isBusy():
            self.freeAvatar(avId)
            return
        self.petSeeds = simbase.air.petMgr.getAvailablePets(3, 2)
        numGenders = len(PetDNA.PetGenders)
        self.petSeeds *= numGenders
        self.petSeeds.sort()
        self.sendUpdateToAvatarId(avId, 'setPetSeeds', [self.petSeeds])
        self.transactionType = ''
        self._pendingAction = False
        self._transactionDonePending = False
        av = self.air.doId2do[avId]
        self.busy = avId
        self.acceptOnce(self.air.getAvatarExitEvent(avId), self.__handleUnexpectedExit, extraArgs=[avId])
        flag = NPCToons.SELL_MOVIE_START
        self.d_setMovie(avId, flag)
        taskMgr.doMethodLater(PetConstants.PETCLERK_TIMER, self.sendTimeoutMovie, self.uniqueName('clearMovie'))
        DistributedNPCToonBaseAI.avatarEnter(self)

    def rejectAvatar(self, avId):
        self.notify.warning('rejectAvatar: should not be called by a fisherman!')

    def d_setMovie(self, avId, flag, extraArgs = []):
        self.sendUpdate('setMovie', [flag,
         self.npcId,
         avId,
         extraArgs,
         ClockDelta.globalClockDelta.getRealNetworkTime()])

    def sendTimeoutMovie(self, task):
        self.d_setMovie(self.busy, NPCToons.SELL_MOVIE_TIMEOUT)
        self.sendClearMovie(None)
        return Task.done

    def sendClearMovie(self, task):
        self.ignore(self.air.getAvatarExitEvent(self.busy))
        taskMgr.remove(self.uniqueName('clearMovie'))
        self.busy = 0
        self.d_setMovie(0, NPCToons.SELL_MOVIE_CLEAR)
        return Task.done

    def fishSold(self):
        avId = self.air.getAvatarIdFromSender()
        if self.busy != avId:
            self.air.writeServerEvent('suspicious', avId, 'DistributedNPCPetshopAI.fishSold busy with %s' % self.busy)
            self.notify.warning('somebody called fishSold that I was not busy with! avId: %s' % avId)
            return
        av = simbase.air.doId2do.get(avId)
        if av:
            self.transactionType = 'fish'
            def sold(trophyResult):
                if self.busy != avId:
                    return
                if trophyResult:
                    movieType = NPCToons.SELL_MOVIE_TROPHY
                    extraArgs = [
                        len(av.fishCollection),
                        FishGlobals.getTotalNumFish()]
                else:
                    movieType = NPCToons.SELL_MOVIE_COMPLETE
                    extraArgs = []
                self.d_setMovie(avId, movieType, extraArgs)
                self.sendClearMovie(None)

            self.air.fishManager.creditFishTank(av, sold)
            return
        self.sendClearMovie(None)
        return

    def petAdopted(self, petNum, nameIndex):
        avId = self.air.getAvatarIdFromSender()
        if self.busy != avId:
            self.air.writeServerEvent('suspicious', avId, 'DistributedNPCPetshopAI.petAdopted busy with %s' % self.busy)
            self.notify.warning('somebody called petAdopted that I was not busy with! avId: %s' % avId)
            return
        if self._pendingAction:
            self.air.writeServerEvent(
                'suspicious', avId,
                'DistributedNPCPetshopAI.petAdopted while transaction pending')
            return
        av = simbase.air.doId2do.get(avId)
        if av:
            from toontown.hood import ZoneUtil
            zoneId = ZoneUtil.getCanonicalSafeZoneId(self.zoneId)
            if petNum not in list(range(0, len(self.petSeeds))):
                self.air.writeServerEvent('suspicious', avId, 'DistributedNPCPetshopAI.petAdopted and no such pet!')
                self.notify.warning('somebody called petAdopted on a non-existent pet! avId: %s' % avId)
                return
            cost = PetUtil.getPetCostFromSeed(self.petSeeds[petNum], zoneId)
            if cost > av.getTotalMoney():
                self.air.writeServerEvent('suspicious', avId, "DistributedNPCPetshopAI.petAdopted and toon doesn't have enough money!")
                self.notify.warning("somebody called petAdopted and didn't have enough money to adopt! avId: %s" % avId)
                return
            if av.petId != 0:
                self.air.writeServerEvent(
                    'suspicious', avId,
                    'Attempted to adopt a second pet without returning the '
                    'current pet first')
                return
            gender = petNum % len(PetDNA.PetGenders)
            if nameIndex not in list(range(0, TTLocalizer.PetNameIndexMAX)):
                self.air.writeServerEvent('avoid_crash', avId, "DistributedNPCPetclerkAI.petAdopted and didn't have valid nameIndex!")
                self.notify.warning("somebody called petAdopted and didn't have valid nameIndex to adopt! avId: %s" % avId)
                return
            def adopted(success, petId):
                self._pendingAction = False
                if self.busy != avId:
                    return
                self.transactionType = 'adopt' if success else ''
                if self._transactionDonePending:
                    self._finishTransaction(avId)

            self._pendingAction = True
            simbase.air.petMgr.createNewPetFromSeed(
                avId, self.petSeeds[petNum], nameIndex=nameIndex,
                gender=gender, safeZoneId=zoneId, cost=cost,
                callback=adopted)

    def petReturned(self):
        avId = self.air.getAvatarIdFromSender()
        if self.busy != avId:
            self.air.writeServerEvent('suspicious', avId, 'DistributedNPCPetshopAI.petReturned busy with %s' % self.busy)
            self.notify.warning('somebody called petReturned that I was not busy with! avId: %s' % avId)
            return
        if self._pendingAction:
            self.air.writeServerEvent(
                'suspicious', avId,
                'DistributedNPCPetshopAI.petReturned while transaction pending')
            return
        av = simbase.air.doId2do.get(avId)
        if av:
            def returned(success):
                self._pendingAction = False
                if self.busy != avId:
                    return
                self.transactionType = 'return' if success else ''
                if self._transactionDonePending:
                    self._finishTransaction(avId)

            self._pendingAction = True
            simbase.air.petMgr.deleteToonsPet(avId, returned)

    def transactionDone(self):
        avId = self.air.getAvatarIdFromSender()
        if self.busy != avId:
            self.air.writeServerEvent('suspicious', avId, 'DistributedNPCPetshopAI.transactionDone busy with %s' % self.busy)
            self.notify.warning('somebody called transactionDone that I was not busy with! avId: %s' % avId)
            return
        if self._pendingAction:
            self._transactionDonePending = True
            return
        self._finishTransaction(avId)

    def _finishTransaction(self, avId):
        av = simbase.air.doId2do.get(avId)
        if av:
            if self.transactionType == 'adopt':
                self.d_setMovie(avId, NPCToons.SELL_MOVIE_PETADOPTED)
            elif self.transactionType == 'return':
                self.d_setMovie(avId, NPCToons.SELL_MOVIE_PETRETURNED)
            elif self.transactionType == '':
                self.d_setMovie(avId, NPCToons.SELL_MOVIE_PETCANCELED)
        self._transactionDonePending = False
        self.sendClearMovie(None)
        return

    def __handleUnexpectedExit(self, avId):
        self.notify.warning('avatar:' + str(avId) + ' has exited unexpectedly')
        self.notify.warning('not busy with avId: %s, busy: %s ' % (avId, self.busy))
        taskMgr.remove(self.uniqueName('clearMovie'))
        self.sendClearMovie(None)
        return
