# -*- coding: utf-8 -*-
# CueMarkerStore -- the marker data leaf: entries, presets, migrations, and
# file-backed persistence.
#
# Owns the dict of marker entries, the audio/video preset dicts, and the
# session-created preset set, plus the dict-like surface, entry/pool mutators,
# sanitize/migrate passes, and persistence that read or write them.  Lives at
# _cue.marker_store (wired in cue_z.rpy) and is handed to CueMarkerManager,
# which keeps the coordinator role (contexts, resolve/detach glue, clipboard,
# scalar-load) and delegates data methods here.
#
# No module-level _cue reads: collaborators come in via the constructor
# (db, paths) plus an on_save callback for post-write side effects (undo
# capture), so the whole layer is testable against a real CueDatabase.

import errno
import os
import copy as _copy
import renpy

from cue_lib.backup import CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME, zip_tree
from cue_lib.constants import CUE_VOLUME_DEFAULT, CueExclusiveStart, CueLoopFrequency
from cue_lib.util import (
    _cue_log,
    is_img_key, is_vid_key, is_dlg_key, is_loop_key,
)

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, ItemsView, KeysView, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import (
        MarkerEntry, PoolDict, VideoPoolDict, VideoPreset,  # pyright: ignore[reportUnusedImport]
    )
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]


class ResolvedExclusive(object):
    """Resolved exclusive config snapshot. group 0 = Off."""
    def __init__(self, group=0, start=CueExclusiveStart.PLAY, hold=False):
        self.group = group
        self.start = start
        self.hold = hold

    def to_dict(self):
        # type: () -> Dict[str, Any]
        """Stored nested-dict form, for write-backs like _detach_pool."""
        return {"group": self.group, "start": self.start, "hold": self.hold}


class ResolvedPool(object):
    """Immutable snapshot of a resolved pool."""
    def __init__(self, files, volume, frequency, trigger_on_shake, exclusive=None):
        self.files = files
        self.volume = volume
        self.frequency = frequency
        self.trigger_on_shake = trigger_on_shake
        self.exclusive = exclusive if exclusive is not None else ResolvedExclusive()


