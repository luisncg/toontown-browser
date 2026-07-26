"""Browser bootstrap for the complete Open Toontown Python client."""

import builtins
import gc
import re
import time
from collections import OrderedDict
from urllib.parse import parse_qs, urlsplit

import browser_audio

try:
    from _browser_battle_sound_index import BATTLE_SOUND_PATHS
except ImportError:
    # Source/native diagnostics do not run the browser packaging generator.
    BATTLE_SOUND_PATHS = {}

from panda3d.core import (
    CullBinManager,
    Filename,
    WindowProperties,
    loadPrcFile,
    loadPrcFileData,
)


LOCAL_ASTRON_DEVELOPMENT = True
DEFAULT_BROWSER_GAME_SERVER = "ws://127.0.0.1:7200/astron"
BROWSER_GAME_SERVER_STORAGE_KEY = "open-toontown.game-server"
_BROWSER_RESUME_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{32,128}$')
_BROWSER_GATEWAY_LEASE_RE = re.compile(
    r'^v1(?:\.[A-Za-z0-9_-]+){3}$')
_BROWSER_AUTHORITY_RE = re.compile(r'^[a-f0-9]{32}$')


def _get_browser_game_server():
    """Return a browser-provided, tightly validated Astron gateway URL."""
    try:
        import browser_storage
    except ImportError:
        return DEFAULT_BROWSER_GAME_SERVER

    candidate = None
    try:
        candidate = browser_storage.get_runtime_game_server()
    except (AttributeError, RuntimeError):
        # Older launchers and native diagnostics do not expose the direct
        # browser-shell handoff. Keep localStorage as a compatibility fallback.
        pass
    if not candidate:
        try:
            candidate = browser_storage.get_item(
                BROWSER_GAME_SERVER_STORAGE_KEY)
        except (AttributeError, RuntimeError):
            return DEFAULT_BROWSER_GAME_SERVER

    if not candidate or not isinstance(candidate, str):
        return DEFAULT_BROWSER_GAME_SERVER
    if any(character.isspace() for character in candidate):
        return DEFAULT_BROWSER_GAME_SERVER

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
        query = parse_qs(
            parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return DEFAULT_BROWSER_GAME_SERVER
    resume_values = query.get('resume', ())
    lease_values = query.get('lease', ())
    authority_values = query.get('authority', ())
    query_names = set(query)
    allowed_query_names = (
        (
            {'resume'},
            {'resume', 'lease'},
            {'resume', 'lease', 'authority'},
        )
        if LOCAL_ASTRON_DEVELOPMENT
        else ({'resume', 'lease', 'authority'},)
    )
    if (
        parsed.scheme not in ('ws', 'wss')
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != '/astron'
        or query_names not in allowed_query_names
        or len(resume_values) != 1
        or not _BROWSER_RESUME_TOKEN_RE.fullmatch(resume_values[0])
        or (
            'lease' in query_names and (
                len(lease_values) != 1
                or len(lease_values[0]) > 2048
                or not _BROWSER_GATEWAY_LEASE_RE.fullmatch(lease_values[0])
            )
        )
        or (
            'authority' in query_names and (
                len(authority_values) != 1
                or not _BROWSER_AUTHORITY_RE.fullmatch(
                    authority_values[0])
            )
        )
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        return DEFAULT_BROWSER_GAME_SERVER
    return candidate


loadPrcFile("/etc/Configrc.prc")
loadPrcFileData(
    "browser-game-overrides",
    """
    window-type onscreen
    load-display p3webgldisplay
    audio-library-name p3openal_audio
    ignore-user-options 0
    toontown-auto-run false
    sync-video false
    framebuffer-srgb false
    textures-power-2 none
    m-dual false
    m-binary-alpha true
    browser-fix-dna-sign-order true
    vertex-buffers 1
    required-login auto
    want-gib-loader false
    browser-game-server %s
    notify-level warning
    default-directnotify-level info
    """ % _get_browser_game_server(),
)

_binManager = CullBinManager.getGlobalPtr()
if _binManager.findBin('browser-dna-sign') < 0:
    _binManager.addBin(
        'browser-dna-sign', CullBinManager.BTFixed, 25)

from toontown.launcher.ToontownDummyLauncher import ToontownDummyLauncher


builtins.launcher = ToontownDummyLauncher()


_browser_gc_started_at = {}


def _record_browser_gc_pause(phase, info):
    generation = int(info.get('generation', -1))
    if phase == 'start':
        _browser_gc_started_at[generation] = time.perf_counter()
        return
    started_at = _browser_gc_started_at.pop(generation, None)
    if phase != 'stop' or started_at is None:
        return
    elapsed_ms = int((time.perf_counter() - started_at) * 1000.0)
    if elapsed_ms >= 50:
        print('[BrowserPerformanceGC] %s %s' % (generation, elapsed_ms))


gc.callbacks.append(_record_browser_gc_pause)


_browser_frame_stage_started_at = None


def _record_browser_frame_stage(stage, task):
    """Report which Panda task-manager section owns a long browser frame."""
    global _browser_frame_stage_started_at
    now = time.perf_counter()
    if stage == 'start' or _browser_frame_stage_started_at is None:
        _browser_frame_stage_started_at = now
        return task.cont
    elapsed_ms = int((now - _browser_frame_stage_started_at) * 1000.0)
    _browser_frame_stage_started_at = now
    if elapsed_ms >= 100:
        print('[BrowserPerformanceFrameStage] %s %s' % (
            stage, elapsed_ms))
    return task.cont


def _install_browser_frame_stage_probes():
    # These sort boundaries surround Panda's interval, collision, render, and
    # audio tasks.  Six tiny probes are cheaper than full task profiling and
    # are only logged when a section takes at least 100 ms.
    for sort, stage in (
        (-100, 'start'),
        (19, 'tasks'),
        (21, 'interval'),
        (49, 'collision'),
        (51, 'render'),
        (1000, 'audio_late'),
    ):
        builtins.base.taskMgr.add(
            _record_browser_frame_stage,
            'browser-frame-stage-%s' % stage,
            sort=sort,
            extraArgs=[stage],
            appendTask=True,
        )

from toontown.toonbase import ToontownStart  # noqa: E402,F401
from otp.otpbase import OTPLocalizer  # noqa: E402
from direct.showbase.MessengerGlobal import messenger  # noqa: E402
from toontown.toonbase import KeybindSettings  # noqa: E402
from direct.interval.FunctionInterval import FunctionInterval  # noqa: E402
from direct.interval.IntervalManager import IntervalManager  # noqa: E402
from direct.interval.ActorInterval import ActorInterval  # noqa: E402
from direct.actor.Actor import Actor  # noqa: E402
from panda3d.direct import CIntervalManager  # noqa: E402
from toontown.battle import BattleParticles  # noqa: E402
from toontown.battle.BattleProps import PropPool, globalPropPool  # noqa: E402
from toontown.battle.BattleSounds import BattleSounds  # noqa: E402


_browser_interval_callback_names = frozenset((
    'loop',
    'play',
    'request',
    'setChatAbsolute',
    'setLocalPageChat',
    'setPageChat',
    'setPlayRate',
))


def _browser_interval_callback_name(function):
    """Return a privacy-safe callback category for interval telemetry."""
    name = getattr(function, '__name__', '')
    if name in _browser_interval_callback_names:
        return name
    if name.startswith('_recordBrowser'):
        return 'marker'
    if name in (
        'clearColorScale', 'clearDepthTest', 'clearDepthWrite',
        'clearHpr', 'clearPos', 'clearScale', 'hide', 'reparentFunc',
        'setColor', 'setColorScale', 'setDepthTest', 'setDepthWrite',
        'setHpr', 'setPos', 'setPosHpr', 'setPosHprScale', 'setScale',
        'show', 'wrtReparentFunc',
    ):
        return 'scene'
    return 'other'


_original_function_interval_priv_instant = FunctionInterval.privInstant


def _profile_browser_interval_function(self):
    started_at = time.perf_counter()
    try:
        return _original_function_interval_priv_instant(self)
    finally:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000.0)
        if elapsed_ms >= 50:
            print('[BrowserPerformanceIntervalFunction] %s %s' % (
                _browser_interval_callback_name(self.function), elapsed_ms))


def _profile_browser_interval_step(self):
    """Separate C++ interval stepping from external Python callbacks."""
    started_at = time.perf_counter()
    CIntervalManager.step(self)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000.0)
    if elapsed_ms >= 50:
        print('[BrowserPerformanceIntervalPhase] core %s' % elapsed_ms)

    started_at = time.perf_counter()
    try:
        self._IntervalManager__doPythonCallbacks()
    finally:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000.0)
        if elapsed_ms >= 50:
            print('[BrowserPerformanceIntervalPhase] callbacks %s' % (
                elapsed_ms))


