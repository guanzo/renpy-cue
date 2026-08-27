# -*- coding: utf-8 -*-
# CueMusicManager -- detect music play/queue/stop by wrapping renpy.audio.music.

import random

import renpy
import renpy.audio.music as _music

from renpy.store import persistent

from cue_lib.state import _cue
from cue_lib.audio.wav_playable import CueWavPlayable
from cue_lib.audio.music_tree import CueMusicTree
from cue_lib.constants import (
    CUE_GAME_MUSIC_FOLDER,
    CUE_MUSIC_GAME_TAG,
    CUE_MUSIC_PREFIX,
    CUE_MUSIC_USER_TAG,
    CUE_MY_MUSIC_FOLDER,
    CUE_PERSIST_MUSIC_UI_STATE,
)
from cue_lib.util import (
    _cue_expand_folder_ref,
    _cue_is_abs_path,
    _cue_log,
    _cue_shift_held,
    _cue_strip_key_prefix,
    _cue_ui_refresh,
    _cue_unwrap_persistent,
    create_img_key,
    create_vid_key,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import DefaultMusicTrigger
    from cue_lib.marker_store import CueMarkerStore
    from cue_lib.state import CueContext
    from cue_lib.db import CueDatabase
    from cue_lib.paths import CuePaths

CUE_DEFAULT_MUSIC_CHANNEL = "music"

# Sentinel from _pick_for_override: play nothing (default disabled with no
# replacement songs).  Distinct from None (no override) and from a filepath.
_SUPPRESS_MUSIC = object()

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

    def __init__(self, ctx, store, db, paths):
        # type: (CueContext, CueMarkerStore, CueDatabase, CuePaths) -> None
        self._store = store
        self._ctx = ctx
        self._db = db
        self._paths = paths
        self._wav_playable = CueWavPlayable()
        self._is_installed = False
        self.last_event = None  # type: Optional[Dict[str, Any]]
        # replay_label -> [DefaultMusicTrigger, ...]  (mirror)
        self._triggers = {}  # type: Dict[str, List[DefaultMusicTrigger]]
        # The play awaiting key_after: {"replay_id", "key_before", "filepaths"}.
        self._pending = None  # type: Optional[Dict[str, Any]]
        # Marker key of the trigger selected in the Music page (the
        # target for "+" adds).  None = nothing selected.
        self.selected_key = None  # type: Optional[str]
        # Scene key at the last _resolve_selection() re-anchor, so a manual
        # pick survives until the scene changes and auto-select can re-aim.
        self._last_auto_scene = None  # type: Optional[str]
        # Trigger-box folder refs: folder_ref -> bool (expand/collapse).
        self.expanded_file_refs = {}  # type: Dict[str, bool]
        # Music Library: scans both My Music and Game Music and merges them
        # for display.  Owns the per-source trees and scan errors too.
        self.library = CueMusicTree(self)  # pyright: ignore[reportArgumentType]
        # CueRecentManager, wired after construction (records add-to-trigger
        # attempts; None before wiring so add_* stays safe).
        self._recent = None
        # Music presets: name -> {"files": [stored music refs, ...]}.  Stored
        # refs keep the u:/g: source tags (same data model as trigger lists).
        self._music_presets = {}  # type: Dict[str, Any]
        # Music Presets/ toggle + per-preset expand state in the Music Library.
        self.presets_expanded = False
        self.expanded_presets = {}  # type: Dict[str, bool]

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

        # Load the default music trigger log + presets from disk (one-time
        # startup).
        self.load_triggers()
        self.load_presets()

    def _playable_file(self, path):
        # type: (str) -> str
        """Route a user My Music WAV through the width converter.

        Game files (game-relative, archive paths) and non-WAV containers come
        back unchanged: only WAVs under the user music dir can have SDL_mixer's
        width problem, and only those are the user's to fix.  The converter
        passes non-WAV through untouched on its own, but this gate also keeps
        game/archive paths out of it entirely."""

        if not path.lower().endswith(".wav"):
            return path
        in_user_dir = path.startswith(self._paths.music_dir)
        in_external = any(path.startswith(root) for root in getattr(self.library, "external_folders", []) or [])
        if not (in_user_dir or in_external):
            return path
        return self._wav_playable.ensure_playable(path)

    def _convert_filename(self, fn):
        # type: (Any) -> Any
        """Gate a play() filename through the width converter.

        Ren'Py's music.play accepts a single path or a list of paths it tries
        in order (the movie channel, via movie_cutscene -> movie_start, passes a
        list).  A bare path is routed directly; a list is mapped per element, so
        every user WAV in the list is rerouted but game/non-WAV paths stay."""
        if hasattr(fn, "lower"):
            return self._playable_file(fn)
        return [self._playable_file(p) for p in fn]

    def _convert_play_file(self, args, kwargs):
        # type: (tuple, dict) -> tuple
        """Convert a play call's filename (args[0] or ``filenames`` kwarg) to
        its playable copy, if it is a user WAV.  Game and non-WAV filenames are
        untouched.  Returns fresh (args, kwargs) for playback; the caller records
        the original (unconverted) args/kwargs first, so a recorded trigger keeps
        the user path rather than a temp cache path."""
        if "filenames" in kwargs:
            new = dict(kwargs)
            new["filenames"] = self._convert_filename(new["filenames"])
            return args, new
        if args:
            return (self._convert_filename(args[0]),) + tuple(args[1:]), kwargs
        return args, kwargs

    def play_untracked(self, full_path, volume=1.0):
        # type: (str, float) -> None
        """Play a file on the music channel without recording a trigger.

        Used by the My Music page previews.  Goes straight to the cached
        original renpy.audio.music.play (bypassing the interceptor), so the
        call is never logged or recorded as a default music trigger.  Playing
        on the default music channel replaces whatever music is currently
        playing, which is the desired preview behavior.
        """
        full_path = self._playable_file(full_path)
        if _cue._has_relative_volume:
            self._original_music_play(full_path, channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=False, relative_volume=volume)
        else:
            self._original_music_play(full_path, channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=False)
            _music.set_volume(volume, delay=0, channel=CUE_DEFAULT_MUSIC_CHANNEL)

    def now_playing(self):
        # type: () -> Optional[str]
        """File currently playing on the music channel, or None.

        My Music files play from an absolute path under the shared root; they
        are reported as a display path under "My Music/" (the "music/" data
        prefix is stripped).  Game-music files play game-relative already and
        are reported under "Game Music/".  Both match the combined Music
        Library tree."""
        try:
            path = _music.get_playing(channel=CUE_DEFAULT_MUSIC_CHANNEL)
        except Exception:
            return None
        if not path:
            return None
        root = self._paths.root
        if path.startswith(root):
            path = path[len(root) :].lstrip("/")
            if path.startswith(CUE_MUSIC_PREFIX):
                path = path[len(CUE_MUSIC_PREFIX) :]
            return CUE_MY_MUSIC_FOLDER + path
        if _cue_is_abs_path(path):
            return self.library.ref_display_path(path)
        return CUE_GAME_MUSIC_FOLDER + path

    @property
    def is_paused(self):
        # type: () -> bool
        """True while the music channel is paused (live read)."""
        try:
            return bool(_music.get_pause(channel=CUE_DEFAULT_MUSIC_CHANNEL))
        except Exception:
            return False

    def toggle_pause(self):
        # type: () -> None
        """Pause or resume the current music channel track."""
        try:
            _music.set_pause(not self.is_paused, channel=CUE_DEFAULT_MUSIC_CHANNEL)
        except Exception:
            pass

    def default_display_path(self, path):
        # type: (str) -> str
        """Display path for a recorded default music filepath.

        Defaults are captured from the game's own `play music` calls, so the
        raw filepath is game-relative -- always shown under the synthetic
        Game Music/ root, never the user "music/" prefix."""
        return CUE_GAME_MUSIC_FOLDER + path

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
                play_args, play_kwargs = self._convert_play_file(args, kwargs)
                return self._original_music_play(*play_args, **play_kwargs)

        self._record("play", args, kwargs, channel_offset=1)
        play_args, play_kwargs = self._convert_play_file(args, kwargs)
        return self._original_music_play(*play_args, **play_kwargs)

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
            _cue_log(
                "MUSIC-{} channel={} files={} loop={} in_replay={} args={} kwargs={}".format(
                    event_type, channel, filenames, loop, in_replay, args, kwargs
                )
            )
        except Exception:
            pass  # detection must never break audio

    # ------------------------------------------------------------------
    # Default music trigger log (per replay)
    # ------------------------------------------------------------------

    def load_triggers(self):
        # type: () -> None
        """Load the default music trigger log from disk into the mirror."""
        self._triggers = self._db.load_default_music_triggers()

    def triggers_for(self, replay_id):
        # type: (Optional[str]) -> List[DefaultMusicTrigger]
        """List of default-music triggers for a replay, sorted by key_before,
        for the screen."""
        return sorted(self._triggers.get(replay_id or "", []), key=lambda it: it["key_before"])

    def _current_scene_key(self):
        # type: () -> str
        """i_/v_ key of the scene currently on screen ("" if none)."""
        if not self._ctx.current_file:
            return ""
        if self._ctx.top_layer_type == "movie":
            return create_vid_key(self._ctx.current_file)
        return create_img_key(self._ctx.current_file)

    def _record_default_trigger(self, filenames, in_replay):
        # type: (Any, Any) -> None
        """Record the default music for the scene on screen at this play call.

        `key_before` is the scene visible at the `play music` statement -- the
        anchor the future override also needs at `_on_play` time. The settled
        scene (`key_after`) is captured later by capture_display() once the
        scene batch lands. Writes through the DB's read-modify-write helper so
        unrelated replay entries are never clobbered.

        Rollback/roll-forward is skipped: it only re-executes statements that
        already played (and were recorded) forward, and self._ctx.current_file is
        NoRollback so the anchor would be computed from drifted state anyway.
        """
        if not in_replay or renpy.in_rollback():
            return
        # The full scripted list -- a `play music [a, b]` cycle keeps both
        # files so a default override can reproduce the cycle.
        if isinstance(filenames, (list, tuple)):
            if not filenames:
                return
            paths = [str(f).replace("\\", "/") for f in filenames]
        else:
            paths = [str(filenames).replace("\\", "/")]
        paths = [p for p in paths if p]
        if not paths or not self._ctx.current_file:
            return
        key_before = self._current_scene_key()
        if not key_before:
            return

        items = self._triggers.setdefault(in_replay, [])
        for item in items:
            if item["key_before"] == key_before:
                # Union, not replace: a `play A` then `queue [B, C]` in the
                # same scene accumulates every scripted track, and the queue's
                # list may omit the base track A.  Order-preserving, deduped.
                existing = item.get("filepaths") or []
                merged = []
                for p in existing + paths:
                    if p not in merged:
                        merged.append(p)
                item["filepaths"] = merged
                paths = merged
                break
        else:
            items.append({"key_before": key_before, "filepaths": list(paths)})

        self._pending = {"replay_id": in_replay, "key_before": key_before, "filepaths": list(paths)}
        self._db.update_default_music_triggers(in_replay, key_before, list(paths))

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
        self._db.update_default_music_triggers(
            pending["replay_id"], pending["key_before"], pending["filepaths"], key_after
        )

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
        entry = self._store.get(key)
        return entry is not None and entry.get("music") is not None and entry.get("replay", None) == replay_id

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
    def create_scene_trigger(self):
        # type: () -> Optional[str]
        """Create a trigger for the current scene and select it.

        The trigger is real and persists even while empty -- it appears
        immediately with an empty song list, and the tree "+" buttons add
        to it.  Returns the new key, or None when there's no scene to
        anchor one to.  Deleting it entirely is delete_trigger()'s job."""
        if not self._ctx.current_file:
            return None
        key = self._current_scene_key()
        entry = self._store._get_or_create_entry(key)
        entry.setdefault("music", [])
        self._store.save_marker(key)
        self.selected_key = key
        return key

    def default_path_for(self, key):
        # type: (str) -> Optional[List[str]]
        """Scripted default file list for a scene key, or None."""
        for trig in self._triggers.get(renpy.store._in_replay or "", []):
            if trig.get("key_after") == key or trig.get("key_before") == key:
                return trig.get("filepaths")
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
        """Expand a single folder ref into concrete stored-form file paths."""
        tag, ref = self._split_ref_tag(folder_ref)
        if tag == CUE_MUSIC_USER_TAG:
            self._expand_into(result, self.library.user_files, ref, CUE_MUSIC_USER_TAG)
        elif tag == CUE_MUSIC_GAME_TAG:
            self._expand_into(result, self.library.game_files, ref, CUE_MUSIC_GAME_TAG)
        elif _cue_is_abs_path(folder_ref):
            # External folder: no tag, expand the absolute path under the
            # external payload list (which holds bare absolute paths).
            for f in _cue_expand_folder_ref(self.library.external_files, ref):
                if f not in result:
                    result.append(f)
        else:
            # Legacy untagged ref -- ambiguous, match both caches (tagged so
            # every expanded child is stored-form).
            self._expand_into(result, self.library.user_files, ref, CUE_MUSIC_USER_TAG)
            self._expand_into(result, self.library.game_files, ref, CUE_MUSIC_GAME_TAG)

    def _expand_into(self, result, files, ref, tag):
        # type: (List[str], List[str], str, str) -> None
        """Append the files under `ref` in `files`, each tagged as stored-form."""
        for f in _cue_expand_folder_ref(files, ref):
            expanded = tag + f
            if expanded not in result:
                result.append(expanded)

    def _split_ref_tag(self, ref):
        # type: (str) -> Tuple[Optional[str], str]
        """Split a stored ref into (tag, path); tag is None if untagged.

        External refs carry no tag -- they are bare absolute paths, recognised
        by _cue_is_abs_path at the call sites that need to distinguish them."""
        if ref.startswith(CUE_MUSIC_USER_TAG):
            return CUE_MUSIC_USER_TAG, ref[len(CUE_MUSIC_USER_TAG) :]
        if ref.startswith(CUE_MUSIC_GAME_TAG):
            return CUE_MUSIC_GAME_TAG, ref[len(CUE_MUSIC_GAME_TAG) :]
        return None, ref

    def ref_path(self, ref):
        # type: (str) -> str
        """Stored ref without its source tag, for display."""
        return self._split_ref_tag(ref)[1]

    def _resolve_music_path(self, stored):
        # type: (str) -> str
        """Turn a stored music entry into a playable path.

        Ref sources are resolved by tag: "u:" (My Music) is root-relative
        under the shared music dir, "g:" (Game Music) is game-relative and
        plays directly.  A bare absolute path is an external ref and plays
        as-is.  No disk probing -- every ref is tagged or absolute, and the
        last branch is a non-probing fallback for stray legacy data."""
        tag, path = self._split_ref_tag(stored)
        if tag == CUE_MUSIC_USER_TAG:
            if path.startswith(CUE_MUSIC_PREFIX):
                path = path[len(CUE_MUSIC_PREFIX) :]
            return self._paths.music_dir + path
        if tag == CUE_MUSIC_GAME_TAG:
            return path
        if _cue_is_abs_path(stored):
            # External payload is already absolute.
            return stored
        # Untagged relative -- legacy only; default to the My Music layout.
        if path.startswith(CUE_MUSIC_PREFIX):
            path = path[len(CUE_MUSIC_PREFIX) :]
        return self._paths.music_dir + path

    def music_pool_for(self, scene_key):
        # type: (str) -> List[str]
        """Compose the playable music pool for a scene: the recorded default
        (unless disabled) plus the user-added custom songs, each resolved to
        a playable path.  Customization applies globally, across replays."""
        entry = self._store.get(scene_key)
        default_paths = self.default_path_for(scene_key)
        pool = []
        if default_paths and not (entry and entry.get("music_default_disabled")):
            pool.extend(default_paths)
        if entry:
            customs = entry.get("music")
            if customs:
                for c in self.resolve_music_files(customs):
                    pool.append(self._resolve_music_path(c))
        return pool

    @_cue_ui_refresh
    def add_user_song_to_trigger(self, path, record=True):
        # type: (str, bool) -> None
        """Add a My Music song to the selected trigger's music list.

        record=False (recently-used rows) suppresses the use feed."""
        self._add_ref_to_trigger(CUE_MUSIC_USER_TAG + path, record)

    @_cue_ui_refresh
    def add_game_song_to_trigger(self, path, record=True):
        # type: (str, bool) -> None
        """Add a Game Music song to the selected trigger's music list.

        record=False (recently-used rows) suppresses the use feed."""
        self._add_ref_to_trigger(CUE_MUSIC_GAME_TAG + path, record)

    @_cue_ui_refresh
    def add_user_folder_to_trigger(self, folder_path, record=True):
        # type: (str, bool) -> None
        """Add a whole My Music folder (a trailing-'/' ref) to the trigger.

        record=False (recently-used rows) suppresses the use feed."""
        self._add_ref_to_trigger(CUE_MUSIC_USER_TAG + folder_path.rstrip("/") + "/", record)

    @_cue_ui_refresh
    def add_game_folder_to_trigger(self, folder_path, record=True):
        # type: (str, bool) -> None
        """Add a whole Game Music folder (a trailing-'/' ref) to the trigger.

        record=False (recently-used rows) suppresses the use feed."""
        self._add_ref_to_trigger(CUE_MUSIC_GAME_TAG + folder_path.rstrip("/") + "/", record)

    @_cue_ui_refresh
    def add_external_song_to_trigger(self, abs_path, record=True):
        # type: (str, bool) -> None
        """Add an external-folder song (already absolute) to the trigger.

        Stored as a bare absolute path (no tag) so it resolves regardless of
        the external list's order."""
        self._add_ref_to_trigger(abs_path, record)

    @_cue_ui_refresh
    def add_external_folder_to_trigger(self, abs_folder, record=True):
        # type: (str, bool) -> None
        """Add a whole external-folder subfolder (a trailing-'/' ref).

        record=False (recently-used rows) suppresses the use feed."""
        self._add_ref_to_trigger(abs_folder.rstrip("/") + "/", record)

    def _add_ref_to_trigger(self, ref, record=True):
        # type: (str, bool) -> None
        """Append a music ref (a file path or a folder ref) to the selected
        trigger's music list."""
        # Record the add-to-trigger attempt (even for a ref already in the
        # list or a missing selection -- the user asked for it).  ref is the
        # exact stored form: source-tagged and folder-normalized.
        # record=False is passed by recently-used rows so acting from the
        # list doesn't re-feed it.
        if record:
            recent = self._recent
            if recent is not None:
                recent.record("folder" if ref.endswith("/") else "file", ref)
        self._resolve_selection()
        key = self.selected_key
        if not key:
            # No trigger selected: anchor a new one to the current scene so
            # the add still has a target.
            key = self.create_scene_trigger()
            if not key:
                return
        entry = self._store._get_or_create_entry(key)
        music = entry.setdefault("music", [])
        is_first_song = not music
        if ref not in music:
            music.append(ref)
        if is_first_song and self.default_path_for(key) and not entry.get("music_default_disabled"):
            entry["music_default_disabled"] = True
        self._store.save_marker(key)

    @_cue_ui_refresh
    def remove_song_from_trigger(self, key, path):
        # type: (str, str) -> None
        """Remove a custom song from a trigger's music list.

        Removing the last song leaves the trigger in place with an empty
        list -- an empty trigger is a legal state (it plays its
        default, or nothing if disabled).  delete_trigger() removes the
        whole trigger."""
        entry = self._store.get(key)
        if entry is None:
            return
        music = entry.get("music")
        if not music or path not in music:
            return
        music.remove(path)
        self._store.save_marker(key)

    @_cue_ui_refresh
    def toggle_file_ref_expand(self, folder_ref):
        # type: (str) -> None
        """Toggle expand/collapse for a folder ref in the trigger box."""
        if folder_ref in self.expanded_file_refs:
            self.expanded_file_refs[folder_ref] = not self.expanded_file_refs[folder_ref]
        else:
            self.expanded_file_refs[folder_ref] = True
        self.save_ui_state()

    @_cue_ui_refresh
    def remove_song_from_folder_ref(self, key, file_index, child_file):
        # type: (str, int, str) -> None
        """Detach one file from an expanded folder ref in a trigger.

        The folder ref is materialized into an explicit list of its remaining
        files (mirroring SFX _detach_folder_ref_in_files), so removing a child
        converts the folder ref into concrete entries minus that child."""
        entry = self._store.get(key)
        if entry is None:
            return
        music = entry.get("music")
        if not music or file_index >= len(music):
            return
        folder_ref = music[file_index]
        if not folder_ref.endswith("/"):
            return
        # resolve_music_files returns stored-form children (u:/g: tagged,
        # external bare absolute), ready to splice back in as-is.
        resolved = self.resolve_music_files([folder_ref])
        if child_file in resolved:
            resolved.remove(child_file)
        music[file_index : file_index + 1] = resolved
        self._store.save_marker(key)

    @_cue_ui_refresh
    def toggle_default(self, key):
        # type: (str) -> None
        """Flip whether the recorded default music plays for a scene."""
        entry = self._store._get_or_create_entry(key)
        entry["music_default_disabled"] = not entry.get("music_default_disabled", False)
        self._store.save_marker(key)

    @_cue_ui_refresh
    def delete_trigger(self, key):
        # type: (str) -> None
        """Delete a music trigger entirely: drop its songs and default-
        disable state.

        Only the music fields are removed -- the marker's other pools (SFX,
        video) are untouched -- so a default trigger simply reverts to
        playing its recorded default."""
        entry = self._store.get(key)
        if entry is None:
            return
        entry.pop("music", None)
        entry.pop("music_default_disabled", None)
        if self.selected_key == key:
            self.selected_key = None
            # Forget the anchor so the next render re-auto-selects whatever
            # trigger the current scene still has (if the scene keeps one).
            self._last_auto_scene = None
        self._store.save_marker(key)

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
            entry = self._store.get(key) or {}
            result.append(
                {
                    "key": key,
                    "label": _cue_strip_key_prefix(key),
                    "is_default": True,
                    "default_paths": trig.get("filepaths") or [],
                    "default_enabled": not entry.get("music_default_disabled", False),
                    "songs": entry.get("music") or [],
                    "selected": key == self.selected_key,
                }
            )

        # Every marker that carries a music list is a custom trigger (an
        # empty list still counts -- empty triggers are legal); list those
        # belonging to the current replay (skipping keys already shown as
        # default triggers) so the list stays replay-scoped.
        for key, entry in self._store.items():
            if key in seen:
                continue
            if entry.get("music") is None:
                continue
            if entry.get("replay", None) != replay_id:
                continue
            seen.add(key)
            result.append(
                {
                    "key": key,
                    "label": _cue_strip_key_prefix(key),
                    "is_default": False,
                    "default_paths": [],
                    "default_enabled": False,
                    "songs": entry.get("music") or [],
                    "selected": key == self.selected_key,
                }
            )
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
        entry = self._store.get(key_after)
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
                self._playable_file(random.choice(pool)), channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=True
            )

    # ------------------------------------------------------------------
    # Music presets -- saved trigger song lists (game-agnostic, like SFX)
    # ------------------------------------------------------------------

    def load_presets(self):
        # type: () -> None
        """Load all music presets from disk, replacing the in-memory set."""
        self._music_presets = self._db.load_music_presets()

    def reload_presets(self):
        # type: () -> None
        """Merge in music presets saved by other games since startup.

        Mirrors marker_store.reload_presets: new/updated presets from disk
        land, nothing in memory is ever deleted."""
        self._music_presets.update(self._db.load_music_presets())

    @_cue_ui_refresh
    def create_preset(self, name, songs):
        # type: (str, List[str]) -> None
        """Save a trigger's song list as a preset.  `songs` are stored refs."""
        self._music_presets[name] = {"files": list(songs)}
        self._db_save_music_preset(name)
        _cue_log("CREATE-MUSIC-PRESET name={} files={}".format(name, len(songs)))

    def get_preset(self, name):
        # type: (str) -> Optional[Dict[str, Any]]
        return self._music_presets.get(name)

    def list_presets(self):
        # type: () -> List[str]
        return sorted(self._music_presets.keys())

    @_cue_ui_refresh
    def delete_preset(self, name):
        # type: (str) -> None
        if name in self._music_presets:
            del self._music_presets[name]
            self.expanded_presets.pop(name, None)
            self._db_save_music_preset(name)
            _cue_log("DELETE-MUSIC-PRESET name={}".format(name))

    def _db_save_music_preset(self, name):
        # type: (str) -> None
        if name in self._music_presets:
            self._db.save_preset("music", name, self._music_presets[name])
        else:
            self._db.delete_preset("music", name)

    def songs_for_trigger(self, key):
        # type: (str) -> List[str]
        """Stored music refs of the trigger at `key` (empty if none).

        A copy, so the Save dialog editing it never mutates the trigger."""
        entry = self._store.get(key)
        if entry is None:
            return []
        return list(entry.get("music") or [])

    @_cue_ui_refresh
    def apply_preset(self, name):
        # type: (str) -> None
        """Apply a music preset to a trigger.

        Click replaces the selected trigger's song list.  Shift+Click applies
        to the scene on screen -- creating a custom trigger there first if the
        scene has none, else replacing that trigger (same as click)."""
        preset = self._music_presets.get(name)
        if preset is None:
            return
        files = preset.get("files", [])
        if _cue_shift_held():
            key = self._current_scene_key()
            if key and not self._current_scene_has_trigger(key):
                self.create_scene_trigger()
            self._set_trigger_songs(key, files)
        else:
            key = self._resolve_selection()
            self._set_trigger_songs(key or "", files)

    def _set_trigger_songs(self, key, files):
        # type: (str, List[str]) -> None
        """Replace the trigger at `key`'s song list ("" no-ops).  Mirrors
        _add_ref_to_trigger's first-song handling: adding songs to a scene
        with a recorded default disables the default."""
        if not key:
            return
        entry = self._store._get_or_create_entry(key)
        is_first_song = not entry.get("music")
        entry["music"] = list(files)
        if is_first_song and self.default_path_for(key) and not entry.get("music_default_disabled"):
            entry["music_default_disabled"] = True
        self._store.save_marker(key)

    @_cue_ui_refresh
    def preset_remove_file(self, name, display_path):
        # type: (str, str) -> None
        """Remove one file from a music preset, given its display path.

        `display_path` is what the preset rows show ("My Music/x.ogg" /
        "Game Music/bgm/x.ogg").  A direct ref is dropped outright; a file
        inside a stored folder ref materializes the folder without it
        (mirrors remove_song_from_folder_ref)."""
        preset = self._music_presets.get(name)
        if preset is None:
            return
        files = preset.get("files", [])
        if not files:
            return
        for ref in list(files):
            if not ref.endswith("/") and self.library.ref_display_path(ref) == display_path:
                files.remove(ref)
                self._db_save_music_preset(name)
                return
        for i, ref in enumerate(files):
            if ref.endswith("/") and display_path in self._folder_display_children(ref):
                # Children are stored-form; the display path drives the match,
                # and the surviving children splice back in as-is (no re-tag).
                resolved = [
                    r for r in self.resolve_music_files([ref]) if self.library.ref_display_path(r) != display_path
                ]
                files[i : i + 1] = resolved
                self._db_save_music_preset(name)
                return

    def preset_display_files(self, preset):
        # type: (Dict[str, Any]) -> List[str]
        """A preset's stored refs as concrete display paths, for its rows.

        Folder refs expand into their stored-form children, each rendered
        through ref_display_path.  Matches the rows the Music Presets/
        section renders."""
        out = []
        for ref in preset.get("files", []):
            if ref.endswith("/"):
                for child in self.resolve_music_files([ref]):
                    out.append(self.library.ref_display_path(child))
            else:
                out.append(self.library.ref_display_path(ref))
        return out

    def _folder_display_children(self, folder_ref):
        # type: (str) -> List[str]
        """Display paths of the files a stored folder ref resolves to."""
        return [self.library.ref_display_path(f) for f in self.resolve_music_files([folder_ref])]

    @_cue_ui_refresh
    def toggle_presets_expand(self):
        # type: () -> None
        """Flip the Music Presets/ folder in the Music Library."""
        self.presets_expanded = not self.presets_expanded
        self.save_ui_state()

    @_cue_ui_refresh
    def toggle_preset_expand(self, name):
        # type: (str) -> None
        """Flip expand/collapse for one preset's file rows."""
        if name in self.expanded_presets:
            self.expanded_presets[name] = not self.expanded_presets[name]
        else:
            self.expanded_presets[name] = True
        self.save_ui_state()

    def save_ui_state(self):
        # type: () -> None
        """Persist the Music Library's folder-UI toggle state."""
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[CUE_PERSIST_MUSIC_UI_STATE] = {
            "expanded_file_refs": dict(self.expanded_file_refs),
            "presets_expanded": self.presets_expanded,
            "expanded_presets": dict(self.expanded_presets),
        }

    def preview_preset(self, preset_name):
        # type: (str) -> None
        """Preview a random song from a music preset."""
        preset = self.get_preset(preset_name)
        if preset is None:
            return
        files = self.preset_display_files(preset)
        if files:
            f = random.choice(files)
            self.library.preview(f)

    def restore_ui_state(self):
        # type: () -> None
        """Overlay persisted Music Library folder-UI toggle state onto the attrs."""
        raw = (persistent._cue or {}).get(CUE_PERSIST_MUSIC_UI_STATE)
        blob = _cue_unwrap_persistent(raw) if raw is not None else None
        if not isinstance(blob, dict):
            return
        if isinstance(blob.get("expanded_file_refs"), dict):
            self.expanded_file_refs = dict(blob["expanded_file_refs"])
        if isinstance(blob.get("presets_expanded"), bool):
            self.presets_expanded = blob["presets_expanded"]
        if isinstance(blob.get("expanded_presets"), dict):
            self.expanded_presets = dict(blob["expanded_presets"])
