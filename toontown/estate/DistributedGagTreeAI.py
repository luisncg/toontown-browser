from direct.directnotify import DirectNotifyGlobal

from toontown.estate.DistributedPlantBaseAI import DistributedPlantBaseAI


class DistributedGagTreeAI(DistributedPlantBaseAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedGagTreeAI')

    def __init__(self, air, ownerId=0, garden=None, item=None):
        DistributedPlantBaseAI.__init__(self, air, ownerId, garden, item)
        self.wilted = int(self.waterLevel < 0)

    def setWilted(self, wilted):
        self.wilted = wilted

    def getWilted(self):
        return self.wilted

    def requestHarvest(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId or self.garden is None:
            self._denyInteraction(avId, 'requestHarvest')
            return
        self.garden.requestHarvest(self, avId)

    def applyItem(self, item):
        oldWilted = self.wilted
        DistributedPlantBaseAI.applyItem(self, item)
        self.wilted = int(self.waterLevel < 0)
        if self.wilted != oldWilted:
            self.sendUpdate('setWilted', [self.wilted])
