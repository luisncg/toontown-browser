"""Native-Panda contracts for the restored scheduled Fish Bingo service."""

import builtins
import unittest
from datetime import datetime
from types import SimpleNamespace

from panda3d.core import loadPrcFile

loadPrcFile('etc/Configrc.prc')


class _Game:
    name = 'toontown'
    process = 'server'


builtins.game = _Game
import otp.ai.AIBaseGlobal  # noqa: E402,F401 - installs server globals

from toontown.fishing import BingoGlobals, FishBingoSchedule, FishGlobals  # noqa: E402
from toontown.fishing.BlockoutBingo import BlockoutBingo  # noqa: E402
from toontown.fishing.DiagonalBingo import DiagonalBingo  # noqa: E402
from toontown.fishing.DistributedPondBingoManagerAI import (  # noqa: E402
    DistributedPondBingoManagerAI)
from toontown.fishing.FishManagerAI import FishManagerAI  # noqa: E402
from toontown.fishing.FourCornerBingo import FourCornerBingo  # noqa: E402
from toontown.fishing.NormalBingo import NormalBingo  # noqa: E402
from toontown.fishing.ThreewayBingo import ThreewayBingo  # noqa: E402


class _Database:
    def __init__(self):
        self.updates = []

    def updateObject(self, databaseId, doId, dclass, newFields, oldFields,
                     callback):
        self.updates.append((doId, oldFields, newFields))
        callback(None)


class _Avatar:
    def __init__(self, doId, zoneId):
        self.doId = doId
        self.zoneId = zoneId
        self.money = 35
        self.bankMoney = 100
        self.maxMoney = 40
        self.maxBankMoney = 12000
        self.announcements = 0

    def getMoney(self):
        return self.money

    def setMoney(self, value):
        self.money = value

    def d_setMoney(self, value):
        return

    def getBankMoney(self):
        return self.bankMoney

    def setBankMoney(self, value):
        self.bankMoney = value

    def d_setBankMoney(self, value):
        return

    def getMaxMoney(self):
        return self.maxMoney

    def getMaxBankMoney(self):
        return self.maxBankMoney

    def d_announceBingo(self):
        self.announcements += 1


class _Air:
    dbId = 4003

    def __init__(self, avatars):
        self.doId2do = {avatar.doId: avatar for avatar in avatars}
        self.sender = avatars[0].doId
        self.dbInterface = _Database()
        self.dclassesByName = {'DistributedToonAI': object()}
        self.events = []
        self.fishManager = FishManagerAI(self)

    def getAvatarIdFromSender(self):
        return self.sender

    def writeServerEvent(self, *args):
        self.events.append(args)


class _Spot:
    def __init__(self, avId, catch=None):
        self.avId = avId
        self.lastFish = catch or [FishGlobals.Nothing, 0, 0, 0]

    def consumeBingoCatch(self):
        self.lastFish = [FishGlobals.Nothing, 0, 0, 0]


class _Pond:
    def __init__(self, zoneId, spots):
        self.doId = 7001
        self.zoneId = zoneId
        self.spots = {index: spot for index, spot in enumerate(spots)}

    def hasToon(self, avId):
        for spot in self.spots.values():
            if spot.avId == avId:
                return spot
        return None


