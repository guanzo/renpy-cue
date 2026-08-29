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
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, TypedDict, Union

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


class IgroupHookDict(TypedDict, total=False):
    """Nested intensity-group hook on a pool: the group name plus the
    pinned level id (fallback content when intensity folding is off)."""

    name: str
    level: int


class PoolDict(TypedDict, total=False):
    """A single pool within a MarkerEntry. Keys vary by context."""

    files: List[str]
    volume: float
    time: float  # video pools only
    frequency: int  # loop pools only
    trigger_on_shake: bool  # image pools only
    exclusive: ExclusiveDict  # nested exclusive config; legacy saves held a bool
    igroup: IgroupHookDict  # nested intensity-group hook
    preset: str  # preset-backed pools (written, replaced on detach)


class LevelDict(TypedDict, total=False):
    """One intensity-group level: a pool of folders/files, plus a stable id.

    ``id`` is a monotonic per-group identity that survives reorder/insert.
    ``files`` are folder refs (trailing ``/``) and direct file entries, the
    same shape as a marker pool's ``files``."""

    id: int
    files: List[str]


class IgroupDict(TypedDict, total=False):
    """One intensity group definition: an ordered level list plus the
    monotonic level-id counter.  The registry value keyed by group name."""

    levels: List[LevelDict]
    next_ilevel_id: int


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
    igroup: NotRequired[IgroupHookDict]


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
    filepath: str  # on-screen file's original path, captured at marker creation
    speaker: str  # dialogue marker: who said the line (the character tag, "mc" for the MC)
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
    igroup: Optional[IgroupHookDict]


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


class AudioSourceConfig(TypedDict):
    """One declared built-in source in a tree's CUE_BUILTIN_SOURCES.

    key owns the {key}_files / {key}_tree / {key}_scan_error per-source attrs;
    discover is the method NAME (string) filling a set with stored-form paths;
    display_root is the synthetic folder the source's tree wraps under;
    scan_label is the human label for scan-failure messages."""

    key: str
    discover: str
    display_root: str
    scan_label: str


# Type alias for union of node types
AudioTreeNode = Union[AudioTreeFolderNode, AudioTreeFileNode]


# =========================================================================
# Tree row dicts -- the cue_tree_rows renderer contract
# =========================================================================


class TreeButtonDict(TypedDict):
    """One icon button in a row's ``buttons``/``hover_buttons`` list."""

    icon: str
    action: Any  # a Ren'Py action / Function()
    tt: NotRequired[str]
    enabled: NotRequired[bool]
    bg: NotRequired[Optional[str]]  # selected/hint bg; None = default


class TreeFileRowDict(TypedDict):
    """A file leaf row: indent, buttons, gap-null, then the accent label."""

    key: str
    type: Literal["file"]
    label: str
    depth: int
    buttons: List[TreeButtonDict]
    warn: str  # invalid-file reason ("" = none)
    gap: int
    size: NotRequired[int]  # label font size


class TreeHelpRowDict(TypedDict):
    """A muted help/empty-state line, indented to depth."""

    key: str
    type: Literal["help"]
    label: str
    depth: int
    color: NotRequired[str]
    v_gap: NotRequired[int]  # null height after the row
    plain: NotRequired[bool]  # drop the cue_help style


class TreeActionRowDict(TypedDict):
    """A clickable text-button row; explorer fills the open-in-explorer
    variant, otherwise the row runs action."""

    key: str
    type: Literal["action"]
    label: str
    depth: int
    action: NotRequired[Any]
    tt: NotRequired[str]
    explorer: NotRequired[str]
    icon: NotRequired[str]
    sensitive: NotRequired[bool]


class TreeActionsRowDict(TypedDict):
    """A row that lays its action buttons out horizontally (same line)."""

    key: str
    type: Literal["actions"]
    actions: List[TreeActionRowDict]
    depth: int


class TreeFolderRowDict(TypedDict):
    """A collapsible folder row."""

    key: str
    type: Literal["folder"]
    label: str
    depth: int
    buttons: List[TreeButtonDict]
    toggle: Any  # a Ren'Py action / Function()
    hover_buttons: NotRequired[List[TreeButtonDict]]
    tt: NotRequired[str]
    bar_color: NotRequired[str]


# Type alias for the flat row stream the cue_tree_rows renderer consumes
TreeRowDict = Union[TreeFileRowDict, TreeHelpRowDict, TreeActionRowDict, TreeActionsRowDict, TreeFolderRowDict]
