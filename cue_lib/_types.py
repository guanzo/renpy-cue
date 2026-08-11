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
from typing import Dict, List, TypedDict, Union

# typing_extensions is safe here -- _types.py is never imported at runtime
# (see header comment).  Pyright understands NotRequired natively.
from typing_extensions import NotRequired


# =========================================================================
# Pool dicts -- the shape of a single pool within a MarkerEntry
# =========================================================================

class PoolDict(TypedDict, total=False):
    """A single pool within a MarkerEntry. Keys vary by context."""
    files: List[str]
    volume: float
    frequency: int              # loop pools only
    trigger_on_shake: bool      # image pools only
    exclusive: bool             # loop pools only
    preset: str                 # preset-backed pools (written, replaced on detach)


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


# =========================================================================
# Marker entry -- the top-level value in the markers dict
# =========================================================================

class MarkerEntry(TypedDict, total=False):
    """Returned by CueMarkerManager.get()."""
    pools: List[PoolDict]
    volume: float               # entry-level master volume (default 1.0)
    replay: str                 # replay label
    speed_pref: float           # per-video speed preference
    speed_sequence: List[float] # per-video speed sequence
    speed_mode: str             # "single" or "multi"
    timestamps: List[PoolDict]  # migration: old name for pools
    files: List[str]            # migration: old flat format
    frequency: int              # migration: old entry-level frequency


# =========================================================================
# Preset dicts
# =========================================================================

class VideoPreset(TypedDict):
    """A saved video preset."""
    pools: List[VideoPoolDict]
    volume: float
    source_duration: float
    speed_mode: NotRequired[str]             # migration: "single" or "multi"
    timestamps: NotRequired[List[PoolDict]]  # migration: old name for pools


# =========================================================================
# Repeater manager
# =========================================================================

class RepeaterOffset(TypedDict):
    """One offset in a CueMarkerRepeater repeat pattern."""
    offset: float
    files: List[str]
    volume: float


# =========================================================================
# Undo / clipboard / persistent
# =========================================================================

class UndoSnapshot(TypedDict):
    """Snapshot taken by CueUndoManager on every save."""
    markers: Dict[str, MarkerEntry]
    presets: Dict[str, PoolDict]
    video_presets: Dict[str, VideoPreset]


class ClipboardData(TypedDict):
    """Copy/paste clipboard for context markers."""
    markers: Dict[str, MarkerEntry]
    source_file: str
    source_dialogue: str


class CuePersistentData(TypedDict):
    """Shape of persistent._cue_config."""
    markers: Dict[str, MarkerEntry]
    presets: Dict[str, PoolDict]
    video_presets: Dict[str, VideoPreset]
    disabled_files: List[str]
    triggers_active: bool
    encode_mode: int
    seamless_transition: bool


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
    """Folder node in _cue.audio_tree / visible_tree."""
    type: str
    name: str
    full_path: str
    depth: int
    expanded: bool
    has_files: bool


class AudioTreeFileNode(TypedDict):
    """File node in _cue.audio_tree / visible_tree."""
    type: str
    name: str
    full_path: str
    depth: int
    index: int
    enabled: bool


# Type alias for union of node types
AudioTreeNode = Union[AudioTreeFolderNode, AudioTreeFileNode]
