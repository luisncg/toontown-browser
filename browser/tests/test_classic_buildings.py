"""Regression checks for retiring Mega-Buildings without changing the wire schema."""
import builtins
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from panda3d.core import loadPrcFile, NodePath
loadPrcFile('etc/Configrc.prc')

class _Game:
    name = 'toontown'
    process = 'server'

builtins.game = _Game
builtins.aspect2dp = NodePath('test-aspect2dp')
import otp.ai.AIBaseGlobal
from toontown.building.DistributedBuildingAI import DistributedBuildingAI
from toontown.building.DistributedElevatorExtAI import DistributedElevatorExtAI
from toontown.building.DistributedBuilding import DistributedBuilding
from toontown.building.DistributedElevatorExt import DistributedElevatorExt
from toontown.authority.BrowserCapabilityTokensAI import normalize_target

class ClassicBuildingTests(unittest.TestCase):
    def test_four_toons_depart_without_a_vote(self):
        for count in (1, 2, 3, 4):
            states = []
            elevator = SimpleNamespace(
                countFullSeats=lambda: count,
                fsm=SimpleNamespace(request=states.append))
            DistributedElevatorExtAI.timeToGoTask(elevator, None)
            self.assertEqual(states, ['allAboard'])

    def test_empty_elevator_waits(self):
        states = []
        elevator = SimpleNamespace(countFullSeats=lambda: 0,
            fsm=SimpleNamespace(request=states.append))
        DistributedElevatorExtAI.timeToGoTask(elevator, None)
        self.assertEqual(states, ['waitEmpty'])

    def test_building_creates_four_seat_elevator(self):
        building = object.__new__(DistributedBuildingAI)
        building.track, building.difficulty, building.numFloors = 's', 1, 5
        building.zoneId, building.block, building.doId = 2100, 1, 101
        building.air = SimpleNamespace(writeServerEvent=lambda *args: None)
        building.sendUpdate = lambda *args: None
        building.d_setState = lambda *args: None
        building.getExteriorAndInteriorZoneId = lambda: (2100, 2200)
        module = 'toontown.building.DistributedBuildingAI'
        with patch(module + '.SuitPlannerInteriorAI.SuitPlannerInteriorAI'), \
             patch(module + '.DistributedElevatorExtAI.DistributedElevatorExtAI') as factory:
            building.enterSuit()
            self.assertEqual(factory.call_args.args, (building.air, building))
            self.assertEqual(factory.call_args.kwargs, {})
        self.assertEqual(DistributedElevatorExtAI.__init__.__defaults__[0], 4)

    def test_stale_mega_flag_still_creates_regular_interior(self):
        building = SimpleNamespace(air=object(),
            elevator=SimpleNamespace(megaTrip=True))
        with patch('toontown.building.DistributedBuildingAI.'
                   'DistributedSuitInteriorAI.DistributedSuitInteriorAI') as factory:
            result = DistributedBuildingAI._createSuitInterior(building)
            factory.assert_called_once_with(building.air, building.elevator)
            self.assertIs(result, factory.return_value)

    def test_retired_messages_cannot_mutate_boarding_or_show_ui(self):
        untouched = SimpleNamespace()
        for cls, method, args in (
            (DistributedElevatorExtAI, 'requestMegaVote', (1,)),
            (DistributedElevatorExtAI, 'requestMegaJoin', (1,)),
            (DistributedElevatorExt, 'showMegaJoinPrompt', (10,)),
            (DistributedElevatorExt, 'setMegaState', (1, 4, 4, 15, 0)),
            (DistributedBuilding, 'setMegaFloors', (10,)),
        ):
            getattr(cls, method)(untouched, *args)
        self.assertEqual(vars(untouched), {})
        self.assertEqual(DistributedBuildingAI.getMegaFloors(untouched), 0)
        self.assertEqual(DistributedElevatorExtAI.getMegaState(untouched), [0]*5)

    def test_retired_capabilities_rejected(self):
        for action in ('mega.vote', 'mega.join'):
            with self.assertRaises(ValueError):
                normalize_target(action, {'elevator': 101, 'accept': 1})

if __name__ == '__main__':
    unittest.main()
