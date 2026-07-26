import json
import os

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI

from toontown.authority.BrowserCapabilityTokensAI import (
    advance_state,
    authority_secret,
    normalize_target,
    verify_state,
    verify_transition,
)
from toontown.authority.BrowserProgressionLedgerAI import (
    BrowserProgressionLedgerStore,
)


REJECT_INVALID_SESSION = 1
REJECT_INVALID_CAPABILITY = 2
REJECT_STATE_MISMATCH = 3


class BrowserAuthorityManagerAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'BrowserAuthorityManagerAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.enforce = (
            os.environ.get('TOONTOWN_PRODUCTION') == '1' or
            config.GetBool('browser-authority-enforce', False))
        self.secret = authority_secret()
        self.states = {}
        self.sessionOwners = {}
        self.pending = {}
        self.recentReceipts = {}
        self.progressionLedger = BrowserProgressionLedgerStore(self.secret)

    def delete(self):
        self.states.clear()
        self.sessionOwners.clear()
        self.pending.clear()
        self.recentReceipts.clear()
        DistributedObjectAI.delete(self)

    def registerRuntime(self, stateToken):
        avId = self.air.getAvatarIdFromSender()
        state = verify_state(stateToken, self.secret)
        if not avId or state is None:
            self._reject(avId, 0, REJECT_INVALID_SESSION,
                         'invalid runtime registration')
            return
        previousOwner = self.sessionOwners.get(state['sid'])
        if (
                previousOwner and previousOwner != avId and
                previousOwner in self.air.doId2do):
            self._reject(avId, 0, REJECT_INVALID_SESSION,
                         'runtime session is already bound to another Toon')
            return
        if previousOwner and previousOwner != avId:
            self.states.pop(previousOwner, None)
            self.pending.pop(previousOwner, None)
        self.sessionOwners[state['sid']] = avId
        self.states[avId] = state
        self.pending.pop(avId, None)
        self.acceptOnce(
            self.air.getAvatarExitEvent(avId),
            self._dropAvatar,
            extraArgs=[avId])
        self.sendUpdateToAvatarId(
            avId, 'runtimeReady', [state['sq'], state['m']])
        self.air.writeServerEvent(
            'browserAuthoritySession', avId,
            'marker=%s sequence=%s epoch=%s' %
            (state['m'], state['sq'], state['ce']))
        self.notify.info(
            'Bound runtime authority to avatar %s at sequence %s '
            '(marker %s).' % (avId, state['sq'], state['m'][:8]))

    def presentCapability(self, requestId, capability):
        avId = self.air.getAvatarIdFromSender()
        state = self.states.get(avId)
        transition = verify_transition(capability, secret=self.secret)
        if not avId or state is None or transition is None:
            self._reject(avId, requestId, REJECT_INVALID_CAPABILITY,
                         'invalid transition capability')
            return
        if not self._chains(state, transition):
            self._reject(avId, requestId, REJECT_STATE_MISMATCH,
                         'transition did not chain to approved state')
            return
        self.pending[avId] = {
            'requestId': requestId,
            'capability': capability,
            'transition': transition,
        }
        self.sendUpdateToAvatarId(
            avId, 'capabilityAccepted', [requestId])

    def consumeTransition(self, avId, action, target):
        try:
            normalized = normalize_target(action, target)
        except Exception:
            return False
        state = self.states.get(avId)
        pending = self.pending.get(avId)
        if state is None or pending is None:
            if self.enforce:
                self._suspicious(
                    avId, 'missing capability for %s' % action)
                return False
            return True
        transition = verify_transition(
            pending['capability'],
            action=action,
            target=normalized,
            secret=self.secret)
        if transition is None or not self._chains(state, transition):
            self.pending.pop(avId, None)
            if self.enforce:
                self._suspicious(
                    avId, 'mismatched capability for %s' % action)
                return False
            return True
        self.pending.pop(avId, None)
        successor = advance_state(transition, self.secret)
        nextState = verify_state(successor['stateToken'], self.secret)
        if nextState is None:
            self._suspicious(avId, 'successor state verification failed')
            return False
        self.states[avId] = nextState
        requestId = pending['requestId']
        receipt = successor['receipt']
        receipts = self.recentReceipts.setdefault(avId, [])
        receipts.append(receipt)
        del receipts[:-32]
        self.sendUpdateToAvatarId(
            avId,
            'transitionCommitted',
            [
                requestId,
                json.dumps(successor, separators=(',', ':')),
                json.dumps(receipt, separators=(',', ':')),
            ])
        self.air.writeServerEvent(
            'browserAuthorityTransition', avId,
            'action=%s sequence=%s marker=%s receipt=%s' %
            (action, transition['sq'], transition['m'], receipt['id'][:16]))
        self.notify.info(
            'Consumed %s for avatar %s at sequence %s.' %
            (action, avId, transition['sq']))
        return True

    def recordProgressionMutation(self, avId, mutation, details=None):
        state = self.states.get(avId)
        if state is None:
            return False
        try:
            entry = self.progressionLedger.append(
                avId, mutation, state, details=details)
        except Exception:
            self.notify.warning(
                'Could not persist progression ledger mutation %s for '
                'avatar %s.' % (mutation, avId))
            return False
        self.notify.info(
            'Recorded progression mutation %s for avatar %s at sequence %s '
            '(head %s).' %
            (mutation, avId, entry['sequence'], entry['signature'][:12]))
        return True

    @staticmethod
    def _chains(state, transition):
        return (
            transition['pk'] == state['pk'] and
            transition['r'] == state['r'] and
            transition['sid'] == state['sid'] and
            transition['ps'] == state['st'] and
            transition['sq'] == state['sq'] + 1 and
            transition['ce'] == state['ce'] and
            transition['m'] == state['m'])

    def _reject(self, avId, requestId, reason, message):
        if avId:
            self.sendUpdateToAvatarId(
                avId, 'transitionRejected', [requestId, reason])
            self._suspicious(avId, message)

    def _dropAvatar(self, avId):
        state = self.states.pop(avId, None)
        self.pending.pop(avId, None)
        self.recentReceipts.pop(avId, None)
        if (
                state is not None and
                self.sessionOwners.get(state['sid']) == avId):
            self.sessionOwners.pop(state['sid'], None)

    def _suspicious(self, avId, message):
        self.air.writeServerEvent(
            'suspicious', avId or 0, 'BrowserAuthority: %s' % message)


def consumeProtectedTransition(air, avId, action, target):
    manager = getattr(air, 'browserAuthorityManager', None)
    if manager is not None:
        return manager.consumeTransition(avId, action, target)
    return os.environ.get('TOONTOWN_PRODUCTION') != '1'
