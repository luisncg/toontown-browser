import hashlib
import hmac
import json
import os
import tempfile
import time


GENESIS_HEAD = '0' * 64


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(',', ':')).encode('utf8')


class BrowserProgressionLedgerStore:
    def __init__(self, secret, root=None):
        if root is None:
            root = os.environ.get('TOONTOWN_PROGRESSION_LEDGER_DIR')
        if not root:
            if os.environ.get('TOONTOWN_PRODUCTION') == '1':
                root = (
                    '/srv/toontown-browser/app/data/progression-ledgers')
            else:
                root = os.path.abspath(
                    os.path.join(
                        '.build-wasm', 'state', 'progression-ledgers'))
        self.secret = secret
        self.root = os.path.abspath(root)
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def append(self, avatarId, mutation, state, details=None, now=None):
        avatarId = int(avatarId)
        if avatarId <= 0:
            raise ValueError('invalid avatar id')
        mutation = str(mutation)
        if not mutation or len(mutation) > 64:
            raise ValueError('invalid mutation')
        safeDetails = details if isinstance(details, dict) else {}
        if len(_canonical(safeDetails)) > 4096:
            raise ValueError('progression details are too large')
        avatarRoot = os.path.join(self.root, str(avatarId))
        os.makedirs(avatarRoot, mode=0o700, exist_ok=True)
        try:
            os.chmod(avatarRoot, 0o700)
        except OSError:
            pass
        head = self._readHead(avatarRoot)
        ledgerSequence = int(head['sequence']) + 1
        entry = {
            'version': 1,
            'previous': head['signature'],
            'mutation': mutation,
            'approvedState': state['st'],
            'approvedSequence': int(state['sq']),
            'sequence': ledgerSequence,
            'marker': state['m'],
            'details': safeDetails,
            'at': int(time.time() if now is None else now),
        }
        entry['newState'] = hashlib.sha256(_canonical(entry)).hexdigest()
        entry['signature'] = hmac.new(
            self.secret, _canonical(entry), hashlib.sha256).hexdigest()
        entryName = '%020d-%s.json' % (
            entry['sequence'], entry['signature'])
        self._writeAtomic(
            os.path.join(avatarRoot, entryName), _canonical(entry) + b'\n')
        nextHead = {
            'version': 1,
            'signature': entry['signature'],
            'sequence': entry['sequence'],
            'entry': entryName,
        }
        self._writeAtomic(
            os.path.join(avatarRoot, 'head.json'),
            _canonical(nextHead) + b'\n')
        return entry

    def _readHead(self, avatarRoot):
        path = os.path.join(avatarRoot, 'head.json')
        if not os.path.exists(path):
            return {
                'version': 1,
                'signature': GENESIS_HEAD,
                'sequence': -1,
            }
        with open(path, 'rb') as stream:
            value = json.loads(stream.read().decode('utf8'))
        if (
                value.get('version') != 1 or
                not isinstance(value.get('signature'), str) or
                len(value['signature']) != 64 or
                not isinstance(value.get('sequence'), int)):
            raise ValueError('invalid progression ledger head')
        entryName = value.get('entry')
        if not isinstance(entryName, str) or '/' in entryName:
            raise ValueError('invalid progression ledger entry reference')
        with open(os.path.join(avatarRoot, entryName), 'rb') as stream:
            entry = json.loads(stream.read().decode('utf8'))
        signature = entry.pop('signature', None)
        expected = hmac.new(
            self.secret, _canonical(entry), hashlib.sha256).hexdigest()
        if (
                not hmac.compare_digest(signature or '', expected) or
                signature != value['signature'] or
                entry.get('sequence') != value['sequence']):
            raise ValueError('progression ledger signature mismatch')
        return value

    @staticmethod
    def _writeAtomic(path, content):
        directory = os.path.dirname(path)
        handle, temporary = tempfile.mkstemp(
            dir=directory, prefix='.ledger-', suffix='.tmp')
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, 'wb') as stream:
                handle = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directoryHandle = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directoryHandle)
            finally:
                os.close(directoryHandle)
        finally:
            if handle is not None:
                os.close(handle)
            if os.path.exists(temporary):
                os.unlink(temporary)


class BrowserAuthorityHeadStore:
    """Durable, signed high-water marks for runtime capability sessions."""

    def __init__(self, secret, root=None):
        if root is None:
            root = os.environ.get('TOONTOWN_AUTHORITY_HEAD_DIR')
        if not root:
            if os.environ.get('TOONTOWN_PRODUCTION') == '1':
                root = '/srv/toontown-browser/app/data/authority-heads'
            else:
                root = os.path.abspath(
                    os.path.join('.build-wasm', 'state', 'authority-heads'))
        self.secret = secret
        self.root = os.path.abspath(root)
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def observe(self, state):
        sessionId = state.get('sid', '')
        if (
                not isinstance(sessionId, str) or len(sessionId) != 32 or
                any(character not in '0123456789abcdef'
                    for character in sessionId)):
            raise ValueError('invalid authority session id')
        current = self.read(sessionId)
        if current is not None:
            if int(state['sq']) < int(current['sq']):
                return False
            if int(state['sq']) == int(current['sq']):
                return self._sameHead(current, state)
        payload = {
            'version': 1,
            'sid': sessionId,
            'pk': state['pk'],
            'release': state['r'],
            'contentEpoch': state['ce'],
            'marker': state['m'],
            'sq': int(state['sq']),
            'state': state['st'],
            'updatedAt': int(time.time()),
        }
        payload['signature'] = hmac.new(
            self.secret, _canonical(payload), hashlib.sha256).hexdigest()
        self._write(sessionId, payload)
        return True

    def read(self, sessionId):
        path = os.path.join(self.root, '%s.json' % sessionId)
        if not os.path.exists(path):
            return None
        with open(path, 'rb') as stream:
            payload = json.loads(stream.read().decode('utf8'))
        signature = payload.pop('signature', None)
        expected = hmac.new(
            self.secret, _canonical(payload), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature or '', expected):
            raise ValueError('authority head signature mismatch')
        payload['signature'] = signature
        return payload

    @staticmethod
    def _sameHead(current, state):
        return (
            current.get('sid') == state.get('sid') and
            current.get('pk') == state.get('pk') and
            current.get('release') == state.get('r') and
            current.get('contentEpoch') == state.get('ce') and
            current.get('marker') == state.get('m') and
            current.get('state') == state.get('st'))

    def _write(self, sessionId, payload):
        BrowserProgressionLedgerStore._writeAtomic(
            os.path.join(self.root, '%s.json' % sessionId),
            _canonical(payload) + b'\n')
