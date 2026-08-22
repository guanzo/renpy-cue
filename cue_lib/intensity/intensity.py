# -*- coding: utf-8 -*-
# cue_lib/intensity/intensity.py -- intensity group registry (slice 0).
#
# An intensity group (igroup) is a named, ordered folder list.  Folder order =
# level order: the first folder is Level 1 (softest), the last is Level N
# (hardest).  Each level carries a volume multiplier and a frequency
# multiplier, defaulting to a linear ramp (Level 1 = 1.0 -> Level N = max
# within the clamps).  Level editing is slice 0; multiplier editing lands with
# the per-video inspector.
#
# Igroups are shared presets -- one JSON per igroup under data/presets/
# intensity/ via the db's preset store (save/delete/atomic write/_key
# injection).  The manager keeps an in-memory registry mirroring
# CueMarkerStore._presets and writes through to the db, which also writes the
# disk file.

from cue_lib.constants import (
    CUE_INTENSITY_FREQ_MAX,
    CUE_INTENSITY_PRESET_TYPE,
    CUE_INTENSITY_VOLUME_MAX,
)
from cue_lib.intensity.banding import _cue_band_speeds, _cue_resolve_level
from cue_lib.util import _cue_resolve_files

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import MarkerEntry  # pyright: ignore[reportUnusedImport]
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
    never lowers the pool's volume.  resolve_intensity bakes the clamp into the
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

    Carries the active level, its folder, the resolved folder files (empty =
    silence), and the volume/frequency multipliers applied at fire time."""

    def __init__(self, group, level, folder, volume_mult, freq_mult, files=None):
        # type: (str, int, Optional[str], float, float, Optional[List[str]]) -> None
        self.group = group
        self.level = level
        self.folder = folder
        self.volume_mult = volume_mult
        self.freq_mult = freq_mult
        self.files = files if files is not None else []


class CueIntensityManager(object):
    """Registry + persistence for intensity groups.

    Create/rename/delete igroups and add/remove/reorder their folders.  Reads
    go through an in-memory registry (write-invalidated, mirroring the marker
    store's preset cache); every write also lands one JSON file on disk under
    data/presets/intensity/ so the files are the durable source of truth."""

    def __init__(self, db):
        # type: (CueDatabase) -> None
        self._db = db
        self._igroups = None  # type: Optional[Dict[str, Any]]
        self._folder_index_cache = None  # type: Optional[Dict[str, Any]]
        self._band_cache = {}  # type: Dict[Any, Any]

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _load(self):
        # type: () -> Dict[str, Any]
        """The registry, loaded from the db's preset store on first use."""
        if self._igroups is None:
            self._igroups = self._db.load_intensity_presets()
        return self._igroups

    def _invalidate(self):
        # type: () -> None
        self._igroups = None
        self._folder_index_cache = None
        self._band_cache = {}

    def list_igroups(self):
        # type: () -> List[str]
        """Sorted igroup names."""
        return sorted(self._load().keys())

    def get_igroup(self, name):
        # type: (str) -> Optional[Dict[str, Any]]
        """Stored igroup dict (includes the db's _key field), or None."""
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
        data = {
            "folders": [],
            "volume_multipliers": [],
            "frequency_multipliers": [],
        }
        self._save(name, data)
        return None

    def rename_igroup(self, old_name, new_name):
        # type: (str, str) -> Optional[str]
        new_name = new_name.strip()
        if not new_name:
            return "Intensity group name can't be empty."
        if new_name == old_name:
            return None
        if self.get_igroup(new_name) is not None:
            return "An intensity group named '{}' already exists.".format(new_name)
        data = self.get_igroup(old_name)
        if data is None:
            return "No intensity group named '{}'.".format(old_name)
        self._save(new_name, data)
        self._db.delete_preset(CUE_INTENSITY_PRESET_TYPE, old_name)
        self._invalidate()
        return None

    def delete_igroup(self, name):
        # type: (str) -> None
        self._db.delete_preset(CUE_INTENSITY_PRESET_TYPE, name)
        self._invalidate()

    # ------------------------------------------------------------------
    # Level editing -- the folder list IS the level list
    # ------------------------------------------------------------------

    def add_folder(self, name, folder_path):
        # type: (str, str) -> Optional[str]
        """Append a folder as the igroup's next (highest) level.

        Returns an error string, or None on success."""
        data = self.get_igroup(name)
        if data is None:
            return "No intensity group named '{}'.".format(name)
        folders = list(data.get("folders", []))
        if folder_path in folders:
            return "'{}' is already a level in this intensity group.".format(folder_path)
        folders.append(folder_path)
        self._save_with_ramp(name, folders)
        return None

    def remove_level(self, name, index):
        # type: (str, int) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        folders = list(data.get("folders", []))
        if 0 <= index < len(folders):
            del folders[index]
            self._save_with_ramp(name, folders)

    def move_level(self, name, index, delta):
        # type: (str, int, int) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        folders = list(data.get("folders", []))
        new_index = index + delta
        if 0 <= index < len(folders) and 0 <= new_index < len(folders):
            folders[index], folders[new_index] = folders[new_index], folders[index]
            self._save_with_ramp(name, folders)

    # ------------------------------------------------------------------
    # Resolution -- hook detection + speed -> level chain (slice 3)
    # ------------------------------------------------------------------

    def _folder_index(self):
        # type: () -> Dict[str, Any]
        """Folder -> (igroup_name, level_index) registry, built lazily and
        write-invalidated.  Folder order = level order, so the position in the
        folders list is the level index (0-based).  A folder registered in
        several igroups resolves to the first group alphabetically."""
        if self._folder_index_cache is None:
            index = {}
            for name in self.list_igroups():
                data = self.get_igroup(name)
                if data is None:
                    continue
                folders = data.get("folders", [])
                for li, folder in enumerate(folders):
                    if folder not in index:
                        index[folder] = (name, li)
            self._folder_index_cache = index
        return self._folder_index_cache

    def resolve_hook(self, files):
        # type: (Optional[List[str]]) -> Optional[Tuple[str, int]]
        """The first folder ref in `files` registered in some igroup, as
        (igroup_name, level_index), or None if the pool isn't hooked.

        Only trailing-slash folder refs count -- direct file entries are not
        intensity hooks."""
        for item in files or []:
            if not item.endswith("/"):
                continue
            hit = self._folder_index().get(item)
            if hit is not None:
                return hit
        return None

    def group_for_folder(self, folder):
        # type: (str) -> Optional[str]
        """The group a folder belongs to, or None when it's untagged."""
        hit = self._folder_index().get(folder)
        return hit[0] if hit is not None else None

    def pool_group(self, files):
        # type: (Optional[List[str]]) -> Optional[str]
        """The group a pool is hooked to, or None when no folder in the pool
        is registered in any group."""
        hook = self.resolve_hook(files)
        return hook[0] if hook is not None else None

    def check_add_folder(self, pool_files, folder):
        # type: (Optional[List[str]], str) -> Optional[str]
        """Error string when adding ``folder`` to a pool whose existing
        folders already hook a different group (one intensity group per pool).
        None when the add is allowed -- untagged folders, and extra folders
        of the already-hooked group (they collapse to one hook)."""
        new_group = self.group_for_folder(folder)
        if new_group is None:
            return None
        existing = self.pool_group(pool_files)
        if existing is not None and existing != new_group:
            return ("That folder belongs to Intensity Group '{}', but this pool "
                    "is already hooked to '{}'. One intensity group per pool."
                    ).format(new_group, existing)
        return None

    def flags_from_entry(self, entry):
        # type: (Optional[MarkerEntry]) -> CueIntensityFlags
        """Per-video intensity toggles from a video marker entry.  Absent
        fields default on; a missing entry reads as fully enabled (hooked
        pools still resolve -- the toggle lives on the video marker entry)."""
        if entry is None:
            return CueIntensityFlags()
        return CueIntensityFlags(
            enabled=entry.get("intensity_enabled", True),
            sfx_levels=entry.get("intensity_sfx_levels", True),
            volume=entry.get("intensity_volume", True),
            frequency=entry.get("intensity_frequency", True))

    def level_folder(self, name, level):
        # type: (str, int) -> Optional[str]
        """The folder for a 1-based level, or None if the level is out of
        range.  No downward fallback: an empty folder means silence."""
        data = self.get_igroup(name)
        if data is None:
            return None
        folders = data.get("folders", [])
        idx = level - 1
        if not (0 <= idx < len(folders)):
            return None
        return folders[idx]

    def level_multipliers(self, name, level):
        # type: (str, int) -> Tuple[float, float]
        """(volume_mult, freq_mult) for a 1-based level.  Out-of-range levels
        clamp to the nearest valid level; missing data reads as identity."""
        data = self.get_igroup(name)
        if data is None:
            return (1.0, 1.0)
        v = data.get("volume_multipliers", [])
        f = data.get("frequency_multipliers", [])
        if not v:
            return (1.0, 1.0)
        idx = max(0, min(level - 1, len(v) - 1))
        vm = v[idx]
        fm = f[idx] if idx < len(f) else 1.0
        return (vm, fm)

    def resolve_intensity(self, files, current_speed, variants, is_populated=None, flags=None):
        # type: (Optional[List[str]], float, List[float], Optional[Callable[[str], bool]], Optional[CueIntensityFlags]) -> Optional[CueIntensityResolution]
        """Full speed -> level chain for a pool.

        Returns None when the pool isn't hooked, the video has no speed
        variants (single-speed), or intensity is toggled off for the video.
        Otherwise bands the variants into as many levels as the group has
        folders, resolves the active level for the current speed, and carries
        the level's folder + multipliers.

        ``is_populated`` is an injectable (folder) -> bool that tests use to
        stand in for the SFX library; when None, real folder resolution via
        ``_cue_resolve_files`` decides (empty folder -> no files -> silence).

        ``flags`` carries the per-video toggles; None means all on (slice 3
        behavior).  volume/frequency off zero their multipliers; sfx_levels
        off plays the pool's own listed folders instead of the level folder
        while the active level still drives volume/frequency."""
        if flags is not None and not flags.enabled:
            return None
        hook = self.resolve_hook(files)
        if hook is None or not variants:
            return None
        name, _level_idx = hook
        data = self.get_igroup(name)
        if data is None:
            return None
        n = len(data.get("folders", []))
        if n == 0:
            return None
        key = (tuple(sorted(set(variants))), n)
        if key not in self._band_cache:
            self._band_cache[key] = _cue_band_speeds(variants, n)
        speeds, levels = self._band_cache[key]
        level = _cue_resolve_level(current_speed, speeds, levels)
        folder = self.level_folder(name, level)
        vm, fm = self.level_multipliers(name, level)
        if flags is not None:
            if not flags.volume:
                vm = 1.0
            if not flags.frequency:
                fm = 1.0
        res = CueIntensityResolution(name, level, folder, _cue_intensity_volume_mult(vm), fm)
        if flags is not None and not flags.sfx_levels:
            # The hook folder plays as a plain folder -- the pool's own list.
            if is_populated is not None:
                res.files = [f for f in files or [] if is_populated(f)]
            else:
                res.files = _cue_resolve_files(files or [])
        elif folder is not None:
            if is_populated is not None:
                res.files = [folder] if is_populated(folder) else []
            else:
                res.files = _cue_resolve_files([folder])
        return res

    def video_level(self, pools_files, current_speed, variants, is_populated=None, flags=None):
        # type: (List[List[str]], float, List[float], Optional[Callable[[str], bool]], Optional[CueIntensityFlags]) -> Optional[CueIntensityResolution]
        """Resolve a video's active intensity from its first hooked pool.

        The result's volume_mult is the global volume scale applied to SFX
        that fire during the video but aren't themselves hooked to a group."""
        for files in pools_files:
            res = self.resolve_intensity(files, current_speed, variants, is_populated, flags)
            if res is not None:
                return res
        return None

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _save(self, name, data):
        # type: (str, Dict[str, Any]) -> None
        self._db.save_preset(CUE_INTENSITY_PRESET_TYPE, name, data)
        self._invalidate()

    def _save_with_ramp(self, name, folders):
        # type: (str, List[str]) -> None
        data = {
            "folders": folders,
            "volume_multipliers": _level_ramp(len(folders), CUE_INTENSITY_VOLUME_MAX),
            "frequency_multipliers": _level_ramp(len(folders), CUE_INTENSITY_FREQ_MAX),
        }
        self._save(name, data)