FunctionInterval.privInstant = _profile_browser_interval_function
IntervalManager.step = _profile_browser_interval_step


def _browser_performance_token(value, fallback='other'):
    """Return a bounded asset/animation label safe for remote telemetry."""
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            return 'multiple'
        value = value[0]
    if value is True:
        return 'all'
    if value is None:
        return fallback
    token = str(value).replace('\\', '/').rsplit('/', 1)[-1].lower()
    token = re.sub('[^a-z0-9_.-]+', '-', token).strip('-.')
    return token[:64] or fallback


def _browser_actor_category(actor):
    """Classify an Actor without exposing its player-visible name."""
    className = actor.__class__.__name__.lower()
    if 'toon' in className:
        return 'toon'
    if 'suit' in className or 'cog' in className:
        return 'suit'
    try:
        if actor.getName() in globalPropPool.propTypes:
            return 'prop'
    except (AttributeError, TypeError):
        pass
    return 'actor'


_browser_prop_load_context = []
_original_prop_pool_get_prop = PropPool.getProp


def _profile_browser_battle_prop(self, name):
    token = _browser_performance_token(name)
    cold = name not in self.props
    _browser_prop_load_context.append(token)
    startedAt = time.perf_counter()
    try:
        return _original_prop_pool_get_prop(self, name)
    finally:
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        _browser_prop_load_context.pop()
        if cold or elapsedMs >= 20:
            print('[BrowserPerformanceBattleAsset] prop %s %s %s' % (
                token, 'cold' if cold else 'cached', elapsedMs))


