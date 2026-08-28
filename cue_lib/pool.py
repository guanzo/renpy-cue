# -*- coding: utf-8 -*-
# CuePool / CueAudioPreset / CueVideoPresetPool -- ephemeral views over one
# pool row (an entry pool or a preset row).
#
# A pool row has three content modes; a view dispatches per mode:
#   {"files": [...]}                       concrete
#   {"preset": "name"}                     live-linked to an audio preset
#   {"igroup": {"name": "g", "level": 2}}  hooked to an intensity level
#
# The views are the single home for the shared file-container rules: dedup on
# add, folder-ref expansion on remove, detach-on-edit, and the igroup
# read-only guard.  They are ephemeral -- each op re-resolves its locator to
# the live dict, and a view is valid for one operation: a remove that prunes
# can pop the pool row (and even the entry) out from under the view, so never
# call _pool_dict() or a second mutator on the same view after a mutating op.
# Igroups stay in CueIntensityManager; they are not views (see the design
# spec's D1/D2).

from cue_lib.util import _cue_remove_ref

MYPY = False
if MYPY:
    from typing import Any, Optional  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import PoolDict  # pyright: ignore[reportUnusedImport]


class _ConcreteOps(object):
    """File-list ops for a concrete pool: dedup add, folder-expand remove,
    plain clear."""

    def add_file(self, pool, d, path):
        # type: (Any, Optional[PoolDict], str) -> bool
        if d is None:
            d = pool._ensure()
            if d is None:
                return False
        files = d.setdefault("files", [])
        if path not in files:
            files.append(path)
        pool._save()
        return True

    def remove_file(self, pool, d, path):
        # type: (Any, Optional[PoolDict], str) -> bool
        if d is None:
            return False
        files = d.get("files", [])
        _, removed = _cue_remove_ref(files, path)
        if not removed:
            return False
        if pool._prunes and not files:
            pool._prune()
        pool._save()
        return True

    def clear_files(self, pool, d):
        # type: (Any, Optional[PoolDict]) -> bool
        if d is None:
            return False
        if not d.get("files", []):
            return False
        d["files"] = []
        pool._save()
        return True


class _PresetOps(object):
    """Preset-linked pools: any file edit materializes the preset first, then
    the concrete op runs on the freshly re-fetched dict."""

    def add_file(self, pool, d, path):
        # type: (Any, Optional[PoolDict], str) -> bool
        pool.detach()
        # Detach never prunes, so re-fetching here is safe -- the only
        # post-mutation _pool_dict() call the one-view-per-op rule allows.
        return _CONCRETE.add_file(pool, pool._pool_dict(), path)

    def remove_file(self, pool, d, path):
        # type: (Any, Optional[PoolDict], str) -> bool
        pool.detach()
        return _CONCRETE.remove_file(pool, pool._pool_dict(), path)

    def clear_files(self, pool, d):
        # type: (Any, Optional[PoolDict]) -> bool
        pool.detach()
        return _CONCRETE.clear_files(pool, pool._pool_dict())


class _IgroupOps(object):
    """Intensity-hooked pools own no refs: file edits refuse (bool False);
    clear drops the hook back to a plain pool."""

    def add_file(self, pool, d, path):
        # type: (Any, Optional[PoolDict], str) -> bool
        return False

    def remove_file(self, pool, d, path):
        # type: (Any, Optional[PoolDict], str) -> bool
        return False

    def clear_files(self, pool, d):
        # type: (Any, Optional[PoolDict]) -> bool
        if d is None:
            return False
        d.pop("igroup", None)
        d["files"] = []
        pool._save()
        return True


_CONCRETE = _ConcreteOps()
_PRESET = _PresetOps()
_IGROUP = _IgroupOps()

# Order documents mode priority when a row carries more than one key.
_MODE_TABLE = (("preset", _PRESET), ("igroup", _IGROUP))


