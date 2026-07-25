import math
import random

from direct.directnotify import DirectNotifyGlobal
from direct.distributed.ClockDelta import globalClockDelta
from direct.distributed.DistributedNodeAI import DistributedNodeAI
from direct.task.TaskManagerGlobal import taskMgr
from toontown.fishing import FishingTargetGlobals


class DistributedFishingTargetAI(DistributedNodeAI):
    notify = DirectNotifyGlobal.directNotify.newCategory(
        'DistributedFishingTargetAI')

    def __init__(self, air):
        DistributedNodeAI.__init__(self, air)
        self.pondDoId = 0
        self.stateIndex = FishingTargetGlobals.MOVING
        self.angle = 0.0
        self.targetRadius = 0.0
        self.travelTime = 0.0
        self.centerPoint = (0, 0, 0)

    def generate(self):
        DistributedNodeAI.generate(self)
        pond = self.air.doId2do.get(self.pondDoId)
        if pond is None:
            self.notify.warning(
                'Fishing target %s has no pond %s' %
                (self.doId, self.pondDoId))
            return
        pond.addTarget(self)
        self.centerPoint = FishingTargetGlobals.getTargetCenter(
            pond.getArea())
        self._chooseDestination()

    def delete(self):
        taskMgr.remove(self.uniqueName('move-target'))
        pond = self.air.doId2do.get(self.pondDoId)
        if pond is not None:
            pond.removeTarget(self)
        DistributedNodeAI.delete(self)

    def setPondDoId(self, pondDoId):
        self.pondDoId = pondDoId

    def getPondDoId(self):
        return self.pondDoId

    def setState(self, stateIndex, angle, radius, travelTime, timeStamp):
        self.stateIndex = stateIndex
        self.angle = angle
        self.targetRadius = radius
        self.travelTime = travelTime

    def getState(self):
        return [
            self.stateIndex, self.angle, self.targetRadius,
            self.travelTime, globalClockDelta.getRealNetworkTime(bits=16)]

    def _chooseDestination(self, task=None):
        pond = self.air.doId2do.get(self.pondDoId)
        if pond is None:
            return task.done if task is not None else None
        self.b_setPosHpr(
            self.targetRadius * math.cos(self.angle) + self.centerPoint[0],
            self.targetRadius * math.sin(self.angle) + self.centerPoint[1],
            self.centerPoint[2], 0, 0, 0)
        self.stateIndex = FishingTargetGlobals.MOVING
        self.angle = random.uniform(0.0, math.pi * 2.0)
        self.targetRadius = random.uniform(
            0.0, FishingTargetGlobals.getTargetRadius(pond.getArea()))
        self.travelTime = random.uniform(5.0, 10.0)
        self.sendUpdate('setState', self.getState())
        taskMgr.doMethodLater(
            self.travelTime + random.uniform(2.5, 5.0),
            self._chooseDestination, self.uniqueName('move-target'))
        return task.done if task is not None else None
