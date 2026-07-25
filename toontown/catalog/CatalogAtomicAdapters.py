"""Side-effect-free plans for catalog items stored on one Toon record."""

from toontown.catalog.CatalogBeanItem import CatalogBeanItem
from toontown.catalog.CatalogAccessoryItem import CatalogAccessoryItem
from toontown.catalog.CatalogAccessoryItem import AccessoryTypes, ATString
from toontown.catalog.CatalogChatItem import CatalogChatItem
from toontown.catalog.CatalogClothingItem import (
    CatalogClothingItem, ClothingTypes, CTString)
from toontown.catalog.CatalogEmoteItem import CatalogEmoteItem
from toontown.catalog.CatalogGardenItem import CatalogGardenItem
from toontown.catalog.CatalogGardenStarterItem import CatalogGardenStarterItem
from toontown.catalog.CatalogNametagItem import CatalogNametagItem
from toontown.catalog.CatalogPetTrickItem import CatalogPetTrickItem
from toontown.catalog.CatalogPoleItem import CatalogPoleItem
from toontown.estate import GardenGlobals
from toontown.fishing import FishGlobals
from toontown.toon import ToonDNA
from toontown.toonbase import ToontownGlobals


def planToonApplication(avatar, item, optional=-1):
    """Return ``(retcode, oldFields, newFields)`` without mutating avatar."""
    if isinstance(item, CatalogBeanItem):
        oldMoney = avatar.getMoney()
        oldBank = avatar.getBankMoney()
        total = oldMoney + int(item.beanAmount)
        newMoney = min(total, avatar.getMaxMoney())
        newBank = min(
            avatar.getMaxBankMoney(), oldBank + max(0, total - newMoney))
        return _ok(
            {'setMoney': oldMoney, 'setBankMoney': oldBank},
            {'setMoney': newMoney, 'setBankMoney': newBank})

    if isinstance(item, CatalogChatItem):
        oldMessages = list(avatar.getCustomMessages())
        if item.customIndex in oldMessages:
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        newMessages = list(oldMessages)
        if len(newMessages) >= ToontownGlobals.MaxCustomMessages:
            if optional < 0 or optional >= len(newMessages):
                return _error(ToontownGlobals.P_NoRoomForItem)
            del newMessages[optional]
        newMessages.append(item.customIndex)
        return _ok(
            {'setCustomMessages': oldMessages},
            {'setCustomMessages': newMessages})

    if isinstance(item, CatalogPetTrickItem):
        oldPhrases = list(avatar.getPetTrickPhrases())
        if item.trickId in oldPhrases:
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        return _ok(
            {'setPetTrickPhrases': oldPhrases},
            {'setPetTrickPhrases': oldPhrases + [item.trickId]})

    if isinstance(item, CatalogEmoteItem):
        oldAccess = list(avatar.emoteAccess)
        if item.emoteIndex < 0 or item.emoteIndex >= len(oldAccess):
            return _error(ToontownGlobals.P_InvalidIndex)
        if oldAccess[item.emoteIndex]:
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        newAccess = list(oldAccess)
        newAccess[item.emoteIndex] = 1
        return _ok(
            {'setEmoteAccess': oldAccess},
            {'setEmoteAccess': newAccess})

    if isinstance(item, CatalogNametagItem):
        if item.nametagStyle < 0 or item.nametagStyle > 255:
            return _error(ToontownGlobals.P_InvalidIndex)
        if avatar.getNametagStyle() == item.nametagStyle:
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        return _ok(
            {'setNametagStyle': avatar.getNametagStyle()},
            {'setNametagStyle': item.nametagStyle})

    if isinstance(item, CatalogGardenItem):
        if item.gardenIndex not in GardenGlobals.Specials:
            return _error(ToontownGlobals.P_InvalidIndex)
        oldSpecials = [list(value) for value in avatar.getGardenSpecials()]
        newSpecials = [list(value) for value in oldSpecials]
        for value in newSpecials:
            if value[0] == item.gardenIndex:
                value[1] = min(255, value[1] + item.numItems)
                break
        else:
            newSpecials.append([
                item.gardenIndex, min(255, int(item.numItems))])
        newSpecials.sort()
        return _ok(
            {'setGardenSpecials': oldSpecials},
            {'setGardenSpecials': newSpecials})

    if isinstance(item, CatalogGardenStarterItem):
        if avatar.getGardenStarted():
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        return _ok(
            {'setGardenStarted': int(avatar.getGardenStarted())},
            {'setGardenStarted': 1})

    if isinstance(item, CatalogPoleItem):
        if item.rodId < 0 or item.rodId > FishGlobals.MaxRodId:
            return _error(ToontownGlobals.P_InvalidIndex)
        if item.rodId <= avatar.getFishingRod():
            return _error(ToontownGlobals.P_ItemUnneeded)
        return _ok(
            {'setFishingRod': avatar.getFishingRod()},
            {'setFishingRod': item.rodId})

    if isinstance(item, CatalogClothingItem):
        return _planClothing(avatar, item)

    if isinstance(item, CatalogAccessoryItem):
        return _planAccessory(avatar, item)

    return None


