import json
import os
import tempfile
import unittest

from toontown.authority.BrowserProgressionLedgerAI import (
    BrowserProgressionLedgerStore,
    GENESIS_HEAD,
)


class GameAuthorityLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = BrowserProgressionLedgerStore(
            bytes([37]) * 32, root=self.temporary.name)
        self.state = {
            'st': 'a' * 43,
            'sq': 4,
            'm': 'b' * 22,
        }

    def test_entries_chain_and_persist_atomically(self):
        first = self.store.append(
            1001, 'fishing.cast', self.state,
            details={'cost': 1}, now=10)
        self.assertEqual(first['previous'], GENESIS_HEAD)
        self.assertEqual(first['sequence'], 0)
        self.assertEqual(first['approvedSequence'], 4)
        self.state['sq'] = 5
        second = self.store.append(
            1001, 'fish-bingo.reward', self.state,
            details={'beans': 10}, now=11)
        self.assertEqual(second['previous'], first['signature'])
        headPath = os.path.join(
            self.temporary.name, '1001', 'head.json')
        with open(headPath, 'r', encoding='utf8') as stream:
            head = json.load(stream)
        self.assertEqual(head['signature'], second['signature'])
        self.assertEqual(second['sequence'], 1)
        self.assertEqual(second['approvedSequence'], 5)
        self.assertEqual(head['sequence'], 1)
        self.assertEqual(
            os.stat(headPath).st_mode & 0o777, 0o600)

    def test_tampered_head_entry_blocks_the_next_append(self):
        entry = self.store.append(
            1002, 'fishing.cast', self.state, now=20)
        entryPath = os.path.join(
            self.temporary.name,
            '1002',
            '%020d-%s.json' % (entry['sequence'], entry['signature']))
        with open(entryPath, 'r', encoding='utf8') as stream:
            tampered = json.load(stream)
        tampered['details'] = {'cost': 999}
        with open(entryPath, 'w', encoding='utf8') as stream:
            json.dump(tampered, stream)
        self.state['sq'] = 5
        with self.assertRaises(ValueError):
            self.store.append(
                1002, 'fish-bingo.reward', self.state, now=21)


if __name__ == '__main__':
    unittest.main()
