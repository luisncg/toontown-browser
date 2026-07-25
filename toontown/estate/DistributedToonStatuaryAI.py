from direct.directnotify import DirectNotifyGlobal

from toontown.estate.DistributedStatuaryAI import DistributedStatuaryAI


class DistributedToonStatuaryAI(DistributedStatuaryAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedToonStatuaryAI')

    def __init__(self, air, ownerId=0, garden=None, item=None):
        DistributedStatuaryAI.__init__(self, air, ownerId, garden, item)
        self.optional = int((item or [0, 0, 0, 0, 0])[4])

    def setOptional(self, optional):
        self.optional = optional

    def getOptional(self):
        return self.optional
