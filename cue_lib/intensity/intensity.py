# -*- coding: utf-8 -*-
# cue_lib/intensity/intensity.py -- intensity group registry.
#
# An intensity group (igroup) is a named, ordered level list.  Each level is a
# pool of folder/file refs with a stable id; level order = 1..N (1 = softest,
# N = hardest).  Volume and frequency multipliers derive from a linear ramp
# over the level count (Level 1 = 1.0 -> Level N = max within the clamps).
# A pool hooks an igroup by storing the group name + the pinned level id;
# speed banding then picks the active level per frame.
#
# Igroups are shared presets -- one JSON per igroup under data/presets/
# intensity/ via the db's preset store (save/delete/atomic write/_key
# injection).  The manager keeps an in-memory registry mirroring
# CueMarkerStore._presets and writes through to the db, which also writes the
# disk file.

from cue_lib.constants import CUE_INTENSITY_FREQ_MAX, CUE_INTENSITY_PRESET_TYPE, CUE_INTENSITY_VOLUME_MAX
from cue_lib.intensity.banding import _cue_band_speeds, _cue_resolve_level
from cue_lib.util import _cue_resolve_files

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import IgroupDict, IgroupHookDict, LevelDict, MarkerEntry  # pyright: ignore[reportUnusedImport]
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]


def _level_ramp(count, max_value):
    # type: (int, float) -> List[float]
    """Linear ramp of `count` multipliers from 1.0 at level 1 to `max_value`
    at level N.  A single level stays at 1.0 (no scaling)."""
    if count <= 1:
        return [1.0]
    step = (max_value - 1.0) / (count - 1)
    return [round(1.0 + i * step, 4) for i in range(count)]


def _cue_intensity_volume_mult(level_mult):
    # type: (float) -> float
    """Clamp a level multiplier to [1.0, CUE_INTENSITY_VOLUME_MAX] so intensity
    never lowers the pool's volume.  resolve_pool_intensity bakes the clamp into the
    resolution's volume_mult; the fire path composes it with the pool volume in
    play_pool."""
    return min(CUE_INTENSITY_VOLUME_MAX, max(1.0, level_mult))


class CueIntensityFlags(object):
    """Per-video intensity toggles.

    All default on -- a video that stores none of them behaves exactly as
    before.  ``enabled`` is the master switch; the three sub-toggles scale
    its effect independently."""

    def __init__(self, enabled=True, sfx_levels=True, volume=True, frequency=True):
        # type: (bool, bool, bool, bool) -> None
        self.enabled = enabled
        self.sfx_levels = sfx_levels
        self.volume = volume
        self.frequency = frequency


class CueIntensityResolution(object):
    """Result of resolving a pool against an intensity group.

    Carries the active level, the resolved level files (empty = silence), and
    the volume/frequency multipliers applied at fire time."""

    def __init__(self, group, level, volume_mult, freq_mult, files=None):
        # type: (str, int, float, float, Optional[List[str]]) -> None
        self.group = group
        self.level = level
        self.volume_mult = volume_mult
        self.freq_mult = freq_mult
        self.files = files if files is not None else []