_browser_battle_sound_requests = {}
_browser_battle_sound_refs = OrderedDict()
_BROWSER_BATTLE_SOUND_REF_LIMIT = 32


def _profile_browser_battle_sound(self, name):
    token = _browser_performance_token(name)
    requestCount = _browser_battle_sound_requests.get(token, 0) + 1
    _browser_battle_sound_requests[token] = requestCount
    requestStatus = 'first' if requestCount == 1 else 'repeat'
    startedAt = time.perf_counter()
    lookupStatus = 'fallback'
    resolveMs = 0
    managerMs = 0
    try:
        browserSound = browser_audio.get_sound(name)
        if browserSound is not None:
            lookupStatus = 'web_audio'
            return browserSound
        retainedSound = _browser_battle_sound_refs.get(token)
        if retainedSound is not None:
            lookupStatus = 'retained'
            _browser_battle_sound_refs.move_to_end(token)
            return retainedSound
        if self.isValid:
            indexedPath = BATTLE_SOUND_PATHS.get(str(name).lower())
            if indexedPath:
                lookupStatus = 'indexed'
                filename = Filename(indexedPath)
                found = True
            else:
                filename = Filename(name)
                resolveStartedAt = time.perf_counter()
                found = builtins.vfs.resolveFilename(
                    filename, self.sfxSearchPath)
                if not found:
                    self.setupSearchPath()
                    found = builtins.vfs.resolveFilename(
                        filename, self.sfxSearchPath)
                resolveMs = int(
                    (time.perf_counter() - resolveStartedAt) * 1000.0)
            if not found:
                self.notify.warning('%s not found on:' % name)
                print(self.sfxSearchPath)
            else:
                managerStartedAt = time.perf_counter()
                try:
                    sound = self.mgr.getSound(filename.getFullpath())
                    _browser_battle_sound_refs[token] = sound
                    _browser_battle_sound_refs.move_to_end(token)
                    while (
                            len(_browser_battle_sound_refs) >
                            _BROWSER_BATTLE_SOUND_REF_LIMIT):
                        _browser_battle_sound_refs.popitem(last=False)
                    return sound
                finally:
                    managerMs = int(
                        (time.perf_counter() - managerStartedAt) * 1000.0)
        return self.mgr.getNullSound()
    finally:
        totalMs = int((time.perf_counter() - startedAt) * 1000.0)
        print(
            '[BrowserPerformanceBattleSound] %s %s %s %s %s %s %s' % (
                token,
                requestStatus,
                requestCount,
                lookupStatus,
                resolveMs,
                managerMs,
                totalMs,
            ))
        print('[BrowserPerformanceBattleAsset] sound %s lookup %s' % (
            token, totalMs))


_original_battle_particles_load = BattleParticles.loadParticles
_original_battle_particles_unload = BattleParticles.unloadParticles
_original_battle_particle_file_load = BattleParticles.loadParticleFile
_browser_particle_config_code = {}
_browser_particle_config_requests = {}
_browser_particle_model_retained = False
_browser_particle_warmup_active = False


def _cache_browser_particle_config(name, indexedPath=None):
    """Compile a mounted PTF once so later attacks skip VFS read/compile."""
    token = _browser_performance_token(name)
    if token in _browser_particle_config_code:
        return
    pfile = Filename(indexedPath or name)
    if not pfile.isRegularFile():
        searchPath = BattleParticles.particleSearchPath
        if (
            searchPath is None
            or not builtins.vfs.resolveFilename(pfile, searchPath)
        ):
            return
    data = builtins.vfs.readFile(pfile, True).replace(b'\r', b'')
    _browser_particle_config_code[token] = compile(
        data,
        pfile.getFullpath(),
        'exec',
    )


