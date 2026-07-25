"""Cog-phase presentation for the first two reactive gag tracks."""

import math

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
    TextNode,
    Vec4,
)
from direct.interval.IntervalGlobal import (
    ActorInterval,
    Func,
    LerpColorScaleInterval,
    LerpHprInterval,
    LerpPosInterval,
    Parallel,
    Sequence,
    SoundInterval,
    Wait,
)
from .ReactiveGagGlobals import (
    DECOY_TRACK,
    EMBARRASS_TRACK,
    REACTIVE_RESULT_FAILURE,
    REACTIVE_RESULT_SUCCESS,
    getReactiveGagName,
)
from . import MovieCamera


def _makeCogPunctuation(suit, character):
    text = TextNode('reactive-cog-punctuation')
    text.setText(character)
    text.setAlign(TextNode.ACenter)
    text.setTextColor(1.0, 0.88, 0.12, 1.0)
    text.setShadow(0.06, 0.06)
    text.setShadowColor(0, 0, 0, 0.75)
    node = suit.attachNewNode(text)
    node.setBillboardPointEye()
    node.setScale(0.72)
    node.setPos(0, 0, suit.getHeight() + 1.15)
    return node


def _changePunctuation(node, character):
    if node and not node.isEmpty():
        node.node().setText(character)


def _changePunctuationInState(state, character):
    _changePunctuation(state.get('punctuation'), character)


def _removeNode(state, key):
    node = state.pop(key, None)
    if node and not node.isEmpty():
        node.removeNode()


def showFlusteredStatus(suit, turns):
    """Show or refresh the lure-style counter for a flustered Cog."""
    turns = max(0, int(turns))
    if turns <= 0:
        clearFlusteredStatus(suit)
        return
    status = suit.find('**/reactive-flustered-status')
    if status.isEmpty():
        status = suit.attachNewNode('reactive-flustered-status')
        status.setBillboardPointEye()
        status.setPos(0, 0, suit.getHeight() + 0.78)
        status.setScale(0.36)
        status.setDepthTest(False)
        status.setDepthWrite(False)
        status.setBin('fixed', 50)

        # Show the emotion rather than naming it: hot steam above the Cog and
        # sweat kicked out to either side remain visible between its two turns.
        for index, (x, z, scale) in enumerate((
                (-0.82, 0.88, 0.78),
                (0.0, 1.18, 0.92),
                (0.82, 0.88, 0.78))):
            puff = _makeInflatedDisc(
                'reactive-flustered-steam-%d' % index,
                0.43, 0.31, 0.08)
            puff.reparentTo(status)
            puff.setPos(x, 0, z)
            puff.setP(90)
            puff.setScale(scale)
            puff.setColor(1.0, 0.30, 0.12, 0.88)
            puff.setTwoSided(True)

        for index, (x, roll) in enumerate(((-1.55, -22), (1.55, 22))):
            sweat = _makeInflatedDisc(
                'reactive-flustered-sweat-%d' % index,
                0.22, 0.48, 0.07)
            sweat.reparentTo(status)
            sweat.setPos(x, 0, 0.12)
            sweat.setP(90)
            sweat.setR(roll)
            sweat.setColor(0.18, 0.82, 1.0, 0.96)
            sweat.setTwoSided(True)

        counter = TextNode('reactive-flustered-turns')
        counter.setAlign(TextNode.ACenter)
        counter.setTextColor(1.0, 0.96, 0.58, 1.0)
        counter.setShadow(0.055, 0.055)
        counter.setShadowColor(0.12, 0.01, 0.02, 0.92)
        counterNode = status.attachNewNode(counter)
        counterNode.setZ(-0.68)
        counterNode.setScale(0.82)

    counterNode = status.find('**/reactive-flustered-turns')
    counterNode.node().setText(
        '%d TURN%s' % (turns, '' if turns == 1 else 'S'))
    status.setPythonTag('turns', turns)
    status.show()


def clearFlusteredStatus(suit):
    status = suit.find('**/reactive-flustered-status')
    if not status.isEmpty():
        status.clearPythonTag('turns')
        status.removeNode()


def advanceFlusteredStatus(suit):
    """Consume the Cog turn that just animated and update its counter."""
    status = suit.find('**/reactive-flustered-status')
    if status.isEmpty():
        return
    turns = int(status.getPythonTag('turns')) - 1
    if turns <= 0:
        clearFlusteredStatus(suit)
    else:
        showFlusteredStatus(suit, turns)


