"""Native server contracts for Decoy and Embarrass reactive gags."""

import builtins
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from panda3d.core import loadPrcFile
from panda3d.direct import DCPacker

loadPrcFile('etc/Configrc.prc')


class _Game:
    name = 'toontown'
    process = 'server'


builtins.game = _Game
import otp.ai.AIBaseGlobal  # noqa: E402,F401 - installs server globals

from toontown.battle.BattleBase import (  # noqa: E402
    SUIT_ATK_COL,
    SUIT_BEFORE_TOONS_COL,
    SUIT_HP_COL,
    TOON_ACCBONUS_COL,
    TOON_HPBONUS_COL,
    TOON_TGT_COL,
    getToonAttack,
)
from toontown.battle.BattleCalculatorAI import BattleCalculatorAI  # noqa: E402
from toontown.battle.DistributedBattleBaseAI import DistributedBattleBaseAI  # noqa: E402
from toontown.battle.ReactiveGagGlobals import (  # noqa: E402
    DECOY_TRACK,
    EMBARRASS_TRACK,
    MAX_REACTIVE_GAG_COUNT,
    REACTIVE_RESULT_FAILURE,
    REACTIVE_RESULT_NOT_TRIGGERED,
    REACTIVE_RESULT_SUCCESS,
    WHOOPEE_CUSHION_FLUSTER_TURNS,
    getWhoopeeCushionSuccessChance,
    reducedDamage,
)
from toontown.toonbase.ToontownBattleGlobals import THROW_TRACK  # noqa: E402
from toontown.toonbase import ToontownGlobals  # noqa: E402


class _Suit:
    def __init__(self, doId):
        self.doId = doId


class _Battle:
    def __init__(self, toonAttacks, damages):
        self.activeToons = list(toonAttacks)
        self.activeSuits = [_Suit(7001)]
        self.toonAttacks = toonAttacks
        self.suitAttacks = [[7001, 0, -1, list(damages), 0, 0, 0]]


def _reaction(toonId, track, target):
    return getToonAttack(toonId, track=track, level=0, target=target)


def _calculator(battle, targets, results):
    calculator = object.__new__(BattleCalculatorAI)
    calculator.battle = battle
    calculator.currentlyFlusteredSuits = {}
    calculator._BattleCalculatorAI__createSuitTargetList = lambda _index: list(targets)
    if callable(results):
        calculator._BattleCalculatorAI__reactiveGagSucceeds = lambda track, chance=None: (
            results(track) if chance is None else results(track, chance))
    else:
        calculator._BattleCalculatorAI__reactiveGagSucceeds = \
            lambda track, chance=None: results[track]
    return calculator


