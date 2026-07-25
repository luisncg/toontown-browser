"""Native state-machine checks for Cog Mega-Building boarding."""

import builtins
import unittest
from types import SimpleNamespace

from panda3d.core import loadPrcFile

loadPrcFile('etc/Configrc.prc')


class _Game:
    name = 'toontown'
    process = 'server'


builtins.game = _Game
import otp.ai.AIBaseGlobal  # noqa: E402,F401 - installs server globals

from direct.task.TaskManagerGlobal import taskMgr  # noqa: E402
from toontown.building import MegaBuildingGlobals as Mega  # noqa: E402
from toontown.building.DistributedElevatorExtAI import (  # noqa: E402
    DistributedElevatorExtAI,
)


class MegaBuildingNativeTests(unittest.TestCase):
    def _elevator(self):
        elevator = object.__new__(DistributedElevatorExtAI)
        elevator.doId = 991234
        elevator.megaState = Mega.MEGA_STATE_VOTING
        elevator.megaVotes = set()
        elevator.megaVoters = [101, 102, 103, 104]
        elevator.pendingMegaJoins = set()
        elevator.megaStateDuration = 0
        elevator.megaStateTimestamp = 0
        elevator.megaTrip = False
        elevator.sendUpdate = lambda *args: None
        return elevator

    def tearDown(self):
        for name in ('mega-vote-timeout', 'mega-recruit-timeout',
                     'mega-regular-timeout', 'mega-full-departure'):
            taskMgr.remove('DistributedElevatorExtAI-991234-%s' % name)

    def test_all_four_yes_votes_are_required(self):
        elevator = self._elevator()
        sender = [101]
        elevator.air = SimpleNamespace(
            getAvatarIdFromSender=lambda: sender[0])
        approved = []
        elevator._approveMegaVote = lambda: approved.append(True)

        for toonId in (101, 102, 103):
            sender[0] = toonId
            DistributedElevatorExtAI.requestMegaVote(elevator, True)
            self.assertEqual(approved, [])
        sender[0] = 104
        DistributedElevatorExtAI.requestMegaVote(elevator, True)

        self.assertEqual(elevator.megaVotes, {101, 102, 103, 104})
        self.assertEqual(approved, [True])

    def test_one_no_vote_immediately_selects_regular(self):
        elevator = self._elevator()
        elevator.air = SimpleNamespace(getAvatarIdFromSender=lambda: 102)
        fallbacks = []
        elevator._beginRegularFallback = lambda: fallbacks.append(True)

        DistributedElevatorExtAI.requestMegaVote(elevator, False)

        self.assertEqual(fallbacks, [True])
        self.assertEqual(elevator.megaVotes, set())

    def test_unanimous_vote_opens_recruiting_state(self):
        elevator = self._elevator()
        updates = []
        elevator.countFullSeats = lambda: 4
        elevator.sendUpdate = lambda field, values: updates.append(
            (field, values))

        DistributedElevatorExtAI._approveMegaVote(elevator)

        self.assertTrue(elevator.megaTrip)
        self.assertEqual(elevator.megaState, Mega.MEGA_STATE_RECRUITING)
        self.assertEqual(elevator.megaStateDuration,
                         int(Mega.MEGA_RECRUIT_SECONDS))
        self.assertEqual(updates[-1][0], 'setMegaState')

    def test_sub_four_party_downgrades_while_doors_close(self):
        elevator = self._elevator()
        elevator.megaTrip = True
        elevator.seats = [101, 102, 103, None, None, None, None, None]
        elevator.countFullSeats = lambda: 3
        created = []
        cleared = []
        states = []
        elevator._createInterior = lambda: created.append(True)
        elevator.clearFullNow = lambda seatIndex: cleared.append(seatIndex)
        elevator.fsm = SimpleNamespace(request=lambda state: states.append(state))

        DistributedElevatorExtAI.elevatorClosed(elevator)

        self.assertFalse(elevator.megaTrip)
        self.assertEqual(created, [True])
        self.assertEqual(cleared, [0, 1, 2])
        self.assertEqual(states, ['closed'])


if __name__ == '__main__':
    unittest.main()
