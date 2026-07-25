"""Exercise reactive-gag movie intervals with preserved native actors."""

import builtins
import time

from panda3d.core import Filename, NodePath, get_model_path, load_prc_file_data

load_prc_file_data(
    '',
    'window-type none\ndefault-directnotify-level warning\n'
    'default-model-extension .bam')
get_model_path().prepend_directory(Filename.from_os_specific('resources'))

builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.showbase.ShowBase import ShowBase  # noqa: E402

base = ShowBase(windowType='none')

from toontown.battle import MovieCamera, MovieReactive  # noqa: E402
from toontown.battle.ReactiveGagGlobals import (  # noqa: E402
    DECOY_TRACK,
    EMBARRASS_TRACK,
    REACTIVE_RESULT_FAILURE,
    REACTIVE_RESULT_SUCCESS,
)
from toontown.suit import Suit, SuitDNA  # noqa: E402
from toontown.toon import Toon, ToonDNA  # noqa: E402


class _Battle(NodePath):
    def __init__(self):
        NodePath.__init__(self, 'reactive-native-battle')
        self.reparentTo(base.render)


battle = _Battle()
toonDna = ToonDNA.ToonDNA()
toonDna.newToonFromProperties(
    'dss', 'ms', 'm', 'm', 2, 0, 2, 2, 1, 8, 1, 8, 1, 14)
toon = Toon.Toon()
toon.setDNA(toonDna)
toon.doId = 1001
toon.reparentTo(battle)
toon.setPos(-2.8, 0, 0)
toon.loop('neutral')


def make_suit(name, x):
    dna = SuitDNA.SuitDNA()
    dna.newSuit(name)
    cog = Suit.Suit()
    cog.setDNA(dna)
    cog.doId = 2000 + int(x * 10)
    cog.reparentTo(battle)
    cog.setPos(x, 6.2, 0)
    cog.setH(180)
    cog.loop('neutral')
    return cog


suit = make_suit('f', 0.2)
otherSuit = make_suit('p', 3.2)
battle.activeToons = [toon]
battle.activeSuits = [suit, otherSuit]


originalChoice = MovieCamera.random.choice
originalBaseCamera = base.camera
originalBuiltinCamera = builtins.camera
testCamera = NodePath('reactive-camera-contract')
cameraChoices = []


def chooseFirst(choices):
    cameraChoices.append(choices)
    return choices[0]


MovieCamera.random.choice = chooseFirst
base.camera = testCamera
builtins.camera = testCamera
try:
    shortCamera = MovieCamera.chooseThrowSquirtReactionShot(
        toon, suit, 1.6, includeBehindToon=False)
    longCamera = MovieCamera.chooseThrowSquirtReactionShot(toon, suit, 4.2)
    lureReactionCamera = MovieCamera.chooseLureReactionShot(toon, suit, 4.2)
finally:
    MovieCamera.random.choice = originalChoice
    base.camera = originalBaseCamera
    builtins.camera = originalBuiltinCamera
assert shortCamera.getName() == 'avatarCloseUpThrowShot'
assert abs(shortCamera.getDuration() - 1.6) < 1e-06
assert MovieCamera.avatarBehindShot not in cameraChoices[0]
assert MovieCamera.avatarBehindShot in cameraChoices[1]
assert longCamera.getName() == 'throwSquirtReactionShot'
assert abs(longCamera.getDuration() - 4.2) < 1e-06
assert lureReactionCamera.getName() == 'allGroupLowShot'
assert abs(lureReactionCamera.getDuration() - 4.2) < 1e-06

moustacheState = {}
originalGlasses = toon.getGlasses()
MovieReactive._showMoustacheInHand(moustacheState, toon)
assert not toon.find('**/fake-moustache-hand').isEmpty()
assert toon.find('**/fake-moustache').isEmpty()
toon.pose('think', 30)
MovieReactive._forceActorJoints(toon)
contactMoustache = toon.find('**/fake-moustache-hand')
contactBounds = contactMoustache.getTightBounds(toon)
faceState = {}
MovieReactive._putOnMoustache(faceState, toon)
faceMoustache = toon.find('**/fake-moustache')
faceBounds = faceMoustache.getTightBounds(toon)
assert ((contactBounds[0] + contactBounds[1]) * 0.5).almostEqual(
    (faceBounds[0] + faceBounds[1]) * 0.5, 0.02)
MovieReactive._removeMoustache(faceState, toon)
MovieReactive._transferMoustacheToFace(moustacheState, toon)
assert toon.find('**/fake-moustache-hand').isEmpty()
assert not toon.find('**/fake-moustache').isEmpty()
MovieReactive._removeMoustache(moustacheState, toon)
toon.loop('neutral')

MovieReactive._putOnMoustache(moustacheState, toon)
moustache = toon.find('**/fake-moustache')
assert not moustache.isEmpty()
moustacheHead = moustache.getParent()
muzzle = moustacheHead.find('**/muzzle')
assert not muzzle.isEmpty()
assert moustache.getTightBounds(moustacheHead)[0].getY() >= \
    muzzle.getTightBounds(moustacheHead)[1].getY()
assert toon.getGlasses() == originalGlasses
MovieReactive._removeMoustache(moustacheState, toon)
assert toon.find('**/fake-moustache').isEmpty()

