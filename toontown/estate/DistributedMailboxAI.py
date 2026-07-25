import hashlib
import time

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from toontown.catalog import CatalogItem
from toontown.catalog.CatalogFurnitureItem import (
    FLBank, FLCloset, FLPhone, FLTrunk)
from toontown.catalog.CatalogInvalidItem import CatalogInvalidItem
from toontown.catalog.CatalogItemList import CatalogItemList
from toontown.catalog.CatalogRentalItem import CatalogRentalItem
from toontown.catalog.CatalogAtomicAdapters import (
    applyToonFields, planToonApplication, postApplyItem)
from toontown.catalog.CatalogSurfaceItem import CatalogSurfaceItem
from toontown.catalog.CatalogWindowItem import CatalogWindowItem
from toontown.estate import MailboxGlobals
from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, ResponseReplayCache)
from toontown.estate.EstateTransactionJournal import (
    decodeJournal, encodeJournal)
from toontown.toonbase import ToontownGlobals


class DistributedMailboxAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory('DistributedMailboxAI')

    def __init__(self, air, houseId=0, housePos=0, name='', ownerId=0):
        DistributedObjectAI.__init__(self, air)
        self.houseId = houseId
        self.housePos = housePos
        self.name = name
        self.ownerId = ownerId
        self.fullIndicator = 0
        self.busyAvatarId = 0
        self._operationInFlight = False
        self._responses = ResponseReplayCache()

    def setHouseId(self, houseId):
        self.houseId = houseId

    def getHouseId(self):
        return self.houseId

    def setHousePos(self, housePos):
        self.housePos = housePos

    def getHousePos(self):
        return self.housePos

    def setName(self, name):
        self.name = name

    def getName(self):
        return self.name

    def setFullIndicator(self, fullIndicator):
        self.fullIndicator = fullIndicator

    def getFullIndicator(self):
        return self.fullIndicator

    def d_setFullIndicator(self, fullIndicator):
        self.sendUpdate('setFullIndicator', [fullIndicator])

    def b_setFullIndicator(self, fullIndicator):
        self.setFullIndicator(fullIndicator)
        self.d_setFullIndicator(fullIndicator)

    def avatarEnter(self):
        avId = self.air.getAvatarIdFromSender()
        avatar = self.air.doId2do.get(avId)
        if (avatar is None or
                getattr(avatar, 'zoneId', 0) != self.zoneId):
            if avatar is not None:
                self._recordUnauthorized(avId, 'use mailbox from another zone')
            return
        if avId != self.ownerId:
            self._recordUnauthorized(avId, 'use mailbox')
            self._sendMovie(avId, MailboxGlobals.MAILBOX_MOVIE_NOT_OWNER)
            self._freeAvatar(avId)
            return
        if self.busyAvatarId and self.busyAvatarId != avId:
            self._sendMovie(avId, MailboxGlobals.MAILBOX_MOVIE_WAITING)
            self._freeAvatar(avId)
            return

        self.busyAvatarId = avId
        if avatar.getEstateTransactionJournal():
            self._recoverJournal(avatar)
        mode = (
            MailboxGlobals.MAILBOX_MOVIE_READY
            if self._avatarHasMail(avatar)
            else MailboxGlobals.MAILBOX_MOVIE_EMPTY)
        self._sendMovie(avId, mode)

    def avatarExit(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.busyAvatarId:
            return
        self.busyAvatarId = 0
        self._sendMovie(avId, MailboxGlobals.MAILBOX_MOVIE_EXIT)
        self._freeAvatar(avId)

    def acceptItemMessage(self, context, blob, index, optional):
        avId = self.air.getAvatarIdFromSender()
        fingerprint = (bytes(blob), int(index), int(optional))
        key = (avId, 'mailbox-accept', int(context))
        if self._replayOrRejectContext(
                key, fingerprint, 'acceptItemResponse', context):
            return
        avatar = self._activeOwner(avId)
        if avatar is None:
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_NotAtMailbox, key, fingerprint)
            return
        if self._operationInFlight or avatar.getEstateTransactionJournal():
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_NotAtMailbox, key, fingerprint)
            return
        item = self._mailItem(avatar, index, blob)
        if item is None:
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_InvalidIndex, key, fingerprint)
            return
        if isinstance(item, CatalogRentalItem):
            self._acceptRental(
                avatar, item, blob, avId, context, key, fingerprint)
            return
        toonPlan = planToonApplication(avatar, item, optional)
        if toonPlan is not None:
            self._acceptToonItem(
                avatar, item, index, toonPlan, avId, context,
                key, fingerprint)
            return
        manager = self._furnitureManager()
        if manager is None:
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_InvalidIndex, key, fingerprint)
            return
        try:
            newHouseFields, toonUpdates = self._buildHouseDelivery(
                manager, avatar, item)
        except ValueError as error:
            self.notify.info(
                'Mailbox item %s could not be accepted by avatar %s: %s' %
                (item, avId, error))
            retcode = error.args[0] if error.args else ToontownGlobals.P_InvalidIndex
            if not isinstance(retcode, int):
                retcode = ToontownGlobals.P_InvalidIndex
            self._respond(
                avId, 'acceptItemResponse', context,
                retcode, key, fingerprint)
            return

        oldHouseFields = dict(manager._persistedFields)
        txid = hashlib.sha256(
            ('%s:%s:' % (avId, context)).encode('ascii') +
            bytes(blob)).hexdigest()
        payload = {
            'kind': 'mailbox-house-delivery',
            'txid': txid,
            'avatarId': avId,
            'houseId': self.houseId,
            'itemBlob': bytes(blob),
            'oldHouseFields': oldHouseFields,
            'newHouseFields': newHouseFields,
            'toonUpdates': toonUpdates,
        }
        journal = encodeJournal(payload)
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._operationInFlight = True

        def prepared(success, conflicts):
            if not success:
                self._operationInFlight = False
                self._respond(
                    avId, 'acceptItemResponse', context,
                    ToontownGlobals.P_InvalidIndex, key, fingerprint)
                return
            avatar.setEstateTransactionJournal(journal)

            def houseCommitted(houseSuccess, houseConflicts):
                if not houseSuccess:
                    self._clearPreparedJournal(
                        avatar, journal,
                        lambda: self._finishFailedAccept(
                            avId, context, key, fingerprint))
                    return
                manager._applyCommittedState(newHouseFields)
                self._finalizeJournal(
                    avatar, payload, journal,
                    lambda finalSuccess: self._finishAccept(
                        avId, context, key, fingerprint, finalSuccess))

            manager._transaction.commit(
                oldHouseFields, newHouseFields, houseCommitted)

        transaction.commit(
            {'setEstateTransactionJournal': b''},
            {'setEstateTransactionJournal': journal},
            prepared)

    def _acceptToonItem(self, avatar, item, index, plan, avId, context,
                        key, fingerprint):
        retcode, itemOldFields, itemNewFields = plan
        if retcode != ToontownGlobals.P_ItemAvailable:
            self._respond(
                avId, 'acceptItemResponse', context,
                retcode, key, fingerprint)
            return
        mailbox = CatalogItemList(
            avatar.mailboxContents, store=CatalogItem.Customization)
        if index < 0 or index >= len(mailbox):
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_InvalidIndex, key, fingerprint)
            return
        del mailbox[index]
        oldFields = dict(itemOldFields)
        oldFields['setMailboxContents'] = avatar.getMailboxContents()
        newFields = dict(itemNewFields)
        newFields['setMailboxContents'] = mailbox.getBlob()
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._operationInFlight = True

        def committed(success, conflicts):
            self._operationInFlight = False
            if not success:
                self._respond(
                    avId, 'acceptItemResponse', context,
                    ToontownGlobals.P_InvalidIndex, key, fingerprint)
                return
            applyToonFields(avatar, itemNewFields)
            postApplyItem(avatar, item)
            avatar.setMailboxContents(mailbox)
            avatar.d_setMailboxContents(mailbox)
            self.b_setFullIndicator(self._avatarHasMail(avatar))
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_ItemAvailable, key, fingerprint)

        transaction.commit(oldFields, newFields, committed)

    def discardItemMessage(self, context, blob, index, optional):
        avId = self.air.getAvatarIdFromSender()
        fingerprint = (bytes(blob), int(index), int(optional))
        key = (avId, 'mailbox-discard', int(context))
        if self._replayOrRejectContext(
                key, fingerprint, 'discardItemResponse', context):
            return
        avatar = self._activeOwner(avId)
        if avatar is None or self._operationInFlight:
            self._respond(
                avId, 'discardItemResponse', context,
                ToontownGlobals.P_NotAtMailbox, key, fingerprint)
            return
        item = self._mailItem(avatar, index, blob)
        if item is None:
            self._respond(
                avId, 'discardItemResponse', context,
                ToontownGlobals.P_InvalidIndex, key, fingerprint)
            return
        newMailbox = CatalogItemList(
            avatar.mailboxContents, store=CatalogItem.Customization)
        del newMailbox[index]
        oldBlob = avatar.getMailboxContents()
        newBlob = newMailbox.getBlob()
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        self._operationInFlight = True

        def committed(success, conflicts):
            self._operationInFlight = False
            if not success:
                self._respond(
                    avId, 'discardItemResponse', context,
                    ToontownGlobals.P_InvalidIndex, key, fingerprint)
                return
            avatar.setMailboxContents(newMailbox)
            avatar.d_setMailboxContents(newMailbox)
            self._respond(
                avId, 'discardItemResponse', context,
                ToontownGlobals.P_ItemAvailable, key, fingerprint)

        transaction.commit(
            {'setMailboxContents': oldBlob},
            {'setMailboxContents': newBlob},
            committed)

    def acceptInviteMessage(self, context, inviteKey):
        avId = self.air.getAvatarIdFromSender()
        self.sendUpdateToAvatarId(
            avId, 'acceptItemResponse',
            [context, ToontownGlobals.P_NoPurchaseMethod])

    def rejectInviteMessage(self, context, inviteKey):
        avId = self.air.getAvatarIdFromSender()
        self.sendUpdateToAvatarId(
            avId, 'discardItemResponse',
            [context, ToontownGlobals.P_NoPurchaseMethod])

    def markInviteReadButNotReplied(self, inviteKey):
        return

    # Cross-object delivery ---------------------------------------------
    def _acceptRental(self, avatar, item, blob, avId, context, key,
                      fingerprint):
        estateManager = getattr(self.air, 'estateMgr', None)
        estate = (
            estateManager.estate.get(self.ownerId)
            if estateManager is not None else None)
        if (estate is None or item.getRentalType() !=
                ToontownGlobals.RentalCannon or item.getDuration() <= 0):
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_NoPurchaseMethod, key, fingerprint)
            return
        now = int(time.time())
        if (estate.getRentalType() and
                estate.getRentalTimeStamp() > now):
            self._respond(
                avId, 'acceptItemResponse', context,
                ToontownGlobals.P_ReachedPurchaseLimit, key, fingerprint)
            return
        oldEstateFields = {
            'setRentalTimeStamp': estate.getRentalTimeStamp(),
            'setRentalType': estate.getRentalType(),
        }
        # Catalog durations are minutes. Bound corrupted legacy blobs to one
        # week even though the preserved catalog currently sells 48 hours.
        duration = min(int(item.getDuration()), 7 * 24 * 60)
        newEstateFields = {
            'setRentalTimeStamp': now + duration * 60,
            'setRentalType': int(item.getRentalType()),
        }
        txid = hashlib.sha256(
            ('rental:%s:%s:' % (avId, context)).encode('ascii') +
            bytes(blob)).hexdigest()
        payload = {
            'kind': 'mailbox-estate-rental',
            'txid': txid,
            'avatarId': avId,
            'estateId': estate.doId,
            'itemBlob': bytes(blob),
            'oldEstateFields': oldEstateFields,
            'newEstateFields': newEstateFields,
        }
        journal = encodeJournal(payload)
        toonTransaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])
        estateTransaction = AstronObjectTransaction(
            self.air, estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])
        self._operationInFlight = True

        def prepared(success, conflicts):
            if not success:
                self._finishFailedAccept(avId, context, key, fingerprint)
                return
            avatar.setEstateTransactionJournal(journal)

            def estateCommitted(estateSuccess, estateConflicts):
                if not estateSuccess:
                    self._clearPreparedJournal(
                        avatar, journal,
                        lambda: self._finishFailedAccept(
                            avId, context, key, fingerprint))
                    return
                estateManager.applyRentalState(
                    self.ownerId,
                    newEstateFields['setRentalTimeStamp'],
                    newEstateFields['setRentalType'])
                self._finalizeJournal(
                    avatar, payload, journal,
                    lambda finalSuccess: self._finishAccept(
                        avId, context, key, fingerprint, finalSuccess))

            estateTransaction.commit(
                oldEstateFields, newEstateFields, estateCommitted)

        toonTransaction.commit(
            {'setEstateTransactionJournal': b''},
            {'setEstateTransactionJournal': journal},
            prepared)

    def _buildHouseDelivery(self, manager, avatar, item):
        state = manager._decodeState(manager._currentFields())
        toonUpdates = {}
        if isinstance(item, CatalogWindowItem):
            if manager._houseItemCount(state) >= ToontownGlobals.MaxHouseItems:
                raise ValueError(ToontownGlobals.P_NoRoomForItem)
            item.placement = None
            state['atticWindows'].append(item)
        elif isinstance(item, CatalogSurfaceItem):
            if manager._houseItemCount(state) >= ToontownGlobals.MaxHouseItems:
                raise ValueError(ToontownGlobals.P_NoRoomForItem)
            state['atticWallpaper'].append(item)
        elif hasattr(item, 'getFlags'):
            flags = item.getFlags()
            if flags & FLPhone:
                raise ValueError(ToontownGlobals.P_ReachedPurchaseLimit)
            replaced = False
            replaceFlags = flags & (FLBank | FLCloset | FLTrunk)
            if replaceFlags:
                for collectionName in ('room', 'attic'):
                    collection = state[collectionName]
                    for itemIndex, existing in enumerate(collection):
                        if existing.getFlags() & replaceFlags:
                            if collectionName == 'room':
                                item.posHpr = existing.posHpr
                            collection[itemIndex] = item
                            replaced = True
                            break
                    if replaced:
                        break
            if not replaced:
                if manager._houseItemCount(state) >= ToontownGlobals.MaxHouseItems:
                    raise ValueError(ToontownGlobals.P_NoRoomForItem)
                state['attic'].append(item)
            if flags & FLCloset:
                toonUpdates['setMaxClothes'] = max(
                    avatar.getMaxClothes(), item.getMaxClothes())
            if flags & FLBank:
                toonUpdates['setMaxBankMoney'] = max(
                    avatar.getMaxBankMoney(), item.getMaxBankMoney())
            if flags & FLTrunk:
                toonUpdates['setMaxAccessories'] = max(
                    avatar.getMaxAccessories(), item.getMaxAccessories())
        else:
            raise ValueError(ToontownGlobals.P_NoPurchaseMethod)
        return manager._encodeState(state), toonUpdates

    def _finalizeJournal(self, avatar, payload, journal, callback):
        mailbox = CatalogItemList(
            avatar.mailboxContents, store=CatalogItem.Customization)
        itemBlob = payload['itemBlob']
        removed = False
        for index, item in enumerate(mailbox):
            if item.getBlob(store=CatalogItem.Customization) == itemBlob:
                del mailbox[index]
                removed = True
                break
        if not removed:
            self.notify.warning(
                'Journal %s finalized after mailbox item was already absent' %
                payload['txid'])

        oldFields = {
            'setEstateTransactionJournal': journal,
            'setMailboxContents': avatar.getMailboxContents(),
        }
        newFields = {
            'setEstateTransactionJournal': b'',
            'setMailboxContents': mailbox.getBlob(),
        }
        for fieldName, target in payload.get('toonUpdates', {}).items():
            current = self._getToonField(avatar, fieldName)
            oldFields[fieldName] = current
            newFields[fieldName] = max(current, target)
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def committed(success, conflicts):
            if not success:
                callback(False)
                return
            avatar.setEstateTransactionJournal(b'')
            avatar.setMailboxContents(mailbox)
            avatar.d_setMailboxContents(mailbox)
            for fieldName, value in newFields.items():
                if fieldName in ('setEstateTransactionJournal',
                                 'setMailboxContents'):
                    continue
                self._setToonField(avatar, fieldName, value)
            callback(True)

        transaction.commit(oldFields, newFields, committed)

    def _recoverJournal(self, avatar):
        if self._operationInFlight:
            return
        journal = avatar.getEstateTransactionJournal()
        try:
            payload = decodeJournal(journal)
        except Exception as error:
            self.notify.warning(
                'Invalid estate transaction journal on avatar %s: %s' %
                (avatar.doId, error))
            return
        if not payload:
            return
        if payload.get('kind') == 'mailbox-estate-rental':
            self._recoverRentalJournal(avatar, payload, journal)
            return
        if (payload.get('kind') != 'mailbox-house-delivery' or
                payload.get('houseId') != self.houseId):
            return
        manager = self._furnitureManager()
        if manager is None:
            return
        current = manager._persistedFields
        oldFields = payload['oldHouseFields']
        newFields = payload['newHouseFields']
        self._operationInFlight = True
        if current == newFields:
            self._finalizeJournal(
                avatar, payload, journal,
                lambda success: self._recoveryFinished(success))
            return
        if current != oldFields:
            self._operationInFlight = False
            self.notify.warning(
                'Estate journal %s needs manual reconciliation; House %s '
                'matches neither side' %
                (payload.get('txid'), self.houseId))
            return

        def committed(success, conflicts):
            if not success:
                self._operationInFlight = False
                return
            manager._applyCommittedState(newFields)
            self._finalizeJournal(
                avatar, payload, journal,
                lambda finalSuccess: self._recoveryFinished(finalSuccess))

        manager._transaction.commit(oldFields, newFields, committed)

    def _recoverRentalJournal(self, avatar, payload, journal):
        estateManager = getattr(self.air, 'estateMgr', None)
        estate = (
            estateManager.estate.get(self.ownerId)
            if estateManager is not None else None)
        if estate is None or payload.get('estateId') != estate.doId:
            return
        oldFields = payload.get('oldEstateFields', {})
        newFields = payload.get('newEstateFields', {})
        current = {
            'setRentalTimeStamp': estate.getRentalTimeStamp(),
            'setRentalType': estate.getRentalType(),
        }
        self._operationInFlight = True
        if current == newFields:
            estateManager.applyRentalState(
                self.ownerId, newFields['setRentalTimeStamp'],
                newFields['setRentalType'])
            self._finalizeJournal(
                avatar, payload, journal,
                lambda success: self._recoveryFinished(success))
            return
        if current != oldFields:
            self._operationInFlight = False
            self.notify.warning(
                'Estate rental journal %s needs manual reconciliation; '
                'Estate %s matches neither side' %
                (payload.get('txid'), estate.doId))
            return

        transaction = AstronObjectTransaction(
            self.air, estate.doId,
            self.air.dclassesByName['DistributedEstateAI'])

        def committed(success, conflicts):
            if not success:
                self._operationInFlight = False
                return
            estateManager.applyRentalState(
                self.ownerId, newFields['setRentalTimeStamp'],
                newFields['setRentalType'])
            self._finalizeJournal(
                avatar, payload, journal,
                lambda finalSuccess: self._recoveryFinished(finalSuccess))

        transaction.commit(oldFields, newFields, committed)

    def _recoveryFinished(self, success):
        self._operationInFlight = False
        if success:
            avatar = self.air.doId2do.get(self.ownerId)
            if avatar is not None:
                self.b_setFullIndicator(self._avatarHasMail(avatar))

    def _clearPreparedJournal(self, avatar, journal, callback):
        transaction = AstronObjectTransaction(
            self.air, avatar.doId,
            self.air.dclassesByName['DistributedToonAI'])

        def cleared(success, conflicts):
            if success:
                avatar.setEstateTransactionJournal(b'')
            callback()

        transaction.commit(
            {'setEstateTransactionJournal': journal},
            {'setEstateTransactionJournal': b''},
            cleared)

    def _finishAccept(self, avId, context, key, fingerprint, success):
        self._operationInFlight = False
        retcode = (
            ToontownGlobals.P_ItemAvailable if success else
            ToontownGlobals.P_InvalidIndex)
        self._respond(
            avId, 'acceptItemResponse', context, retcode, key, fingerprint)

    def _finishFailedAccept(self, avId, context, key, fingerprint):
        self._operationInFlight = False
        self._respond(
            avId, 'acceptItemResponse', context,
            ToontownGlobals.P_InvalidIndex, key, fingerprint)

    # Helpers ------------------------------------------------------------
    def _activeOwner(self, avId):
        if avId != self.ownerId or avId != self.busyAvatarId:
            self._recordUnauthorized(avId, 'mailbox transaction')
            return None
        avatar = self.air.doId2do.get(avId)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            return None
        return avatar

    def _mailItem(self, avatar, index, blob):
        if index < 0 or index >= len(avatar.mailboxContents):
            return None
        item = avatar.mailboxContents[index]
        if isinstance(item, CatalogInvalidItem):
            return None
        if item.getBlob(store=CatalogItem.Customization) != bytes(blob):
            return None
        return CatalogItem.getItem(
            blob, store=CatalogItem.Customization)

    def _furnitureManager(self):
        estateManager = getattr(self.air, 'estateMgr', None)
        if estateManager is None:
            return None
        manager = estateManager.furnitureManagers.get(self.ownerId)
        if manager is None or manager.house.doId != self.houseId:
            return None
        return manager

    def _replayOrRejectContext(self, key, fingerprint, responseName, context):
        avId = key[0]
        status, response = self._responses.lookup(key, fingerprint)
        if status == 'replay':
            self.sendUpdateToAvatarId(avId, responseName, list(response))
            return True
        if status == 'mismatch':
            self._recordUnauthorized(avId, 'reused mailbox context')
            self.sendUpdateToAvatarId(
                avId, responseName,
                [context, ToontownGlobals.P_InvalidIndex])
            return True
        return False

    def _respond(self, avId, responseName, context, retcode, key,
                 fingerprint):
        response = (context, retcode)
        self._responses.remember(key, fingerprint, response)
        self.sendUpdateToAvatarId(avId, responseName, list(response))

    def _getToonField(self, avatar, fieldName):
        getters = {
            'setMaxClothes': avatar.getMaxClothes,
            'setMaxBankMoney': avatar.getMaxBankMoney,
            'setMaxAccessories': avatar.getMaxAccessories,
        }
        return getters[fieldName]()

    def _setToonField(self, avatar, fieldName, value):
        setters = {
            'setMaxClothes': (
                avatar.setMaxClothes, avatar.d_setMaxClothes),
            'setMaxBankMoney': (
                avatar.setMaxBankMoney, avatar.d_setMaxBankMoney),
            'setMaxAccessories': (
                avatar.setMaxAccessories, avatar.d_setMaxAccessories),
        }
        setter, broadcaster = setters[fieldName]
        setter(value)
        broadcaster(value)

    def _avatarHasMail(self, avatar):
        return bool(
            len(getattr(avatar, 'mailboxContents', [])) or
            len(getattr(avatar, 'awardMailboxContents', [])) or
            getattr(avatar, 'numMailItems', 0) or
            getattr(avatar, 'getNumInvitesToShowInMailbox', lambda: 0)())

    def _sendMovie(self, avId, mode):
        self.sendUpdateToAvatarId(avId, 'setMovie', [mode, avId])

    def _freeAvatar(self, avId):
        self.sendUpdateToAvatarId(avId, 'freeAvatar', [])

    def _recordUnauthorized(self, avId, action):
        self.air.writeServerEvent(
            'suspicious', avId,
            '%s on mailbox %s owned by %s' %
            (action, self.doId, self.ownerId))
