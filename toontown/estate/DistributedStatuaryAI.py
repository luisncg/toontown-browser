from direct.directnotify import DirectNotifyGlobal

from toontown.estate.DistributedLawnDecorAI import DistributedLawnDecorAI


class DistributedStatuaryAI(DistributedLawnDecorAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedStatuaryAI')

    def __init__(self, air, ownerId=0, garden=None, item=None):
        DistributedLawnDecorAI.__init__(self, air, ownerId, garden)
        item = item or [200, 0, 0, 0, 0]
        self.typeIndex = int(item[0])
        self.waterLevel = int(item[2])
        self.growthLevel = int(item[3])

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
