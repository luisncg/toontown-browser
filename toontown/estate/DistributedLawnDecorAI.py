from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedNodeAI import DistributedNodeAI


class DistributedLawnDecorAI(DistributedNodeAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedLawnDecorAI')

    def __init__(self, air, ownerId=0, garden=None):
        DistributedNodeAI.__init__(self, air)
        self.ownerId = ownerId
        self.garden = garden
        self.plot = 0
        self.ownerIndex = 0

    def setPlot(self, plot):
        self.plot = plot

    def getPlot(self):
        return self.plot

    def setHeading(self, heading):
        self.setH(heading)

    def getHeading(self):
        return self.getH()

    def setPosition(self, x, y, z):
        self.setPos(x, y, z)

    def getPosition(self):
        return self.getPos()

    def setOwnerIndex(self, ownerIndex):
        self.ownerIndex = ownerIndex

    def getOwnerIndex(self):
        return self.ownerIndex

    def plotEntered(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId:
            self._denyInteraction(avId, 'plotEntered')

    def removeItem(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId:
            self._denyInteraction(avId, 'removeItem')
            return
        if self.garden is None:
            self._denyInteraction(avId, 'removeItem')
            return
        self.garden.requestRemove(self, avId)

    def movieDone(self):
        return

    def d_setMovie(self, mode, avId=None):
        if avId is None:
            avId = self.air.getAvatarIdFromSender()
        self.sendUpdate('setMovie', [mode, avId])

    def _denyInteraction(self, avId, action):
        if avId != self.ownerId:
            self.air.writeServerEvent(
                'suspicious', avId,
                'Tried garden action %s on plot %s owned by %s' %
                (action, self.doId, self.ownerId))
        self.sendUpdateToAvatarId(avId, 'interactionDenied', [avId])
