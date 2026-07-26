from panda3d.core import *
from direct.distributed import DistributedSmoothNodeAI
from toontown.toonbase import ToontownGlobals
from otp.otpbase import OTPGlobals
from direct.fsm import FSM
from direct.task import Task
import math
import time

class DistributedCashbotBossObjectAI(DistributedSmoothNodeAI.DistributedSmoothNodeAI, FSM.FSM):
    wantsWatchDrift = 1

    def __init__(self, air, boss):
        DistributedSmoothNodeAI.DistributedSmoothNodeAI.__init__(self, air)
        FSM.FSM.__init__(self, 'DistributedCashbotBossObjectAI')
        self.boss = boss
        self.reparentTo(self.boss.scene)
        self.avId = 0
        self.craneId = 0
        self._movementLastAt = time.monotonic()
        self._movementCredit = 45.0

    def _clientSender(self):
        return int(self.air.getAvatarIdFromSender() or 0)

    def _acceptClientPosition(self, candidate):
        avId = self._clientSender()
        if not avId:
            return True
        if (
                avId != self.avId or
                avId not in self.boss.involvedToons or
                self.state not in (
                    'Grabbed', 'Dropped', 'SlidingFloor', 'WaitFree')):
            self.air.writeServerEvent(
                'suspicious', avId,
                'unauthorized Cashbot boss object transform')
            return False
        try:
            values = tuple(float(value) for value in candidate)
        except (TypeError, ValueError):
            return False
        if (
                len(values) != 3 or
                not all(math.isfinite(value) for value in values) or
                abs(values[0]) > 500.0 or
                abs(values[1]) > 500.0 or
                values[2] < -50.0 or
                values[2] > 300.0):
            self.air.writeServerEvent(
                'suspicious', avId,
                'invalid Cashbot boss object transform')
            return False
        now = time.monotonic()
        elapsed = max(0.0, min(now - self._movementLastAt, 1.0))
        self._movementLastAt = now
        self._movementCredit = min(
            45.0, self._movementCredit + elapsed * 120.0)
        current = self.getPos()
        distance = math.sqrt(sum(
            (values[index] - current[index]) ** 2
            for index in range(3)))
        if distance > self._movementCredit + 0.01:
            self.air.writeServerEvent(
                'suspicious', avId,
                'Cashbot boss object movement envelope exceeded')
            self.sendUpdate('setPosHpr', [
                current[0], current[1], current[2],
                self.getH(), self.getP(), self.getR()])
            return False
        self._movementCredit -= distance
        return True

    def _acceptClientAngle(self, value):
        avId = self._clientSender()
        if not avId:
            return True
        if avId != self.avId or avId not in self.boss.involvedToons:
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    # Cashbot boss objects use client-side physics for presentation. These
    # setters keep that simulation inside a server-time envelope and bind it
    # to the Toon who actually controls the crane/object.
    def setX(self, x):
        if self._acceptClientPosition((x, self.getY(), self.getZ())):
            NodePath.setX(self, x)

    def setY(self, y):
        if self._acceptClientPosition((self.getX(), y, self.getZ())):
            NodePath.setY(self, y)

    def setZ(self, z):
        if self._acceptClientPosition((self.getX(), self.getY(), z)):
            NodePath.setZ(self, z)

    def setH(self, h):
        if self._acceptClientAngle(h):
            NodePath.setH(self, h)

    def setP(self, p):
        if self._acceptClientAngle(p):
            NodePath.setP(self, p)

    def setR(self, r):
        if self._acceptClientAngle(r):
            NodePath.setR(self, r)

    def setComponentX(self, x):
        self.setX(x)

    def setComponentY(self, y):
        self.setY(y)

    def setComponentZ(self, z):
        self.setZ(z)

    def setComponentH(self, h):
        self.setH(h)

    def setComponentP(self, p):
        self.setP(p)

    def setComponentR(self, r):
        self.setR(r)

    def setComponentL(self, location):
        pass

    def setComponentT(self, timestamp):
        pass

    def cleanup(self):
        self.detachNode()
        self.stopWaitFree()

    def delete(self):
        self.cleanup()
        DistributedSmoothNodeAI.DistributedSmoothNodeAI.delete(self)

    def startWaitFree(self, delayTime):
        waitFreeEvent = self.uniqueName('waitFree')
        taskMgr.remove(waitFreeEvent)
        taskMgr.doMethodLater(delayTime, self.doFree, waitFreeEvent)

    def stopWaitFree(self):
        waitFreeEvent = self.uniqueName('waitFree')
        taskMgr.remove(waitFreeEvent)

    def doFree(self, task):
        if not self.isDeleted():
            self.demand('Free')
            p = self.getPos()
            h = self.getH()
            self.d_setPosHpr(p[0], p[1], 0, h, 0, 0)
        return Task.done

    def getBossCogId(self):
        return self.boss.doId

    def d_setObjectState(self, state, avId, craneId):
        self.sendUpdate('setObjectState', [state, avId, craneId])

    def requestGrab(self):
        avId = self.air.getAvatarIdFromSender()
        from toontown.authority.ServerActionGuardsAI import (
            allowAction, requireInteraction,
        )
        if not allowAction(
                self.air, avId, 'boss.cashbot.object.grab',
                rate=1.0, burst=2.0):
            return
        if self.state != 'Grabbed' and self.state != 'Off':
            craneId, objectId = self.__getCraneAndObject(avId)
            if craneId != 0 and objectId == 0:
                avatar = self.air.doId2do.get(avId)
                crane = self.air.doId2do.get(craneId)
                if (
                        crane is None or
                        not requireInteraction(
                            self.air, avId, avatar,
                            targetPosition=crane.goonShield,
                            maximum=35.0,
                            action='boss.cashbot.object.grab')):
                    return
                self.demand('Grabbed', avId, craneId)
                return
        self.sendUpdateToAvatarId(avId, 'rejectGrab', [])

    def requestDrop(self):
        avId = self.air.getAvatarIdFromSender()
        from toontown.authority.ServerActionGuardsAI import allowAction
        if (
                allowAction(
                    self.air, avId, 'boss.cashbot.object.drop',
                    rate=1.5, burst=2.0) and
                avId == self.avId and self.state == 'Grabbed'):
            craneId, objectId = self.__getCraneAndObject(avId)
            if craneId != 0 and objectId == self.doId:
                self.demand('Dropped', avId, craneId)

    def hitFloor(self):
        avId = self.air.getAvatarIdFromSender()
        from toontown.authority.ServerActionGuardsAI import allowAction
        if (
                allowAction(
                    self.air, avId, 'boss.cashbot.object.floor',
                    rate=1.0, burst=2.0) and
                avId == self.avId and self.state == 'Dropped'):
            self.demand('SlidingFloor', avId)

    def requestFree(self, x, y, z, h):
        avId = self.air.getAvatarIdFromSender()
        from toontown.authority.ServerActionGuardsAI import allowAction
        if (
                allowAction(
                    self.air, avId, 'boss.cashbot.object.free',
                    rate=0.5, burst=1.0) and
                avId == self.avId and
                self._acceptClientPosition((x, y, 0)) and
                self._acceptClientAngle(h)):
            NodePath.setPosHpr(self, x, y, 0, h, 0, 0)
            self.demand('WaitFree')

    def hitBoss(self, impact):
        pass

    def removeToon(self, avId):
        if avId == self.avId:
            self.doFree(None)
        return

    def __getCraneAndObject(self, avId):
        if self.boss and self.boss.cranes != None:
            for crane in self.boss.cranes:
                if crane.avId == avId:
                    return (crane.doId, crane.objectId)

        return (0, 0)

    def __setCraneObject(self, craneId, objectId):
        if self.air:
            crane = self.air.doId2do.get(craneId)
            if crane:
                crane.objectId = objectId

    def enterGrabbed(self, avId, craneId):
        self.avId = avId
        self.craneId = craneId
        self.__setCraneObject(self.craneId, self.doId)
        self.d_setObjectState('G', avId, craneId)

    def exitGrabbed(self):
        self.__setCraneObject(self.craneId, 0)

    def enterDropped(self, avId, craneId):
        self.avId = avId
        self.craneId = craneId
        self.d_setObjectState('D', avId, craneId)
        self.startWaitFree(10)

    def exitDropped(self):
        self.stopWaitFree()

    def enterSlidingFloor(self, avId):
        self.avId = avId
        self.d_setObjectState('s', avId, 0)
        if self.wantsWatchDrift:
            self.startWaitFree(5)

    def exitSlidingFloor(self):
        self.stopWaitFree()

    def enterWaitFree(self):
        self.avId = 0
        self.craneId = 0
        self.startWaitFree(1)

    def exitWaitFree(self):
        self.stopWaitFree()

    def enterFree(self):
        self.avId = 0
        self.craneId = 0
        self.d_setObjectState('F', 0, 0)

    def exitFree(self):
        pass
