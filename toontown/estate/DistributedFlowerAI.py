from direct.directnotify import DirectNotifyGlobal

from toontown.estate.DistributedPlantBaseAI import DistributedPlantBaseAI


class DistributedFlowerAI(DistributedPlantBaseAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedFlowerAI')

    def __init__(self, air, ownerId=0, garden=None, item=None):
        DistributedPlantBaseAI.__init__(self, air, ownerId, garden, item)
        self.variety = int((item or [0, 0, 0, 0, 0])[4])

    def setVariety(self, variety):
        self.variety = variety

    def getVariety(self):
        return self.variety
