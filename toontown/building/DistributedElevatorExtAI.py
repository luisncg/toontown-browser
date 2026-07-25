from otp.ai.AIBase import *
from toontown.toonbase import ToontownGlobals
from direct.distributed.ClockDelta import *
from .ElevatorConstants import *
from . import DistributedElevatorAI
from direct.fsm import ClassicFSM
from direct.fsm import State
from direct.task import Task
from direct.directnotify import DirectNotifyGlobal
from . import MegaBuildingGlobals
from toontown.toonbase import ToontownAccessAI

class DistributedElevatorExtAI(DistributedElevatorAI.DistributedElevatorAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedElevatorExtAI')

    def __init__(self, air, bldg, numSeats=4, antiShuffle=0, minLaff=0, fSkipOpening=False):
        DistributedElevatorAI.DistributedElevatorAI.__init__(self, air, bldg, numSeats, antiShuffle=antiShuffle, minLaff=minLaff, fSkipOpening=fSkipOpening)
        self.anyToonsBailed = 0
        self.boardingParty = None
        self.megaState = MegaBuildingGlobals.MEGA_STATE_CLASSIC
        self.megaVotes = set()
        self.megaVoters = []
        self.pendingMegaJoins = set()
        self.megaStateDuration = 0
        self.megaStateTimestamp = globalClockDelta.getRealNetworkTime()
        self.megaTrip = False
        return

    def delete(self):
        self._clearMegaTasks()
        for seatIndex in range(len(self.seats)):
            avId = self.seats[seatIndex]
            if avId:
                self.clearFullNow(seatIndex)
                self.clearEmptyNow(seatIndex)

        DistributedElevatorAI.DistributedElevatorAI.delete(self)

    def getMegaState(self):
        return [self.megaState, len(self.megaVotes), len(self.megaVoters),
                self.megaStateDuration, self.megaStateTimestamp]

    def _clearMegaTasks(self):
        taskMgr.remove(self.uniqueName('mega-vote-timeout'))
        taskMgr.remove(self.uniqueName('mega-recruit-timeout'))
        taskMgr.remove(self.uniqueName('mega-regular-timeout'))
        taskMgr.remove(self.uniqueName('mega-full-departure'))

    def _setMegaState(self, state, duration=0):
        self.megaState = state
        self.megaStateDuration = int(max(0, duration))
        self.megaStateTimestamp = globalClockDelta.getRealNetworkTime()
        self.sendUpdate('setMegaState', self.getMegaState())

    def _resetMegaRound(self, broadcast=True):
        self._clearMegaTasks()
        self.megaVotes = set()
        self.megaVoters = []
        self.pendingMegaJoins = set()
        self.megaTrip = False
        if broadcast:
            self._setMegaState(MegaBuildingGlobals.MEGA_STATE_CLASSIC)
        else:
            self.megaState = MegaBuildingGlobals.MEGA_STATE_CLASSIC
            self.megaStateDuration = 0
            self.megaStateTimestamp = globalClockDelta.getRealNetworkTime()

    def _startMegaVote(self):
        if self.megaState != MegaBuildingGlobals.MEGA_STATE_CLASSIC:
            return
        boarded = [avId for avId in self.seats[:4] if avId]
        if len(boarded) != MegaBuildingGlobals.MEGA_MIN_TOONS:
            return
        taskMgr.remove(self.uniqueName('countdown-timer'))
        self.megaVoters = boarded
        self.megaVotes = set()
        self.pendingMegaJoins = set()
        self._setMegaState(MegaBuildingGlobals.MEGA_STATE_VOTING,
                           MegaBuildingGlobals.MEGA_VOTE_SECONDS)
        taskMgr.doMethodLater(
            MegaBuildingGlobals.MEGA_VOTE_SECONDS,
            self._megaVoteTimedOut,
            self.uniqueName('mega-vote-timeout'))

    def _megaVoteTimedOut(self, task):
        self._beginRegularFallback()
        return Task.done

    def requestMegaVote(self, acceptMega):
        avId = self.air.getAvatarIdFromSender()
        if self.megaState != MegaBuildingGlobals.MEGA_STATE_VOTING:
            return
        if avId not in self.megaVoters or avId in self.megaVotes:
            return
        if not acceptMega:
            self._beginRegularFallback()
            return
        self.megaVotes.add(avId)
        # Update the tally without restarting the shared vote deadline.
        self.sendUpdate('setMegaState', self.getMegaState())
        if len(self.megaVotes) == len(self.megaVoters):
            self._approveMegaVote()

    def _approveMegaVote(self):
        taskMgr.remove(self.uniqueName('mega-vote-timeout'))
        if self.countFullSeats() < MegaBuildingGlobals.MEGA_MIN_TOONS:
            self._beginRegularFallback()
            return
        self.megaTrip = True
        self.pendingMegaJoins = set()
        self._setMegaState(MegaBuildingGlobals.MEGA_STATE_RECRUITING,
                           MegaBuildingGlobals.MEGA_RECRUIT_SECONDS)
        taskMgr.doMethodLater(
            MegaBuildingGlobals.MEGA_RECRUIT_SECONDS,
            self._megaRecruitTimedOut,
            self.uniqueName('mega-recruit-timeout'))

    def _megaRecruitTimedOut(self, task):
        self._departMega()
        return Task.done

    def _departMega(self):
        if self.megaState not in (MegaBuildingGlobals.MEGA_STATE_RECRUITING,
                                  MegaBuildingGlobals.MEGA_STATE_DEPARTING):
            return
        if self.countFullSeats() < MegaBuildingGlobals.MEGA_MIN_TOONS:
            self._beginRegularFallback()
            return
        self._clearMegaTasks()
        self.megaTrip = True
        self._setMegaState(MegaBuildingGlobals.MEGA_STATE_DEPARTING)
        self.fsm.request('allAboard')

    def _beginRegularFallback(self):
        self._clearMegaTasks()
        taskMgr.remove(self.uniqueName('countdown-timer'))
        self.megaTrip = False
        self.pendingMegaJoins = set()
        self._setMegaState(MegaBuildingGlobals.MEGA_STATE_REGULAR_FALLBACK,
                           MegaBuildingGlobals.REGULAR_FALLBACK_SECONDS)
        taskMgr.doMethodLater(
            MegaBuildingGlobals.REGULAR_FALLBACK_SECONDS,
            self._regularFallbackTimedOut,
            self.uniqueName('mega-regular-timeout'))

    def _regularFallbackTimedOut(self, task):
        if self.countFullSeats() > 0:
            self.fsm.request('allAboard')
        else:
            self.fsm.request('waitEmpty')
        return Task.done

    def requestBoard(self, *args):
        if self.megaState == MegaBuildingGlobals.MEGA_STATE_RECRUITING:
            avId = self.air.getAvatarIdFromSender()
            av = self.air.doId2do.get(avId)
            if (av and self.findAvatar(avId) is None and
                    self.countFullSeats() < MegaBuildingGlobals.MEGA_MAX_TOONS and
                    self.checkBoard(av) == 0 and
                    self._canRecruitMegaToon(avId)):
                self.pendingMegaJoins.add(avId)
                self.sendUpdateToAvatarId(
                    avId, 'showMegaJoinPrompt', [self.bldg.getMegaFloors()])
            else:
                self.rejectBoarder(avId, REJECT_NOSEAT)
            return
        DistributedElevatorAI.DistributedElevatorAI.requestBoard(self, *args)

    def _canRecruitMegaToon(self, avId):
        if not ToontownAccessAI.canAccess(
                avId, self.zoneId,
                'DistributedElevatorExtAI.requestMegaJoin'):
            return False
        if (self.boardingParty and
                self.boardingParty.hasActiveGroup(avId) and
                self.boardingParty.getGroupLeader(avId) != avId):
            return False
        return True

    def checkBoard(self, av):
        result = DistributedElevatorAI.DistributedElevatorAI.checkBoard(self, av)
        if result:
            return result
        if self.megaState in (MegaBuildingGlobals.MEGA_STATE_VOTING,
                              MegaBuildingGlobals.MEGA_STATE_DEPARTING):
            return REJECT_NOSEAT
        if (self.megaState != MegaBuildingGlobals.MEGA_STATE_RECRUITING and
                self.countFullSeats() >= MegaBuildingGlobals.MEGA_MIN_TOONS):
            return REJECT_NOSEAT
        return 0

    def requestMegaJoin(self, acceptMega):
        avId = self.air.getAvatarIdFromSender()
        if avId not in self.pendingMegaJoins:
            return
        self.pendingMegaJoins.discard(avId)
        if not acceptMega or self.megaState != MegaBuildingGlobals.MEGA_STATE_RECRUITING:
            return
        av = self.air.doId2do.get(avId)
        if (not av or self.findAvatar(avId) is not None or
                self.countFullSeats() >= MegaBuildingGlobals.MEGA_MAX_TOONS or
                self.checkBoard(av) != 0 or
                not self._canRecruitMegaToon(avId)):
            self.rejectBoarder(avId, REJECT_NOSEAT)
            return
        self.acceptingBoardersHandler(avId, 0, 0)

    def d_setFloor(self, floorNumber):
        self.sendUpdate('setFloor', [floorNumber])

    def acceptBoarder(self, avId, seatIndex, wantBoardingShow=0):
        DistributedElevatorAI.DistributedElevatorAI.acceptBoarder(
            self, avId, seatIndex, wantBoardingShow)
        self.acceptOnce(self.air.getAvatarExitEvent(avId), self.__handleUnexpectedExit, extraArgs=[avId])
        if self.fsm.getCurrentState().getName() == 'waitEmpty':
            self.fsm.request('waitCountdown')
        if (self.megaState == MegaBuildingGlobals.MEGA_STATE_CLASSIC and
                self.countFullSeats() == MegaBuildingGlobals.MEGA_MIN_TOONS):
            self._startMegaVote()
        elif (self.megaState == MegaBuildingGlobals.MEGA_STATE_RECRUITING and
              self.countFullSeats() == MegaBuildingGlobals.MEGA_MAX_TOONS):
            taskMgr.doMethodLater(
                TOON_BOARD_ELEVATOR_TIME,
                self._departFullMegaTask,
                self.uniqueName('mega-full-departure'))

    def _departFullMegaTask(self, task):
        self._departMega()
        return Task.done

    def __handleUnexpectedExit(self, avId):
        self.notify.warning('Avatar: ' + str(avId) + ' has exited unexpectedly')
        seatIndex = self.findAvatar(avId)
        if seatIndex == None:
            pass
        else:
            self.clearFullNow(seatIndex)
            self.clearEmptyNow(seatIndex)
            if self.countFullSeats() == 0:
                self.fsm.request('waitEmpty')
            elif (self.megaState == MegaBuildingGlobals.MEGA_STATE_VOTING and
                  self.countFullSeats() < MegaBuildingGlobals.MEGA_MIN_TOONS):
                self._resetMegaRound()
                self.resetCountdown()
            elif (self.megaState == MegaBuildingGlobals.MEGA_STATE_RECRUITING and
                  self.countFullSeats() < MegaBuildingGlobals.MEGA_MIN_TOONS):
                self._beginRegularFallback()
        return

    def acceptExiter(self, avId):
        seatIndex = self.findAvatar(avId)
        if seatIndex == None:
            pass
        else:
            self.clearFullNow(seatIndex)
            bailFlag = 0
            timeToSend = self.countdownTime
            if self.antiShuffle:
                myTask = taskMgr.getTasksNamed(self.uniqueName('countdown-timer'))[0]
                timeLeft = myTask.wakeTime - globalClock.getFrameTime()
                timeLeft = max(0, timeLeft)
                timeToSet = timeLeft + 10.0
                timeToSet = min(timeLeft + 10.0, self.countdownTime)
                self.setCountdown(timeToSet)
                timeToSend = timeToSet
                self.sendUpdate('emptySlot' + str(seatIndex), [
                 avId, 1, globalClockDelta.getRealNetworkTime(), timeToSend])
            else:
                if self.anyToonsBailed == 0:
                    bailFlag = 1
                    self.resetCountdown()
                    self.anyToonsBailed = 1
                    self.sendUpdate('emptySlot' + str(seatIndex), [
                     avId, bailFlag, globalClockDelta.getRealNetworkTime(), timeToSend])
                else:
                    self.sendUpdate('emptySlot' + str(seatIndex), [
                     avId, bailFlag, globalClockDelta.getRealNetworkTime(), timeToSend])
            if self.countFullSeats() == 0:
                self.fsm.request('waitEmpty')
            elif (self.megaState == MegaBuildingGlobals.MEGA_STATE_VOTING and
                  self.countFullSeats() < MegaBuildingGlobals.MEGA_MIN_TOONS):
                self._resetMegaRound()
                self.resetCountdown()
            elif (self.megaState == MegaBuildingGlobals.MEGA_STATE_RECRUITING and
                  self.countFullSeats() < MegaBuildingGlobals.MEGA_MIN_TOONS):
                self._beginRegularFallback()
            taskMgr.doMethodLater(TOON_EXIT_ELEVATOR_TIME, self.clearEmptyNow, self.uniqueName('clearEmpty-%s' % seatIndex), extraArgs=(seatIndex,))
        return

    def enterOpening(self):
        self._resetMegaRound()
        DistributedElevatorAI.DistributedElevatorAI.enterOpening(self)
        taskMgr.doMethodLater(ElevatorData[ELEVATOR_NORMAL]['openTime'], self.waitEmptyTask, self.uniqueName('opening-timer'))

    def waitEmptyTask(self, task):
        self.fsm.request('waitEmpty')
        return Task.done

    def enterWaitEmpty(self):
        DistributedElevatorAI.DistributedElevatorAI.enterWaitEmpty(self)
        self.anyToonsBailed = 0
        self._resetMegaRound()

    def enterWaitCountdown(self):
        DistributedElevatorAI.DistributedElevatorAI.enterWaitCountdown(self)
        taskMgr.doMethodLater(self.countdownTime, self.timeToGoTask, self.uniqueName('countdown-timer'))

    def timeToGoTask(self, task):
        if self.megaState != MegaBuildingGlobals.MEGA_STATE_CLASSIC:
            return Task.done
        if self.countFullSeats() == MegaBuildingGlobals.MEGA_MIN_TOONS:
            self._startMegaVote()
        elif self.countFullSeats() > 0:
            self.fsm.request('allAboard')
        else:
            self.fsm.request('waitEmpty')
        return Task.done

    def resetCountdown(self):
        taskMgr.remove(self.uniqueName('countdown-timer'))
        taskMgr.doMethodLater(self.countdownTime, self.timeToGoTask, self.uniqueName('countdown-timer'))

    def setCountdown(self, timeToSet):
        taskMgr.remove(self.uniqueName('countdown-timer'))
        taskMgr.doMethodLater(timeToSet, self.timeToGoTask, self.uniqueName('countdown-timer'))

    def enterAllAboard(self):
        DistributedElevatorAI.DistributedElevatorAI.enterAllAboard(self)
        currentTime = globalClock.getRealTime()
        elapsedTime = currentTime - self.timeOfBoarding
        self.notify.debug('elapsed time: ' + str(elapsedTime))
        waitTime = max(TOON_BOARD_ELEVATOR_TIME - elapsedTime, 0)
        waitTime += self.getBoardingShowTimeLeft()
        taskMgr.doMethodLater(waitTime, self.closeTask, self.uniqueName('waitForAllAboard'))

    def getBoardingShowTimeLeft(self):
        currentTime = globalClock.getRealTime()
        timeLeft = 0.0
        if hasattr(self, 'timeOfGroupBoarding') and self.timeOfGroupBoarding:
            elapsedTime = currentTime - self.timeOfGroupBoarding
            timeLeft = max(MAX_GROUP_BOARDING_TIME - elapsedTime, 0)
            if timeLeft > MAX_GROUP_BOARDING_TIME:
                timeLeft = 0.0
        return timeLeft

    def closeTask(self, task):
        if self.countFullSeats() > 0:
            self.fsm.request('closing')
        else:
            self.fsm.request('waitEmpty')
        return Task.done

    def enterClosing(self):
        DistributedElevatorAI.DistributedElevatorAI.enterClosing(self)
        taskMgr.doMethodLater(ElevatorData[ELEVATOR_NORMAL]['closeTime'], self.elevatorClosedTask, self.uniqueName('closing-timer'))

    def elevatorClosedTask(self, task):
        self.elevatorClosed()
        return Task.done

    def _createInterior(self):
        self.bldg.createSuitInterior()

    def elevatorClosed(self):
        numPlayers = self.countFullSeats()
        if numPlayers > 0:
            # A Toon can disappear after the unanimous vote and after the
            # doors begin closing.  Never start the Mega interior below its
            # four-Toon minimum; the survivors take the regular building.
            if (self.megaTrip and
                    numPlayers < MegaBuildingGlobals.MEGA_MIN_TOONS):
                self.notify.warning(
                    'Mega party dropped below four while closing; '
                    'using the regular Cog Building.')
                self.megaTrip = False
            self._createInterior()
            for seatIndex in range(len(self.seats)):
                avId = self.seats[seatIndex]
                if avId:
                    self.clearFullNow(seatIndex)

        else:
            self.notify.warning('The elevator left, but was empty.')
        self.fsm.request('closed')

    def requestExit(self, *args):
        self.notify.debug('requestExit')
        avId = self.air.getAvatarIdFromSender()
        av = self.air.doId2do.get(avId)
        if self.boardingParty and self.boardingParty.getGroupLeader(avId) and avId:
            if avId == self.boardingParty.getGroupLeader(avId):
                memberIds = self.boardingParty.getGroupMemberList(avId)
                for memberId in memberIds:
                    member = simbase.air.doId2do.get(memberId)
                    if member:
                        if self.accepting:
                            self.acceptingExitersHandler(memberId)
                        else:
                            self.rejectingExitersHandler(memberId)

            else:
                self.rejectingExitersHandler(avId)
        else:
            if av:
                newArgs = (
                 avId,) + args
                if self.accepting:
                    self.acceptingExitersHandler(*newArgs)
                else:
                    self.rejectingExitersHandler(*newArgs)
            else:
                self.notify.warning('avId: %s does not exist, but tried to exit an elevator' % avId)
            return
