# -*- coding: utf-8 -*-
# CueMusicManager -- detect music play/queue/stop by wrapping renpy.audio.music.
#
# The manager keeps the channel interception and playback helpers; the trigger
# log + editing (CueMusicTriggers), preset screen behavior (CueMusicPresetsUi),
# and stored-ref resolution (cue_lib.music.refs) live in sibling modules.  The
# flat _triggers/_pending/selection/expand attributes are delegates so the old
# manager-level API (tests, screens) keeps working unchanged.

import renpy
import renpy.audio.music as _music

from renpy.store import persistent

from cue_lib.state import _cue
from cue_lib.audio.wav_playable import CueWavPlayable
from cue_lib.audio.tree.music_tree import CueMusicTree
from cue_lib.constants import (
    CUE_DEFAULT_MUSIC_CHANNEL,
    CUE_GAME_MUSIC_FOLDER,
    CUE_MUSIC_PREFIX,
    CUE_MY_MUSIC_FOLDER,
    CUE_PERSIST_MUSIC_UI_STATE,
)
from cue_lib.music.presets import CueMusicPresetsUi
from cue_lib.music.refs import _cue_ref_path, _cue_resolve_music_files, _cue_resolve_music_path, _cue_split_ref_tag
from cue_lib.music.triggers import _SUPPRESS_MUSIC, CueMusicTriggers
from cue_lib.preset_store import CuePresetStore
from cue_lib.util import _cue_is_abs_path, _cue_log, _cue_ui_refresh, _cue_unwrap_persistent

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import DefaultMusicTrigger
    from cue_lib.marker_store import CueMarkerStore
    from cue_lib.state import CueContext
    from cue_lib.db import CueDatabase
    from cue_lib.paths import CuePaths

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

    def __init__(self, ctx, store, db, paths, presets=None):
        # type: (CueContext, CueMarkerStore, CueDatabase, CuePaths, Optional[CuePresetStore]) -> None
        self._store = store
        self._ctx = ctx
        self._db = db
        self._paths = paths
        # Music preset data + CRUD lives in the shared CuePresetStore.music
        # collection; the manager keeps library/trigger behaviors.  Built here
        # when the store isn't injected (tests, standalone use).
        self._presets = presets if presets is not None else CuePresetStore(self._db, None)
        self._wav_playable = CueWavPlayable()
        self._is_installed = False
        self.last_event = None  # type: Optional[Dict[str, Any]]
        # Music Library: scans both My Music and Game Music and merges them
        # for display.  Owns the per-source trees and scan errors too.
        self.library = CueMusicTree(self)  # pyright: ignore[reportArgumentType]
        # CueRecentManager, wired after construction (records add-to-trigger
        # attempts; None before wiring so add_* stays safe).
        self._recent = None
        # Trigger log + editing + override, and preset screen behavior.
        self._triggers_man = CueMusicTriggers(self)  # pyright: ignore[reportArgumentType]
        self._presets_ui = CueMusicPresetsUi(self)  # pyright: ignore[reportArgumentType]

    # ------------------------------------------------------------------
    # Delegated trigger/preset state (flat manager-level access)
    # ------------------------------------------------------------------

    @property
    def _triggers(self):
        # type: () -> Dict[str, List[DefaultMusicTrigger]]
        """Read-through to the trigger sub-manager's mirror (test/legacy)."""
        return self._triggers_man._triggers

    @_triggers.setter
    def _triggers(self, value):
        # type: (Dict[str, List[DefaultMusicTrigger]]) -> None
        self._triggers_man._triggers = value

    @property
    def _pending(self):
        # type: () -> Optional[Dict[str, Any]]
        """Read-through to the trigger sub-manager's pending play (test/legacy)."""
        return self._triggers_man._pending

    @_pending.setter
    def _pending(self, value):
        # type: (Optional[Dict[str, Any]]) -> None
        self._triggers_man._pending = value

    @property
    def selected_key(self):
        # type: () -> Optional[str]
        """Read-through to the trigger sub-manager's selected trigger key."""
        return self._triggers_man.selected_key

    @selected_key.setter
    def selected_key(self, value):
        # type: (Optional[str]) -> None
        self._triggers_man.selected_key = value

    @property
    def _last_auto_scene(self):
        # type: () -> Optional[str]
        """Read-through to the trigger sub-manager's last auto-select scene."""
        return self._triggers_man._last_auto_scene

    @_last_auto_scene.setter
    def _last_auto_scene(self, value):
        # type: (Optional[str]) -> None
        self._triggers_man._last_auto_scene = value

    @property
    def expanded_file_refs(self):
        # type: () -> Dict[str, bool]
        """Read-through to the trigger sub-manager's trigger-box expand state."""
        return self._triggers_man.expanded_file_refs

    @expanded_file_refs.setter
    def expanded_file_refs(self, value):
        # type: (Dict[str, bool]) -> None
        self._triggers_man.expanded_file_refs = value

    @property
    def presets_expanded(self):
        # type: () -> bool
        """Read-through to the preset sub-manager's Music Presets/ expand state."""
        return self._presets_ui.presets_expanded

    @presets_expanded.setter
    def presets_expanded(self, value):
        # type: (bool) -> None
        self._presets_ui.presets_expanded = value

    @property
    def expanded_presets(self):
        # type: () -> Dict[str, bool]
        """Read-through to the preset sub-manager's per-preset expand state."""
        return self._presets_ui.expanded_presets

    @expanded_presets.setter
    def expanded_presets(self, value):
        # type: (Dict[str, bool]) -> None
        self._presets_ui.expanded_presets = value

    @property
    def _music_presets(self):
        # type: () -> Dict[str, Any]
        """Read-through to the CueMusicPresets dict (kept for test/legacy
        access; CRUD goes through the manager methods)."""
        return self._presets.music._presets

    @_music_presets.setter
    def _music_presets(self, value):
        # type: (Dict[str, Any]) -> None
        self._presets.music._presets = value

    # ------------------------------------------------------------------
    # Interception
    # ------------------------------------------------------------------

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
        self._triggers_man.load_triggers()
        self._presets.music.load()

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
        """Play a file on the music channel without recording a trigger."""
        full_path = self._playable_file(full_path)
        if _cue._has_relative_volume:
            self._original_music_play(full_path, channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=False, relative_volume=volume)
        else:
            self._original_music_play(full_path, channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=False)
            _music.set_volume(volume, delay=0, channel=CUE_DEFAULT_MUSIC_CHANNEL)

    def now_playing(self):
        # type: () -> Optional[str]
        """File currently playing on the music channel, or None."""
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
            return self.library.display_for_ref(path)
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
        """Display path for a recorded default music filepath."""
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
            override = self._triggers_man._pick_for_override()

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
                self._triggers_man._record_default_trigger(filenames, in_replay)
            # Log the full raw call so no argument is ever dropped.
            _cue_log(
                "MUSIC-{} channel={} files={} loop={} in_replay={} args={} kwargs={}".format(
                    event_type, channel, filenames, loop, in_replay, args, kwargs
                )
            )
        except Exception:
            pass  # detection must never break audio

    # ------------------------------------------------------------------
    # Delegates: trigger log + editing + override (CueMusicTriggers)
    # ------------------------------------------------------------------

    def load_triggers(self):
        # type: () -> None
        """Load the default music trigger log from disk into the mirror."""
        self._triggers_man.load_triggers()

    def triggers_for(self, replay_id):
        # type: (Optional[str]) -> List[DefaultMusicTrigger]
        """List of default-music triggers for a replay, sorted by key_before."""
        return self._triggers_man.triggers_for(replay_id)

    def _current_scene_key(self):
        # type: () -> str
        """i_/v_ key of the scene currently on screen ("" if none)."""
        return self._triggers_man._current_scene_key()

    def capture_display(self):
        # type: () -> None
        """Fill key_after (the settled scene) for the most recent play."""
        self._triggers_man.capture_display()

    @_cue_ui_refresh
    def select_trigger(self, key):
        # type: (str) -> None
        """Select the trigger that "+" adds songs to."""
        self._triggers_man.select_trigger(key)

    def selected_trigger_label(self):
        # type: () -> str
        """Short label of the selected trigger for tooltips ("" if none)."""
        return self._triggers_man.selected_trigger_label()

    def _current_scene_has_trigger(self, key):
        # type: (str) -> bool
        """True if `key` is a music trigger key in the current replay."""
        return self._triggers_man._current_scene_has_trigger(key)

    def _resolve_selection(self):
        # type: () -> Optional[str]
        """Reconcile the selected trigger with the scene on screen."""
        return self._triggers_man._resolve_selection()

    @_cue_ui_refresh
    def create_scene_trigger(self):
        # type: () -> Optional[str]
        """Create a trigger for the current scene and select it."""
        return self._triggers_man.create_scene_trigger()

    def default_path_for(self, key):
        # type: (str) -> Optional[List[str]]
        """Scripted default file list for a scene key, or None."""
        return self._triggers_man.default_path_for(key)

    def _default_trigger_by_key_before(self, key_before):
        # type: (str) -> Optional[DefaultMusicTrigger]
        """The trigger log entry anchored at key_before, or None."""
        return self._triggers_man._default_trigger_by_key_before(key_before)

    def _is_default_trigger_scene(self, key):
        # type: (str) -> bool
        """True if the scene key is anchored by a default trigger."""
        return self._triggers_man._is_default_trigger_scene(key)

    def music_pool_for(self, scene_key):
        # type: (str) -> List[str]
        """Compose the playable music pool for a scene."""
        return self._triggers_man.music_pool_for(scene_key)

    @_cue_ui_refresh
    def add_user_song_to_trigger(self, path, record=True):
        # type: (str, bool) -> None
        """Add a My Music song to the selected trigger's music list."""
        self._triggers_man.add_user_song_to_trigger(path, record)

    @_cue_ui_refresh
    def add_game_song_to_trigger(self, path, record=True):
        # type: (str, bool) -> None
        """Add a Game Music song to the selected trigger's music list."""
        self._triggers_man.add_game_song_to_trigger(path, record)

    @_cue_ui_refresh
    def add_external_song_to_trigger(self, abs_path, record=True):
        # type: (str, bool) -> None
        """Add an external-folder song (already absolute) to the trigger."""
        self._triggers_man.add_external_song_to_trigger(abs_path, record)

    @_cue_ui_refresh
    def add_user_folder_to_trigger(self, folder_path, record=True):
        # type: (str, bool) -> None
        """Add a whole My Music folder (a trailing-'/' ref) to the trigger."""
        self._triggers_man.add_user_folder_to_trigger(folder_path, record)

    @_cue_ui_refresh
    def add_game_folder_to_trigger(self, folder_path, record=True):
        # type: (str, bool) -> None
        """Add a whole Game Music folder (a trailing-'/' ref) to the trigger."""
        self._triggers_man.add_game_folder_to_trigger(folder_path, record)

    @_cue_ui_refresh
    def add_external_folder_to_trigger(self, abs_folder, record=True):
        # type: (str, bool) -> None
        """Add a whole external-folder subfolder (a trailing-'/' ref)."""
        self._triggers_man.add_external_folder_to_trigger(abs_folder, record)

    def _add_ref_to_trigger(self, ref, record=True):
        # type: (str, bool) -> None
        """Append a music ref (file path or folder ref) to the selected trigger."""
        self._triggers_man._add_ref_to_trigger(ref, record)

    @_cue_ui_refresh
    def remove_song_from_trigger(self, key, path):
        # type: (str, str) -> None
        """Remove a custom song from a trigger's music list."""
        self._triggers_man.remove_song_from_trigger(key, path)

    @_cue_ui_refresh
    def toggle_file_ref_expand(self, folder_ref):
        # type: (str) -> None
        """Toggle expand/collapse for a folder ref in the trigger box."""
        self._triggers_man.toggle_file_ref_expand(folder_ref)

    @_cue_ui_refresh
    def remove_song_from_folder_ref(self, key, file_index, child_file):
        # type: (str, int, str) -> None
        """Detach one file from an expanded folder ref in a trigger."""
        self._triggers_man.remove_song_from_folder_ref(key, file_index, child_file)

    @_cue_ui_refresh
    def toggle_default(self, key):
        # type: (str) -> None
        """Flip whether the recorded default music plays for a scene."""
        self._triggers_man.toggle_default(key)

    @_cue_ui_refresh
    def delete_trigger(self, key):
        # type: (str) -> None
        """Delete a music trigger entirely: drop its songs and default-disable."""
        self._triggers_man.delete_trigger(key)

    def triggers(self):
        # type: () -> List[Dict[str, Any]]
        """Build the selectable music triggers for the current replay."""
        return self._triggers_man.triggers()

    def _pick_for_override(self):
        # type: () -> Any
        """Resolve what a default-trigger scene should play."""
        return self._triggers_man._pick_for_override()

    def play_custom_music(self):
        # type: () -> None
        """Play a custom-trigger scene's music on scene change."""
        self._triggers_man.play_custom_music()

    def _record_default_trigger(self, filenames, in_replay):
        # type: (Any, Any) -> None
        """Record the default music for the scene on screen at this play call."""
        self._triggers_man._record_default_trigger(filenames, in_replay)

    def songs_for_trigger(self, key):
        # type: (str) -> List[str]
        """Stored music refs of the trigger at `key` (empty if none)."""
        return self._triggers_man.songs_for_trigger(key)

    # ------------------------------------------------------------------
    # Delegates: preset screen behavior (CueMusicPresetsUi)
    # ------------------------------------------------------------------

    @_cue_ui_refresh
    def apply_preset(self, name):
        # type: (str) -> None
        """Apply a music preset to a trigger (click / shift+click)."""
        self._presets_ui.apply_preset(name)

    def _set_trigger_songs(self, key, files):
        # type: (str, List[str]) -> None
        """Replace the trigger at `key`'s song list ("" no-ops)."""
        self._presets_ui._set_trigger_songs(key, files)

    @_cue_ui_refresh
    def preset_remove_file(self, name, display_path):
        # type: (str, str) -> None
        """Remove one file from a music preset, given its display path."""
        self._presets_ui.preset_remove_file(name, display_path)

    def preset_display_files(self, preset):
        # type: (Dict[str, Any]) -> List[str]
        """A preset's stored refs as concrete display paths, for its rows."""
        return self._presets_ui.preset_display_files(preset)

    def _folder_display_children(self, folder_ref):
        # type: (str) -> List[str]
        """Display paths of the files a stored folder ref resolves to."""
        return self._presets_ui._folder_display_children(folder_ref)

    @_cue_ui_refresh
    def toggle_presets_expand(self):
        # type: () -> None
        """Flip the Music Presets/ folder in the Music Library."""
        self._presets_ui.toggle_presets_expand()

    @_cue_ui_refresh
    def toggle_preset_expand(self, name):
        # type: (str) -> None
        """Flip expand/collapse for one preset's file rows."""
        self._presets_ui.toggle_preset_expand(name)

    def preview_preset(self, preset_name):
        # type: (str) -> None
        """Preview a random song from a music preset."""
        self._presets_ui.preview_preset(preset_name)

    # ------------------------------------------------------------------
    # Stored-ref resolution (cue_lib.music.refs) + folder-UI persistence
    # ------------------------------------------------------------------

    def resolve_music_files(self, files):
        # type: (List[str]) -> List[str]
        """Expand folder refs (trailing '/') to matching available files."""
        return _cue_resolve_music_files(self.library, files)

    def ref_path(self, ref):
        # type: (str) -> str
        """Stored ref without its source tag, for display."""
        return _cue_ref_path(ref)

    def _split_ref_tag(self, ref):
        # type: (str) -> Tuple[Optional[str], str]
        """Split a stored ref into (tag, path); tag is None if untagged."""
        return _cue_split_ref_tag(ref)

    def _resolve_music_path(self, stored):
        # type: (str) -> str
        """Turn a stored music entry into a playable path (refs helper)."""
        return _cue_resolve_music_path(self._paths, stored)

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
