from direct.directnotify import DirectNotifyGlobal

from toontown.estate import GardenGlobals
from toontown.estate.DistributedLawnDecorAI import DistributedLawnDecorAI


class DistributedPlantBaseAI(DistributedLawnDecorAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedPlantBaseAI')

    def __init__(self, air, ownerId=0, garden=None, item=None):
        DistributedLawnDecorAI.__init__(self, air, ownerId, garden)
        item = item or [0, 0, 0, 0, 0]
        self.typeIndex = int(item[0])
        self.waterLevel = int(item[2])
        self.growthLevel = int(item[3])
        self._wateringAvatarId = 0

    def setTypeIndex(self, typeIndex):
        self.typeIndex = typeIndex

    def getTypeIndex(self):
        return self.typeIndex

    def setWaterLevel(self, waterLevel):
        self.waterLevel = waterLevel

    def getWaterLevel(self):
        return self.waterLevel

    def setGrowthLevel(self, growthLevel):
        self.growthLevel = growthLevel

    def getGrowthLevel(self):
        return self.growthLevel

    def waterPlant(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId or self.garden is None:
            self._denyInteraction(avId, 'waterPlant')
            return
        if self._wateringAvatarId:
            self._denyInteraction(avId, 'waterPlant while busy')
            return
        self._wateringAvatarId = avId
        self.garden.requestWater(self, avId)

    def waterPlantDone(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self._wateringAvatarId:
            self._denyInteraction(avId, 'waterPlantDone')
            return
        self._wateringAvatarId = 0
        if self.garden is not None:
            self.garden.finishWater(self, avId)
        else:
            self.d_setMovie(GardenGlobals.MOVIE_CLEAR, avId)

    def applyItem(self, item):
        oldWater = self.waterLevel
        oldGrowth = self.growthLevel
        self.typeIndex = int(item[0])
        self.waterLevel = int(item[2])
        self.growthLevel = int(item[3])
        if self.waterLevel != oldWater:
            self.sendUpdate('setWaterLevel', [self.waterLevel])
        if self.growthLevel != oldGrowth:
            self.sendUpdate('setGrowthLevel', [self.growthLevel])
