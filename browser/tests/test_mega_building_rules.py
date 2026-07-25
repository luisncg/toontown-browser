import pathlib
import unittest


PROJECT_DIR = pathlib.Path(__file__).resolve().parents[2]

from toontown.building import MegaBuildingGlobals as Mega


class MegaBuildingRuleTests(unittest.TestCase):
    def test_yellow_dots_are_extra_floors(self):
        self.assertEqual(Mega.getYellowFloorCount(1, 10), 9)
        self.assertEqual(Mega.getYellowFloorCount(3, 10), 7)
        self.assertEqual(Mega.getYellowFloorCount(5, 10), 5)
        self.assertEqual(Mega.getYellowFloorCount(4, 10), 6)

    def test_mega_floor_total_is_six_through_ten(self):
        for regularFloors in range(1, 6):
            for requested in range(-2, 14):
                total = Mega.clampMegaFloors(regularFloors, requested)
                self.assertGreaterEqual(total, 6)
                self.assertLessEqual(total, 10)
                self.assertGreater(total, regularFloors)

    def test_squads_preserve_elevator_halves(self):
        first, second = Mega.splitMegaToons(
            [101, 102, 103, 104, 201, None, 203, 204])
        self.assertEqual(first, [101, 102, 103, 104])
        self.assertEqual(second, [201, 203, 204])

    def test_protocol_and_interior_contracts_exist(self):
        dc = (PROJECT_DIR / 'etc' / 'toon.dc').read_text()
        self.assertIn('setMegaFloors(uint8) required broadcast ram;', dc)
        self.assertIn('setMegaState(uint8, uint8, uint8, uint8, int16)', dc)
        self.assertIn(
            'dclass DistributedMegaSuitInterior : DistributedSuitInterior', dc)
        self.assertIn(
            'setSquads(uint32[], uint32[]) required broadcast ram;', dc)

    def test_regular_building_path_remains_separate(self):
        source = (PROJECT_DIR / 'toontown' / 'building' /
                  'DistributedBuildingAI.py').read_text()
        self.assertIn("if getattr(self.elevator, 'megaTrip', False):", source)
        self.assertIn(
            'return DistributedSuitInteriorAI.DistributedSuitInteriorAI('
            'self.air, self.elevator)', source)

    def test_four_toon_mega_queues_guaranteed_reinforcements(self):
        source = (PROJECT_DIR / 'toontown' / 'building' /
                  'MegaSuitPlannerInteriorAI.py').read_text()
        self.assertIn('if numSquads == 1:', source)
        self.assertIn('(suit, 100)', source)

    def test_second_battle_cannot_own_local_camera_or_movie(self):
        source = (PROJECT_DIR / 'toontown' / 'battle' /
                  'DistributedBattleBldg.py').read_text()
        self.assertIn('def _isSpectatorBattle(self):', source)
        self.assertIn('if self._isSpectatorBattle():', source)
        self.assertIn(
            'DistributedBattleBase.DistributedBattleBase.enterPlayMovie',
            source)

    def test_explainer_sign_states_all_mega_rule(self):
        source = (PROJECT_DIR / 'toontown' / 'building' /
                  'DistributedBuilding.py').read_text()
        self.assertIn('COG MEGA-BUILDINGS', source)
        self.assertIn('Every floor uses Mega rules!', source)

    def test_mega_victory_uses_mega_floor_total_for_trophies(self):
        source = (PROJECT_DIR / 'toontown' / 'building' /
                  'DistributedBuildingAI.py').read_text()
        self.assertIn(
            'runFloors = self.activeRunFloors or self.numFloors', source)
        self.assertIn(
            'self.trophyMgr.addTrophy(avId, name, runFloors)', source)

    def test_closing_elevator_downgrades_sub_four_mega_party(self):
        source = (PROJECT_DIR / 'toontown' / 'building' /
                  'DistributedElevatorExtAI.py').read_text()
        self.assertIn(
            'numPlayers < MegaBuildingGlobals.MEGA_MIN_TOONS', source)
        self.assertIn('self.megaTrip = False', source)


if __name__ == '__main__':
    unittest.main()
