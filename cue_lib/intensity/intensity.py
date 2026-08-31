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
# injection).  The name->igroup dict and its CRUD live on CueIntensityPresets
# (injected as _cue.presets.intensity); this manager adds level editing and
# the speed-band resolution chain on top.

import renpy.python as _renpy_python

from cue_lib.constants import CUE_INTENSITY_FREQ_MAX, CUE_INTENSITY_VOLUME_MAX
from cue_lib.intensity.banding import _cue_band_speeds, _cue_resolve_level
from cue_lib.preset_store import CueIntensityPresets
from cue_lib.util import _cue_resolve_files

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, List, Optional, Tuple, Union  # pyright: ignore[reportUnusedImport]
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


def _cue_igroup_volume_mult(level_mult):
    # type: (float) -> float
    """Clamp a level multiplier to [1.0, CUE_INTENSITY_VOLUME_MAX] so intensity
    never lowers the pool's volume.  resolve_pool_intensity bakes the clamp into the
    resolution's volume_mult; the fire path composes it with the pool volume in
    play_pool."""
    return min(CUE_INTENSITY_VOLUME_MAX, max(1.0, level_mult))


def _cue_igroup_tooltip(group_name, is_active):
    # type: (str, bool) -> str
    """Tooltip for a pool locked to an intensity group: an active/inactive
    status line plus the locked-pool note.  Shared by the pool-files rows and
    the marker timeline."""
    status = "Active" if is_active else "Inactive"
    return ("{} Intensity Group: '{}'\nNo more files can be added to this pool.").format(
        status, group_name
    )


class CueIntensityFlags(_renpy_python.NoRollback):
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


class CueIntensityResolution(_renpy_python.NoRollback):
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


class CueIntensityManager(_renpy_python.NoRollback):
    """Behavior over the shared CueIntensityPresets collection.

    Igroups are shared presets (one JSON per igroup under data/presets/
    intensity/ via the db's preset store).  CRUD lives on
    _cue.presets.intensity; this manager adds level editing and the speed-band
    resolution chain."""

    def __init__(self, db, presets=None):
        # type: (CueDatabase, Optional[CueIntensityPresets]) -> None
        self._presets = presets if presets is not None else CueIntensityPresets(db, set())
        self._presets.load()
        self._band_cache = {}  # type: Dict[Any, Any]

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
        data = self._presets.get(name)
        if data is None:
            return None
        levels = list(data.get("levels", []))
        new_id = self._new_ilevel_id(data)
        levels.append({"id": new_id, "files": []})
        data["levels"] = levels
        self._save(name)
        return new_id

    def _find_level(self, data, ilevel_id):
        # type: (IgroupDict, int) -> Optional[LevelDict]
        for level in data.get("levels", []):
            if level.get("id") == ilevel_id:
                return level
        return None

    def add_level_file(self, name, ilevel_id, file_ref):
        # type: (str, int, str) -> Optional[str]
        data = self._presets.get(name)
        if data is None:
            return "No intensity group named '{}'.".format(name)
        level = self._find_level(data, ilevel_id)
        if level is None:
            return "No level '{}' in '{}'.".format(ilevel_id, name)
        files = level.setdefault("files", [])
        if file_ref in files:
            return "'{}' is already in this level.".format(file_ref)
        files.append(file_ref)
        self._save(name)
        return None

    def remove_level_file(self, name, ilevel_id, file_ref):
        # type: (str, int, str) -> None
        data = self._presets.get(name)
        if data is None:
            return
        level = self._find_level(data, ilevel_id)
        if level is None:
            return
        files = level.get("files", [])
        if file_ref in files:
            files.remove(file_ref)
            self._save(name)

    def remove_level(self, name, index):
        # type: (str, int) -> None
        data = self._presets.get(name)
        if data is None:
            return
        levels = list(data.get("levels", []))
        if 0 <= index < len(levels):
            del levels[index]
            data["levels"] = levels
            self._save(name)

    def move_level(self, name, index, delta):
        # type: (str, int, int) -> None
        data = self._presets.get(name)
        if data is None:
            return
        levels = list(data.get("levels", []))
        new_index = index + delta
        if 0 <= index < len(levels) and 0 <= new_index < len(levels):
            levels[index], levels[new_index] = levels[new_index], levels[index]
            data["levels"] = levels
            self._save(name)

    def level_files(self, name, level_index):
        # type: (str, int) -> Optional[List[str]]
        data = self._presets.get(name)
        if data is None:
            return None
        levels = data.get("levels", [])
        idx = level_index - 1
        if not (0 <= idx < len(levels)):
            return None
        return levels[idx].get("files", [])

    def level_files_by_id(self, name, ilevel_id):
        # type: (str, int) -> Optional[List[str]]
        data = self._presets.get(name)
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
        data = self._presets.get(name)
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
        data = self._presets.get(igroup)
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
        return CueIntensityResolution(igroup, level, _cue_igroup_volume_mult(vm), fm, resolve_files(files))

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
            data = self._presets.get(igroup)
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
        # type: (Optional[Union[str, IgroupHookDict]], Optional[List[float]], Optional[CueIntensityFlags]) -> bool
        """True when a hooked pool's intensity mode is live: the master toggle
        and SFX-by-level are on, the video has 2+ speed variants (i.e. at
        least 1 non-default variant), and the pool carries a hook."""
        if flags is not None:
            if not flags.enabled:
                return False
            if not flags.sfx_levels:
                return False
        if not variants or len(variants) < 2:
            return False
        return bool(igroup)

    def variant_levels(self, group_name, variants):
        # type: (str, List[float]) -> Optional[List[Tuple[float, int]]]
        if not variants:
            return None
        data = self._presets.get(group_name)
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

    def _save(self, name):
        # type: (str) -> None
        """Persist a level-edit (data was mutated in place) and drop the band
        cache so the new level count reshapes speed banding."""
        self._presets.save(name)
        self._band_cache = {}