def _ops_for(pool_dict):
    # type: (Optional[PoolDict]) -> Any
    """Pick the op set for a pool row by its content mode (concrete default)."""
    if pool_dict is None:
        return _CONCRETE
    return next((ops for key, ops in _MODE_TABLE if key in pool_dict), _CONCRETE)


class _CueFileContainer(object):
    """Ephemeral view over one file container row.  Public mutators are
    branch-free dispatch into the mode's ops; each op re-resolves the row."""

    # Whether remove_file drops the row when it empties.  Entry pools prune
    # (one-shot lifecycle); presets can be empty and never prune.
    _prunes = False

    def _pool_dict(self):
        # type: () -> Optional[PoolDict]
        raise NotImplementedError("_pool_dict must be overridden")

    def add_file(self, path):
        # type: (str) -> bool
        d = self._pool_dict()
        return _ops_for(d).add_file(self, d, path)

    def remove_file(self, path):
        # type: (str) -> bool
        d = self._pool_dict()
        return _ops_for(d).remove_file(self, d, path)

    def clear_files(self):
        # type: () -> bool
        d = self._pool_dict()
        return _ops_for(d).clear_files(self, d)

    def detach(self):
        # type: () -> bool
        """Materialize a linked row to a concrete one.  No-op on containers
        that are never linked."""
        return False


class CuePool(_CueFileContainer):
    """Ephemeral view over _data[key]["pools"][i].  Locates the pool row by
    (marker_key, pool_index) and re-resolves it each call."""

    _prunes = True

    def __init__(self, store, marker_key, pool_index):
        # type: (Any, str, int) -> None
        self._store = store
        self._marker_key = marker_key
        self._pool_index = pool_index

    def _pool_dict(self):
        # type: () -> Optional[PoolDict]
        entry = self._store._data.get(self._marker_key)
        if entry is None:
            return None
        pools = entry.get("pools")
        if not pools or not (0 <= self._pool_index < len(pools)):
            return None
        return pools[self._pool_index]

    def detach(self):
        # type: () -> bool
        return self._store._detach_pool(self._marker_key, self._pool_index)

    def _ensure(self):
        # type: () -> PoolDict
        """Get-or-create the pool row (entry + pool)."""
        return self._store._ensure_pool(self._marker_key, self._pool_index)

    def _prune(self):
        # type: () -> None
        """Drop the pool row, then the entry when it empties (one-shot
        image/dialogue lifecycle)."""
        entry = self._store._data.get(self._marker_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if not pools or not (0 <= self._pool_index < len(pools)):
            return
        pools.pop(self._pool_index)
        if not pools:
            del self._store._data[self._marker_key]

    def _save(self):
        # type: () -> None
        self._store._db_save_marker(self._marker_key)


class CueAudioPreset(_CueFileContainer):
    """Ephemeral view over _presets[name].  A saved preset can be empty, so
    nothing is pruned on remove."""

    def __init__(self, store, name):
        # type: (Any, str) -> None
        self._store = store
        self._name = name

    def _pool_dict(self):
        # type: () -> Optional[PoolDict]
        return self._store._presets.get(self._name)

    def _ensure(self):
        # type: () -> None
        return None

    def _save(self):
        # type: () -> None
        self._store._db_save_preset(self._name)


class CueVideoPresetPool(_CueFileContainer):
    """Ephemeral view over _video_presets[name]["pools"][i].  Video preset
    pools keep their time slot, so remove empties the files list without
    pruning the row."""

    def __init__(self, store, name, pool_index):
        # type: (Any, str, int) -> None
        self._store = store
        self._name = name
        self._pool_index = pool_index

    def _pool_dict(self):
        # type: () -> Optional[PoolDict]
        preset = self._store._video_presets.get(self._name)
        if preset is None:
            return None
        pools = preset.get("pools")
        if not pools or not (0 <= self._pool_index < len(pools)):
            return None
        return pools[self._pool_index]

    def _ensure(self):
        # type: () -> None
        return None

    def _save(self):
        # type: () -> None
        self._store._db_save_video_preset(self._name)
