"""Native-Panda contract checks for restored estate fishing and pets."""

import builtins
import unittest
from types import SimpleNamespace

from panda3d.core import loadPrcFile

loadPrcFile('etc/Configrc.prc')


class _Game:
    name = 'toontown'
    process = 'server'


builtins.game = _Game
import otp.ai.AIBaseGlobal  # noqa: E402,F401 - installs server globals

from toontown.fishing.FishCollection import FishCollection  # noqa: E402
from toontown.fishing.FishManagerAI import FishManagerAI  # noqa: E402
from toontown.fishing.FishTank import FishTank  # noqa: E402
from toontown.catalog import CatalogItem  # noqa: E402
from toontown.catalog.CatalogFurnitureItem import CatalogFurnitureItem  # noqa: E402
from toontown.catalog.CatalogItemList import CatalogItemList  # noqa: E402
from toontown.estate.DistributedHouseDoorAI import DistributedHouseDoorAI  # noqa: E402
from toontown.estate.DistributedCannonAI import DistributedCannonAI  # noqa: E402
from toontown.pets import PetConstants  # noqa: E402
from toontown.pets.DistributedPetAI import DistributedPetAI  # noqa: E402
from toontown.pets.PetManagerAI import PetManagerAI  # noqa: E402
from toontown.safezone.DistributedFishingSpotAI import DistributedFishingSpotAI  # noqa: E402
from toontown.toon import DistributedNPCPetclerkAI as PetClerkModule  # noqa: E402


class _Database:
    def __init__(self):
        self.createdFields = None
        self.updates = []

    def createObject(self, databaseId, dclass, fields, callback):
        self.createdFields = fields
        callback(9001)

    def updateObject(self, databaseId, doId, dclass, newFields, oldFields,
                     callback):
        self.updates.append((doId, oldFields, newFields))
        callback(None)


class _Air:
    dbId = 4003
    districtId = 401000000

    def __init__(self, avatar):
        self.dbInterface = _Database()
        self.dclassesByName = {
            'DistributedPetAI': object(),
            'DistributedToonAI': object(),
        }
        self.doId2do = {avatar.doId: avatar}

    def writeServerEvent(self, *args):
        return

    def getAvatarIdFromSender(self):
        return next(iter(self.doId2do))


class _Avatar:
    doId = 42
    zoneId = 2000

    def __init__(self):
        self.petId = 0
        self.money = 40
        self.bankMoney = 500
        self.maxMoney = 40
        self.maxBankMoney = 12000
        self.fishingRod = 0
        self.maxFishTank = 20
        self.fishCollection = FishCollection()
        self.fishTank = FishTank()
        self.friends = []

    def getPetId(self):
        return self.petId

    def setPetId(self, value):
        self.petId = value

    def d_setPetId(self, value):
        return

    def getMoney(self):
        return self.money

    def setMoney(self, value):
        self.money = value

    def d_setMoney(self, value):
        return

    def getBankMoney(self):
        return self.bankMoney

    def getTotalMoney(self):
        return self.money + self.bankMoney

    def setBankMoney(self, value):
        self.bankMoney = value

    def d_setBankMoney(self, value):
        return

    def getMaxMoney(self):
        return self.maxMoney

    def getMaxBankMoney(self):
        return self.maxBankMoney

    def getFishingRod(self):
        return self.fishingRod

    def getMaxFishTank(self):
        return self.maxFishTank

    def getFriendsList(self):
        return self.friends

    def getFishCollection(self):
        return self.fishCollection.getNetLists()

    def setFishCollection(self, *values):
        self.fishCollection.makeFromNetLists(*values)

    def d_setFishCollection(self, *values):
        return

    def getFishTank(self):
        return self.fishTank.getNetLists()

    def setFishTank(self, *values):
        self.fishTank.makeFromNetLists(*values)

    def d_setFishTank(self, *values):
        return