def _profile_browser_battle_particles_load():
    global _browser_particle_model_retained
    cold = BattleParticles.particleModel is None
    startedAt = time.perf_counter()
    try:
        return _original_battle_particles_load()
    finally:
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        if BattleParticles.particleModel is not None:
            # The shared particle atlas is tiny and phase 3.5 is always
            # mounted. Keeping it avoids paying its first-use model/texture
            # setup again after every playground transition.
            _browser_particle_model_retained = True
        print('[BrowserPerformanceBattleParticle] model suit-particles %s %s' % (
            'cold' if cold else 'cached',
            elapsedMs,
        ))


def _preserve_browser_battle_particles():
    if (
        _browser_particle_model_retained
        and BattleParticles.particleModel is not None
    ):
        print(
            '[BrowserPerformanceBattleParticle] '
            'model suit-particles preserved 0'
        )
        return
    return _original_battle_particles_unload()


def _profile_browser_battle_particle_file(name):
    token = _browser_performance_token(name)
    requestCount = _browser_particle_config_requests.get(token, 0) + 1
    _browser_particle_config_requests[token] = requestCount
    cachedCode = _browser_particle_config_code.get(token)
    status = 'cached' if cachedCode is not None else 'cold'
    startedAt = time.perf_counter()
    try:
        if cachedCode is None:
            indexedPath = _BROWSER_COG_PARTICLE_PATHS.get(token)
            if indexedPath:
                # The preserved loader's phase search intentionally probes
                # older phases first. Exact VFS paths avoid four rounds of
                # browser 404s for every known phase-5 Cog particle config.
                effect = BattleParticles.ParticleEffect()
                effect.loadConfig(Filename(indexedPath))
            else:
                effect = _original_battle_particle_file_load(name)
            if effect is not None:
                _cache_browser_particle_config(name, indexedPath)
            return effect

        effect = BattleParticles.ParticleEffect()
        exec(
            cachedCode,
            BattleParticles.ParticleEffect.loadConfig.__globals__,
            {'self': effect},
        )
        return effect
    finally:
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        # The first cold and cached requests establish whether warmup worked.
        # Later requests are only interesting when they are measurably slow.
        if (
            not _browser_particle_warmup_active
            and (requestCount <= 2 or elapsedMs >= 20)
        ):
            print(
                '[BrowserPerformanceBattleParticle] config %s %s %s' % (
                    token,
                    status,
                    elapsedMs,
                )
            )


# These are the PTF files actually used by Cog attack movie construction and
# confirmed to live in phase 5. Finger Wag is first because production timing
# isolated it as the current MML stall. Work is spread across task frames.
_BROWSER_COG_PARTICLE_WARMUP = (
    'fingerwag.ptf',
    'smile.ptf',
    'synergy.ptf',
    'synergyWaterfall.ptf',
    'brainStorm.ptf',
    'buzzWord.ptf',
    'demotionSpray.ptf',
    'demotionFreeze.ptf',
    'demotionUnFreeze.ptf',
    'downsizeSpray.ptf',
    'downsizeCloud.ptf',
    'reorgSpray.ptf',
    'headShrinkSpray.ptf',
    'headShrinkCloud.ptf',
    'headShrinkDrop.ptf',
    'rollodexWaterfall.ptf',
    'rollodexStream.ptf',
    'doubleTalkLeft.ptf',
    'doubleTalkRight.ptf',
    'freezeAssets.ptf',
    'hotAirSpray.ptf',
    'firedBaseFlame.ptf',
    'firedFlame.ptf',
    'spriteFiredFlecks.ptf',
    'filibusterSpray.ptf',
    'schmoozeUpperSpray.ptf',
    'schmoozeLowerSpray.ptf',
    'shiftSpray.ptf',
    'pixieDrop.ptf',
    'powertrip.ptf',
    'powertrip2.ptf',
    'waterfall.ptf',
    'calculate.ptf',
    'numberSpill.ptf',
    'numberSpray.ptf',
    'liquidate.ptf',
    'withdrawal.ptf',
    'jargonSpray.ptf',
    'mumboJumboSpray.ptf',
    'mumboJumboSmother.ptf',
    'guiltTrip.ptf',
    'restrainingOrderCloud.ptf',
    'spinSpray.ptf',
    'spinEffect.ptf',
    'legaleseSpray.ptf',
    'fillWithLeadSpray.ptf',
    'fillWithLeadSmother.ptf',
    'penSpill.ptf',
)
_BROWSER_COG_ANIMATION_WARMUP = (
    'phase_5/models/char/suitA-fingerwag',
    'phase_5/models/char/suitB-finger-wag',
    'phase_5/models/char/suitC-finger-wag',
)
_BROWSER_COG_PARTICLE_PATHS = {
    name.lower(): '/resources/phase_5/etc/' + name
    for name in _BROWSER_COG_PARTICLE_WARMUP
}
_browser_cog_warmup_queue = None
_browser_cog_warmup_model_refs = []


def _browser_cog_warmup_safe():
    localAvatar = getattr(builtins.base, 'localAvatar', None)
    return localAvatar is None or not getattr(localAvatar, 'battleId', 0)


