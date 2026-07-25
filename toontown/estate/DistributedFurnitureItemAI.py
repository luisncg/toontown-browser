import math

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedSmoothNodeAI import DistributedSmoothNodeAI
from toontown.catalog import CatalogItem
from toontown.estate import HouseGlobals


class DistributedFurnitureItemAI(DistributedSmoothNodeAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedFurnitureItemAI')

    def __init__(self, air, furnitureManager=None, catalogItem=None):
        DistributedSmoothNodeAI.__init__(self, air)
        self.furnitureManager = furnitureManager
        self.catalogItem = catalogItem
        self.mode = HouseGlobals.FURNITURE_MODE_OFF
        self.modeAvId = 0

    def announceGenerate(self):
        DistributedSmoothNodeAI.announceGenerate(self)
        if self.catalogItem is None:
            return
        posHpr = self.catalogItem.posHpr or (0, 0, 0, 0, 0, 0)
        self.b_setPosHpr(*posHpr)

    def getItem(self):
        if self.furnitureManager is None or self.catalogItem is None:
            return (0, b'')
        return (
            self.furnitureManager.doId,
            self.catalogItem.getBlob(store=CatalogItem.Customization))

    def requestPosHpr(self, final, x, y, z, h, p, r, timestamp):
        avId = self.air.getAvatarIdFromSender()
        manager = self.furnitureManager
        if manager is None or not manager.canMoveItem(avId, self):
            if manager is not None:
                manager.recordUnauthorized(avId, 'requestPosHpr')
            return

        values = (x, y, z, h, p, r)
        if not all(math.isfinite(value) for value in values):
            manager.recordUnauthorized(avId, 'non-finite furniture position')
            return
        # These are well beyond the actual house bounds but prevent malformed
        # clients from persisting absurd coordinates at the edge of the DC
        # numeric range.
        if abs(x) > 200 or abs(y) > 200 or z < -20 or z > 100:
            manager.recordUnauthorized(avId, 'out-of-bounds furniture position')
            return

        self.catalogItem.posHpr = values
        if not final and self.mode != HouseGlobals.FURNITURE_MODE_START:
            self.b_setMode(HouseGlobals.FURNITURE_MODE_START, avId)
        self.sendUpdate(
            'setSmPosHpr', [x, y, z, h, p, r, timestamp])

        if final:
            self.b_setMode(HouseGlobals.FURNITURE_MODE_STOP, avId)
            manager.persistItemPosition(self)

    def setMode(self, mode, avId):
        self.mode = mode
        self.modeAvId = avId
        if (mode == HouseGlobals.FURNITURE_MODE_STOP and
                self.catalogItem is not None):
            self.b_setPosHpr(*(self.catalogItem.posHpr or (0, 0, 0, 0, 0, 0)))

    def d_setMode(self, mode, avId):
        self.sendUpdate('setMode', [mode, avId])

    def b_setMode(self, mode, avId):
        self.setMode(mode, avId)
        self.d_setMode(mode, avId)

    def getMode(self):
        return (self.mode, self.modeAvId)

    def destroy(self):
        if not getattr(self, 'do_deleted', False):
            self.requestDelete()

    def delete(self):
        if getattr(self, 'do_deleted', False):
            return
        self.do_deleted = True
        DistributedSmoothNodeAI.delete(self)
