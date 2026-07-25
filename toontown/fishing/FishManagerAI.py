"""Server-authoritative fishing rewards with one-Toon atomic persistence."""

import random

from direct.directnotify import DirectNotifyGlobal
from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, SerialOperationQueue)
from toontown.fishing import FishGlobals
from toontown.fishing.FishBase import FishBase
from toontown.fishing.FishCollection import FishCollection
from toontown.fishing.FishTank import FishTank
from toontown.toonbase import ToontownGlobals


class FishManagerAI:
    notify = DirectNotifyGlobal.directNotify.newCategory('FishManagerAI')

    def __init__(self, air):
        self.air = air
        self.ponds = {}
        self.requestedFish = {}
        self._queues = {}

    def generateCatch(self, avatar, area, callback):
        """Generate and persist one catch, then call ``callback(movieData)``."""
        queue = self._queues.setdefault(avatar.doId, SerialOperationQueue())

        def operation(done):
            catch, oldFields, newFields = self._planCatch(avatar, area)
            if not oldFields:
                callback(catch)
                done()
                return
            transaction = self._transaction(avatar)

            def committed(success, conflicts):
                if success:
                    self._applyFields(avatar, newFields)
                    callback(catch)
                else:
                    self._applyConflicts(avatar, conflicts)
                    callback([FishGlobals.Nothing, 0, 0, 0])
                done()

            transaction.commit(oldFields, newFields, committed)

        queue.submit(operation)

    def creditFishTank(self, avatar, callback=None):
        """Atomically sell the tank and award any newly earned trophies."""
        if callback is None:
            callback = lambda trophy: None
        queue = self._queues.setdefault(avatar.doId, SerialOperationQueue())

        def operation(done):
            tankLists = avatar.getFishTank()
            tank = FishTank()
            tank.makeFromNetLists(*tankLists)
            if not len(tank):
                callback(False)
                done()
                return
            oldMoney = avatar.getMoney()
            oldBank = avatar.getBankMoney()
            total = oldMoney + tank.getTotalValue()
            newMoney = min(total, avatar.getMaxMoney())
            newBank = min(
                avatar.getMaxBankMoney(),
                oldBank + max(0, total - newMoney))
            trophyCount = min(
                len(avatar.fishCollection) // 10,
                FishGlobals.getTotalNumFish() // 10)
            oldTrophies = list(avatar.getFishingTrophies())
            newTrophies = list(range(max(len(oldTrophies), trophyCount)))
            trophyDelta = max(0, len(newTrophies) - len(oldTrophies))
            oldMaxHp = avatar.getMaxHp()
            newMaxHp = min(
                ToontownGlobals.MaxHpLimit, oldMaxHp + trophyDelta)
            oldFields = {
                'setMoney': oldMoney,
                'setBankMoney': oldBank,
                'setFishTank': tuple(tankLists),
                'setFishingTrophies': oldTrophies,
                'setMaxHp': oldMaxHp,
            }
            newFields = {
                'setMoney': newMoney,
                'setBankMoney': newBank,
                'setFishTank': ([], [], []),
                'setFishingTrophies': newTrophies,
                'setMaxHp': newMaxHp,
            }

            def committed(success, conflicts):
                if success:
                    self._applyFields(avatar, newFields)
                    if newMaxHp > oldMaxHp:
                        avatar.toonUp(newMaxHp)
                    callback(newMaxHp > oldMaxHp)
                else:
                    self._applyConflicts(avatar, conflicts)
                    callback(False)
                done()

            self._transaction(avatar).commit(
                oldFields, newFields, committed)

        queue.submit(operation)

    def creditJellybeans(self, avatar, amount, callback=None):
        """Atomically add a gameplay reward to pocket/bank balances."""
        if callback is None:
            callback = lambda success: None
        amount = max(0, int(amount))
        queue = self._queues.setdefault(avatar.doId, SerialOperationQueue())

        def operation(done):
            oldMoney = avatar.getMoney()
            oldBank = avatar.getBankMoney()
            newMoney = min(avatar.getMaxMoney(), oldMoney + amount)
            overflow = max(0, oldMoney + amount - newMoney)
            newBank = min(avatar.getMaxBankMoney(), oldBank + overflow)
            oldFields = {
                'setMoney': oldMoney,
                'setBankMoney': oldBank,
            }
            newFields = {
                'setMoney': newMoney,
                'setBankMoney': newBank,
            }

            def committed(success, conflicts):
                if success:
                    self._applyFields(avatar, newFields)
                else:
                    self._applyConflicts(avatar, conflicts)
                callback(success)
                done()

            self._transaction(avatar).commit(
                oldFields, newFields, committed)

        queue.submit(operation)

    def _planCatch(self, avatar, area):
        if len(avatar.fishTank) >= avatar.getMaxFishTank():
            return [FishGlobals.OverTankLimit, 0, 0, 0], {}, {}

        itemType = FishGlobals.BootItem
        roll = random.random() * 100.0
        for cutoff in FishGlobals.SortedProbabilityCutoffs:
            if roll <= cutoff:
                itemType = FishGlobals.ProbabilityDict[cutoff]
                break

        requested = self.requestedFish.pop(avatar.doId, None)
        if requested is not None:
            genus, species = requested
            weight = FishGlobals.getRandomWeight(
                genus, species, avatar.getFishingRod())
            return self._planFish(avatar, genus, species, weight)

        if itemType == FishGlobals.FishItem:
            try:
                success, genus, species, weight = (
                    FishGlobals.getRandomFishVitals(
                        area, avatar.getFishingRod()))
            except (AttributeError, KeyError, TypeError):
                success = False
            if not success:
                return [FishGlobals.Nothing, 0, 0, 0], {}, {}
            return self._planFish(avatar, genus, species, weight)

        if itemType == FishGlobals.JellybeanItem:
            reward = FishGlobals.Rod2JellybeanDict[avatar.getFishingRod()]
            oldMoney = avatar.getMoney()
            oldBank = avatar.getBankMoney()
            total = oldMoney + reward
            newMoney = min(total, avatar.getMaxMoney())
            newBank = min(
                avatar.getMaxBankMoney(),
                oldBank + max(0, total - newMoney))
            return (
                [itemType, reward, 0, 0],
                {'setMoney': oldMoney, 'setBankMoney': oldBank},
                {'setMoney': newMoney, 'setBankMoney': newBank})

        return [itemType, 0, 0, 0], {}, {}

    def _planFish(self, avatar, genus, species, weight):
        oldCollectionLists = avatar.getFishCollection()
        collection = FishCollection()
        collection.makeFromNetLists(*oldCollectionLists)
        oldTankLists = avatar.getFishTank()
        tank = FishTank()
        tank.makeFromNetLists(*oldTankLists)
        if len(tank) >= avatar.getMaxFishTank():
            return [FishGlobals.OverTankLimit, 0, 0, 0], {}, {}
        fish = FishBase(genus, species, weight)
        collectResult = collection.collectFish(fish)
        if collectResult == FishGlobals.COLLECT_NEW_ENTRY:
            itemType = FishGlobals.FishItemNewEntry
        elif collectResult == FishGlobals.COLLECT_NEW_RECORD:
            itemType = FishGlobals.FishItemNewRecord
        else:
            itemType = FishGlobals.FishItem
        tank.addFish(fish)
        return (
            [itemType, genus, species, weight],
            {'setFishCollection': tuple(oldCollectionLists),
             'setFishTank': tuple(oldTankLists)},
            {'setFishCollection': tuple(collection.getNetLists()),
             'setFishTank': tuple(tank.getNetLists())})

    def _transaction(self, avatar):
        return AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

    def _applyConflicts(self, avatar, conflicts):
        if conflicts:
            self._applyFields(avatar, conflicts)

    def _applyFields(self, avatar, fields):
        for fieldName, value in fields.items():
            if fieldName == 'setFishCollection':
                avatar.setFishCollection(*value)
                avatar.d_setFishCollection(*value)
            elif fieldName == 'setFishTank':
                avatar.setFishTank(*value)
                avatar.d_setFishTank(*value)
            elif fieldName == 'setFishingTrophies':
                avatar.setFishingTrophies(value)
                avatar.d_setFishingTrophies(value)
            elif fieldName == 'setMaxHp':
                avatar.setMaxHp(value)
                avatar.d_setMaxHp(value)
            elif fieldName == 'setMoney':
                avatar.setMoney(value)
                avatar.d_setMoney(value)
            elif fieldName == 'setBankMoney':
                avatar.setBankMoney(value)
                avatar.d_setBankMoney(value)
