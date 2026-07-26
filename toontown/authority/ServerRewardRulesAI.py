import time
import math


def boundedMinigameReward(
        normalExit, avatarPresent, avatarState, exitedState,
        startedAt, endedAt=None, now=None):
    """Return a bounded reward based only on server-observed participation."""
    if not normalExit or not avatarPresent or avatarState != exitedState:
        return 0
    if startedAt is None:
        return 0
    if endedAt is None:
        endedAt = time.monotonic() if now is None else now
    if endedAt < startedAt:
        return 0
    elapsed = min(180.0, max(0.0, endedAt - startedAt))
    if elapsed < 10.0:
        return 0
    return min(40, max(1, 1 + int(elapsed / 3.0)))


def fixedBossDamage(claimed, expected=1):
    """Accept only the event code; keep the damage amount server-owned."""
    try:
        if not math.isfinite(float(claimed)) or int(claimed) != claimed:
            return None
        return int(expected) if int(claimed) == int(expected) else None
    except (TypeError, ValueError, OverflowError):
        return None


def cashbotSafeDamage():
    return 25


def cashbotGoonDamage(scale, knockoutDamage):
    try:
        scale = float(scale)
        knockoutDamage = int(knockoutDamage)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(scale) or scale <= 0.0 or knockoutDamage < 1:
        return 0
    return min(knockoutDamage, max(int(25 * scale), 2))


def lawbotDefensePanDamage(weight, bonus, multiplier):
    try:
        damage = max(1, int(weight))
        if bonus:
            damage *= max(1, int(multiplier))
    except (TypeError, ValueError, OverflowError):
        return 1
    return damage
