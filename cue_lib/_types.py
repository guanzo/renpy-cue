# -*- coding: utf-8 -*-
# cue_lib/_types.py
# This file is NEVER imported at runtime under Python 2 (see MYPY guard
# pattern in consuming files). It exists purely so a type checker has a
# real, resolvable module to import TypedDict names from -- both for .pyi
# stub authoring and for in-source `# type:` comments. Because it's never
# executed at runtime, it is free to use TypedDict/modern syntax with no
# Python 2.7 constraint.
#
# This is the SINGLE canonical source for all TypedDict definitions used
# across cue_lib. .pyi stubs import from here rather than redeclaring.

from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple, TypedDict, Union

# typing_extensions is safe here -- _types.py is never imported at runtime
# (see header comment).  Pyright understands NotRequired natively.
from typing_extensions import NotRequired


# =========================================================================
# Pool dicts -- the shape of a single pool within a MarkerEntry
# =========================================================================


class ExclusiveDict(TypedDict, total=False):
    """Nested exclusive config on a pool. Absence of the ``exclusive``
    key on a pool means plain-citizen (Off / Play / no hold)."""

    group: int  # 1..N shared group; absent = 0 (Off)
    start: int  # CueExclusiveStart: 0=play, 1=fade, 2=wait
    hold: bool  # block non-group SFX until done


class PoolDict(TypedDict, total=False):
    """A single pool within a MarkerEntry. Keys vary by context."""

    files: List[str]
    volume: float
    time: float  # video pools only
    frequency: int  # loop pools only
    trigger_on_shake: bool  # image pools only
    exclusive: ExclusiveDict  # nested exclusive config; legacy saves held a bool
    igroup: str  # intensity group name (hook)
    ilevel_id: int  # stable id of the pinned level (fallback content)
    preset: str  # preset-backed pools (written, replaced on detach)


class LevelDict(TypedDict, total=False):
    """One intensity-group level: a pool of folders/files, plus a stable id.

    ``id`` is a monotonic per-group identity that survives reorder/insert.
    ``files`` are folder refs (trailing ``/``) and direct file entries, the
    same shape as a marker pool's ``files``."""

    id: int
    files: List[str]


class VideoPoolDict(TypedDict):
    """A video marker pool.

    ``time`` is always required -- every video pool has a timestamp.
    ``files`` and ``volume`` are optional: preset-backed pools
    (``{"time": t, "preset": name}``) delegate them to the preset.
    ``preset`` is absent in resolved pools."""

    time: float
    files: NotRequired[List[str]]
    volume: NotRequired[float]
    preset: NotRequired[str]
    igroup: NotRequired[str]
    ilevel_id: NotRequired[int]


# =========================================================================
# Marker entry -- the top-level value in the markers dict
# =========================================================================


class AutoSpeedDict(TypedDict, total=False):
    """Nested per-video auto-speed selection (preset + shuffle toggle)."""

    active_preset: str
    is_shuffle_mode: bool


class IntensityDict(TypedDict, total=False):
    """Nested per-video intensity toggles; absent keys read as on."""

    enabled: bool
    sfx_levels: bool
    volume: bool
    frequency: bool


class MarkerEntry(TypedDict, total=False):
    """Returned by CueMarkerManager.get()."""

    pools: List[PoolDict]
    volume: float  # entry-level master volume (default 1.0)
    video_file_muted: bool  # video audio track muted
    replay: str  # replay label
    single_speed_pref: float  # per-video single-mode speed preference
    multi_speed_sequence: List[float]  # per-video custom multi-mode sequence
    speed_mode: str  # "single", "multi", or "auto"
    disabled_auto_speeds: List[float]  # speeds toggled off in auto-speed
    auto_speed: AutoSpeedDict  # nested auto-speed preset + shuffle selection
    intensity: IntensityDict  # nested intensity toggles
    music: List[str]  # user-added songs only; default lives in the trigger log.
    # My Music files are stored relative to the My Music dir;
    # game-music files are stored game-relative.
    music_default_disabled: bool  # recorded default music for this scene is toggled off
    timestamps: List[PoolDict]  # migration: old name for pools
    files: List[str]  # migration: old flat format
    frequency: int  # migration: old entry-level frequency


# =========================================================================
# Default music trigger log
# =========================================================================


class DefaultMusicTrigger(TypedDict):
    """One recorded default-music trigger: the scene key anchoring the
    replay's `play music` statement and the files it scripted.

    ``key_before`` is the scene visible at the play call (the deterministic
    anchor); ``key_after`` is the settled scene, captured once the scene
    batch lands (absent until then).  Either can match a scene key.

    ``filepaths`` holds the full scripted list -- a `play music [a, b]`
    cycle keeps both files, so a default override can reproduce the cycle."""

    key_before: str
    filepaths: List[str]
    key_after: NotRequired[str]


# =========================================================================
# Preset dicts
# =========================================================================


class VideoPreset(TypedDict):
    """A saved video preset."""

    pools: List[VideoPoolDict]
    volume: float
    source_duration: float
    speed_mode: NotRequired[str]  # migration: "single" or "multi"
    timestamps: NotRequired[List[PoolDict]]  # migration: old name for pools


# =========================================================================
# Repeater manager
# =========================================================================


class RepeaterOffset(TypedDict):
    """One offset in a CueMarkerRepeater repeat pattern."""

    offset: float
    files: List[str]
    volume: float
    igroup: Optional[str]
    ilevel_id: Optional[int]


# =========================================================================
# Undo / clipboard / persistent
# =========================================================================


class UndoSnapshot(TypedDict):
    """Snapshot taken by CueUndoManager on every save."""

    markers: Dict[str, MarkerEntry]
    presets: Dict[str, PoolDict]
    video_presets: Dict[str, VideoPreset]
    session_created: Set[Tuple[str, str]]  # ("audio"|"video", name) created this session


class ClipboardData(TypedDict):
    """Copy/paste clipboard for context markers."""

    markers: Dict[str, MarkerEntry]
    source_file: str
    source_dialogue: str


class CuePersistentData(TypedDict):
    """Shape of the backup/restore config dict (cue_config.json)."""

    markers: Dict[str, MarkerEntry]
    presets: Dict[str, PoolDict]
    video_presets: Dict[str, VideoPreset]
    disabled_files: List[str]
    music_folders: List[str]
    sfx_folders: List[str]
    triggers_active: bool
    encode_mode: int
    remove_audio: bool
    seamless_transition: bool
    auto_backups: bool


# =========================================================================
# Auto-speed generator
# =========================================================================


class AutoSpeedKnobs(TypedDict):
    """Four-knob tuning dict for CueAutoSpeedGenerator presets and custom."""

    drift: float
    intensity: float
    volatility: float
    center: float


# =========================================================================
# Audio tree nodes
# =========================================================================


class AudioTreeFolderNode(TypedDict):
    """Folder node in _cue.sfx.library.tree / visible_tree."""

    type: str
    name: str
    full_path: str
    depth: int
    expanded: bool
    has_files: bool


class AudioTreeFileNode(TypedDict):
    """File node in _cue.sfx.library.tree / visible_tree."""

    type: str
    name: str
    full_path: str
    depth: int
    index: int
    enabled: bool


# Type alias for union of node types
AudioTreeNode = Union[AudioTreeFolderNode, AudioTreeFileNode]
