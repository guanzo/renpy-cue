# -*- coding: utf-8 -*-
# CueMusicTriggers -- the per-replay default-music trigger log, trigger-box
# editing, and the scene-music override pool.  Owns the trigger state; the
# CueMusicManager delegates interception and playback to it.

import random

import renpy

from cue_lib.constants import CUE_DEFAULT_MUSIC_CHANNEL, CUE_MUSIC_GAME_TAG, CUE_MUSIC_USER_TAG
from cue_lib.music.refs import _cue_resolve_music_files, _cue_resolve_music_path
from cue_lib.util import _cue_strip_key_prefix, _cue_ui_refresh, create_img_key, create_vid_key

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import DefaultMusicTrigger
    from cue_lib.music.manager import CueMusicManager

# Sentinel from _pick_for_override: play nothing (default disabled with no
# replacement songs).  Distinct from None (no override) and from a filepath.
_SUPPRESS_MUSIC = object()


class CueMusicTriggers(object):
    """Default-music trigger log + trigger-box editing + scene override.

    Split out of CueMusicManager so the manager keeps only interception and
    playback.  Reaches back through _mgr for playback/recent; owns the trigger
    log (_triggers), the pending key_after capture (_pending), and the
    selection/expand UI state the Music page renders."""

    def __init__(self, mgr):
        # type: (CueMusicManager) -> None
        self._mgr = mgr
        self._store = mgr._store
        self._ctx = mgr._ctx
        self._db = mgr._db
        self._paths = mgr._paths
        self.library = mgr.library
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
                for c in _cue_resolve_music_files(self.library, customs):
                    pool.append(_cue_resolve_music_path(self._paths, c))
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
            recent = self._mgr._recent
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
        self._mgr.save_ui_state()

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
        # _cue_resolve_music_files returns stored-form children (u:/g: tagged,
        # external bare absolute), ready to splice back in as-is.
        resolved = _cue_resolve_music_files(self.library, [folder_ref])
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
            self._mgr._original_music_play(
                self._mgr._playable_file(random.choice(pool)), channel=CUE_DEFAULT_MUSIC_CHANNEL, loop=True
            )

    def songs_for_trigger(self, key):
        # type: (str) -> List[str]
        """Stored music refs of the trigger at `key` (empty if none).

        A copy, so the Save dialog editing it never mutates the trigger."""
        entry = self._store.get(key)
        if entry is None:
            return []
        return list(entry.get("music") or [])