def _makeFakeMoustacheModel():
    """Build a standalone Toon-style moustache in accessory-model space."""
    data = GeomVertexData(
        'fake-moustache', GeomVertexFormat.getV3(), Geom.UHStatic)
    vertex = GeomVertexWriter(data, 'vertex')
    triangles = GeomTriangles(Geom.UHStatic)
    leftLobe = [
        (0.02, 0.48),
        (-0.28, 0.70),
        (-0.78, 0.76),
        (-1.28, 0.60),
        (-1.70, 0.30),
        (-1.20, 0.16),
        (-0.62, 0.28),
        (-0.20, 0.42),
    ]
    lobes = [leftLobe, [(-x, z) for x, z in reversed(leftLobe)]]
    frontY = 0.04
    backY = -0.04
    for lobe in lobes:
        frontStart = data.getNumRows()
        for x, z in lobe:
            vertex.addData3(x, frontY, z)
        backStart = data.getNumRows()
        for x, z in lobe:
            vertex.addData3(x, backY, z)
        for index in range(1, len(lobe) - 1):
            triangles.addVertices(
                frontStart, frontStart + index, frontStart + index + 1)
            triangles.addVertices(
                backStart, backStart + index + 1, backStart + index)
        for index in range(len(lobe)):
            nextIndex = (index + 1) % len(lobe)
            frontA = frontStart + index
            frontB = frontStart + nextIndex
            backA = backStart + index
            backB = backStart + nextIndex
            triangles.addVertices(frontA, backA, backB)
            triangles.addVertices(frontA, backB, frontB)

    geom = Geom(data)
    geom.addPrimitive(triangles)
    node = GeomNode('fake-moustache')
    node.addGeom(geom)
    model = NodePath(node)
    model.setColor(0.025, 0.018, 0.012, 1.0)
    model.setTwoSided(True)
    model.setLightOff(1)
    return model


def _putOnMoustache(state, toon):
    model = _makeFakeMoustacheModel()
    moustaches = []
    for headNode in toon.findAllMatches('**/__Actor_head'):
        muzzle = headNode.find('**/muzzle')
        if muzzle.isEmpty():
            for candidate in headNode.findAllMatches('**/+GeomNode'):
                name = candidate.getName()
                if name.startswith('muzzle-') and name.endswith('-neutral'):
                    muzzle = candidate
                    break
        if muzzle.isEmpty():
            bounds = headNode.getTightBounds(headNode)
        else:
            bounds = muzzle.getTightBounds(headNode)
        if not bounds:
            continue
        minimum, maximum = bounds
        muzzleWidth = maximum.getX() - minimum.getX()
        muzzleHeight = maximum.getZ() - minimum.getZ()
        scale = max(0.16, muzzleWidth * 1.12 / 3.4)
        targetZ = maximum.getZ() - muzzleHeight * 0.30
        moustache = model.copyTo(headNode)
        moustache.setName('fake-moustache')
        moustache.setScale(scale)
        moustache.setPos(
            (minimum.getX() + maximum.getX()) * 0.5,
            maximum.getY() + 0.035,
            targetZ - 0.46 * scale,
        )
        moustaches.append(moustache)
    model.removeNode()
    state['moustaches'] = moustaches


def _forceActorJoints(toon):
    for lodName in toon.getLODNames():
        toon.update(lodName=lodName, force=True)


