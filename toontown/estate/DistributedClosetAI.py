from direct.directnotify import DirectNotifyGlobal
from direct.distributed.ClockDelta import globalClockDelta
from direct.task.TaskManagerGlobal import taskMgr
from toontown.estate import ClosetGlobals
from toontown.estate.DistributedFurnitureItemAI import DistributedFurnitureItemAI
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.toon import ToonDNA


class DistributedClosetAI(DistributedFurnitureItemAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedClosetAI')

    def __init__(self, air, furnitureManager=None, catalogItem=None):
        DistributedFurnitureItemAI.__init__(
            self, air, furnitureManager, catalogItem)
        self.ownerId = (
            furnitureManager.ownerId if furnitureManager is not None else 0)
        self.busyAvatarId = 0
        self.customerDNA = None
        self.topList = []
        self.bottomList = []
        self.removedTops = []
        self.removedBottoms = []
        self._commitInFlight = False

    def setOwnerId(self, ownerId):
        self.ownerId = ownerId

    def getOwnerId(self):
        return self.ownerId

    def enterAvatar(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if self.busyAvatarId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.furnitureManager.recordUnauthorized(
                avId, 'use closet from another zone')
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return

        owner = self.air.doId2do.get(self.ownerId)
        if owner is None:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        self.busyAvatarId = avId
        self.customerDNA = ToonDNA.ToonDNA()
        self.customerDNA.makeFromNetString(avatar.getDNAString())
        self.topList = list(owner.getClothesTopsList())
        self.bottomList = list(owner.getClothesBottomsList())
        self.removedTops = []
        self.removedBottoms = []
        self.d_setState(
            ClosetGlobals.OPEN, avId, self.ownerId,
            owner.getStyle().getGender(), self.topList, self.bottomList)
        taskMgr.remove(self.uniqueName('closet-timeout'))
        taskMgr.doMethodLater(
            120.0, self._timeout,
            self.uniqueName('closet-timeout'))

    def removeItem(self, dnaString, topOrBottom):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId or avId != self.busyAvatarId:
            self.furnitureManager.recordUnauthorized(
                avId, 'remove item from closet')
            return
        dna = self._decodeDNA(dnaString)
        if dna is None:
            self.furnitureManager.recordUnauthorized(
                avId, 'remove invalid closet DNA')
            return
        if topOrBottom == ClosetGlobals.SHIRT:
            value = self._topTuple(dna)
            if value not in self.removedTops:
                self.removedTops.append(value)
        elif topOrBottom == ClosetGlobals.SHORTS:
            value = self._bottomTuple(dna)
            if value not in self.removedBottoms:
                self.removedBottoms.append(value)
        else:
            self.furnitureManager.recordUnauthorized(
                avId, 'invalid closet item category')

    def setDNA(self, dnaString, finished, whichItems):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (avId != self.busyAvatarId or avatar is None or
                getattr(avatar, 'zoneId', 0) != self.zoneId):
            self.furnitureManager.recordUnauthorized(
                avId, 'set DNA outside closet session')
            return
        dna = self._decodeDNA(dnaString)
        if dna is None or not self._validClothingChange(dna):
            self.furnitureManager.recordUnauthorized(
                avId, 'invalid closet DNA change')
            self._cancelSession(avId)
            return

        if finished == 0:
            self.sendUpdate('setCustomerDNA', [avId, dnaString])
            return
        if finished == 1:
            self.sendUpdate(
                'setCustomerDNA', [avId, self.customerDNA.makeNetString()])
            self._completeSession(avId)
            return
        if finished != 2 or avId != self.ownerId or self._commitInFlight:
            self.furnitureManager.recordUnauthorized(
                avId, 'invalid closet completion')
            self._cancelSession(avId)
            return

        oldDNAString = avatar.getDNAString()
        oldTops = list(avatar.getClothesTopsList())
        oldBottoms = list(avatar.getClothesBottomsList())
        newTops = list(oldTops)
        newBottoms = list(oldBottoms)
        finalDNA = ToonDNA.ToonDNA()
        finalDNA.makeFromNetString(self.customerDNA.makeNetString())

        if whichItems & ClosetGlobals.SHIRT:
            selected = self._topTuple(dna)
            original = self._topTuple(self.customerDNA)
            if selected != original:
                if not self._replaceFlat(newTops, selected, original):
                    self.furnitureManager.recordUnauthorized(
                        avId, 'selected unowned closet top')
                    self._cancelSession(avId)
                    return
                self._applyTop(finalDNA, selected)
        if whichItems & ClosetGlobals.SHORTS:
            selected = self._bottomTuple(dna)
            original = self._bottomTuple(self.customerDNA)
            if selected != original:
                if not self._replaceFlat(newBottoms, selected, original):
                    self.furnitureManager.recordUnauthorized(
                        avId, 'selected unowned closet bottom')
                    self._cancelSession(avId)
                    return
                self._applyBottom(finalDNA, selected, dna.torso)

        for value in self.removedTops:
            if not self._removeFlat(newTops, value):
                # Deleting the originally worn item is valid: after a swap it
                # has just been inserted into the closet list.
                if value != self._topTuple(self.customerDNA):
                    self.furnitureManager.recordUnauthorized(
                        avId, 'removed unowned closet top')
                    self._cancelSession(avId)
                    return
        for value in self.removedBottoms:
            if not self._removeFlat(newBottoms, value):
                if value != self._bottomTuple(self.customerDNA):
                    self.furnitureManager.recordUnauthorized(
                        avId, 'removed unowned closet bottom')
                    self._cancelSession(avId)
                    return

        newDNAString = finalDNA.makeNetString()
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._commitInFlight = True

        def committed(success, conflicts):
            self._commitInFlight = False
            if not success:
                self._applyConflict(avatar, conflicts)
                self._cancelSession(avId)
                return
            avatar.setDNAString(newDNAString)
            avatar.d_setDNAString(newDNAString)
            avatar.setClothesTopsList(newTops)
            avatar.d_setClothesTopsList(newTops)
            avatar.setClothesBottomsList(newBottoms)
            avatar.d_setClothesBottomsList(newBottoms)
            self.topList = list(newTops)
            self.bottomList = list(newBottoms)
            self.sendUpdate('setCustomerDNA', [avId, newDNAString])
            self._completeSession(avId)

        transaction.commit(
            {
                'setDNAString': oldDNAString,
                'setClothesTopsList': oldTops,
                'setClothesBottomsList': oldBottoms,
            },
            {
                'setDNAString': newDNAString,
                'setClothesTopsList': newTops,
                'setClothesBottomsList': newBottoms,
            },
            committed)

    def d_setState(self, mode, avId, ownerId, gender, topList, bottomList):
        self.sendUpdate(
            'setState',
            [mode, avId, ownerId, gender, topList, bottomList])

    def setState(self, mode, avId, ownerId, gender, topList, bottomList):
        return

    def setMovie(self, mode, avId, timestamp):
        return

    def resetItemLists(self):
        return

    def setCustomerDNA(self, avId, dnaString):
        return

    def freeAvatar(self):
        if self.busyAvatarId:
            self._cancelSession(self.busyAvatarId)

    def _completeSession(self, avId):
        owner = self.air.doId2do.get(self.ownerId)
        gender = owner.getStyle().getGender() if owner else 'm'
        self.sendUpdate(
            'setMovie',
            [ClosetGlobals.CLOSET_MOVIE_COMPLETE, avId,
             globalClockDelta.getRealNetworkTime(bits=16)])
        self.d_setState(
            ClosetGlobals.CLOSED, 0, self.ownerId, gender,
            self.topList, self.bottomList)
        self._clearSession()
        taskMgr.doMethodLater(
            1.0, self._clearMovie,
            self.uniqueName('clear-closet-movie'))

    def _cancelSession(self, avId):
        if self.customerDNA is not None:
            self.sendUpdate(
                'setCustomerDNA',
                [avId, self.customerDNA.makeNetString()])
        self._completeSession(avId)

    def _clearSession(self):
        taskMgr.remove(self.uniqueName('closet-timeout'))
        self.busyAvatarId = 0
        self.customerDNA = None
        self.removedTops = []
        self.removedBottoms = []

    def _clearMovie(self, task):
        self.sendUpdate(
            'setMovie',
            [ClosetGlobals.CLOSET_MOVIE_CLEAR, 0,
             globalClockDelta.getRealNetworkTime(bits=16)])
        return task.done

    def _timeout(self, task):
        avId = self.busyAvatarId
        if avId:
            self.sendUpdate(
                'setMovie',
                [ClosetGlobals.CLOSET_MOVIE_TIMEOUT, avId,
                 globalClockDelta.getRealNetworkTime(bits=16)])
            self._clearSession()
        return task.done

    def _decodeDNA(self, dnaString):
        dna = ToonDNA.ToonDNA()
        if not dna.isValidNetString(dnaString):
            return None
        dna.makeFromNetString(dnaString)
        return dna

    def _validClothingChange(self, dna):
        original = self.customerDNA
        if original is None:
            return False
        if (dna.head != original.head or dna.legs != original.legs or
                dna.gender != original.gender or
                dna.armColor != original.armColor or
                dna.gloveColor != original.gloveColor or
                dna.legColor != original.legColor or
                dna.headColor != original.headColor):
            return False
        if dna.torso != original.torso:
            if original.gender == 'm' or dna.torso[0] != original.torso[0]:
                return False
        return True

    @staticmethod
    def _topTuple(dna):
        return (
            dna.topTex, dna.topTexColor,
            dna.sleeveTex, dna.sleeveTexColor)

    @staticmethod
    def _bottomTuple(dna):
        return (dna.botTex, dna.botTexColor)

    @staticmethod
    def _replaceFlat(values, oldValue, newValue):
        width = len(oldValue)
        for index in range(0, len(values), width):
            if tuple(values[index:index + width]) == tuple(oldValue):
                values[index:index + width] = list(newValue)
                return True
        return False

    @staticmethod
    def _removeFlat(values, value):
        width = len(value)
        for index in range(0, len(values), width):
            if tuple(values[index:index + width]) == tuple(value):
                del values[index:index + width]
                return True
        return False

    @staticmethod
    def _applyTop(dna, value):
        (dna.topTex, dna.topTexColor,
         dna.sleeveTex, dna.sleeveTexColor) = value

    @staticmethod
    def _applyBottom(dna, value, torso):
        dna.botTex, dna.botTexColor = value
        dna.torso = torso

    def _applyConflict(self, avatar, conflicts):
        if not conflicts:
            return
        if 'setDNAString' in conflicts:
            avatar.setDNAString(conflicts['setDNAString'])
            avatar.d_setDNAString(conflicts['setDNAString'])
        if 'setClothesTopsList' in conflicts:
            avatar.setClothesTopsList(conflicts['setClothesTopsList'])
            avatar.d_setClothesTopsList(conflicts['setClothesTopsList'])
        if 'setClothesBottomsList' in conflicts:
            avatar.setClothesBottomsList(conflicts['setClothesBottomsList'])
            avatar.d_setClothesBottomsList(
                conflicts['setClothesBottomsList'])

    def delete(self):
        taskMgr.remove(self.uniqueName('closet-timeout'))
        taskMgr.remove(self.uniqueName('clear-closet-movie'))
        DistributedFurnitureItemAI.delete(self)
