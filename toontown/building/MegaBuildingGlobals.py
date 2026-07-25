"""Shared, dependency-light rules for Cog Mega-Buildings."""

import random


MEGA_MIN_FLOORS = 6
MEGA_MAX_FLOORS = 10
MEGA_MIN_TOONS = 4
MEGA_MAX_TOONS = 8

MEGA_VOTE_SECONDS = 15.0
MEGA_RECRUIT_SECONDS = 15.0
REGULAR_FALLBACK_SECONDS = 10.0

MEGA_STATE_CLASSIC = 0
MEGA_STATE_VOTING = 1
MEGA_STATE_RECRUITING = 2
MEGA_STATE_REGULAR_FALLBACK = 3
MEGA_STATE_DEPARTING = 4


def clampRegularFloors(numFloors):
    return max(1, min(5, int(numFloors)))


def clampMegaFloors(regularFloors, megaFloors):
    regularFloors = clampRegularFloors(regularFloors)
    minimum = max(MEGA_MIN_FLOORS, regularFloors + 1)
    return max(minimum, min(MEGA_MAX_FLOORS, int(megaFloors)))


def chooseMegaFloors(regularFloors, rng=None):
    """Choose the advertised all-Mega floor total for a street building."""
    regularFloors = clampRegularFloors(regularFloors)
    minimum = max(MEGA_MIN_FLOORS, regularFloors + 1)
    if rng is None:
        rng = random
    return rng.randint(minimum, MEGA_MAX_FLOORS)


def getYellowFloorCount(regularFloors, megaFloors):
    regularFloors = clampRegularFloors(regularFloors)
    megaFloors = clampMegaFloors(regularFloors, megaFloors)
    return megaFloors - regularFloors


def splitMegaToons(toonIds):
    """Keep original voters together and place recruits on the second front."""
    seats = list(toonIds[:MEGA_MAX_TOONS])
    if len(seats) < MEGA_MAX_TOONS:
        seats.extend([None] * (MEGA_MAX_TOONS - len(seats)))
    return ([toonId for toonId in seats[:4] if toonId],
            [toonId for toonId in seats[4:] if toonId])
