"""Recoverable Toon + Estate transactions used by gardening."""

import hashlib
import time

from toontown.estate.EstateGardenState import getItem, withItem, withoutItem
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.estate.EstateTransactionJournal import (
    decodeJournal, encodeJournal)


class GardenCrossObjectTransaction:
    KIND = 'garden-estate-mutation'

    def __init__(self, air):
        self.air = air

    def begin(self, avatar, estate, slotField, oldItems, newItems,
              toonOldFields, toonNewFields, metadata, callback):
        digest = hashlib.sha256(repr((
            avatar.doId, estate.doId, slotField, oldItems, newItems,
            toonNewFields, time.time())).encode('utf-8')).hexdigest()
        payload = {
            'kind': self.KIND,
            'txid': digest,
            'avatarId': avatar.doId,
            'estateId': estate.doId,
            'slotField': slotField,
            'oldItems': oldItems,
            'newItems': newItems,
            'toonOldFields': toonOldFields,
            'toonNewFields': toonNewFields,
            'metadata': metadata,
        }
        journal = encodeJournal(payload)
        oldFields = dict(toonOldFields)
        oldFields['setEstateTransactionJournal'] = b''
        newFields = dict(toonNewFields)
        newFields['setEstateTransactionJournal'] = journal
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def prepared(success, conflicts):
            if not success:
                callback(False, 'toon-conflict')
                return
            avatar.setEstateTransactionJournal(journal)
            self.applyToonFields(avatar, toonNewFields)
            self._commitEstate(
                avatar, estate, payload, journal,
                lambda committed, reason: callback(committed, reason))

        transaction.commit(oldFields, newFields, prepared)

    def recover(self, avatar, estate, callback):
        journal = avatar.getEstateTransactionJournal()
        try:
            payload = decodeJournal(journal)
        except Exception:
            callback(False, 'invalid-journal')
            return
        if (not payload or payload.get('kind') != self.KIND or
                payload.get('avatarId') != avatar.doId or
                payload.get('estateId') != estate.doId):
            callback(False, 'unrelated-journal')
            return
        self._commitEstate(avatar, estate, payload, journal, callback)

    def _commitEstate(self, avatar, estate, payload, journal, callback):
        slotField = payload['slotField']
        currentItems = self._getEstateField(estate, slotField)
        oldItems = payload['oldItems']
        newItems = payload['newItems']
        if currentItems == newItems:
            self._finalize(avatar, journal, callback)
            return
        if currentItems != oldItems:
            metadata = payload.get('metadata', {})
            hardPoint = metadata.get('hardPoint')
            intended = getItem(newItems, hardPoint) if hardPoint is not None else None
            oldTarget = getItem(oldItems, hardPoint) if hardPoint is not None else None
            if (hardPoint is not None and intended is not None and
                    getItem(currentItems, hardPoint) == intended):
                self._finalize(avatar, journal, callback)
                return
            if (hardPoint is not None and intended is None and
                    getItem(currentItems, hardPoint) is None):
                self._finalize(avatar, journal, callback)
                return
            if (hardPoint is not None and intended is not None and
                    getItem(currentItems, hardPoint) is None):
                # A different plot changed concurrently. Rebase this one
                # hardpoint rather than rolling back an otherwise valid plant.
                rebased = withItem(currentItems, intended)
                payload['oldItems'] = currentItems
                payload['newItems'] = rebased
                # The journal already contains the original lists, but this
                # process can finish the rebased CAS immediately. A conflict
                # here leaves the journal for another recovery attempt.
                oldItems = currentItems
                newItems = rebased
            elif (hardPoint is not None and intended is None and
                    getItem(currentItems, hardPoint) == oldTarget):
                oldItems = currentItems
                newItems = withoutItem(currentItems, hardPoint)
            else:
                self._rollback(avatar, payload, journal, callback)
                return

        transaction = AstronObjectTransaction(
            self.air, estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])

        def committed(success, conflicts):
            if not success:
                callback(False, 'estate-conflict-pending-recovery')
                return
            self._setEstateField(estate, slotField, newItems)
            self._finalize(avatar, journal, callback)

        transaction.commit(
            {slotField: oldItems}, {slotField: newItems}, committed)

    def _finalize(self, avatar, journal, callback):
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def finalized(success, conflicts):
            if success:
                avatar.setEstateTransactionJournal(b'')
                callback(True, 'committed')
            else:
                callback(False, 'finalize-pending-recovery')

        transaction.commit(
            {'setEstateTransactionJournal': journal},
            {'setEstateTransactionJournal': b''},
            finalized)

    def _rollback(self, avatar, payload, journal, callback):
        expected = dict(payload.get('toonNewFields', {}))
        expected['setEstateTransactionJournal'] = journal
        restored = dict(payload.get('toonOldFields', {}))
        restored['setEstateTransactionJournal'] = b''
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def rolledBack(success, conflicts):
            if success:
                avatar.setEstateTransactionJournal(b'')
                self.applyToonFields(
                    avatar, payload.get('toonOldFields', {}))
                callback(False, 'rolled-back')
            else:
                callback(False, 'rollback-pending-manual-recovery')

        transaction.commit(expected, restored, rolledBack)

    @staticmethod
    def applyToonFields(avatar, fields):
        methods = {
            'setMoney': ('setMoney', 'd_setMoney'),
            'setBankMoney': ('setBankMoney', 'd_setBankMoney'),
            'setInventory': ('setInventory', 'd_setInventory'),
            'setGardenSpecials': (
                'setGardenSpecials', 'd_setGardenSpecials'),
            'setShovelSkill': ('setShovelSkill', 'd_setShovelSkill'),
            'setShovel': ('setShovel', 'd_setShovel'),
            'setWateringCanSkill': (
                'setWateringCanSkill', 'd_setWateringCanSkill'),
            'setWateringCan': ('setWateringCan', 'd_setWateringCan'),
            'setFlowerBasket': ('setFlowerBasket', 'd_setFlowerBasket'),
        }
        for fieldName, value in fields.items():
            setterName, broadcasterName = methods[fieldName]
            if fieldName == 'setFlowerBasket':
                getattr(avatar, setterName)(*value)
                getattr(avatar, broadcasterName)(*value)
            else:
                getattr(avatar, setterName)(value)
                getattr(avatar, broadcasterName)(value)

    @staticmethod
    def _getEstateField(estate, fieldName):
        slot = int(fieldName[len('setSlot')])
        return [list(item) for item in
                getattr(estate, 'getSlot%sItems' % slot)()]

    @staticmethod
    def _setEstateField(estate, fieldName, items):
        slot = int(fieldName[len('setSlot')])
        getattr(estate, 'setSlot%sItems' % slot)(items)
