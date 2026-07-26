#!/usr/bin/env python3

import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, ResponseReplayCache, SerialOperationQueue,
    chargeBalances)
from toontown.estate.EstateTransactionJournal import (
    decodeJournal, encodeJournal)
from toontown.estate.EstateGardenState import (
    advanceDays, elapsedEpochDays, getItem, withItem, withoutItem)


class FakeDatabaseInterface:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def updateObject(self, databaseId, doId, dclass, newFields, oldFields,
                     callback):
        self.calls.append((
            databaseId, doId, dclass, newFields, oldFields))
        callback(self.result)


class FakeAir:
    dbId = 4003

    def __init__(self, result=None):
        self.dbInterface = FakeDatabaseInterface(result)


class FakeAtomicField:
    def getNumElements(self):
        return 1


class FakeField:
    def asAtomicField(self):
        return FakeAtomicField()


class FakeDClass:
    def getFieldByName(self, name):
        return FakeField()


class FakeToonDClass(FakeDClass):
    def getName(self):
        return 'DistributedToon'


class FakeAuthorityManager:
    def __init__(self, approved=True):
        self.approved = approved
        self.calls = []

    def recordProgressionMutation(self, avId, mutation, details):
        self.calls.append((avId, mutation, details))
        return self.approved


class EstateTransactionTests(unittest.TestCase):
    def test_multi_field_compare_and_swap_success(self):
        air = FakeAir()
        transaction = AstronObjectTransaction(air, 1234, object())
        result = []

        transaction.commit(
            {'setAtticItems': b'old', 'setInteriorItems': b'room-old'},
            {'setAtticItems': b'new', 'setInteriorItems': b'room-new'},
            lambda committed, conflict: result.append((committed, conflict)))

        self.assertEqual(result, [(True, None)])
        self.assertEqual(len(air.dbInterface.calls), 1)
        self.assertEqual(
            set(air.dbInterface.calls[0][3]),
            {'setAtticItems', 'setInteriorItems'})

    def test_conflict_values_are_unpacked(self):
        air = FakeAir({
            'setAtticItems': (b'actual-attic',),
            'setInteriorItems': (b'actual-room',),
        })
        transaction = AstronObjectTransaction(air, 1234, object())
        result = []

        transaction.commit(
            {'setAtticItems': b'old', 'setInteriorItems': b'room-old'},
            {'setAtticItems': b'new', 'setInteriorItems': b'room-new'},
            lambda committed, conflict: result.append((committed, conflict)))

        self.assertEqual(result, [(False, {
            'setAtticItems': b'actual-attic',
            'setInteriorItems': b'actual-room',
        })])

    def test_mismatched_field_set_is_rejected_before_database_write(self):
        air = FakeAir()
        transaction = AstronObjectTransaction(air, 1234, object())
        with self.assertRaises(ValueError):
            transaction.commit(
                {'setAtticItems': b'old'},
                {'setInteriorItems': b'new'},
                lambda committed, conflict: None)
        self.assertEqual(air.dbInterface.calls, [])

    def test_single_array_arguments_are_wrapped_for_dc_packing(self):
        air = FakeAir()
        transaction = AstronObjectTransaction(air, 1234, FakeDClass())
        transaction.commit(
            {'setSlot0Items': []},
            {'setSlot0Items': [[49, 0, 0, 0, 0]]},
            lambda committed, conflict: None)
        self.assertEqual(
            air.dbInterface.calls[0][4]['setSlot0Items'], ([],))
        self.assertEqual(
            air.dbInterface.calls[0][3]['setSlot0Items'],
            ([[49, 0, 0, 0, 0]],))

    def test_single_scalar_arguments_are_wrapped_for_dc_packing(self):
        air = FakeAir()
        transaction = AstronObjectTransaction(air, 1234, FakeDClass())
        transaction.commit(
            {'setLastEpochTimeStamp': 1784378865},
            {'setLastEpochTimeStamp': 1784378866},
            lambda committed, conflict: None)
        self.assertEqual(
            air.dbInterface.calls[0][4]['setLastEpochTimeStamp'],
            (1784378865,))
        self.assertEqual(
            air.dbInterface.calls[0][3]['setLastEpochTimeStamp'],
            (1784378866,))

    def test_toon_compare_and_swap_requires_durable_progression_approval(self):
        air = FakeAir()
        air.browserAuthorityManager = FakeAuthorityManager(approved=False)
        transaction = AstronObjectTransaction(
            air, 1234, FakeToonDClass())
        result = []
        transaction.commit(
            {'setMoney': 10},
            {'setMoney': 20},
            lambda committed, conflict: result.append((committed, conflict)))
        self.assertEqual(result, [(False, {})])
        self.assertEqual(air.dbInterface.calls, [])
        self.assertEqual(
            air.browserAuthorityManager.calls[0][1],
            'astron.cas.approved')

    def test_toon_compare_and_swap_records_approval_and_commit(self):
        air = FakeAir()
        air.browserAuthorityManager = FakeAuthorityManager()
        transaction = AstronObjectTransaction(
            air, 1234, FakeToonDClass())
        transaction.commit(
            {'setMoney': 10},
            {'setMoney': 20},
            lambda committed, conflict: None)
        self.assertEqual(
            [call[1] for call in air.browserAuthorityManager.calls],
            ['astron.cas.approved', 'astron.cas.committed'])

    def test_response_cache_replays_only_matching_payload(self):
        cache = ResponseReplayCache(capacity=2)
        key = (1001, 'move', 7)
        cache.remember(key, ('chair',), (1, 7))
        self.assertEqual(
            cache.lookup(key, ('chair',)), ('replay', (1, 7)))
        self.assertEqual(
            cache.lookup(key, ('table',)), ('mismatch', None))
        self.assertEqual(
            cache.lookup((1001, 'move', 8), ('chair',)),
            ('missing', None))

    def test_response_cache_is_bounded(self):
        cache = ResponseReplayCache(capacity=2)
        cache.remember(('a',), (), (1,))
        cache.remember(('b',), (), (2,))
        cache.remember(('c',), (), (3,))
        self.assertEqual(cache.lookup(('a',), ()), ('missing', None))
        self.assertEqual(cache.lookup(('c',), ()), ('replay', (3,)))

    def test_serial_queue_waits_for_async_completion(self):
        queue = SerialOperationQueue()
        events = []
        completions = []

        def first(done):
            events.append('first-start')
            completions.append(done)

        def second(done):
            events.append('second-start')
            done()

        queue.submit(first)
        queue.submit(second)
        self.assertEqual(events, ['first-start'])
        self.assertEqual(queue.pending_count, 2)
        completions[0]()
        self.assertEqual(events, ['first-start', 'second-start'])
        self.assertEqual(queue.pending_count, 0)

    def test_recovery_journal_round_trips_nested_binary_values(self):
        payload = {
            'kind': 'mailbox-house-delivery',
            'itemBlob': b'\x00\xffitem',
            'fields': {
                'setAtticItems': b'attic',
                'setInteriorItems': [b'room', 7],
            },
        }
        self.assertEqual(decodeJournal(encodeJournal(payload)), payload)

    def test_recovery_journal_rejects_unknown_versions(self):
        with self.assertRaises(ValueError):
            decodeJournal(b'{"version":2,"payload":{}}')

    def test_garden_items_replace_and_remove_by_hardpoint(self):
        items = withItem([], [49, 3, 0, 0, 2])
        items = withItem(items, [50, 3, 4, 1, 0])
        self.assertEqual(items, [[50, 3, 4, 1, 0]])
        self.assertEqual(getItem(items, 3), [50, 3, 4, 1, 0])
        self.assertEqual(withoutItem(items, 3), [])

    def test_garden_daily_growth_requires_non_wilted_water(self):
        # Daisy growth caps at its final threshold of one.
        attributes = {49: {
            'plantType': 1,
            'minWaterLevel': -2,
            'growthThresholds': (1, 1, 1),
        }}
        self.assertEqual(
            advanceDays([[49, 0, 0, 0, 0]], 2, attributes),
            [[49, 0, -2, 1, 0]])
        self.assertEqual(
            advanceDays([[49, 0, -1, 0, 0]], 1, attributes),
            [[49, 0, -2, 0, 0]])

    def test_epoch_day_math_survives_uint16_wrap(self):
        self.assertEqual(elapsedEpochDays(65535, 1), 2)

    def test_charge_balances_uses_pocket_before_bank(self):
        self.assertEqual(chargeBalances(20, 100, 35), (0, 85))
        self.assertEqual(chargeBalances(20, 100, 10), (10, 100))
        self.assertIsNone(chargeBalances(20, 10, 31))


if __name__ == '__main__':
    unittest.main()
