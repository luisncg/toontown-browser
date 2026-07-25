"""Small Web Audio sound-bank bridge for the browser client.

The proxy intentionally implements the AudioSound surface used by Panda's
SoundInterval/SfxPlayer code. Sounds not present in the browser-published
manifest continue through the original Panda/OpenAL loader.
"""

from __future__ import annotations

import builtins
import json
import re
import time
import types

from panda3d.core import AudioSound


_READY_FILE = "/browser-short-audio-banks.json"
_SAFE_TOKEN_RE = re.compile(r"[^a-z0-9_-]+")
_metadata = None
_last_metadata_check = 0.0
_sounds = {}
_next_proxy_id = 1
_next_lease_id = 1
_active_leases = {}
_heartbeat_scheduled = False
_audio_hooks_installed = False


def _emit(message):
    print(message)


def _load_metadata():
    global _metadata, _last_metadata_check
    if _metadata is not None:
        return _metadata
    now = time.monotonic()
    if now - _last_metadata_check < 0.1:
        return None
    _last_metadata_check = now
    try:
        with open(_READY_FILE, "r", encoding="utf-8") as ready_file:
            value = json.load(ready_file)
        sounds = value.get("sounds")
        if value.get("version") != 1 or not isinstance(sounds, dict):
            return None
        _metadata = sounds
    except (OSError, ValueError, TypeError):
        return None
    return _metadata


def _safe_token(value, fallback):
    token = _SAFE_TOKEN_RE.sub(
        "-", str(value).lower().replace(".", "-")
    ).strip("-_")
    return (token[:48] or fallback)


def _current_lease_token():
    if not _active_leases:
        return "-"
    return next(reversed(_active_leases))


class BrowserAudioSound:
    """Duck-typed AudioSound backed by a decoded browser AudioBuffer."""

    def __init__(self, logical_name, metadata):
        global _next_proxy_id
        self.logical_name = logical_name
        self.metadata = metadata
        self.proxy_id = _next_proxy_id
        _next_proxy_id += 1
        self._loop = False
        self._volume = 1.0
        self._balance = 0.0
        self._play_rate = 1.0
        self._time = 0.0
        self._started_at = None
        self._stopped = True

    def length(self):
        return float(self.metadata["length"])

    def getName(self):
        return self.logical_name

    def play(self):
        if (
            not bool(getattr(builtins.base, "sfxActive", True))
            or not bool(getattr(builtins.base, "AppHasAudioFocus", True))
        ):
            self._stopped = True
            return
        self._started_at = time.monotonic()
        self._stopped = False
        _emit(
            "[BrowserWebAudioCommand] "
            "play %s %s %.6f %s %.6f %.6f %.6f %s"
            % (
                self.proxy_id,
                self.logical_name,
                max(0.0, self._time),
                1 if self._loop else 0,
                self._volume,
                self._play_rate,
                self._balance,
                _current_lease_token(),
            )
        )

    def stop(self):
        self._remember_time()
        self._stopped = True
        _emit("[BrowserWebAudioCommand] stop %s" % self.proxy_id)

    def status(self):
        if self._stopped or self._started_at is None:
            return AudioSound.READY
        if self._loop:
            return AudioSound.PLAYING
        elapsed = (
            (time.monotonic() - self._started_at) * self._play_rate
        )
        if self._time + elapsed < self.length():
            return AudioSound.PLAYING
        self._time = self.length()
        self._stopped = True
        return AudioSound.READY

    def _remember_time(self):
        if self._stopped or self._started_at is None:
            return
        elapsed = (
            (time.monotonic() - self._started_at) * self._play_rate
        )
        if self._loop and self.length() > 0:
            self._time = (self._time + elapsed) % self.length()
        else:
            self._time = min(self.length(), self._time + elapsed)
        self._started_at = None

    def setTime(self, value):
        self._time = min(self.length(), max(0.0, float(value)))
        self._started_at = (
            time.monotonic() if not self._stopped else None
        )

    def getTime(self):
        if self._stopped or self._started_at is None:
            return self._time
        elapsed = (
            (time.monotonic() - self._started_at) * self._play_rate
        )
        if self._loop and self.length() > 0:
            return (self._time + elapsed) % self.length()
        return min(self.length(), self._time + elapsed)

    def setLoop(self, value):
        self._loop = bool(value)

    def getLoop(self):
        return self._loop

    def setVolume(self, value):
        self._volume = min(4.0, max(0.0, float(value)))
        _emit(
            "[BrowserWebAudioCommand] volume %s %.6f"
            % (self.proxy_id, self._volume)
        )

    def getVolume(self):
        return self._volume

    def setPlayRate(self, value):
        self._remember_time()
        self._play_rate = min(4.0, max(0.05, float(value)))
        self._started_at = (
            time.monotonic() if not self._stopped else None
        )

    def getPlayRate(self):
        return self._play_rate

    def setBalance(self, value):
        self._balance = min(1.0, max(-1.0, float(value)))
        _emit(
            "[BrowserWebAudioCommand] balance %s %.6f"
            % (self.proxy_id, self._balance)
        )

    def getBalance(self):
        return self._balance


