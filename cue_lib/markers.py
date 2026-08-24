# -*- coding: utf-8 -*-
# CueMarkerManager -- unified marker CRUD with typed context accessors.
# Instantiated once at _cue.markers, lives on the NoRollback _cue object.
#
# The coordinator for the marker system: owns the context sub-objects,
# sfx/video-dependent preset operations, scalar-load fan-out, the post-restore
# reload callback, and the clipboard.  All marker data (entries, presets,
# migrations, persistence) lives in self._store (CueMarkerStore), wired in
# before this manager in cue_z.rpy.  Data methods are delegated to the store so
# contexts and external consumers keep a single stable surface on _cue.markers.

import copy as _copy
import renpy

from renpy.store import persistent

from cue_lib.constants import (
    CUE_VOLUME_DEFAULT, CueExclusiveStart as CueExclusiveStart, CueLoopFrequency as CueLoopFrequency,
    CueContextType,
)
from cue_lib.marker_context import CueImageContext, CueDialogueContext, CueVideoContext, CueLoopContext
from cue_lib.copy_paste import copy_context as _copy_context, paste_context as _paste_context
# ResolvedExclusive is re-exported (as X form = explicit re-export): tests
# import both snapshots from cue_lib.markers.
from cue_lib.marker_store import CueMarkerStore, ResolvedPool, ResolvedExclusive as ResolvedExclusive
from cue_lib.state import _cue
from cue_lib.util import (
    _cue_expand_folder_ref, _cue_format_time, _cue_log, create_vid_key,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, ItemsView, KeysView, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import (
        ClipboardData, MarkerEntry, PoolDict, VideoPoolDict, VideoPreset,  # pyright: ignore[reportUnusedImport]
    )
    # Injected constructor collaborators (type-only; resolved at wiring time).
    from cue_lib.state import CueContext  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video import CueVideoManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.audio.sfx_manager import CueSfxManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.trigger import CueTriggerEngine  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video_editor import CueVideoEditor  # pyright: ignore[reportUnusedImport]


# =========================================================================
# CueMarkerManager
# =========================================================================

# Valid CueContextType ids (set_target_context validation + screen bars).
_CUE_TARGET_CONTEXT_IDS = (
    CueContextType.VIDEO,
    CueContextType.IMAGE,
    CueContextType.DIALOGUE,
    CueContextType.LOOP,
)


class CueMarkerManager(object):

    def __init__(self, ctx, store, vid_manager, sfx_manager, trigger, video_editor):
        # type: (CueContext, CueMarkerStore, CueVideoManager, CueSfxManager, CueTriggerEngine, CueVideoEditor) -> None
        self._store = store
        self._ctx = ctx
        self._vid_manager = vid_manager
        self._sfx_manager = sfx_manager
        self._trigger = trigger
        self._video_editor = video_editor
        # pyright can't unify the source `self` with the stub-declared manager
        # type that context.pyi imports back in -- suppress per line.
        self.image = CueImageContext(self)  # pyright: ignore[reportArgumentType]
        self.dialogue = CueDialogueContext(self)  # pyright: ignore[reportArgumentType]
        self.video = CueVideoContext(self)  # pyright: ignore[reportArgumentType]
        self.loop = CueLoopContext(self)  # pyright: ignore[reportArgumentType]
        self.clipboard = None
        # SFX library [+] assign target.  Session-only; never persisted.  May
        # be mutated by resolve_target_context() when the selection can't
        # receive assigns right now (video/image fallback).
        self.target_context = CueContextType.VIDEO

    # -- read-through to the store (legacy consumers read AND write these) --
    # Setters keep undo._restore() (which swaps the whole dicts) and
    # _apply_restore working until Chunk 4 rewrites them against the store.

    @property
    def _data(self):
        return self._store._data

    @_data.setter
    def _data(self, value):
        self._store._data = value

    @property
    def _presets(self):
        return self._store._presets

    @_presets.setter
    def _presets(self, value):
        self._store._presets = value

    @property
    def _video_presets(self):
        return self._store._video_presets

    @_video_presets.setter
    def _video_presets(self, value):
        self._store._video_presets = value

    @property
    def _session_created(self):
        return self._store._session_created

    @_session_created.setter
    def _session_created(self, value):
        self._store._session_created = value

    # -- dict-like interface --

    def __getitem__(self, key):
        # type: (str) -> MarkerEntry
        return self._store[key]

    def __setitem__(self, key, value):
        # type: (str, MarkerEntry) -> None
        self._store[key] = value

    def __delitem__(self, key):
        # type: (str) -> None
        del self._store[key]

    def __contains__(self, key):
        # type: (str) -> bool
        return key in self._store

    def get(self, key, default=None):
        # type: (str, Optional[MarkerEntry]) -> Optional[MarkerEntry]
        return self._store.get(key, default)

    def setdefault(self, key, default):
        # type: (str, MarkerEntry) -> MarkerEntry
        return self._store.setdefault(key, default)

    def pop(self, key, *args):
        # type: (str, *MarkerEntry) -> MarkerEntry
        return self._store.pop(key, *args)

    def items(self):
        # type: () -> ItemsView[str, MarkerEntry]
        return self._store.items()

    def keys(self):
        # type: () -> KeysView[str]
        return self._store.keys()

    def __len__(self):
        # type: () -> int
        return len(self._store)

    # -- presets --

    def create_preset(self, name, pool_dict):
        # type: (str, PoolDict) -> None
        self._store.create_preset(name, pool_dict)

    def delete_preset(self, name):
        # type: (str) -> None
        self._store.delete_preset(name)

    def get_preset(self, name):
        # type: (str) -> Optional[PoolDict]
        return self._store.get_preset(name)

    def list_presets(self):
        # type: () -> List[str]
        return self._store.list_presets()

    def preset_remove_file(self, name, file_path):
        # type: (str, str) -> None
        preset = self._presets.get(name)
        if preset is None:
            return
        files = preset.get("files", [])
        if file_path in files:
            files.remove(file_path)
            self._db_save_preset(name)
            return
        for fi, f in enumerate(files):
            if f.endswith("/") and file_path.startswith(f):
                resolved = _cue_expand_folder_ref(
                    self._sfx_manager.library.files, f, self._sfx_manager.library.disabled_files)
                if file_path in resolved:
                    resolved.remove(file_path)
                files[fi:fi + 1] = resolved
                self._db_save_preset(name)
                return

    # -- video presets --

    def create_video_preset(self, name, entry):
        # type: (str, Any) -> None
        """Save a video preset. The source duration comes from the video
        manager; the store has no video dependency."""
        source_dur = self._vid_manager.get_duration()
        self._store.create_video_preset(name, entry, source_dur)

    def delete_video_preset(self, name):
        # type: (str) -> None
        self._store.delete_video_preset(name)

    def get_video_preset(self, name):
        # type: (str) -> Optional[VideoPreset]
        return self._store.get_video_preset(name)

    def list_video_presets(self):
        # type: () -> List[str]
        return self._store.list_video_presets()

    def remove_video_preset_pool(self, name, pool_index):
        # type: (str, int) -> None
        """Remove one pool from a video preset; a preset left with no pools is
        deleted (a saved video preset always has at least one pool)."""
        preset = self._video_presets.get(name)
        if preset is None:
            return
        pools = preset.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        del pools[pool_index]
        if not pools:
            self.delete_video_preset(name)
            return
        self._db_save_video_preset(name)
        _cue_log("REMOVE-VIDEO-POOL preset={} index={}".format(name, pool_index))

    def remove_video_preset_pool_file(self, name, pool_index, file_path):
        # type: (str, int, str) -> None
        """Remove one file from a pool in a saved video preset.

        Same folder-ref handling as _remove_file_from_preset_pool: a ref
        covering ``file_path`` is expanded via _detach_folder_ref_in_files."""
        preset = self._video_presets.get(name)
        if preset is None:
            return
        pools = preset.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        files = pools[pool_index].get("files", [])
        for fi, f in enumerate(files):
            if f.endswith("/") and file_path.startswith(f):
                self._detach_folder_ref_in_files(files, fi, file_path)
                break
        else:
            if file_path in files:
                files.remove(file_path)
        self._db_save_video_preset(name)

    def video_preset_out_of_range(self, name):
        # type: (str) -> int
        preset = self._video_presets.get(name)
        if preset is None:
            return 0
        dur = self._vid_manager.get_duration()
        if dur is None or dur <= 0:
            return 0
        out = 0
        for pool in preset.get("pools", []):
            t = pool.get("time")
            if t is not None and t > dur:
                out += 1
        return out

    def apply_video_preset(self, name):
        # type: (str) -> None
        preset = self._video_presets.get(name)
        if preset is None:
            return
        if not self._ctx.current_file:
            return
        vid_key = create_vid_key(self._ctx.current_file)
        dur = self._vid_manager.get_duration()
        dropped = 0
        new_pools = []
        for pool in preset.get("pools", []):
            t = pool.get("time")
            if t is None:
                dropped += 1
                continue
            if dur and dur > 0 and t > dur:
                dropped += 1
                continue
            new_pool = _copy.deepcopy(pool)
            new_pool.setdefault("files", [])
            new_pool.setdefault("volume", CUE_VOLUME_DEFAULT)
            new_pools.append(new_pool)
        new_pools.sort(key=lambda e: e["time"])
        entry = self._get_or_create_entry(vid_key)
        entry["pools"] = new_pools
        entry["volume"] = preset.get("volume", CUE_VOLUME_DEFAULT)
        self.video.active_pool = 0
        self.video.selected = set()
        self.video.sync_text()
        self._db_save_marker(vid_key)
        _cue_log("APPLY-VIDEO-PRESET key={} preset={} markers={} dropped={}".format(
            vid_key, name, len(new_pools), dropped))

    def _resolve_video_pools(self, entry):
        # type: (Any) -> List[VideoPoolDict]
        return self._store._resolve_video_pools(entry)

    def _video_multi_file_edit(self, marker_key):
        # type: (str) -> bool
        """True when a file-list edit should fan out to every selected pool:
        the target is the current video and a multi-select is active."""
        if len(self.video.get_selected()) <= 1:
            return False
        vid_key = create_vid_key(self._ctx.current_file) if self._ctx.current_file else ""
        return bool(vid_key) and vid_key == marker_key

    def _remove_file_from_preset_pool(self, marker_key, pool_index, _dummy_fi, child_file):
        # type: (str, int, int, str) -> None
        if self._video_multi_file_edit(marker_key):
            self.video._remove_path_from_selected(child_file)
            return
        self._detach_pool(marker_key, pool_index)
        entry = self._data.get(marker_key)
        if entry is None:
            return

        pools = entry.get("pools")
        if not (pools and 0 <= pool_index < len(pools)):
            return

        files = pools[pool_index].get("files", [])

        # A preset's files may hold folder refs (trailing "/"), not
        # individual files. Expand the matching folder ref and drop the
        # child; otherwise remove the child directly.
        for file_index, item in enumerate(files):
            if item.endswith("/") and child_file.startswith(item):
                self._detach_folder_ref_in_files(files, file_index, child_file)
                break
        else:
            if child_file in files:
                files.remove(child_file)
        self._db_save_marker(marker_key)

    def resolve_pool(self, pool):
        # type: (PoolDict) -> ResolvedPool
        return self._store.resolve_pool(pool)

    def _detach_pool(self, marker_key, pool_index):
        # type: (str, int) -> bool
        return self._store._detach_pool(marker_key, pool_index)

    def detach_active_video_ts(self, *args):
        # type: (*Any) -> None
        vid_key = create_vid_key(self._ctx.current_file) if self._ctx.current_file else ""
        if not vid_key:
            return
        entry = self.get(vid_key)
        if entry is None:
            return
        sel = self.video.get_selected()
        if len(sel) > 1:
            for idx in sorted(sel):
                self._detach_pool(vid_key, idx)
        else:
            self._detach_pool(vid_key, self.video.active_pool)
        self.save_marker(vid_key)

    def detach_pool_at(self, marker_key, pool_index):
        # type: (str, int) -> None
        self._detach_pool(marker_key, pool_index)
        self.save_marker(marker_key)

    def _stamp_preset(self, marker_key, preset_name, pool_index=0):
        # type: (str, str, int) -> None
        self._store._stamp_preset(marker_key, preset_name, pool_index)

    def _detach_folder_ref_in_files(self, files, file_index, child_file):
        # type: (List[str], int, str) -> None
        folder_ref = files[file_index]
        if not folder_ref.endswith("/"):
            return
        resolved = _cue_expand_folder_ref(
            self._sfx_manager.library.files, folder_ref, self._sfx_manager.library.disabled_files)
        if child_file in resolved:
            resolved.remove(child_file)
        files[file_index:file_index + 1] = resolved

    def _remove_file_from_folder_ref(self, marker_key, pool_index, file_index, child_file):
        # type: (str, int, int, str) -> None
        if self._video_multi_file_edit(marker_key):
            self.video._remove_path_from_selected(child_file)
            return
        self._detach_pool(marker_key, pool_index)
        entry = self._data.get(marker_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return
        files = pools[pool_index].get("files", [])
        if file_index >= len(files):
            return
        self._detach_folder_ref_in_files(files, file_index, child_file)
        self._db_save_marker(marker_key)

    # -- entry / pool mutators (delegated to the store) --

    def _normalize_entry(self, entry):
        # type: (Any) -> MarkerEntry
        return self._store._normalize_entry(entry)

    def _get_or_create_entry(self, marker_key):
        # type: (str) -> Any
        return self._store._get_or_create_entry(marker_key)

    def _ensure_pool(self, marker_key, pool_index):
        # type: (str, int) -> PoolDict
        return self._store._ensure_pool(marker_key, pool_index)

    def _add_file_to_pool(self, marker_key, filename, pool_index=0):
        # type: (str, str, int) -> None
        self._store._add_file_to_pool(marker_key, filename, pool_index)

    def _remove_file_from_pool(self, marker_key, file_index, pool_index=0):
        # type: (str, int, int) -> None
        self._store._remove_file_from_pool(marker_key, file_index, pool_index)

    # -- sanitize / migration passes (delegated to the store) --

    def _normalize_all(self):
        # type: () -> bool
        return self._store._normalize_all()

    def _migrate_legacy_exclusive(self):
        # type: () -> int
        return self._store._migrate_legacy_exclusive()

    @staticmethod
    def _migrate_exclusive_pool(pool):
        # type: (Any) -> bool
        return CueMarkerStore._migrate_exclusive_pool(pool)

    @staticmethod
    def _migrate_colon_key(key):
        # type: (str) -> str
        return CueMarkerStore._migrate_colon_key(key)

    def _migrate_speed_mode_rename(self):
        # type: () -> None
        self._store._migrate_speed_mode_rename()

    def _migrate_video_timestamps_to_pools(self):
        # type: () -> Tuple[int, int]
        return self._store._migrate_video_timestamps_to_pools()

    def _sanitize_video_pools(self):
        # type: () -> int
        return self._store._sanitize_video_pools()

    def _sanitize_video_presets(self):
        # type: () -> int
        return self._store._sanitize_video_presets()

    @staticmethod
    def _clean_pool_list(pools):
        # type: (List[PoolDict]) -> Tuple[List[PoolDict], int]
        return CueMarkerStore._clean_pool_list(pools)

    # -- persistence --

    def reload_presets(self):
        # type: () -> None
        """Re-read presets from the shared data store. Merges new/updated
        presets from disk (other games may have added them). Never deletes."""
        self._store.reload_presets()

    # ------------------------------------------------------------------
    # Public save API -- targeted data store writes for routine mutations
    # ------------------------------------------------------------------

    def save_marker(self, key):
        # type: (str) -> None
        """Persist one marker entry to data store. Call after mutating self._data[key]."""
        self._store.save_marker(key)

    def save_markers(self, keys):
        # type: (List[str]) -> None
        """Persist several marker entries in one batch. Call after mutating
        self._data[key] for each key. Side effects run once for the whole
        batch, so a multi-key edit produces a single undo step."""
        self._store.save_markers(keys)

    def save_preset(self, name):
        # type: (str) -> None
        """Persist one audio preset to data store."""
        self._store.save_preset(name)

    def save_video_preset(self, name):
        # type: (str) -> None
        """Persist one video preset to data store."""
        self._store.save_video_preset(name)

    # ------------------------------------------------------------------
    # Internal helpers -- write one item to DB, then run side effects
    # ------------------------------------------------------------------

    def _db_save_marker(self, key):
        # type: (str) -> None
        self._store._db_save_marker(key)

    def _db_save_preset(self, name):
        # type: (str) -> None
        self._store._db_save_preset(name)

    def _db_save_video_preset(self, name):
        # type: (str) -> None
        self._store._db_save_video_preset(name)

    def save_all(self):
        # type: () -> None
        """Full save of all markers + presets to DB.
        Used by migration, restore, and undo/redo."""
        self._store.save_all()

    def delete_removed_files(self, old_marker_keys, old_presets, old_video_presets, old_session_created):
        # type: (Set[str], Dict[str, Any], Dict[str, Any], Set[Tuple[str, str]]) -> None
        """Delete DB files for keys a restore just dropped from the stores.

        old_* capture the live stores BEFORE the restore swapped in new data.
        Marker files are removed by key diff -- marker stores are per-game and
        only mutated by this session, so any dropped key was created here.
        Preset files are shared across games and reloadable mid-session, so a
        preset is removed only when it was created in this session AND the
        on-disk entry still matches the entry being dropped. Never a
        directory sweep: files the store never loaded are left untouched."""
        self._store.delete_removed_files(
            old_marker_keys, old_presets, old_video_presets, old_session_created)

    # ------------------------------------------------------------------
    # Load / migration
    # ------------------------------------------------------------------

    def load_persistent(self):
        # type: () -> None
        """Load markers + presets from the data store."""
        self._store.load_from_db()
        _cue_log("LOAD-MARKERS total_keys={}".format(len(self._data)))


    # ------------------------------------------------------------------
    # Post-restore reload (callback for CueManualBackupManager)
    # ------------------------------------------------------------------

    def _reload_after_restore(self, count):
        # type: (int) -> None
        """Reload in-memory state from restored files.  Main thread only --
        touches persistent and the Ren'Py store.  Called by the manual backup
        manager (cue_lib/backup.py) once the background restore merge is done."""
        db = self._store._db
        if db is None or not db.is_open():
            return
        db.open()
        # The session-created bookkeeping no longer matches the restored data
        # (merge-only restore can surface files this session never created).
        self._session_created = set()
        # Lazy import breaks the markers <-> runtime cycle: runtime.py imports
        # _cue_load_scalars_from_persistent at module load.
        from cue_lib.runtime import _cue_full_reload
        _cue_full_reload()
        # Capture the restored tree in a fresh auto-backup.
        db._backup.force_backup()
        renpy.restart_interaction()
        _cue_log("RESTORE-MARKERS ok files={}".format(count))

    # -- clipboard --

    def copy_context(self):
        # type: () -> None
        _copy_context(self)  # pyright: ignore[reportArgumentType]  # source `self` vs stub-typed param

    def paste_context(self):
        # type: () -> None
        _paste_context(self)  # pyright: ignore[reportArgumentType]  # source `self` vs stub-typed param

    # -- SFX library target context ([+] assign target) --

    def set_target_context(self, ctx_id):
        # type: (str) -> None
        """Set the [+] assign target.  Unknown ids are ignored so a stale
        screen can't strand the manager on a bogus value."""
        if ctx_id in _CUE_TARGET_CONTEXT_IDS:
            self.target_context = ctx_id

    def target_is_available(self, ctx_id):
        # type: (str) -> bool
        """True when *ctx_id* can receive [+] assigns right now."""
        if ctx_id == CueContextType.VIDEO:
            return self._ctx.top_layer_type == "movie"
        if ctx_id == CueContextType.IMAGE:
            return bool(self._ctx.current_file) and self._ctx.top_layer_type != "movie"
        if ctx_id == CueContextType.DIALOGUE:
            return bool(self._ctx.current_dialogue)
        # LOOP (and any unknown id) is always available.
        return True

    def resolve_target_context(self):
        # type: () -> str
        """The effective [+] target, mutating self.target_context when the
        selection is unavailable: fall back to whatever video/image is on
        screen (movie beats image).  In the menu -- neither video nor image --
        the selection is left untouched and the caller disables [+].
        The default selection is the on-screen context, so a fresh page
        resolves without a prior set."""
        if self.target_is_available(self.target_context):
            return self.target_context
        if self._ctx.top_layer_type == "movie":
            self.target_context = CueContextType.VIDEO
        elif self._ctx.current_file:
            self.target_context = CueContextType.IMAGE
        return self.target_context

    def send_target(self, kind, ref, record=True):
        # type: (str, object, bool) -> Optional[str]
        """Send a library row to the resolved target context's active pool.
        *kind* is the send_* suffix: "file" (ref = file index), "folder"
        (ref = path), "preset" (ref = preset name).  Shift+Click new-pool
        behavior is handled inside the context's send_* methods.  Returns a
        guardrail error string when a folder add is rejected, else None."""
        ctx_id = self.resolve_target_context()
        ctx = getattr(self, ctx_id)
        return getattr(ctx, "send_" + kind)(ref, record=record)

    def target_active_label(self):
        # type: () -> str
        """Context bar second line: the resolved target's active pool label
        ("Pool 1", video "Pool 1 @ MM:SS.cs"), or a hint when no pool exists
        yet.  1-indexed to match the pool tabs."""
        ctx_id = self.resolve_target_context()
        ctx = getattr(self, ctx_id)
        if not ctx.has_pools():
            return "No pool yet.  Click + to create one."
        if ctx_id == CueContextType.VIDEO:
            pool = ctx.get_active_pool()
            return "Pool {} @ {}".format(
                ctx.get_active_index() + 1, _cue_format_time(pool.get("time", 0)))
        return "Pool {}".format(ctx.get_active_index() + 1)

# ---------------------------------------------------------------------------
# Bootstrap / coordinator functions -- module-level because they write to
# managers wired after CueMarkerManager (trigger, etc.).  They read _cue
# directly; the manager itself no longer touches sibling managers.
# ---------------------------------------------------------------------------


def _cue_load_scalars_from_persistent():
    # type: () -> None
    """Fan out per-game scalars from persistent/shared config into the
    owning managers.  Lives at module level (not on the manager) because it
    writes to sfx_manager/trigger/video_editor/speed_resolver -- siblings the
    coordinator is wired after."""
    # Migrate from individual persistent._cue_* scalars to a single dict
    _cue_dict = getattr(persistent, '_cue', None)
    if _cue_dict is None:
        _cue_dict = {
            "disabled_files": set(getattr(persistent, '_cue_disabled_files', None) or ()),
            "triggers_active": getattr(persistent, '_cue_triggers_active', True),
            "encode_mode": getattr(persistent, '_cue_encode_mode', _cue.video_editor.MODE_INTERPOLATE),
            "remove_audio": getattr(persistent, '_cue_remove_audio', True),
            "seamless_transition": getattr(persistent, '_cue_seamless_transition', False),
        }
        persistent._cue = _cue_dict

    # Migrate disabled_files from persistent._cue to shared config file.
    # Shared config always wins if it already has the key.
    shared = _cue.db.load_shared_config()
    if "disabled_files" not in shared:
        shared["disabled_files"] = list(_cue_dict.pop("disabled_files", set()))
        _cue.db.save_shared_config(shared)
    else:
        _cue_dict.pop("disabled_files", None)

    _cue.sfx.library.disabled_files = set(shared.get("disabled_files", []))
    # Coalesce None to the default: a dict whose keys hold None (e.g. a
    # partially-nulled persistent._cue) must not silently flip these to
    # falsy -- remove_audio=None would keep audio on every encode.
    _triggers = _cue_dict.get("triggers_active")
    _cue.trigger.active = True if _triggers is None else bool(_triggers)
    _mode = _cue_dict.get("encode_mode")
    if _mode is None:
        _mode = _cue.video_editor.MODE_INTERPOLATE
    _cue.video_editor.encode_mode = _mode
    _ra = _cue_dict.get("remove_audio")
    _cue.video_editor.remove_audio = True if _ra is None else bool(_ra)
    _st = _cue_dict.get("seamless_transition")
    _cue.speed_resolver.seamless_transition = False if _st is None else bool(_st)


def _cue_markers_send(kind, ref, record=True):
    # type: (str, object, bool) -> None
    """Store bridge for the SFX library [+] button: dispatch *ref* (file
    index / folder path / preset name) to the resolved target context's
    active pool.  Reads _cue at call time so screens can Function()-call it.
    A folder add rejected by the one-group-per-pool guardrail shows the
    notice under the target bar."""
    err = _cue.markers.send_target(kind, ref, record=record)
    if err:
        _cue.sfx.library.set_add_to_pool_warning(err)


def _cue_send_folder_to_video(folder_path):
    # type: (str) -> None
    """Store bridge for the intensity-group [V] button: send a folder to the
    active video marker's pool, ignoring the target-context selector.  A folder
    add rejected by the one-group-per-pool guardrail shows the notice under the
    target bar (same surfacing as _cue_markers_send)."""
    err = _cue.markers.video.send_folder(folder_path)
    if err:
        _cue.sfx.library.set_add_to_pool_warning(err)


def _cue_assign_tt(ctx_id):
    # type: (str) -> str
    """Shared [+]-assign tooltip for one context id (video or image): Click
    adds to the active pool, Shift+Click creates a new pool and adds."""
    mgr = _cue.markers
    if not mgr.target_is_available(ctx_id):
        return "No video or image on screen right now"
    label = ctx_id.title()
    if getattr(mgr, ctx_id).has_pools():
        return ("Click: Add to {} active pool\nShift+Click: Create new {} pool and add"
                .format(label, label))
    return "Create {} pool and add".format(label)


def _cue_target_assign_tt():
    # type: () -> str
    """Tooltip for the [+] assign button, reflecting the resolved target
    context and whether that context already has an active pool."""
    return _cue_assign_tt(_cue.markers.resolve_target_context())


def _cue_send_folder_to_video_tt():
    # type: () -> str
    """Tooltip for the intensity-group [V] button: same as the [+]
    button when video is targeted, always pinned to the video marker."""
    return _cue_assign_tt(CueContextType.VIDEO)