class CueIntensityManager(object):
    """Registry + persistence for intensity groups.

    Create/rename/delete igroups and add/remove/reorder their levels.  Reads
    go through an in-memory registry (write-invalidated, mirroring the marker
    store's preset cache); every write also lands one JSON file on disk under
    data/presets/intensity/ so the files are the durable source of truth."""

    def __init__(self, db):
        # type: (CueDatabase) -> None
        self._db = db
        self._igroups = None  # type: Optional[Dict[str, IgroupDict]]
        self._band_cache = {}  # type: Dict[Any, Any]

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _load(self):
        # type: () -> Dict[str, IgroupDict]
        """The registry, loaded from the db's preset store on first use.

        One-time migration from the legacy ``folders`` shape: a folder list
        becomes the level list (sequential ids, one folder per level) and the
        two multiplier arrays are dropped (the ramp is now derived).  The
        back-write persists the migrated shape so the migration doesn't rerun."""
        if self._igroups is None:
            loaded = self._db.load_intensity_presets()
            for name, data in loaded.items():
                if "levels" not in data and "folders" in data:
                    folders = data.get("folders", [])
                    data["levels"] = [{"id": i + 1, "files": [f]} for i, f in enumerate(folders)]
                    data["next_ilevel_id"] = len(folders) + 1
                    data.pop("folders", None)
                    data.pop("volume_multipliers", None)
                    data.pop("frequency_multipliers", None)
                    self._db.save_preset(CUE_INTENSITY_PRESET_TYPE, name, data)
            self._igroups = loaded
        return self._igroups

    def _invalidate(self):
        # type: () -> None
        self._igroups = None
        self._band_cache = {}

    def list_igroups(self):
        # type: () -> List[str]
        """Sorted igroup names."""
        return sorted(self._load().keys())

    def get_igroup(self, name):
        # type: (str) -> Optional[IgroupDict]
        """Stored igroup definition (includes the db's _key field), or None."""
        return self._load().get(name)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_igroup(self, name):
        # type: (str) -> Optional[str]
        """Create an empty igroup.  Returns an error string, or None."""
        name = name.strip()
        if not name:
            return "Intensity group name can't be empty."
        if self.get_igroup(name) is not None:
            return "An intensity group named '{}' already exists.".format(name)
        data = {"levels": [], "next_ilevel_id": 1}  # type: IgroupDict
        self._save(name, data)
        return None

    def delete_igroup(self, name):
        # type: (str) -> None
        self._db.delete_preset(CUE_INTENSITY_PRESET_TYPE, name)
        self._invalidate()

    # ------------------------------------------------------------------
    # Level editing -- the level list IS the pool list
    # ------------------------------------------------------------------

    def _new_ilevel_id(self, data):
        # type: (IgroupDict) -> int
        next_id = data.get("next_ilevel_id", 1)
        data["next_ilevel_id"] = next_id + 1
        return next_id

    def add_level(self, name):
        # type: (str) -> Optional[int]
        data = self.get_igroup(name)
        if data is None:
            return None
        levels = list(data.get("levels", []))
        new_id = self._new_ilevel_id(data)
        levels.append({"id": new_id, "files": []})
        data["levels"] = levels
        self._save(name, data)
        return new_id

    def _find_level(self, data, ilevel_id):
        # type: (IgroupDict, int) -> Optional[LevelDict]
        for level in data.get("levels", []):
            if level.get("id") == ilevel_id:
                return level
        return None

    def add_level_file(self, name, ilevel_id, file_ref):
        # type: (str, int, str) -> Optional[str]
        data = self.get_igroup(name)
        if data is None:
            return "No intensity group named '{}'.".format(name)
        level = self._find_level(data, ilevel_id)
        if level is None:
            return "No level '{}' in '{}'.".format(ilevel_id, name)
        files = level.setdefault("files", [])
        if file_ref in files:
            return "'{}' is already in this level.".format(file_ref)
        files.append(file_ref)
        self._save(name, data)
        return None

    def remove_level_file(self, name, ilevel_id, file_ref):
        # type: (str, int, str) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        level = self._find_level(data, ilevel_id)
        if level is None:
            return
        files = level.get("files", [])
        if file_ref in files:
            files.remove(file_ref)
            self._save(name, data)

    def remove_level(self, name, index):
        # type: (str, int) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        levels = list(data.get("levels", []))
        if 0 <= index < len(levels):
            del levels[index]
            data["levels"] = levels
            self._save(name, data)

    def move_level(self, name, index, delta):
        # type: (str, int, int) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        levels = list(data.get("levels", []))
        new_index = index + delta
        if 0 <= index < len(levels) and 0 <= new_index < len(levels):
            levels[index], levels[new_index] = levels[new_index], levels[index]
            data["levels"] = levels
            self._save(name, data)

    def level_files(self, name, level_index):
        # type: (str, int) -> Optional[List[str]]
        data = self.get_igroup(name)
        if data is None:
            return None
        levels = data.get("levels", [])
        idx = level_index - 1
        if not (0 <= idx < len(levels)):
            return None
        return levels[idx].get("files", [])

    def level_files_by_id(self, name, ilevel_id):
        # type: (str, int) -> Optional[List[str]]
        data = self.get_igroup(name)
        if data is None:
            return None
        levels = data.get("levels", [])
        level = self._find_level(data, ilevel_id)
        if level is not None:
            return level.get("files", [])
        if levels:
            return levels[0].get("files", [])
        return None

    def level_multipliers(self, name, level_index):
        # type: (str, int) -> Tuple[float, float]
        data = self.get_igroup(name)
        if data is None:
            return (1.0, 1.0)
        count = len(data.get("levels", []))
        if count == 0:
            return (1.0, 1.0)
        idx = max(0, min(level_index - 1, count - 1))
        vm = _level_ramp(count, CUE_INTENSITY_VOLUME_MAX)[idx]
        fm = _level_ramp(count, CUE_INTENSITY_FREQ_MAX)[idx]
        return (vm, fm)

    # ------------------------------------------------------------------
    # Resolution -- speed -> level chain (slice 3)
    # ------------------------------------------------------------------

    def flags_from_entry(self, entry):
        # type: (Optional[MarkerEntry]) -> CueIntensityFlags
        """Per-video intensity toggles from a video marker entry.  Absent
        fields default on; a missing entry reads as fully enabled (hooked
        pools still resolve -- the toggle lives on the video marker entry)."""
        if entry is None:
            return CueIntensityFlags()
        flags = entry.get("intensity", {})
        return CueIntensityFlags(
            enabled=flags.get("enabled", True),
            sfx_levels=flags.get("sfx_levels", True),
            volume=flags.get("volume", True),
            frequency=flags.get("frequency", True),
        )

    def resolve_pool_intensity(self, igroup, ilevel_id, current_speed, variants, flags=None, resolve_files=None):
        # type: (Optional[str], Optional[int], float, Optional[List[float]], Optional[CueIntensityFlags], Optional[Callable[[List[str]], List[str]]]) -> Optional[CueIntensityResolution]
        if igroup is None:
            return None
        data = self.get_igroup(igroup)
        if data is None:
            return None
        levels = data.get("levels", [])
        if not levels:
            return None
        if resolve_files is None:
            resolve_files = _cue_resolve_files
        count = len(levels)
        can_band = (flags is None or flags.enabled) and bool(variants)
        swap = can_band and (flags is None or flags.sfx_levels)
        if can_band and variants is not None:
            key = (tuple(sorted(set(variants))), count)
            if key not in self._band_cache:
                self._band_cache[key] = _cue_band_speeds(variants, count)
            speeds, band_levels = self._band_cache[key]
            level = _cue_resolve_level(current_speed, speeds, band_levels)
        else:
            level = 1
        if swap:
            files = self.level_files(igroup, level)
        else:
            files = self.level_files_by_id(igroup, ilevel_id or 0)
        if files is None:
            files = []
        vm, fm = self.level_multipliers(igroup, level)
        if flags is not None:
            if not flags.enabled:
                vm, fm = 1.0, 1.0
            else:
                if not flags.volume:
                    vm = 1.0
                if not flags.frequency:
                    fm = 1.0
        return CueIntensityResolution(igroup, level, _cue_intensity_volume_mult(vm), fm, resolve_files(files))

    def resolve_video_intensity(self, pool_hooks, current_speed, variants, flags=None, resolve_files=None):
        # type: (List[Optional[IgroupHookDict]], float, Optional[List[float]], Optional[CueIntensityFlags], Optional[Callable[[List[str]], List[str]]]) -> Optional[CueIntensityResolution]
        for hook in pool_hooks:
            igroup = hook.get("name") if hook else None
            ilevel_id = hook.get("level") if hook else None
            res = self.resolve_pool_intensity(igroup, ilevel_id, current_speed, variants, flags, resolve_files)
            if res is not None:
                return res
        return None

    def current_level(self, pool_hooks, current_speed, variants, flags=None):
        # type: (List[Optional[IgroupHookDict]], float, Optional[List[float]], Optional[CueIntensityFlags]) -> Optional[Tuple[int, int]]
        if flags is not None and not flags.enabled:
            return None
        if not variants:
            return None
        for hook in pool_hooks:
            igroup = hook.get("name") if hook else None
            if not igroup:
                continue
            data = self.get_igroup(igroup)
            if data is None:
                continue
            count = len(data.get("levels", []))
            if count == 0:
                continue
            key = (tuple(sorted(set(variants))), count)
            if key not in self._band_cache:
                self._band_cache[key] = _cue_band_speeds(variants, count)
            speeds, band_levels = self._band_cache[key]
            level = _cue_resolve_level(current_speed, speeds, band_levels)
            return (level, count)
        return None

    def video_hook(self, pool_hooks):
        # type: (List[Optional[IgroupHookDict]]) -> Optional[str]
        for hook in pool_hooks:
            if hook:
                return hook.get("name")
        return None

    def is_pool_intensity_active(self, igroup, variants, flags=None):
        # type: (Optional[IgroupHookDict], Optional[List[float]], Optional[CueIntensityFlags]) -> bool
        if flags is not None and not flags.enabled:
            return False
        if not variants or len(variants) < 2:
            return False
        return bool(igroup)

    def variant_levels(self, group_name, variants):
        # type: (str, List[float]) -> Optional[List[Tuple[float, int]]]
        if not variants:
            return None
        data = self.get_igroup(group_name)
        if data is None:
            return None
        level_count = len(data.get("levels", []))
        if level_count < 2:
            return None
        speeds, levels = _cue_band_speeds(list(variants), level_count)
        return list(zip(speeds, levels))

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _save(self, name, data):
        # type: (str, IgroupDict) -> None
        self._db.save_preset(CUE_INTENSITY_PRESET_TYPE, name, data)
        self._invalidate()
