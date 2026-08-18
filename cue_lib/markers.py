# -*- coding: utf-8 -*-
# CueMarkerManager -- unified marker CRUD with typed context accessors.
# Instantiated once at _cue.markers, lives on the NoRollback _cue object.
#
# The coordinator for the marker system: owns the context sub-objects,
# sfx/video-dependent preset operations, scalar-load fan-out, backup/restore
# glue, and the clipboard.  All marker data (entries, presets, migrations,
# persistence) lives in self._store (CueMarkerStore), wired in before this
# manager in cue_z.rpy.  Data methods are delegated to the store so contexts
# and external consumers keep a single stable surface on _cue.markers.

import os
import copy as _copy
import renpy

from renpy.store import Function, persistent

from cue_lib.backup import (
    CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME,
    validate_backup_zip, restore_pieces,
)
from cue_lib.constants import (
    CUE_VOLUME_DEFAULT, CueExclusiveStart as CueExclusiveStart, CueLoopFrequency as CueLoopFrequency,
)
from cue_lib.context import CueImageContext, CueDialogueContext, CueVideoContext, CueLoopContext
from cue_lib.copy_paste import copy_context as _copy_context, paste_context as _paste_context
# ResolvedExclusive is re-exported (as X form = explicit re-export): tests
# import both snapshots from cue_lib.markers.
from cue_lib.marker_store import CueMarkerStore, ResolvedPool, ResolvedExclusive as ResolvedExclusive
from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, create_vid_key,
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
    from cue_lib.ui.dialogs import CueConfirmDialog  # pyright: ignore[reportUnusedImport]


# =========================================================================
# CueMarkerManager
# =========================================================================

