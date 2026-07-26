import math
import re
import time
import unicodedata

from direct.showbase import GarbageReport
from otp.ai.AIBaseGlobal import *
from otp.avatar import DistributedAvatarAI
from otp.avatar import PlayerBase
from otp.distributed.ClsendTracker import ClsendTracker
from otp.otpbase import OTPGlobals

class DistributedPlayerAI(DistributedAvatarAI.DistributedAvatarAI, PlayerBase.PlayerBase, ClsendTracker):

    def __init__(self, air):
        DistributedAvatarAI.DistributedAvatarAI.__init__(self, air)
        PlayerBase.PlayerBase.__init__(self)
        ClsendTracker.__init__(self)
        self.friendsList = []
        self.DISLname = ''
        self.DISLid = 0
        self.accessLevel = 0
        # Smooth transforms are client-originated.  Keep a server-side movement
        # budget so sending many tiny updates cannot turn the client into an
        # authoritative teleporter.
        self._movementLastAt = time.monotonic()
        self._movementCredit = 20.0
        self._verticalCredit = 12.0
        self._movementRejects = []

    if __dev__:

        def generate(self):
            self._sentExitServerEvent = False
            DistributedAvatarAI.DistributedAvatarAI.generate(self)

    def announceGenerate(self):
        DistributedAvatarAI.DistributedAvatarAI.announceGenerate(self)
        ClsendTracker.announceGenerate(self)
        self._doPlayerEnter()

    def _announceArrival(self):
        self.sendUpdate('arrivedOnDistrict', [self.air.districtId])

    def _announceExit(self):
        self.sendUpdate('arrivedOnDistrict', [0])

    def _sendExitServerEvent(self):
        self.air.writeServerEvent('avatarExit', self.doId, '')
        if __dev__:
            self._sentExitServerEvent = True

    def delete(self):
        if __dev__:
            del self._sentExitServerEvent
        self._doPlayerExit()
        ClsendTracker.destroy(self)
        if __dev__:
            GarbageReport.checkForGarbageLeaks()
        DistributedAvatarAI.DistributedAvatarAI.delete(self)

    def isPlayerControlled(self):
        return True

    def setLocation(self, parentId, zoneId):
        DistributedAvatarAI.DistributedAvatarAI.setLocation(self, parentId, zoneId)
        if self.isPlayerControlled():
            if not self.air._isValidPlayerLocation(parentId, zoneId):
                self.notify.info('booting player %s for doing setLocation to (%s, %s)' % (self.doId, parentId, zoneId))
                self.air.writeServerEvent('suspicious', self.doId, 'invalid setLocation: (%s, %s)' % (parentId, zoneId))
                self.requestDelete()
        self._resetMovementBudget()

    def _resetMovementBudget(self):
        self._movementLastAt = time.monotonic()
        self._movementCredit = 20.0
        self._verticalCredit = 12.0

    def _movementCandidate(self, x=None, y=None, z=None):
        current = self.getPos()
        return (
            current[0] if x is None else x,
            current[1] if y is None else y,
            current[2] if z is None else z,
        )

    def _acceptMovement(self, candidate):
        try:
            values = tuple(float(value) for value in candidate)
        except (TypeError, ValueError):
            self._rejectMovement('non-numeric transform')
            return False
        if not all(math.isfinite(value) for value in values):
            self._rejectMovement('non-finite transform')
            return False
        if (
                abs(values[0]) > 10000.0 or
                abs(values[1]) > 10000.0 or
                values[2] < -500.0 or
                values[2] > 2000.0):
            self._rejectMovement('transform outside world bounds')
            return False
        current = self.getPos()
        now = time.monotonic()
        elapsed = max(0.0, min(now - self._movementLastAt, 2.0))
        self._movementLastAt = now
        # Normal walking is roughly 16 units/s and browser sprinting is 1.5x.
        # A 30 units/s refill leaves headroom above the 24 units/s sprint while
        # remaining too small to sustain a materially faster movement hack.
        # Capped credits tolerate packet bunching without accumulating travel.
        self._movementCredit = min(
            20.0, self._movementCredit + elapsed * 30.0)
        self._verticalCredit = min(
            12.0, self._verticalCredit + elapsed * 24.0)
        dx = values[0] - current[0]
        dy = values[1] - current[1]
        dz = values[2] - current[2]
        horizontal = math.sqrt(dx * dx + dy * dy)
        vertical = abs(dz)
        if (
                horizontal > self._movementCredit + 0.01 or
                vertical > self._verticalCredit + 0.01):
            self._rejectMovement(
                'movement envelope exceeded h=%.2f/%.2f v=%.2f/%.2f' %
                (horizontal, self._movementCredit,
                 vertical, self._verticalCredit))
            return False
        self._movementCredit = max(0.0, self._movementCredit - horizontal)
        self._verticalCredit = max(0.0, self._verticalCredit - vertical)
        return True

    def _rejectMovement(self, reason):
        now = time.monotonic()
        self._movementRejects = [
            timestamp for timestamp in self._movementRejects
            if now - timestamp <= 30.0]
        self._movementRejects.append(now)
        pos = self.getPos()
        hpr = self.getHpr()
        # Astron may already have relayed the ownsend field, so immediately
        # replace it with the last authoritative server transform.
        self.sendUpdate('setSmPosHpr', [
            pos[0], pos[1], pos[2], hpr[0], hpr[1], hpr[2], 0])
        self.air.writeServerEvent(
            'suspicious', self.doId, 'movement: %s' % reason)
        if len(self._movementRejects) >= 8:
            self.notify.warning(
                'Avatar %s repeatedly violated the movement envelope.' %
                self.doId)
        if len(self._movementRejects) == 12:
            self.air.writeServerEvent(
                'suspicious', self.doId,
                'movement: disconnecting after repeated violations')
            self.requestDelete()

    @staticmethod
    def _finiteAngles(*values):
        try:
            return all(math.isfinite(float(value)) for value in values)
        except (TypeError, ValueError):
            return False

    # DC smooth-transform entry points.  These intentionally do not trust the
    # client timestamp; only server monotonic time replenishes movement credit.
    def setSmStop(self, t=None):
        pass

    def setSmH(self, h, t=None):
        if self._finiteAngles(h):
            self.setH(h)

    def setSmZ(self, z, t=None):
        candidate = self._movementCandidate(z=z)
        if self._acceptMovement(candidate):
            self.setZ(z)

    def setSmXY(self, x, y, t=None):
        candidate = self._movementCandidate(x=x, y=y)
        if self._acceptMovement(candidate):
            self.setX(x)
            self.setY(y)

    def setSmXZ(self, x, z, t=None):
        candidate = self._movementCandidate(x=x, z=z)
        if self._acceptMovement(candidate):
            self.setX(x)
            self.setZ(z)

    def setSmPos(self, x, y, z, t=None):
        candidate = (x, y, z)
        if self._acceptMovement(candidate):
            self.setPos(x, y, z)

    def setSmHpr(self, h, p, r, t=None):
        if self._finiteAngles(h, p, r):
            self.setHpr(h, p, r)

    def setSmXYH(self, x, y, h, t=None):
        candidate = self._movementCandidate(x=x, y=y)
        if self._finiteAngles(h) and self._acceptMovement(candidate):
            self.setX(x)
            self.setY(y)
            self.setH(h)

    def setSmXYZH(self, x, y, z, h, t=None):
        if self._finiteAngles(h) and self._acceptMovement((x, y, z)):
            self.setPos(x, y, z)
            self.setH(h)

    def setSmPosHpr(self, x, y, z, h, p, r, t=None):
        if (
                self._finiteAngles(h, p, r) and
                self._acceptMovement((x, y, z))):
            self.setPosHpr(x, y, z, h, p, r)

    def setSmPosHprL(self, location, x, y, z, h, p, r, t=None):
        # The legacy location component is a smoothing token, not authority to
        # change this DistributedObject's parent/zone. The base implementation
        # also ignores it.
        self.setSmPosHpr(x, y, z, h, p, r, t)

    def setComponentX(self, x):
        self.setSmXY(x, self.getY())

    def setComponentY(self, y):
        self.setSmXY(self.getX(), y)

    def setComponentZ(self, z):
        self.setSmZ(z)

    def setComponentH(self, h):
        self.setSmH(h)

    def setComponentP(self, p):
        if self._finiteAngles(p):
            self.setP(p)

    def setComponentR(self, r):
        if self._finiteAngles(r):
            self.setR(r)

    def setComponentL(self, location):
        pass

    def setComponentT(self, timestamp):
        pass

    def _doPlayerEnter(self):
        self.incrementPopulation()
        self._announceArrival()

    def _doPlayerExit(self):
        self._announceExit()
        self.decrementPopulation()

    def incrementPopulation(self):
        self.air.incrementPopulation()

    def decrementPopulation(self):
        simbase.air.decrementPopulation()

    def b_setChat(self, chatString, chatFlags):
        self.setChat(chatString, chatFlags)
        self.d_setChat(chatString, chatFlags)

    def d_setChat(self, chatString, chatFlags):
        self.sendUpdate('setChat', [chatString, chatFlags])

    def setChat(self, chatString, chatFlags):
        pass

    def requestTalk(self, fromAV, fromAC, avatarName, chat, mods, flags):
        """Validate public chat before broadcasting it to the zone."""
        from toontown.authority.ServerActionGuardsAI import allowAction
        if not allowAction(
                self.air, self.doId, 'chat.public',
                rate=0.8, burst=4.0):
            return
        message = self._moderatePublicChat(chat)
        if message is None:
            self.air.writeServerEvent(
                'moderation', self.doId,
                'blocked public chat without recording message content')
            return
        safeMods = []
        if isinstance(mods, (tuple, list)) and len(mods) <= 32:
            for modification in mods:
                if (
                        isinstance(modification, (tuple, list)) and
                        len(modification) == 2):
                    try:
                        offset = int(modification[0])
                        size = int(modification[1])
                    except (TypeError, ValueError):
                        continue
                    if (
                            0 <= offset <= len(message) and
                            0 <= size <= len(message) - offset):
                        safeMods.append((offset, size))
        safeFlags = int(flags) & 0x3f
        self.sendUpdate('setTalk', [
            int(self.doId),
            int(getattr(self, 'DISLid', 0) or 0),
            str(self.getName())[:256],
            message,
            safeMods,
            safeFlags,
        ])

    @staticmethod
    def _moderatePublicChat(chat):
        if not isinstance(chat, str):
            return None
        message = unicodedata.normalize('NFKC', chat)
        message = ''.join(
            character for character in message
            if character in '\t ' or
            unicodedata.category(character)[0] != 'C')
        message = re.sub(r'\s+', ' ', message).strip()
        if not message or len(message) > 200:
            return None
        lowered = message.casefold()
        if (
                re.search(r'(?:https?://|www\.|\b[a-z0-9._%+-]+@'
                          r'[a-z0-9.-]+\.[a-z]{2,}\b)', lowered) or
                re.search(r'(?<!\d)(?:\d[ .()-]*){7,}(?!\d)', lowered)):
            return None
        blocked = (
            'fuck', 'shit', 'bitch', 'cunt', 'nigger', 'faggot',
            'kys', 'kill yourself',
        )
        words = re.findall(r"[a-z0-9']+", lowered)
        if any(term in lowered for term in blocked if ' ' in term):
            return None
        if any(word in blocked for word in words):
            return None
        return message

    def d_setMaxHp(self, maxHp):
        DistributedAvatarAI.DistributedAvatarAI.d_setMaxHp(self, maxHp)
        self.air.writeServerEvent('setMaxHp', self.doId, '%s' % maxHp)

    def d_setSystemMessage(self, aboutId, chatString):
        self.sendUpdate('setSystemMessage', [aboutId, chatString])

    def d_setCommonChatFlags(self, flags):
        self.sendUpdate('setCommonChatFlags', [flags])

    def setCommonChatFlags(self, flags):
        pass

    def d_friendsNotify(self, avId, status):
        self.sendUpdate('friendsNotify', [avId, status])

    def friendsNotify(self, avId, status):
        pass

    def setAccountName(self, accountName):
        self.accountName = accountName

    def getAccountName(self):
        return self.accountName

    def setDISLid(self, id):
        self.DISLid = id

    def setAccessLevel(self, accessLevel):
        self.accessLevel = accessLevel

    def getAccessLevel(self):
        return self.accessLevel

    def d_setFriendsList(self, friendsList):
        self.sendUpdate('setFriendsList', [friendsList])

    def setFriendsList(self, friendsList):
        self.friendsList = friendsList
        self.notify.debug('setting friends list to %s' % self.friendsList)

    def getFriendsList(self):
        return self.friendsList

    def extendFriendsList(self, friendId, friendCode):
        for i in range(len(self.friendsList)):
            friendPair = self.friendsList[i]
            if friendPair[0] == friendId:
                self.friendsList[i] = (friendId, friendCode)
                return

        self.friendsList.append((friendId, friendCode))
