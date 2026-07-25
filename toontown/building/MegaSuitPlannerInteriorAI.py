"""Two-front Cog planner used by Cog Mega-Buildings."""

from direct.directnotify import DirectNotifyGlobal

from . import SuitPlannerInteriorAI


class MegaSuitPlannerInteriorAI:
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'MegaSuitPlannerInteriorAI')

    def __init__(self, numFloors, bldgLevel, bldgTrack, zone,
                 respectInvasions=1):
        self.numFloors = numFloors
        self.zoneId = zone
        self.planners = [
            SuitPlannerInteriorAI.SuitPlannerInteriorAI(
                numFloors, bldgLevel, bldgTrack, zone, respectInvasions),
            SuitPlannerInteriorAI.SuitPlannerInteriorAI(
                numFloors, bldgLevel, bldgTrack, zone, respectInvasions),
        ]

    def genFloorSuits(self, floor, numSquads=2):
        numSquads = max(1, min(2, int(numSquads)))
        squadHandles = []
        activeSuits = []
        reserveSuits = []
        for planner in self.planners[:numSquads]:
            handles = planner.genFloorSuits(floor)
            squadHandles.append(handles)
            activeSuits.extend(handles['activeSuits'])
            reserveSuits.extend(handles['reserveSuits'])

        # A four-Toon Mega run still needs more Cogs per floor.  Queue a
        # second planner's opening group as a guaranteed reinforcement wave.
        # With five to eight Toons the same two encounters run in parallel,
        # one on each classic four-Toon battle front.
        if numSquads == 1:
            reinforcementHandles = self.planners[1].genFloorSuits(floor)
            guaranteedReserves = [
                (suit, 100) for suit in reinforcementHandles['activeSuits']]
            guaranteedReserves.extend(
                (suit, 100)
                for suit, unusedChance in
                reinforcementHandles['reserveSuits'])
            squadHandles[0]['reserveSuits'].extend(guaranteedReserves)
            reserveSuits.extend(guaranteedReserves)
        return {
            'activeSuits': activeSuits,
            'reserveSuits': reserveSuits,
            'squadHandles': squadHandles,
        }