def _warm_browser_cog_battle_assets(task):
    """Warm one confirmed Cog dependency per tick after phase 5 mounts."""
    global _browser_cog_warmup_queue, _browser_particle_warmup_active
    if not builtins.launcher.getPhaseComplete(5):
        return task.again
    if not _browser_cog_warmup_safe():
        return task.again
    if _browser_cog_warmup_queue is None:
        _browser_cog_warmup_queue = [
            ('model', 'suit-particles'),
            ('config', _BROWSER_COG_PARTICLE_WARMUP[0]),
        ]
        _browser_cog_warmup_queue.extend(
            ('animation', path)
            for path in _BROWSER_COG_ANIMATION_WARMUP
        )
        _browser_cog_warmup_queue.extend(
            ('config', name)
            for name in _BROWSER_COG_PARTICLE_WARMUP[1:]
        )
    if not _browser_cog_warmup_queue:
        print('[BrowserPerformanceBattleParticle] warmup complete ready 0')
        return task.done

    kind, name = _browser_cog_warmup_queue.pop(0)
    token = _browser_performance_token(name)
    startedAt = time.perf_counter()
    status = 'ready'
    effect = None
    _browser_particle_warmup_active = True
    try:
        if kind == 'model':
            BattleParticles.loadParticles()
        elif kind == 'animation':
            _browser_cog_warmup_model_refs.append(
                builtins.base.loader.loadModel(name)
            )
        else:
            effect = BattleParticles.loadParticleFile(name)
            if effect is None:
                status = 'error'
    except Exception:
        status = 'error'
        print('[BrowserCogWarmup] failed %s %s' % (kind, token))
    finally:
        try:
            if effect is not None:
                effect.cleanup()
        except Exception:
            status = 'error'
            print('[BrowserCogWarmup] cleanup failed %s %s' % (kind, token))
        finally:
            _browser_particle_warmup_active = False
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        if (
            kind != 'config'
            or token == 'fingerwag.ptf'
            or status == 'error'
            or elapsedMs >= 20
        ):
            print('[BrowserPerformanceBattleParticle] warmup %s %s %s' % (
                token,
                status,
                elapsedMs,
            ))
    return task.again


_original_actor_load_model = Actor.loadModel
_original_actor_load_anims = Actor.loadAnims


def _profile_browser_actor_load_model(self, modelPath, *args, **kwargs):
    startedAt = time.perf_counter()
    try:
        return _original_actor_load_model(self, modelPath, *args, **kwargs)
    finally:
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        if _browser_prop_load_context and elapsedMs >= 20:
            print('[BrowserPerformanceBattleAsset] model %s load %s' % (
                _browser_performance_token(modelPath), elapsedMs))


def _profile_browser_actor_load_anims(self, anims, *args, **kwargs):
    startedAt = time.perf_counter()
    try:
        return _original_actor_load_anims(self, anims, *args, **kwargs)
    finally:
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        if _browser_prop_load_context and elapsedMs >= 20:
            names = list(anims) if isinstance(anims, dict) else anims
            print('[BrowserPerformanceBattleAsset] anims %s load %s' % (
                _browser_performance_token(names), elapsedMs))


_original_actor_get_anim_controls = Actor.getAnimControls


def _profile_browser_actor_get_anim_controls(
        self, animName=None, partName=None, lodName=None,
        allowAsyncBind=True, onlyPlaying=True):
    startedAt = time.perf_counter()
    controls = _original_actor_get_anim_controls(
        self,
        animName=animName,
        partName=partName,
        lodName=lodName,
        allowAsyncBind=allowAsyncBind,
        onlyPlaying=onlyPlaying,
    )
    elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
    if elapsedMs >= 20:
        print('[BrowserPerformanceAnimationBind] %s %s %s %s' % (
            _browser_actor_category(self),
            _browser_performance_token(animName),
            len(controls),
            elapsedMs,
        ))
    return controls


_original_actor_interval_init = ActorInterval.__init__


def _profile_browser_actor_interval_init(
        self, actor, animName, *args, **kwargs):
    startedAt = time.perf_counter()
    try:
        return _original_actor_interval_init(
            self, actor, animName, *args, **kwargs)
    finally:
        elapsedMs = int((time.perf_counter() - startedAt) * 1000.0)
        if elapsedMs >= 20:
            print('[BrowserPerformanceActorIntervalBuild] %s %s %s' % (
                _browser_actor_category(actor),
                _browser_performance_token(animName),
                elapsedMs,
            ))


