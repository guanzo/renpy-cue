# -*- coding: utf-8 -*-
# CueMusicManager -- detect music play/queue/stop by wrapping renpy.audio.music.

import renpy
import renpy.audio.music as _music

from cue_lib.state import _cue
from cue_lib.audio.user_music import CueUserMusic
from cue_lib.util import _cue_log, create_img_key, create_vid_key

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional

CUE_DEFAULT_MUSIC_CHANNEL = "music"

# True originals, cached once at module level so a Shift+R load_triggers (which
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
        # replay_label -> [ {"key_before": ..., "filepath": ..., "key_after": ...}, ... ]  (mirror)
        self._triggers = {}
        # The play awaiting key_after: {"replay_id", "key_before", "filepath"}.
        self._pending = None  # type: Optional[Dict[str, Any]]
        # My Music page: tree expand/collapse state.
        self.user_music = CueUserMusic()

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

        # Load the default music trigger log from disk (one-time startup).
        self.load_triggers()

    def play_untracked(self, full_path, volume=1.0):
        # type: (str, float) -> None
        """Play a file on the music channel without recording a trigger.

        Used by the My Music page previews.  Goes straight to the cached
        original renpy.audio.music.play (bypassing the interceptor), so the
        call is never logged or recorded as a default music trigger.  Playing
        on the default music channel replaces whatever music is currently
        playing, which is the desired preview behavior.
        """
        if _cue._has_relative_volume:
            self._original_music_play(
                full_path, channel=CUE_DEFAULT_MUSIC_CHANNEL,
                loop=False, relative_volume=volume)
        else:
            self._original_music_play(
                full_path, channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=False)
            _music.set_volume(volume, delay=0, channel=CUE_DEFAULT_MUSIC_CHANNEL)

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
            if event_type != "stop":
                self._record_default_trigger(filenames, in_replay)
            # Log the full raw call so no argument is ever dropped.
            _cue_log("MUSIC-{} channel={} files={} loop={} in_replay={} args={} kwargs={}".format(
                event_type, channel, filenames, loop, in_replay, args, kwargs))
        except Exception:
            pass  # detection must never break audio

    # ------------------------------------------------------------------
    # Default music trigger log (per replay)
    # ------------------------------------------------------------------

    def load_triggers(self):
        # type: () -> None
        """Load the default music trigger log from disk into the mirror."""
        self._triggers = _cue.db.load_default_music_triggers()

    def triggers_for(self, replay_id):
        # type: (Optional[str]) -> List[Dict[str, str]]
        """List of {key_before, filepath, key_after?} for a replay, sorted by
        key_before, for the screen."""
        return sorted(self._triggers.get(replay_id or "", []), key=lambda it: it["key_before"])

    def _current_scene_key(self):
        # type: () -> str
        """i_/v_ key of the scene currently on screen ("" if none)."""
        if not _cue.current_file:
            return ""
        if _cue.top_layer_type == "movie":
            return create_vid_key(_cue.current_file)
        return create_img_key(_cue.current_file)

    def _record_default_trigger(self, filenames, in_replay):
        # type: (Any, Any) -> None
        """Record the default music for the scene on screen at this play call.

        `key_before` is the scene visible at the `play music` statement -- the
        anchor the future override also needs at `_on_play` time. The settled
        scene (`key_after`) is captured later by capture_display() once the
        scene batch lands. Writes through the DB's read-modify-write helper so
        unrelated replay entries are never clobbered.

        Rollback/roll-forward is skipped: it only re-executes statements that
        already played (and were recorded) forward, and _cue.current_file is
        NoRollback so the anchor would be computed from drifted state anyway.
        """
        if not in_replay or renpy.in_rollback():
            return
        if isinstance(filenames, (list, tuple)):
            if not filenames:
                return
            filenames = filenames[0]

        path = str(filenames).replace("\\", "/")
        if not path or not _cue.current_file:
            return
        key_before = self._current_scene_key()
        if not key_before:
            return

        items = self._triggers.setdefault(in_replay, [])
        for item in items:
            if item["key_before"] == key_before:
                item["filepath"] = path
                break
        else:
            items.append({"key_before": key_before, "filepath": path})

        self._pending = {"replay_id": in_replay, "key_before": key_before, "filepath": path}
        _cue.db.update_default_music_triggers(in_replay, key_before, path)

    def capture_display(self):
        # type: () -> None
        """Fill key_after (the settled scene) for the most recent play.

        Called from _cue_refresh_context once the scene batch has landed, so
        current_file reflects the scene the user actually sees. Skipped when
        the scene did not change (key_after would just equal key_before), when
        the replay ended before the scene landed, or during a rollback (where
        current_file is drifted NoRollback state).
        """
        if self._pending is None or renpy.in_rollback():
            return
        
        pending = self._pending
        self._pending = None
        if getattr(renpy.store, "_in_replay", None) != pending["replay_id"]:
            return
        key_after = self._current_scene_key()
        if not key_after or key_after == pending["key_before"]:
            return
        for item in self._triggers.get(pending["replay_id"], []):
            if item["key_before"] == pending["key_before"]:
                item["key_after"] = key_after
                break
        _cue.db.update_default_music_triggers(
            pending["replay_id"], pending["key_before"], pending["filepath"], key_after)
