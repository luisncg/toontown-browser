import base64
import hashlib
import json
import os
import subprocess
import unittest

from toontown.authority.BrowserCapabilityTokensAI import (
    advance_state,
    verify_state,
    verify_transition,
)


class GameAuthorityPythonTests(unittest.TestCase):
    def setUp(self):
        self.secret = base64.urlsafe_b64encode(bytes([7]) * 32).rstrip(
            b'=').decode('ascii')
        self.release = 'a' * 64
        self.thumbprint = 'b' * 64
        self.now_ms = 1800000000000

    def _node_fixture(self):
        script = r'''
          import {
            createGameSessionState,
            createGameTransitionCapability,
          } from "./browser/shared/game-authority.mjs";
          const state = createGameSessionState({
            secret: process.env.TEST_SECRET,
            release: "a".repeat(64),
            thumbprint: "b".repeat(64),
            now: 1800000000000,
          });
          const transition = createGameTransitionCapability({
            secret: process.env.TEST_SECRET,
            stateToken: state.stateToken,
            release: "a".repeat(64),
            thumbprint: "b".repeat(64),
            action: "estate.enter",
            target: {manager: 1001, owner: 2002},
            now: 1800000000000,
          });
          process.stdout.write(JSON.stringify({state, transition}));
        '''
        environment = os.environ.copy()
        environment['TEST_SECRET'] = self.secret
        output = subprocess.check_output(
            ['node', '--input-type=module', '--eval', script],
            cwd=os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..', '..')),
            env=environment,
            text=True)
        return json.loads(output)

    def test_node_tokens_verify_and_python_successor_chains(self):
        value = self._node_fixture()
        secret = base64.urlsafe_b64decode(self.secret + '=')
        state = verify_state(
            value['state']['stateToken'],
            secret=secret,
            release=self.release,
            now=self.now_ms // 1000)
        self.assertEqual(state['sq'], 0)
        transition = verify_transition(
            value['transition']['capability'],
            action='estate.enter',
            target={'manager': 1001, 'owner': 2002},
            secret=secret,
            release=self.release,
            now=self.now_ms // 1000)
        self.assertEqual(transition['ps'], state['st'])
        successor = advance_state(
            transition, secret=secret, now=self.now_ms // 1000)
        next_state = verify_state(
            successor['stateToken'],
            secret=secret,
            release=self.release,
            now=self.now_ms // 1000)
        self.assertEqual(next_state['st'], transition['ns'])
        self.assertEqual(next_state['sq'], 1)
        self.assertEqual(
            successor['receipt']['id'],
            hashlib.sha256('\n'.join((
                'toontown-browser-transition-receipt-v1',
                transition['sid'],
                transition['ps'],
                transition['ns'],
                transition['a'],
                str(transition['sq']),
            )).encode('utf8')).hexdigest())

    def test_target_change_is_rejected(self):
        value = self._node_fixture()
        secret = base64.urlsafe_b64decode(self.secret + '=')
        self.assertIsNone(verify_transition(
            value['transition']['capability'],
            action='estate.enter',
            target={'manager': 1001, 'owner': 9999},
            secret=secret,
            release=self.release,
            now=self.now_ms // 1000))


if __name__ == '__main__':
    unittest.main()
