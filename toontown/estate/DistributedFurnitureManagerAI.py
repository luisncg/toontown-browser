from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from toontown.catalog import CatalogItem
from toontown.catalog.CatalogFlooringItem import CatalogFlooringItem
from toontown.catalog.CatalogFurnitureItem import (
    CatalogFurnitureItem, FLBank, FLCloset, FLPhone, FLTrunk)
from toontown.catalog.CatalogItemList import CatalogItemList
from toontown.catalog.CatalogMouldingItem import CatalogMouldingItem
from toontown.catalog.CatalogSurfaceItem import NUM_ST_TYPES
from toontown.catalog.CatalogWainscotingItem import CatalogWainscotingItem
from toontown.catalog.CatalogWallpaperItem import CatalogWallpaperItem
from toontown.estate.DistributedBankAI import DistributedBankAI
from toontown.estate.DistributedClosetAI import DistributedClosetAI
from toontown.estate.DistributedFurnitureItemAI import DistributedFurnitureItemAI
from toontown.estate.DistributedPhoneAI import DistributedPhoneAI
from toontown.estate.DistributedTrunkAI import DistributedTrunkAI
from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, ResponseReplayCache, SerialOperationQueue)
from toontown.toonbase import ToontownGlobals


class FurnitureError(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


class DistributedFurnitureManagerAI(DistributedObjectAI):
    """Authoritative, persistent furniture editor for one Toon house.

    All seven House content blobs are committed with one Astron CAS.  Defaults
    are supplied in memory for old or incomplete House records and only become
    persistent after the owner makes an explicit furniture edit.
    """

    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedFurnitureManagerAI')

    CONTENT_FIELDS = (
        'setAtticItems',
        'setInteriorItems',
        'setAtticWallpaper',
        'setInteriorWallpaper',
        'setAtticWindows',
        'setInteriorWindows',
        'setDeletedItems',
    )

    def __init__(self, air, house=None, interior=None, ownerId=0,
                 ownerName='', interiorId=0, atticItems=b'',
                 atticWallpaper=b'', atticWindows=b'', deletedItems=b''):
        DistributedObjectAI.__init__(self, air)
        self.house = house
        self.interior = interior
        self.ownerId = house.getAvatarId() if house is not None else ownerId
        self.ownerName = house.getName() if house is not None else ownerName
        self.interiorId = (
            interior.doId if interior is not None else interiorId)
        self.director = 0
        self.avatars = set()
        self.items = []
        self._queue = SerialOperationQueue()
        self._responses = ResponseReplayCache()
        self._positionCommitQueued = set()
        self._positionCommitDirty = set()
        self._usingFallbackDefaults = False

        if house is not None:
            self._persistedFields = house.getContentFields()
        else:
            self._persistedFields = {
                'setAtticItems': atticItems,
                'setInteriorItems': b'',
                'setAtticWallpaper': atticWallpaper,
                'setInteriorWallpaper': b'',
                'setAtticWindows': atticWindows,
                'setInteriorWindows': b'',
                'setDeletedItems': deletedItems,
            }

        self._loadActiveState(self._persistedFields, allowFallback=True,
                              generateItems=False)
        self._transaction = None
        if house is not None:
            dclass = self.air.dclassesByName['DistributedHouseAI']
            self._transaction = AstronObjectTransaction(
                self.air, house.doId, dclass)

    def announceGenerate(self):
        DistributedObjectAI.announceGenerate(self)
        self._generateItems()

    # Required fields -----------------------------------------------------
    def setOwnerId(self, ownerId):
        self.ownerId = ownerId

    def getOwnerId(self):
        return self.ownerId

    def setOwnerName(self, ownerName):
        self.ownerName = ownerName

    def getOwnerName(self):
        return self.ownerName

    def setInteriorId(self, interiorId):
        self.interiorId = interiorId

    def getInteriorId(self):
        return self.interiorId

    def setAtticItems(self, items):
        self.atticItems = CatalogItemList(
            items, store=CatalogItem.Customization)

    def getAtticItems(self):
        return self.atticItems.getBlob()

    def d_setAtticItems(self, items):
        self.sendUpdate('setAtticItems', [items])

    def b_setAtticItems(self, items):
        self.setAtticItems(items)
        self.d_setAtticItems(items)

    def setAtticWallpaper(self, items):
        self.atticWallpaper = CatalogItemList(
            items, store=CatalogItem.Customization)

    def getAtticWallpaper(self):
        return self.atticWallpaper.getBlob()

    def d_setAtticWallpaper(self, items):
        self.sendUpdate('setAtticWallpaper', [items])

    def b_setAtticWallpaper(self, items):
        self.setAtticWallpaper(items)
        self.d_setAtticWallpaper(items)

    def setAtticWindows(self, items):
        self.atticWindows = CatalogItemList(
            items, store=CatalogItem.Customization)

    def getAtticWindows(self):
        return self.atticWindows.getBlob()

    def d_setAtticWindows(self, items):
        self.sendUpdate('setAtticWindows', [items])

    def b_setAtticWindows(self, items):
        self.setAtticWindows(items)
        self.d_setAtticWindows(items)

    def setDeletedItems(self, items):
        self.deletedItems = CatalogItemList(
            items, store=CatalogItem.Customization)

    def getDeletedItems(self):
        return self.deletedItems.getBlob()

    def d_setDeletedItems(self, items):
        self.sendUpdate('setDeletedItems', [items])

    def b_setDeletedItems(self, items):
        self.setDeletedItems(items)
        self.d_setDeletedItems(items)

    def setDirector(self, avId):
        self.director = avId

    def getDirector(self):
        return self.director

    def d_setDirector(self, avId):
        self.sendUpdate('setDirector', [avId])

    def b_setDirector(self, avId):
        self.setDirector(avId)
        self.d_setDirector(avId)
        taskMgr.remove(self.uniqueName('director-watch'))
        if avId:
            taskMgr.doMethodLater(
                1.0, self._watchDirector,
                self.uniqueName('director-watch'))

    # Director lifecycle -------------------------------------------------
    def suggestDirector(self, requestedAvId):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId:
            self.recordUnauthorized(avId, 'suggestDirector')
            return
        if requestedAvId not in (0, avId):
            self.recordUnauthorized(
                avId, 'suggestDirector for another avatar')
            return
        avatar = self.air.doId2do.get(avId)
        if requestedAvId and (
                avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId):
            self.recordUnauthorized(avId, 'suggestDirector from another zone')
            return
        if requestedAvId and self.director not in (0, avId):
            return
        self.b_setDirector(requestedAvId)
        self.notify.info(
            'Furniture director for interior %s is now %s' %
            (self.interiorId, requestedAvId))

    def avatarEnter(self):
        avId = self.air.getAvatarIdFromSender()
        if avId != self.ownerId:
            self.recordUnauthorized(avId, 'avatarEnter')
            return
        avatar = self.air.doId2do.get(avId)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.recordUnauthorized(avId, 'avatarEnter from another zone')
            return
        self.avatars.add(avId)

    def avatarExit(self):
        avId = self.air.getAvatarIdFromSender()
        self.avatars.discard(avId)
        if self.director == avId:
            self.b_setDirector(0)

    def canMoveItem(self, avId, item):
        avatar = self.air.doId2do.get(avId)
        return (
            avId == self.ownerId and
            avId == self.director and
            avatar is not None and
            getattr(avatar, 'zoneId', 0) == self.zoneId and
            item in self.items)

    # Furniture requests -------------------------------------------------
    def moveItemToAtticMessage(self, itemId, context):
        def mutate(state):
            itemIndex = self._itemIndex(itemId)
            item = state['room'].pop(itemIndex)
            state['attic'].append(item)
            return ToontownGlobals.FM_MovedItem, state, None
        self._handleMutation(
            'move-room-attic', 'moveItemToAtticResponse', context,
            (itemId,), mutate)

    def moveItemFromAtticMessage(self, index, x, y, z, h, p, r, context):
        def mutate(state):
            if len(state['room']) >= ToontownGlobals.MaxHouseItems:
                raise FurnitureError(ToontownGlobals.FM_RoomFull)
            item = self._indexed(state['attic'], index)
            del state['attic'][index]
            item.posHpr = (x, y, z, h, p, r)
            state['room'].append(item)
            return ToontownGlobals.FM_MovedItem, state, len(state['room']) - 1
        self._handleMutation(
            'move-attic-room', 'moveItemFromAtticResponse', context,
            (index, x, y, z, h, p, r), mutate, objectResponse=True)

    def deleteItemFromAtticMessage(self, blob, index, context):
        def mutate(state):
            item = self._indexed(state['attic'], index)
            self._validateBlob(item, blob)
            self._requireDeletable(item)
            del state['attic'][index]
            state['deleted'].append(item)
            return ToontownGlobals.FM_DeletedItem, state, None
        self._handleMutation(
            'delete-attic', 'deleteItemFromAtticResponse', context,
            (bytes(blob), index), mutate)

    def deleteItemFromRoomMessage(self, blob, itemId, context):
        def mutate(state):
            itemIndex = self._itemIndex(itemId)
            item = state['room'][itemIndex]
            self._validateBlob(item, blob)
            self._requireDeletable(item)
            del state['room'][itemIndex]
            state['deleted'].append(item)
            return ToontownGlobals.FM_DeletedItem, state, None
        self._handleMutation(
            'delete-room', 'deleteItemFromRoomResponse', context,
            (bytes(blob), itemId), mutate)

    def moveWallpaperFromAtticMessage(self, index, room, context):
        def mutate(state):
            if room not in (0, 1):
                raise FurnitureError(ToontownGlobals.FM_InvalidItem)
            item = self._indexed(state['atticWallpaper'], index)
            surfaceType = item.getSurfaceType()
            target = room * NUM_ST_TYPES + surfaceType
            if target >= len(state['wallpaper']):
                raise FurnitureError(ToontownGlobals.FM_InvalidItem)
            oldItem = state['wallpaper'][target]
            state['wallpaper'][target] = item
            state['atticWallpaper'][index] = oldItem
            return ToontownGlobals.FM_SwappedItem, state, None
        self._handleMutation(
            'apply-wallpaper', 'moveWallpaperFromAtticResponse', context,
            (index, room), mutate)

    def deleteWallpaperFromAtticMessage(self, blob, index, context):
        def mutate(state):
            item = self._indexed(state['atticWallpaper'], index)
            self._validateBlob(item, blob)
            del state['atticWallpaper'][index]
            state['deleted'].append(item)
            return ToontownGlobals.FM_DeletedItem, state, None
        self._handleMutation(
            'delete-wallpaper', 'deleteWallpaperFromAtticResponse', context,
            (bytes(blob), index), mutate)

    def moveWindowToAtticMessage(self, slot, context):
        def mutate(state):
            windowIndex = self._windowIndex(state['windows'], slot)
            item = state['windows'].pop(windowIndex)
            item.placement = None
            state['atticWindows'].append(item)
            return ToontownGlobals.FM_MovedItem, state, None
        self._handleMutation(
            'window-to-attic', 'moveWindowToAtticResponse', context,
            (slot,), mutate)

    def moveWindowFromAtticMessage(self, index, slot, context):
        def mutate(state):
            self._validateWindowSlot(slot)
            item = self._indexed(state['atticWindows'], index)
            del state['atticWindows'][index]
            retcode = ToontownGlobals.FM_MovedItem
            existing = self._findWindowIndex(state['windows'], slot)
            if existing is not None:
                oldItem = state['windows'].pop(existing)
                oldItem.placement = None
                state['atticWindows'].insert(index, oldItem)
                retcode = ToontownGlobals.FM_SwappedItem
            item.placement = slot
            state['windows'].append(item)
            return retcode, state, None
        self._handleMutation(
            'window-from-attic', 'moveWindowFromAtticResponse', context,
            (index, slot), mutate)

    def moveWindowMessage(self, fromSlot, toSlot, context):
        def mutate(state):
            self._validateWindowSlot(toSlot)
            sourceIndex = self._windowIndex(state['windows'], fromSlot)
            source = state['windows'][sourceIndex]
            retcode = ToontownGlobals.FM_MovedItem
            targetIndex = self._findWindowIndex(state['windows'], toSlot)
            if targetIndex is not None:
                target = state['windows'][targetIndex]
                target.placement = fromSlot
                retcode = ToontownGlobals.FM_SwappedItem
            source.placement = toSlot
            return retcode, state, None
        self._handleMutation(
            'move-window', 'moveWindowResponse', context,
            (fromSlot, toSlot), mutate)

    def deleteWindowFromAtticMessage(self, blob, index, context):
        def mutate(state):
            item = self._indexed(state['atticWindows'], index)
            self._validateBlob(item, blob)
            del state['atticWindows'][index]
            state['deleted'].append(item)
            return ToontownGlobals.FM_DeletedItem, state, None
        self._handleMutation(
            'delete-window', 'deleteWindowFromAtticResponse', context,
            (bytes(blob), index), mutate)

    def recoverDeletedItemMessage(self, blob, index, context):
        def mutate(state):
            if self._houseItemCount(state) >= ToontownGlobals.MaxHouseItems:
                raise FurnitureError(ToontownGlobals.FM_HouseFull)
            item = self._indexed(state['deleted'], index)
            self._validateBlob(item, blob)
            del state['deleted'][index]
            if hasattr(item, 'placement'):
                item.placement = None
                state['atticWindows'].append(item)
            elif hasattr(item, 'getSurfaceType'):
                state['atticWallpaper'].append(item)
            else:
                state['attic'].append(item)
            return ToontownGlobals.FM_RecoveredItem, state, None
        self._handleMutation(
            'recover-deleted', 'recoverDeletedItemResponse', context,
            (bytes(blob), index), mutate)

    # Position commits ---------------------------------------------------
    def persistItemPosition(self, itemObject):
        if itemObject not in self.items:
            return
        itemId = itemObject.doId
        if itemId in self._positionCommitQueued:
            # The authoritative item already contains the newest transform.
            # Remember that it changed while the current CAS was in flight so
            # the final placement can never be lost to request coalescing.
            self._positionCommitDirty.add(itemId)
            return
        self._positionCommitQueued.add(itemId)

        def operation(done):
            if itemObject not in self.items:
                self._positionCommitQueued.discard(itemId)
                done()
                return
            itemIndex = self.items.index(itemObject)
            state = self._decodeState(self._currentFields())
            state['room'][itemIndex].posHpr = itemObject.catalogItem.posHpr
            newFields = self._encodeState(state)

            def finish(success):
                self._positionCommitQueued.discard(itemId)
                if success:
                    self._positionCommitSucceeded(itemObject, newFields)
                done()
                if itemId in self._positionCommitDirty:
                    self._positionCommitDirty.discard(itemId)
                    self.persistItemPosition(itemObject)

            self._commitFields(
                newFields,
                lambda: finish(True),
                lambda: finish(False))

        self._queue.submit(operation)

    def _positionCommitSucceeded(self, itemObject, newFields):
        self._applyPersistedFields(newFields)

    # Atomic request plumbing -------------------------------------------
    def _handleMutation(self, action, responseName, context, fingerprint,
                        mutate, objectResponse=False):
        avId = self.air.getAvatarIdFromSender()
        key = (avId, action, int(context))
        status, response = self._responses.lookup(key, fingerprint)
        if status == 'replay':
            self.sendUpdateToAvatarId(avId, responseName, list(response))
            return
        if status == 'mismatch':
            self.recordUnauthorized(avId, 'reused furniture context')
            self._sendMutationResponse(
                avId, responseName, context,
                ToontownGlobals.FM_InvalidItem, objectResponse, 0)
            return

        def operation(done):
            # A duplicate may have waited behind the original transaction.
            replayStatus, replay = self._responses.lookup(key, fingerprint)
            if replayStatus == 'replay':
                self.sendUpdateToAvatarId(avId, responseName, list(replay))
                done()
                return
            authError = self._authorizationError(avId)
            if authError is not None:
                responseArgs = self._makeResponseArgs(
                    context, authError, objectResponse, 0)
                self._responses.remember(key, fingerprint, responseArgs)
                self.sendUpdateToAvatarId(
                    avId, responseName, list(responseArgs))
                done()
                return
            try:
                state = self._decodeState(self._currentFields())
                retcode, state, result = mutate(state)
                newFields = self._encodeState(state)
            except FurnitureError as error:
                responseArgs = self._makeResponseArgs(
                    context, error.code, objectResponse, 0)
                self._responses.remember(key, fingerprint, responseArgs)
                self.sendUpdateToAvatarId(
                    avId, responseName, list(responseArgs))
                done()
                return
            except Exception as error:
                self.notify.warning(
                    'Rejected malformed furniture operation %s from %s: %s' %
                    (action, avId, error))
                responseArgs = self._makeResponseArgs(
                    context, ToontownGlobals.FM_InvalidItem,
                    objectResponse, 0)
                self._responses.remember(key, fingerprint, responseArgs)
                self.sendUpdateToAvatarId(
                    avId, responseName, list(responseArgs))
                done()
                return

            def committed():
                self._applyCommittedState(newFields)
                objectId = 0
                if objectResponse and result is not None:
                    if 0 <= result < len(self.items):
                        objectId = self.items[result].doId
                responseArgs = self._makeResponseArgs(
                    context, retcode, objectResponse, objectId)
                self._responses.remember(key, fingerprint, responseArgs)
                self.sendUpdateToAvatarId(
                    avId, responseName, list(responseArgs))
                done()

            def conflicted():
                responseArgs = self._makeResponseArgs(
                    context, ToontownGlobals.FM_InvalidItem,
                    objectResponse, 0)
                self._responses.remember(key, fingerprint, responseArgs)
                self.sendUpdateToAvatarId(
                    avId, responseName, list(responseArgs))
                done()

            self._commitFields(newFields, committed, conflicted)

        self._queue.submit(operation)

    def _commitFields(self, newFields, success, failure):
        if self._transaction is None:
            self.notify.warning(
                'Cannot persist furniture for manager %s without a House' %
                self.doId)
            failure()
            return

        oldFields = dict(self._persistedFields)

        def finished(committed, conflicts):
            if committed:
                success()
                return
            self.notify.warning(
                'Furniture CAS conflict for house %s; reloading authoritative '
                'state' % self.house.doId)
            if conflicts and set(conflicts) == set(self.CONTENT_FIELDS):
                self._persistedFields = dict(conflicts)
                self._loadActiveState(
                    conflicts, allowFallback=False, generateItems=True)
            else:
                self._reloadHouseState()
            failure()

        self._transaction.commit(oldFields, newFields, finished)

    def _reloadHouseState(self):
        dclass = self.air.dclassesByName['DistributedHouseAI']

        def loaded(resultDclass, fields):
            if resultDclass != dclass or not fields:
                self.notify.warning(
                    'Could not reload House %s after furniture conflict' %
                    self.house.doId)
                return
            normalized = {
                name: fields[name][0]
                if isinstance(fields[name], (tuple, list)) else fields[name]
                for name in self.CONTENT_FIELDS
                if name in fields
            }
            if set(normalized) == set(self.CONTENT_FIELDS):
                self._persistedFields = normalized
                self._loadActiveState(
                    normalized, allowFallback=False, generateItems=True)

        self.air.dbInterface.queryObject(
            self.air.dbId, self.house.doId, loaded, dclass,
            self.CONTENT_FIELDS)

    # State encoding/application ----------------------------------------
    def _currentFields(self):
        room = CatalogItemList(
            [item.catalogItem for item in self.items],
            store=CatalogItem.Customization | CatalogItem.Location)
        return {
            'setAtticItems': self.getAtticItems(),
            'setInteriorItems': room.getBlob(),
            'setAtticWallpaper': self.getAtticWallpaper(),
            'setInteriorWallpaper': self.wallpaper.getBlob(),
            'setAtticWindows': self.getAtticWindows(),
            'setInteriorWindows': self.windows.getBlob(),
            'setDeletedItems': self.getDeletedItems(),
        }

    def _decodeState(self, fields):
        return {
            'attic': CatalogItemList(
                fields['setAtticItems'], store=CatalogItem.Customization),
            'room': CatalogItemList(
                fields['setInteriorItems'],
                store=CatalogItem.Customization | CatalogItem.Location),
            'atticWallpaper': CatalogItemList(
                fields['setAtticWallpaper'],
                store=CatalogItem.Customization),
            'wallpaper': CatalogItemList(
                fields['setInteriorWallpaper'],
                store=CatalogItem.Customization),
            'atticWindows': CatalogItemList(
                fields['setAtticWindows'],
                store=CatalogItem.Customization),
            'windows': CatalogItemList(
                fields['setInteriorWindows'],
                store=CatalogItem.Customization | CatalogItem.WindowPlacement),
            'deleted': CatalogItemList(
                fields['setDeletedItems'],
                store=CatalogItem.Customization),
        }

    def _encodeState(self, state):
        return {
            'setAtticItems': state['attic'].getBlob(),
            'setInteriorItems': state['room'].getBlob(),
            'setAtticWallpaper': state['atticWallpaper'].getBlob(),
            'setInteriorWallpaper': state['wallpaper'].getBlob(),
            'setAtticWindows': state['atticWindows'].getBlob(),
            'setInteriorWindows': state['windows'].getBlob(),
            'setDeletedItems': state['deleted'].getBlob(),
        }

    def _loadActiveState(self, fields, allowFallback, generateItems):
        state = self._decodeState(fields)
        fallback = False
        if allowFallback and self.ownerId:
            fallback |= self._addRequiredFurniture(state['room'])
            if len(state['wallpaper']) == 0:
                state['wallpaper'] = self._defaultWallpaper()
                fallback = True
        self._usingFallbackDefaults = fallback
        activeFields = self._encodeState(state)
        self.setAtticItems(activeFields['setAtticItems'])
        self.setAtticWallpaper(activeFields['setAtticWallpaper'])
        self.setAtticWindows(activeFields['setAtticWindows'])
        self.setDeletedItems(activeFields['setDeletedItems'])
        self.wallpaper = CatalogItemList(
            activeFields['setInteriorWallpaper'],
            store=CatalogItem.Customization)
        self.windows = CatalogItemList(
            activeFields['setInteriorWindows'],
            store=CatalogItem.Customization | CatalogItem.WindowPlacement)
        self._roomItems = CatalogItemList(
            activeFields['setInteriorItems'],
            store=CatalogItem.Customization | CatalogItem.Location)

        if self.house is not None:
            # Only persisted values belong on the activated House until an
            # owner action commits any in-memory compatibility defaults.
            self.house.applyContentFields(self._persistedFields)
        if self.interior is not None:
            self.interior.b_setWallpaper(self.wallpaper.getBlob())
            self.interior.b_setWindows(self.windows.getBlob())
        if generateItems:
            self._generateItems()
            self.d_setAtticItems(self.getAtticItems())
            self.d_setAtticWallpaper(self.getAtticWallpaper())
            self.d_setAtticWindows(self.getAtticWindows())
            self.d_setDeletedItems(self.getDeletedItems())

    def _applyPersistedFields(self, fields):
        self._persistedFields = dict(fields)
        self._usingFallbackDefaults = False
        if self.house is not None:
            self.house.applyContentFields(fields)

    def _applyCommittedState(self, fields):
        self._applyPersistedFields(fields)
        self._loadActiveState(fields, allowFallback=False, generateItems=True)

    def _generateItems(self):
        for item in self.items:
            item.destroy()
        self.items = []
        for catalogItem in self._roomItems:
            itemObject = self._makeItemObject(catalogItem)
            self.items.append(itemObject)
            if self.isGenerated():
                itemObject.generateWithRequired(self.zoneId)

    def _makeItemObject(self, item):
        flags = item.getFlags()
        if flags & FLTrunk:
            cls = DistributedTrunkAI
        elif flags & FLCloset:
            cls = DistributedClosetAI
        elif flags & FLBank:
            cls = DistributedBankAI
        elif flags & FLPhone:
            cls = DistributedPhoneAI
        else:
            cls = DistributedFurnitureItemAI
        return cls(self.air, self, item)

    def _addRequiredFurniture(self, room):
        flags = 0
        for item in room:
            flags |= item.getFlags()
        changed = False
        defaults = (
            (FLPhone, 1399, (-5, 0, 0, 0, 0, 0)),
            (FLBank, 1300, (5, 0, 0, 0, 0, 0)),
            (FLCloset, self._defaultClosetType(), (0, 0, 0, 0, 0, 0)),
        )
        for requiredFlag, furnitureType, posHpr in defaults:
            if not flags & requiredFlag:
                room.append(CatalogFurnitureItem(
                    furnitureType, posHpr=posHpr))
                changed = True
        return changed

    def _defaultClosetType(self):
        avatar = self.air.doId2do.get(self.ownerId)
        style = getattr(avatar, 'style', None)
        getGender = getattr(style, 'getGender', None)
        return 510 if getGender and getGender() == 'f' else 500

    def _defaultWallpaper(self):
        room = [
            CatalogWallpaperItem(1000, 0),
            CatalogMouldingItem(1000, 0),
            CatalogFlooringItem(1000, 0),
            CatalogWainscotingItem(1000, 0),
        ]
        return CatalogItemList(
            room + [
                CatalogWallpaperItem(1000, 0),
                CatalogMouldingItem(1000, 0),
                CatalogFlooringItem(1000, 0),
                CatalogWainscotingItem(1000, 0),
            ],
            store=CatalogItem.Customization)

    # Validation helpers -------------------------------------------------
    def _authorizationError(self, avId):
        if avId != self.ownerId:
            self.recordUnauthorized(avId, 'furniture mutation')
            return ToontownGlobals.FM_NotOwner
        if avId != self.director:
            return ToontownGlobals.FM_NotDirector
        avatar = self.air.doId2do.get(avId)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            self.recordUnauthorized(avId, 'furniture mutation from another zone')
            return ToontownGlobals.FM_NotDirector
        return None

    def _itemIndex(self, itemId):
        for index, item in enumerate(self.items):
            if item.doId == itemId:
                return index
        raise FurnitureError(ToontownGlobals.FM_InvalidItem)

    def _indexed(self, items, index):
        if index < 0 or index >= len(items):
            raise FurnitureError(ToontownGlobals.FM_InvalidIndex)
        return items[index]

    def _validateBlob(self, item, blob):
        expected = item.getBlob(store=CatalogItem.Customization)
        if bytes(blob) != bytes(expected):
            raise FurnitureError(ToontownGlobals.FM_InvalidItem)

    def _requireDeletable(self, item):
        if not item.isDeletable():
            raise FurnitureError(ToontownGlobals.FM_NondeletableItem)

    def _validateWindowSlot(self, slot):
        if slot < 0 or slot > 5:
            raise FurnitureError(ToontownGlobals.FM_HouseFull)

    def _findWindowIndex(self, windows, slot):
        for index, item in enumerate(windows):
            if item.placement == slot:
                return index
        return None

    def _windowIndex(self, windows, slot):
        index = self._findWindowIndex(windows, slot)
        if index is None:
            raise FurnitureError(ToontownGlobals.FM_InvalidIndex)
        return index

    def _houseItemCount(self, state):
        return (
            len(state['attic']) + len(state['room']) +
            len(state['atticWallpaper']) + len(state['atticWindows']))

    def _makeResponseArgs(self, context, retcode, objectResponse, objectId):
        if objectResponse:
            return (retcode, objectId, context)
        return (retcode, context)

    def _sendMutationResponse(self, avId, responseName, context, retcode,
                              objectResponse, objectId):
        self.sendUpdateToAvatarId(
            avId, responseName,
            list(self._makeResponseArgs(
                context, retcode, objectResponse, objectId)))

    def recordUnauthorized(self, avId, action):
        self.air.writeServerEvent(
            'suspicious', avId,
            'Tried furniture action %s on manager %s owned by %s' %
            (action, self.doId, self.ownerId))

    def _watchDirector(self, task):
        avatar = self.air.doId2do.get(self.director)
        if avatar is None or getattr(avatar, 'zoneId', 0) != self.zoneId:
            staleDirector = self.director
            self.b_setDirector(0)
            self.notify.info(
                'Released stale furniture director %s from interior %s' %
                (staleDirector, self.interiorId))
            return Task.done
        task.delayTime = 1.0
        return Task.again

    def delete(self):
        taskMgr.remove(self.uniqueName('director-watch'))
        for item in self.items:
            item.destroy()
        self.items = []
        DistributedObjectAI.delete(self)