class CueMarkerManager(object):

    def __init__(self, ctx, store, vid_manager, sfx_manager, trigger, video_editor, confirm_dialog):
        # type: (CueContext, CueMarkerStore, CueVideoManager, CueSfxManager, CueTriggerEngine, CueVideoEditor, CueConfirmDialog) -> None
        self._store = store
        self._ctx = ctx
        self._vid_manager = vid_manager
        self._sfx_manager = sfx_manager
        self._trigger = trigger
        self._video_editor = video_editor
        self._confirm_dialog = confirm_dialog
        self._img_target = 0
        self._dlg_target = 0
        self._loop_target = 0
        # pyright can't unify the source `self` with the stub-declared manager
        # type that context.pyi imports back in -- suppress per line.
        self.image = CueImageContext(self)  # pyright: ignore[reportArgumentType]
        self.dialogue = CueDialogueContext(self)  # pyright: ignore[reportArgumentType]
        self.video = CueVideoContext(self)  # pyright: ignore[reportArgumentType]
        self.loop = CueLoopContext(self)  # pyright: ignore[reportArgumentType]
        self.clipboard = None

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
                resolved = []
                for rf in self._sfx_manager.files:
                    if rf.startswith(f) and rf not in self._sfx_manager.disabled_files and rf not in resolved:
                        resolved.append(rf)
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
        self.video.target_pool = 0
        self.video.selected = set()
        self.video.sync_text()
        self._db_save_marker(vid_key)
        _cue_log("APPLY-VIDEO-PRESET key={} preset={} markers={} dropped={}".format(
            vid_key, name, len(new_pools), dropped))

    def _resolve_video_pools(self, entry):
        # type: (Any) -> List[VideoPoolDict]
        return self._store._resolve_video_pools(entry)

    def _video_multi_file_edit(self, trigger_key):
        # type: (str) -> bool
        """True when a file-list edit should fan out to every selected pool:
        the target is the current video and a multi-select is active."""
        if len(self.video.get_selected()) <= 1:
            return False
        vid_key = create_vid_key(self._ctx.current_file) if self._ctx.current_file else ""
        return bool(vid_key) and vid_key == trigger_key

    def _remove_file_from_preset_pool(self, trigger_key, pool_index, _dummy_fi, child_file):
        # type: (str, int, int, str) -> None
        if self._video_multi_file_edit(trigger_key):
            self.video._remove_path_from_selected(child_file)
            return
        self._detach_pool(trigger_key, pool_index)
        entry = self._data.get(trigger_key)
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
        self._db_save_marker(trigger_key)

    def resolve_pool(self, pool):
        # type: (PoolDict) -> ResolvedPool
        return self._store.resolve_pool(pool)

    def _detach_pool(self, trigger_key, pool_index):
        # type: (str, int) -> bool
        return self._store._detach_pool(trigger_key, pool_index)

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
            self._detach_pool(vid_key, self.video.target_pool)
        self.save_marker(vid_key)

    def detach_pool_at(self, trigger_key, pool_index):
        # type: (str, int) -> None
        self._detach_pool(trigger_key, pool_index)
        self.save_marker(trigger_key)

    def _stamp_preset(self, trigger_key, preset_name, pool_index=0):
        # type: (str, str, int) -> None
        self._store._stamp_preset(trigger_key, preset_name, pool_index)

    def _detach_folder_ref_in_files(self, files, file_index, child_file):
        # type: (List[str], int, str) -> None
        folder_ref = files[file_index]
        if not folder_ref.endswith("/"):
            return
        resolved = []
        for f in self._sfx_manager.files:
            if f.startswith(folder_ref) and f not in self._sfx_manager.disabled_files and f not in resolved:
                resolved.append(f)
        if child_file in resolved:
            resolved.remove(child_file)
        files[file_index:file_index + 1] = resolved

    def _remove_file_from_folder_ref(self, trigger_key, pool_index, file_index, child_file):
        # type: (str, int, int, str) -> None
        if self._video_multi_file_edit(trigger_key):
            self.video._remove_path_from_selected(child_file)
            return
        self._detach_pool(trigger_key, pool_index)
        entry = self._data.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return
        files = pools[pool_index].get("files", [])
        if file_index >= len(files):
            return
        self._detach_folder_ref_in_files(files, file_index, child_file)
        self._db_save_marker(trigger_key)

    # -- entry / pool mutators (delegated to the store) --

    def _normalize_entry(self, entry):
        # type: (Any) -> MarkerEntry
        return self._store._normalize_entry(entry)

    def _get_or_create_entry(self, trigger_key):
        # type: (str) -> Any
        return self._store._get_or_create_entry(trigger_key)

    def _ensure_pool(self, trigger_key, pool_index):
        # type: (str, int) -> PoolDict
        return self._store._ensure_pool(trigger_key, pool_index)

    def _add_file_to_pool(self, trigger_key, filename, pool_index=0):
        # type: (str, str, int) -> None
        self._store._add_file_to_pool(trigger_key, filename, pool_index)

    def _remove_file_from_pool(self, trigger_key, file_index, pool_index=0):
        # type: (str, int, int) -> None
        self._store._remove_file_from_pool(trigger_key, file_index, pool_index)

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
    # Backup / restore
    # ------------------------------------------------------------------

    def backup_to_file(self):
        # type: () -> None
        """Zip the shared data/ tree to {shared}/backups/backup.zip."""
        self._store.backup_to_file()

    def restore_from_file(self):
        # type: () -> None
        """Validate backup.zip, then ask the user to confirm a restore."""
        db = self._store._db
        if db is None or not db.is_open():
            return
        zip_path = os.path.join(self._store._paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
        if not os.path.isfile(zip_path):
            _cue_log("RESTORE-MARKERS-NO-FILE path={}".format(zip_path))
            return
        ok, reason = validate_backup_zip(zip_path)
        if not ok:
            _cue_log("RESTORE-MARKERS-INVALID {}".format(reason))
            return
        self._confirm_dialog.show(
            "Restore from backups/backup.zip? This will overwrite this "
            "game's markers, presets, shared config, and the audio/ and "
            "music/ folders with the backup's version. Data not included in "
            "the backup -- including anything added after, and other games' "
            "markers -- is left untouched. Previous data is saved to data_bak.",
            Function(self._apply_restore, zip_path),
        )

    def _apply_restore(self, zip_path):
        # type: (str) -> None
        """Merge backup.zip over the live tree, then reload in-memory state."""
        try:
            db = self._store._db
            if db is None or not db.is_open():
                return
            # Don't mutate the live tree while the auto-backup is zipping it.
            if not db._backup.wait_until_idle():
                _cue_log("RESTORE-MARKERS: timed out waiting for auto backup")
                return
            count = restore_pieces(zip_path, self._store._paths.root, self._store._paths.game_id)
            db.open()
            # Reload the stores from the restored files.  load_persistent
            # treats an empty marker dir as fresh and skips presets, so
            # re-read presets to cover a markerless-but-preset restore.
            self.load_persistent()
            _cue_load_scalars_from_persistent()
            self.reload_presets()
            self._session_created = set()
            _cue.undo.reset()
            # Re-scan the media folders so restored audio/music shows up.
            self._sfx_manager.scan()
            _cue.music.user_music.scan()
            _cue.music.library.maybe_rebuild()
            self._video_editor.refresh()
            # Capture the restored tree in a fresh auto-backup.
            db._backup.force_backup()
            renpy.restart_interaction()
            _cue_log("RESTORE-MARKERS ok files={}".format(count))
        except Exception as e:
            _cue_log("RESTORE-MARKERS-ERROR {}".format(str(e)))

    # -- clipboard --

    def copy_context(self):
        # type: () -> None
        _copy_context(self)  # pyright: ignore[reportArgumentType]  # source `self` vs stub-typed param

    def paste_context(self):
        # type: () -> None
        _paste_context(self)  # pyright: ignore[reportArgumentType]  # source `self` vs stub-typed param

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

    _cue.sfx_manager.disabled_files = set(shared.get("disabled_files", []))
    _cue.trigger.active = _cue_dict.get("triggers_active", True)
    _cue.video_editor.encode_mode = _cue_dict.get("encode_mode", _cue.video_editor.MODE_INTERPOLATE)
    _cue.video_editor.remove_audio = _cue_dict.get("remove_audio", True)
    _cue.speed_resolver.seamless_transition = _cue_dict.get("seamless_transition", False)