def applyToonFields(avatar, fields):
    methods = {
        'setMoney': ('setMoney', 'd_setMoney'),
        'setBankMoney': ('setBankMoney', 'd_setBankMoney'),
        'setCustomMessages': ('setCustomMessages', 'd_setCustomMessages'),
        'setPetTrickPhrases': (
            'setPetTrickPhrases', 'd_setPetTrickPhrases'),
        'setEmoteAccess': ('setEmoteAccess', 'd_setEmoteAccess'),
        'setNametagStyle': ('setNametagStyle', 'd_setNametagStyle'),
        'setGardenSpecials': (
            'setGardenSpecials', 'd_setGardenSpecials'),
        'setGardenStarted': ('setGardenStarted', 'd_setGardenStarted'),
        'setFishingRod': ('setFishingRod', 'd_setFishingRod'),
        'setDNAString': ('setDNAString', 'd_setDNAString'),
        'setClothesTopsList': (
            'setClothesTopsList', 'd_setClothesTopsList'),
        'setClothesBottomsList': (
            'setClothesBottomsList', 'd_setClothesBottomsList'),
        'setHatList': ('setHatList', 'd_setHatList'),
        'setGlassesList': ('setGlassesList', 'd_setGlassesList'),
        'setBackpackList': ('setBackpackList', 'd_setBackpackList'),
        'setShoesList': ('setShoesList', 'd_setShoesList'),
        'setHat': ('setHat', 'd_setHat'),
        'setGlasses': ('setGlasses', 'd_setGlasses'),
        'setBackpack': ('setBackpack', 'd_setBackpack'),
        'setShoes': ('setShoes', 'd_setShoes'),
    }
    for fieldName, value in fields.items():
        setter, broadcaster = methods[fieldName]
        if fieldName in ('setHat', 'setGlasses', 'setBackpack', 'setShoes'):
            getattr(avatar, setter)(*value)
            getattr(avatar, broadcaster)(*value)
        else:
            getattr(avatar, setter)(value)
            getattr(avatar, broadcaster)(value)


def postApplyItem(avatar, item):
    if isinstance(item, CatalogClothingItem):
        avatar.d_catalogGenClothes()
    elif isinstance(item, CatalogAccessoryItem):
        avatar.d_catalogGenAccessories()


