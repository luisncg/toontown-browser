#!/usr/bin/env python3

import ast
import builtins
import math
import pathlib
import re
import types
import unittest
from unittest import mock

from panda3d.core import loadPrcFile

loadPrcFile('etc/Configrc.prc')


class _Game:
    name = 'toontown'
    process = 'server'


builtins.game = _Game
import otp.ai.AIBaseGlobal  # noqa: E402,F401 - installs server globals

from otp.avatar.DistributedPlayerAI import DistributedPlayerAI
from toontown.authority import ServerActionGuardsAI
from toontown.authority.ServerRewardRulesAI import (
    boundedMinigameReward,
    cashbotGoonDamage,
    cashbotSafeDamage,
    fixedBossDamage,
    lawbotDefensePanDamage,
)


class _MovementAvatar:
    _acceptMovement = DistributedPlayerAI._acceptMovement
    _rejectMovement = DistributedPlayerAI._rejectMovement

    def __init__(self):
        self.doId = 1234
        self.position = [0.0, 0.0, 0.0]
        self.heading = [0.0, 0.0, 0.0]
        self._movementLastAt = 100.0
        self._movementCredit = 2.0
        self._verticalCredit = 1.0
        self._movementRejects = []
        self.updates = []
        self.events = []
        self.air = types.SimpleNamespace(
            writeServerEvent=lambda *args: self.events.append(args))

    def getPos(self):
        return tuple(self.position)

    def getHpr(self):
        return tuple(self.heading)

    def sendUpdate(self, fieldName, args):
        self.updates.append((fieldName, args))


class _LocatedObject:
    def __init__(self, position, parent=5000, zone=5100):
        self.position = position
        self.parentId = parent
        self.zoneId = zone

    def getPos(self):
        return self.position


