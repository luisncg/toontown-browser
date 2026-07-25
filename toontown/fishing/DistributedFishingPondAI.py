from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from toontown.fishing import FishingTargetGlobals
from toontown.fishing.DistributedFishingTargetAI import (
    DistributedFishingTargetAI)

class DistributedFishingPondAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedFishingPondAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.area = None
        self.targets = {}
        self.spots = {}
        self.bingoMgr = None

    def generate(self):
        DistributedObjectAI.generate(self)
        fishManager = getattr(self.air, 'fishManager', None)
        if fishManager is not None:
            fishManager.ponds[self.zoneId] = self
        bingoManager = getattr(self.air, 'bingoManager', None)
        if bingoManager is not None:
            bingoManager.registerPond(self)

    def setArea(self, area):
        self.area = area

    def getArea(self):
        return self.area

    def generateTargets(self):
        if self.targets:
            return
        for _ in range(FishingTargetGlobals.getNumTargets(self.area)):
            target = DistributedFishingTargetAI(self.air)
            target.setPondDoId(self.doId)
            target.generateWithRequired(self.zoneId)

    def addTarget(self, target):
        self.targets[target.doId] = target

    def removeTarget(self, target):
        self.targets.pop(target.doId, None)

    def addSpot(self, spot):
        self.spots[spot.doId] = spot

    def removeSpot(self, spot):
        self.spots.pop(spot.doId, None)

    def hitTarget(self, targetId):
        avId = self.air.getAvatarIdFromSender()
        if targetId not in self.targets:
            self.air.writeServerEvent(
                'suspicious', avId,
                'Toon hit nonexistent fishing target %s' % targetId)
            return
        spot = self.hasToon(avId)
        if spot is None:
            self.air.writeServerEvent(
                'suspicious', avId,
                'Toon hit fishing target while not on a spot')
            return
        spot.considerReward(targetId)

    def hasToon(self, avId):
        for spot in self.spots.values():
            if spot.avId == avId:
                return spot
        return None

    def setPondBingoManager(self, bingoMgr):
        self.bingoMgr = bingoMgr

    def removePondBingoManager(self, bingoMgr=None):
        if bingoMgr is None or self.bingoMgr is bingoMgr:
            self.bingoMgr = None

    def getPondBingoManager(self):
        return self.bingoMgr

    def delete(self):
        bingoManager = getattr(self.air, 'bingoManager', None)
        if bingoManager is not None:
            bingoManager.unregisterPond(self)
        fishManager = getattr(self.air, 'fishManager', None)
        if (fishManager is not None and
                fishManager.ponds.get(self.zoneId) is self):
            fishManager.ponds.pop(self.zoneId, None)
        for obj in list(self.targets.values()) + list(self.spots.values()):
            if not getattr(obj, 'deleted', False):
                obj.requestDelete()
        self.targets.clear()
        self.spots.clear()
        self.bingoMgr = None
        DistributedObjectAI.delete(self)
