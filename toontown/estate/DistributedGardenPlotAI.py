from direct.directnotify import DirectNotifyGlobal

from toontown.estate.DistributedLawnDecorAI import DistributedLawnDecorAI


class DistributedGardenPlotAI(DistributedLawnDecorAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedGardenPlotAI')

    def __init__(self, air, ownerId=0, garden=None):
        DistributedLawnDecorAI.__init__(self, air, ownerId, garden)

    def plantFlower(self, species, variety):
        avId = self.air.getAvatarIdFromSender()
        if self.garden is not None:
            self.garden.plantFlower(self, species, variety, avId)

    def plantGagTree(self, track, level):
        avId = self.air.getAvatarIdFromSender()
        if self.garden is not None:
            self.garden.plantGagTree(self, track, level, avId)

    def plantStatuary(self, species):
        avId = self.air.getAvatarIdFromSender()
        if self.garden is not None:
            self.garden.plantStatuary(self, species, 0, avId)

    def plantToonStatuary(self, species, dnaCode):
        avId = self.air.getAvatarIdFromSender()
        if self.garden is not None:
            self.garden.plantStatuary(self, species, dnaCode, avId)

    def plantNothing(self, burntBeans):
        avId = self.air.getAvatarIdFromSender()
        if self.garden is not None:
            self.garden.plantNothing(self, burntBeans, avId)