def _showMoustacheInHand(state, toon, contactFrame=30):
    """Place the prop in the right hand, aligned for the face contact pose."""
    _removeMoustache(state, toon)
    toon.pose('think', contactFrame)
    _forceActorJoints(toon)

    model = _makeFakeMoustacheModel()
    handMoustaches = []
    heads = list(toon.findAllMatches('**/__Actor_head'))
    for hand, headNode in zip(toon.getRightHands(), heads):
        targetModel = model.copyTo(headNode)
        targetModel.setName('fake-moustache-target')

        muzzle = headNode.find('**/muzzle')
        if muzzle.isEmpty():
            for candidate in headNode.findAllMatches('**/+GeomNode'):
                name = candidate.getName()
                if name.startswith('muzzle-') and name.endswith('-neutral'):
                    muzzle = candidate
                    break
        bounds = (muzzle if not muzzle.isEmpty() else headNode).getTightBounds(
            headNode)
        if not bounds:
            targetModel.removeNode()
            continue
        minimum, maximum = bounds
        muzzleWidth = maximum.getX() - minimum.getX()
        muzzleHeight = maximum.getZ() - minimum.getZ()
        scale = max(0.16, muzzleWidth * 1.12 / 3.4)
        targetModel.setScale(scale)
        targetModel.setPos(
            (minimum.getX() + maximum.getX()) * 0.5,
            maximum.getY() + 0.035,
            maximum.getZ() - muzzleHeight * 0.30 - 0.46 * scale,
        )

        held = model.copyTo(hand)
        held.setName('fake-moustache-hand')
        held.setTransform(targetModel.getTransform(hand))
        handMoustaches.append(held)
        targetModel.removeNode()

    model.removeNode()
    state['handMoustaches'] = handMoustaches
    toon.pose('think', 0)
    _forceActorJoints(toon)


def _transferMoustacheToFace(state, toon):
    for moustache in state.pop('handMoustaches', []):
        if moustache and not moustache.isEmpty():
            moustache.removeNode()
    _putOnMoustache(state, toon)


def _removeMoustache(state, toon):
    for moustache in state.pop('handMoustaches', []):
        if moustache and not moustache.isEmpty():
            moustache.removeNode()
    for moustache in state.pop('moustaches', []):
        if moustache and not moustache.isEmpty():
            moustache.removeNode()


def _showPunctuation(state, suit, character):
    _removeNode(state, 'punctuation')
    state['punctuation'] = _makeCogPunctuation(suit, character)


def _makeCogHeadShake(state, suit):
    headTracks = []
    originalHprs = []
    for head in suit.getHeadParts():
        if head.isEmpty():
            continue
        originalHpr = head.getHpr()
        originalHprs.append((head, originalHpr))
        headTracks.append(Sequence(
            LerpHprInterval(head, 0.13, originalHpr + (12, 0, 0)),
            LerpHprInterval(head, 0.20, originalHpr + (-12, 0, 0)),
            LerpHprInterval(head, 0.20, originalHpr + (10, 0, 0)),
            LerpHprInterval(head, 0.16, originalHpr),
        ))
    state['cogHeadHprs'] = originalHprs
    return Parallel(*headTracks)


def _restoreCogHeads(state):
    for head, hpr in state.pop('cogHeadHprs', []):
        if head and not head.isEmpty():
            head.setHpr(hpr)


def _doFakeMoustache(suitAttack, reaction):
    toon = reaction['toon']
    suit = suitAttack['suit']
    battle = reaction['battle']
    success = reaction['result'] == REACTIVE_RESULT_SUCCESS
    state = {}
    questionSfx = base.loader.loadSfx('phase_3.5/audio/dial/COG_VO_question.ogg')
    originalHpr = suit.getHpr(battle)
    confusion = _makeCogHeadShake(state, suit)
    track = Sequence(
        Func(_showMoustacheInHand, state, toon),
        ActorInterval(toon, 'think', startFrame=0, endFrame=30,
                      duration=0.86),
        Func(_transferMoustacheToFace, state, toon),
        Func(_showPunctuation, state, suit, '?'),
        Parallel(
            ActorInterval(toon, 'think', startFrame=30, endFrame=0,
                          duration=0.66),
            SoundInterval(questionSfx, node=suit),
            confusion,
        ),
    )
    if not success:
        track.append(Func(_changePunctuationInState, state, '!'))
        track.append(Wait(0.35))
    else:
        track.append(Wait(0.45))
    track.append(Func(_removeNode, state, 'punctuation'))
    track.append(Func(_removeMoustache, state, toon))
    track.append(Func(toon.loop, 'neutral'))
    track.append(Func(_restoreCogHeads, state))
    track.append(Func(suit.setHpr, battle, originalHpr))
    track.append(Func(suit.loop, 'neutral'))
    return track


