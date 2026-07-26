import math
import time

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.ClockDelta import globalClockDelta
from direct.task.TaskManagerGlobal import taskMgr
from toontown.catalog import CatalogItem
from toontown.catalog.CatalogInvalidItem import CatalogInvalidItem
from toontown.catalog.CatalogItemList import CatalogItemList
from toontown.catalog.CatalogAtomicAdapters import (
    applyToonFields, planToonApplication, postApplyItem)
from toontown.estate import PhoneGlobals
from toontown.estate.DistributedFurnitureItemAI import DistributedFurnitureItemAI
from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, ResponseReplayCache, chargeBalances)
from toontown.toonbase import ToontownGlobals


class DistributedPhoneAI(DistributedFurnitureItemAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedPhoneAI')

    MAX_ON_ORDER = 6

    def __init__(self, air, furnitureManager=None, catalogItem=None):
        DistributedFurnitureItemAI.__init__(
            self, air, furnitureManager, catalogItem)
        self.initialScale = (0.8, 0.8, 0.8)
        self.busyAvatarId = 0
        self._purchaseInFlight = False
        self._responses = ResponseReplayCache()

    def setInitialScale(self, sx, sy, sz):
        self.initialScale = (sx, sy, sz)

    def getInitialScale(self):
        return self.initialScale

    def setNewScale(self, sx, sy, sz):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.busyAvatarId:
            return
        values = (sx, sy, sz)
        if (not all(math.isfinite(value) for value in values) or
                any(value < 0.1 or value > 2.0 for value in values)):
            return
        self.setInitialScale(*values)
        self.sendUpdate('setInitialScale', list(values))

    def avatarEnter(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId or
                avId != self.furnitureManager.ownerId):
            self.furnitureManager.recordUnauthorized(avId, 'use phone')
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        from toontown.authority.ServerActionGuardsAI import requireInteraction
        if not requireInteraction(
                self.air, avId, avatar, target=self,
                maximum=24.0, action='catalog.phone.enter'):
            self.furnitureManager.recordUnauthorized(
                avId, 'used catalog phone remotely')
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if self.busyAvatarId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if not avatar.houseId:
            self._sendMovie(PhoneGlobals.PHONE_MOVIE_EMPTY, avId)
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return
        if not (len(avatar.monthlyCatalog) or len(avatar.weeklyCatalog) or
                len(avatar.backCatalog)):
            # A brand-new avatar can reach the house before the management
            # object has answered startCatalog. Generate synchronously here.
            self.air.catalogManager.deliverCatalogFor(avatar)
            self._sendMovie(PhoneGlobals.PHONE_MOVIE_EMPTY, avId)
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])
            return

        self.busyAvatarId = avId
        state = self.furnitureManager._decodeState(
            self.furnitureManager._currentFields())
        self.sendUpdateToAvatarId(
            avId, 'setLimits',
            [self.furnitureManager._houseItemCount(state)])
        self._sendMovie(PhoneGlobals.PHONE_MOVIE_PICKUP, avId)
        avatar.b_setCatalogNotify(
            ToontownGlobals.NoItems, avatar.mailboxNotify)

    def avatarExit(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.busyAvatarId:
            return
        self.busyAvatarId = 0
        self._sendMovie(PhoneGlobals.PHONE_MOVIE_HANGUP, avId)
        taskMgr.doMethodLater(
            1.0, self._resetMovie,
            self.uniqueName('reset-phone-movie'))

    def freeAvatar(self):
        avId = self.busyAvatarId
        self.busyAvatarId = 0
        if avId:
            self.sendUpdateToAvatarId(avId, 'freeAvatar', [])

    def _sendMovie(self, mode, avId):
        self.sendUpdate(
            'setMovie',
            [mode, avId, globalClockDelta.getRealNetworkTime(bits=32)])

    def _resetMovie(self, task):
        self._sendMovie(PhoneGlobals.PHONE_MOVIE_CLEAR, 0)
        return task.done

    def requestPurchaseMessage(self, context, blob, optional):
        avId = self.air.getAvatarIdFromSender()
        fingerprint = (bytes(blob), int(optional))
        key = (avId, 'catalog-purchase', int(context))
        status, response = self._responses.lookup(key, fingerprint)
        if status == 'replay':
            # A lost response may cause Astron/the browser transport to retry
            # the already committed request.  Replaying the cached response is
            # harmless and must not require a second spend capability.
            self.sendUpdateToAvatarId(
                avId, 'requestPurchaseResponse', list(response))
            return
        if status == 'mismatch':
            self.furnitureManager.recordUnauthorized(
                avId, 'reused catalog purchase context')
            self._respondPurchase(
                avId, context, ToontownGlobals.P_InvalidIndex,
                key, fingerprint)
            return
        from toontown.authority.BrowserAuthorityManagerAI import (
            consumeProtectedTransition,
        )
        if not consumeProtectedTransition(
                self.air, avId, 'catalog.purchase',
                {'phone': self.doId, 'context': context, 'gift': 0}):
            return
        if (avId != self.busyAvatarId or self._purchaseInFlight):
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NotShopping,
                key, fingerprint)
            return
        avatar = self.air.doId2do.get(avId)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NotShopping,
                key, fingerprint)
            return

        item = CatalogItem.getItem(
            blob, store=CatalogItem.Customization)
        if isinstance(item, CatalogInvalidItem):
            self._respondPurchase(
                avId, context, ToontownGlobals.P_InvalidIndex,
                key, fingerprint)
            return
        offer, catalogType = self._findOffer(avatar, item)
        if offer is None:
            self.furnitureManager.recordUnauthorized(
                avId, 'purchase item not in catalog')
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NotInCatalog,
                key, fingerprint)
            return
        if (offer.loyaltyRequirement() and
                getattr(avatar, 'getAccountDays', lambda: 0)() <
                offer.loyaltyRequirement()):
            self._respondPurchase(
                avId, context, ToontownGlobals.P_ReachedPurchaseLimit,
                key, fingerprint)
            return
        item.saleItem = offer.saleItem
        if item.notOfferedTo(avatar) or item.reachedPurchaseLimit(avatar):
            self._respondPurchase(
                avId, context, ToontownGlobals.P_ReachedPurchaseLimit,
                key, fingerprint)
            return
        if item.getEmblemPrices():
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NoPurchaseMethod,
                key, fingerprint)
            return
        price = item.getPrice(catalogType)
        money = avatar.getMoney()
        bankMoney = avatar.getBankMoney()
        balances = chargeBalances(money, bankMoney, price)
        if balances is None:
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NotEnoughMoney,
                key, fingerprint)
            return
        if not item.getDeliveryTime():
            self._purchaseInstant(
                avatar, item, optional, balances,
                context, key, fingerprint)
            return
        if len(avatar.onOrder) >= self.MAX_ON_ORDER:
            self._respondPurchase(
                avId, context, ToontownGlobals.P_OnOrderListFull,
                key, fingerprint)
            return
        if (len(avatar.mailboxContents) + len(avatar.onOrder) >=
                ToontownGlobals.MaxMailboxContents):
            self._respondPurchase(
                avId, context, ToontownGlobals.P_MailboxFull,
                key, fingerprint)
            return

        newMoney, newBankMoney = balances
        item.deliveryDate = (
            int(time.time() / 60.0) + item.getDeliveryTime())
        newOrder = CatalogItemList(
            avatar.onOrder,
            store=CatalogItem.Customization | CatalogItem.DeliveryDate)
        newOrder.append(item)
        oldFields = {
            'setMoney': money,
            'setBankMoney': bankMoney,
            'setDeliverySchedule': avatar.getDeliverySchedule(),
        }
        newFields = {
            'setMoney': newMoney,
            'setBankMoney': newBankMoney,
            'setDeliverySchedule': newOrder.getBlob(),
        }
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._purchaseInFlight = True

        def committed(success, conflicts):
            self._purchaseInFlight = False
            if not success:
                self._applyMoneyConflict(avatar, conflicts)
                self._respondPurchase(
                    avId, context, ToontownGlobals.P_InvalidIndex,
                    key, fingerprint)
                return
            avatar.setMoney(newMoney)
            avatar.d_setMoney(newMoney)
            avatar.setBankMoney(newBankMoney)
            avatar.d_setBankMoney(newBankMoney)
            avatar.setDeliverySchedule(newOrder)
            avatar.d_setDeliverySchedule(newOrder)
            self._respondPurchase(
                avId, context, ToontownGlobals.P_ItemOnOrder,
                key, fingerprint)

        transaction.commit(oldFields, newFields, committed)

    def _purchaseInstant(self, avatar, item, optional, balances,
                         context, key, fingerprint):
        avId = avatar.doId
        plan = planToonApplication(avatar, item, optional)
        if plan is None:
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NoPurchaseMethod,
                key, fingerprint)
            return
        retcode, itemOldFields, itemNewFields = plan
        if retcode != ToontownGlobals.P_ItemAvailable:
            self._respondPurchase(
                avId, context, retcode, key, fingerprint)
            return
        if 'setMoney' in itemOldFields or 'setBankMoney' in itemOldFields:
            # Bean grants are mailbox/refund items rather than catalog offers;
            # combining a grant with a charge needs explicit price semantics.
            self._respondPurchase(
                avId, context, ToontownGlobals.P_NoPurchaseMethod,
                key, fingerprint)
            return
        oldFields = dict(itemOldFields)
        oldFields.update({
            'setMoney': avatar.getMoney(),
            'setBankMoney': avatar.getBankMoney(),
        })
        newFields = dict(itemNewFields)
        newFields.update({
            'setMoney': balances[0],
            'setBankMoney': balances[1],
        })
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._purchaseInFlight = True

        def committed(success, conflicts):
            self._purchaseInFlight = False
            if not success:
                self._applyMoneyConflict(avatar, conflicts)
                self._respondPurchase(
                    avId, context, ToontownGlobals.P_InvalidIndex,
                    key, fingerprint)
                return
            applyToonFields(avatar, itemNewFields)
            postApplyItem(avatar, item)
            avatar.setMoney(balances[0])
            avatar.d_setMoney(balances[0])
            avatar.setBankMoney(balances[1])
            avatar.d_setBankMoney(balances[1])
            self._respondPurchase(
                avId, context, ToontownGlobals.P_ItemAvailable,
                key, fingerprint)

        transaction.commit(oldFields, newFields, committed)

    def requestGiftPurchaseMessage(self, context, targetId, blob, optional):
        avId = self.air.getAvatarIdFromSender()
        from toontown.authority.BrowserAuthorityManagerAI import (
            consumeProtectedTransition,
        )
        if not consumeProtectedTransition(
                self.air, avId, 'catalog.purchase',
                {'phone': self.doId, 'context': context, 'gift': 1}):
            return
        # Gifting spans two Toon records. It will be enabled with the delivery
        # recovery journal rather than risking a charge without a gift.
        self.sendUpdateToAvatarId(
            avId, 'requestGiftPurchaseResponse',
            [context, ToontownGlobals.P_NoPurchaseMethod])

    def _findOffer(self, avatar, item):
        catalogs = (
            (avatar.weeklyCatalog, CatalogItem.CatalogTypeWeekly),
            (avatar.monthlyCatalog, CatalogItem.CatalogTypeMonthly),
            (avatar.backCatalog, CatalogItem.CatalogTypeBackorder),
        )
        for catalog, catalogType in catalogs:
            for offer in catalog:
                if offer == item:
                    return offer, catalogType
        return None, CatalogItem.CatalogTypeUnspecified

    def _respondPurchase(self, avId, context, retcode, key, fingerprint):
        response = (context, retcode)
        self._responses.remember(key, fingerprint, response)
        self.sendUpdateToAvatarId(
            avId, 'requestPurchaseResponse', list(response))

    def _applyMoneyConflict(self, avatar, conflicts):
        if not conflicts:
            return
        if 'setMoney' in conflicts:
            avatar.setMoney(conflicts['setMoney'])
            avatar.d_setMoney(conflicts['setMoney'])
        if 'setBankMoney' in conflicts:
            avatar.setBankMoney(conflicts['setBankMoney'])
            avatar.d_setBankMoney(conflicts['setBankMoney'])
        if 'setDeliverySchedule' in conflicts:
            order = CatalogItemList(
                conflicts['setDeliverySchedule'],
                store=CatalogItem.Customization | CatalogItem.DeliveryDate)
            avatar.setDeliverySchedule(order)
            avatar.d_setDeliverySchedule(order)

    def delete(self):
        taskMgr.remove(self.uniqueName('reset-phone-movie'))
        DistributedFurnitureItemAI.delete(self)
