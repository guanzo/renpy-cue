# -*- coding: utf-8 -*-
# CueMusicManager -- detect music play/queue/stop by wrapping renpy.audio.music.

import os
import random

import renpy
import renpy.audio.music as _music

from cue_lib.state import _cue
from cue_lib.audio.user_music import CueUserMusic
from cue_lib.audio.game_music import CueGameMusic
from cue_lib.constants import CUE_MUSIC_PREFIX
from cue_lib.util import _cue_log, _cue_strip_key_prefix, _cue_ui_refresh, create_img_key, create_vid_key

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple
    from cue_lib._types import DefaultMusicTrigger

CUE_DEFAULT_MUSIC_CHANNEL = "music"

# Sentinel from _pick_for_override: play nothing (default disabled with no
# replacement songs).  Distinct from None (no override) and from a filepath.
_SUPPRESS_MUSIC = object()

# Source tags for refs stored in a trigger's music list.  My Music and Game
# Music can both contain a "music/" folder, so a bare path is ambiguous.
# The tag records which cache the ref was added from, so resolution never
# has to probe the disk to tell them apart.  Tags are stripped before
# display and before playing.
CUE_MUSIC_USER_TAG = "u:"
CUE_MUSIC_GAME_TAG = "g:"

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
        # replay_label -> [DefaultMusicTrigger, ...]  (mirror)
        self._triggers = {}  # type: Dict[str, List[DefaultMusicTrigger]]
        # The play awaiting key_after: {"replay_id", "key_before", "filepath"}.
        self._pending = None  # type: Optional[Dict[str, Any]]
        # Marker key of the trigger selected in the Music page (the
        # target for "+" adds).  None = nothing selected.
        self.selected_key = None  # type: Optional[str]
        # Scene key at the last _resolve_selection() re-anchor, so a manual
        # pick survives until the scene changes and auto-select can re-aim.
        self._last_auto_scene = None  # type: Optional[str]
        # Trigger-box folder refs: folder_ref -> bool (expand/collapse).
        self.expanded_file_refs = {}  # type: Dict[str, bool]
        # My Music page: tree expand/collapse state.
        self.user_music = CueUserMusic()
        # Game Music page: discovered game audio, tree expand/collapse state.
        self.game_music = CueGameMusic()

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

    def now_playing(self):
        # type: () -> Optional[str]
        """File currently playing on the music channel, or None.

        My Music files play from an absolute path under the shared root; they
        are reported relative to it ("music/Folder/song.ogg") so the readout
        matches the Music page's tree.  Game-music files play game-relative
        already and are reported unchanged."""
        try:
            path = _music.get_playing(channel=CUE_DEFAULT_MUSIC_CHANNEL)
        except Exception:
            return None
        if not path:
            return None
        root = _cue.paths.root
        if path.startswith(root):
            path = path[len(root):].lstrip("/")
        return path

    def _on_play(self, *args, **kwargs):
        # type: (Any, Any) -> Any
        if "channel" in kwargs:
            channel = kwargs["channel"]
        elif len(args) > 1:
            channel = args[1]
        else:
            channel = CUE_DEFAULT_MUSIC_CHANNEL

        # Default-trigger override: a replay's `play music` is replaced by the
        # scene marker's music pool (or silenced).  Only the music channel is
        # touched; every other channel forwards unchanged.  The override is
        # skipped for _record so a replacement never re-records the trigger.
        if channel == CUE_DEFAULT_MUSIC_CHANNEL and renpy.store._in_replay:
            override = self._pick_for_override()

            if override is _SUPPRESS_MUSIC:
                self._original_music_stop(channel=CUE_DEFAULT_MUSIC_CHANNEL)
                return None
            if override is not None:
                if "filenames" in kwargs:
                    kwargs["filenames"] = override
                elif args:
                    args = (override,) + tuple(args[1:])
                return self._original_music_play(*args, **kwargs)

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

            in_replay = renpy.store._in_replay

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
        # type: (Optional[str]) -> List[DefaultMusicTrigger]
        """List of default-music triggers for a replay, sorted by key_before,
        for the screen."""
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
        if renpy.store._in_replay != pending["replay_id"]:
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

    # ------------------------------------------------------------------
    # Music trigger editing & override
    # ------------------------------------------------------------------
    #
    # A marker's `music` list holds user-added songs for a scene key; the
    # recorded default (if any) is NOT in it -- it lives in the trigger log
    # and its on/off state lives in `music_default_disabled`.  The playable
    # pool for a scene is always composed by music_pool_for().

    @_cue_ui_refresh
    def select_trigger(self, key):
        # type: (str) -> None
        """Select the trigger that "+" adds songs to."""
        self.selected_key = key

    def selected_trigger_label(self):
        # type: () -> str
        """Short label of the selected trigger for tooltips ("" if none)."""
        self._resolve_selection()
        if not self.selected_key:
            return ""
        return _cue_strip_key_prefix(self.selected_key)

    def _current_scene_has_trigger(self, key):
        # type: (str) -> bool
        """True if `key` is the key of a music trigger in the current replay:
        a default trigger anchored at the scene, or a custom marker carrying
        a music list for this replay.  Mirrors the set built by triggers()."""
        if not key:
            return False
        replay_id = renpy.store._in_replay
        for trig in self._triggers.get(replay_id or "", []):
            if trig.get("key_after") == key or trig.get("key_before") == key:
                return True
        entry = _cue.markers.get(key)
        return (
            entry is not None
            and entry.get("music") is not None
            and entry.get("replay", None) == replay_id
        )

    def _resolve_selection(self):
        # type: () -> Optional[str]
        """Reconcile the selected trigger with the scene on screen.

        Landing on a scene that has a trigger auto-selects it (so "+" adds
        and the triggers target the scene you're on).  A manual pick is
        respected until the next scene change, which re-anchors the selection
        to the new scene's trigger if it has one.  Returns the effective pick."""
        key = self._current_scene_key()
        if key != self._last_auto_scene:
            self._last_auto_scene = key
            if key and self._current_scene_has_trigger(key):
                self.selected_key = key
        return self.selected_key

    @_cue_ui_refresh
    def add_custom_trigger(self):
        # type: () -> None
        """Create a trigger for the current scene and select it.

        The trigger is real and persists even while empty -- it appears
        immediately with an empty song list, and the tree "+" buttons add
        to it.  Deleting it entirely is delete_trigger()'s job."""
        if not _cue.current_file:
            return
        key = self._current_scene_key()
        entry = _cue.markers._get_or_create_entry(key)
        entry.setdefault("music", [])
        _cue.markers.save_marker(key)
        self.selected_key = key

    def default_path_for(self, key):
        # type: (str) -> Optional[str]
        """Filepath of the recorded default music for a scene key, or None."""
        for trig in self._triggers.get(renpy.store._in_replay or "", []):
            if trig.get("key_after") == key or trig.get("key_before") == key:
                return trig.get("filepath")
        return None

    def _default_trigger_by_key_before(self, key_before):
        # type: (str) -> Optional[DefaultMusicTrigger]
        """The trigger log entry anchored at key_before, or None."""
        for trig in self._triggers.get(renpy.store._in_replay or "", []):
            if trig.get("key_before") == key_before:
                return trig
        return None

    def _is_default_trigger_scene(self, key):
        # type: (str) -> bool
        """True if the scene key is anchored by a default trigger for the
        current replay (scripted, handled via _on_play's override)."""
        for trig in self._triggers.get(renpy.store._in_replay or "", []):
            if trig.get("key_before") == key or trig.get("key_after") == key:
                return True
        return False

    def resolve_music_files(self, files):
        # type: (List[str]) -> List[str]
        """Expand folder refs (trailing '/') to matching available files.

        A tagged ref ("u:" My Music / "g:" Game Music) expands only against
        that cache; an untagged legacy ref expands against both.  Direct refs
        pass through unchanged; results are deduped."""
        result = []
        for item in files:
            if item.endswith("/"):
                self._resolve_folder_ref(item, result)
            elif item not in result:
                result.append(item)
        return result

    def _resolve_folder_ref(self, folder_ref, result):
        # type: (str, List[str]) -> None
        """Expand a single folder ref into concrete file paths."""
        tag, ref = self._split_ref_tag(folder_ref)
        if tag == CUE_MUSIC_USER_TAG:
            sources = [self.user_music.files]
        elif tag == CUE_MUSIC_GAME_TAG:
            sources = [self.game_music.files]
        else:
            # Legacy untagged ref -- ambiguous, match both caches.
            sources = [self.user_music.files, self.game_music.files]
        for files in sources:
            for f in files:
                if f.startswith(ref) and f not in result:
                    result.append(f)

    def _split_ref_tag(self, ref):
        # type: (str) -> Tuple[Optional[str], str]
        """Split a stored ref into (tag, path); tag is None if untagged."""
        if ref.startswith(CUE_MUSIC_USER_TAG):
            return CUE_MUSIC_USER_TAG, ref[len(CUE_MUSIC_USER_TAG):]
        if ref.startswith(CUE_MUSIC_GAME_TAG):
            return CUE_MUSIC_GAME_TAG, ref[len(CUE_MUSIC_GAME_TAG):]
        return None, ref

    def ref_path(self, ref):
        # type: (str) -> str
        """Stored ref without its source tag, for display."""
        return self._split_ref_tag(ref)[1]

    def _resolve_music_path(self, stored):
        # type: (str) -> str
        """Turn a stored music entry into a playable path.

        Tagged refs resolve by source: "u:" (My Music) is root-relative under
        the shared music dir, "g:" (Game Music) is game-relative and plays
        directly -- no disk check needed.  Untagged legacy refs fall back to
        the on-disk probe: a shared file exists under the music dir, a game
        file does not (it lives in the game's archive)."""
        tag, path = self._split_ref_tag(stored)
        if tag == CUE_MUSIC_USER_TAG:
            if path.startswith(CUE_MUSIC_PREFIX):
                path = path[len(CUE_MUSIC_PREFIX):]
            return _cue.paths.music_dir + path
        if tag == CUE_MUSIC_GAME_TAG:
            return path
        # Legacy untagged entry -- probe the disk to tell user from game.
        root = _cue.paths.root
        music_dir = _cue.paths.music_dir
        root_prefix = root.rstrip("/") + "/"
        if stored.startswith(root_prefix):
            stored = stored[len(root_prefix):]
        candidates = []
        if stored.startswith(CUE_MUSIC_PREFIX):
            candidates.append(stored[len(CUE_MUSIC_PREFIX):])
        candidates.append(stored)
        for rel in candidates:
            abs_path = music_dir + rel
            if os.path.isfile(abs_path):
                return abs_path
        return stored

    def music_pool_for(self, scene_key):
        # type: (str) -> List[str]
        """Compose the playable music pool for a scene: the recorded default
        (unless disabled) plus the user-added custom songs, each resolved to
        a playable path.  Customization applies globally, across replays."""
        entry = _cue.markers.get(scene_key)
        default_path = self.default_path_for(scene_key)
        pool = []
        if default_path and not (entry and entry.get("music_default_disabled")):
            pool.append(default_path)
        if entry:
            customs = entry.get("music")
            if customs:
                for c in self.resolve_music_files(customs):
                    pool.append(self._resolve_music_path(c))
        return pool

    @_cue_ui_refresh
    def add_user_song_to_trigger(self, path):
        # type: (str) -> None
        """Add a My Music song to the selected trigger's music list."""
        self._add_ref_to_trigger(CUE_MUSIC_USER_TAG + path)

    @_cue_ui_refresh
    def add_game_song_to_trigger(self, path):
        # type: (str) -> None
        """Add a Game Music song to the selected trigger's music list."""
        self._add_ref_to_trigger(CUE_MUSIC_GAME_TAG + path)

    @_cue_ui_refresh
    def add_user_folder_to_trigger(self, folder_path):
        # type: (str) -> None
        """Add a whole My Music folder (a trailing-'/' ref) to the trigger."""
        self._add_ref_to_trigger(CUE_MUSIC_USER_TAG + folder_path.rstrip("/") + "/")

    @_cue_ui_refresh
    def add_game_folder_to_trigger(self, folder_path):
        # type: (str) -> None
        """Add a whole Game Music folder (a trailing-'/' ref) to the trigger."""
        self._add_ref_to_trigger(CUE_MUSIC_GAME_TAG + folder_path.rstrip("/") + "/")

    def _add_ref_to_trigger(self, ref):
        # type: (str) -> None
        """Append a music ref (a file path or a folder ref) to the selected
        trigger's music list."""
        self._resolve_selection()
        key = self.selected_key
        if not key:
            return
        entry = _cue.markers._get_or_create_entry(key)
        music = entry.setdefault("music", [])
        is_first_song = not music
        if ref not in music:
            music.append(ref)
        if is_first_song and self.default_path_for(key) and not entry.get("music_default_disabled"):
            entry["music_default_disabled"] = True
        _cue.markers.save_marker(key)

    @_cue_ui_refresh
    def remove_song_from_trigger(self, key, path):
        # type: (str, str) -> None
        """Remove a custom song from a trigger's music list.

        Removing the last song leaves the trigger in place with an empty
        list -- an empty trigger is a legal state (it plays its
        default, or nothing if disabled).  delete_trigger() removes the
        whole trigger."""
        entry = _cue.markers.get(key)
        if entry is None:
            return
        music = entry.get("music")
        if not music or path not in music:
            return
        music.remove(path)
        _cue.markers.save_marker(key)

    @_cue_ui_refresh
    def toggle_file_ref_expand(self, folder_ref):
        # type: (str) -> None
        """Toggle expand/collapse for a folder ref in the trigger box."""
        if folder_ref in self.expanded_file_refs:
            self.expanded_file_refs[folder_ref] = not self.expanded_file_refs[folder_ref]
        else:
            self.expanded_file_refs[folder_ref] = True

    @_cue_ui_refresh
    def remove_song_from_folder_ref(self, key, file_index, child_file):
        # type: (str, int, str) -> None
        """Detach one file from an expanded folder ref in a trigger.

        The folder ref is materialized into an explicit list of its remaining
        files (mirroring SFX _detach_folder_ref_in_files), so removing a child
        converts the folder ref into concrete entries minus that child."""
        entry = _cue.markers.get(key)
        if entry is None:
            return
        music = entry.get("music")
        if not music or file_index >= len(music):
            return
        folder_ref = music[file_index]
        if not folder_ref.endswith("/"):
            return
        tag, _ = self._split_ref_tag(folder_ref)
        resolved = self.resolve_music_files([folder_ref])
        if child_file in resolved:
            resolved.remove(child_file)
        if tag:
            resolved = [tag + f for f in resolved]
        music[file_index:file_index + 1] = resolved
        _cue.markers.save_marker(key)

    @_cue_ui_refresh
    def toggle_default(self, key):
        # type: (str) -> None
        """Flip whether the recorded default music plays for a scene."""
        entry = _cue.markers._get_or_create_entry(key)
        entry["music_default_disabled"] = not entry.get("music_default_disabled", False)
        _cue.markers.save_marker(key)

    @_cue_ui_refresh
    def delete_trigger(self, key):
        # type: (str) -> None
        """Delete a music trigger entirely: drop its songs and default-
        disable state.

        Only the music fields are removed -- the marker's other pools (SFX,
        video) are untouched -- so a default trigger simply reverts to
        playing its recorded default."""
        entry = _cue.markers.get(key)
        if entry is None:
            return
        entry.pop("music", None)
        entry.pop("music_default_disabled", None)
        if self.selected_key == key:
            self.selected_key = None
            # Forget the anchor so the next render re-auto-selects whatever
            # trigger the current scene still has (if the scene keeps one).
            self._last_auto_scene = None
        _cue.markers.save_marker(key)

    def triggers(self):
        # type: () -> List[Dict[str, Any]]
        """Build the selectable music triggers for the current replay.

        One trigger per recorded default (deduped by scene key), each showing
        that marker's (global) customization, plus one trigger per custom
        trigger -- a scene key with a music list, possibly empty -- created in
        the current replay, so custom triggers stay scoped to the replay being
        viewed.  An empty trigger is a legal state and still shows up.
        """
        result = []  # type: List[Dict[str, Any]]
        seen = set()
        replay_id = renpy.store._in_replay
        # Auto-select the current scene's trigger (on scene change) before the
        # triggers are built, so the highlight and "+" target agree with what
        # the user is looking at.
        self._resolve_selection()
        for trig in self._triggers.get(replay_id or "", []):
            key = trig.get("key_after") or trig.get("key_before")
            if not key or key in seen:
                continue
            seen.add(key)
            entry = _cue.markers.get(key) or {}
            result.append({
                "key": key,
                "label": _cue_strip_key_prefix(key),
                "is_default": True,
                "default_path": trig.get("filepath"),
                "default_enabled": not entry.get("music_default_disabled", False),
                "songs": entry.get("music") or [],
                "selected": key == self.selected_key,
            })

        # Every marker that carries a music list is a custom trigger (an
        # empty list still counts -- empty triggers are legal); list those
        # belonging to the current replay (skipping keys already shown as
        # default triggers) so the list stays replay-scoped.
        for key, entry in _cue.markers.items():
            if key in seen:
                continue
            if entry.get("music") is None:
                continue
            if entry.get("replay", None) != replay_id:
                continue
            seen.add(key)
            result.append({
                "key": key,
                "label": _cue_strip_key_prefix(key),
                "is_default": False,
                "default_path": None,
                "default_enabled": False,
                "songs": entry.get("music") or [],
                "selected": key == self.selected_key,
            })
        return result

    def _pick_for_override(self):
        # type: () -> Any
        """Resolve what a default-trigger scene should play.

        Returns a filepath (random pick from the marker's music pool), the
        _SUPPRESS_MUSIC sentinel (default disabled, no replacements), or None
        (untouched -- forward the scripted default unchanged).
        """
        key_before = self._current_scene_key()
        if not key_before:
            return None
        trig = self._default_trigger_by_key_before(key_before)
        if trig is None:
            return None
        key_after = trig.get("key_after") or key_before
        entry = _cue.markers.get(key_after)
        if entry is None or (entry.get("music") is None and not entry.get("music_default_disabled")):
            return None
        pool = self.music_pool_for(key_after)
        if pool:
            return random.choice(pool)
        return _SUPPRESS_MUSIC

    def play_custom_music(self):
        # type: () -> None
        """Play a custom-trigger scene's music on scene change.

        Called from _cue_refresh_context once the settled scene is known.
        Default-trigger scenes are skipped -- the script's `play music`
        statement (with _on_play's override) handles those.
        """
        if renpy.in_rollback():
            return
        key = self._current_scene_key()
        if not key or self._is_default_trigger_scene(key):
            return
        pool = self.music_pool_for(key)
        if pool:
            self._original_music_play(
                random.choice(pool),
                channel=CUE_DEFAULT_MUSIC_CHANNEL,
                loop=True)
