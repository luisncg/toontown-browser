import time

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from toontown.catalog.CatalogGenerator import CatalogGenerator
from toontown.estate.EstateTransactionAI import AstronObjectTransaction
from toontown.toonbase import ToontownGlobals


class CatalogManagerAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('CatalogManagerAI')

    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.catalogGenerator = CatalogGenerator()
        self._generating = set()

    def startCatalog(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if avatar is None or avId in self._generating:
            return
        if getattr(avatar, 'catalogScheduleNextTime', 0):
            return
        self.deliverCatalogFor(avatar)

    def deliverCatalogFor(self, avatar):
        avId = avatar.doId
        if avId in self._generating:
            return
        self._generating.add(avId)
        try:
            nowMinutes = time.time() / 60.0
            monthlyCatalog = self.catalogGenerator.generateMonthlyCatalog(
                avatar, nowMinutes)
            newWeek = (
                (avatar.catalogScheduleCurrentWeek + 1) %
                ToontownGlobals.CatalogNumWeeks)
            weeklyCatalog = self.catalogGenerator.generateWeeklyCatalog(
                avatar, newWeek, monthlyCatalog)
            backCatalog = self.catalogGenerator.generateBackCatalog(
                avatar, newWeek, avatar.catalogScheduleCurrentWeek,
                monthlyCatalog)
            nextTime = int((time.time() + 7 * 24 * 60 * 60) / 60)
        except Exception as error:
            self._generating.discard(avId)
            self.notify.warning(
                'Could not generate catalog for avatar %s: %s' %
                (avId, error))
            return

        oldFields = {
            'setCatalog': avatar.getCatalog(),
            'setCatalogSchedule': avatar.getCatalogSchedule(),
            'setCatalogNotify': avatar.getCatalogNotify(),
        }
        newFields = {
            'setCatalog': (
                monthlyCatalog.getBlob(), weeklyCatalog.getBlob(),
                backCatalog.getBlob()),
            'setCatalogSchedule': (newWeek, nextTime),
            'setCatalogNotify': (
                ToontownGlobals.NewItems, avatar.mailboxNotify),
        }
        transaction = AstronObjectTransaction(
            self.air, avId,
            self.air.dclassesByName['DistributedToonAI'])

        def committed(success, conflicts):
            self._generating.discard(avId)
            if not success:
                self.notify.warning(
                    'Catalog generation CAS conflicted for avatar %s' % avId)
                return
            avatar.setCatalog(
                monthlyCatalog, weeklyCatalog, backCatalog)
            avatar.d_setCatalog(
                monthlyCatalog, weeklyCatalog, backCatalog)
            avatar.setCatalogSchedule(newWeek, nextTime)
            avatar.d_setCatalogSchedule(newWeek, nextTime)
            avatar.setCatalogNotify(
                ToontownGlobals.NewItems, avatar.mailboxNotify)
            avatar.d_setCatalogNotify(
                ToontownGlobals.NewItems, avatar.mailboxNotify)
            self.notify.info(
                'Delivered catalog week %s to avatar %s' %
                (newWeek, avId))

        transaction.commit(oldFields, newFields, committed)
