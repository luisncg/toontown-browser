"""Shared constants and deterministic math for reactive battle gags.

Reactive gags intentionally do not extend ToontownBattleGlobals.Tracks.  The
classic inventory, experience, gag-shop and battle tables are all fixed at
seven tracks, while battle command IDs 96-100 already describe SOS/fire
actions.  These reserved IDs use a small separate persistent inventory and
travel through the existing one-action-per-Toon movie record without being
mistaken for ordinary inventory indexes.
"""

DECOY_TRACK = 101
EMBARRASS_TRACK = 102
REACTIVE_TRACKS = (DECOY_TRACK, EMBARRASS_TRACK)

FAKE_MOUSTACHE_LEVEL = 0
WHOOPEE_CUSHION_LEVEL = 0
FIRST_REACTIVE_LEVEL = 0
LAST_IMPLEMENTED_REACTIVE_LEVEL = 0
NUM_REACTIVE_LEVELS = 7
MAX_REACTIVE_GAG_COUNT = 10

REACTIVE_RESULT_PENDING = 0
REACTIVE_RESULT_SUCCESS = 1
REACTIVE_RESULT_FAILURE = 2
REACTIVE_RESULT_NOT_TRIGGERED = 3

# First-pass balance values are deliberately centralized for live tuning.
FAKE_MOUSTACHE_SUCCESS_CHANCE = 50
WHOOPEE_CUSHION_SUCCESS_CHANCE = 60
WHOOPEE_CUSHION_GROUP_SUCCESS_CHANCE = 70
WHOOPEE_CUSHION_DAMAGE_REDUCTION = 25
WHOOPEE_CUSHION_FLUSTER_TURNS = 2

REACTIVE_TRACK_NAMES = {
    DECOY_TRACK: 'Decoy',
    EMBARRASS_TRACK: 'Embarrass',
}

REACTIVE_GAG_NAMES = {
    (DECOY_TRACK, FAKE_MOUSTACHE_LEVEL): 'Fake Moustache',
    (EMBARRASS_TRACK, WHOOPEE_CUSHION_LEVEL): 'Whoopee Cushion',
}

REACTIVE_TRACK_INDEX = {
    DECOY_TRACK: 0,
    EMBARRASS_TRACK: 1,
}


def isReactiveTrack(track):
    return track in REACTIVE_TRACKS


def isImplementedReactiveGag(track, level):
    return isReactiveTrack(track) and level == FIRST_REACTIVE_LEVEL


def getReactiveTrackIndex(track):
    return REACTIVE_TRACK_INDEX.get(track, -1)


def clampReactiveGagCount(count):
    return max(0, min(MAX_REACTIVE_GAG_COUNT, int(count)))


def getReactiveTrackName(track):
    return REACTIVE_TRACK_NAMES.get(track, 'Reactive')


def getReactiveGagName(track, level):
    return REACTIVE_GAG_NAMES.get((track, level), 'Coming Soon')


def reducedDamage(damage, reduction=WHOOPEE_CUSHION_DAMAGE_REDUCTION):
    """Return level-one Embarrass damage without converting a hit to a miss."""
    damage = int(damage)
    if damage <= 0:
        return damage
    if damage == 1:
        return 1
    prevented = max(1, int(round(damage * (float(reduction) / 100.0))))
    return max(1, damage - prevented)


def getWhoopeeCushionSuccessChance(cushionCount):
    """Return the one shared roll used by a same-Cog cushion group."""
    if int(cushionCount) <= 1:
        return WHOOPEE_CUSHION_SUCCESS_CHANCE
    return WHOOPEE_CUSHION_GROUP_SUCCESS_CHANCE


def rollSucceeds(chance, randrange):
    """Roll through an injected randrange callable for deterministic tests."""
    return randrange(100) < chance
