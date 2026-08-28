# -*- coding: utf-8 -*-

# CueMarkerStore -- the marker data leaf: entries, pool mutators, migrations,
# and file-backed persistence.
#
# Owns the dict of marker entries and the dict-like surface, entry/pool
# mutators, entry-side sanitize/migrate passes, and marker persistence.  The
# audio/video preset dicts live in CuePresetStore (self._preset_store), which
# this store consults for the two preset reads it makes (resolve_pool defaults,
# detach materialization).  Lives at _cue.marker_store (wired in cue_z.rpy)
# and is handed to CueMarkerManager, which keeps the coordinator role.
#
# No module-level _cue reads: collaborators come in via the constructor
# (db, paths, on_save) plus an optional preset store; when preset_store is
# omitted one is auto-built on the same db/on_save.

import copy as _copy
import renpy

from cue_lib.constants import CUE_VOLUME_DEFAULT, CueExclusiveStart, CueLoopFrequency
from cue_lib.pool import CuePool
from cue_lib.preset_store import CuePresetStore
from cue_lib.util import (
    _cue_clean_pool_list,
    _cue_log,
    _cue_migrate_exclusive_pool,
    _cue_remove_ref,
    _cue_resolve_files,
    is_vid_key,
    is_loop_key,
)

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, ItemsView, KeysView, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import (
        IgroupDict,
        MarkerEntry,
        PoolDict,
        VideoPoolDict,
        VideoPreset,  # pyright: ignore[reportUnusedImport]
    )
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]
    from cue_lib.preset_store import CuePresetStore  # pyright: ignore[reportUnusedImport]


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

    def __repr__(self):
        # type: () -> str
        return "ResolvedExclusive(group={!r}, start={!r}, hold={!r})".format(self.group, self.start, self.hold)


class ResolvedPool(object):
    """Immutable snapshot of a resolved pool.

    ``refs`` is the stored view -- the pool's own file refs (folder refs and
    preset lists intact).  ``files`` is the playback view -- concrete playable
    files (folder refs expanded, intensity level files when folded), or None
    when resolve_pool was called without expand.  ``intensity`` carries the
    folded intensity resolution when resolve_pool was given a runtime speed."""

    def __init__(self, refs, files, volume, frequency, trigger_on_shake, exclusive=None, igroup=None, intensity=None):
        # type: (List[str], Optional[List[str]], float, int, bool, Optional[Any], Optional[Any], Optional[Any]) -> None
        self.refs = refs
        self.files = files
        self.igroup = igroup  # IgroupHookDict or None
        self.volume = volume
        self.frequency = frequency
        self.trigger_on_shake = trigger_on_shake
        self.exclusive = exclusive if exclusive is not None else ResolvedExclusive()
        self.intensity = intensity

    @property
    def volume_mult(self):
        # type: () -> Optional[float]
        return self.intensity.volume_mult if self.intensity is not None else None

    @property
    def freq_mult(self):
        # type: () -> Optional[float]
        return self.intensity.freq_mult if self.intensity is not None else None

    @property
    def level(self):
        # type: () -> Optional[int]
        return self.intensity.level if self.intensity is not None else None

    def __repr__(self):
        # type: () -> str
        return (
            "ResolvedPool(refs={!r}, files={!r}, volume={!r}, frequency={!r}, "
            "trigger_on_shake={!r}, exclusive={!r}, igroup={!r}, intensity={!r})"
        ).format(
            self.refs,
            self.files,
            self.volume,
            self.frequency,
            self.trigger_on_shake,
            self.exclusive,
            self.igroup,
            self.intensity,
        )


