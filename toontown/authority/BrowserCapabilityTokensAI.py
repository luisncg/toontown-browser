import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time


GAME_AUTHORITY_PROTOCOL = 1
GAME_CONTENT_EPOCH = 'gameplay-v1'
GAME_STATE_TTL_SECONDS = 6 * 60 * 60
GAME_TRANSITION_TTL_SECONDS = 45

_STATE_PREFIX = 'gs1'
_TRANSITION_PREFIX = 'gt1'
_HEX_32 = re.compile(r'^[a-f0-9]{32}$')
_HEX_64 = re.compile(r'^[a-f0-9]{64}$')
_MARKER = re.compile(r'^[A-Za-z0-9_-]{22}$')
_PART = re.compile(r'^[A-Za-z0-9_-]+$')
_ACTIONS = frozenset((
    'battle.attack',
    'building.board',
    'door.enter',
    'estate.enter',
    'fishing.cast',
    'fishing.enter',
    'fish-bingo.claim',
    'mega.join',
    'mega.vote',
    'npc.interact',
    'catalog.purchase',
    'boss.reward',
    'minigame.finish',
    'race.finish',
    'trolley.board',
))


def _base64url_encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _base64url_decode(value):
    if not isinstance(value, str) or not _PART.match(value):
        raise ValueError('invalid base64url')
    padding = '=' * ((4 - len(value) % 4) % 4)
    decoded = base64.urlsafe_b64decode((value + padding).encode('ascii'))
    if _base64url_encode(decoded) != value:
        raise ValueError('non-canonical base64url')
    return decoded


def authority_secret(environment=None):
    environment = environment if environment is not None else os.environ
    value = environment.get('RUNTIME_AUTHORITY_SECRET', '')
    if value:
        secret = _base64url_decode(value)
        if len(secret) != 32:
            raise ValueError('RUNTIME_AUTHORITY_SECRET must contain 32 bytes')
        return secret
    if environment.get('TOONTOWN_PRODUCTION') == '1':
        raise ValueError('RUNTIME_AUTHORITY_SECRET is required in production')
    return hashlib.sha256(
        b'toontown-browser-local-game-authority-v1').digest()


def _signing_key(secret):
    return hmac.new(
        secret,
        b'toontown-browser-game-authority-signing-key-v1',
        hashlib.sha256).digest()


def _seal(prefix, payload, secret):
    encoded = _base64url_encode(json.dumps(
        payload, separators=(',', ':'), ensure_ascii=True).encode('utf8'))
    signed = '%s.%s' % (prefix, encoded)
    signature = _base64url_encode(hmac.new(
        _signing_key(secret), signed.encode('utf8'), hashlib.sha256).digest())
    return '%s.%s' % (signed, signature)


def _open(prefix, token, secret):
    if not isinstance(token, str) or len(token) < 80 or len(token) > 4096:
        return None
    parts = token.split('.')
    if len(parts) != 3 or parts[0] != prefix:
        return None
    try:
        supplied = _base64url_decode(parts[2])
        payload_bytes = _base64url_decode(parts[1])
    except Exception:
        return None
    expected = hmac.new(
        _signing_key(secret),
        ('%s.%s' % (parts[0], parts[1])).encode('utf8'),
        hashlib.sha256).digest()
    if len(supplied) != 32 or not hmac.compare_digest(supplied, expected):
        return None
    try:
        payload = json.loads(payload_bytes.decode('utf8'))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _valid_lifetime(payload, maximum_seconds, now=None):
    current = int(time.time() if now is None else now)
    issued = payload.get('iat')
    expires = payload.get('exp')
    return (
        isinstance(issued, int) and not isinstance(issued, bool) and
        isinstance(expires, int) and not isinstance(expires, bool) and
        issued <= current + 60 and
        expires >= current - 60 and
        expires > issued and
        expires - issued <= maximum_seconds)


def _integer(value, minimum, maximum):
    if (
            not isinstance(value, int) or isinstance(value, bool) or
            value < minimum or value > maximum):
        raise ValueError('invalid transition integer')
    return value


