from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from toontown.fishing import FishBingoSchedule

class NewsManagerAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('NewsManagerAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.holidayIdList = []

    def getWeeklyCalendarHolidays(self):
        return FishBingoSchedule.weeklyCalendarHolidays()

    def getYearlyCalendarHolidays(self):
        return []

    def getOncelyCalendarHolidays(self):
        return []

    def getRelativelyCalendarHolidays(self):
        return []

    def getMultipleStartHolidays(self):
        return []

    def setHolidayIdList(self, holidayIdList):
        self.holidayIdList = list(holidayIdList)

    def getHolidayIdList(self):
        return self.holidayIdList

    def d_setHolidayIdList(self, holidayIdList):
        self.sendUpdate('setHolidayIdList', [list(holidayIdList)])

    def b_setHolidayIdList(self, holidayIdList):
        self.setHolidayIdList(holidayIdList)
        self.d_setHolidayIdList(holidayIdList)

    def bingoStart(self):
        self.sendUpdate('setBingoStart', [])

    def bingoEnd(self):
        self.sendUpdate('setBingoEnd', [])

    def bingoWin(self, zoneId):
        self.sendUpdate('setBingoWin', [zoneId])

    def holidayNotify(self):
        self.sendUpdate('holidayNotify', [])
