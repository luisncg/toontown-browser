from otp.ai.AIBaseGlobal import *
from panda3d.core import *
from . import DistributedToonAI
from direct.fsm import ClassicFSM
from direct.fsm import State
from direct.distributed import ClockDelta
from toontown.toonbase import ToontownGlobals
from . import NPCToons
from direct.task import Task
from toontown.quest import Quests

class DistributedNPCToonBaseAI(DistributedToonAI.DistributedToonAI):

    def __init__(self, air, npcId, questCallback = None):
        DistributedToonAI.DistributedToonAI.__init__(self, air)
        self.air = air
        self.npcId = npcId
        self.busy = 0
        self.questCallback = questCallback
        self.givesQuests = 1

    def delete(self):
        taskMgr.remove(self.uniqueName('clearMovie'))
        DistributedToonAI.DistributedToonAI.delete(self)

    def _doPlayerEnter(self):
        pass

    def _doPlayerExit(self):
        pass

    def _announceArrival(self):
        pass

    def isPlayerControlled(self):
        return False

    def getHq(self):
        return 0

    def getTailor(self):
        return 0

    def getGivesQuests(self):
        return self.givesQuests

    def avatarEnter(self):
        pass

    def canAvatarInteract(self, avId):
        avatar = self.air.doId2do.get(avId)
        from toontown.authority.BrowserAuthorityManagerAI import (
            consumeProtectedTransition,
        )
        if not consumeProtectedTransition(
                self.air, avId, 'npc.interact',
                {'npc': self.doId, 'zone': self.zoneId}):
            self.freeAvatar(avId)
            return False
        from toontown.authority.ServerActionGuardsAI import requireInteraction
        allowed = requireInteraction(
            self.air, avId, avatar, target=self,
            maximum=42.0, action='npc.interact')
        if not allowed:
            self.freeAvatar(avId)
        return allowed

    def isBusy(self):
        return self.busy > 0

    def getNpcId(self):
        return self.npcId

    def freeAvatar(self, avId):
        self.sendUpdateToAvatarId(avId, 'freeAvatar', [])

    def setPositionIndex(self, posIndex):
        self.posIndex = posIndex

    def getPositionIndex(self):
        return self.posIndex
