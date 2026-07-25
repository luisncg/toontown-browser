"""Versioned JSON codec for recoverable cross-object estate operations."""

import base64
import json


def _encode(value):
    if isinstance(value, bytes):
        return {'$bytes': base64.b64encode(value).decode('ascii')}
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError('unsupported journal value: %r' % (type(value),))


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {'$bytes'}:
            return base64.b64decode(value['$bytes'].encode('ascii'))
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def encodeJournal(payload):
    document = {'version': 1, 'payload': _encode(payload)}
    return json.dumps(
        document, sort_keys=True, separators=(',', ':')).encode('utf-8')


def decodeJournal(blob):
    if not blob:
        return None
    document = json.loads(bytes(blob).decode('utf-8'))
    if document.get('version') != 1:
        raise ValueError('unsupported estate transaction journal version')
    payload = _decode(document.get('payload'))
    if not isinstance(payload, dict):
        raise ValueError('estate transaction journal payload is not a dict')
    return payload