class ReactiveGagNativeTests(unittest.TestCase):
    def test_reserved_tracks_round_trip_through_battle_dc_int8(self):
        for track in (DECOY_TRACK, EMBARRASS_TRACK):
            packer = DCPacker()
            packer.rawPackInt8(track)
            data = packer.getString().encode('latin1')
            unpacker = DCPacker()
            unpacker.setUnpackData(data)
            self.assertEqual(unpacker.rawUnpackInt8(), track)

    def test_level_one_reduction_preserves_positive_hits(self):
        self.assertEqual([reducedDamage(value) for value in (0, 1, 2, 4, 10, 20)],
                         [0, 1, 1, 3, 8, 15])

    def test_whoopee_cushion_group_has_a_bounded_success_bonus(self):
        self.assertEqual(
            [getWhoopeeCushionSuccessChance(count)
             for count in (1, 2, 3, 4)],
            [60, 70, 70, 70])

    def test_fake_moustache_success_cancels_a_group_attack(self):
        reaction = _reaction(101, DECOY_TRACK, 101)
        battle = _Battle({101: reaction, 102: getToonAttack(102)}, [12, 8])
        calculator = _calculator(battle, [101, 102], {DECOY_TRACK: True})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [0, 0])
        self.assertEqual(reaction[TOON_ACCBONUS_COL], REACTIVE_RESULT_SUCCESS)
        self.assertEqual(reaction[TOON_HPBONUS_COL], 20)
        self.assertEqual(reaction[TOON_TGT_COL], 7001)

    def test_group_attack_triggers_every_armed_decoy(self):
        toonIds = [101, 102, 103, 104]
        reactions = {
            toonId: _reaction(toonId, DECOY_TRACK, toonId)
            for toonId in toonIds
        }
        battle = _Battle(reactions, [12, 8, 6, 4])
        rolls = iter((False, True, False, True))
        calculator = _calculator(
            battle, toonIds, lambda _track: next(rolls))

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [0, 0, 0, 0])
        self.assertEqual(
            [reactions[toonId][TOON_ACCBONUS_COL] for toonId in toonIds],
            [REACTIVE_RESULT_FAILURE, REACTIVE_RESULT_SUCCESS,
             REACTIVE_RESULT_FAILURE, REACTIVE_RESULT_SUCCESS])
        self.assertTrue(all(
            reactions[toonId][TOON_TGT_COL] == 7001
            for toonId in toonIds
        ))

    def test_fake_moustache_failure_leaves_attack_unchanged(self):
        reaction = _reaction(101, DECOY_TRACK, 101)
        battle = _Battle({101: reaction}, [9])
        calculator = _calculator(battle, [101], {DECOY_TRACK: False})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [9])
        self.assertEqual(reaction[TOON_ACCBONUS_COL], REACTIVE_RESULT_FAILURE)

    def test_decoy_does_not_trigger_for_a_different_target(self):
        reaction = _reaction(101, DECOY_TRACK, 101)
        battle = _Battle({101: reaction, 102: getToonAttack(102)}, [0, 7])
        calculator = _calculator(battle, [102], {DECOY_TRACK: True})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)
        calculator._BattleCalculatorAI__finishReactiveGags()

        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [0, 7])
        self.assertEqual(reaction[TOON_ACCBONUS_COL], REACTIVE_RESULT_NOT_TRIGGERED)
        self.assertEqual(reaction[TOON_TGT_COL], -1)

    def test_four_single_target_decoys_trigger_only_the_attacked_toon(self):
        toonIds = [101, 102, 103, 104]
        reactions = {
            toonId: _reaction(toonId, DECOY_TRACK, toonId)
            for toonId in toonIds
        }
        battle = _Battle(reactions, [0, 0, 9, 0])
        calculator = _calculator(
            battle, [103], {DECOY_TRACK: False})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)
        calculator._BattleCalculatorAI__finishReactiveGags()

        self.assertEqual(
            [reactions[toonId][TOON_ACCBONUS_COL] for toonId in toonIds],
            [REACTIVE_RESULT_NOT_TRIGGERED,
             REACTIVE_RESULT_NOT_TRIGGERED,
             REACTIVE_RESULT_FAILURE,
             REACTIVE_RESULT_NOT_TRIGGERED])
        self.assertEqual(
            [reactions[toonId][TOON_TGT_COL] for toonId in toonIds],
            [-1, -1, 7001, -1])

    def test_only_triggered_reactive_gags_are_consumed(self):
        used = []

        class _Toon:
            def __init__(self, toonId):
                self.doId = toonId

            def useReactiveGag(self, track, level):
                used.append((self.doId, track, level))
                return True

        attacks = {
            101: _reaction(101, DECOY_TRACK, 7001),
            102: _reaction(102, DECOY_TRACK, -1),
            103: _reaction(103, EMBARRASS_TRACK, 7001),
        }
        attacks[101][TOON_ACCBONUS_COL] = REACTIVE_RESULT_SUCCESS
        attacks[102][TOON_ACCBONUS_COL] = REACTIVE_RESULT_NOT_TRIGGERED
        attacks[103][TOON_ACCBONUS_COL] = REACTIVE_RESULT_FAILURE
        toons = {toonId: _Toon(toonId) for toonId in attacks}
        holder = SimpleNamespace(
            activeToons=list(attacks),
            toonAttacks=attacks,
            getToon=lambda toonId: toons.get(toonId),
            notify=DistributedBattleBaseAI.notify,
        )

        DistributedBattleBaseAI._DistributedBattleBaseAI__consumeTriggeredReactiveGags(
            holder)

        self.assertEqual(used, [
            (101, DECOY_TRACK, 0),
            (103, EMBARRASS_TRACK, 0),
        ])

    def test_reactive_inventory_caps_at_ten_and_refills_independently(self):
        from toontown.toon.DistributedToonAI import DistributedToonAI

        updates = []
        toon = DistributedToonAI.__new__(DistributedToonAI)
        toon.doId = 101
        toon.reactiveGagCounts = [1, 4]
        toon.sendUpdate = lambda field, values: updates.append((field, values))
        toon.air = SimpleNamespace(
            getAvatarIdFromSender=lambda: 101,
            writeServerEvent=lambda *_event: None,
        )

        self.assertTrue(toon.useReactiveGag(DECOY_TRACK, 0))
        self.assertEqual(toon.getReactiveGagCounts(), (0, 4))
        self.assertFalse(toon.useReactiveGag(DECOY_TRACK, 0))
        toon.requestReactiveGagRefill(DECOY_TRACK)
        self.assertEqual(
            toon.getReactiveGagCounts(),
            (MAX_REACTIVE_GAG_COUNT, 4))
        toon.requestReactiveGagRefill(EMBARRASS_TRACK)
        self.assertEqual(
            toon.getReactiveGagCounts(),
            (MAX_REACTIVE_GAG_COUNT, MAX_REACTIVE_GAG_COUNT))
        self.assertTrue(all(
            field == 'setReactiveGagCounts' for field, _values in updates
        ))

    def test_testing_refill_is_rejected_by_the_production_server(self):
        from toontown.toon.DistributedToonAI import DistributedToonAI

        events = []
        updates = []
        toon = DistributedToonAI.__new__(DistributedToonAI)
        toon.doId = 101
        toon.reactiveGagCounts = [1, 4]
        toon.sendUpdate = lambda field, values: updates.append((field, values))
        toon.air = SimpleNamespace(
            getAvatarIdFromSender=lambda: 101,
            writeServerEvent=lambda *event: events.append(event),
        )

        with patch.dict(os.environ, {'TOONTOWN_PRODUCTION': '1'}):
            toon.requestReactiveGagRefill(DECOY_TRACK)

        self.assertEqual(toon.getReactiveGagCounts(), (1, 4))
        self.assertEqual(updates, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], 'suspicious')
        self.assertIn('rejected in production', events[0][-1])

    def test_whoopee_cushion_reduces_only_its_chosen_cogs_attack(self):
        reaction = _reaction(101, EMBARRASS_TRACK, 7001)
        battle = _Battle({101: reaction, 102: getToonAttack(102)}, [10, 20])
        calculator = _calculator(battle, [101, 102], {EMBARRASS_TRACK: True})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [8, 15])
        self.assertEqual(reaction[TOON_ACCBONUS_COL], REACTIVE_RESULT_SUCCESS)
        self.assertEqual(
            reaction[TOON_HPBONUS_COL],
            WHOOPEE_CUSHION_FLUSTER_TURNS)

    def test_cushion_group_uses_one_shared_roll_and_fixed_reduction(self):
        toonIds = [101, 102, 103, 104]
        reactions = {
            toonId: _reaction(toonId, EMBARRASS_TRACK, 7001)
            for toonId in toonIds
        }
        battle = _Battle(reactions, [100, 20, 1, 0])
        rolls = []

        def sharedRoll(track, chance):
            rolls.append((track, chance))
            return True

        calculator = _calculator(
            battle, toonIds, sharedRoll)

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertTrue(all(
            reactions[toonId][TOON_ACCBONUS_COL] == REACTIVE_RESULT_SUCCESS
            for toonId in toonIds
        ))
        self.assertEqual(
            battle.suitAttacks[0][SUIT_HP_COL], [75, 15, 1, 0])
        self.assertEqual(
            [reactions[toonId][TOON_HPBONUS_COL] for toonId in toonIds],
            [WHOOPEE_CUSHION_FLUSTER_TURNS] * 4)
        self.assertEqual(rolls, [(EMBARRASS_TRACK, 70)])

    def test_same_cog_cushions_all_fail_only_when_every_roll_fails(self):
        toonIds = [101, 102, 103, 104]
        reactions = {
            toonId: _reaction(toonId, EMBARRASS_TRACK, 7001)
            for toonId in toonIds
        }
        battle = _Battle(reactions, [16, 12, 8, 4])
        calculator = _calculator(
            battle, toonIds, {EMBARRASS_TRACK: False})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertTrue(all(
            reactions[toonId][TOON_ACCBONUS_COL] == REACTIVE_RESULT_FAILURE
            for toonId in toonIds
        ))
        self.assertEqual(
            battle.suitAttacks[0][SUIT_HP_COL], [16, 12, 8, 4])

    def test_fluster_reduces_exactly_two_cog_turns(self):
        reaction = _reaction(101, EMBARRASS_TRACK, 7001)
        battle = _Battle({101: reaction}, [20])
        calculator = _calculator(
            battle, [101], {EMBARRASS_TRACK: True})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)
        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [15])
        self.assertEqual(
            battle.suitAttacks[0][SUIT_BEFORE_TOONS_COL], 2)
        self.assertEqual(calculator.currentlyFlusteredSuits, {7001: 1})

        battle.toonAttacks = {101: getToonAttack(101)}
        battle.suitAttacks[0] = [7001, 0, -1, [20], 0, 0, 0]
        calculator._BattleCalculatorAI__resolveReactiveGags(0)
        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [15])
        self.assertEqual(
            battle.suitAttacks[0][SUIT_BEFORE_TOONS_COL], 1)
        self.assertEqual(calculator.currentlyFlusteredSuits, {})

        battle.suitAttacks[0] = [7001, 0, -1, [20], 0, 0, 0]
        calculator._BattleCalculatorAI__resolveReactiveGags(0)
        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [20])
        self.assertEqual(
            battle.suitAttacks[0][SUIT_BEFORE_TOONS_COL], 0)

    def test_whoopee_cushion_failure_keeps_full_damage(self):
        reaction = _reaction(101, EMBARRASS_TRACK, 7001)
        battle = _Battle({101: reaction}, [11])
        calculator = _calculator(battle, [101], {EMBARRASS_TRACK: False})

        calculator._BattleCalculatorAI__resolveReactiveGags(0)

        self.assertEqual(battle.suitAttacks[0][SUIT_HP_COL], [11])
        self.assertEqual(reaction[TOON_ACCBONUS_COL], REACTIVE_RESULT_FAILURE)

    def test_server_rejects_regular_and_reactive_double_selection(self):
        class _State:
            def getName(self):
                return 'WaitForInput'

        class _Fsm:
            def getCurrentState(self):
                return _State()

        class _Air:
            def __init__(self):
                self.events = []

            def getAvatarIdFromSender(self):
                return 101

            def writeServerEvent(self, *event):
                self.events.append(event)

        cases = (
            (
                'reactive then regular',
                _reaction(101, DECOY_TRACK, 101),
                (THROW_TRACK, 0, 7001),
                DECOY_TRACK,
            ),
            (
                'regular then reactive',
                getToonAttack(101, track=THROW_TRACK, level=0, target=7001),
                (EMBARRASS_TRACK, 0, 7001),
                THROW_TRACK,
            ),
        )
        for label, chosen, request, expectedTrack in cases:
            with self.subTest(label=label):
                holder = SimpleNamespace(
                    air=_Air(),
                    ignoreResponses=0,
                    fsm=_Fsm(),
                    activeToons=[101],
                    responses={101: 1},
                    toonAttacks={101: chosen},
                    getToon=lambda _toonId: SimpleNamespace(),
                    notify=DistributedBattleBaseAI.notify,
                )

                DistributedBattleBaseAI.requestAttack(holder, *request)

                self.assertEqual(holder.toonAttacks[101][1], expectedTrack)
                self.assertTrue(holder.air.events)
                self.assertIn('more than one action', holder.air.events[0][-1])

    def test_server_rejects_an_empty_reactive_track(self):
        class _State:
            def getName(self):
                return 'WaitForInput'

        class _Fsm:
            def getCurrentState(self):
                return _State()

        rejected = []

        def validate(_toonId, condition, message):
            if not condition:
                rejected.append(message)
            return condition

        toon = SimpleNamespace(
            getGameAccess=lambda: ToontownGlobals.AccessFull,
            hasReactiveGag=lambda _track, _level: False,
        )
        holder = SimpleNamespace(
            air=SimpleNamespace(
                getAvatarIdFromSender=lambda: 101,
                writeServerEvent=lambda *_event: None,
            ),
            ignoreResponses=0,
            fsm=_Fsm(),
            activeToons=[101],
            activeSuits=[_Suit(7001)],
            responses={101: 0},
            toonAttacks={101: getToonAttack(101)},
            getToon=lambda _toonId: toon,
            validate=validate,
            notify=DistributedBattleBaseAI.notify,
        )

        DistributedBattleBaseAI.requestAttack(
            holder, DECOY_TRACK, 0, 101)

        self.assertEqual(holder.toonAttacks[101][1], -1)
        self.assertTrue(rejected)
        self.assertIn('no reactive gag inventory', rejected[0])

    def test_ordinary_gag_still_uses_the_normal_single_action_path(self):
        class _State:
            def getName(self):
                return 'WaitForInput'

        class _Fsm:
            def getCurrentState(self):
                return _State()

        toon = SimpleNamespace(
            getGameAccess=lambda: ToontownGlobals.AccessFull,
            inventory=SimpleNamespace(numItem=lambda _track, _level: 1),
        )
        holder = SimpleNamespace(
            air=SimpleNamespace(
                getAvatarIdFromSender=lambda: 101,
                writeServerEvent=lambda *_event: None,
            ),
            ignoreResponses=0,
            fsm=_Fsm(),
            activeToons=[101],
            activeSuits=[_Suit(7001)],
            runningToons=[],
            responses={101: 0},
            toonAttacks={101: getToonAttack(101)},
            getToon=lambda _toonId: toon,
            validate=lambda _toonId, condition, _message: condition,
            d_setChosenToonAttacks=lambda: None,
            _DistributedBattleBaseAI__allActiveToonsResponded=lambda: False,
            notify=DistributedBattleBaseAI.notify,
        )

        DistributedBattleBaseAI.requestAttack(
            holder, THROW_TRACK, 0, 7001)

        self.assertEqual(holder.toonAttacks[101][1], THROW_TRACK)
        self.assertEqual(holder.responses[101], 1)


if __name__ == '__main__':
    unittest.main()