class CueMarkerStore(object):
    """Marker entry + preset data with file-backed persistence.

    ``on_save`` is called once after every DB write (single-key or batch);
    the coordinator uses it to capture an undo snapshot.  ``_session_created``
    tracks presets created this session so a restore can tell them apart from
    presets loaded from disk (shared across games)."""

    def __init__(self, db, paths, on_save=None):
        # type: (CueDatabase, CuePaths, Optional[Callable[[], None]]) -> None
        self._db = db
        self._paths = paths
        self._on_save = on_save
        # The store attrs stay loosely typed here: they are loaded from
        # db.load_markers() (Dict[str, Any]) and mutated with partial pool
        # literals, so strict MarkerEntry typing would force a cascade of
        # "TypedDict can't narrow" suppressions. The .pyi keeps the strict
        # contract for consumers.
        self._data = {}
        self._presets = {}
        self._video_presets = {}
        # ("audio"|"video", name) -- presets created this session
        self._session_created = set()

    # -- dict-like interface --

    def __getitem__(self, key):
        # type: (str) -> MarkerEntry
        return self._data[key]

    def __setitem__(self, key, value):
        # type: (str, MarkerEntry) -> None
        self._data[key] = value

    def __delitem__(self, key):
        # type: (str) -> None
        del self._data[key]

    def __contains__(self, key):
        # type: (str) -> bool
        return key in self._data

    def get(self, key, default=None):
        # type: (str, Optional[MarkerEntry]) -> Optional[MarkerEntry]
        entry = self._data.get(key)
        if entry is None:
            return default
        return self._normalize_entry(entry)

    def setdefault(self, key, default):
        # type: (str, MarkerEntry) -> MarkerEntry
        return self._data.setdefault(key, default)

    def pop(self, key, *args):
        # type: (str, *MarkerEntry) -> MarkerEntry
        return self._data.pop(key, *args)

    def items(self):
        # type: () -> ItemsView[str, MarkerEntry]
        return self._data.items()

    def keys(self):
        # type: () -> KeysView[str]
        return self._data.keys()

    def __len__(self):
        # type: () -> int
        return len(self._data)

    # -- presets --

    def create_preset(self, name, pool_dict):
        # type: (str, PoolDict) -> None
        self._presets[name] = _copy.deepcopy(pool_dict)
        self._session_created.add(("audio", name))
        self._db_save_preset(name)
        _cue_log("CREATE-PRESET name={} files={} vol={:.1f}".format(
            name, len(pool_dict.get("files", [])), pool_dict.get("volume", CUE_VOLUME_DEFAULT)))

    def delete_preset(self, name):
        # type: (str) -> None
        if name in self._presets:
            del self._presets[name]
            self._session_created.discard(("audio", name))
            self._db_save_preset(name)
            _cue_log("DELETE-PRESET name={}".format(name))

    def get_preset(self, name):
        # type: (str) -> Optional[PoolDict]
        return self._presets.get(name)

    def list_presets(self):
        # type: () -> List[str]
        return sorted(self._presets.keys())

    # -- video presets --

    def create_video_preset(self, name, entry, source_dur=0.0):
        # type: (str, Any, float) -> None
        """Save a video preset from a marker entry's pools.

        ``source_dur`` is the source video's duration, supplied by the
        coordinator (the store has no video dependency)."""
        pools = entry.get("pools", [])
        if not pools:
            return
        clean = []
        for pool in pools:
            if pool.get("time") is not None:
                clean.append({
                    "time": pool["time"],
                    "files": list(pool.get("files", [])),
                    "volume": pool.get("volume", CUE_VOLUME_DEFAULT),
                })
        if not clean:
            return
        clean.sort(key=lambda e: e["time"])
        self._video_presets[name] = {
            "pools": clean,
            "volume": entry.get("volume", CUE_VOLUME_DEFAULT),
            "source_duration": max(source_dur, 0.0),
        }
        self._session_created.add(("video", name))
        self._db_save_video_preset(name)
        _cue_log("CREATE-VIDEO-PRESET name={} markers={} dur={:.1f}".format(
            name, len(clean), source_dur))

    def delete_video_preset(self, name):
        # type: (str) -> None
        if name in self._video_presets:
            del self._video_presets[name]
            self._session_created.discard(("video", name))
            self._db_save_video_preset(name)
            _cue_log("DELETE-VIDEO-PRESET name={}".format(name))

    def get_video_preset(self, name):
        # type: (str) -> Optional[VideoPreset]
        return self._video_presets.get(name)

    def list_video_presets(self):
        # type: () -> List[str]
        return sorted(self._video_presets.keys())

    # -- resolve (preset -> concrete pool) --

    def resolve_pool(self, pool):
        # type: (PoolDict) -> ResolvedPool
        defaults = self._presets.get(pool["preset"], {}) if "preset" in pool else {}
        files = pool.get("files", defaults.get("files", []))
        volume = pool.get("volume", defaults.get("volume", CUE_VOLUME_DEFAULT))
        frequency = pool.get("frequency", defaults.get("frequency", CueLoopFrequency.NORMAL))
        trigger_on_shake = pool.get("trigger_on_shake", defaults.get("trigger_on_shake", False))
        exclusive = self._resolve_exclusive(pool, defaults)
        return ResolvedPool(list(files), volume, frequency, trigger_on_shake, exclusive)

    @staticmethod
    def _resolve_exclusive(pool, defaults):
        # type: (PoolDict, Any) -> ResolvedExclusive
        excl = pool.get("exclusive", {})
        if not isinstance(excl, dict):  # legacy bool from unmigrated saves
            excl = {}
        base = defaults.get("exclusive", {})
        if not isinstance(base, dict):
            base = {}
        return ResolvedExclusive(
            excl.get("group", base.get("group", 0)),
            excl.get("start", base.get("start", CueExclusiveStart.PLAY)),
            excl.get("hold", base.get("hold", False)))

    # -- entry / pool mutators --

    def _normalize_entry(self, entry):
        # type: (Any) -> MarkerEntry
        if "pools" not in entry:
            entry["pools"] = [{"files": entry.pop("files", [])}]
        entry.pop('replay_id', None)
        entry.setdefault("replay", renpy.store._in_replay)
        return entry

    def _get_or_create_entry(self, trigger_key):
        # type: (str) -> Any
        entry = self._data.get(trigger_key)
        if entry is None:
            entry = {"pools": []}
            self._data[trigger_key] = entry
        entry = self._normalize_entry(entry)
        return entry

    def _ensure_pool(self, trigger_key, pool_index):
        # type: (str, int) -> PoolDict
        entry = self._get_or_create_entry(trigger_key)
        pools = entry["pools"]
        if not pools:
            pools.append({
                "files": [],
                "volume": CUE_VOLUME_DEFAULT,
            })
        if pool_index < 0:
            pool_index = 0
        if pool_index >= len(pools):
            pool_index = len(pools) - 1
        return pools[pool_index]

    def _add_file_to_pool(self, trigger_key, filename, pool_index=0):
        # type: (str, str, int) -> None
        self._detach_pool(trigger_key, pool_index)
        pool = self._ensure_pool(trigger_key, pool_index)
        files = pool.setdefault("files", [])
        if filename not in files:
            files.append(filename)
        self._db_save_marker(trigger_key)

    def _remove_file_from_pool(self, trigger_key, file_index, pool_index=0):
        # type: (str, int, int) -> None
        self._detach_pool(trigger_key, pool_index)
        entry = self._data.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if pools:
            if not (0 <= pool_index < len(pools)):
                return
            pool = pools[pool_index]
            files = pool.get("files", [])
            if 0 <= file_index < len(files):
                files.pop(file_index)
            if not files:
                pools.pop(pool_index)
            if not pools:
                del self._data[trigger_key]
            self._db_save_marker(trigger_key)
        elif "files" in entry:
            files = entry["files"]
            if 0 <= file_index < len(files):
                files.pop(file_index)
                if not files:
                    del self._data[trigger_key]
                self._db_save_marker(trigger_key)

    def _stamp_preset(self, trigger_key, preset_name, pool_index=0):
        # type: (str, str, int) -> None
        entry = self._get_or_create_entry(trigger_key)
        pools = entry["pools"]
        while len(pools) <= pool_index:
            pools.append({"files": [], "volume": CUE_VOLUME_DEFAULT})
        pools[pool_index] = {"preset": preset_name}
        self._db_save_marker(trigger_key)
        _cue_log("STAMP-PRESET key={} pi={} preset={}".format(
            trigger_key, pool_index, preset_name))

    def _detach_pool(self, trigger_key, pool_index):
        # type: (str, int) -> bool
        entry = self._data.get(trigger_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return False
        pool = pools[pool_index]
        if "preset" not in pool:
            return False
        preset_name = pool["preset"]
        preset = self._presets.get(preset_name, {})
        r = self.resolve_pool(pool)
        del pool["preset"]
        pool["files"] = r.files
        pool["volume"] = r.volume
        if "frequency" in preset:
            pool["frequency"] = r.frequency
        if "trigger_on_shake" in preset:
            pool["trigger_on_shake"] = r.trigger_on_shake
        # Exclusive config: copy when the preset or a pool-level override
        # (toggled before detach) defines it, so overrides survive detach.
        if "exclusive" in preset or "exclusive" in pool:
            pool["exclusive"] = r.exclusive.to_dict()
        self._db_save_marker(trigger_key)
        _cue_log("DETACH-POOL key={} pi={} preset={} files={}".format(
            trigger_key, pool_index, preset_name, len(r.files)))
        return True

    def _resolve_video_pools(self, entry):
        # type: (Any) -> List[VideoPoolDict]
        raw = entry.get("pools", [])
        resolved = []
        for pool in raw:
            if "preset" in pool:
                r = self.resolve_pool(pool)
                resolved_pool = _copy.deepcopy(pool)
                resolved_pool.pop("preset", None)
                resolved_pool["files"] = r.files
                resolved_pool["volume"] = r.volume
                resolved.append(resolved_pool)
            else:
                resolved.append(pool)
        return resolved

    # -- sanitize / migration passes --

    @staticmethod
    def _clean_pool_list(pools):
        # type: (List[PoolDict]) -> Tuple[List[PoolDict], int]
        stripped = 0
        clean = []
        for pool in pools:
            if pool.get("time") is not None:
                clean.append(pool)
            else:
                stripped += 1
        return clean, stripped

    def _sanitize_video_presets(self):
        # type: () -> int
        total_stripped = 0
        for _, preset in list(self._video_presets.items()):
            pools = preset.get("pools")
            if not pools:
                continue
            clean, stripped = self._clean_pool_list(pools)
            if stripped:
                preset["pools"] = clean
                total_stripped += stripped
        return total_stripped

    def _sanitize_video_pools(self):
        # type: () -> int
        total_stripped = 0
        for key, entry in list(self._data.items()):
            if not is_vid_key(key):
                continue
            pools = entry.get("pools")
            if not pools:
                continue
            clean, stripped = self._clean_pool_list(pools)
            if stripped:
                entry["pools"] = clean
                total_stripped += stripped
        return total_stripped

    def _sanitize_video_pools_tracked(self):
        # type: () -> Set[str]
        modified = set()
        for key, entry in list(self._data.items()):
            if not is_vid_key(key):
                continue
            pools = entry.get("pools")
            if not pools:
                continue
            clean, stripped = self._clean_pool_list(pools)
            if stripped:
                entry["pools"] = clean
                modified.add(key)

        total = len(modified)
        if total:
            _cue_log("SAVE-MARKERS: sanitized {} malformed video pool(s)".format(total))
        return modified

    def _normalize_all(self):
        # type: () -> bool
        changed = False
        for key, entry in list(self._data.items()):
            if is_img_key(key) or is_dlg_key(key) or is_loop_key(key):
                if "pools" not in entry:
                    self._normalize_entry(entry)
                    changed = True
            if is_loop_key(key) and "frequency" in entry:
                freq = entry.pop("frequency")
                for pool in entry.get("pools", []):
                    pool.setdefault("frequency", freq)
                changed = True
        return changed

    def _migrate_legacy_exclusive(self):
        # type: () -> int
        """Legacy bool 'exclusive' -> nested dict (idempotent).

        Old loop-exclusive pools become G1 + Wait + hold: polite
        wait-then-reserve, now with G1 membership in the unified system.
        Legacy False values are cleaned up (absence = plain citizen)."""
        migrated = 0
        for entry in list(self._data.values()):
            for pool in entry.get("pools", []):
                if self._migrate_exclusive_pool(pool):
                    migrated += 1
        for preset in list(self._presets.values()):
            if self._migrate_exclusive_pool(preset):
                migrated += 1
        return migrated

    @staticmethod
    def _migrate_exclusive_pool(pool):
        # type: (Any) -> bool
        excl = pool.get("exclusive")
        if not isinstance(excl, bool):
            return False
        if excl:
            pool["exclusive"] = {"group": 1, "start": CueExclusiveStart.WAIT, "hold": True}
        else:
            del pool["exclusive"]
        return True

    @staticmethod
    def _migrate_colon_key(key):
        # type: (str) -> str
        """Convert legacy colon keys (v:file) to underscore (v_file).
        Also normalizes dialogue pipe separator | to __."""
        if key.startswith("v:"):
            return "v_" + key[2:]
        if key.startswith("i:"):
            return "i_" + key[2:]
        if key.startswith("d:"):
            key = "d_" + key[2:]
        elif key.startswith("l:"):
            return "l_" + key[2:]
        # Normalize legacy pipe separator in dialogue keys
        if key.startswith("d_") and "|" in key:
            file_part, dialogue = key[2:].split("|", 1)
            key = "d_{}__{}".format(file_part, dialogue)
        return key

    def _migrate_speed_mode_rename(self):
        # type: () -> None
        for key, entry in list(self._data.items()):
            if is_vid_key(key) and entry.get("speed_mode") == "sequence":
                entry["speed_mode"] = "multi"
        for preset in self._video_presets.values():
            if preset.get("speed_mode") == "sequence":
                preset["speed_mode"] = "multi"

    def _migrate_video_timestamps_to_pools(self):
        # type: () -> Tuple[int, int]
        entries_changed = 0
        for key, entry in list(self._data.items()):
            if is_vid_key(key) and "timestamps" in entry:
                if "pools" not in entry:
                    entry["pools"] = entry.pop("timestamps")
                else:
                    del entry["timestamps"]
                entries_changed += 1
        presets_changed = 0
        for _, preset in list(self._video_presets.items()):
            if "timestamps" in preset:
                if "pools" not in preset:
                    preset["pools"] = preset.pop("timestamps")
                else:
                    del preset["timestamps"]
                presets_changed += 1
        if entries_changed or presets_changed:
            _cue_log("MIGRATE-VIDEO-POOLS entries={} presets={}".format(
                entries_changed, presets_changed))
        return entries_changed, presets_changed

    # -- persistence --

    def reload_presets(self):
        # type: () -> None
        """Re-read presets from the shared data store. Merges new/updated
        presets from disk (other games may have added them). Never deletes."""
        db = self._db
        if db is None or not db.is_open():
            return
        audio, video = db.load_presets()
        self._presets.update(audio)
        self._video_presets.update(video)

    # ------------------------------------------------------------------
    # Public save API -- targeted data store writes for routine mutations
    # ------------------------------------------------------------------

    def save_marker(self, key):
        # type: (str) -> None
        """Persist one marker entry to data store. Call after mutating self._data[key]."""
        self._db_save_marker(key)

    def save_markers(self, keys):
        # type: (List[str]) -> None
        """Persist several marker entries in one batch. Call after mutating
        self._data[key] for each key. Side effects run once for the whole
        batch, so a multi-key edit produces a single undo step."""
        db = self._db
        if db is not None and db.is_open():
            for key in keys:
                if key in self._data:
                    db.save_marker(key, self._data[key])
                else:
                    db.delete_marker(key)
        self._post_save()

    def save_preset(self, name):
        # type: (str) -> None
        """Persist one audio preset to data store."""
        self._db_save_preset(name)

    def save_video_preset(self, name):
        # type: (str) -> None
        """Persist one video preset to data store."""
        self._db_save_video_preset(name)

    # ------------------------------------------------------------------
    # Internal helpers -- write one item to DB, then run side effects
    # ------------------------------------------------------------------

    def _db_save_marker(self, key):
        # type: (str) -> None
        db = self._db
        if db is not None and db.is_open():
            if key in self._data:
                db.save_marker(key, self._data[key])
            else:
                db.delete_marker(key)
        self._post_save()

    def _db_save_preset(self, name):
        # type: (str) -> None
        db = self._db
        if db is not None and db.is_open():
            if name in self._presets:
                db.save_preset("audio", name, self._presets[name])
            else:
                db.delete_preset("audio", name)
        self._post_save()

    def _db_save_video_preset(self, name):
        # type: (str) -> None
        db = self._db
        if db is not None and db.is_open():
            if name in self._video_presets:
                db.save_preset("video", name, self._video_presets[name])
            else:
                db.delete_preset("video", name)
        self._post_save()

    def _post_save(self):
        # type: () -> None
        """Common side effects after any DB write."""
        stripped_keys = self._sanitize_video_pools_tracked()
        db = self._db
        if db is not None and db.is_open():
            for key in stripped_keys:
                if key in self._data:
                    db.save_marker(key, self._data[key])
        if self._on_save is not None:
            self._on_save()

    def save_all(self):
        # type: () -> None
        """Full save of all markers + presets to DB.
        Used by migration, restore, and undo/redo."""
        db = self._db
        if db is not None and db.is_open():
            for key in self._data:
                db.save_marker(key, self._data[key])
            for name, data in self._presets.items():
                db.save_preset("audio", name, data)
            for name, data in self._video_presets.items():
                db.save_preset("video", name, data)
        if self._on_save is not None:
            self._on_save()

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
        db = self._db
        if db is None or not db.is_open():
            return
        for key in old_marker_keys - set(self._data):
            db.delete_marker(key)
        for name, dropped in old_presets.items():
            if name in self._presets:
                continue
            if ("audio", name) in old_session_created and db.preset_file_matches("audio", name, dropped):
                db.delete_preset("audio", name)
        for name, dropped in old_video_presets.items():
            if name in self._video_presets:
                continue
            if ("video", name) in old_session_created and db.preset_file_matches("video", name, dropped):
                db.delete_preset("video", name)

    # -- load --

    def load_from_db(self):
        # type: () -> None
        """Load markers + presets from the data store.

        This is the disk side of CueMarkerManager.load_persistent; the
        persistent-scalar side (triggers_active, encode_mode, ...) stays on
        the coordinator because it fans out to other managers."""
        db = self._db
        if db is None or not db.is_open():
            self._data = {}
            self._video_presets = {}
            return

        self._data = db.load_markers()
        self._presets, self._video_presets = db.load_presets()
        self._migrate_video_timestamps_to_pools()
        self._sanitize_video_pools()
        self._sanitize_video_presets()
        self._normalize_all()
        self._migrate_speed_mode_rename()
        self._migrate_legacy_exclusive()

    # -- backup --

    def backup_to_file(self):
        # type: () -> None
        """Zip the shared data/ tree to {shared}/backups/backup.zip."""
        try:
            db = self._db
            if db is None or not db.is_open():
                return
            data_dir = os.path.join(self._paths.root, "data")
            if not os.path.isdir(data_dir):
                _cue_log("DUMP-MARKERS-NO-DATA")
                return
            backups_dir = os.path.join(self._paths.root, CUE_BACKUP_DIR)
            if not os.path.isdir(backups_dir):
                try:
                    os.makedirs(backups_dir)
                except OSError as e:
                    # The auto-backup thread (db._backup) can create
                    # {root}/backups/ between the isdir check and here -- its
                    # makedirs of backups/auto/ creates the parent first.
                    # EEXIST is benign; anything else is a real failure.
                    if e.errno != errno.EEXIST:
                        raise
            zip_path = os.path.join(backups_dir, CUE_MANUAL_BACKUP_NAME)
            tmp_path = os.path.join(
                backups_dir, "{}.{}.tmp".format(CUE_MANUAL_BACKUP_NAME, self._paths.game_id))
            count = zip_tree(data_dir, zip_path, tmp_path)
            _cue_log("DUMP-MARKERS files={} path={}".format(count, zip_path))
        except Exception as e:
            _cue_log("DUMP-MARKERS-ERROR {}".format(str(e)))
