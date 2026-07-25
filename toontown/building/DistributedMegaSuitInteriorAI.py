from functools import partial

from panda3d.core import Point3
from otp.ai.AIBaseGlobal import *
from direct.distributed.ClockDelta import globalClockDelta
from direct.task import Task

from toontown.toonbase.ToontownBattleGlobals import (
    getCreditMultiplier, getInvasionMultiplier)
from toontown.battle import BattleBase, DistributedBattleBldgAI
from .ElevatorConstants import ELEVATOR_NORMAL, ElevatorData
from . import DistributedSuitInteriorAI, MegaBuildingGlobals


class DistributedMegaSuitInteriorAI(
        DistributedSuitInteriorAI.DistributedSuitInteriorAI):
    """One building progression with up to two classic four-Toon fronts."""

    def __init__(self, air, elevator):
        DistributedSuitInteriorAI.DistributedSuitInteriorAI.__init__(
            self, air, elevator)
        self.squads = MegaBuildingGlobals.splitMegaToons(self.toonIds)
        self.squadHandles = [{}, {}]
        self.battles = [None, None]
        self.squadFinished = [False, False]
        self.squadSurvivors = [[], []]
        self.squadSuitsKilled = [[], []]
        self.squadSuitsKilledPerFloor = [[], []]

    def getSquads(self):
        return [self.squads[0], self.squads[1]]

    def d_setSquads(self):
        self.sendUpdate('setSquads', self.getSquads())

    def _onToonSeatsChanged(self):
        if not hasattr(self, 'squads'):
            return
        self.squads = MegaBuildingGlobals.splitMegaToons(self.toonIds)
        if getattr(self, 'doId', 0):
            self.d_setSquads()

    def enterElevator(self):
        activeSquadIndexes = [index for index, squad in enumerate(self.squads)
                              if squad]
        handles = self.planner.genFloorSuits(
            self.currentFloor, numSquads=len(activeSquadIndexes))
        self.squadHandles = [{}, {}]
        for plannerIndex, squadIndex in enumerate(activeSquadIndexes):
            self.squadHandles[squadIndex] = handles['squadHandles'][plannerIndex]

        self.suits = list(handles['activeSuits'])
        self.activeSuits = list(handles['activeSuits'])
        self.reserveSuits = list(handles['reserveSuits'])
        self.battles = [None, None]
        self.battle = None
        self.squadFinished = [not bool(squad) for squad in self.squads]
        self.squadSurvivors = [[], []]
        self.d_setToons()
        self.d_setSquads()
        self.d_setSuits()
        self._resetResponses()
        self.d_setState('Elevator')
        self.timer.startCallback(
            BattleBase.ELEVATOR_T +
            ElevatorData[ELEVATOR_NORMAL]['openTime'] +
            BattleBase.SERVER_BUFFER_TIME,
            self._serverMegaElevatorDone)

    def _serverMegaElevatorDone(self):
        self.ignoreElevatorDone = 1
        self.b_setState('Battle')

    def _configureBattleProgress(self, battle, squadIndex):
        battle.suitsKilled = self.squadSuitsKilled[squadIndex]
        battle.suitsKilledPerFloor = self.squadSuitsKilledPerFloor[squadIndex]
        battle.battleCalc.toonSkillPtsGained = self.toonSkillPtsGained
        battle.toonExp = self.toonExp
        battle.toonOrigQuests = self.toonOrigQuests
        battle.toonItems = self.toonItems
        battle.toonOrigMerits = self.toonOrigMerits
        battle.toonMerits = self.toonMerits
        battle.toonParts = self.toonParts
        battle.helpfulToons = self.helpfulToons

    def _createSquadBattle(self, squadIndex):
        handles = self.squadHandles[squadIndex]
        if not self.squads[squadIndex] or not handles:
            self.squadFinished[squadIndex] = True
            return
        bossBattle = int(self.currentFloor == self.topFloor)
        battle = DistributedBattleBldgAI.DistributedBattleBldgAI(
            self.air,
            self.zoneId,
            partial(self._handleSquadRoundDone, squadIndex),
            partial(self._handleSquadBattleDone, squadIndex),
            bossBattle=bossBattle,
            megaBattleGroup=squadIndex + 1)
        battle.pos = Point3(-9.0 if squadIndex == 0 else 9.0, 0.0, 0.0)
        self._configureBattleProgress(battle, squadIndex)
        battle.setInitialMembers(
            self.squads[squadIndex], handles['activeSuits'])
        battle.generateWithRequired(self.zoneId)
        multiplier = getCreditMultiplier(self.currentFloor)
        if self.air.suitInvasionManager.getInvading():
            multiplier *= getInvasionMultiplier()
        battle.battleCalc.setSkillCreditMultiplier(multiplier)
        self.battles[squadIndex] = battle

    def enterBattle(self):
        if not any(self.battles):
            for squadIndex in range(2):
                self._createSquadBattle(squadIndex)
            self.elevator.d_setFloor(self.currentFloor)

    def exitBattle(self):
        self._cleanupFloorBattle()

    def _handleSquadRoundDone(self, squadIndex, toonIds, totalHp, deadSuits):
        handles = self.squadHandles[squadIndex]
        activeSuits = handles.get('activeSuits', [])
        reserveSuits = handles.get('reserveSuits', [])
        totalMaxHp = sum(suit.maxHP for suit in activeSuits)
        for suit in deadSuits:
            if suit in activeSuits:
                activeSuits.remove(suit)
            if suit in self.activeSuits:
                self.activeSuits.remove(suit)

        joined = []
        if reserveSuits and len(activeSuits) < 4:
            hpPercent = 100.0
            if totalMaxHp:
                hpPercent = 100.0 - totalHp / float(totalMaxHp) * 100.0
            for info in list(reserveSuits):
                if info[1] <= hpPercent and len(activeSuits) < 4:
                    reserveSuits.remove(info)
                    if info in self.reserveSuits:
                        self.reserveSuits.remove(info)
                    activeSuits.append(info[0])
                    self.activeSuits.append(info[0])
                    self.suits.append(info[0])
                    joined.append(info)

        battle = self.battles[squadIndex]
        if joined:
            self.d_setSuits()
            for info in joined:
                battle.suitRequestJoin(info[0])
            battle.resume()
        elif activeSuits:
            battle.resume()
        else:
            battle.resume(
                self.currentFloor,
                topFloor=int(self.currentFloor == self.topFloor))

    def _handleSquadBattleDone(self, squadIndex, zoneId, toonIds):
        self.squadFinished[squadIndex] = True
        self.squadSurvivors[squadIndex] = list(toonIds)
        if not all(self.squadFinished):
            return
        taskMgr.remove(self.taskName('mega-floor-finished'))
        taskMgr.doMethodLater(
            0.0, self._finishMegaFloorTask,
            self.taskName('mega-floor-finished'))

    def _finishMegaFloorTask(self, task):
        survivors = self.squadSurvivors[0] + self.squadSurvivors[1]
        for toonId in list(self.toons):
            if toonId not in survivors:
                self._removeToon(toonId)
        self.d_setToons()
        self.d_setSquads()
        if not self.toons:
            self.bldg.deleteSuitInterior()
        elif self.currentFloor == self.topFloor:
            self.setState('Reward')
        else:
            self.b_setState('Resting')
        return Task.done

    def _cleanupFloorBattle(self):
        floorSuits = list(self.suits)
        floorSuits.extend(info[0] for info in self.reserveSuits)
        for suit in set(floorSuits):
            if not suit.isDeleted():
                suit.requestDelete()
        for battle in getattr(self, 'battles', []):
            if battle is not None and not battle.isDeleted():
                battle.requestDelete()
        self.battles = [None, None]
        self.battle = None
        self.suits = []
        self.reserveSuits = []
        self.activeSuits = []
        self.squadHandles = [{}, {}]

    def delete(self):
        taskMgr.remove(self.taskName('mega-floor-finished'))
        DistributedSuitInteriorAI.DistributedSuitInteriorAI.delete(self)