def _makeInflatedDisc(name, xRadius, yRadius, thickness):
    """Build a tiny, WebGL-safe inflated disc without a new art asset."""
    segments = 24
    data = GeomVertexData(name, GeomVertexFormat.getV3(), Geom.UHStatic)
    vertex = GeomVertexWriter(data, 'vertex')
    vertex.addData3(0, 0, thickness)
    for index in range(segments):
        angle = math.pi * 2.0 * index / segments
        lobe = 1.0 + 0.08 * math.cos(angle * 2.0)
        vertex.addData3(
            math.cos(angle) * xRadius * lobe,
            math.sin(angle) * yRadius * lobe,
            thickness * 0.24,
        )
    bottomCenter = segments + 1
    vertex.addData3(0, 0, -thickness * 0.62)
    for index in range(segments):
        angle = math.pi * 2.0 * index / segments
        lobe = 1.0 + 0.08 * math.cos(angle * 2.0)
        vertex.addData3(
            math.cos(angle) * xRadius * lobe,
            math.sin(angle) * yRadius * lobe,
            -thickness * 0.24,
        )

    triangles = GeomTriangles(Geom.UHStatic)
    for index in range(segments):
        nextIndex = (index + 1) % segments
        topA = 1 + index
        topB = 1 + nextIndex
        bottomA = bottomCenter + 1 + index
        bottomB = bottomCenter + 1 + nextIndex
        triangles.addVertices(0, topA, topB)
        triangles.addVertices(bottomCenter, bottomB, bottomA)
        triangles.addVertices(topA, bottomA, bottomB)
        triangles.addVertices(topA, bottomB, topB)

    geom = Geom(data)
    geom.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geom)
    return NodePath(node)


def _makeCushion(state, battle, toon, suit):
    cushion = battle.attachNewNode('whoopee-cushion')
    body = _makeInflatedDisc('whoopee-cushion-body', 0.70, 0.52, 0.15)
    body.reparentTo(cushion)
    body.setColor(0.96, 0.10, 0.38, 1)
    body.setTwoSided(True)
    nozzle = _makeInflatedDisc('whoopee-cushion-nozzle', 0.19, 0.32, 0.09)
    nozzle.reparentTo(cushion)
    nozzle.setPos(0, -0.66, -0.01)
    nozzle.setColor(0.76, 0.045, 0.24, 1)
    nozzle.setTwoSided(True)
    cushion.setScale(0.86)
    suitPos = suit.getPos(battle)
    toonPos = toon.getPos(battle)
    cushionPos = suitPos * 0.72 + toonPos * 0.28
    cushionPos.setZ(suitPos.getZ() + 0.025)
    cushion.setPos(cushionPos)
    state['cushion'] = cushion
    state['cushionPos'] = cushionPos


def _startToonLaugh(toon):
    toon.setPlayRate(10, 'neutral')
    toon.loop('neutral')
    toon.showLaughMuzzle()


def _stopToonLaugh(toon):
    toon.hideLaughMuzzle()
    toon.setPlayRate(1, 'neutral')
    toon.loop('neutral')