PropPool.getProp = _profile_browser_battle_prop
BattleSounds.getSound = _profile_browser_battle_sound
BattleParticles.loadParticles = _profile_browser_battle_particles_load
BattleParticles.unloadParticles = _preserve_browser_battle_particles
BattleParticles.loadParticleFile = _profile_browser_battle_particle_file
Actor.loadModel = _profile_browser_actor_load_model
Actor.loadAnims = _profile_browser_actor_load_anims
Actor.getAnimControls = _profile_browser_actor_get_anim_controls
ActorInterval.__init__ = _profile_browser_actor_interval_init
browser_audio.install_audio_state_hooks()
builtins.base.taskMgr.doMethodLater(
    0.1,
    _warm_browser_cog_battle_assets,
    'browser-cog-battle-warmup',
)


def _report_browser_actor_animation(
        operation, controls, lookup_started_at, controls_started_at):
    """Report privacy-safe timing for Actor lookup versus control mutation."""
    controls_finished_at = time.perf_counter()
    lookup_ms = int((controls_started_at - lookup_started_at) * 1000.0)
    control_ms = int((controls_finished_at - controls_started_at) * 1000.0)
    if lookup_ms >= 50 or control_ms >= 50:
        print('[BrowserPerformanceActorAnimation] %s %s %s %s' % (
            operation, len(controls), lookup_ms, control_ms))


def _profile_browser_actor_set_play_rate(
        self, rate, animName, partName=None):
    lookup_started_at = time.perf_counter()
    controls = self.getAnimControls(animName, partName)
    controls_started_at = time.perf_counter()
    for control in controls:
        control.setPlayRate(rate)
    _report_browser_actor_animation(
        'setPlayRate', controls, lookup_started_at, controls_started_at)


def _profile_browser_actor_play(
        self, animName, partName=None, fromFrame=None, toFrame=None):
    lookup_started_at = time.perf_counter()
    controls = self.getAnimControls(animName, partName)
    controls_started_at = time.perf_counter()
    if fromFrame is None:
        for control in controls:
            control.play()
    elif toFrame is None:
        for control in controls:
            control.play(fromFrame, control.getNumFrames() - 1)
    else:
        for control in controls:
            control.play(fromFrame, toFrame)
    _report_browser_actor_animation(
        'play', controls, lookup_started_at, controls_started_at)


def _profile_browser_actor_loop(
        self, animName, restart=1, partName=None,
        fromFrame=None, toFrame=None):
    lookup_started_at = time.perf_counter()
    controls = self.getAnimControls(animName, partName)
    controls_started_at = time.perf_counter()
    if fromFrame is None:
        for control in controls:
            control.loop(restart)
    elif toFrame is None:
        for control in controls:
            control.loop(
                restart, fromFrame, control.getNumFrames() - 1)
    else:
        for control in controls:
            control.loop(restart, fromFrame, toFrame)
    _report_browser_actor_animation(
        'loop', controls, lookup_started_at, controls_started_at)


_profile_browser_actor_set_play_rate.__name__ = 'setPlayRate'
_profile_browser_actor_play.__name__ = 'play'
_profile_browser_actor_loop.__name__ = 'loop'
Actor.setPlayRate = _profile_browser_actor_set_play_rate
Actor.play = _profile_browser_actor_play
Actor.loop = _profile_browser_actor_loop


MOBILE_INPUT_ACTIONS = {
    1: 'forward',
    2: 'reverse',
    3: 'turnLeft',
    4: 'turnRight',
    5: 'sprint',
    6: 'jump',
    7: 'performAction',
    8: 'exitActivity',
    9: 'viewGags',
    10: 'viewToonTasks',
    11: 'viewStreetMap',
    12: 'switchPov',
}
MOBILE_INPUT_STATE_ACTIONS = frozenset((
    'forward',
    'reverse',
    'turnLeft',
    'turnRight',
    'sprint',
    'jump',
))
MOBILE_FORM_VALUE_ACTIONS = {
    20: 'username',
    21: 'password',
    22: 'confirmPassword',
}
MOBILE_FORM_FOCUS_ACTIONS = {
    24: 'username',
    25: 'password',
    26: 'confirmPassword',
}
MOBILE_FORM_SUBMIT_ACTION = 23


def _mobile_input_smoke_enabled():
    try:
        import browser_storage
        return (
            browser_storage.get_item(
                'open-toontown.mobile-controls-smoke') == '1'
        )
    except (ImportError, RuntimeError):
        return False


def _mobile_form_smoke_enabled():
    try:
        import browser_storage
        return (
            browser_storage.get_item(
                'open-toontown.mobile-form-smoke') == '1'
        )
    except (ImportError, RuntimeError):
        return False


