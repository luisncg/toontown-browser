import base64
import json
import os
import subprocess
import tempfile
import types
import unittest

from toontown.authority.BrowserAuthorityManagerAI import (
    BrowserAuthorityManagerAI,
)
from toontown.authority.BrowserCapabilityTokensAI import (
    advance_state,
    verify_state,
    verify_transition,
)
from toontown.authority.BrowserProgressionLedgerAI import (
    BrowserAuthorityHeadStore,
    BrowserProgressionLedgerStore,
)


class _Manager(BrowserAuthorityManagerAI):
    def sendUpdateToAvatarId(self, avId, fieldName, args):
        self.updates.append((avId, fieldName, args))


class GameAuthorityManagerTests(unittest.TestCase):
    def setUp(self):
        self.secretText = base64.urlsafe_b64encode(
            bytes([19]) * 32).rstrip(b'=').decode('ascii')
        self.secret = base64.urlsafe_b64decode(self.secretText + '=')
        self.release = 'a' * 64
        self.thumbprint = 'b' * 64
        script = r'''
          import {
            createGameSessionState,
            createGameTransitionCapability,
          } from "./browser/shared/game-authority.mjs";
          const state = createGameSessionState({
            secret: process.env.TEST_SECRET,
            release: "a".repeat(64),
            thumbprint: "b".repeat(64),
          });
          const transition = createGameTransitionCapability({
            secret: process.env.TEST_SECRET,
            stateToken: state.stateToken,
            release: "a".repeat(64),
            thumbprint: "b".repeat(64),
            action: "fish-bingo.claim",
            target: {manager: 501, card: 7},
          });
          process.stdout.write(JSON.stringify({state, transition}));
        '''
        environment = os.environ.copy()
        environment['TEST_SECRET'] = self.secretText
        output = subprocess.check_output(
            ['node', '--input-type=module', '--eval', script],
            cwd=os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..', '..')),
            env=environment,
            text=True)
        self.fixture = json.loads(output)
        self.events = []
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = _Manager.__new__(_Manager)
        self.manager.enforce = True
        self.manager.secret = self.secret
        self.manager.states = {}
        self.manager.sessionOwners = {}
        self.manager.pending = {}
        self.manager.recentReceipts = {}
        self.manager.authorityHeads = BrowserAuthorityHeadStore(
            self.secret, root=os.path.join(self.temporary.name, 'heads'))
        self.manager.progressionLedger = BrowserProgressionLedgerStore(
            self.secret, root=os.path.join(self.temporary.name, 'ledger'))
        self.manager.updates = []
        self.manager.air = types.SimpleNamespace(
            doId2do={},
            writeServerEvent=lambda *args: self.events.append(args))

    def test_consumption_advances_once_and_returns_signed_successor(self):
        avId = 1234
        state = verify_state(
            self.fixture['state']['stateToken'], self.secret)
        transition = verify_transition(
            self.fixture['transition']['capability'], secret=self.secret)
        self.manager.states[avId] = state
        self.manager.pending[avId] = {
            'requestId': 17,
            'capability': self.fixture['transition']['capability'],
            'transition': transition,
        }
        self.assertTrue(self.manager.consumeTransition(
            avId,
            'fish-bingo.claim',
            {'manager': 501, 'card': 7}))
        self.assertEqual(self.manager.states[avId]['sq'], 1)
        self.assertNotIn(avId, self.manager.pending)
        self.assertEqual(
            self.manager.updates[-1][1], 'transitionCommitted')
        successor = json.loads(self.manager.updates[-1][2][1])
        self.assertEqual(successor['sequence'], 1)
        self.assertIsNotNone(verify_state(
            successor['stateToken'], self.secret))
        self.assertFalse(self.manager.consumeTransition(
            avId,
            'fish-bingo.claim',
            {'manager': 501, 'card': 7}))

    def test_target_mismatch_does_not_mutate_game_state(self):
        avId = 1234
        state = verify_state(
            self.fixture['state']['stateToken'], self.secret)
        transition = verify_transition(
            self.fixture['transition']['capability'], secret=self.secret)
        self.manager.states[avId] = state
        self.manager.pending[avId] = {
            'requestId': 18,
            'capability': self.fixture['transition']['capability'],
            'transition': transition,
        }
        self.assertFalse(self.manager.consumeTransition(
            avId,
            'fish-bingo.claim',
            {'manager': 501, 'card': 8}))
        self.assertEqual(self.manager.states[avId]['sq'], 0)

    def test_durable_high_water_rejects_runtime_rewind(self):
        avId = 1234
        state = verify_state(
            self.fixture['state']['stateToken'], self.secret)
        transition = verify_transition(
            self.fixture['transition']['capability'], secret=self.secret)
        successor = advance_state(transition, self.secret)
        nextState = verify_state(successor['stateToken'], self.secret)
        self.assertTrue(self.manager.authorityHeads.observe(nextState))
        self.manager.states[avId] = state
        self.manager.pending[avId] = {
            'requestId': 19,
            'capability': self.fixture['transition']['capability'],
            'transition': transition,
        }
        self.assertFalse(self.manager.consumeTransition(
            avId,
            'fish-bingo.claim',
            {'manager': 501, 'card': 7}))
        self.assertEqual(self.manager.states[avId]['sq'], 0)

    def test_restarted_manager_rejects_old_runtime_registration(self):
        avId = 1234
        state = verify_state(
            self.fixture['state']['stateToken'], self.secret)
        transition = verify_transition(
            self.fixture['transition']['capability'], secret=self.secret)
        successor = advance_state(transition, self.secret)
        nextState = verify_state(successor['stateToken'], self.secret)
        self.assertTrue(self.manager.authorityHeads.observe(nextState))
        restartedStore = BrowserAuthorityHeadStore(
            self.secret,
            root=os.path.join(self.temporary.name, 'heads'))
        self.manager.authorityHeads = restartedStore
        self.manager.air.getAvatarIdFromSender = lambda: avId
        self.manager.air.getAvatarExitEvent = (
            lambda value: 'avatar-exit-%s' % value)
        self.manager.registerRuntime(self.fixture['state']['stateToken'])
        self.assertNotIn(avId, self.manager.states)
        self.assertEqual(
            self.manager.updates[-1][1], 'transitionRejected')
        self.assertFalse(restartedStore.observe(state))

    def test_server_driven_progression_is_durably_recorded(self):
        self.assertTrue(self.manager.recordProgressionMutation(
            1234, 'offline.delivery', {'itemDigest': 'c' * 64}))
        headPath = os.path.join(
            self.temporary.name, 'ledger', '1234', 'head.json')
        self.assertTrue(os.path.exists(headPath))


if __name__ == '__main__':
    unittest.main()
