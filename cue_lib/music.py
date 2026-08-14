# -*- coding: utf-8 -*-
# CueMusicManager -- detect music play/queue/stop by wrapping renpy.audio.music.

import renpy
import renpy.audio.music as _music

from cue_lib.util import _cue_log

MYPY = False
if MYPY:
    from typing import Any, Dict, Optional

CUE_DEFAULT_MUSIC_CHANNEL = "music"

# True originals, cached once at module level so a Shift+R reload (which
# re-instantiates the manager but does NOT re-import this module) never
# captures our own wrapper as the "original" and double-wraps.
_ORIGINALS = None


class CueMusicManager(object):
    """Detects music play/queue/stop events; forwards all calls unchanged.

    All Ren'Py audio funnels through renpy.audio.music.play/.queue/.stop, so
    wrapping those three attributes observes every music change without
    touching the game. Records the last music-channel event on
    self.last_event and logs it (debug mode only); other channels are
    forwarded untouched."""

    def __init__(self):
        self._is_installed = False
        self.last_event = None  # type: Optional[Dict[str, Any]]

    def install(self):
        # type: () -> None
        global _ORIGINALS
        if _ORIGINALS is None:
            _ORIGINALS = (_music.play, _music.queue, _music.stop)
        self._original_music_play, self._original_music_queue, self._original_music_stop = _ORIGINALS
        if self._is_installed:
            return
        _music.play = self._on_play
        _music.queue = self._on_queue
        _music.stop = self._on_stop
        self._is_installed = True

    def _on_play(self, *args, **kwargs):
        # type: (Any, Any) -> Any
        self._record("play", args, kwargs, channel_offset=1)
        return self._original_music_play(*args, **kwargs)

    def _on_queue(self, *args, **kwargs):
        # type: (Any, Any) -> Any
        self._record("queue", args, kwargs, channel_offset=1)
        return self._original_music_queue(*args, **kwargs)

    def _on_stop(self, *args, **kwargs):
        # type: (Any, Any) -> Any
        self._record("stop", args, kwargs, channel_offset=0)
        return self._original_music_stop(*args, **kwargs)

    def _record(self, event_type, args, kwargs, channel_offset):
        # type: (str, tuple, dict, int) -> None
        try:
            if "channel" in kwargs:
                channel = kwargs["channel"]
            elif len(args) > channel_offset:
                channel = args[channel_offset]
            else:
                channel = CUE_DEFAULT_MUSIC_CHANNEL

            # Only the music channel counts as a music event.  Everything
            # else (sound, voice, movies, custom channels) shares these three
            # functions but is not music -- skip it so the log and last_event
            # stay music-only.  The wrapper still forwards every call.
            if channel != CUE_DEFAULT_MUSIC_CHANNEL:
                return

            filenames = None
            loop = None
            if event_type != "stop":
                filenames = kwargs.get("filenames", args[0] if args else None)
                loop = kwargs.get("loop")

            in_replay = getattr(renpy.store, "_in_replay", None)

            self.last_event = {
                "type": event_type,
                "channel": channel,
                "filenames": filenames,
                "loop": loop,
                "in_replay": in_replay,
            }
            # Log the full raw call so no argument is ever dropped.
            _cue_log("MUSIC-{} channel={} files={} loop={} in_replay={} args={} kwargs={}".format(
                event_type, channel, filenames, loop, in_replay, args, kwargs))
        except Exception:
            pass  # detection must never break audio
