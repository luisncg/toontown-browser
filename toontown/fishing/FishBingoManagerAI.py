"""District-wide scheduling and Super Blockout coordination for Fish Bingo."""

import json
import os

from direct.directnotify import DirectNotifyGlobal
from direct.task.TaskManagerGlobal import taskMgr
from panda3d.core import ConfigVariableBool, ConfigVariableInt, ConfigVariableString
from toontown.fishing import BingoGlobals
from toontown.fishing import FishBingoSchedule


class FishBingoManagerAI:
    notify = DirectNotifyGlobal.directNotify.newCategory('FishBingoManagerAI')

    def __init__(self, air, nowProvider=None):
        self.air = air
        self.nowProvider = nowProvider
        self.ponds = {}
        self.managers = {}
        self.activeHolidayId = None
        self.forceActive = ConfigVariableBool(
            'fish-bingo-force-active', False).value
        self.forceCardType = ConfigVariableInt(
            'fish-bingo-force-card-type', -1).value
        if self.forceCardType not in range(BingoGlobals.BLOCKOUT_CARD + 1):
            self.forceCardType = -1
        self.superJackpot = BingoGlobals.MIN_SUPER_JACKPOT
        self._superWinner = {}
        self._superLosers = {}
        self._resolvedSuperHours = set()
        self._loadJackpot()

    def _now(self):
        return self.nowProvider() if self.nowProvider else None

    def start(self):
        self.reconcile()

    def stop(self):
        taskMgr.remove('fish-bingo-schedule')
        self._setActiveHoliday(None)

    def reconcile(self, task=None):
        holidayId = FishBingoSchedule.activeHoliday(
            self._now(), self.forceActive)
        self._setActiveHoliday(holidayId)
        if holidayId is not None:
            now = self._now()
            for manager in list(self.managers.values()):
                manager.reconcileSchedule(now)
        taskMgr.remove('fish-bingo-schedule')
        taskMgr.doMethodLater(
            30.0, self.reconcile, 'fish-bingo-schedule')
        return task.done if task is not None else None

    def registerPond(self, pond):
        self.ponds[pond.doId] = pond
        if self.activeHolidayId is not None:
            self._createManager(pond)

    def unregisterPond(self, pond):
        self.ponds.pop(pond.doId, None)
        manager = self.managers.pop(pond.doId, None)
        if manager is not None and not getattr(manager, 'deleted', False):
            manager.requestDelete()

    def managerDeleted(self, manager):
        pond = getattr(manager, 'pond', None)
        if pond is not None and self.managers.get(pond.doId) is manager:
            self.managers.pop(pond.doId, None)

    def isActive(self):
        return self.activeHolidayId is not None

    def isIntermission(self, now=None):
        return (not self.forceActive and
                FishBingoSchedule.isHourlyIntermission(now))

    def secondsUntilNextHour(self, now=None):
        return FishBingoSchedule.secondsUntilNextHour(now)

    def chooseCardType(self, manager, now=None):
        if self.forceCardType >= 0:
            return self.forceCardType
        hour = FishBingoSchedule.hourKey(now)
        if (FishBingoSchedule.isBlockoutWindow(now) and
                hour not in self._resolvedSuperHours and
                manager.lastSuperHour != hour):
            manager.lastSuperHour = hour
            return BingoGlobals.BLOCKOUT_CARD
        return None

    def getSuperJackpot(self):
        return self.superJackpot

    def claimSuperWin(self, manager, avId):
        hour = manager.superHour
        if (not hour or hour in self._resolvedSuperHours or
                self._superWinner.get(hour) is not None):
            return False
        self._superWinner[hour] = manager.doId
        self._resolvedSuperHours.add(hour)
        manager.resolveWin(avId, self.superJackpot)
        for other in list(self.managers.values()):
            if (other is not manager and other.superHour == hour and
                    other.typeId == BingoGlobals.BLOCKOUT_CARD and
                    other.state in ('WaitCountdown', 'Playing')):
                other.resolveLoss()
        self.superJackpot = BingoGlobals.MIN_SUPER_JACKPOT
        self._saveJackpot()
        self._trimSuperHistory()
        return True

    def reportSuperLoss(self, manager):
        hour = manager.superHour
        if not hour or hour in self._resolvedSuperHours:
            return
        losers = self._superLosers.setdefault(hour, set())
        losers.add(manager.doId)
        contenders = {
            item.doId for item in self.managers.values()
            if item.superHour == hour and
            item.typeId == BingoGlobals.BLOCKOUT_CARD
        }
        if contenders and contenders.issubset(losers):
            self._resolvedSuperHours.add(hour)
            self.superJackpot = min(
                BingoGlobals.MAX_SUPER_JACKPOT,
                self.superJackpot + BingoGlobals.ROLLOVER_AMOUNT)
            self._saveJackpot()
            self._trimSuperHistory()

    def _setActiveHoliday(self, holidayId):
        if holidayId == self.activeHolidayId:
            return
        oldHoliday = self.activeHolidayId
        self.activeHolidayId = holidayId
        if oldHoliday is not None:
            self.air.holidayManager.currentHolidays.pop(oldHoliday, None)
        if holidayId is None:
            if oldHoliday is not None and self.air.newsManager is not None:
                self.air.newsManager.bingoEnd()
            for manager in list(self.managers.values()):
                manager.closeEvent()
            self._publishHolidays()
            return
        self.air.holidayManager.currentHolidays[holidayId] = self
        self._publishHolidays()
        for pond in list(self.ponds.values()):
            self._createManager(pond)
        if self.air.newsManager is not None:
            self.air.newsManager.bingoStart()
        self.notify.info(
            'Fish Bingo event active (holiday %s, %s ponds)' %
            (holidayId, len(self.ponds)))

    def _createManager(self, pond):
        existing = self.managers.get(pond.doId)
        if existing is not None and not getattr(existing, 'deleted', False):
            return existing
        from toontown.fishing.DistributedPondBingoManagerAI import (
            DistributedPondBingoManagerAI)
        manager = DistributedPondBingoManagerAI(self.air, pond, self)
        manager.setPondDoId(pond.doId)
        manager.generateWithRequired(pond.zoneId)
        self.managers[pond.doId] = manager
        pond.setPondBingoManager(manager)
        manager.startup()
        return manager

    def _publishHolidays(self):
        if self.air.newsManager is None:
            return
        self.air.newsManager.b_setHolidayIdList(
            sorted(self.air.holidayManager.currentHolidays))

    def _jackpotPath(self):
        folder = ConfigVariableString('server-data-folder', 'data').value
        return os.path.join(folder or 'data', 'fish-bingo-jackpot.json')

    def _loadJackpot(self):
        try:
            with open(self._jackpotPath(), 'r', encoding='utf-8') as stream:
                value = int(json.load(stream).get('superJackpot', 0))
            if BingoGlobals.MIN_SUPER_JACKPOT <= value <= BingoGlobals.MAX_SUPER_JACKPOT:
                self.superJackpot = value
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

    def _saveJackpot(self):
        path = self._jackpotPath()
        temporary = path + '.tmp'
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temporary, 'w', encoding='utf-8') as stream:
                json.dump({'superJackpot': self.superJackpot}, stream)
            os.replace(temporary, path)
        except OSError as error:
            self.notify.warning('Could not persist Fish Bingo jackpot: %s' % error)

    def _trimSuperHistory(self):
        if len(self._resolvedSuperHours) <= 48:
            return
        keep = set(sorted(self._resolvedSuperHours)[-24:])
        self._resolvedSuperHours.intersection_update(keep)
        self._superWinner = {
            key: value for key, value in self._superWinner.items()
            if key in keep
        }
        self._superLosers = {
            key: value for key, value in self._superLosers.items()
            if key in keep
        }
