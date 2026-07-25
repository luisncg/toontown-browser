"""Contracts for browser-safe NPC quest movie setup and reward handling."""

import builtins
from pathlib import Path
import unittest
from unittest import mock

from panda3d.core import Filename, get_model_path, load_prc_file_data


load_prc_file_data(
    '',
    'window-type none\n'
    'audio-library-name null\n'
    'default-directnotify-level warning',
)
get_model_path().prepend_directory(Filename.from_os_specific('resources'))
builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.showbase.ShowBase import ShowBase  # noqa: E402


base = ShowBase(windowType='none')

from toontown.quest import QuestParser  # noqa: E402
from toontown.quest.Quests import MaxHpReward  # noqa: E402
from toontown.toon import Toon  # noqa: E402
from toontown.toon.DistributedNPCSpecialQuestGiverAI import (  # noqa: E402
    DistributedNPCSpecialQuestGiverAI,
)
from toontown.toon.DistributedNPCToonAI import DistributedNPCToonAI  # noqa: E402
from toontown.toon.ToonHead import getLookAtTiming  # noqa: E402


class FakeAvatar:

    def __init__(self, max_hp=15):
        self.max_hp = max_hp
        self.max_hp_updates = []
        self.toon_up_calls = []

    def getMaxHp(self):
        return self.max_hp

    def b_setMaxHp(self, max_hp):
        self.max_hp = max_hp
        self.max_hp_updates.append(max_hp)

    def toonUp(self, amount):
        self.toon_up_calls.append(amount)


class FakeTagNode:

    def setActive(self, active):
        self.active = active


class FakeToonHeadFrame:

    def __init__(self, toon):
        self.toon = toon
        self.tag1Node = FakeTagNode()

    def hide(self):
        pass

    def show(self):
        pass

    def setPos(self, *position):
        pass

    def setScale(self, scale):
        pass

    def destroy(self):
        pass


class FakeAnimationControl:

    def __init__(self):
        self.play_rates = []
        self.play_calls = 0
        self.loop_calls = []

    def setPlayRate(self, play_rate):
        self.play_rates.append(play_rate)

    def play(self):
        self.play_calls += 1

    def loop(self, restart):
        self.loop_calls.append(restart)

    def getNumFrames(self):
        return 48

    def getFrameRate(self):
        return 24.0


class FakeActor:

    def __init__(self, controls):
        self.controls = controls
        self.control_lookups = []

    def getAnimControls(self, anim_name):
        self.control_lookups.append(anim_name)
        return self.controls


class FakeBatchActor:

    def __init__(self):
        self.control_lookups = []
        self.controls = [
            FakeAnimationControl() for _ in range(6)
        ]

    def getAnimControls(self, anim_names, allowAsyncBind=True):
        self.control_lookups.append((anim_names, allowAsyncBind))
        return self.controls