def _doWhoopeeCushion(suitAttack, reaction, playSuccessAudio=True,
                      showStatus=True):
    toon = reaction['toon']
    suit = suitAttack['suit']
    battle = reaction['battle']
    success = reaction['result'] == REACTIVE_RESULT_SUCCESS
    state = {}
    originalSuitPos = suit.getPos(battle)
    originalSuitHpr = suit.getHpr(battle)
    toonPos = toon.getPos(battle)
    stepPos = originalSuitPos * 0.70 + toonPos * 0.30
    stepPos.setZ(originalSuitPos.getZ())

    track = Sequence(
        Parallel(
            ActorInterval(toon, 'toss', duration=0.9),
            Sequence(Wait(0.38), Func(_makeCushion, state, battle, toon, suit)),
        ),
        ActorInterval(toon, 'wave', duration=0.72),
        LerpPosInterval(suit, 0.62, stepPos, other=battle),
    )
    if success:
        toons = list(battle.activeToons)
        otherSuits = [other for other in battle.activeSuits if other != suit]
        laughStart = Parallel(*[Func(_startToonLaugh, laughingToon) for laughingToon in toons])
        laughStop = Parallel(*[Func(_stopToonLaugh, laughingToon) for laughingToon in toons])
        cogLaughs = Parallel(*[
            Sequence(ActorInterval(other, 'victory', duration=1.15), Func(other.loop, 'neutral'))
            for other in otherSuits
        ])
        successEffects = [
            Sequence(
                ActorInterval(suit, 'flail', duration=1.1),
                Func(suit.loop, 'neutral'),
            ),
            Sequence(laughStart, Wait(1.1), laughStop),
            cogLaughs,
            Sequence(
                LerpColorScaleInterval(suit, 0.22, Vec4(1.0, 0.42, 0.42, 1.0)),
                Wait(0.65),
                LerpColorScaleInterval(suit, 0.22, Vec4(1, 1, 1, 1)),
                Func(suit.clearColorScale),
            ),
        ]
        if showStatus:
            successEffects.append(Func(
                showFlusteredStatus, suit,
                reaction.get('flusterTurns', 2)))
        # Every successful cushion still gets its complete visual reaction,
        # but a same-Cog group shares one audio cue instead of stacking it once
        # per Toon.
        if playSuccessAudio:
            comicSfx = base.loader.loadSfx(
                'phase_3/audio/sfx/tt_s_ara_mat_crash_boing.ogg')
            laughSfx = base.loader.loadSfx(
                'phase_4/audio/sfx/avatar_emotion_laugh.ogg')
            successEffects.extend([
                SoundInterval(comicSfx, node=suit),
                Sequence(Wait(0.12), SoundInterval(laughSfx, node=toon)),
            ])
        track.append(Parallel(*successEffects))
    else:
        track.append(Wait(0.55))
        track.append(ActorInterval(toon, 'shrug', duration=0.8))
    track.append(LerpPosInterval(suit, 0.58, originalSuitPos, other=battle))
    track.append(Func(_removeNode, state, 'cushion'))
    track.append(Func(suit.setPosHpr, battle, originalSuitPos, originalSuitHpr))
    track.append(Func(suit.clearColorScale))
    track.append(Func(suit.loop, 'neutral'))
    track.append(Func(toon.loop, 'neutral'))
    return track


def doReactions(suitAttack, reactions):
    """Return reaction movie, matching camera wait, and attack-cancel flag."""
    if not reactions:
        return (None, None, False)

    track = Sequence(name='reactive-gags')
    cameraTrack = Sequence(name='reactive-gags-camera')
    skipSuitAttack = False
    playedEmbarrassSuccessAudio = False
    # A cushion is planted before a targeted Toon tries its disguise.
    reactions = sorted(reactions, key=lambda reaction: 0 if reaction['track'] == EMBARRASS_TRACK else 1)
    for reaction in reactions:
        if reaction['result'] not in (REACTIVE_RESULT_SUCCESS, REACTIVE_RESULT_FAILURE):
            continue
        if reaction['track'] == EMBARRASS_TRACK:
            playSuccessAudio = (
                reaction['result'] != REACTIVE_RESULT_SUCCESS or
                not playedEmbarrassSuccessAudio)
            reactionTrack = _doWhoopeeCushion(
                suitAttack, reaction,
                playSuccessAudio=playSuccessAudio,
                showStatus=not playedEmbarrassSuccessAudio)
            if reaction['result'] == REACTIVE_RESULT_SUCCESS:
                playedEmbarrassSuccessAudio = True
        elif reaction['track'] == DECOY_TRACK:
            reactionTrack = _doFakeMoustache(suitAttack, reaction)
            if reaction['result'] == REACTIVE_RESULT_SUCCESS:
                skipSuitAttack = True
        else:
            continue
        track.append(reactionTrack)
        duration = reactionTrack.getDuration()
        if getattr(base, 'camera', None) is not None:
            if reaction['track'] == EMBARRASS_TRACK:
                # The fixed Lure angle keeps both the acting Toon and cushion
                # toss visible from start to finish.
                shot = MovieCamera.chooseLureReactionShot(
                    reaction['toon'], suitAttack['suit'], duration)
            else:
                shot = MovieCamera.chooseThrowSquirtReactionShot(
                    reaction['toon'], suitAttack['suit'], duration,
                    includeBehindToon=False)
        else:
            # Headless native contract tests deliberately create no camera.
            shot = Wait(duration)
        playByPlayText = reaction.get('playByPlayText')
        if playByPlayText:
            label = getReactiveGagName(
                reaction['track'], reaction['level'])
            shot = Parallel(
                shot,
                playByPlayText.getShowInterval(label, duration),
            )
        cameraTrack.append(shot)

    if len(track) == 0:
        return (None, None, False)
    return (track, cameraTrack, skipSuitAttack)
