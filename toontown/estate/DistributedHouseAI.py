from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from toontown.estate import HouseGlobals


class DistributedHouseAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedHouseAI')

    def __init__(self, air, housePos=0, avatarId=0, name=''):
        DistributedObjectAI.__init__(self, air)
        self.housePos = housePos
        self.houseType = HouseGlobals.HOUSE_DEFAULT
        self.gardenPos = housePos
        self.avatarId = avatarId
        self.name = name
        self.color = housePos % len(HouseGlobals.houseColors)
        self.atticItems = b''
        self.interiorItems = b''
        self.atticWallpaper = b''
        self.interiorWallpaper = b''
        self.atticWindows = b''
        self.interiorWindows = b''
        self.deletedItems = b''
        self.cannonEnabled = 0

    def setHousePos(self, housePos):
        self.housePos = housePos

    def getHousePos(self):
        return self.housePos

    def setHouseType(self, houseType):
        self.houseType = houseType

    def getHouseType(self):
        return self.houseType

    def setGardenPos(self, gardenPos):
        self.gardenPos = gardenPos

    def getGardenPos(self):
        return self.gardenPos

    def setAvatarId(self, avatarId):
        self.avatarId = avatarId

    def getAvatarId(self):
        return self.avatarId

    def setName(self, name):
        self.name = name

    def getName(self):
        return self.name

    def setColor(self, color):
        self.color = color

    def getColor(self):
        return self.color

    def setAtticItems(self, items):
        self.atticItems = items

    def getAtticItems(self):
        return self.atticItems

    def setInteriorItems(self, items):
        self.interiorItems = items

    def getInteriorItems(self):
        return self.interiorItems

    def setAtticWallpaper(self, wallpaper):
        self.atticWallpaper = wallpaper

    def getAtticWallpaper(self):
        return self.atticWallpaper

    def setInteriorWallpaper(self, wallpaper):
        self.interiorWallpaper = wallpaper

    def getInteriorWallpaper(self):
        return self.interiorWallpaper

    def setAtticWindows(self, windows):
        self.atticWindows = windows

    def getAtticWindows(self):
        return self.atticWindows

    def setInteriorWindows(self, windows):
        self.interiorWindows = windows

    def getInteriorWindows(self):
        return self.interiorWindows

    def setDeletedItems(self, items):
        self.deletedItems = items

    def getDeletedItems(self):
        return self.deletedItems

    def setCannonEnabled(self, enabled):
        self.cannonEnabled = enabled

    def getCannonEnabled(self):
        return self.cannonEnabled

    # The furniture service writes the seven house-content fields in one
    # Astron compare-and-swap.  These helpers update the activated AI object
    # after that commit; using individual b_set calls here would destroy the
    # all-or-nothing guarantee.
    def applyContentFields(self, fields):
        setters = {
            'setAtticItems': self.setAtticItems,
            'setInteriorItems': self.setInteriorItems,
            'setAtticWallpaper': self.setAtticWallpaper,
            'setInteriorWallpaper': self.setInteriorWallpaper,
            'setAtticWindows': self.setAtticWindows,
            'setInteriorWindows': self.setInteriorWindows,
            'setDeletedItems': self.setDeletedItems,
        }
        for fieldName, setter in setters.items():
            if fieldName in fields:
                setter(fields[fieldName])

    def getContentFields(self):
        return {
            'setAtticItems': self.getAtticItems(),
            'setInteriorItems': self.getInteriorItems(),
            'setAtticWallpaper': self.getAtticWallpaper(),
            'setInteriorWallpaper': self.getInteriorWallpaper(),
            'setAtticWindows': self.getAtticWindows(),
            'setInteriorWindows': self.getInteriorWindows(),
            'setDeletedItems': self.getDeletedItems(),
        }
