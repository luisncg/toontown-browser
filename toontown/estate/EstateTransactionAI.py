"""Small transaction helpers shared by estate gameplay services.

Astron can atomically compare-and-swap several fields when they belong to one
database object.  Estate services use :class:`AstronObjectTransaction` instead
of issuing a series of independent ``b_set*`` calls.  The latter can charge a
Toon while failing to deliver an item, or persist only half of a furniture
move.

The helper deliberately does not pretend to offer a cross-object transaction.
Flows which touch both a Toon and a House need an explicit recovery journal.
"""

from collections import OrderedDict, deque
import hashlib
import os


def unpack_field_value(value):
    """Return the Python value from Astron's one-argument DC field tuple."""
    if isinstance(value, (tuple, list)) and len(value) == 1:
        return value[0]
    return value


def chargeBalances(money, bankMoney, cost):
    """Return post-charge pocket/bank balances without mutating a Toon."""
    money = int(money)
    bankMoney = int(bankMoney)
    cost = int(cost)
    if cost < 0 or cost > money + bankMoney:
        return None
    newMoney = max(0, money - cost)
    return newMoney, bankMoney - max(0, cost - money)


class ResponseReplayCache:
    """Bounded idempotency cache for client request contexts.

    A context is only unique to an avatar and operation.  Keeping the payload
    fingerprint alongside the response lets callers replay harmless retries
    while detecting context reuse with different arguments.
    """

    def __init__(self, capacity=256):
        self.capacity = max(1, int(capacity))
        self._entries = OrderedDict()

    def lookup(self, key, fingerprint):
        entry = self._entries.get(key)
        if entry is None:
            return 'missing', None
        oldFingerprint, response = entry
        self._entries.move_to_end(key)
        if oldFingerprint != fingerprint:
            return 'mismatch', None
        return 'replay', response

    def remember(self, key, fingerprint, response):
        self._entries[key] = (fingerprint, response)
        self._entries.move_to_end(key)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)


class SerialOperationQueue:
    """Serialize asynchronous mutations without dropping fast UI requests."""

    def __init__(self):
        self._active = False
        self._pending = deque()

    def submit(self, operation):
        self._pending.append(operation)
        self._run_next()

    def _run_next(self):
        if self._active or not self._pending:
            return
        self._active = True
        operation = self._pending.popleft()
        operation(self._finished)

    def _finished(self):
        if not self._active:
            return
        self._active = False
        self._run_next()

    @property
    def pending_count(self):
        return len(self._pending) + int(self._active)


class AstronObjectTransaction:
    """Compare-and-swap one object's fields through Astron's DB interface."""

    def __init__(self, air, doId, dclass):
        self.air = air
        self.doId = doId
        self.dclass = dclass

    def commit(self, oldFields, newFields, callback):
        if set(oldFields) != set(newFields):
            raise ValueError('transaction field sets must match')
        progression = self._progressionApproval(oldFields, newFields)
        if progression is False:
            callback(False, {})
            return
        packedOldFields = {
            name: self._packValue(name, value)
            for name, value in oldFields.items()
        }
        packedNewFields = {
            name: self._packValue(name, value)
            for name, value in newFields.items()
        }

        def handleResult(conflictingFields):
            if conflictingFields is None:
                if progression:
                    self._recordProgression(
                        'astron.cas.committed', progression)
                callback(True, None)
                return
            normalized = {
                name: unpack_field_value(value)
                for name, value in conflictingFields.items()
            }
            callback(False, normalized)

        self.air.dbInterface.updateObject(
            self.air.dbId,
            self.doId,
            self.dclass,
            packedNewFields,
            packedOldFields,
            handleResult)

    def _progressionApproval(self, oldFields, newFields):
        getName = getattr(self.dclass, 'getName', None)
        dclassName = getName() if getName is not None else 'unknown'
        fields = sorted(str(field) for field in newFields)
        digest = hashlib.sha256(repr([
            (field, oldFields[field], newFields[field])
            for field in sorted(newFields)
        ]).encode('utf8')).hexdigest()
        details = {
            'dclass': str(dclassName)[:128],
            'fields': fields,
            'valueDigest': digest,
        }
        if not self._recordProgression('astron.cas.approved', details):
            return False
        return details

    def _recordProgression(self, mutation, details):
        manager = getattr(self.air, 'browserAuthorityManager', None)
        if manager is None:
            return os.environ.get('TOONTOWN_PRODUCTION') != '1'
        return manager.recordProgressionMutation(
            self.doId, mutation, details)

    def _packValue(self, fieldName, value):
        getField = getattr(self.dclass, 'getFieldByName', None)
        if getField is None:
            return value
        field = getField(fieldName)
        atomic = field.asAtomicField() if field is not None else None
        if atomic is not None and atomic.getNumElements() == 1:
            return (value,)
        return value
