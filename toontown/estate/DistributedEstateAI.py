from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from toontown.estate import HouseGlobals
from toontown.estate import GardenGlobals
from toontown.estate.FlowerCollection import FlowerCollection
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.toonbase import ToontownGlobals
import time


class DistributedEstateAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedEstateAI')

    def __init__(self, air, ownerId=0, zoneId=0):
        DistributedObjectAI.__init__(self, air)
        now = int(time.time())
        self.ownerId = ownerId
        self.zoneId = zoneId
        self.estateType = 0
        self.closestHouse = 0
        self.dawnTime = now % HouseGlobals.DAY_NIGHT_PERIOD
        self.decorData = []
        self.lastEpochTimeStamp = now
        self.rentalTimeStamp = 0
        self.rentalType = 0
        self.slotToonIds = [ownerId, 0, 0, 0, 0, 0]
        self.slotItems = [[], [], [], [], [], []]
        self.idList = [ownerId] if ownerId else []
        self.clouds = 0
        self._flowerSaleInFlight = set()

    def setClientReady(self):
        return

    def setEstateType(self, estateType):
        self.estateType = estateType

    def getEstateType(self):
        return self.estateType

    def setClosestHouse(self, houseIndex):
        self.closestHouse = houseIndex

    def getClosestHouse(self):
        return self.closestHouse

    def requestServerTime(self):
        avId = self.air.getAvatarIdFromSender()
        if avId:
            serverTime = int(time.time()) % HouseGlobals.DAY_NIGHT_PERIOD
            self.sendUpdateToAvatarId(avId, 'setServerTime', [serverTime])

    def setDawnTime(self, dawnTime):
        self.dawnTime = dawnTime

    def getDawnTime(self):
        return self.dawnTime

    def setDecorData(self, decorData):
        self.decorData = decorData

    def getDecorData(self):
        return self.decorData

    def setLastEpochTimeStamp(self, timestamp):
        self.lastEpochTimeStamp = timestamp

    def getLastEpochTimeStamp(self):
        return self.lastEpochTimeStamp

    def setRentalTimeStamp(self, timestamp):
        self.rentalTimeStamp = timestamp

    def d_setRentalTimeStamp(self, timestamp):
        self.sendUpdate('setRentalTimeStamp', [timestamp])

    def b_setRentalTimeStamp(self, timestamp):
        self.setRentalTimeStamp(timestamp)
        self.d_setRentalTimeStamp(timestamp)

    def getRentalTimeStamp(self):
        return self.rentalTimeStamp

    def setRentalType(self, rentalType):
        self.rentalType = rentalType

    def d_setRentalType(self, rentalType):
        self.sendUpdate('setRentalType', [rentalType])

    def b_setRentalType(self, rentalType):
        self.setRentalType(rentalType)
        self.d_setRentalType(rentalType)

    def getRentalType(self):
        return self.rentalType

    def setIdList(self, idList):
        self.idList = idList

    def getIdList(self):
        return self.idList

    def setClouds(self, clouds):
        self.clouds = clouds

    def d_setClouds(self, clouds):
        self.sendUpdate('setClouds', [clouds])

    def b_setClouds(self, clouds):
        self.setClouds(clouds)
        self.d_setClouds(clouds)

    def getClouds(self):
        return self.clouds

    def completeFlowerSale(self, sell):
        if not sell:
            return
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId or
                avId in self._flowerSaleInFlight):
            self.air.writeServerEvent(
                'suspicious', avId,
                'Invalid or overlapping estate flower sale')
            return
        oldBasket = tuple(avatar.flowerBasket.getNetLists())
        if not oldBasket[0]:
            return
        oldCollection = tuple(avatar.flowerCollection.getNetLists())
        collection = FlowerCollection()
        collection.makeFromNetLists(*oldCollection)
        earnings = 0
        for flower in avatar.flowerBasket.getFlower():
            collection.collectFlower(flower)
            earnings += flower.getValue()
        newCollection = tuple(collection.getNetLists())
        oldMoney = avatar.getMoney()
        oldBank = avatar.getBankMoney()
        total = oldMoney + earnings
        newMoney = min(total, avatar.getMaxMoney())
        newBank = min(
            avatar.getMaxBankMoney(),
            oldBank + max(0, total - newMoney))
        oldTrophies = list(avatar.getGardenTrophies())
        trophyCount = len(collection) // 10
        newTrophies = list(range(max(len(oldTrophies), trophyCount)))
        oldMaxHp = avatar.getMaxHp()
        newMaxHp = min(
            ToontownGlobals.MaxHpLimit,
            oldMaxHp + max(0, len(newTrophies) - len(oldTrophies)))
        oldFields = {
            'setFlowerBasket': oldBasket,
            'setFlowerCollection': oldCollection,
            'setMoney': oldMoney,
            'setBankMoney': oldBank,
            'setGardenTrophies': oldTrophies,
            'setMaxHp': oldMaxHp,
        }
        newFields = {
            'setFlowerBasket': ([], []),
            'setFlowerCollection': newCollection,
            'setMoney': newMoney,
            'setBankMoney': newBank,
            'setGardenTrophies': newTrophies,
            'setMaxHp': newMaxHp,
        }
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._flowerSaleInFlight.add(avId)

        def committed(success, conflicts):
            self._flowerSaleInFlight.discard(avId)
            if not success:
                if conflicts:
                    self._applyFlowerSaleFields(avatar, conflicts)
                return
            self._applyFlowerSaleFields(avatar, newFields)
            if newMaxHp > oldMaxHp:
                avatar.toonUp(newMaxHp)
                self.sendUpdate('awardedTrophy', [avId])

        transaction.commit(oldFields, newFields, committed)

    @staticmethod
    def _applyFlowerSaleFields(avatar, fields):
        for fieldName, value in fields.items():
            if fieldName == 'setFlowerBasket':
                avatar.setFlowerBasket(*value)
                avatar.d_setFlowerBasket(*value)
            elif fieldName == 'setFlowerCollection':
                avatar.setFlowerCollection(*value)
                avatar.d_setFlowerCollection(*value)
            elif fieldName == 'setMoney':
                avatar.setMoney(value)
                avatar.d_setMoney(value)
            elif fieldName == 'setBankMoney':
                avatar.setBankMoney(value)
                avatar.d_setBankMoney(value)
            elif fieldName == 'setGardenTrophies':
                avatar.setGardenTrophies(value)
                avatar.d_setGardenTrophies(value)
            elif fieldName == 'setMaxHp':
                avatar.setMaxHp(value)
                avatar.d_setMaxHp(value)

    def _setSlotToonId(self, slot, toonId):
        self.slotToonIds[slot] = toonId

    def _getSlotToonId(self, slot):
        return self.slotToonIds[slot]

    def _setSlotItems(self, slot, items):
        self.slotItems[slot] = items

    def _getSlotItems(self, slot):
        return self.slotItems[slot]


def _makeSlotAccessors(slot):
    def setToonId(self, toonId):
        self._setSlotToonId(slot, toonId)

    def getToonId(self):
        return self._getSlotToonId(slot)

    def setItems(self, items):
        self._setSlotItems(slot, items)

    def getItems(self):
        return self._getSlotItems(slot)

    return setToonId, getToonId, setItems, getItems


for _slot in range(6):
    _setToonId, _getToonId, _setItems, _getItems = _makeSlotAccessors(_slot)
    setattr(DistributedEstateAI, 'setSlot%sToonId' % _slot, _setToonId)
    setattr(DistributedEstateAI, 'getSlot%sToonId' % _slot, _getToonId)
    setattr(DistributedEstateAI, 'setSlot%sItems' % _slot, _setItems)
    setattr(DistributedEstateAI, 'getSlot%sItems' % _slot, _getItems)
