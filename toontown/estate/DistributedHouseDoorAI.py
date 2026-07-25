from direct.directnotify import DirectNotifyGlobal
from toontown.building import DistributedDoorAI


class DistributedHouseDoorAI(DistributedDoorAI.DistributedDoorAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedHouseDoorAI')

    def __init__(self, air, houseId, doorType, ownerId=0):
        DistributedDoorAI.DistributedDoorAI.__init__(
            self, air, houseId, doorType)
        self.ownerId = ownerId

    def requestEnter(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if avatar is None or not self._avatarMayEnter(avId):
            self.notify.warning(
                'Rejected avatar %s at house %s owned by %s' %
                (avId, self.block, self.ownerId))
            self.sendReject(avId, 0)
            return

        if self.otherDoor is None:
            self.notify.warning('House door %s has no paired door' % self.doId)
            self.sendReject(avId, 0)
            return

        self.enqueueAvatarIdEnter(avId)
        self.sendUpdateToAvatarId(
            avId, 'setOtherZoneIdAndDoId',
            [self.otherDoor.getZoneId(), self.otherDoor.getDoId()])

    def requestExit(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.notify.warning(
                'Rejected remote exit request from avatar %s at house %s' %
                (avId, self.block))
            return
        self.notify.info(
            'Avatar %s requested exit through house door %s in zone %s' %
            (avId, self.doId, self.zoneId))
        DistributedDoorAI.DistributedDoorAI.requestExit(self)

    def _avatarMayEnter(self, avId):
        if not self.ownerId:
            return False
        avatar = self.air.doId2do.get(avId)
        if (avatar is None or
                getattr(avatar, 'zoneId', 0) != self.zoneId):
            return False
        if avId == self.ownerId:
            return True
        return any(friend[0] == self.ownerId
                   for friend in avatar.getFriendsList())