class NpcMovieResilienceTests(unittest.TestCase):

    def makeMoviePlayer(self):
        toon = type('Toon', (), {'getDoId': lambda self: 1001})()
        npc = type('Npc', (), {'getDoId': lambda self: 2001})()
        base.localAvatar = toon
        return QuestParser.NPCMoviePlayer('gag_intro', toon, npc)

    def test_primed_animation_controls_skip_actor_lookup(self):
        controls = [FakeAnimationControl() for _ in range(6)]
        actor = FakeActor(controls)
        player = self.makeMoviePlayer()
        player.primeAnimationControls(actor, {'right-hand': controls})

        player.playActorAnimation(actor, 'right-hand', 1.25, False)

        self.assertEqual(actor.control_lookups, [])
        for control in controls:
            self.assertEqual(control.play_rates, [1.25])
            self.assertEqual(control.play_calls, 1)
            self.assertEqual(control.loop_calls, [])
        player.cleanup()

    def test_primed_controls_are_shared_between_movie_players(self):
        controls = [FakeAnimationControl() for _ in range(6)]
        actor = FakeActor(controls)
        first_player = self.makeMoviePlayer()
        second_player = self.makeMoviePlayer()
        first_player.primeAnimationControls(actor, {'right-hand': controls})

        second_player.playActorAnimation(
            actor, 'right-hand', 1.0, False)

        self.assertEqual(actor.control_lookups, [])
        first_player.cleanup()
        second_player.cleanup()

    def test_batch_preparation_uses_one_actor_traversal(self):
        actor = FakeBatchActor()

        controls_by_animation = QuestParser.prepareAnimationControls(
            actor, ('neutral', 'right-hand'))

        self.assertEqual(
            actor.control_lookups,
            [(('neutral', 'right-hand'), False)],
        )
        self.assertEqual(
            controls_by_animation['neutral'],
            tuple(actor.controls[0::2]),
        )
        self.assertEqual(
            controls_by_animation['right-hand'],
            tuple(actor.controls[1::2]),
        )

    def test_animation_controls_are_looked_up_once_and_reused(self):
        controls = [FakeAnimationControl() for _ in range(6)]
        actor = FakeActor(controls)
        player = self.makeMoviePlayer()

        player.playActorAnimation(actor, 'right-point', 0.75, True)
        player.playActorAnimation(actor, 'right-point', 1.0, True)

        self.assertEqual(actor.control_lookups, ['right-point'])
        for control in controls:
            self.assertEqual(control.play_rates, [0.75, 1.0])
            self.assertEqual(control.play_calls, 0)
            self.assertEqual(control.loop_calls, [1, 1])
        player.cleanup()

    def test_reward_animation_duration_reuses_prepared_controls(self):
        controls = [FakeAnimationControl() for _ in range(6)]
        actor = FakeActor(controls)
        QuestParser.primeAnimationControls(
            actor, {'right-hand-start': controls})

        duration = QuestParser.getActorAnimationDuration(
            actor, 'right-hand-start')
        QuestParser.playActorAnimation(
            actor, 'right-hand-start', 1.5, False)

        self.assertEqual(duration, 2.0)
        self.assertEqual(actor.control_lookups, [])
        for control in controls:
            self.assertEqual(control.play_rates, [1.5])
            self.assertEqual(control.play_calls, 1)

    def test_long_dog_missing_head_gestures_use_preserved_fallbacks(self):
        for anim_name in Toon.LongDogHeadAnimationFallbacks:
            self.assertEqual(
                Toon.HeadAnimDict['dll'][anim_name],
                Toon.HeadAnimDict['dls'][anim_name],
            )
        self.assertNotEqual(
            Toon.HeadAnimDict['dll']['walk'],
            Toon.HeadAnimDict['dls']['walk'],
        )

    def test_tutorial_tom_scared_point_plays_once(self):
        quest_scripts = Path(
            'resources/phase_3/etc/QuestScripts.txt').read_text()
        scene = quest_scripts.split(
            'ID quest_assign_101', 1)[1].split('ID ', 1)[0]

        self.assertIn(
            'PLAY_ANIM npc "right-point"\n'
            'LOCAL_CHAT_CONFIRM npc QuestScript101_11',
            scene,
        )
        self.assertNotIn('LOOP_ANIM npc "right-point"', scene)

    def test_short_look_at_has_no_zero_or_negative_lerp(self):
        total, look, hold, return_to_center = getLookAtTiming(0.5)
        self.assertAlmostEqual(total, 0.5)
        self.assertGreater(look, 0)
        self.assertGreaterEqual(hold, 0)
        self.assertGreater(return_to_center, 0)
        self.assertAlmostEqual(look + hold + return_to_center, total)

    def test_max_laff_reward_does_not_duplicate_full_heal(self):
        avatar = FakeAvatar()
        reward = MaxHpReward(100, (1,))
        reward.sendRewardAI(avatar)
        self.assertEqual(avatar.max_hp_updates, [16])
        self.assertEqual(avatar.toon_up_calls, [])

    def test_toon_head_variable_exists_while_later_script_lines_parse(self):
        player = self.makeMoviePlayer()
        with mock.patch.object(
                QuestParser.ToonHeadFrame, 'ToonHeadFrame',
                FakeToonHeadFrame):
            player.parseToonHead(('TOON_HEAD', 'npc', 0, 0, 1))
        self.assertIsInstance(
            player.getVar('npcToonHead'), FakeToonHeadFrame)
        player.cleanup()

    def test_busy_npc_listens_for_avatar_exit_and_clears_immediately(self):
        self.assertNpcClearsOnAvatarExit(DistributedNPCToonAI)

    def test_busy_special_npc_listens_for_avatar_exit_and_clears_immediately(self):
        self.assertNpcClearsOnAvatarExit(DistributedNPCSpecialQuestGiverAI)

    def assertNpcClearsOnAvatarExit(self, npcClass):
        npc = npcClass.__new__(npcClass)
        npc.busy = 0
        npc.air = type('Air', (), {
            'getAvatarExitEvent': lambda self, av_id: 'avatarExit-%s' % av_id,
        })()
        accepted = []
        cleared = []
        npc.acceptOnce = lambda event, callback, extraArgs=None: accepted.append(
            (event, callback, extraArgs))
        npc.ignore = lambda event: None
        npc.uniqueName = lambda name: 'npc-%s' % name
        npc.sendClearMovie = lambda task: cleared.append(task)

        npc.setBusyAvatar(1234)
        self.assertEqual(npc.busy, 1234)
        self.assertEqual(accepted[0][0], 'avatarExit-1234')
        self.assertEqual(accepted[0][2], [1234])

        npc.handleUnexpectedExit(1234)
        self.assertEqual(cleared, [None])


def tearDownModule():
    base.destroy()


if __name__ == '__main__':
    unittest.main()