def _planClothing(avatar, item):
    oldTops = list(avatar.getClothesTopsList())
    oldBottoms = list(avatar.getClothesBottomsList())
    if len(oldTops) / 4 + len(oldBottoms) / 2 >= avatar.getMaxClothes():
        return _error(ToontownGlobals.P_NoRoomForItem)
    dna = ToonDNA.ToonDNA()
    dna.makeFromNetString(avatar.getDNAString())
    styleName = ClothingTypes[item.clothingType][CTString]
    oldFields = {'setDNAString': avatar.getDNAString()}
    newFields = {}
    if item.isShirt():
        current = [
            dna.topTex, dna.topTexColor,
            dna.sleeveTex, dna.sleeveTexColor]
        target = ToonDNA.ShirtStyles[styleName]
        selected = [
            target[0], target[2][item.colorIndex][0],
            target[1], target[2][item.colorIndex][1]]
        if current == selected or _containsFlat(oldTops, selected):
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        newTops = list(oldTops)
        if not _containsFlat(newTops, current):
            newTops.extend(current)
        oldFields['setClothesTopsList'] = oldTops
        newFields['setClothesTopsList'] = newTops
        (dna.topTex, dna.topTexColor,
         dna.sleeveTex, dna.sleeveTexColor) = selected
    else:
        current = [dna.botTex, dna.botTexColor]
        target = ToonDNA.BottomStyles[styleName]
        selected = [target[0], target[1][item.colorIndex]]
        if current == selected or _containsFlat(oldBottoms, selected):
            return _error(ToontownGlobals.P_ReachedPurchaseLimit)
        newBottoms = list(oldBottoms)
        if not _containsFlat(newBottoms, current):
            newBottoms.extend(current)
        oldFields['setClothesBottomsList'] = oldBottoms
        newFields['setClothesBottomsList'] = newBottoms
        dna.botTex, dna.botTexColor = selected
        if dna.getGender() == 'f':
            try:
                bottomPair = ToonDNA.GirlBottoms[dna.botTex]
            except (IndexError, TypeError):
                bottomPair = ToonDNA.GirlBottoms[0]
            if dna.torso[1] == 's' and bottomPair[1] == ToonDNA.SKIRT:
                dna.torso = dna.torso[0] + 'd'
            elif dna.torso[1] == 'd' and bottomPair[1] == ToonDNA.SHORTS:
                dna.torso = dna.torso[0] + 's'
    newFields['setDNAString'] = dna.makeNetString()
    return _ok(oldFields, newFields)


def _planAccessory(avatar, item):
    count = sum(len(values) for values in (
        avatar.getHatList(), avatar.getGlassesList(),
        avatar.getBackpackList(), avatar.getShoesList())) / 3
    if count >= avatar.getMaxAccessories():
        return _error(
            ToontownGlobals.P_NoTrunk if avatar.getMaxAccessories() == 0
            else ToontownGlobals.P_NoRoomForItem)
    styleName = AccessoryTypes[item.accessoryType][ATString]
    if item.isHat():
        which = ToonDNA.HAT
        definition = ToonDNA.HatStyles[styleName]
        listField, getList, wornField, getWorn = (
            'setHatList', avatar.getHatList, 'setHat', avatar.getHat)
    elif item.areGlasses():
        which = ToonDNA.GLASSES
        definition = ToonDNA.GlassesStyles[styleName]
        listField, getList, wornField, getWorn = (
            'setGlassesList', avatar.getGlassesList,
            'setGlasses', avatar.getGlasses)
    elif item.isBackpack():
        which = ToonDNA.BACKPACK
        definition = ToonDNA.BackpackStyles[styleName]
        listField, getList, wornField, getWorn = (
            'setBackpackList', avatar.getBackpackList,
            'setBackpack', avatar.getBackpack)
    else:
        which = ToonDNA.SHOES
        definition = ToonDNA.ShoesStyles[styleName]
        listField, getList, wornField, getWorn = (
            'setShoesList', avatar.getShoesList,
            'setShoes', avatar.getShoes)
    selected = list(definition[:3])
    current = list(getWorn())
    oldList = list(getList())
    if current == selected or _containsFlat(oldList, selected):
        return _error(ToontownGlobals.P_ReachedPurchaseLimit)
    if not avatar.checkAccessorySanity(which, *selected):
        return _error(ToontownGlobals.P_InvalidIndex)
    newList = list(oldList)
    if not _containsFlat(newList, current):
        newList.extend(current)
    return _ok(
        {listField: oldList, wornField: current},
        {listField: newList, wornField: selected})


def _containsFlat(values, target):
    width = len(target)
    return any(values[index:index + width] == target
               for index in range(0, len(values), width))


def _ok(oldFields, newFields):
    return ToontownGlobals.P_ItemAvailable, oldFields, newFields


def _error(retcode):
    return retcode, {}, {}
