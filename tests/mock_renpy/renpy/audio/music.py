# -*- coding: utf-8 -*-
"""Stateful mock of renpy.audio.music for unit tests.

A module-level channel registry tracks playback state. The public functions
read and write that registry, so tests can drive playback (CueVideoManager,
CueVidSpeedSequence) through the same calls the real engine uses.

Channels that were never registered keep the old static defaults (get_pos ->
0.0, get_duration -> 0.0, is_playing -> False, get_playing -> None), so tests
that don't care about audio state keep passing unchanged.

Tests advance playback by mutating `_registry` directly, e.g. to simulate the
engine switching to a queued file:
    music_mock._registry["video"]["playing"] = variant_path
or reset all state between tests:
    music_mock._reset_all()
"""

_registry = {}  # channel name -> state dict


def _state(channel):
    """Return the channel's state dict, creating it on first touch."""
    return _registry.setdefault(channel, {})


def _reset_all():
    """Clear the channel registry (call between tests)."""
    _registry.clear()


def get_pos(channel="music", **kwargs):
    st = _registry.get(channel)
    if st is None:
        return 0.0
    return st.get("position", 0.0)


def get_duration(channel="music", **kwargs):
    st = _registry.get(channel)
    if st is None:
        return 0.0
    return st.get("duration", 0.0)


def is_playing(channel="music", **kwargs):
    st = _registry.get(channel)
    if st is None:
        return False
    return st.get("playing") is not None and not st.get("paused", False)


def get_playing(channel="music", **kwargs):
    st = _registry.get(channel)
    if st is None:
        return None
    return st.get("playing")


def get_pause(channel="music", **kwargs):
    st = _registry.get(channel)
    if st is None:
        return False
    return st.get("paused", False)


def set_pause(value, channel="music", **kwargs):
    st = _registry.get(channel)
    if st is not None:
        st["paused"] = bool(value)


def set_volume(volume, delay=0, channel="music", **kwargs):
    st = _registry.get(channel)
    if st is not None:
        st["volume"] = volume


def register_channel(name, mixer=None, loop=None, stop_on_mute=None, tight=False, **kwargs):
    _state(name)["loop"] = loop


def channel_defined(name):
    return name in _registry


def play(filenames, channel="music", loop=None, **kwargs):
    st = _state(channel)
    st["playing"] = filenames
    st["queue"] = []
    st["position"] = 0.0
    st["paused"] = False
    if loop is not None:
        st["loop"] = loop


def stop(channel="music", **kwargs):
    st = _registry.get(channel)
    if st is not None:
        st["playing"] = None
        st["queue"] = []


def queue(filenames, channel="music", loop=None, clear_queue=True, **kwargs):
    """Enqueue a file for the next loop. Does NOT change what get_playing
    reports -- that only advances when the test (or the real engine, in the
    harness) actually starts the queued file via play() or a state write."""
    st = _state(channel)
    if clear_queue:
        st["queue"] = []
    st["queue"].append(filenames)
    if loop is not None:
        st["loop"] = loop