class EstateNativeContractTests(unittest.TestCase):
    def test_fishing_cast_debits_once_before_enabling_reward(self):
        avatar = _Avatar()
        air = _Air(avatar)
        spot = DistributedFishingSpotAI.__new__(DistributedFishingSpotAI)
        spot.air = air
        spot.zoneId = avatar.zoneId
        spot.avId = avatar.doId
        spot.cast = False
        spot._operationInFlight = False
        spot.uniqueName = lambda name: 'test-' + name
        spot.d_setMovie = lambda *args: None
        spot._scheduleMovieClear = lambda: None
        spot._scheduleTimeout = lambda delay: None
        oldMoney = avatar.money

        spot.doCast(0.5, 0)

        self.assertTrue(spot.cast)
        self.assertLess(avatar.money, oldMoney)
        _, oldFields, newFields = air.dbInterface.updates[0]
        self.assertEqual(set(oldFields), {'setMoney'})
        self.assertEqual(set(oldFields), set(newFields))

    def test_cannon_rejects_duplicate_fire(self):
        avatar = _Avatar()
        air = _Air(avatar)
        cannon = DistributedCannonAI.__new__(DistributedCannonAI)
        cannon.air = air
        cannon.zoneId = avatar.zoneId
        cannon.avId = avatar.doId
        cannon.lit = False
        cannon.timeoutTask = None
        updates = []
        cannon.sendUpdate = lambda name, args: updates.append((name, args))

        cannon.setCannonLit(0, 45)
        cannon.setCannonLit(0, 45)

        self.assertTrue(cannon.lit)
        self.assertEqual(
            [name for name, _args in updates], ['setCannonWillFire'])

    def test_house_door_requires_same_zone_for_owner_and_friend(self):
        owner = _Avatar()
        owner.doId = 42
        friend = _Avatar()
        friend.doId = 43
        friend.friends = [(owner.doId, 0)]
        stranger = _Avatar()
        stranger.doId = 44
        air = _Air(owner)
        air.doId2do.update({friend.doId: friend, stranger.doId: stranger})
        door = DistributedHouseDoorAI.__new__(DistributedHouseDoorAI)
        door.air = air
        door.ownerId = owner.doId
        door.zoneId = 61000

        owner.zoneId = 2000
        friend.zoneId = door.zoneId
        stranger.zoneId = door.zoneId

        self.assertFalse(door._avatarMayEnter(owner.doId))
        self.assertTrue(door._avatarMayEnter(friend.doId))
        self.assertFalse(door._avatarMayEnter(stranger.doId))

    def test_positioned_catalog_item_round_trips_on_python_3(self):
        store = CatalogItem.Customization | CatalogItem.Location
        item = CatalogFurnitureItem(
            1399, posHpr=(-5, 0, 0, 0, 0, 0))

        blob = CatalogItemList([item], store=store).getBlob()
        restored = CatalogItemList(blob, store=store)

        self.assertEqual(len(restored), 1)
        self.assertEqual(
            tuple(restored[0].posHpr),
            (-5.0, 0.0, 0.0, 0.0, 0.0, 0.0))

    def test_fish_catch_updates_collection_and_tank_together(self):
        avatar = _Avatar()
        air = _Air(avatar)
        manager = FishManagerAI(air)
        manager.requestedFish[avatar.doId] = (0, 0)
        result = []

        manager.generateCatch(avatar, 2000, result.append)

        self.assertEqual(len(avatar.fishCollection), 1)
        self.assertEqual(len(avatar.fishTank), 1)
        self.assertIn(result[0][0], (2, 9, 10))
        _, oldFields, newFields = air.dbInterface.updates[0]
        self.assertEqual(
            set(oldFields), {'setFishCollection', 'setFishTank'})
        self.assertEqual(set(oldFields), set(newFields))

    def test_pet_adoption_builds_complete_record_and_atomic_link(self):
        avatar = _Avatar()
        air = _Air(avatar)
        manager = PetManagerAI(air)
        result = []

        manager.createNewPetFromSeed(
            avatar.doId, 1, 0, 0, 2000, cost=100,
            callback=lambda *values: result.append(values))

        self.assertEqual(result, [(True, 9001)])
        self.assertEqual(avatar.petId, 9001)
        self.assertEqual((avatar.money, avatar.bankMoney), (0, 440))
        required = {
            'setOwnerId', 'setPetName', 'setForgetfulness',
            'setBoredom', 'setTrickAptitudes', 'setLastSeenTimestamp',
        }
        self.assertTrue(required.issubset(air.dbInterface.createdFields))
        _, oldFields, newFields = air.dbInterface.updates[0]
        self.assertEqual(
            set(oldFields), {'setPetId', 'setMoney', 'setBankMoney'})
        self.assertEqual(set(oldFields), set(newFields))

    def test_pet_feed_charges_wallet_and_bank_in_one_commit(self):
        avatar = _Avatar()
        avatar.money = 0
        air = _Air(avatar)
        pet = DistributedPetAI.__new__(DistributedPetAI)
        pet.air = air
        pet.zoneId = avatar.zoneId
        pet.active = 1
        pet.busy = 0
        pet._interactionInFlight = False
        pet.isBusy = lambda: False
        pet.freeAvatar = lambda avId: self.fail(
            'valid pet feed unexpectedly freed avatar %s' % avId)
        started = []
        pet._DistributedPetAI__startInteraction = (
            lambda mode, current: started.append((mode, current.doId)))

        pet.handleAvPetInteraction(PetConstants.PET_MOVIE_FEED, avatar.doId)

        self.assertEqual(
            (avatar.money, avatar.bankMoney),
            (0, 500 - PetConstants.FEED_AMOUNT))
        self.assertEqual(
            started, [(PetConstants.PET_MOVIE_FEED, avatar.doId)])
        _, oldFields, newFields = air.dbInterface.updates[0]
        self.assertEqual(set(oldFields), {'setMoney', 'setBankMoney'})
        self.assertEqual(set(oldFields), set(newFields))

    def test_pet_clerk_waits_for_adoption_commit_before_closing(self):
        avatar = _Avatar()
        avatar.getTotalMoney = lambda: 100000
        air = _Air(avatar)
        air.getAvatarIdFromSender = lambda: avatar.doId

        class _PetManager:
            callback = None

            def createNewPetFromSeed(self, *args, **kwargs):
                self.callback = kwargs['callback']

        air.petMgr = _PetManager()
        hadSimbase = hasattr(builtins, 'simbase')
        oldSimbase = getattr(builtins, 'simbase', None)
        builtins.simbase = SimpleNamespace(air=air)
        try:
            clerk = PetClerkModule.DistributedNPCPetclerkAI.__new__(
                PetClerkModule.DistributedNPCPetclerkAI)
            clerk.air = air
            clerk.zoneId = avatar.zoneId
            clerk.busy = avatar.doId
            clerk.petSeeds = [1]
            clerk.transactionType = ''
            clerk._pendingAction = False
            clerk._transactionDonePending = False
            movies = []
            cleared = []
            clerk.d_setMovie = lambda avId, flag, extraArgs=[]: (
                movies.append((avId, flag, extraArgs)))
            clerk.sendClearMovie = lambda task: cleared.append(True)

            clerk.petAdopted(0, 0)
            clerk.transactionDone()

            self.assertTrue(clerk._pendingAction)
            self.assertTrue(clerk._transactionDonePending)
            self.assertFalse(cleared)

            air.petMgr.callback(True, 9001)

            self.assertEqual(clerk.transactionType, 'adopt')
            self.assertEqual(
                movies[-1][1],
                PetClerkModule.NPCToons.SELL_MOVIE_PETADOPTED)
            self.assertEqual(cleared, [True])
        finally:
            if hadSimbase:
                builtins.simbase = oldSimbase
            else:
                del builtins.simbase


if __name__ == '__main__':
    unittest.main()
