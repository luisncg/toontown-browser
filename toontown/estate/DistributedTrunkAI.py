from direct.directnotify import DirectNotifyGlobal
from direct.distributed.ClockDelta import globalClockDelta
from direct.task.TaskManagerGlobal import taskMgr

from toontown.estate import ClosetGlobals
from toontown.estate.DistributedClosetAI import DistributedClosetAI
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.toon import ToonDNA


class DistributedTrunkAI(DistributedClosetAI):
    """Estate accessory trunk with one atomic Toon-record commit."""

    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedTrunkAI')
    _CATEGORIES = (
        (ToonDNA.HAT, 'setHatList', 'getHatList', 'setHatList',
         'd_setHatList', 'getHat', 'setHat', 'd_setHat'),
        (ToonDNA.GLASSES, 'setGlassesList', 'getGlassesList',
         'setGlassesList', 'd_setGlassesList', 'getGlasses',
         'setGlasses', 'd_setGlasses'),
        (ToonDNA.BACKPACK, 'setBackpackList', 'getBackpackList',
         'setBackpackList', 'd_setBackpackList', 'getBackpack',
         'setBackpack', 'd_setBackpack'),
        (ToonDNA.SHOES, 'setShoesList', 'getShoesList', 'setShoesList',
         'd_setShoesList', 'getShoes', 'setShoes', 'd_setShoes'),
    )

    def __init__(self, air, furnitureManager=None, catalogItem=None):
        DistributedClosetAI.__init__(self, air, furnitureManager, catalogItem)
        self.originalAccessories = {}
        self.previewAccessories = {}
        self.accessoryLists = {}
        self.removedAccessories = {}

    def enterAvatar(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if self.busyAvatarId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.furnitureManager.recordUnauthorized(
                avId, 'use trunk from another zone')
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return

        owner = self.air.doId2do.get(self.ownerId)
        if owner is None:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        self.busyAvatarId = avId
        self.originalAccessories = {}
        self.previewAccessories = {}
        self.accessoryLists = {}
        self.removedAccessories = {}
        for (which, _field, getList, _setList, _dSetList,
             getWorn, _setWorn, _dSetWorn) in self._CATEGORIES:
            worn = tuple(getattr(owner, getWorn)())
            self.originalAccessories[which] = worn
            self.previewAccessories[which] = worn
            self.accessoryLists[which] = list(getattr(owner, getList)())
            self.removedAccessories[which] = []

        self.d_setState(
            ClosetGlobals.OPEN, avId, self.ownerId,
            owner.getStyle().getGender(),
            self.accessoryLists[ToonDNA.HAT],
            self.accessoryLists[ToonDNA.GLASSES],
            self.accessoryLists[ToonDNA.BACKPACK],
            self.accessoryLists[ToonDNA.SHOES])
        taskMgr.remove(self.uniqueName('closet-timeout'))
        taskMgr.doMethodLater(
            120.0, self._timeout, self.uniqueName('closet-timeout'))

    def removeItem(self, geom, texture, color, which):
        avId = self.air.getAvatarIdFromSender()
        value = (geom, texture, color)
        if (avId != self.ownerId or avId != self.busyAvatarId or
                which not in self.removedAccessories):
            self.furnitureManager.recordUnauthorized(
                avId, 'remove item from trunk')
            return
        if not self._ownedAccessory(which, value):
            self.furnitureManager.recordUnauthorized(
                avId, 'remove unowned trunk accessory')
            return
        if value not in self.removedAccessories[which]:
            self.removedAccessories[which].append(value)

    def setDNA(self, hatGeom, hatTex, hatColor,
               glassesGeom, glassesTex, glassesColor,
               backpackGeom, backpackTex, backpackColor,
               shoesGeom, shoesTex, shoesColor, finished, whichItems):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (avId != self.busyAvatarId or avatar is None or
                getattr(avatar, 'zoneId', 0) != self.zoneId):
            self.furnitureManager.recordUnauthorized(
                avId, 'set accessories outside trunk session')
            return

        requested = {
            ToonDNA.HAT: (hatGeom, hatTex, hatColor),
            ToonDNA.GLASSES: (glassesGeom, glassesTex, glassesColor),
            ToonDNA.BACKPACK: (backpackGeom, backpackTex, backpackColor),
            ToonDNA.SHOES: (shoesGeom, shoesTex, shoesColor),
        }
        if not self._validateRequested(requested, whichItems):
            self.furnitureManager.recordUnauthorized(
                avId, 'wear unowned trunk accessory')
            self._cancelTrunkSession(avId)
            return

        if finished == 0:
            for which, value in requested.items():
                if whichItems & which:
                    self.previewAccessories[which] = value
            self._sendCustomerAccessories(avId, requested, whichItems)
            return
        if finished == 1:
            self._sendCustomerAccessories(
                avId, self.originalAccessories,
                ToonDNA.HAT | ToonDNA.GLASSES |
                ToonDNA.BACKPACK | ToonDNA.SHOES)
            self._completeTrunkSession(avId)
            return
        if finished != 2 or avId != self.ownerId or self._commitInFlight:
            self.furnitureManager.recordUnauthorized(
                avId, 'invalid trunk completion')
            self._cancelTrunkSession(avId)
            return

        oldFields = {}
        newFields = {}
        newLists = {}
        newWorn = {}
        for (which, field, getList, _setList, _dSetList,
             getWorn, _setWorn, _dSetWorn) in self._CATEGORIES:
            oldList = list(getattr(avatar, getList)())
            oldWorn = tuple(getattr(avatar, getWorn)())
            selected = requested[which] if whichItems & which else oldWorn
            newList = list(oldList)

            if selected != oldWorn:
                if not self._replaceFlat(newList, selected, oldWorn):
                    self.furnitureManager.recordUnauthorized(
                        avId, 'commit unowned trunk accessory')
                    self._cancelTrunkSession(avId)
                    return
            for removed in self.removedAccessories[which]:
                if not self._removeFlat(newList, removed):
                    # The originally worn item enters the list during a swap,
                    # so deleting it in the same session is valid.
                    if removed != oldWorn:
                        self.furnitureManager.recordUnauthorized(
                            avId, 'commit unowned trunk removal')
                        self._cancelTrunkSession(avId)
                        return

            oldFields[field] = oldList
            oldFields[self._wornField(which)] = list(oldWorn)
            newFields[field] = newList
            newFields[self._wornField(which)] = list(selected)
            newLists[which] = newList
            newWorn[which] = selected

        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._commitInFlight = True

        def committed(success, conflicts):
            self._commitInFlight = False
            if not success:
                self._applyTrunkConflict(avatar, conflicts)
                self._cancelTrunkSession(avId)
                return
            for (which, _field, _getList, setList, dSetList,
                 _getWorn, setWorn, dSetWorn) in self._CATEGORIES:
                getattr(avatar, setList)(newLists[which])
                getattr(avatar, dSetList)(newLists[which])
                getattr(avatar, setWorn)(*newWorn[which])
                getattr(avatar, dSetWorn)(*newWorn[which])
                self.accessoryLists[which] = list(newLists[which])
            self._sendCustomerAccessories(
                avId, newWorn,
                ToonDNA.HAT | ToonDNA.GLASSES |
                ToonDNA.BACKPACK | ToonDNA.SHOES)
            self._completeTrunkSession(avId)

        transaction.commit(oldFields, newFields, committed)

    def d_setState(self, mode, avId, ownerId, gender, hatList,
                   glassesList, backpackList, shoesList):
        self.sendUpdate('setState', [
            mode, avId, ownerId, gender, hatList,
            glassesList, backpackList, shoesList])

    def setState(self, mode, avId, ownerId, gender, hatList,
                 glassesList, backpackList, shoesList):
        return

    def setCustomerDNA(self, avId, hatGeom, hatTex, hatColor,
                       glassesGeom, glassesTex, glassesColor,
                       backpackGeom, backpackTex, backpackColor,
                       shoesGeom, shoesTex, shoesColor, whichItems):
        return

    def freeAvatar(self):
        if self.busyAvatarId:
            self._cancelTrunkSession(self.busyAvatarId)

    def _completeTrunkSession(self, avId):
        owner = self.air.doId2do.get(self.ownerId)
        gender = owner.getStyle().getGender() if owner else 'm'
        self.sendUpdate('setMovie', [
            ClosetGlobals.CLOSET_MOVIE_COMPLETE, avId,
            globalClockDelta.getRealNetworkTime(bits=16)])
        self.d_setState(
            ClosetGlobals.CLOSED, 0, self.ownerId, gender,
            self.accessoryLists.get(ToonDNA.HAT, []),
            self.accessoryLists.get(ToonDNA.GLASSES, []),
            self.accessoryLists.get(ToonDNA.BACKPACK, []),
            self.accessoryLists.get(ToonDNA.SHOES, []))
        self._clearTrunkSession()
        taskMgr.doMethodLater(
            1.0, self._clearMovie,
            self.uniqueName('clear-closet-movie'))

    def _cancelTrunkSession(self, avId):
        if self.originalAccessories:
            self._sendCustomerAccessories(
                avId, self.originalAccessories,
                ToonDNA.HAT | ToonDNA.GLASSES |
                ToonDNA.BACKPACK | ToonDNA.SHOES)
        self._completeTrunkSession(avId)

    def _clearTrunkSession(self):
        taskMgr.remove(self.uniqueName('closet-timeout'))
        self.busyAvatarId = 0
        self.originalAccessories = {}
        self.previewAccessories = {}
        self.removedAccessories = {}

    def _timeout(self, task):
        avId = self.busyAvatarId
        if avId:
            self.sendUpdate('setMovie', [
                ClosetGlobals.CLOSET_MOVIE_TIMEOUT, avId,
                globalClockDelta.getRealNetworkTime(bits=16)])
            if self.originalAccessories:
                self._sendCustomerAccessories(
                    avId, self.originalAccessories,
                    ToonDNA.HAT | ToonDNA.GLASSES |
                    ToonDNA.BACKPACK | ToonDNA.SHOES)
            self._clearTrunkSession()
        return task.done

    def _sendCustomerAccessories(self, avId, values, whichItems):
        hat = values.get(ToonDNA.HAT, self.originalAccessories[ToonDNA.HAT])
        glasses = values.get(
            ToonDNA.GLASSES, self.originalAccessories[ToonDNA.GLASSES])
        backpack = values.get(
            ToonDNA.BACKPACK, self.originalAccessories[ToonDNA.BACKPACK])
        shoes = values.get(
            ToonDNA.SHOES, self.originalAccessories[ToonDNA.SHOES])
        self.sendUpdate('setCustomerDNA', [
            avId,
            hat[0], hat[1], hat[2],
            glasses[0], glasses[1], glasses[2],
            backpack[0], backpack[1], backpack[2],
            shoes[0], shoes[1], shoes[2], whichItems])

    def _validateRequested(self, requested, whichItems):
        validMask = (ToonDNA.HAT | ToonDNA.GLASSES |
                     ToonDNA.BACKPACK | ToonDNA.SHOES)
        if whichItems & ~validMask:
            return False
        for which, value in requested.items():
            if whichItems & which and not self._ownedAccessory(which, value):
                return False
        return True

    def _ownedAccessory(self, which, value):
        if value == self.originalAccessories.get(which):
            return True
        values = self.accessoryLists.get(which, [])
        return any(tuple(values[index:index + 3]) == tuple(value)
                   for index in range(0, len(values), 3))

    @staticmethod
    def _wornField(which):
        return {
            ToonDNA.HAT: 'setHat',
            ToonDNA.GLASSES: 'setGlasses',
            ToonDNA.BACKPACK: 'setBackpack',
            ToonDNA.SHOES: 'setShoes',
        }[which]

    def _applyTrunkConflict(self, avatar, conflicts):
        if not conflicts:
            return
        for (which, field, _getList, setList, dSetList,
             _getWorn, setWorn, dSetWorn) in self._CATEGORIES:
            if field in conflicts:
                value = list(conflicts[field])
                getattr(avatar, setList)(value)
                getattr(avatar, dSetList)(value)
            wornField = self._wornField(which)
            if wornField in conflicts:
                value = tuple(conflicts[wornField])
                getattr(avatar, setWorn)(*value)
                getattr(avatar, dSetWorn)(*value)

    def delete(self):
        taskMgr.remove(self.uniqueName('closet-timeout'))
        taskMgr.remove(self.uniqueName('clear-closet-movie'))
        DistributedClosetAI.delete(self)
