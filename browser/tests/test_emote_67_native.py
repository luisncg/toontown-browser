"""Exercise the procedural 67 emote against preserved native Toon skeletons."""

import builtins
import time

from panda3d.core import Filename, get_model_path, load_prc_file_data


load_prc_file_data('', 'window-type none\ndefault-directnotify-level warning')
get_model_path().prepend_directory(
    Filename.from_os_specific('resources')
)

from direct.showbase.ShowBase import ShowBase


base = ShowBase(windowType='none')
builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.actor.Actor import Actor
from direct.interval.IntervalGlobal import Sequence
from otp.otpbase import OTPLocalizer
from toontown.toon import TTEmote
from toontown.toon.DistributedToonAI import DistributedToonAI


TORSOS = (
    'tt_a_chr_dgs_shorts_torso',
    'tt_a_chr_dgm_shorts_torso',
    'tt_a_chr_dgl_shorts_torso',
    'tt_a_chr_dgm_skirt_torso',
)


def exercise_torso(torso, start_time=0.0):
    model = 'phase_3/models/char/%s_1000.bam' % torso
    animations = {
        'neutral': 'phase_3/models/char/%s_neutral.bam' % torso,
        'shrug': 'phase_3.5/models/char/%s_shrug.bam' % torso,
    }
    toon = Actor(models={'torso': model}, anims={'torso': animations})
    toon.playingAnim = 'neutral'
    toon.loop('neutral')
    warmup_deadline = time.monotonic() + 0.25
    while time.monotonic() < warmup_deadline:
        base.taskMgr.step()
        toon.update(force=True)
        time.sleep(0.01)
    resume_frame = toon.getCurrentFrame('neutral', partName='torso')
    assert resume_frame > 1
    palms = {
        side: toon.exposeJoint(None, 'torso', 'def_%s_palm' % side)
        for side in ('left', 'right')
    }
    head = toon.exposeJoint(None, 'torso', 'def_head')
    track, duration, exit_track = TTEmote.doSixtySeven(toon)
    full_track = Sequence(track, exit_track)
    full_track.start(start_time)
    deltas = []
    active_head_hprs = []
    entry_left_x = []
    entry_right_x = []
    last_controlled_head_hpr = None
    released_head_hpr = None
    deadline = time.monotonic() + 6.0
    started_at = time.monotonic()
    while full_track.isPlaying() and time.monotonic() < deadline:
        base.taskMgr.step()
        toon.update(force=True)
        elapsed = time.monotonic() - started_at
        deltas.append(
            palms['left'].getZ(toon) - palms['right'].getZ(toon)
        )
        if start_time == 0.0 and elapsed < 0.30:
            entry_left_x.append(palms['left'].getX(toon))
            entry_right_x.append(palms['right'].getX(toon))
        head_hpr = tuple(head.getHpr(toon))
        if hasattr(toon, '_sixtySevenJointControllers'):
            active_head_hprs.append(head_hpr)
            last_controlled_head_hpr = head_hpr
        elif last_controlled_head_hpr is not None and released_head_hpr is None:
            released_head_hpr = head_hpr
        time.sleep(0.01)

    assert not full_track.isPlaying(), '%s emote did not finish' % torso
    assert not hasattr(toon, '_sixtySevenJointControllers')
    assert min(deltas) < -0.15, '%s never raised its right hand' % torso
    assert max(deltas) > 0.15, '%s never raised its left hand' % torso
    if start_time == 0.0:
        assert max(entry_left_x) < 0.0, \
            '%s left hand crossed the body during entry' % torso
        assert min(entry_right_x) > 0.0, \
            '%s right hand crossed the body during entry' % torso
    head_ranges = [
        max(values) - min(values)
        for values in zip(*active_head_hprs)]
    assert max(head_ranges) < 0.001, \
        '%s moved its head during 67: %s' % (torso, head_ranges)
    assert released_head_hpr is not None
    assert max(
        abs(before - after)
        for before, after in zip(last_controlled_head_hpr, released_head_hpr)
    ) < 1.5, '%s popped when releasing its controlled pose: %s -> %s' % (
        torso, last_controlled_head_hpr, released_head_hpr)
    resumed_frame = toon.getCurrentFrame('neutral', partName='torso')
    frame_count = toon.getNumFrames('neutral', partName='torso')
    frame_delta = abs(resumed_frame - resume_frame)
    frame_delta = min(frame_delta, frame_count - frame_delta)
    assert frame_delta <= 2, '%s reset idle frame %s to %s' % (
        torso, resume_frame, resumed_frame)
    toon.cleanup()
    return (round(min(deltas), 3), round(max(deltas), 3))


class _Notify:
    def warning(self, message):
        raise AssertionError(message)


class _Avatar:
    notify = _Notify()

    def __init__(self):
        self.emoteAccess = [0] * 25 + [1]
        self.persisted = []

    def d_setEmoteAccess(self, bits):
        self.persisted.append(list(bits))


assert OTPLocalizer.EmoteList[25] == '67'
assert OTPLocalizer.EmoteWhispers[25] == '%s does the 67.'
assert OTPLocalizer.EmoteFuncDict['67'] == 25
assert len(OTPLocalizer.EmoteList) == len(TTEmote.EmoteFunc) == 26
assert TTEmote.EmoteFunc[25][0] is TTEmote.doSixtySeven

for legacy_length in (20, 25):
    avatar = _Avatar()
    DistributedToonAI.setEmoteAccess(avatar, [0] * legacy_length)
    assert len(avatar.emoteAccess) == 26
    assert avatar.emoteAccess[25] == 1
    assert avatar.persisted == [avatar.emoteAccess]

results = {torso: exercise_torso(torso) for torso in TORSOS}
timestamped = exercise_torso('tt_a_chr_dgm_shorts_torso', start_time=1.5)
print('67 emote native contracts passed: %s timestamped=%s' % (
    results,
    timestamped,
))
