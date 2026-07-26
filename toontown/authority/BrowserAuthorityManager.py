import json
import time

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObject import DistributedObject
from direct.task import Task

try:
    import browser_authority
except ImportError:
    browser_authority = None


class BrowserAuthorityManager(DistributedObject):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'BrowserAuthorityManager')
    neverDisable = 1

    def __init__(self, cr):
        DistributedObject.__init__(self, cr)
        self.ready = browser_authority is None
        self.registered = False
        self.registeredAvatarId = 0
        self.marker = ''
        self.sequence = 0
        self.nextRequestId = 1
        self.queue = []
        self.active = None

    def generate(self):
        DistributedObject.generate(self)
        base.cr.browserAuthorityManager = self
        if browser_authority is not None:
            browser_authority.prepare_session()
            taskMgr.add(
                self._authorityTask,
                self.uniqueName('browser-authority'))

    def disable(self):
        taskMgr.remove(self.uniqueName('browser-authority'))
        if getattr(base.cr, 'browserAuthorityManager', None) is self:
            base.cr.browserAuthorityManager = None
        self.queue = []
        self.active = None
        DistributedObject.disable(self)

    def requestTransition(self, action, target, callback):
        if browser_authority is None:
            callback()
            return True
        self.queue.append({
            'action': action,
            'target': target,
            'callback': callback,
        })
        return True

    def runtimeReady(self, sequence, marker):
        self.sequence = sequence
        self.marker = marker
        self.ready = True
        self.notify.info(
            'Runtime authority ready at sequence %s (marker %s).' %
            (sequence, marker[:8]))

    def capabilityAccepted(self, requestId):
        if (
                self.active is None or
                self.active['requestId'] != requestId or
                self.active['phase'] != 'presented'):
            return
        self.active['phase'] = 'committing'
        self.active['deadline'] = time.time() + 15.0
        try:
            self.active['callback']()
        except Exception:
            self.notify.warning(
                'Protected transition callback failed for %s' %
                self.active['action'])
            self.active = None

    def transitionCommitted(self, requestId, stateJson, receiptJson):
        if self.active is None or self.active['requestId'] != requestId:
            return
        try:
            state = json.loads(stateJson)
            if not browser_authority.commit_state(json.dumps(
                    state, separators=(',', ':'))):
                raise ValueError('browser rejected successor state')
            self.sequence = state['sequence']
            self.marker = state['marker']
            self.notify.info(
                'Committed protected transition %s at sequence %s.' %
                (self.active['action'], self.sequence))
        except Exception:
            self.notify.warning('Could not commit successor authority state.')
            self.ready = False
            self.registered = False
            browser_authority.prepare_session()
        self.active = None

    def transitionRejected(self, requestId, reason):
        if self.active is not None and self.active['requestId'] == requestId:
            self.notify.warning(
                'Protected transition %s was rejected (%s).' %
                (self.active['action'], reason))
            self.active = None

    def _authorityTask(self, task):
        localAvatar = getattr(base, 'localAvatar', None)
        localAvatarId = getattr(localAvatar, 'doId', 0) if localAvatar else 0
        if (
                self.registeredAvatarId and
                localAvatarId != self.registeredAvatarId):
            self.registered = False
            self.ready = False
            self.registeredAvatarId = 0
            self.active = None
        if not self.registered:
            if not localAvatarId:
                return Task.cont
            stateJson = browser_authority.session_state()
            if stateJson:
                try:
                    state = json.loads(stateJson)
                    self.sendUpdate('registerRuntime', [state['stateToken']])
                    self.registered = True
                    self.registeredAvatarId = localAvatarId
                except Exception:
                    self.notify.warning(
                        'Browser game session state could not be registered.')
        if self.active is not None:
            self._pollActive()
        elif self.ready and self.registered and self.queue:
            self._startNext()
        return Task.cont

    def _startNext(self):
        value = self.queue.pop(0)
        requestId = self.nextRequestId
        self.nextRequestId = 1 if requestId >= 0xffffffff else requestId + 1
        accepted = browser_authority.request_transition(
            requestId,
            value['action'],
            json.dumps(value['target'], separators=(',', ':')))
        if not accepted:
            self.notify.warning(
                'Browser refused transition request %s.' % value['action'])
            return
        value.update({
            'requestId': requestId,
            'phase': 'requesting',
            'deadline': time.time() + 12.0,
        })
        self.active = value

    def _pollActive(self):
        if time.time() > self.active['deadline']:
            self.notify.warning(
                'Protected transition %s timed out.' % self.active['action'])
            self.active = None
            return
        if self.active['phase'] != 'requesting':
            return
        resultJson = browser_authority.poll_transition(
            self.active['requestId'])
        if not resultJson:
            return
        try:
            result = json.loads(resultJson)
        except Exception:
            result = {'ok': False}
        if not result.get('ok') or not result.get('capability'):
            self.notify.warning(
                'Transition capability request failed for %s.' %
                self.active['action'])
            self.active = None
            return
        self.active['phase'] = 'presented'
        self.active['deadline'] = time.time() + 12.0
        self.sendUpdate(
            'presentCapability',
            [self.active['requestId'], result['capability']])


def requestTransition(action, target, callback):
    manager = getattr(base.cr, 'browserAuthorityManager', None)
    if manager is None:
        callback()
        return True
    return manager.requestTransition(action, target, callback)