class CueMarkerStore(object):
    """Marker entry data with file-backed persistence.

    ``on_save`` is called once after every DB write (single-key or batch);
    the coordinator uses it to capture an undo snapshot.  Preset data lives in
    ``self._preset_store`` (CuePresetStore)."""

    def __init__(self, db, paths, on_save=None, preset_store=None, intensity=None):
        # type: (CueDatabase, CuePaths, Optional[Callable[[], None]], Optional[CuePresetStore], Optional[Any]) -> None
        self._db = db
        self._paths = paths
        self._on_save = on_save
        if preset_store is None:
            preset_store = CuePresetStore(db, on_save)
        self._preset_store = preset_store
        # The store attrs stay loosely typed here: they are loaded from
        # db.load_markers() (Dict[str, Any]) and mutated with partial pool
        # literals, so strict MarkerEntry typing would force a cascade of
        # "TypedDict can't narrow" suppressions. The .pyi keeps the strict
        # contract for consumers.
        self._data = {}
        self._intensity = intensity

    # -- transitional preset read-throughs (Chunks 4-5 move consumers to
    # _cue.presets / self._preset_store; kept so manager shims and tests that
    # read/write the whole dicts keep working until then) --

    @property
    def _presets(self):
        # type: () -> Dict[str, PoolDict]
        return self._preset_store.audio._presets

    @_presets.setter
    def _presets(self, value):
        # type: (Dict[str, PoolDict]) -> None
        self._preset_store.audio._presets = value

    @property
    def _video_presets(self):
        # type: () -> Dict[str, VideoPreset]
        return self._preset_store.video._presets

    @_video_presets.setter
    def _video_presets(self, value):
        # type: (Dict[str, VideoPreset]) -> None
        self._preset_store.video._presets = value

    @property
    def _session_created(self):
        # type: () -> Set[Tuple[str, str]]
        return self._preset_store._session_created

    @_session_created.setter
    def _session_created(self, value):
        # type: (Set[Tuple[str, str]]) -> None
        self._preset_store._session_created = value

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
        return self._data.get(key, default)

    def setdefault(self, key, default):
        # type: (str, MarkerEntry) -> MarkerEntry
        return self._normalize_entry(self._data.setdefault(key, default))

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

    # -- preset delegators (transitional; preset logic lives in the preset
    # store, manager pass-throughs forward here until Chunk 5) --

    def create_preset(self, name, pool_dict):
        # type: (str, PoolDict) -> None
        self._preset_store.audio.create(name, pool_dict)

    def delete_preset(self, name):
        # type: (str) -> None
        self._preset_store.audio.delete(name)

    def get_preset(self, name):
        # type: (str) -> Optional[PoolDict]
        return self._preset_store.audio.get(name)

    def list_presets(self):
        # type: () -> List[str]
        return self._preset_store.audio.list()

    def create_video_preset(self, name, entry, source_dur=0.0):
        # type: (str, Any, float) -> None
        self._preset_store.video.create(name, entry, source_dur)

    def delete_video_preset(self, name):
        # type: (str) -> None
        self._preset_store.video.delete(name)

    def get_video_preset(self, name):
        # type: (str) -> Optional[VideoPreset]
        return self._preset_store.video.get(name)

    def list_video_presets(self):
        # type: () -> List[str]
        return self._preset_store.video.list()

    # -- resolve (preset -> concrete pool) --

    def resolve_pool(self, pool, speed=None, variants=None, flags=None, expand=False):
        # type: (PoolDict, Optional[float], Optional[List[float]], Optional[Any], bool) -> ResolvedPool
        """Resolve a pool to its concrete fire snapshot.

        ``refs`` always holds the pool's stored file refs (folder refs and
        preset lists intact).  With ``expand=True``, ``files`` becomes the
        concrete playable list -- the intensity fold's level files when a
        runtime ``speed`` hooks an igroup (already expanded by the intensity
        manager), otherwise the pool's refs with folder refs expanded.
        ``files`` is None when ``expand`` is False, so the default path never
        touches the SFX library."""
        defaults = self._preset_store.audio._presets.get(pool["preset"], {}) if "preset" in pool else {}
        refs = pool.get("files", defaults.get("files", []))
        volume = pool.get("volume", defaults.get("volume", CUE_VOLUME_DEFAULT))
        frequency = pool.get("frequency", defaults.get("frequency", CueLoopFrequency.MEDIUM))
        trigger_on_shake = pool.get("trigger_on_shake", defaults.get("trigger_on_shake", False))
        exclusive = self._resolve_exclusive(pool, defaults)
        hook = pool.get("igroup", defaults.get("igroup"))
        igroup = hook.get("name") if hook else None
        ilevel_id = hook.get("level") if hook else None
        intensity = None
        if igroup is not None and speed is not None and self._intensity is not None:
            intensity = self._intensity.resolve_pool_intensity(igroup, ilevel_id, speed, variants, flags)
        files = None
        if expand:
            if intensity is not None:
                files = intensity.files
            else:
                files = _cue_resolve_files(list(refs))
        return ResolvedPool(list(refs), files, volume, frequency, trigger_on_shake, exclusive, hook, intensity)

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
            excl.get("hold", base.get("hold", False)),
        )

    # -- entry / pool mutators --

    def _normalize_entry(self, entry):
        # type: (Any) -> MarkerEntry
        if "pools" not in entry:
            entry["pools"] = [{"files": entry.pop("files", [])}]
        entry.pop('replay_id', None)
        # Only edits inside a replay stamp replay; writing a falsy _in_replay
        # would pin the marker as non-replay and block later re-scoping.
        in_replay = renpy.store._in_replay
        if in_replay:
            entry["replay"] = in_replay
        return entry

    def _get_or_create_entry(self, marker_key):
        # type: (str) -> Any
        entry = self._data.get(marker_key)
        if entry is None:
            entry = {"pools": []}
            self._data[marker_key] = entry
        entry = self._normalize_entry(entry)
        return entry

    def _ensure_pool(self, marker_key, pool_index):
        # type: (str, int) -> PoolDict
        entry = self._get_or_create_entry(marker_key)
        pools = entry["pools"]
        if not pools:
            pools.append({"files": [], "volume": CUE_VOLUME_DEFAULT})
        if pool_index < 0:
            pool_index = 0
        if pool_index >= len(pools):
            pool_index = len(pools) - 1
        return pools[pool_index]

    def _remove_file_from_pool(self, marker_key, file_index, pool_index=0):
        # type: (str, int, int) -> bool
        """Remove one ref by index from a pool, pruning the emptied pool and
        entry (one-shot image/dialogue lifecycle).  Legacy single-file entries
        keep their own branch.  Returns True when something was removed."""
        self._detach_pool(marker_key, pool_index)
        entry = self._data.get(marker_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if pools:
            if not (0 <= pool_index < len(pools)):
                return False
            refs = pools[pool_index].get("files", [])
            if not (0 <= file_index < len(refs)):
                return False
            return self._remove_ref_from_pool(marker_key, refs[file_index], pool_index, prune=True)
        if "files" in entry:
            files = entry["files"]
            if 0 <= file_index < len(files):
                files.pop(file_index)
                if not files:
                    del self._data[marker_key]
                self._db_save_marker(marker_key)
                return True
        return False

    def _remove_ref_from_pool(self, marker_key, path, pool_index=0, prune=False):
        # type: (str, str, int, bool) -> bool
        """Remove one ref by path from a pool, expanding a covering folder ref
        into its children and dropping the child.  Detaches a preset first; a
        pool hooked to an intensity group owns no refs (no-op).  With
        ``prune``, an emptied pool (and entry) is dropped.  Returns True when
        something was removed."""
        self._detach_pool(marker_key, pool_index)
        entry = self._data.get(marker_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if not pools or not (0 <= pool_index < len(pools)):
            return False
        pool = pools[pool_index]
        if "igroup" in pool:
            return False
        files = pool.get("files", [])
        _, removed = _cue_remove_ref(files, path)
        if not removed:
            return False
        if prune and not files:
            pools.pop(pool_index)
            if not pools:
                del self._data[marker_key]
        self._db_save_marker(marker_key)
        return True

    def _clear_pool_files(self, marker_key, pool_index=0):
        # type: (str, int) -> bool
        """Clear a pool's own refs, keeping the pool row.  Detaches a preset
        first; a pool hooked to an intensity group is detached from the hook
        (its refs are dynamic, so clearing the pool means dropping the hook).
        Returns True when the pool changed."""
        self._detach_pool(marker_key, pool_index)
        entry = self._data.get(marker_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if not pools or not (0 <= pool_index < len(pools)):
            return False
        pool = pools[pool_index]
        if "igroup" in pool:
            pool.pop("igroup")
            pool["files"] = []
            self._db_save_marker(marker_key)
            return True
        if not pool.get("files", []):
            return False
        pool["files"] = []
        self._db_save_marker(marker_key)
        return True

    def _stamp_preset(self, marker_key, preset_name, pool_index=0):
        # type: (str, str, int) -> None
        entry = self._get_or_create_entry(marker_key)
        pools = entry["pools"]
        while len(pools) <= pool_index:
            pools.append({"files": [], "volume": CUE_VOLUME_DEFAULT})
        pools[pool_index] = {"preset": preset_name}
        self._db_save_marker(marker_key)
        _cue_log("STAMP-PRESET key={} pi={} preset={}".format(marker_key, pool_index, preset_name))

    def _detach_pool(self, marker_key, pool_index):
        # type: (str, int) -> bool
        entry = self._data.get(marker_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return False
        pool = pools[pool_index]
        if "preset" not in pool:
            return False
        preset_name = pool["preset"]
        preset = self._preset_store.audio._presets.get(preset_name, {})
        r = self.resolve_pool(pool)
        del pool["preset"]
        pool["files"] = r.refs
        pool["volume"] = r.volume
        if "frequency" in preset:
            pool["frequency"] = r.frequency
        if "trigger_on_shake" in preset:
            pool["trigger_on_shake"] = r.trigger_on_shake
        # Exclusive config: copy when the preset or a pool-level override
        # (toggled before detach) defines it, so overrides survive detach.
        if "exclusive" in preset or "exclusive" in pool:
            pool["exclusive"] = r.exclusive.to_dict()
        self._db_save_marker(marker_key)
        _cue_log("DETACH-POOL key={} pi={} preset={} files={}".format(marker_key, pool_index, preset_name, len(r.refs)))
        return True

    def pool(self, marker_key, pool_index=0):
        # type: (str, int) -> CuePool
        """Ephemeral view over one pool row.  One view = one op; the view
        re-resolves the row from the live dict each call."""
        return CuePool(self, marker_key, pool_index)

    def _resolve_video_pools(self, entry):
        # type: (Any) -> List[VideoPoolDict]
        raw = entry.get("pools", [])
        resolved = []
        for pool in raw:
            if "preset" in pool:
                r = self.resolve_pool(pool)
                resolved_pool = _copy.deepcopy(pool)
                resolved_pool.pop("preset", None)
                resolved_pool["files"] = r.refs
                resolved_pool["volume"] = r.volume
                resolved.append(resolved_pool)
            else:
                resolved.append(pool)
        return resolved

    # -- sanitize / migration passes --

    @staticmethod
    def _clean_pool_list(pools):
        # type: (List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]
        return _cue_clean_pool_list(pools)

    def _sanitize_video_presets(self):
        # type: () -> int
        return self._preset_store.video._sanitize_video_presets()

    def _sanitize_video_pools(self):
        # type: () -> int
        total_stripped = 0
        for key, entry in list(self._data.items()):
            if not is_vid_key(key):
                continue
            pools = entry.get("pools")
            if not pools:
                continue
            clean, stripped = _cue_clean_pool_list(pools)
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
            clean, stripped = _cue_clean_pool_list(pools)
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
        Legacy False values are cleaned up (absence = plain citizen).
        Entry-side only; presets migrate in CuePresetStore."""
        migrated = 0
        for entry in list(self._data.values()):
            for pool in entry.get("pools", []):
                if self._migrate_exclusive_pool(pool):
                    migrated += 1
        return migrated

    @staticmethod
    def _migrate_exclusive_pool(pool):
        # type: (Any) -> bool
        return _cue_migrate_exclusive_pool(pool)

    def _migrate_speed_mode_rename(self):
        # type: () -> None
        for key, entry in list(self._data.items()):
            if is_vid_key(key) and entry.get("speed_mode") == "sequence":
                entry["speed_mode"] = "multi"

    def _migrate_marker_keys(self):
        # type: () -> None
        """Rename marker keys that predate the single/multi split.

        speed_pref/speed_sequence are migrated because their values matter
        (single-mode speed, custom multi sequence).  The auto_speed and
        intensity fields were flattened into the entry; their nested readers
        default when absent, so old flat values are dropped without migration.
        """
        for entry in self._data.values():
            if "speed_pref" in entry and "single_speed_pref" not in entry:
                entry["single_speed_pref"] = entry.pop("speed_pref")
            if "speed_sequence" in entry and "multi_speed_sequence" not in entry:
                entry["multi_speed_sequence"] = entry.pop("speed_sequence")

    def _migrate_video_timestamps_to_pools(self):
        # type: () -> int
        entries_changed = 0
        for key, entry in list(self._data.items()):
            if is_vid_key(key) and "timestamps" in entry:
                if "pools" not in entry:
                    entry["pools"] = entry.pop("timestamps")
                else:
                    del entry["timestamps"]
                entries_changed += 1
        if entries_changed:
            _cue_log("MIGRATE-VIDEO-POOLS entries={}".format(entries_changed))
        return entries_changed

    # -- persistence --

    def reload_presets(self):
        # type: () -> None
        """Re-read presets from the shared data store. Merges new/updated
        presets from disk (other games may have added them). Never deletes."""
        self._preset_store.reload_presets()

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
        self._post_save(keys)

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
        self._post_save([key])

    def _post_save(self, keys=None):
        # type: (Optional[List[str]]) -> None
        """Common side effects after any DB write.  ``keys`` names the marker
        entries just written (None for preset-only saves); the malformed
        video-pool repair only runs when a video key is among them, so audio
        and preset saves skip the all-markers scan."""
        if keys and any(is_vid_key(key) for key in keys):
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
        """Full save of all markers to DB. Used by migration, restore, and
        undo/redo.  Presets persist through CuePresetStore.save_all()."""
        db = self._db
        if db is not None and db.is_open():
            for key in self._data:
                db.save_marker(key, self._data[key])
        if self._on_save is not None:
            self._on_save()

    def delete_removed_files(self, old_marker_keys):
        # type: (Set[str]) -> None
        """Delete DB files for marker keys a restore just dropped.

        Marker files are removed by key diff -- marker stores are per-game and
        only mutated by this session, so any dropped key was created here.
        Preset cleanup lives in CuePresetStore.delete_removed_files."""
        db = self._db
        if db is None or not db.is_open():
            return
        for key in old_marker_keys - set(self._data):
            db.delete_marker(key)

    # -- load --

    def load_from_db(self):
        # type: () -> None
        """Load markers + presets from the data store.

        Marker entries load here (with the entry-side migrations); the preset
        load and its migrations run in CuePresetStore.load.  This is
        the disk side of CueMarkerManager.load_persistent; the persistent-
        scalar side (triggers_active, encode_mode, ...) stays on the
        coordinator because it fans out to other managers."""
        db = self._db
        if db is None or not db.is_open():
            self._data = {}
        else:
            self._data = db.load_markers()
            self._migrate_video_timestamps_to_pools()
            self._sanitize_video_pools()
            self._normalize_all()
            self._migrate_speed_mode_rename()
            self._migrate_legacy_exclusive()
            self._migrate_marker_keys()
        self._preset_store.load()


def _cue_migrate_intensity_hooks(store, igroups):
    # type: (CueMarkerStore, Dict[str, IgroupDict]) -> int
    """One-time: convert legacy folder-hooked pools to nested igroup hooks.

    A legacy hooked pool holds a folder ref (trailing ``/``) in its
    ``files``; the old folder-scan machinery expanded it into the group's
    level content.  The level IS now the pool: set the nested ``igroup``
    hook and clear ``files``.  Returns the number of pools rewritten.  Idempotent
    -- a rewritten pool has empty ``files``, so a re-run finds no folder-hooks
    and changes nothing."""
    folder_map = {}
    for name, data in sorted(igroups.items()):
        for level in data.get("levels", []):
            for f in level.get("files", []):
                if f.endswith("/") and f not in folder_map:
                    folder_map[f] = (name, level.get("id"))
    migrated = 0
    for entry in list(store._data.values()):
        for pool in entry.get("pools", []):
            files = pool.get("files")
            if not files:
                continue
            for f in files:
                if f in folder_map:
                    group, ilevel_id = folder_map[f]
                    pool["igroup"] = {"name": group, "level": ilevel_id}
                    pool["files"] = []
                    migrated += 1
                    break
    if migrated:
        _cue_log("MIGRATE-INTENSITY-HOOKS pools={}".format(migrated))
    return migrated