def mobile_input(action_code, pressed):
    """Route a semantic touch action through Panda3D's normal input layer."""
    action_code = int(action_code)
    if action_code in MOBILE_FORM_VALUE_ACTIONS:
        if not pressed:
            return True
        screen = _active_mobile_form_screen()
        if screen is None:
            return False
        try:
            import browser_storage
            field = MOBILE_FORM_VALUE_ACTIONS[action_code]
            value = browser_storage.get_mobile_form_value(field)
        except (ImportError, RuntimeError):
            return False
        if not isinstance(value, str):
            return False
        handled = bool(screen.browserSetFormField(field, value))
        if handled and _mobile_form_smoke_enabled():
            print('[BrowserMobileFormTest] field=%s length=%s' % (
                field, len(value)))
        return handled

    if action_code in MOBILE_FORM_FOCUS_ACTIONS:
        if not pressed:
            return True
        screen = _active_mobile_form_screen()
        if screen is None:
            return False
        return bool(screen.browserFocusFormField(
            MOBILE_FORM_FOCUS_ACTIONS[action_code]))

    if action_code == MOBILE_FORM_SUBMIT_ACTION:
        if not pressed:
            return True
        screen = _active_mobile_form_screen()
        return bool(screen is not None and screen.browserSubmitForm())

    action = MOBILE_INPUT_ACTIONS.get(action_code)
    if action is None:
        return False
    active = bool(pressed)
    if action == 'switchPov':
        binding = 'tab'
    else:
        binding = KeybindSettings.getActiveBinding(action)

    if action in MOBILE_INPUT_STATE_ACTIONS:
        # Dispatch the player's actual configured key event.  Normal avatar
        # controls translate it into InputState, while trolley games and other
        # activities can consume the same event directly.  This keeps the
        # touch joystick and physical keyboard on one authoritative path.
        event = KeybindSettings.getActiveEvent(action, released=not active)
        messenger.send(event)
    else:
        if action == 'switchPov':
            event = binding + ('-up' if not active else '')
        else:
            event = KeybindSettings.getActiveEvent(
                action, released=not active)
        if action == 'performAction' and binding in ('delete', 'insert'):
            event = 'time-' + event
            messenger.send(event, [builtins.globalClock.getFrameTime()])
        else:
            messenger.send(event)

    if _mobile_input_smoke_enabled():
        print('[BrowserMobileInputTest] action=%s pressed=%s binding=%s' % (
            action, active, binding))
    return True


def _active_mobile_form_screen():
    cr = getattr(builtins.base, 'cr', None)
    if cr is None:
        return None
    login_fsm = getattr(cr, 'loginFSM', None)
    if login_fsm is None:
        return None
    login_state = login_fsm.getCurrentState()
    if login_state is None:
        return None
    state_name = login_state.getName()
    if state_name == 'login':
        screen = getattr(cr, 'loginScreen', None)
        required_inner_state = 'login'
    elif state_name == 'createAccount':
        screen = getattr(cr, 'createAccountScreen', None)
        required_inner_state = 'create'
    else:
        return None
    if screen is None:
        return None
    inner_state = screen.fsm.getCurrentState()
    if inner_state is None or inner_state.getName() != required_inner_state:
        return None
    return screen


_browser_render_resolution = None


def _desired_browser_render_resolution():
    """Keep portrait CSS and Panda's drawing buffer at the same aspect."""
    try:
        import browser_storage
        portrait = (
            browser_storage.get_item(
                'open-toontown.mobile-portrait-render') == '1'
        )
    except (ImportError, RuntimeError):
        portrait = False
    if portrait:
        return 768, 953

    resolution = builtins.base.settings.getSetting('resolution', (1024, 768))
    try:
        width, height = int(resolution[0]), int(resolution[1])
    except (IndexError, TypeError, ValueError):
        width, height = 1024, 768
    if width <= 0 or height <= 0:
        width, height = 1024, 768
    return width, height


def _sync_browser_render_resolution(task):
    """Reassert the correct buffer after CSS resize and phone rotation."""
    global _browser_render_resolution
    width, height = _desired_browser_render_resolution()
    if _browser_render_resolution == (width, height):
        return task.again
    properties = WindowProperties()
    properties.setSize(width, height)
    builtins.base.win.requestProperties(properties)
    _browser_render_resolution = (width, height)
    print('[BrowserDisplay] startup-resolution=%sx%s' % (width, height))
    return task.again


builtins.base.taskMgr.doMethodLater(
    0.25,
    _sync_browser_render_resolution,
    'browser-sync-render-resolution',
)


_mobile_controls_visible = None


def _normal_mobile_gameplay_visible():
    """Keep touch controls present for the entire authenticated game session."""
    cr = getattr(builtins.base, 'cr', None)
    local_avatar = getattr(builtins.base, 'localAvatar', None)
    if cr is None or local_avatar is None:
        return False

    login_state = cr.loginFSM.getCurrentState()
    return login_state is not None and login_state.getName() == 'playingGame'


def _sync_mobile_controls_visibility(task):
    global _mobile_controls_visible
    visible = _normal_mobile_gameplay_visible()
    if visible != _mobile_controls_visible:
        try:
            import browser_storage
            browser_storage.set_mobile_controls_visible(visible)
        except (ImportError, RuntimeError):
            return task.done
        _mobile_controls_visible = visible
    return task.again