headShakeState = {}
originalSuitHpr = suit.getHpr(battle)
originalHeadHprs = [head.getHpr() for head in suit.getHeadParts()]
headShake = MovieReactive._makeCogHeadShake(headShakeState, suit)
headShake.start()
headShake.setT(0.16)
assert suit.getHpr(battle).almostEqual(originalSuitHpr)
assert any(
    not head.getHpr().almostEqual(originalHeadHpr, 0.5)
    for head, originalHeadHpr in zip(
        suit.getHeadParts(), originalHeadHprs)
)
headShake.finish()
MovieReactive._restoreCogHeads(headShakeState)
assert all(
    head.getHpr().almostEqual(originalHeadHpr)
    for head, originalHeadHpr in zip(
        suit.getHeadParts(), originalHeadHprs)
)


def play(track, result, interrupt=False):
    originalSuitPos = suit.getPos(battle)
    originalSuitHpr = suit.getHpr(battle)
    originalHeadHprs = [head.getHpr() for head in suit.getHeadParts()]
    reaction = {
        'toon': toon,
        'track': track,
        'level': 0,
        'result': result,
        'preventedDamage': 4,
        'flusterTurns': 2,
        'targetSuit': suit,
        'battle': battle,
    }
    interval, camera, skip = MovieReactive.doReactions(
        {'suit': suit}, [reaction])
    assert interval is not None
    assert camera.getDuration() == interval.getDuration()
    interval.start()
    deadline = time.monotonic() + 12
    interruptDeadline = time.monotonic() + 1.0 if interrupt else None
    while interval.isPlaying() and time.monotonic() < deadline:
        base.taskMgr.step()
        if interruptDeadline is not None and time.monotonic() >= interruptDeadline:
            interval.finish()
            interruptDeadline = None
        time.sleep(0.005)
    assert not interval.isPlaying()
    if track == EMBARRASS_TRACK and result == REACTIVE_RESULT_SUCCESS:
        status = suit.find('**/reactive-flustered-status')
        assert not status.isEmpty()
        assert status.getPythonTag('turns') == 2
        assert status.find('**/reactive-flustered-label').isEmpty()
        assert not status.find('**/reactive-flustered-steam-0').isEmpty()
        assert not status.find('**/reactive-flustered-sweat-0').isEmpty()
        assert 'FLUSTERED' not in \
            status.find('**/reactive-flustered-turns').node().getText()
        MovieReactive.advanceFlusteredStatus(suit)
        status = suit.find('**/reactive-flustered-status')
        assert status.getPythonTag('turns') == 1
        assert status.find('**/reactive-flustered-turns').node().getText() == '1 TURN'
        MovieReactive.advanceFlusteredStatus(suit)
    else:
        assert suit.find('**/reactive-flustered-status').isEmpty()
    assert battle.find('**/whoopee-cushion').isEmpty()
    assert suit.find('**/reactive-cog-punctuation').isEmpty()
    assert toon.find('**/fake-moustache').isEmpty()
    assert toon.find('**/fake-moustache-hand').isEmpty()
    assert suit.find('**/reactive-flustered-status').isEmpty()
    assert toon.getGlasses() == (0, 0, 0)
    assert suit.getPos(battle).almostEqual(originalSuitPos)
    assert suit.getHpr(battle).almostEqual(originalSuitHpr)
    assert all(
        head.getHpr().almostEqual(originalHeadHpr)
        for head, originalHeadHpr in zip(
            suit.getHeadParts(), originalHeadHprs)
    )
    assert not suit.hasColorScale()
    assert abs(toon.getPlayRate('neutral') - 1.0) < 1e-06
    assert all(muzzle.isHidden() for muzzle in toon.getLaughMuzzles())
    return skip


assert play(EMBARRASS_TRACK, REACTIVE_RESULT_SUCCESS) is False
assert play(EMBARRASS_TRACK, REACTIVE_RESULT_FAILURE) is False
assert play(DECOY_TRACK, REACTIVE_RESULT_SUCCESS) is True
assert play(DECOY_TRACK, REACTIVE_RESULT_FAILURE) is False
assert play(EMBARRASS_TRACK, REACTIVE_RESULT_SUCCESS, interrupt=True) is False
assert play(DECOY_TRACK, REACTIVE_RESULT_SUCCESS, interrupt=True) is True

# Four successful cushions aimed at one Cog share the same two-layer success
# cue (cushion plus laughter) instead of creating four overlapping copies.
soundIntervals = []
originalSoundInterval = MovieReactive.SoundInterval


def countSoundInterval(*args, **kwargs):
    soundIntervals.append((args, kwargs))
    return originalSoundInterval(*args, **kwargs)


MovieReactive.SoundInterval = countSoundInterval
try:
    sharedReactions = [{
        'toon': toon,
        'track': EMBARRASS_TRACK,
        'level': 0,
        'result': REACTIVE_RESULT_SUCCESS,
        'preventedDamage': 4,
        'flusterTurns': 2,
        'targetSuit': suit,
        'battle': battle,
    } for _ in range(4)]
    sharedTrack, sharedCamera, sharedSkip = MovieReactive.doReactions(
        {'suit': suit}, sharedReactions)
finally:
    MovieReactive.SoundInterval = originalSoundInterval
assert sharedTrack is not None
assert sharedCamera.getDuration() == sharedTrack.getDuration()
assert sharedSkip is False
assert len(soundIntervals) == 2
print('Reactive gag native movie contracts passed.')
