"""Pure helpers for the estate ``lawnItem`` persistence format."""


ITEM_WIDTH = 5


def normalizeItem(item):
    if len(item) != ITEM_WIDTH:
        raise ValueError('garden item must have five fields')
    typeIndex, hardPoint, waterLevel, growthLevel, optional = (
        int(value) for value in item)
    if not 0 <= typeIndex <= 255:
        raise ValueError('garden type is outside uint8')
    if not 0 <= hardPoint <= 255:
        raise ValueError('garden hardpoint is outside uint8')
    if not -128 <= waterLevel <= 127:
        raise ValueError('garden water level is outside int8')
    if not -128 <= growthLevel <= 127:
        raise ValueError('garden growth level is outside int8')
    if not 0 <= optional <= 65535:
        raise ValueError('garden optional value is outside uint16')
    return [typeIndex, hardPoint, waterLevel, growthLevel, optional]


def normalizeItems(items):
    normalized = []
    seen = set()
    for item in items:
        value = normalizeItem(item)
        if value[1] in seen:
            raise ValueError('duplicate garden hardpoint %s' % value[1])
        seen.add(value[1])
        normalized.append(value)
    normalized.sort(key=lambda value: value[1])
    return normalized


def getItem(items, hardPoint):
    for item in items:
        if int(item[1]) == int(hardPoint):
            return normalizeItem(item)
    return None


def withItem(items, item):
    item = normalizeItem(item)
    result = [normalizeItem(value) for value in items
              if int(value[1]) != item[1]]
    result.append(item)
    return normalizeItems(result)


def withoutItem(items, hardPoint):
    return normalizeItems(
        [value for value in items if int(value[1]) != int(hardPoint)])


def plantType(typeIndex, plantAttributes=None):
    if plantAttributes is None:
        from toontown.estate import GardenGlobals
        plantAttributes = GardenGlobals.PlantAttributes
    attributes = plantAttributes.get(int(typeIndex))
    return attributes.get('plantType') if attributes else None


def advanceDays(items, days, plantAttributes=None):
    """Apply deterministic daily water and growth progression."""
    days = max(0, int(days))
    if not days:
        return normalizeItems(items)
    if plantAttributes is None:
        from toontown.estate import GardenGlobals
        plantAttributes = GardenGlobals.PlantAttributes
    result = []
    for item in normalizeItems(items):
        typeIndex, hardPoint, waterLevel, growthLevel, optional = item
        attributes = plantAttributes.get(typeIndex)
        if not attributes:
            result.append(item)
            continue
        kind = attributes.get('plantType')
        if kind in (0, 1):
            for _day in range(days):
                if waterLevel >= 0:
                    growthLevel += 1
                waterLevel -= 1
            waterLevel = max(
                int(attributes.get('minWaterLevel', -2)), waterLevel)
            thresholds = attributes.get('growthThresholds', (0, 0, 0))
            if thresholds:
                growthLevel = min(int(thresholds[-1]), growthLevel)
        result.append([
            typeIndex, hardPoint, waterLevel, growthLevel, optional])
    return normalizeItems(result)


def epochDay(timestamp):
    return (int(timestamp) // 86400) & 0xffff


def elapsedEpochDays(thenDay, nowDay):
    """Compare uint16 epoch-day counters across their wrap boundary."""
    return (int(nowDay) - int(thenDay)) & 0xffff
