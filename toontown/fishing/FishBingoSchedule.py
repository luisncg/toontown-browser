"""Historical Fish Bingo windows expressed in Toontown (Pacific) time."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from toontown.toonbase import ToontownGlobals


TOONTOWN_TIME = ZoneInfo('America/Los_Angeles')


def toontownTime(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=TOONTOWN_TIME)
    return now.astimezone(TOONTOWN_TIME)


def activeHoliday(now=None, forceActive=False):
    """Return the active Bingo holiday ID, or ``None`` outside its window.

    Disney's final server calendar ran Bingo throughout Wednesday.  Silly
    Saturday rotated two-hour blocks of Bingo, Grand Prix and the Trolley
    holiday, beginning with Bingo at midnight.
    """
    local = toontownTime(now)
    if forceActive:
        return ToontownGlobals.FISH_BINGO_NIGHT
    if local.weekday() == 2:
        return ToontownGlobals.FISH_BINGO_NIGHT
    if local.weekday() == 5 and local.hour % 6 < 2:
        return ToontownGlobals.SILLY_SATURDAY_BINGO
    return None


def hourKey(now=None):
    local = toontownTime(now)
    return local.strftime('%Y-%m-%dT%H')


def isHourlyIntermission(now=None):
    return toontownTime(now).minute >= 55


def isBlockoutWindow(now=None):
    """The Super Blockout is the first round at the top of each hour."""
    return toontownTime(now).minute < 5


def secondsUntilNextHour(now=None):
    local = toontownTime(now)
    return max(0.1, 3600.0 - (local.minute * 60.0 + local.second +
                             local.microsecond / 1000000.0))


def weeklyCalendarHolidays():
    # Python's weekday convention is Monday=0, Wednesday=2, Saturday=5.
    return [
        (ToontownGlobals.FISH_BINGO_NIGHT, 2),
        (ToontownGlobals.SILLY_SATURDAY_BINGO, 5),
    ]