def normalize_target(action, target):
    if action not in _ACTIONS or not isinstance(target, dict):
        raise ValueError('invalid transition target')
    if action == 'battle.attack':
        return {
            'battle': _integer(target.get('battle'), 1, 0xffffffff),
            'track': _integer(target.get('track'), -128, 127),
            'level': _integer(target.get('level'), -128, 127),
            'target': _integer(
                target.get('target'), -0x80000000, 0x7fffffff),
        }
    if action == 'fish-bingo.claim':
        return {
            'manager': _integer(target.get('manager'), 1, 0xffffffff),
            'card': _integer(target.get('card'), 0, 0xffff),
        }
    if action == 'estate.enter':
        return {
            'manager': _integer(target.get('manager'), 1, 0xffffffff),
            'owner': _integer(target.get('owner'), 1, 0xffffffff),
        }
    if action in ('fishing.cast', 'fishing.enter'):
        return {
            'spot': _integer(target.get('spot'), 1, 0xffffffff),
            'zone': _integer(target.get('zone'), 1, 0xffffffff),
        }
    if action == 'trolley.board':
        return {
            'trolley': _integer(target.get('trolley'), 1, 0xffffffff),
            'zone': _integer(target.get('zone'), 1, 0xffffffff),
        }
    if action == 'door.enter':
        return {
            'door': _integer(target.get('door'), 1, 0xffffffff),
            'zone': _integer(target.get('zone'), 1, 0xffffffff),
        }
    if action == 'building.board':
        return {
            'elevator': _integer(target.get('elevator'), 1, 0xffffffff),
            'zone': _integer(target.get('zone'), 1, 0xffffffff),
        }
    if action == 'npc.interact':
        return {
            'npc': _integer(target.get('npc'), 1, 0xffffffff),
            'zone': _integer(target.get('zone'), 1, 0xffffffff),
        }
    if action == 'catalog.purchase':
        return {
            'phone': _integer(target.get('phone'), 1, 0xffffffff),
            'context': _integer(target.get('context'), 0, 0xffffffff),
            'gift': _integer(target.get('gift'), 0, 1),
        }
    if action == 'boss.reward':
        return {
            'boss': _integer(target.get('boss'), 1, 0xffffffff),
            'reward': _integer(target.get('reward'), 0, 0xffffffff),
        }
    if action == 'minigame.finish':
        return {
            'game': _integer(target.get('game'), 1, 0xffffffff),
        }
    if action == 'race.finish':
        return {
            'race': _integer(target.get('race'), 1, 0xffffffff),
            'laps': _integer(target.get('laps'), 1, 0x7f),
        }
    return {
        'elevator': _integer(target.get('elevator'), 1, 0xffffffff),
        'accept': _integer(target.get('accept'), 0, 1),
    }


def verify_state(token, secret=None, release=None, now=None):
    secret = secret if secret is not None else authority_secret()
    payload = _open(_STATE_PREFIX, token, secret)
    if not payload:
        return None
    valid = (
        payload.get('v') == GAME_AUTHORITY_PROTOCOL and
        payload.get('t') == 'state' and
        bool(_HEX_64.match(payload.get('pk', ''))) and
        bool(_HEX_64.match(payload.get('r', ''))) and
        bool(_HEX_32.match(payload.get('sid', ''))) and
        bool(_HEX_32.match(payload.get('st', ''))) and
        bool(_MARKER.match(payload.get('m', ''))) and
        isinstance(payload.get('sq'), int) and
        not isinstance(payload.get('sq'), bool) and
        payload.get('sq') >= 0 and
        isinstance(payload.get('ce'), str) and
        len(payload.get('ce')) <= 64 and
        _valid_lifetime(payload, GAME_STATE_TTL_SECONDS, now) and
        (not release or payload.get('r') == release))
    return payload if valid else None


def verify_transition(token, action=None, target=None, secret=None,
                      release=None, now=None):
    secret = secret if secret is not None else authority_secret()
    payload = _open(_TRANSITION_PREFIX, token, secret)
    if not payload:
        return None
    expected_action = action if action is not None else payload.get('a')
    try:
        expected_target = normalize_target(
            expected_action, target if target is not None else payload.get('x'))
    except Exception:
        return None
    valid = (
        payload.get('v') == GAME_AUTHORITY_PROTOCOL and
        payload.get('t') == 'transition' and
        bool(_HEX_64.match(payload.get('pk', ''))) and
        bool(_HEX_64.match(payload.get('r', ''))) and
        bool(_HEX_32.match(payload.get('sid', ''))) and
        bool(_HEX_32.match(payload.get('ps', ''))) and
        bool(_HEX_32.match(payload.get('ns', ''))) and
        bool(_MARKER.match(payload.get('m', ''))) and
        bool(_MARKER.match(payload.get('n', ''))) and
        isinstance(payload.get('sq'), int) and
        not isinstance(payload.get('sq'), bool) and
        payload.get('sq') > 0 and
        payload.get('a') == expected_action and
        payload.get('x') == expected_target and
        _valid_lifetime(payload, GAME_TRANSITION_TTL_SECONDS, now) and
        (not release or payload.get('r') == release))
    return payload if valid else None


def advance_state(transition, secret=None, now=None):
    secret = secret if secret is not None else authority_secret()
    if (
            not isinstance(transition, dict) or
            transition.get('v') != GAME_AUTHORITY_PROTOCOL or
            transition.get('t') != 'transition'):
        raise ValueError('verified transition required')
    issued = int(time.time() if now is None else now)
    payload = {
        'v': GAME_AUTHORITY_PROTOCOL,
        't': 'state',
        'pk': transition['pk'],
        'r': transition['r'],
        'sid': transition['sid'],
        'st': transition['ns'],
        'sq': transition['sq'],
        'ce': transition['ce'],
        'm': transition['m'],
        'iat': issued,
        'exp': issued + GAME_STATE_TTL_SECONDS,
    }
    state_token = _seal(_STATE_PREFIX, payload, secret)
    receipt_id = hashlib.sha256('\n'.join((
        'toontown-browser-transition-receipt-v1',
        transition['sid'],
        transition['ps'],
        transition['ns'],
        transition['a'],
        str(transition['sq']),
    )).encode('utf8')).hexdigest()
    return {
        'version': GAME_AUTHORITY_PROTOCOL,
        'release': transition['r'],
        'contentEpoch': transition['ce'],
        'marker': transition['m'],
        'sequence': transition['sq'],
        'stateToken': state_token,
        'receipt': {
            'id': receipt_id,
            'action': transition['a'],
            'sequence': transition['sq'],
            'marker': transition['m'],
        },
        'expiresAt': payload['exp'] * 1000,
    }
