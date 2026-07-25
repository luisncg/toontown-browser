from direct.directnotify import DirectNotifyGlobal
from direct.distributed.ClockDelta import globalClockDelta
from direct.task.TaskManagerGlobal import taskMgr
from toontown.estate import BankGlobals
from toontown.estate.DistributedFurnitureItemAI import DistributedFurnitureItemAI
from toontown.estate.EstateTransactionAI import AstronObjectTransaction


class DistributedBankAI(DistributedFurnitureItemAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedBankAI')

    def __init__(self, air, furnitureManager=None, catalogItem=None):
        DistributedFurnitureItemAI.__init__(
            self, air, furnitureManager, catalogItem)
        self.busyAvatarId = 0
        self._transferInFlight = False

    def avatarEnter(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if self.busyAvatarId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if avId != self.furnitureManager.ownerId:
            self._setMovie(BankGlobals.BANK_MOVIE_NOT_OWNER, avId)
            return
        self.busyAvatarId = avId
        self._setMovie(BankGlobals.BANK_MOVIE_GUI, avId)

    def freeAvatar(self):
        avId = self.busyAvatarId
        self.busyAvatarId = 0
        if avId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
        self._setMovie(BankGlobals.BANK_MOVIE_CLEAR, 0)

    def transferMoney(self, amount):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.busyAvatarId or self._transferInFlight:
            self.furnitureManager.recordUnauthorized(
                avId, 'invalid bank transfer')
            return
        avatar = self.air.doId2do.get(avId)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.freeAvatar()
            return
        if amount == 0:
            self.busyAvatarId = 0
            self._setMovie(BankGlobals.BANK_MOVIE_NO_OP, avId)
            self._scheduleClear()
            return

        oldMoney = avatar.getMoney()
        oldBank = avatar.getBankMoney()
        newMoney = oldMoney - amount
        newBank = oldBank + amount
        if (newMoney < 0 or newMoney > avatar.getMaxMoney() or
                newBank < 0 or newBank > avatar.getMaxBankMoney()):
            self.furnitureManager.recordUnauthorized(
                avId, 'out-of-range bank transfer')
            self.busyAvatarId = 0
            self._setMovie(BankGlobals.BANK_MOVIE_NO_OP, avId)
            self._scheduleClear()
            return

        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._transferInFlight = True

        def committed(success, conflicts):
            self._transferInFlight = False
            self.busyAvatarId = 0
            if not success:
                if conflicts:
                    if 'setMoney' in conflicts:
                        avatar.setMoney(conflicts['setMoney'])
                        avatar.d_setMoney(conflicts['setMoney'])
                    if 'setBankMoney' in conflicts:
                        avatar.setBankMoney(conflicts['setBankMoney'])
                        avatar.d_setBankMoney(conflicts['setBankMoney'])
                self._setMovie(BankGlobals.BANK_MOVIE_NO_OP, avId)
                self._scheduleClear()
                return
            avatar.setMoney(newMoney)
            avatar.d_setMoney(newMoney)
            avatar.setBankMoney(newBank)
            avatar.d_setBankMoney(newBank)
            mode = (
                BankGlobals.BANK_MOVIE_DEPOSIT if amount > 0 else
                BankGlobals.BANK_MOVIE_WITHDRAW)
            self._setMovie(mode, avId)
            self._scheduleClear()

        transaction.commit(
            {'setMoney': oldMoney, 'setBankMoney': oldBank},
            {'setMoney': newMoney, 'setBankMoney': newBank},
            committed)

    def _setMovie(self, mode, avId):
        self.sendUpdate(
            'setMovie',
            [mode, avId, globalClockDelta.getRealNetworkTime(bits=16)])

    def _scheduleClear(self):
        taskMgr.remove(self.uniqueName('clear-bank-movie'))
        taskMgr.doMethodLater(
            3.0, self._clearMovie,
            self.uniqueName('clear-bank-movie'))

    def _clearMovie(self, task):
        self._setMovie(BankGlobals.BANK_MOVIE_CLEAR, 0)
        return task.done

    def delete(self):
        taskMgr.remove(self.uniqueName('clear-bank-movie'))
        DistributedFurnitureItemAI.delete(self)
