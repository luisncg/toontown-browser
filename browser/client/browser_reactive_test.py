"""Isolated WebGL movie scene for the two level-one reactive gags."""

import builtins

from panda3d.core import Filename, NodePath, PerspectiveLens, get_model_path, loadPrcFile, loadPrcFileData

loadPrcFile('/etc/Configrc.prc')
loadPrcFileData(
    'browser-reactive-gag-test',
    '''
    window-type onscreen
    load-display p3webgldisplay
    audio-library-name p3openal_audio
    sync-video false
    framebuffer-srgb false
    textures-power-2 none
    m-dual false
    m-binary-alpha true
    vertex-buffers 1
    model-path /resources
    default-model-extension .bam
    notify-level warning
    ''')
get_model_path().prepend_directory(Filename('/resources'))

builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.interval.IntervalGlobal import Func, Parallel, Sequence, Wait  # noqa: E402
from direct.showbase.ShowBase import ShowBase  # noqa: E402


client = ShowBase()
client.disableMouse()
client.setBackgroundColor(0.16, 0.54, 0.82, 1)

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
        NodePath.__init__(self, 'reactive-test-battle')
        self.reparentTo(client.render)


battle = _Battle()

toonDna = ToonDNA.ToonDNA()
toonDna.newToonFromProperties(
    'fss', 'ms', 'm', 'm', 2, 0, 2, 2, 1, 8, 1, 8, 1, 14)
toon = Toon.Toon()
toon.setDNA(toonDna)
toon.doId = 1001
toon.reparentTo(battle)
toon.setPos(-2.8, 0, 0)
toon.setH(0)
toon.loop('neutral')


def makeSuit(name, x):
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


suit = makeSuit('f', 0.2)
otherSuit = makeSuit('p', 3.2)
battle.activeToons = [toon]
battle.activeSuits = [suit, otherSuit]

lens = PerspectiveLens()
lens.setFov(48)
client.cam.node().setLens(lens)
client.camera.setPos(-15.5, 1.0, 6.2)
client.camera.lookAt(0.2, 3.0, 3.0)

suitAttack = {'suit': suit}


def reaction(track, result):
    return {
        'toon': toon,
        'track': track,
        'level': 0,
        'result': result,
        'preventedDamage': 4,
        'flusterTurns': 2,
        'targetSuit': suit,
        'battle': battle,
    }


# Keep visual-regression captures deterministic; native contracts separately
# verify the complete randomized camera pools.
originalCameraChoice = MovieCamera.random.choice
MovieCamera.random.choice = lambda choices: next(
    (choice for choice in choices
     if choice is MovieCamera.allGroupLowShot),
    choices[0],
)
try:
    whoopee, whoopeeCamera, _skip = MovieReactive.doReactions(
        suitAttack, [reaction(EMBARRASS_TRACK, REACTIVE_RESULT_SUCCESS)])
    decoySuccess, decoySuccessCamera, decoySkips = MovieReactive.doReactions(
        suitAttack, [reaction(DECOY_TRACK, REACTIVE_RESULT_SUCCESS)])
    decoyFailure, decoyFailureCamera, failureSkips = MovieReactive.doReactions(
        suitAttack, [reaction(DECOY_TRACK, REACTIVE_RESULT_FAILURE)])
finally:
    MovieCamera.random.choice = originalCameraChoice


def activeMarker(stage):
    moustacheVisible = not toon.find('**/fake-moustache').isEmpty()
    handMoustacheVisible = not toon.find('**/fake-moustache-hand').isEmpty()
    glassesUnchanged = toon.getGlasses() == (0, 0, 0)
    flustered = suit.find('**/reactive-flustered-status')
    flusterTurns = 0 if flustered.isEmpty() else flustered.getPythonTag('turns')
    print('[BrowserReactiveGagMovie] %s-active moustache=%s handMoustache=%s glassesUnchanged=%s flusterTurns=%s' % (
        stage, moustacheVisible, handMoustacheVisible,
        glassesUnchanged, flusterTurns))


def cleanupMarker(stage):
    cushionGone = battle.find('**/whoopee-cushion').isEmpty()
    punctuationGone = suit.find('**/reactive-cog-punctuation').isEmpty()
    moustacheGone = toon.find('**/fake-moustache').isEmpty()
    handMoustacheGone = toon.find('**/fake-moustache-hand').isEmpty()
    glassesRestored = toon.getGlasses() == (0, 0, 0)
    flusteredGone = suit.find('**/reactive-flustered-status').isEmpty()
    print('[BrowserReactiveGagMovie] %s-clean cushion=%s punctuation=%s moustache=%s handMoustache=%s glasses=%s flustered=%s' % (
        stage, cushionGone, punctuationGone, moustacheGone,
        handMoustacheGone, glassesRestored, flusteredGone))


movie = Sequence(
    Func(print, '[BrowserReactiveGagMovie] whoopee-start'),
    Parallel(whoopee, whoopeeCamera,
             Sequence(Wait(2.5), Func(activeMarker, 'whoopee'))),
    Func(MovieReactive.advanceFlusteredStatus, suit),
    Func(MovieReactive.advanceFlusteredStatus, suit),
    Func(cleanupMarker, 'whoopee'),
    Wait(0.4),
    Func(print, '[BrowserReactiveGagMovie] decoy-success-start'),
    Parallel(decoySuccess, decoySuccessCamera,
             Sequence(Wait(0.62),
                      Func(activeMarker, 'decoy-success-putting'),
                      Wait(0.38),
                      Func(activeMarker, 'decoy-success'))),
    Func(cleanupMarker, 'decoy-success'),
    Wait(0.4),
    Func(print, '[BrowserReactiveGagMovie] decoy-failure-start'),
    Parallel(decoyFailure, decoyFailureCamera,
             Sequence(Wait(0.62),
                      Func(activeMarker, 'decoy-failure-putting'),
                      Wait(0.38),
                      Func(activeMarker, 'decoy-failure'))),
    Func(cleanupMarker, 'decoy-failure'),
    Func(print, '[BrowserReactiveGagMovie] complete skips=%s failureSkips=%s' % (
        decoySkips, failureSkips)),
)
movie.start()


def frame():
    client.taskMgr.step()
