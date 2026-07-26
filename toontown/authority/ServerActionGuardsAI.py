import math
import time

from toontown.hood import ZoneUtil


DEFAULT_INTERACTION_DISTANCE = 35.0


def _guardState(air):
    state = getattr(air, '_serverActionGuardState', None)
    if state is None:
        state = {
            'buckets': {},
            'lastCleanup': time.monotonic(),
        }
        air._serverActionGuardState = state
    return state


def allowAction(air, avId, action, rate=2.0, burst=4.0, cost=1.0):
    """Server-time token bucket for semantic gameplay actions."""
    if not avId or rate <= 0.0 or burst < cost:
        return False
    now = time.monotonic()
    state = _guardState(air)
    key = (int(avId), str(action))
    previous = state['buckets'].get(key)
    if previous is None:
        tokens = float(burst)
        updatedAt = now
    else:
        tokens, updatedAt = previous
        tokens = min(float(burst), tokens + (now - updatedAt) * float(rate))
    if tokens + 1e-9 < cost:
        state['buckets'][key] = (tokens, now)
        recordSuspicious(air, avId, '%s exceeded action cadence' % action)
        return False
    state['buckets'][key] = (tokens - cost, now)
    if now - state['lastCleanup'] > 300.0:
        state['buckets'] = {
            bucketKey: bucket for bucketKey, bucket in state['buckets'].items()
            if now - bucket[1] < 900.0}
        state['lastCleanup'] = now
    return True


def avatarFromSender(air):
    avId = air.getAvatarIdFromSender()
    return avId, air.doId2do.get(avId)


def sameLocation(avatar, target):
    return (
        avatar is not None and target is not None and
        int(getattr(avatar, 'parentId', 0) or 0) ==
        int(getattr(target, 'parentId', 0) or 0) and
        int(getattr(avatar, 'zoneId', 0) or 0) ==
        int(getattr(target, 'zoneId', 0) or 0))


def _position(value):
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        result = value[:3]
    elif hasattr(value, 'getPos'):
        result = value.getPos()
    elif hasattr(value, 'getPosHpr'):
        result = value.getPosHpr()[:3]
    elif hasattr(value, 'posHpr'):
        result = value.posHpr[:3]
    else:
        return None
    try:
        point = tuple(float(component) for component in result)
    except (TypeError, ValueError):
        return None
    if len(point) != 3 or not all(math.isfinite(item) for item in point):
        return None
    return point


def withinDistance(avatar, target, maximum=DEFAULT_INTERACTION_DISTANCE):
    avatarPos = _position(avatar)
    targetPos = _position(target)
    if avatarPos is None or targetPos is None:
        return False
    dx = avatarPos[0] - targetPos[0]
    dy = avatarPos[1] - targetPos[1]
    dz = avatarPos[2] - targetPos[2]
    return dx * dx + dy * dy + dz * dz <= float(maximum) ** 2


def doorPosition(air, door):
    zoneId = int(getattr(door, 'zoneId', 0) or 0)
    block = int(getattr(door, 'block', 0) or 0)
    if not zoneId or not block:
        return None
    canonical = ZoneUtil.getCanonicalZoneId(zoneId)
    store = getattr(air, 'dnaStoreMap', {}).get(canonical)
    if store is None:
        store = getattr(air, 'dnaStoreMap', {}).get(
            ZoneUtil.getCanonicalHoodId(zoneId))
    if store is None:
        return None
    try:
        transform = store.getDoorPosHprFromBlockNumber(block)
        return _position(transform.getPos())
    except Exception:
        return None


def requireInteraction(
        air, avId, avatar, target=None, targetPosition=None,
        maximum=DEFAULT_INTERACTION_DISTANCE, action='interaction',
        requirePosition=True):
    if avatar is None:
        recordSuspicious(air, avId, '%s missing avatar' % action)
        return False
    if target is not None and not sameLocation(avatar, target):
        recordSuspicious(air, avId, '%s crossed location boundary' % action)
        return False
    position = targetPosition if targetPosition is not None else target
    if _position(position) is None:
        if requirePosition:
            recordSuspicious(
                air, avId, '%s lacked authoritative target position' % action)
            return False
        return True
    if not withinDistance(avatar, position, maximum):
        recordSuspicious(air, avId, '%s was attempted remotely' % action)
        return False
    return allowAction(air, avId, action, rate=2.0, burst=3.0)


def recordSuspicious(air, avId, message):
    air.writeServerEvent('suspicious', int(avId or 0), str(message))
