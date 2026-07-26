from panda3d.core import *
from panda3d.otp import *
from direct.distributed.ClockDelta import *
from direct.interval.IntervalGlobal import *
from .ElevatorConstants import *
from .ElevatorUtils import *
from . import DistributedElevator
from toontown.toonbase import ToontownGlobals
from direct.directnotify import DirectNotifyGlobal
from direct.fsm import ClassicFSM
from direct.fsm import State
from toontown.hood import ZoneUtil
from toontown.toonbase import TTLocalizer
from toontown.toontowngui import TeaserPanel
from toontown.toontowngui import TTDialog
from direct.gui import DirectGuiGlobals as DGG
from direct.task import Task
from . import MegaBuildingGlobals

class DistributedElevatorExt(DistributedElevator.DistributedElevator):

    def __init__(self, cr):
        DistributedElevator.DistributedElevator.__init__(self, cr)
        self.nametag = None
        self.currentFloor = -1
        self.megaState = MegaBuildingGlobals.MEGA_STATE_CLASSIC
        self.megaStateDuration = 0
        self.megaStateTimestamp = 0
        self.megaVoteDialog = None
        self.megaJoinDialog = None
        self.megaNoticeDialog = None
        self.megaVoteSubmitted = False
        self.megaNoticeState = None
        return

    def setupElevator(self):
        if self.isSetup:
            self.elevatorSphereNodePath.removeNode()
        self.leftDoor = self.bldg.leftDoor
        self.rightDoor = self.bldg.rightDoor
        DistributedElevator.DistributedElevator.setupElevator(self)
        self.setupNametag()

    def disable(self):
        taskMgr.remove(self.uniqueName('show-mega-vote'))
        self._cleanupMegaDialogs()
        self.clearNametag()
        DistributedElevator.DistributedElevator.disable(self)

    def _cleanupDialog(self, attribute):
        dialog = getattr(self, attribute, None)
        if dialog is not None:
            dialog.destroy()
            setattr(self, attribute, None)

    def _cleanupMegaDialogs(self):
        self._cleanupDialog('megaVoteDialog')
        self._cleanupDialog('megaJoinDialog')
        self._cleanupDialog('megaNoticeDialog')

    def _localIsBoarded(self):
        return bool(self.localToonOnBoard or
                    base.localAvatar.doId in self.boardedAvIds)

    def setMegaState(self, state, yesVotes, voterCount, duration, timestamp):
        previousState = self.megaState
        self.megaState = state
        self.megaStateDuration = duration
        self.megaStateTimestamp = timestamp
        if state != MegaBuildingGlobals.MEGA_STATE_VOTING:
            self._cleanupDialog('megaVoteDialog')
            self.megaVoteSubmitted = False
        if hasattr(self, 'bldg') and self.bldg:
            self.bldg.setMegaDisplayActive(
                state in (MegaBuildingGlobals.MEGA_STATE_RECRUITING,
                          MegaBuildingGlobals.MEGA_STATE_DEPARTING))
        if state == MegaBuildingGlobals.MEGA_STATE_VOTING:
            taskMgr.remove(self.uniqueName('show-mega-vote'))
            taskMgr.doMethodLater(0.15, self._showMegaVoteTask,
                                  self.uniqueName('show-mega-vote'),
                                  extraArgs=[yesVotes, voterCount], appendTask=True)
        elif state == MegaBuildingGlobals.MEGA_STATE_RECRUITING:
            if previousState != state and self._localIsBoarded():
                self._showMegaNotice(
                    'Cog Mega-Building approved!\n\n'
                    'Four extra spots are open. This run will use %s Mega floors.' %
                    getattr(self.bldg, 'megaFloors', '?'), state)
        elif state == MegaBuildingGlobals.MEGA_STATE_REGULAR_FALLBACK:
            if previousState != state and self._localIsBoarded():
                self._showMegaNotice(
                    'The group chose a Regular Cog Building.\n\n'
                    'The elevator leaves in 10 seconds. You may hop off now.', state)
        elif state == MegaBuildingGlobals.MEGA_STATE_DEPARTING:
            # Never carry a notice or join prompt into the elevator ride.
            self._cleanupMegaDialogs()
        elif state == MegaBuildingGlobals.MEGA_STATE_CLASSIC:
            self._cleanupMegaDialogs()
            self.megaNoticeState = None

    def _showMegaVoteTask(self, yesVotes, voterCount, task):
        if (self.megaState == MegaBuildingGlobals.MEGA_STATE_VOTING and
                self._localIsBoarded() and not self.megaVoteSubmitted and
                self.megaVoteDialog is None):
            megaFloors = getattr(self.bldg, 'megaFloors', '?')
            self.megaVoteDialog = TTDialog.TTDialog(
                text=('Choose this building run:\n\n'
                      'Cog Mega-Building: %s all-Mega floors and up to 8 Toons.\n'
                      'Mega requires all 4 votes. (%s/%s yes)') %
                     (megaFloors, yesVotes, voterCount),
                style=TTDialog.TwoChoice,
                buttonTextList=['Mega Building', 'Regular Building'],
                command=self._handleMegaVote,
                fadeScreen=0.45,
                text_wordwrap=18,
                text_scale=0.065)
        return Task.done

    def _handleMegaVote(self, value):
        acceptMega = value == DGG.DIALOG_OK
        self.megaVoteSubmitted = True
        self._cleanupDialog('megaVoteDialog')
        from toontown.authority.BrowserAuthorityManager import requestTransition
        choice = int(acceptMega)
        requestTransition(
            'mega.vote',
            {'elevator': self.doId, 'accept': choice},
            lambda: self.sendUpdate('requestMegaVote', [choice]))

    def showMegaJoinPrompt(self, megaFloors):
        self._cleanupDialog('megaJoinDialog')
        self.megaJoinDialog = TTDialog.TTDialog(
            text=('Join this %s-floor Cog Mega-Building?\n\n'
                  'Up to 8 Toons can enter, and every floor uses Mega rules.') %
                 megaFloors,
            style=TTDialog.YesNo,
            command=self._handleMegaJoin,
            fadeScreen=0.4,
            text_wordwrap=18,
            text_scale=0.065)

    def _handleMegaJoin(self, value):
        acceptMega = value == DGG.DIALOG_OK
        self._cleanupDialog('megaJoinDialog')
        from toontown.authority.BrowserAuthorityManager import requestTransition
        choice = int(acceptMega)
        requestTransition(
            'mega.join',
            {'elevator': self.doId, 'accept': choice},
            lambda: self.sendUpdate('requestMegaJoin', [choice]))

    def _showMegaNotice(self, message, state):
        if self.megaNoticeState == state:
            return
        self.megaNoticeState = state
        self._cleanupDialog('megaNoticeDialog')
        self.megaNoticeDialog = TTDialog.TTDialog(
            text=message,
            style=TTDialog.Acknowledge,
            command=self._handleMegaNotice,
            fadeScreen=0.15,
            text_wordwrap=18,
            text_scale=0.065)

    def _handleMegaNotice(self, value):
        self._cleanupDialog('megaNoticeDialog')

    def setupNametag(self):
        if self.nametag == None:
            self.nametag = NametagGroup()
            self.nametag.setFont(ToontownGlobals.getBuildingNametagFont())
            if TTLocalizer.BuildingNametagShadow:
                self.nametag.setShadow(*TTLocalizer.BuildingNametagShadow)
            self.nametag.setContents(Nametag.CName)
            self.nametag.setColorCode(NametagGroup.CCSuitBuilding)
            self.nametag.setActive(0)
            self.nametag.setAvatar(self.getElevatorModel())
            name = self.cr.playGame.dnaStore.getTitleFromBlockNumber(self.bldg.block)
            if not name:
                name = TTLocalizer.CogsInc
            else:
                name += TTLocalizer.CogsIncExt
            self.nametag.setName(name)
            self.nametag.manage(base.marginManager)
        return

    def clearNametag(self):
        if self.nametag != None:
            self.nametag.unmanage(base.marginManager)
            self.nametag.setAvatar(NodePath())
            self.nametag = None
        return

    def getBldgDoorOrigin(self):
        return self.bldg.getSuitDoorOrigin()

    def gotBldg(self, buildingList):
        self.bldgRequest = None
        self.bldg = buildingList[0]
        if not self.bldg:
            self.notify.error('setBldgDoId: elevator %d cannot find bldg %d!' % (self.doId, self.bldgDoId))
            return
        if self.getBldgDoorOrigin():
            self.bossLevel = self.bldg.getBossLevel()
            self.setupElevator()
            self.bldg.setMegaDisplayActive(
                self.megaState in (MegaBuildingGlobals.MEGA_STATE_RECRUITING,
                                   MegaBuildingGlobals.MEGA_STATE_DEPARTING))
        else:
            self.notify.warning('setBldgDoId: elevator %d cannot find suitDoorOrigin for bldg %d!' % (self.doId, bldgDoId))
        return

    def setFloor(self, floorNumber):
        if self.currentFloor >= 0:
            indicator = self.bldg.getFloorIndicatorNode(self.currentFloor)
            if indicator:
                if self.bldg.megaDisplayActive:
                    indicator.setColor(1.0, 0.67, 0.02, 1.0)
                else:
                    indicator.setColor(LIGHT_OFF_COLOR)
        if floorNumber >= 0:
            indicator = self.bldg.getFloorIndicatorNode(floorNumber)
            if indicator:
                if self.bldg.megaDisplayActive:
                    indicator.setColor(1.0, 1.0, 0.25, 1.0)
                else:
                    indicator.setColor(LIGHT_ON_COLOR)
        self.currentFloor = floorNumber

    def handleEnterSphere(self, collEntry):
        self.notify.debug('Entering Elevator Sphere....')
        if hasattr(localAvatar, 'boardingParty') and localAvatar.boardingParty and localAvatar.boardingParty.getGroupLeader(localAvatar.doId) and localAvatar.boardingParty.getGroupLeader(localAvatar.doId) != localAvatar.doId:
            base.localAvatar.elevatorNotifier.showMe(TTLocalizer.ElevatorGroupMember)
        elif self.allowedToEnter(self.zoneId):
            self.cr.playGame.getPlace().detectedElevatorCollision(self)
        else:
            place = base.cr.playGame.getPlace()
            if place:
                place.fsm.request('stopped')
            self.dialog = TeaserPanel.TeaserPanel(pageName='cogHQ', doneFunc=self.handleOkTeaser)

    def handleEnterElevator(self):
        if hasattr(localAvatar, 'boardingParty') and localAvatar.boardingParty and localAvatar.boardingParty.getGroupLeader(localAvatar.doId):
            if localAvatar.boardingParty.getGroupLeader(localAvatar.doId) == localAvatar.doId:
                localAvatar.boardingParty.handleEnterElevator(self)
        elif self.elevatorTripId and localAvatar.lastElevatorLeft == self.elevatorTripId:
            self.rejectBoard(base.localAvatar.doId, REJECT_SHUFFLE)
        elif base.localAvatar.hp > 0:
            toon = base.localAvatar
            self.sendUpdate('requestBoard', [])
        else:
            self.notify.warning('Tried to board elevator with hp: %d' % base.localAvatar.hp)

    def enterWaitEmpty(self, ts):
        self.elevatorSphereNodePath.unstash()
        self.forceDoorsOpen()
        self.accept(self.uniqueName('enterelevatorSphere'), self.handleEnterSphere)
        self.accept(self.uniqueName('enterElevatorOK'), self.handleEnterElevator)
        DistributedElevator.DistributedElevator.enterWaitEmpty(self, ts)

    def exitWaitEmpty(self):
        self.elevatorSphereNodePath.stash()
        self.ignore(self.uniqueName('enterelevatorSphere'))
        self.ignore(self.uniqueName('enterElevatorOK'))
        DistributedElevator.DistributedElevator.exitWaitEmpty(self)

    def enterWaitCountdown(self, ts):
        DistributedElevator.DistributedElevator.enterWaitCountdown(self, ts)
        self.forceDoorsOpen()
        self.accept(self.uniqueName('enterElevatorOK'), self.handleEnterElevator)
        self.startCountdownClock(self.countdownTime, ts)

    def exitWaitCountdown(self):
        self.ignore(self.uniqueName('enterElevatorOK'))
        DistributedElevator.DistributedElevator.exitWaitCountdown(self)

    def getZoneId(self):
        return self.bldg.interiorZoneId

    def getElevatorModel(self):
        return self.bldg.getSuitElevatorNodePath()
