import math
import time

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from direct.task.TaskManagerGlobal import taskMgr

from toontown.estate import GardenGlobals
from toontown.estate.DistributedAnimatedStatuaryAI import (
    DistributedAnimatedStatuaryAI)
from toontown.estate.DistributedChangingStatuaryAI import (
    DistributedChangingStatuaryAI)
from toontown.estate.DistributedFlowerAI import DistributedFlowerAI
from toontown.estate.DistributedGagTreeAI import DistributedGagTreeAI
from toontown.estate.DistributedGardenBoxAI import DistributedGardenBoxAI
from toontown.estate.DistributedGardenPlotAI import DistributedGardenPlotAI
from toontown.estate.DistributedStatuaryAI import DistributedStatuaryAI
from toontown.estate.DistributedToonStatuaryAI import (
    DistributedToonStatuaryAI)
from toontown.estate.EstateGardenState import (
    advanceDays, elapsedEpochDays, epochDay, getItem, normalizeItems, plantType,
    withItem, withoutItem)
from toontown.estate.EstateGardenTransactionAI import (
    GardenCrossObjectTransaction)
from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, chargeBalances)
from toontown.toon import InventoryBase


class DistributedGardenAI(DistributedObjectAI):
    """Persistent garden root and server-authoritative lifecycle manager."""

    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedGardenAI')
    FLOWER_BOXES = (0, 1, 2, 2, 2, 3, 3, 3, 4, 4)
    FLOWER_SLOTS = (0, 0, 0, 1, 2, 0, 1, 2, 0, 1)
    FLOWER_OFFSETS = {
        GardenGlobals.BOX_ONE: (0,),
        GardenGlobals.BOX_TWO: (-1.5, 1.5),
        GardenGlobals.BOX_THREE: (-3.4, 0, 3.5),
    }

    def __init__(self, air, ownerId=0, estate=None, ownerIndex=0):
        DistributedObjectAI.__init__(self, air)
        self.ownerId = ownerId
        self.estate = estate
        self.ownerIndex = int(ownerIndex)
        self.slotField = 'setSlot%sItems' % self.ownerIndex
        self.items = []
        self.boxes = []
        self.objects = []
        self.objectsByPlot = {}
        self._operationInFlight = False
        self._transaction = GardenCrossObjectTransaction(air)

    def load(self, zoneId):
        self.zoneId = zoneId
        if self.estate is None:
            return self.objects
        try:
            self.items = normalizeItems(
                getattr(self.estate, 'getSlot%sItems' % self.ownerIndex)())
        except ValueError as error:
            self.notify.warning(
                'Garden data for avatar %s is invalid and was not changed: %s' %
                (self.ownerId, error))
            self.items = []
        self._generateBoxes()
        avatar = self.air.doId2do.get(self.ownerId)
        if (avatar is not None and avatar.getEstateTransactionJournal()):
            self._transaction.recover(
                avatar, self.estate,
                lambda success, reason: self._afterRecovery(success, reason))
        else:
            self._advanceAndGenerate()
        return self.objects

    def _afterRecovery(self, success, reason):
        if success:
            self.items = normalizeItems(
                getattr(self.estate, 'getSlot%sItems' % self.ownerIndex)())
        elif reason not in ('unrelated-journal',):
            self.notify.warning(
                'Garden recovery for avatar %s is pending: %s' %
                (self.ownerId, reason))
        self._advanceAndGenerate()

    def _advanceAndGenerate(self):
        now = int(time.time())
        oldTimestamp = int(self.estate.getLastEpochTimeStamp())
        elapsedDays = max(0, (now - oldTimestamp) // 86400)
        if not elapsedDays:
            self._generatePlots()
            self._reconsiderOrganicBonus()
            return
        oldItems = normalizeItems(self.items)
        newItems = advanceDays(oldItems, elapsedDays)
        newTimestamp = oldTimestamp + elapsedDays * 86400
        transaction = AstronObjectTransaction(
            self.air, self.estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])

        def committed(success, conflicts):
            if success:
                self.items = newItems
                getattr(self.estate, 'setSlot%sItems' % self.ownerIndex)(
                    newItems)
                self.estate.setLastEpochTimeStamp(newTimestamp)
            else:
                self.notify.warning(
                    'Daily garden growth conflicted for avatar %s; using '
                    'the currently active state' % self.ownerId)
            self._generatePlots()
            self._reconsiderOrganicBonus()

        transaction.commit(
            {self.slotField: oldItems,
             'setLastEpochTimeStamp': oldTimestamp},
            {self.slotField: newItems,
             'setLastEpochTimeStamp': newTimestamp}, committed)

    def _generateBoxes(self):
        for boxIndex, (x, y, heading, typeIndex) in enumerate(
                GardenGlobals.estateBoxes[self.ownerIndex]):
            box = DistributedGardenBoxAI(
                self.air, ownerId=self.ownerId, typeIndex=typeIndex)
            box.setPlot(boxIndex)
            box.setPosition(x, y, 0)
            box.setHeading(heading)
            box.setOwnerIndex(self.ownerIndex)
            box.generateWithRequired(self.zoneId)
            self.boxes.append(box)
            self.objects.append(box)

    def _generatePlots(self):
        flowerIndex = 0
        for plotId, (x, y, heading, expectedType) in enumerate(
                GardenGlobals.estatePlots[self.ownerIndex]):
            item = getItem(self.items, plotId)
            if item is not None and plantType(item[0]) != expectedType:
                self.notify.warning(
                    'Ignoring garden item %s in incompatible plot %s' %
                    (item, plotId))
                item = None
            obj = self._makePlotObject(plotId, expectedType, item)
            if expectedType == GardenGlobals.FLOWER_TYPE:
                x, y, heading, z = self._flowerPosition(
                    flowerIndex, item is not None)
                flowerIndex += 1
            else:
                z = 0
            self._placeObject(obj, plotId, x, y, z, heading)

    def _makePlotObject(self, plotId, expectedType, item):
        if item is None:
            obj = DistributedGardenPlotAI(
                self.air, ownerId=self.ownerId, garden=self)
        elif expectedType == GardenGlobals.FLOWER_TYPE:
            obj = DistributedFlowerAI(
                self.air, self.ownerId, self, item)
        elif expectedType == GardenGlobals.GAG_TREE_TYPE:
            obj = DistributedGagTreeAI(
                self.air, self.ownerId, self, item)
        elif item[0] in GardenGlobals.ToonStatuaryTypeIndices:
            obj = DistributedToonStatuaryAI(
                self.air, self.ownerId, self, item)
        elif item[0] in GardenGlobals.ChangingStatuaryTypeIndices:
            obj = DistributedChangingStatuaryAI(
                self.air, self.ownerId, self, item)
        elif item[0] in GardenGlobals.AnimatedStatuaryTypeIndices:
            obj = DistributedAnimatedStatuaryAI(
                self.air, self.ownerId, self, item)
        else:
            obj = DistributedStatuaryAI(
                self.air, self.ownerId, self, item)
        return obj

    def _placeObject(self, obj, plotId, x, y, z, heading):
        obj.setPlot(plotId)
        obj.setOwnerIndex(self.ownerIndex)
        obj.setPosition(x, y, z)
        obj.setHeading(heading)
        obj.generateWithRequired(self.zoneId)
        self.objects.append(obj)
        self.objectsByPlot[plotId] = obj

    def _flowerPosition(self, flowerIndex, occupied):
        box = self.boxes[self.FLOWER_BOXES[flowerIndex]]
        offset = self.FLOWER_OFFSETS[box.getTypeIndex()][
            self.FLOWER_SLOTS[flowerIndex]]
        radians = math.radians(box.getHeading())
        x = box.getX() + math.cos(radians) * offset
        y = box.getY() + math.sin(radians) * offset
        return x, y, box.getHeading(), 1.5 if occupied else 1.2

    # Planting ---------------------------------------------------------
    def plantFlower(self, plot, species, variety, avId):
        attributes = GardenGlobals.PlantAttributes.get(species)
        if (not attributes or
                attributes.get('plantType') != GardenGlobals.FLOWER_TYPE or
                variety < 0 or variety >= len(attributes.get('varieties', ()) )):
            return self._reject(plot, avId, 'invalid flower')
        avatar = self._activeOwner(avId)
        if avatar is None or not self._emptyPlot(plot, GardenGlobals.FLOWER_TYPE):
            return self._reject(plot, avId, 'invalid flower plot')
        cost = GardenGlobals.getNumBeansRequired(species, variety)
        if cost < 0 or GardenGlobals.getShovelPower(
                avatar.getShovel(), avatar.getShovelSkill()) < cost:
            return self._reject(plot, avId, 'flower recipe exceeds shovel')
        balances = chargeBalances(
            avatar.getMoney(), avatar.getBankMoney(), cost)
        if balances is None:
            return self._reject(plot, avId, 'not enough beans')
        self._commitPlant(
            plot, [species, plot.getPlot(), 0, 0, variety], avatar,
            {'setMoney': avatar.getMoney(),
             'setBankMoney': avatar.getBankMoney()},
            {'setMoney': balances[0], 'setBankMoney': balances[1]})

    def plantGagTree(self, plot, track, level, avId):
        avatar = self._activeOwner(avId)
        if (avatar is None or not self._emptyPlot(
                plot, GardenGlobals.GAG_TREE_TYPE) or
                track < 0 or track >= 7 or level < 0 or level >= 7):
            return self._reject(plot, avId, 'invalid gag tree')
        for priorLevel in range(level):
            if not self._hasTree(track, priorLevel):
                return self._reject(plot, avId, 'missing prerequisite tree')
        if self._hasTree(track, level):
            return self._reject(plot, avId, 'duplicate gag tree')
        if avatar.inventory.numItem(track, level) <= 0:
            return self._reject(plot, avId, 'selected gag not carried')
        oldInventory = avatar.getInventory()
        inventory = InventoryBase.InventoryBase(avatar, oldInventory)
        inventory.inventory[track][level] -= 1
        inventory.calcTotalProps()
        newInventory = inventory.makeNetString()
        self._commitPlant(
            plot,
            [GardenGlobals.getTreeTypeIndex(track, level),
             plot.getPlot(), 0, 0, 0],
            avatar, {'setInventory': oldInventory},
            {'setInventory': newInventory})

    def plantStatuary(self, plot, species, dnaCode, avId):
        avatar = self._activeOwner(avId)
        attributes = GardenGlobals.PlantAttributes.get(species)
        if (avatar is None or not self._emptyPlot(
                plot, GardenGlobals.STATUARY_TYPE) or not attributes or
                attributes.get('plantType') != GardenGlobals.STATUARY_TYPE or
                dnaCode < 0 or dnaCode > 65535):
            return self._reject(plot, avId, 'invalid statuary')
        gardenItem = species - 100
        if gardenItem == 134:
            gardenItem = 135
        oldSpecials = [list(value) for value in avatar.getGardenSpecials()]
        newSpecials = self._removeSpecial(oldSpecials, gardenItem)
        if newSpecials is None:
            return self._reject(plot, avId, 'statuary item not owned')
        recipeKey = attributes.get('varieties', ((-1,),))[0][0]
        cost = len(GardenGlobals.Recipes.get(recipeKey, {}).get('beans', ()))
        balances = chargeBalances(
            avatar.getMoney(), avatar.getBankMoney(), cost)
        if balances is None:
            return self._reject(plot, avId, 'not enough beans')
        self._commitPlant(
            plot, [species, plot.getPlot(), 0, 0, dnaCode], avatar,
            {'setMoney': avatar.getMoney(),
             'setBankMoney': avatar.getBankMoney(),
             'setGardenSpecials': oldSpecials},
            {'setMoney': balances[0], 'setBankMoney': balances[1],
             'setGardenSpecials': newSpecials})

    def plantNothing(self, plot, burntBeans, avId):
        avatar = self._activeOwner(avId)
        burntBeans = max(0, min(int(burntBeans), 8))
        if avatar is None:
            return self._reject(plot, avId, 'invalid failed recipe')
        balances = chargeBalances(
            avatar.getMoney(), avatar.getBankMoney(), burntBeans)
        if balances is None:
            return self._reject(plot, avId, 'not enough beans')
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def committed(success, conflicts):
            if success:
                avatar.setMoney(balances[0])
                avatar.d_setMoney(balances[0])
                avatar.setBankMoney(balances[1])
                avatar.d_setBankMoney(balances[1])
            plot.d_setMovie(GardenGlobals.MOVIE_PLANT_REJECTED, avId)

        transaction.commit(
            {'setMoney': avatar.getMoney(),
             'setBankMoney': avatar.getBankMoney()},
            {'setMoney': balances[0], 'setBankMoney': balances[1]},
            committed)

    def _commitPlant(self, plot, item, avatar, toonOld, toonNew):
        if self._operationInFlight or avatar.getEstateTransactionJournal():
            return self._reject(plot, avatar.doId, 'garden transaction busy')
        oldItems = normalizeItems(self.items)
        newItems = withItem(oldItems, item)
        self._operationInFlight = True
        plot.d_setMovie(GardenGlobals.MOVIE_PLANT, avatar.doId)

        def committed(success, reason):
            self._operationInFlight = False
            if not success:
                self.notify.warning(
                    'Garden plant for avatar %s did not finish: %s' %
                    (avatar.doId, reason))
                if reason not in ('finalize-pending-recovery',
                                  'estate-conflict-pending-recovery'):
                    plot.d_setMovie(
                        GardenGlobals.MOVIE_PLANT_REJECTED, avatar.doId)
                return
            self.items = newItems
            taskMgr.doMethodLater(
                7.0, self._finishPlant,
                self.uniqueName('finish-plant-%s' % plot.getPlot()),
                extraArgs=[plot, item, avatar.doId], appendTask=True)

        self._transaction.begin(
            avatar, self.estate, self.slotField, oldItems, newItems,
            toonOld, toonNew,
            {'operation': 'plant', 'hardPoint': plot.getPlot()}, committed)

    def _finishPlant(self, plot, item, avId, task):
        if plot not in self.objects:
            return task.done
        x, y, z = plot.getPosition()
        heading = plot.getHeading()
        plotId = plot.getPlot()
        expectedType = GardenGlobals.whatCanBePlanted(
            self.ownerIndex, plotId)
        if expectedType == GardenGlobals.FLOWER_TYPE:
            x, y, heading, z = self._flowerPosition(
                self._flowerIndex(plotId), True)
        self._deleteObject(plot)
        obj = self._makePlotObject(
            plotId, expectedType, item)
        self._placeObject(obj, plotId, x, y, z, heading)
        obj.d_setMovie(GardenGlobals.MOVIE_FINISHPLANTING, avId)
        obj.d_setMovie(GardenGlobals.MOVIE_CLEAR, avId)
        self._reconsiderOrganicBonus()
        return task.done

    # Existing plant actions ------------------------------------------
    def requestWater(self, plant, avId):
        avatar = self._activeOwner(avId)
        item = getItem(self.items, plant.getPlot())
        if avatar is None or item is None or self._operationInFlight:
            plant._wateringAvatarId = 0
            return self._reject(plant, avId, 'invalid watering')
        attributes = GardenGlobals.PlantAttributes.get(item[0], {})
        power = GardenGlobals.getWateringCanPower(
            avatar.getWateringCan(), avatar.getWateringCanSkill())
        newItem = list(item)
        newItem[2] = min(
            int(attributes.get('maxWaterLevel', 20)), item[2] + power)
        oldItems = normalizeItems(self.items)
        newItems = withItem(oldItems, newItem)
        transaction = AstronObjectTransaction(
            self.air, self.estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])
        self._operationInFlight = True

        def committed(success, conflicts):
            self._operationInFlight = False
            if not success:
                plant._wateringAvatarId = 0
                return self._reject(plant, avId, 'watering conflict')
            self.items = newItems
            getattr(self.estate, 'setSlot%sItems' % self.ownerIndex)(newItems)
            plant.applyItem(newItem)
            plant.d_setMovie(GardenGlobals.MOVIE_WATER, avId)

        transaction.commit(
            {self.slotField: oldItems}, {self.slotField: newItems}, committed)

    def finishWater(self, plant, avId):
        avatar = self._activeOwner(avId)
        if avatar is None:
            return
        oldCan = avatar.getWateringCan()
        oldSkill = avatar.getWateringCanSkill()
        threshold = GardenGlobals.WateringCanAttributes[oldCan]['skillPts']
        newCan = oldCan
        newSkill = oldSkill + 1
        if newSkill >= threshold:
            if oldCan < GardenGlobals.MAX_WATERING_CANS - 1:
                newCan = oldCan + 1
                newSkill = 0
            else:
                newSkill = threshold - 1
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def committed(success, conflicts):
            if success:
                avatar.setWateringCan(newCan)
                avatar.d_setWateringCan(newCan)
                avatar.setWateringCanSkill(newSkill)
                avatar.d_setWateringCanSkill(newSkill)
            plant.d_setMovie(GardenGlobals.MOVIE_CLEAR, avId)

        transaction.commit(
            {'setWateringCan': oldCan,
             'setWateringCanSkill': oldSkill},
            {'setWateringCan': newCan,
             'setWateringCanSkill': newSkill}, committed)

    def requestRemove(self, plant, avId):
        item = getItem(self.items, plant.getPlot())
        avatar = self._activeOwner(avId)
        if (item is None or avatar is None or
                self._operationInFlight):
            return self._reject(plant, avId, 'invalid garden removal')
        oldItems = normalizeItems(self.items)
        newItems = withoutItem(oldItems, plant.getPlot())
        if (isinstance(plant, DistributedFlowerAI) and
                item[2] >= 0 and item[3] >=
                GardenGlobals.PlantAttributes[item[0]][
                    'growthThresholds'][-1]):
            return self._pickFlower(
                plant, avatar, item, oldItems, newItems)
        transaction = AstronObjectTransaction(
            self.air, self.estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])
        self._operationInFlight = True
        plant.d_setMovie(GardenGlobals.MOVIE_REMOVE, avId)

        def committed(success, conflicts):
            self._operationInFlight = False
            if not success:
                return self._reject(plant, avId, 'garden removal conflict')
            self.items = newItems
            getattr(self.estate, 'setSlot%sItems' % self.ownerIndex)(newItems)
            taskMgr.doMethodLater(
                7.0, self._finishRemove,
                self.uniqueName('finish-remove-%s' % plant.getPlot()),
                extraArgs=[plant, avId], appendTask=True)

        transaction.commit(
            {self.slotField: oldItems}, {self.slotField: newItems}, committed)

    def _pickFlower(self, plant, avatar, item, oldItems, newItems):
        oldBasket = [list(values) for values in avatar.getFlowerBasket()]
        if len(oldBasket[0]) >= avatar.getMaxFlowerBasket():
            return self._reject(plant, avatar.doId, 'flower basket full')
        newBasket = [list(oldBasket[0]), list(oldBasket[1])]
        newBasket[0].append(item[0])
        newBasket[1].append(item[4])
        oldFields = {'setFlowerBasket': oldBasket}
        newFields = {'setFlowerBasket': newBasket}

        beansRequired = GardenGlobals.getNumBeansRequired(item[0], item[4])
        shovel = avatar.getShovel()
        shovelSkill = avatar.getShovelSkill()
        if GardenGlobals.getShovelPower(shovel, shovelSkill) == beansRequired:
            value = GardenGlobals.PlantAttributes[item[0]][
                'varieties'][item[4]][2]
            threshold = GardenGlobals.ShovelAttributes[shovel]['skillPts']
            newShovel = shovel
            newSkill = shovelSkill + value
            if newSkill >= threshold:
                if shovel < GardenGlobals.MAX_SHOVELS - 1:
                    newShovel = shovel + 1
                    newSkill = 0
                else:
                    newSkill = threshold - 1
            oldFields.update({
                'setShovel': shovel,
                'setShovelSkill': shovelSkill,
            })
            newFields.update({
                'setShovel': newShovel,
                'setShovelSkill': newSkill,
            })

        self._operationInFlight = True
        plant.d_setMovie(GardenGlobals.MOVIE_REMOVE, avatar.doId)

        def committed(success, reason):
            self._operationInFlight = False
            if not success:
                return self._reject(
                    plant, avatar.doId, 'flower pick %s' % reason)
            self.items = newItems
            taskMgr.doMethodLater(
                7.0, self._finishRemove,
                self.uniqueName('finish-remove-%s' % plant.getPlot()),
                extraArgs=[plant, avatar.doId], appendTask=True)

        self._transaction.begin(
            avatar, self.estate, self.slotField, oldItems, newItems,
            oldFields, newFields,
            {'operation': 'pick-flower',
             'hardPoint': plant.getPlot()}, committed)
        return True

    def _finishRemove(self, plant, avId, task):
        if plant not in self.objects:
            return task.done
        x, y, z = plant.getPosition()
        heading = plant.getHeading()
        plotId = plant.getPlot()
        if GardenGlobals.whatCanBePlanted(
                self.ownerIndex, plotId) == GardenGlobals.FLOWER_TYPE:
            x, y, heading, z = self._flowerPosition(
                self._flowerIndex(plotId), False)
        self._deleteObject(plant)
        plot = DistributedGardenPlotAI(
            self.air, ownerId=self.ownerId, garden=self)
        self._placeObject(plot, plotId, x, y, z, heading)
        plot.d_setMovie(GardenGlobals.MOVIE_FINISHREMOVING, avId)
        plot.d_setMovie(GardenGlobals.MOVIE_CLEAR, avId)
        self._reconsiderOrganicBonus()
        return task.done

    def requestHarvest(self, tree, avId):
        avatar = self._activeOwner(avId)
        item = getItem(self.items, tree.getPlot())
        if avatar is None or item is None or self._operationInFlight:
            return self._reject(tree, avId, 'invalid tree harvest')
        attributes = GardenGlobals.PlantAttributes.get(item[0], {})
        if (item[2] < 0 or item[3] < attributes.get(
                'growthThresholds', (0, 0, 0))[-1]):
            return self._reject(tree, avId, 'tree is not fruiting')
        today = epochDay(time.time())
        if item[4] and elapsedEpochDays(item[4], today) < 1:
            return self._reject(tree, avId, 'tree already harvested today')
        track, level = GardenGlobals.getTreeTrackAndLevel(item[0])
        oldInventory = avatar.getInventory()
        inventory = InventoryBase.InventoryBase(avatar, oldInventory)
        harvested = 0
        while harvested < int(attributes.get('maxFruit', 9)):
            if inventory.addItem(track, level) <= 0:
                break
            harvested += 1
        if not harvested:
            return self._reject(tree, avId, 'inventory cannot hold fruit')
        newItem = list(item)
        newItem[4] = today
        oldItems = normalizeItems(self.items)
        newItems = withItem(oldItems, newItem)
        self._operationInFlight = True

        def committed(success, reason):
            self._operationInFlight = False
            if not success:
                return self._reject(tree, avId, 'tree harvest %s' % reason)
            self.items = newItems
            tree.applyItem(newItem)
            tree.d_setMovie(GardenGlobals.MOVIE_HARVEST, avId)

        self._transaction.begin(
            avatar, self.estate, self.slotField, oldItems, newItems,
            {'setInventory': oldInventory},
            {'setInventory': inventory.makeNetString()},
            {'operation': 'harvest', 'hardPoint': tree.getPlot()}, committed)

    # Helpers ----------------------------------------------------------
    def _activeOwner(self, avId):
        avatar = self.air.doId2do.get(avId)
        if (avId != self.ownerId or avatar is None or
                getattr(avatar, 'zoneId', 0) != self.zoneId):
            if avId:
                self.air.writeServerEvent(
                    'suspicious', avId,
                    'Unauthorized garden action in estate owned by %s' %
                    self.ownerId)
            return None
        return avatar

    def _emptyPlot(self, plot, expectedType):
        return (plot in self.objects and
                isinstance(plot, DistributedGardenPlotAI) and
                GardenGlobals.whatCanBePlanted(
                    self.ownerIndex, plot.getPlot()) == expectedType and
                getItem(self.items, plot.getPlot()) is None)

    def _hasTree(self, track, level):
        typeIndex = GardenGlobals.getTreeTypeIndex(track, level)
        return any(item[0] == typeIndex and
                   plantType(item[0]) == GardenGlobals.GAG_TREE_TYPE
                   for item in self.items)

    def _flowerIndex(self, plotId):
        index = 0
        for currentPlot in range(plotId):
            if GardenGlobals.whatCanBePlanted(
                    self.ownerIndex, currentPlot) == GardenGlobals.FLOWER_TYPE:
                index += 1
        return index

    @staticmethod
    def _removeSpecial(specials, index):
        result = []
        found = False
        for specialIndex, count in specials:
            if specialIndex == index and count > 0 and not found:
                found = True
                if count > 1:
                    result.append([specialIndex, count - 1])
            else:
                result.append([specialIndex, count])
        result.sort()
        return result if found else None

    def _reject(self, obj, avId, reason):
        self.notify.info(
            'Rejected garden action for avatar %s: %s' % (avId, reason))
        obj.d_setMovie(GardenGlobals.MOVIE_PLANT_REJECTED, avId)
        return False

    def _deleteObject(self, obj):
        if obj in self.objects:
            self.objects.remove(obj)
        self.objectsByPlot.pop(obj.getPlot(), None)
        obj.requestDelete()

    def _reconsiderOrganicBonus(self):
        avatar = self.air.doId2do.get(self.ownerId)
        if avatar is None:
            return
        bonus = [-1] * 7
        for track in range(7):
            for level in range(7):
                treeItem = next((item for item in self.items
                                 if item[0] == GardenGlobals.getTreeTypeIndex(
                                     track, level)), None)
                if treeItem is None:
                    break
                thresholds = GardenGlobals.PlantAttributes[
                    treeItem[0]]['growthThresholds']
                if treeItem[2] < 0 or treeItem[3] < thresholds[1]:
                    break
                bonus[track] = level
        avatar.b_setTrackBonusLevel(bonus)

    def delete(self):
        for obj in list(self.objects):
            obj.requestDelete()
        self.objects = []
        self.objectsByPlot = {}
        DistributedObjectAI.delete(self)