def get_sound(name):
    """Return a Web Audio proxy only when its decoded bank is ready."""
    metadata = _load_metadata()
    logical_name = str(name).replace("\\", "/").rsplit("/", 1)[-1].lower()
    sound_metadata = metadata.get(logical_name) if metadata else None
    if not isinstance(sound_metadata, dict):
        return None
    sound = _sounds.get(logical_name)
    if sound is None:
        try:
            sound = BrowserAudioSound(logical_name, sound_metadata)
            sound.length()
        except (KeyError, TypeError, ValueError):
            return None
        _sounds[logical_name] = sound
    return sound


def _lease_heartbeat_task(task):
    global _heartbeat_scheduled
    if not _active_leases:
        _heartbeat_scheduled = False
        return task.done
    for token in tuple(_active_leases):
        _emit("[BrowserWebAudioLease] heartbeat %s" % token)
    return task.again


def acquire_battle_lease(movie_id):
    """Acquire a tokenized lease that spans delayed battle sounds."""
    global _next_lease_id, _heartbeat_scheduled
    safe_movie_id = _safe_token(movie_id, "battle")
    token = "b%s_%s" % (_next_lease_id, safe_movie_id)
    _next_lease_id += 1
    _active_leases[token] = {
        "movieId": safe_movie_id,
        "acquiredAt": time.monotonic(),
    }
    _emit(
        "[BrowserWebAudioLease] acquire %s %s"
        % (token, safe_movie_id)
    )
    if not _heartbeat_scheduled:
        _heartbeat_scheduled = True
        builtins.base.taskMgr.doMethodLater(
            10.0,
            _lease_heartbeat_task,
            "browser-web-audio-lease-heartbeat",
        )
    return token


def release_battle_lease(token, reason="finish"):
    if token not in _active_leases:
        return False
    del _active_leases[token]
    _emit(
        "[BrowserWebAudioLease] release %s %s"
        % (token, _safe_token(reason, "cleanup"))
    )
    return True


def install_audio_state_hooks():
    """Mirror Panda's SFX/audio-focus state into the Web Audio master gain."""
    global _audio_hooks_installed
    if _audio_hooks_installed:
        return
    base = builtins.base
    original_enable_sfx = base.enableSoundEffects
    original_disable_all = base.disableAllAudio
    original_enable_all = base.enableAllAudio

    def enable_sound_effects(self, enabled):
        result = original_enable_sfx(enabled)
        active = bool(self.sfxActive and self.AppHasAudioFocus)
        _emit("[BrowserWebAudioCommand] enabled %s" % (1 if active else 0))
        return result

    def disable_all_audio(self):
        result = original_disable_all()
        _emit("[BrowserWebAudioCommand] enabled 0")
        return result

    def enable_all_audio(self):
        result = original_enable_all()
        active = bool(self.sfxActive and self.AppHasAudioFocus)
        _emit("[BrowserWebAudioCommand] enabled %s" % (1 if active else 0))
        return result

    base.enableSoundEffects = types.MethodType(enable_sound_effects, base)
    base.disableAllAudio = types.MethodType(disable_all_audio, base)
    base.enableAllAudio = types.MethodType(enable_all_audio, base)
    _audio_hooks_installed = True
    active = bool(base.sfxActive and base.AppHasAudioFocus)
    _emit("[BrowserWebAudioCommand] enabled %s" % (1 if active else 0))