builtins.base.taskMgr.doMethodLater(
    0.2,
    _sync_mobile_controls_visibility,
    'browser-sync-mobile-controls-visibility',
)


_mobile_form_state = None


def _current_mobile_form_state():
    screen = _active_mobile_form_screen()
    if screen is None:
        return 'none', '', False
    cr = builtins.base.cr
    login_state = cr.loginFSM.getCurrentState().getName()
    mode = 'login' if login_state == 'login' else 'createAccount'
    dialog = getattr(screen, 'dialog', None)
    interactive = dialog is None or dialog.isHidden()
    return mode, screen.nameEntry.get(), interactive


def _sync_mobile_form_state(task):
    global _mobile_form_state
    state = _current_mobile_form_state()
    if state != _mobile_form_state:
        try:
            import browser_storage
            browser_storage.set_mobile_form_state(*state)
        except (ImportError, RuntimeError):
            return task.done
        _mobile_form_state = state
    return task.again


builtins.base.taskMgr.doMethodLater(
    0.1,
    _sync_mobile_form_state,
    'browser-sync-mobile-form-state',
)


def _start_emote_67_smoke(task):
    """Run the opt-in visual smoke once a Toon reaches normal play."""
    try:
        import browser_storage
        enabled = (
            browser_storage.get_item('open-toontown.emote-67-smoke') == '1'
        )
    except (ImportError, RuntimeError):
        enabled = False
    if not enabled:
        return task.done

    localAvatar = getattr(builtins.base, 'localAvatar', None)
    cr = getattr(builtins.base, 'cr', None)
    playGame = getattr(cr, 'playGame', None) if cr else None
    place = playGame.getPlace() if playGame else None
    if (
        localAvatar is None
        or place is None
        or place.getState() != 'walk'
    ):
        return task.again
    try:
        triggered = (
            browser_storage.get_item(
                'open-toontown.emote-67-trigger') == '1'
        )
    except RuntimeError:
        triggered = False
    if not triggered:
        return task.again
    browser_storage.set_item('open-toontown.emote-67-trigger', '0')

    localAvatar._browserEmote67Smoke = True
    access = (
        len(localAvatar.emoteAccess) > 25
        and bool(localAvatar.emoteAccess[25])
    )
    print('[BrowserEmote67Test] registered=%s access=%s' % (
        OTPLocalizer.EmoteList[25], access))
    localAvatar.b_setSCEmote(25)
    return task.done


def _start_reactive_gag_ui_smoke(task):
    """Expose the real battle inventory UI for opt-in browser interaction."""
    try:
        import browser_storage
        enabled = (
            browser_storage.get_item('open-toontown.reactive-gag-smoke') == '1'
        )
    except (ImportError, RuntimeError):
        enabled = False
    if not enabled:
        return task.done

    localAvatar = getattr(builtins.base, 'localAvatar', None)
    cr = getattr(builtins.base, 'cr', None)
    playGame = getattr(cr, 'playGame', None) if cr else None
    place = playGame.getPlace() if playGame else None
    if localAvatar is None or place is None or place.getState() != 'walk':
        return task.again

    def selected(track, level):
        print('[BrowserReactiveGagTest] selected=%s:%s' % (track, level))

    def countsUpdated(counts):
        print('[BrowserReactiveGagTest] counts=%s:%s' % counts)

    builtins.base.accept('reactive-inventory-selection', selected)
    builtins.base.accept('reactive-gag-counts-updated', countsUpdated)
    localAvatar.inventory.setActivateMode(
        'battle', heal=1, trap=1, lure=1, bldg=0, creditLevel=7)
    localAvatar.inventory.show()
    # Production keeps the unfinished reactive picker hidden.  The explicit
    # browser smoke flag may expose it long enough to exercise the preserved
    # implementation without publishing the button to players.
    localAvatar.inventory.reactiveToggleButton.show()
    print('[BrowserReactiveGagTest] battle-menu-ready counts=%s:%s' % (
        localAvatar.getReactiveGagCounts()))
    return task.done


try:
    import browser_storage
    if browser_storage.get_item('open-toontown.emote-67-smoke') == '1':
        builtins.base.taskMgr.doMethodLater(
            0.5,
            _start_emote_67_smoke,
            'browser-emote-67-smoke')
    if browser_storage.get_item('open-toontown.reactive-gag-smoke') == '1':
        builtins.base.taskMgr.doMethodLater(
            0.5,
            _start_reactive_gag_ui_smoke,
            'browser-reactive-gag-ui-smoke')
except (ImportError, RuntimeError):
    pass


_install_browser_frame_stage_probes()


def frame():
    """Advance the full game's task manager from requestAnimationFrame."""
    builtins.base.taskMgr.step()