class SecurityAuthorityGuardTests(unittest.TestCase):
    def test_movement_envelope_accepts_normal_step_and_rejects_teleport(self):
        avatar = _MovementAvatar()
        with mock.patch(
                'otp.avatar.DistributedPlayerAI.time.monotonic',
                return_value=100.0):
            self.assertTrue(avatar._acceptMovement((1.0, 0.0, 0.0)))
            self.assertFalse(avatar._acceptMovement((20.0, 0.0, 0.0)))
        self.assertEqual(avatar.updates[-1][0], 'setSmPosHpr')
        self.assertEqual(avatar.events[-1][0], 'suspicious')

    def test_movement_envelope_rejects_non_finite_coordinates(self):
        avatar = _MovementAvatar()
        self.assertFalse(
            avatar._acceptMovement((math.inf, 0.0, 0.0)))
        self.assertIn('non-finite', avatar.events[-1][2])
        self.assertFalse(
            avatar._acceptMovement((10001.0, 0.0, 0.0)))
        self.assertIn('world bounds', avatar.events[-1][2])

    def test_public_chat_normalizes_text_and_blocks_contact_details(self):
        moderate = DistributedPlayerAI._moderatePublicChat
        self.assertEqual(moderate('  Hello\n   Toons!  '), 'Hello Toons!')
        self.assertIsNone(moderate('visit https://example.com'))
        self.assertIsNone(moderate('visit www.example.com'))
        self.assertIsNone(moderate('toon@example.com'))
        self.assertIsNone(moderate('call 212-555-0199'))
        self.assertIsNone(moderate('kill yourself'))

    def test_public_chat_submission_cannot_broadcast_before_ai_review(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root / 'etc' / 'otp.dc').read_text(encoding='utf8')
        ownerPath = re.search(
            r'dclass TalkPath_owner\s*\{(.*?)\n\};',
            source,
            re.DOTALL)
        self.assertIsNotNone(ownerPath)
        self.assertRegex(
            ownerPath.group(1),
            r'requestTalk\([^;]+\)\s+clsend airecv;')
        setTalk = re.search(
            r'setTalk\([^;]+\)\s+([^;]+);',
            ownerPath.group(1))
        self.assertIsNotNone(setTalk)
        self.assertIn('broadcast', setTalk.group(1))
        self.assertNotIn('clsend', setTalk.group(1))
        self.assertNotIn('airecv', setTalk.group(1))

    def test_interaction_guard_requires_same_location_and_distance(self):
        events = []
        air = types.SimpleNamespace(
            writeServerEvent=lambda *args: events.append(args))
        avatar = _LocatedObject((0.0, 0.0, 0.0))
        nearby = _LocatedObject((10.0, 0.0, 0.0))
        far = _LocatedObject((100.0, 0.0, 0.0))
        elsewhere = _LocatedObject((1.0, 0.0, 0.0), zone=5200)
        with mock.patch(
                'toontown.authority.ServerActionGuardsAI.time.monotonic',
                return_value=200.0):
            self.assertTrue(ServerActionGuardsAI.requireInteraction(
                air, 1234, avatar, nearby))
            self.assertFalse(ServerActionGuardsAI.requireInteraction(
                air, 1234, avatar, far))
            self.assertFalse(ServerActionGuardsAI.requireInteraction(
                air, 1234, avatar, elsewhere))
        self.assertGreaterEqual(len(events), 2)

    def test_minigame_reward_is_server_time_bounded_not_client_score(self):
        reward = boundedMinigameReward(
            True, True, 0, 0, 100.0, endedAt=160.0)
        self.assertGreater(reward, 0)
        self.assertLessEqual(reward, 40)
        self.assertLessEqual(
            boundedMinigameReward(
                True, True, 0, 0, 100.0, endedAt=10000.0),
            40)
        self.assertEqual(
            boundedMinigameReward(
                False, True, 0, 0, 100.0, endedAt=160.0),
            0)
        self.assertEqual(
            boundedMinigameReward(
                True, True, 0, 0, 100.0, endedAt=105.0),
            0)

    def test_boss_damage_is_derived_from_server_rules(self):
        self.assertEqual(fixedBossDamage(1), 1)
        self.assertIsNone(fixedBossDamage(2))
        self.assertIsNone(fixedBossDamage(math.inf))
        self.assertEqual(cashbotSafeDamage(), 25)
        self.assertEqual(cashbotGoonDamage(1.5, 35), 35)
        self.assertEqual(cashbotGoonDamage(0, 35), 0)
        self.assertEqual(lawbotDefensePanDamage(6, True, 2), 12)

    def test_every_distributed_toon_database_field_is_ledger_gated(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root / 'etc' / 'toon.dc').read_text(encoding='utf8')
        toonClass = re.search(
            r'dclass DistributedToon\s*:[^{]+\{(.*?)\n\};',
            source,
            re.DOTALL)
        self.assertIsNotNone(toonClass)
        databaseFields = set(re.findall(
            r'^\s*([A-Za-z_]\w*)\([^;]*\)[^;]*\bdb\b[^;]*;',
            toonClass.group(1),
            re.MULTILINE))
        self.assertTrue(databaseFields)
        toonAiTree = ast.parse(
            (root / 'toontown' / 'toon' / 'DistributedToonAI.py').read_text(
                encoding='utf8'))
        ledgeredFields = None
        for node in toonAiTree.body:
            if isinstance(node, ast.ClassDef) and node.name == 'DistributedToonAI':
                for statement in node.body:
                    if (
                            isinstance(statement, ast.Assign) and
                            any(
                                isinstance(target, ast.Name) and
                                target.id == '_LEDGERED_DB_FIELDS'
                                for target in statement.targets)):
                        call = statement.value
                        ledgeredFields = set(ast.literal_eval(call.args[0]))
                        break
        self.assertEqual(
            databaseFields - (ledgeredFields or set()),
            set(),
            'A DistributedToon DB field is missing its ledger gate')


if __name__ == '__main__':
    unittest.main()
