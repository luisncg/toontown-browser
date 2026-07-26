"""Server-authoritative shared Fish Bingo card for one fishing pond."""

import random

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.ClockDelta import globalClockDelta
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from direct.task.TaskManagerGlobal import taskMgr
from toontown.fishing import BingoGlobals
from toontown.fishing import FishBingoSchedule
from toontown.fishing import FishGlobals
from toontown.fishing.BlockoutBingo import BlockoutBingo
from toontown.fishing.DiagonalBingo import DiagonalBingo
from toontown.fishing.FourCornerBingo import FourCornerBingo
from toontown.fishing.NormalBingo import NormalBingo
from toontown.fishing.ThreewayBingo import ThreewayBingo


class DistributedPondBingoManagerAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedPondBingoManagerAI')
    cardTypes = {
        BingoGlobals.NORMAL_CARD: NormalBingo,
        BingoGlobals.FOURCORNER_CARD: FourCornerBingo,
        BingoGlobals.DIAGONAL_CARD: DiagonalBingo,
        BingoGlobals.THREEWAY_CARD: ThreewayBingo,
        BingoGlobals.BLOCKOUT_CARD: BlockoutBingo,
    }

    def __init__(self, air, pond=None, coordinator=None):
        DistributedObjectAI.__init__(self, air)
        self.pond = pond
        self.coordinator = coordinator
        self.pondDoId = getattr(pond, 'doId', 0)
        self.state = 'Off'
        self.cardId = 0
        self.typeId = BingoGlobals.NORMAL_CARD
        self.tileSeed = 0
        self.bingoCard = None
        self.jackpot = 0
        self.canCall = False
        self.closing = False
        self.resolvedCardId = None
        self.lastUpdate = globalClockDelta.getRealNetworkTime(bits=32)
        self.lastSuperHour = None
        self.superHour = None

    def generate(self):
        DistributedObjectAI.generate(self)
        if self.pond is None:
            self.pond = self.air.doId2do.get(self.pondDoId)
        if self.pond is not None:
            self.pond.setPondBingoManager(self)

    def delete(self):
        self._removeTasks()
        pond = self.pond
        if pond is not None:
            pond.removePondBingoManager(self)
        if self.coordinator is not None:
            self.coordinator.managerDeleted(self)
        self.pond = None
        self.coordinator = None
        DistributedObjectAI.delete(self)

    def setPondDoId(self, pondDoId):
        self.pondDoId = pondDoId

    def getPondDoId(self):
        return self.pondDoId

    # These are server-to-client DC fields.  The AI retains local setters so
    # generated field dispatch remains well-defined, but clients cannot send
    # them because the DC contract does not mark them clsend.
    def updateGameState(self, gameState, cellId):
        return

    def setCardState(self, cardId, typeId, tileSeed, gameState):
        return

    def setState(self, state, timeStamp):
        return

    def setJackpot(self, jackpot):
        self.jackpot = jackpot

    def startup(self):
        if self.closing or not self._eventActive():
            return
        self._transition('Intro')
        self._schedule(
            'intro', BingoGlobals.INTRO_SESSION, self._beginCountdown)
        for avId in self._participantIds():
            self.activateForPlayer(avId)

    def reconcileSchedule(self, now=None):
        if self.closing:
            return
        if not self._eventActive():
            self.closeEvent()
            return
        if (self.coordinator.isIntermission(now) and
                self.state not in ('Intermission', 'CloseEvent', 'Off')):
            self._enterIntermission(now)

    def activateForPlayer(self, avId):
        if avId not in self._participantIds() or self.state == 'Off':
            return
        if self.bingoCard is not None:
            self.sendUpdateToAvatarId(
                avId, 'setCardState',
                [self.cardId, self.typeId, self.tileSeed,
                 self.bingoCard.getGameState()])
            self.sendUpdateToAvatarId(avId, 'setJackpot', [self.jackpot])
        self.sendUpdateToAvatarId(
            avId, 'setState', [self.state, self.lastUpdate])
        if self.canCall:
            self.sendUpdateToAvatarId(avId, 'enableBingo', [])

    def removePlayer(self, avId):
        return

    def cardUpdate(self, cardId, cellId, genus, species):
        avId = self.air.getAvatarIdFromSender()
        spot = self.pond.hasToon(avId) if self.pond is not None else None
        if (spot is None or self.state != 'Playing' or self.canCall or
                self.bingoCard is None or cardId != self.cardId or
                cellId < 0 or cellId >= BingoGlobals.CARD_SIZE or
                self.bingoCard.getGameState() & (1 << cellId)):
            self._record(avId, 'invalid Fish Bingo card update')
            return
        if not self._validCatch(spot, genus, species):
            self._record(avId, 'Fish Bingo update did not match latest catch')
            return
        result = self.bingoCard.cellUpdateCheck(cellId, genus, species)
        if result not in (BingoGlobals.UPDATE, BingoGlobals.WIN):
            self._record(avId, 'Fish Bingo catch did not match selected cell')
            return
        spot.consumeBingoCatch()
        self._broadcast(
            'updateGameState',
            [self.bingoCard.getGameState(), cellId])
        if result == BingoGlobals.WIN:
            self.canCall = True
            self._broadcast('enableBingo', [])

    def handleBingoCall(self, cardId):
        avId = self.air.getAvatarIdFromSender()
        spot = self.pond.hasToon(avId) if self.pond is not None else None
        if (spot is None or self.state != 'Playing' or not self.canCall or
                cardId != self.cardId or self.resolvedCardId == self.cardId or
                self.bingoCard is None or
                self.bingoCard.checkForBingo() != BingoGlobals.WIN):
            self._record(avId, 'invalid or duplicate Fish Bingo call')
            return
        from toontown.authority.BrowserAuthorityManagerAI import (
            consumeProtectedTransition)
        if not consumeProtectedTransition(
                self.air,
                avId,
                'fish-bingo.claim',
                {'manager': self.doId, 'card': cardId}):
            return
        self.canCall = False
        self.resolvedCardId = self.cardId
        avatar = self.air.doId2do.get(avId)
        if avatar is not None:
            avatar.d_announceBingo()
        if self.typeId == BingoGlobals.BLOCKOUT_CARD:
            if not self.coordinator.claimSuperWin(self, avId):
                self.resolveLoss()
            return
        self.resolveWin(avId, self.jackpot)

    def resolveWin(self, avId, jackpot=None):
        if self.state not in ('WaitCountdown', 'Playing'):
            return
        self._cancelRoundTasks()
        self.canCall = False
        if jackpot is not None:
            self.jackpot = jackpot
            self._broadcast('setJackpot', [self.jackpot])
        participantIds = self._participantIds()
        self._transition('Reward')
        for participantId in participantIds:
            avatar = self.air.doId2do.get(participantId)
            if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
                continue
            self.air.fishManager.creditJellybeans(
                avatar, self.jackpot,
                lambda success, target=participantId, reward=self.jackpot,
                card=self.cardId: self._rewardLogged(
                    target, success, reward, card))
        self.air.writeServerEvent(
            'fishBingoWin', avId,
            'pond=%s card=%s type=%s winners=%s reward=%s' %
            (self.pondDoId, self.cardId, self.typeId,
             len(participantIds), self.jackpot))
        self._schedule(
            'next-round', BingoGlobals.REWARD_TIMEOUT,
            self._beginCountdown)

    def resolveLoss(self, task=None):
        if self.state not in ('WaitCountdown', 'Playing'):
            return task.done if task is not None else None
        self._cancelRoundTasks()
        self.canCall = False
        wasSuper = self.typeId == BingoGlobals.BLOCKOUT_CARD
        self._transition('GameOver')
        if wasSuper and self.coordinator is not None:
            self.coordinator.reportSuperLoss(self)
        self._schedule(
            'next-round', BingoGlobals.REWARD_TIMEOUT,
            self._beginCountdown)
        return task.done if task is not None else None

    def closeEvent(self):
        if self.closing:
            return
        self.closing = True
        self._removeTasks()
        self.canCall = False
        self._transition('CloseEvent')
        self._schedule(
            'close', BingoGlobals.CLOSE_EVENT_TIMEOUT,
            self._finishClose)

    def _beginCountdown(self, task=None):
        if self.closing or not self._eventActive():
            self.closeEvent()
            return task.done if task is not None else None
        now = self.coordinator._now()
        if self.coordinator.isIntermission(now):
            self._enterIntermission(now)
            return task.done if task is not None else None
        forcedType = self.coordinator.chooseCardType(self, now)
        self._generateCard(forcedType)
        self._transition('WaitCountdown')
        self._broadcastCardState()
        self._broadcast('setJackpot', [self.jackpot])
        self._schedule(
            'countdown', BingoGlobals.TIMEOUT_SESSION,
            self._beginPlaying)
        return task.done if task is not None else None

    def _beginPlaying(self, task=None):
        if self.closing or not self._eventActive():
            self.closeEvent()
            return task.done if task is not None else None
        self.canCall = False
        for spot in self.pond.spots.values():
            spot.consumeBingoCatch()
        self._transition('Playing')
        self._schedule(
            'game', BingoGlobals.getGameTime(self.typeId),
            self.resolveLoss)
        return task.done if task is not None else None

    def _enterIntermission(self, now=None):
        self._cancelRoundTasks()
        self.canCall = False
        local = FishBingoSchedule.toontownTime(now)
        elapsed = max(0, (local.minute - 55) * 60 + local.second)
        timestamp = globalClockDelta.getRealNetworkTime(bits=32) - elapsed
        self._transition('Intermission', timestamp)
        self._schedule(
            'intermission',
            self.coordinator.secondsUntilNextHour(now),
            self._beginCountdown)

    def _generateCard(self, forcedType=None):
        self.cardId = (self.cardId + 1) & 0xffff
        self.typeId = (forcedType if forcedType is not None else
                       random.randrange(BingoGlobals.NORMAL_CARD,
                                        BingoGlobals.BLOCKOUT_CARD))
        self.tileSeed = random.randrange(0, 65536)
        self.bingoCard = self.cardTypes[self.typeId]()
        self.bingoCard.generateCard(self.tileSeed, self.pond.getArea())
        self.jackpot = (self.coordinator.getSuperJackpot()
                        if self.typeId == BingoGlobals.BLOCKOUT_CARD
                        else BingoGlobals.getJackpot(self.typeId))
        self.superHour = (FishBingoSchedule.hourKey(self.coordinator._now())
                          if self.typeId == BingoGlobals.BLOCKOUT_CARD
                          else None)
        self.resolvedCardId = None

    def _broadcastCardState(self):
        self._broadcast(
            'setCardState',
            [self.cardId, self.typeId, self.tileSeed,
             self.bingoCard.getGameState()])

    def _transition(self, state, timestamp=None):
        self.state = state
        self.lastUpdate = (globalClockDelta.getRealNetworkTime(bits=32)
                           if timestamp is None else int(timestamp))
        self._broadcast('setState', [state, self.lastUpdate])

    def _broadcast(self, fieldName, args):
        for avId in self._participantIds():
            self.sendUpdateToAvatarId(avId, fieldName, args)

    def _participantIds(self):
        if self.pond is None:
            return []
        return sorted({
            spot.avId for spot in self.pond.spots.values()
            if spot.avId
        })

    def _validCatch(self, spot, genus, species):
        catch = spot.lastFish
        if not catch:
            return False
        if catch[0] == FishGlobals.BootItem:
            return (genus, species) == FishGlobals.BingoBoot
        return (catch[0] in (
                    FishGlobals.FishItem,
                    FishGlobals.FishItemNewEntry,
                    FishGlobals.FishItemNewRecord) and
                genus == catch[1] and species == catch[2])

    def _eventActive(self):
        return self.coordinator is not None and self.coordinator.isActive()

    def _schedule(self, suffix, delay, callback):
        taskMgr.remove(self.uniqueName(suffix))
        taskMgr.doMethodLater(
            max(0.01, delay), callback, self.uniqueName(suffix))

    def _cancelRoundTasks(self):
        for suffix in ('intro', 'countdown', 'game', 'next-round',
                       'intermission'):
            taskMgr.remove(self.uniqueName(suffix))

    def _removeTasks(self):
        self._cancelRoundTasks()
        taskMgr.remove(self.uniqueName('close'))

    def _finishClose(self, task):
        self.state = 'Off'
        self.requestDelete()
        return task.done

    def _rewardLogged(self, avId, success, reward=0, cardId=0):
        if not success:
            self.notify.warning(
                'Atomic Fish Bingo reward conflicted for avatar %s' % avId)
            return
        authority = getattr(self.air, 'browserAuthorityManager', None)
        if authority is not None:
            authority.recordProgressionMutation(
                avId,
                'fish-bingo.reward',
                {
                    'card': int(cardId),
                    'jellybeans': int(reward),
                    'pond': int(self.pondDoId),
                })

    def _record(self, avId, message):
        self.air.writeServerEvent('suspicious', avId or 0, message)
