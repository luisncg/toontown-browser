import time

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from toontown.building import DoorTypes
from toontown.estate import HouseGlobals
from toontown.estate.DistributedEstateAI import DistributedEstateAI
from toontown.estate.DistributedCannonAI import DistributedCannonAI
from toontown.estate.DistributedTargetAI import DistributedTargetAI
from toontown.estate.DistributedGardenAI import DistributedGardenAI
from toontown.estate.DistributedHouseAI import DistributedHouseAI
from toontown.estate.DistributedHouseDoorAI import DistributedHouseDoorAI
from toontown.estate.DistributedHouseInteriorAI import DistributedHouseInteriorAI
from toontown.estate.DistributedFurnitureManagerAI import DistributedFurnitureManagerAI
from toontown.estate.DistributedMailboxAI import DistributedMailboxAI
from toontown.estate import CannonGlobals
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.fishing.DistributedFishingPondAI import DistributedFishingPondAI
from toontown.safezone.DistributedFishingSpotAI import DistributedFishingSpotAI
from toontown.toonbase import ToontownGlobals


class EstateManagerAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('EstateManagerAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.ownerToZone = {}
        self.zone2owner = {}
        self.estate = {}
        self.houses = {}
        self.houseInteriors = {}
        self.houseZones = {}
        self.houseDoors = {}
        self.mailboxes = {}
        self.furnitureManagers = {}
        self.gardens = {}
        self.gardenObjects = {}
        self.fishingPonds = {}
        self.fishingObjects = {}
        self.cannonObjects = {}
        self._rentalApplied = {}
        self.ownerPetIds = {}
        self.pets = {}
        self.loadingOwners = set()
        self.pendingEstateRequests = {}

    def getEstateZone(self, ownerId, ownerName):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if not avId or avatar is None:
            self.notify.warning(
                'Ignoring estate request from an unknown avatar: %s' % avId)
            return

        if ownerId != avId and not self._avatarHasFriend(avatar, ownerId):
            self.air.writeServerEvent(
                'suspicious', avId,
                'EstateManagerAI.getEstateZone requested non-friend avatar: %s' %
                ownerId)
            self.sendUpdateToAvatarId(avId, 'setEstateZone', [0, 0])
            return

        self.pendingEstateRequests.setdefault(ownerId, []).append(avId)
        if ownerId in self.ownerToZone:
            self._finishEstateRequests(ownerId)
            return

        if ownerId in self.loadingOwners:
            return

        self.loadingOwners.add(ownerId)
        owner = self.air.doId2do.get(ownerId)
        if owner is not None:
            accountId = owner.DISLid
            self._queryOwnerAccount(
                ownerId, accountId, owner.getName() or ownerName or '', owner)
        else:
            self._queryOfflineOwner(ownerId, ownerName)

    def _avatarHasFriend(self, avatar, friendId):
        for friend in avatar.getFriendsList():
            if friend and friend[0] == friendId:
                return True
        return False

    def _queryOfflineOwner(self, ownerId, ownerName):
        toonDclass = self.air.dclassesByName['DistributedToonAI']

        def handleOwner(dclass, fields):
            if dclass != toonDclass or not fields:
                self._failEstateLoad(ownerId, 'owner Toon record was not found')
                return
            accountId = self._single(fields.get('setDISLid'), 0)
            storedName = self._single(fields.get('setName'), ownerName or '')
            self.ownerPetIds[ownerId] = self._single(
                fields.get('setPetId'), 0)
            self._queryOwnerAccount(ownerId, accountId, storedName, None)

        self.air.dbInterface.queryObject(
            self.air.dbId, ownerId, handleOwner, toonDclass,
            ('setDISLid', 'setName', 'setPetId'))

    def _queryOwnerAccount(self, ownerId, accountId, ownerName, ownerAvatar):
        if not accountId:
            self._failEstateLoad(ownerId, 'owner has no account database id')
            return

        if ownerAvatar is not None:
            getPetId = getattr(ownerAvatar, 'getPetId', None)
            self.ownerPetIds[ownerId] = getPetId() if getPetId else 0

        accountDclass = self._accountDclass()

        def handleAccount(dclass, fields):
            if dclass != accountDclass or fields is None:
                self._failEstateLoad(ownerId, 'account record was not found')
                return

            estateId = fields.get('ESTATE_ID', 0) or 0
            houseIds = list(fields.get('HOUSE_ID_SET', []) or [])[:6]
            houseIds += [0] * (6 - len(houseIds))
            avatarIds = list(fields.get('ACCOUNT_AV_SET', []) or [])[:6]
            avatarIds += [0] * (6 - len(avatarIds))

            if estateId and all(houseIds):
                self._activatePersistentEstate(
                    ownerId, accountId, estateId, houseIds, avatarIds,
                    ownerName, ownerAvatar)
            else:
                self._createMissingHouses(
                    ownerId, accountId, estateId, houseIds, avatarIds,
                    ownerName, ownerAvatar, 0)

        self.air.dbInterface.queryObject(
            self.air.dbId, accountId, handleAccount)

    def _createMissingHouses(self, ownerId, accountId, estateId, houseIds,
                             avatarIds, ownerName, ownerAvatar, plot):
        if plot >= 6:
            if estateId:
                self._storePersistentIdsAndActivate(
                    ownerId, accountId, estateId, houseIds, avatarIds,
                    ownerName, ownerAvatar)
            else:
                self._createEstateRecord(
                    ownerId, accountId, houseIds, avatarIds,
                    ownerName, ownerAvatar)
            return

        if houseIds[plot]:
            self._createMissingHouses(
                ownerId, accountId, estateId, houseIds, avatarIds,
                ownerName, ownerAvatar, plot + 1)
            return

        houseDclass = self.air.dclassesByName['DistributedHouseAI']
        toonId = avatarIds[plot]
        if ownerId not in avatarIds and plot == 0:
            toonId = ownerId
        houseName = ownerName if toonId == ownerId else ''
        houseFields = {
            'setHouseType': (HouseGlobals.HOUSE_DEFAULT,),
            'setGardenPos': (plot,),
            'setAvatarId': (toonId,),
            'setName': (houseName,),
            'setColor': (plot % len(HouseGlobals.houseColors),),
            'setAtticItems': (b'',),
            'setInteriorItems': (b'',),
            'setAtticWallpaper': (b'',),
            'setInteriorWallpaper': (b'',),
            'setAtticWindows': (b'',),
            'setInteriorWindows': (b'',),
            'setDeletedItems': (b'',),
        }

        def handleHouseCreated(houseId):
            if not houseId:
                self._failEstateLoad(ownerId, 'house record creation failed')
                return
            houseIds[plot] = houseId
            self._createMissingHouses(
                ownerId, accountId, estateId, houseIds, avatarIds,
                ownerName, ownerAvatar, plot + 1)

        self.air.dbInterface.createObject(
            self.air.dbId, houseDclass, houseFields, handleHouseCreated)

    def _createEstateRecord(self, ownerId, accountId, houseIds, avatarIds,
                            ownerName, ownerAvatar):
        now = int(time.time())
        estateDclass = self.air.dclassesByName['DistributedEstateAI']
        estateFields = {
            'setEstateType': (0,),
            'setDecorData': ([],),
            'setLastEpochTimeStamp': (now,),
            'setRentalTimeStamp': (0,),
            'setRentalType': (0,),
        }
        estateAvatarIds = self._estateAvatarIds(ownerId, avatarIds)
        for slot in range(6):
            estateFields['setSlot%sToonId' % slot] = (
                estateAvatarIds[slot],)
            estateFields['setSlot%sItems' % slot] = ([],)

        def handleEstateCreated(estateId):
            if not estateId:
                self._failEstateLoad(ownerId, 'estate record creation failed')
                return
            self._storePersistentIdsAndActivate(
                ownerId, accountId, estateId, houseIds, avatarIds,
                ownerName, ownerAvatar)

        self.air.dbInterface.createObject(
            self.air.dbId, estateDclass, estateFields, handleEstateCreated)

    def _storePersistentIdsAndActivate(self, ownerId, accountId, estateId,
                                       houseIds, avatarIds, ownerName,
                                       ownerAvatar):
        self.air.dbInterface.updateObject(
            self.air.dbId, accountId,
            self._accountDclass(),
            {'ESTATE_ID': estateId, 'HOUSE_ID_SET': houseIds})
        if ownerAvatar is not None:
            ownerHouseId = self._ownerHouseId(ownerId, houseIds, avatarIds)
            if ownerAvatar.getHouseId() != ownerHouseId:
                ownerAvatar.b_setHouseId(ownerHouseId)
        self.notify.info(
            'Stored persistent estate %s and houses %s for account %s' %
            (estateId, houseIds, accountId))
        self._activatePersistentEstate(
            ownerId, accountId, estateId, houseIds, avatarIds,
            ownerName, ownerAvatar)

    def _activatePersistentEstate(self, ownerId, accountId, estateId, houseIds,
                                  avatarIds, ownerName, ownerAvatar):
        zoneId = self.air.allocateZone(ownerId)
        self.ownerToZone[ownerId] = zoneId
        self.zone2owner[zoneId] = ownerId

        now = int(time.time())
        estateDclass = self.air.dclassesByName['DistributedEstateAI']
        self._activateObject(
            estateId, zoneId, estateDclass,
            {'setDawnTime': (now % HouseGlobals.DAY_NIGHT_PERIOD,),
             'setClouds': (0,)})

        houseDclass = self.air.dclassesByName['DistributedHouseAI']
        for plot, houseId in enumerate(houseIds):
            self._activateObject(
                houseId, zoneId, houseDclass,
                {'setHousePos': (plot,), 'setCannonEnabled': (0,)})

        taskMgr.doMethodLater(
            0.1, self._pollActivatedEstate,
            'poll-persistent-estate-%s' % ownerId,
            extraArgs=[ownerId, accountId, estateId, houseIds, avatarIds,
                       ownerName, ownerAvatar, zoneId, 0],
            appendTask=True)

    def _activateObject(self, doId, zoneId, dclass, defaults):
        obj = self.air.doId2do.get(doId)
        if obj is not None:
            obj.b_setLocation(self.air.districtId, zoneId)
            return
        self.air.sendActivate(
            doId, self.air.districtId, zoneId, dclass, defaults)

    def _pollActivatedEstate(self, ownerId, accountId, estateId, houseIds,
                             avatarIds, ownerName, ownerAvatar, zoneId,
                             attempt, task):
        estate = self.air.doId2do.get(estateId)
        houses = [self.air.doId2do.get(houseId) for houseId in houseIds]
        if estate is not None and all(houses):
            self._finishActivatedEstate(
                ownerId, estate, houses, avatarIds, zoneId, ownerAvatar)
            return Task.done
        if attempt >= 100:
            self.ownerToZone.pop(ownerId, None)
            self.zone2owner.pop(zoneId, None)
            self._failEstateLoad(ownerId, 'persistent objects did not activate')
            return Task.done
        task.delayTime = 0.1
        task.setArgs([
            ownerId, accountId, estateId, houseIds, avatarIds, ownerName,
            ownerAvatar, zoneId, attempt + 1])
        return Task.again

    def _finishActivatedEstate(self, ownerId, estate, houses, avatarIds,
                               zoneId, ownerAvatar):
        estate.ownerId = ownerId
        estate.zoneId = zoneId
        # Keep all six account slots so garden ownerIndex values continue to
        # address the same house plot even when earlier avatar slots are empty.
        estate.setIdList(self._estateAvatarIds(ownerId, avatarIds))
        estate.sendUpdate('setIdList', [estate.getIdList()])
        estate.sendUpdate('setTreasureIds', [[]])
        estate.sendUpdate('setEstateReady', [])
        self.estate[ownerId] = estate

        houses.sort(key=lambda house: house.getHousePos())
        for house in houses:
            house.sendUpdate('setHouseReady', [])
        self.houses[ownerId] = houses

        ownerHouse = self._findOwnerHouse(ownerId, houses)
        if ownerAvatar is not None and ownerAvatar.getHouseId() != ownerHouse.doId:
            ownerAvatar.b_setHouseId(ownerHouse.doId)
        self._generateOwnerMailbox(ownerId, zoneId, ownerHouse, ownerAvatar)
        self._generateOwnerGarden(ownerId, zoneId, ownerHouse)
        self._generateOwnerFishing(ownerId, zoneId)
        self._activateOwnerPet(ownerId, zoneId)
        self._generateOwnerHouseInterior(ownerId, zoneId, ownerHouse)
        self.applyRentalState(
            ownerId, estate.getRentalTimeStamp(), estate.getRentalType())

        self.loadingOwners.discard(ownerId)
        self.notify.info(
            'Activated persistent estate %s in zone %s for avatar %s' %
            (estate.doId, zoneId, ownerId))
        self._finishEstateRequests(ownerId)

    def _generateOwnerHouseInterior(self, ownerId, estateZoneId, ownerHouse):
        interiorZoneId = self.air.allocateZone(ownerId)
        self.zone2owner[interiorZoneId] = ownerId
        self.houseZones[ownerId] = [interiorZoneId]

        interior = DistributedHouseInteriorAI(
            self.air,
            houseId=ownerHouse.doId,
            houseIndex=ownerHouse.getHouseType(),
            wallpaper=ownerHouse.getInteriorWallpaper(),
            windows=ownerHouse.getInteriorWindows())
        interior.generateWithRequired(interiorZoneId)
        self.houseInteriors[ownerId] = [interior]

        furnitureManager = DistributedFurnitureManagerAI(
            self.air,
            house=ownerHouse,
            interior=interior)
        furnitureManager.zoneId = interiorZoneId
        furnitureManager.generateWithRequired(interiorZoneId)
        self.furnitureManagers[ownerId] = furnitureManager

        exteriorDoor = DistributedHouseDoorAI(
            self.air, ownerHouse.doId, DoorTypes.EXT_STANDARD, ownerId)
        interiorDoor = DistributedHouseDoorAI(
            self.air, ownerHouse.doId, DoorTypes.INT_STANDARD, ownerId)
        exteriorDoor.setOtherDoor(interiorDoor)
        interiorDoor.setOtherDoor(exteriorDoor)
        exteriorDoor.zoneId = estateZoneId
        interiorDoor.zoneId = interiorZoneId
        exteriorDoor.generateWithRequired(estateZoneId)
        interiorDoor.generateWithRequired(interiorZoneId)
        exteriorDoor.fsm.request('closed')
        exteriorDoor.exitDoorFSM.request('closed')
        interiorDoor.fsm.request('closed')
        interiorDoor.exitDoorFSM.request('closed')
        self.houseDoors[ownerId] = (exteriorDoor, interiorDoor)

        self.notify.info(
            'Generated house interior zone %s and furniture manager %s for '
            'avatar %s' % (interiorZoneId, furnitureManager.doId, ownerId))

    def _generateOwnerMailbox(self, ownerId, estateZoneId, ownerHouse,
                              ownerAvatar):
        mailbox = DistributedMailboxAI(
            self.air,
            houseId=ownerHouse.doId,
            housePos=ownerHouse.getHousePos(),
            name=ownerHouse.getName(),
            ownerId=ownerId)
        if ownerAvatar is not None:
            mailbox.setFullIndicator(mailbox._avatarHasMail(ownerAvatar))
        mailbox.generateWithRequired(estateZoneId)
        ownerHouse.mailbox = mailbox
        self.mailboxes[ownerId] = mailbox
        self.notify.info(
            'Generated mailbox %s for house %s in estate zone %s' %
            (mailbox.doId, ownerHouse.doId, estateZoneId))

    def _generateOwnerGarden(self, ownerId, estateZoneId, ownerHouse):
        gardenIndex = ownerHouse.getGardenPos()
        if gardenIndex < 0 or gardenIndex >= 6:
            gardenIndex = ownerHouse.getHousePos()

        estate = self.estate[ownerId]
        garden = DistributedGardenAI(
            self.air, ownerId, estate=estate, ownerIndex=gardenIndex)
        garden.generateWithRequired(estateZoneId)
        self.gardens[ownerId] = garden
        self.gardenObjects[ownerId] = garden.load(estateZoneId)
        self.notify.info(
            'Generated garden %s with %s estate objects for avatar %s' %
            (garden.doId, len(self.gardenObjects[ownerId]), ownerId))

    def _activateOwnerPet(self, ownerId, estateZoneId):
        petId = self.ownerPetIds.get(ownerId, 0)
        if not petId:
            return
        pet = self.air.doId2do.get(petId)
        if pet is not None:
            pet.b_setLocation(self.air.districtId, estateZoneId)
        else:
            petDclass = self.air.dclassesByName.get('DistributedPetAI')
            if petDclass is None:
                self.notify.warning(
                    'Could not activate pet %s: pet dclass is unavailable' %
                    petId)
                return
            self.air.sendActivate(
                petId, self.air.districtId, estateZoneId, petDclass, {})
        self.pets[ownerId] = petId
        self.notify.info(
            'Requested activation of existing pet %s in estate zone %s for '
            'avatar %s' % (petId, estateZoneId, ownerId))

    def _generateOwnerFishing(self, ownerId, estateZoneId):
        pond = DistributedFishingPondAI(self.air)
        pond.setArea(ToontownGlobals.MyEstate)
        pond.generateWithRequired(estateZoneId)
        pond.generateTargets()
        positions = (
            (49.1029, -124.805, 0.344704, 90, 0, 0),
            (46.5222, -134.739, 0.390713, 75, 0, 0),
            (41.31, -144.559, 0.375978, 45, 0, 0),
            (46.8254, -113.682, 0.46015, 135, 0, 0),
        )
        spots = []
        for posHpr in positions:
            spot = DistributedFishingSpotAI(self.air)
            spot.setPondDoId(pond.doId)
            spot.setPosHpr(*posHpr)
            spot.generateWithRequired(estateZoneId)
            spots.append(spot)
        self.fishingPonds[ownerId] = pond
        self.fishingObjects[ownerId] = list(pond.targets.values()) + spots
        self.notify.info(
            'Generated estate fishing pond %s, %s targets, and %s spots for '
            'avatar %s' %
            (pond.doId, len(pond.targets), len(spots), ownerId))

    def applyRentalState(self, ownerId, timestamp, rentalType):
        estate = self.estate.get(ownerId)
        if estate is None:
            return
        timestamp = int(timestamp)
        rentalType = int(rentalType)
        estate.b_setRentalTimeStamp(timestamp)
        estate.b_setRentalType(rentalType)
        taskMgr.remove('estate-rental-expire-%s' % ownerId)
        state = (timestamp, rentalType)
        if (self._rentalApplied.get(ownerId) == state and
                self.cannonObjects.get(ownerId)):
            delay = max(0.1, timestamp - time.time())
            taskMgr.doMethodLater(
                delay, self._expireRental,
                'estate-rental-expire-%s' % ownerId,
                extraArgs=[ownerId], appendTask=True)
            return
        self._deleteCannonObjects(ownerId)
        self._rentalApplied[ownerId] = state
        if rentalType != ToontownGlobals.RentalCannon or timestamp <= time.time():
            estate.b_setClouds(0)
            if rentalType:
                taskMgr.doMethodLater(
                    0.1, self._expireRental,
                    'estate-rental-expire-%s' % ownerId,
                    extraArgs=[ownerId], appendTask=True)
            return
        target = DistributedTargetAI(self.air)
        target.generateWithRequired(estate.zoneId)
        objects = [target]
        for posHpr in CannonGlobals.cannonDrops:
            cannon = DistributedCannonAI(
                self.air, estate.doId, target.doId, *posHpr)
            cannon.generateWithRequired(estate.zoneId)
            objects.append(cannon)
        self.cannonObjects[ownerId] = objects
        estate.b_setClouds(1)
        taskMgr.doMethodLater(
            max(0.1, timestamp - time.time()), self._expireRental,
            'estate-rental-expire-%s' % ownerId,
            extraArgs=[ownerId], appendTask=True)
        self.notify.info(
            'Activated %s estate cannons through %s for avatar %s' %
            (len(objects) - 1, timestamp, ownerId))

    def _expireRental(self, ownerId, task):
        estate = self.estate.get(ownerId)
        if estate is None:
            return task.done
        timestamp = estate.getRentalTimeStamp()
        rentalType = estate.getRentalType()
        if not rentalType:
            self._deleteCannonObjects(ownerId)
            return task.done
        remaining = timestamp - time.time()
        if remaining > 0:
            task.delayTime = remaining
            return task.again
        transaction = AstronObjectTransaction(
            self.air, estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])

        def committed(success, conflicts):
            if success:
                self.applyRentalState(ownerId, 0, 0)
                estate.sendUpdate('cannonsOver', [])
                return
            if conflicts:
                newTimestamp = conflicts.get('setRentalTimeStamp', timestamp)
                newType = conflicts.get('setRentalType', rentalType)
                self.applyRentalState(ownerId, newTimestamp, newType)

        transaction.commit(
            {'setRentalTimeStamp': timestamp, 'setRentalType': rentalType},
            {'setRentalTimeStamp': 0, 'setRentalType': 0}, committed)
        return task.done

    def _deleteCannonObjects(self, ownerId):
        for obj in self.cannonObjects.pop(ownerId, []):
            if not getattr(obj, 'deleted', False):
                obj.requestDelete()
        estate = self.estate.get(ownerId)
        if estate is not None and estate.getClouds():
            estate.b_setClouds(0)

    def _finishEstateRequests(self, ownerId):
        zoneId = self.ownerToZone.get(ownerId)
        if not zoneId or ownerId not in self.houses:
            return
        ownerHouse = self._findOwnerHouse(ownerId, self.houses[ownerId])
        for avId in self.pendingEstateRequests.pop(ownerId, []):
            avatar = self.air.doId2do.get(avId)
            if avatar is None:
                continue
            if avId == ownerId and avatar.getHouseId() != ownerHouse.doId:
                avatar.b_setHouseId(ownerHouse.doId)
            if hasattr(avatar, 'isInEstate') and not avatar.isInEstate():
                avatar.enterEstate(ownerId, zoneId)
            self.notify.info(
                'Sending avatar %s to estate %s in zone %s' %
                (avId, ownerId, zoneId))
            self.sendUpdateToAvatarId(
                avId, 'setEstateZone', [ownerId, zoneId])

    def _findOwnerHouse(self, ownerId, houses):
        for house in houses:
            if house.getAvatarId() == ownerId:
                return house
        return houses[0]

    def _ownerHouseId(self, ownerId, houseIds, avatarIds):
        if ownerId in avatarIds:
            return houseIds[avatarIds.index(ownerId)]
        return houseIds[0]

    @staticmethod
    def _estateAvatarIds(ownerId, avatarIds):
        result = list(avatarIds[:6])
        result += [0] * (6 - len(result))
        if ownerId not in result:
            result[0] = ownerId
        return result

    def _single(self, value, default):
        if isinstance(value, (tuple, list)) and len(value) == 1:
            return value[0]
        if value is None:
            return default
        return value

    def _accountDclass(self):
        for name in ('AstronAccountAI', 'AstronAccount', 'AstronAccountUD'):
            dclass = self.air.dclassesByName.get(name)
            if dclass is not None:
                return dclass
        raise KeyError('AstronAccount dclass is unavailable on the AI repository')

    def _failEstateLoad(self, ownerId, reason):
        self.loadingOwners.discard(ownerId)
        self.notify.warning(
            'Could not load estate for avatar %s: %s' % (ownerId, reason))
        for avId in self.pendingEstateRequests.pop(ownerId, []):
            self.sendUpdateToAvatarId(avId, 'setEstateZone', [0, 0])

    def getOwnerFromZone(self, zoneId):
        return self.zone2owner.get(zoneId, 0)

    def getEstateZones(self, ownerId):
        zoneId = self.ownerToZone.get(ownerId)
        zones = [zoneId] if zoneId else []
        zones.extend(self.houseZones.get(ownerId, []))
        return zones

    def getEstateHouseZones(self, ownerId):
        return list(self.houseZones.get(ownerId, []))

    def exitEstate(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (avatar is not None and hasattr(avatar, 'isInEstate') and
                avatar.isInEstate()):
            avatar.exitEstate()

    def removeFriend(self, avId, friendId):
        return