class FishBingoNativeContractTests(unittest.TestCase):
    def test_classic_schedule_is_intermittent_in_pacific_time(self):
        pacific = FishBingoSchedule.TOONTOWN_TIME
        holiday = BingoGlobals  # keep assertions visually compact
        self.assertIsNone(FishBingoSchedule.activeHoliday(
            datetime(2026, 7, 14, 23, 59, tzinfo=pacific)))
        self.assertEqual(
            FishBingoSchedule.activeHoliday(
                datetime(2026, 7, 15, 0, 0, tzinfo=pacific)),
            7)
        self.assertEqual(
            FishBingoSchedule.activeHoliday(
                datetime(2026, 7, 15, 23, 59, tzinfo=pacific)),
            7)
        self.assertIsNone(FishBingoSchedule.activeHoliday(
            datetime(2026, 7, 16, 0, 0, tzinfo=pacific)))
        self.assertEqual(
            FishBingoSchedule.activeHoliday(
                datetime(2026, 7, 18, 0, 30, tzinfo=pacific)),
            19)
        self.assertIsNone(FishBingoSchedule.activeHoliday(
            datetime(2026, 7, 18, 2, 30, tzinfo=pacific)))
        self.assertEqual(
            FishBingoSchedule.activeHoliday(
                datetime(2026, 7, 18, 6, 30, tzinfo=pacific)),
            19)
        self.assertIsNone(FishBingoSchedule.activeHoliday(
            datetime(2026, 7, 18, 10, 30, tzinfo=pacific)))
        self.assertEqual(
            FishBingoSchedule.activeHoliday(
                datetime(2026, 7, 18, 18, 30, tzinfo=pacific)),
            19)
        self.assertIsNotNone(holiday)

    def test_all_five_server_card_types_recognize_their_win_shape(self):
        free = 1 << (BingoGlobals.CARD_SIZE // 2)
        cases = [
            (NormalBingo(), free | sum(1 << cell for cell in range(5))),
            (FourCornerBingo(), free | sum(
                1 << cell for cell in FourCornerBingo.corners)),
            (DiagonalBingo(), free | sum(
                1 << cell for cell in (0, 4, 6, 8, 12, 16, 18, 20, 24))),
            (ThreewayBingo(), free | sum(
                1 << cell for cell in
                (0, 4, 6, 8, 10, 11, 12, 13, 14, 16, 18, 20, 24))),
            (BlockoutBingo(), (1 << BingoGlobals.CARD_SIZE) - 1),
        ]
        for card, state in cases:
            with self.subTest(card=card.__class__.__name__):
                card.setGameState(state)
                self.assertEqual(card.checkForBingo(), BingoGlobals.WIN)

    def test_hourly_super_blockout_boundaries(self):
        pacific = FishBingoSchedule.TOONTOWN_TIME
        self.assertFalse(FishBingoSchedule.isHourlyIntermission(
            datetime(2026, 7, 15, 12, 54, 59, tzinfo=pacific)))
        self.assertTrue(FishBingoSchedule.isHourlyIntermission(
            datetime(2026, 7, 15, 12, 55, 0, tzinfo=pacific)))
        self.assertTrue(FishBingoSchedule.isBlockoutWindow(
            datetime(2026, 7, 15, 13, 4, 59, tzinfo=pacific)))
        self.assertFalse(FishBingoSchedule.isBlockoutWindow(
            datetime(2026, 7, 15, 13, 5, 0, tzinfo=pacific)))

    def test_card_update_consumes_exactly_one_matching_catch(self):
        avatar = _Avatar(42, 2000)
        spot = _Spot(
            avatar.doId,
            [FishGlobals.FishItem, 0, 0, 16])
        manager, air, updates = self._manager([avatar], [spot])
        manager.bingoCard.cellList = [(0, 0)] * BingoGlobals.CARD_SIZE

        manager.cardUpdate(manager.cardId, 0, 0, 0)
        firstState = manager.bingoCard.getGameState()
        manager.cardUpdate(manager.cardId, 1, 0, 0)

        self.assertTrue(firstState & 1)
        self.assertEqual(
            spot.lastFish, [FishGlobals.Nothing, 0, 0, 0])
        self.assertEqual(
            [name for _avId, name, _args in updates].count(
                'updateGameState'), 1)
        self.assertTrue(air.events)

    def test_stale_card_and_wrong_species_do_not_consume_catch(self):
        avatar = _Avatar(42, 2000)
        catch = [FishGlobals.FishItem, 0, 1, 16]
        spot = _Spot(avatar.doId, list(catch))
        manager, air, updates = self._manager([avatar], [spot])
        manager.bingoCard.cellList = [(0, 0)] * BingoGlobals.CARD_SIZE

        manager.cardUpdate(manager.cardId - 1, 0, 0, 1)
        manager.cardUpdate(manager.cardId, 0, 0, 0)

        self.assertEqual(spot.lastFish, catch)
        self.assertFalse(updates)
        self.assertEqual(len(air.events), 2)

    def test_boot_can_mark_one_arbitrary_cell_only_once(self):
        avatar = _Avatar(42, 2000)
        spot = _Spot(avatar.doId, [FishGlobals.BootItem, 0, 0, 0])
        manager, _air, updates = self._manager([avatar], [spot])
        manager.bingoCard.cellList = [(30, 0)] * BingoGlobals.CARD_SIZE

        manager.cardUpdate(
            manager.cardId, 7, *FishGlobals.BingoBoot)
        manager.cardUpdate(
            manager.cardId, 8, *FishGlobals.BingoBoot)

        self.assertTrue(manager.bingoCard.getGameState() & (1 << 7))
        self.assertFalse(manager.bingoCard.getGameState() & (1 << 8))
        self.assertEqual(
            [name for _avId, name, _args in updates].count(
                'updateGameState'), 1)

    def test_bingo_call_rewards_current_pond_once_and_atomically(self):
        first = _Avatar(42, 2000)
        second = _Avatar(43, 2000)
        firstSpot = _Spot(
            first.doId,
            [FishGlobals.FishItem, 0, 0, 16])
        secondSpot = _Spot(second.doId)
        manager, air, _updates = self._manager(
            [first, second], [firstSpot, secondSpot])
        manager.bingoCard.cellList = [(0, 0)] * BingoGlobals.CARD_SIZE
        manager.bingoCard.setGameState(
            (1 << (BingoGlobals.CARD_SIZE // 2)) |
            sum(1 << cell for cell in range(4)))

        manager.cardUpdate(manager.cardId, 4, 0, 0)
        self.assertTrue(manager.canCall)
        manager.handleBingoCall(manager.cardId)
        manager.handleBingoCall(manager.cardId)

        self.assertEqual(first.announcements, 1)
        self.assertEqual((first.money, first.bankMoney), (40, 105))
        self.assertEqual((second.money, second.bankMoney), (40, 105))
        self.assertEqual(len(air.dbInterface.updates), 2)
        for _doId, oldFields, newFields in air.dbInterface.updates:
            self.assertEqual(
                set(oldFields), {'setMoney', 'setBankMoney'})
            self.assertEqual(set(oldFields), set(newFields))

    def test_nonparticipant_cannot_mark_or_call_bingo(self):
        participant = _Avatar(42, 2000)
        outsider = _Avatar(99, 2000)
        manager, air, updates = self._manager(
            [participant, outsider], [_Spot(participant.doId)])
        manager.bingoCard.cellList = [(0, 0)] * BingoGlobals.CARD_SIZE
        original = manager.bingoCard.getGameState()
        air.sender = outsider.doId

        manager.cardUpdate(manager.cardId, 0, 0, 0)
        manager.canCall = True
        manager.handleBingoCall(manager.cardId)

        self.assertEqual(manager.bingoCard.getGameState(), original)
        self.assertEqual(outsider.announcements, 0)
        self.assertFalse(updates)
        self.assertEqual(len(air.events), 2)

    def _manager(self, avatars, spots):
        air = _Air(avatars)
        pond = _Pond(avatars[0].zoneId, spots)
        manager = DistributedPondBingoManagerAI.__new__(
            DistributedPondBingoManagerAI)
        manager.air = air
        manager.doId = 8001
        manager.zoneId = pond.zoneId
        manager.pond = pond
        manager.pondDoId = pond.doId
        manager.coordinator = SimpleNamespace(
            claimSuperWin=lambda item, avId: False)
        manager.state = 'Playing'
        manager.cardId = 17
        manager.typeId = BingoGlobals.NORMAL_CARD
        manager.tileSeed = 123
        manager.bingoCard = NormalBingo()
        manager.jackpot = BingoGlobals.getJackpot(manager.typeId)
        manager.canCall = False
        manager.closing = False
        manager.resolvedCardId = None
        manager.lastUpdate = 0
        manager.lastSuperHour = None
        manager.superHour = None
        updates = []
        manager.sendUpdateToAvatarId = (
            lambda avId, name, args: updates.append((avId, name, args)))
        manager._cancelRoundTasks = lambda: None
        manager._schedule = lambda suffix, delay, callback: None
        return manager, air, updates


if __name__ == '__main__':
    unittest.main()
