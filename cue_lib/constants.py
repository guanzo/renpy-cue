# -*- coding: utf-8 -*-
# Cross-file constants shared by multiple cue_lib modules.  The CUE_ prefix
# avoids collisions in the flat Ren'Py store.

import os


# Debug flag from the RENPY_CUE_DEBUG env var; read at import, so set it
# before the game launches.
def _cue_env_flag(name, default=False):
    # type: (str, bool) -> bool
    """Parse a boolean env var. 1/true/yes/on (case-insensitive) are true;
    unset falls back to default; any other value is false, so a stray value
    can't silently enable a feature."""
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


class CueExclusiveStart(object):
    """Exclusive 'start' behavior values (exclusive.start)."""

    PLAY = 0  # start immediately, overlapping whatever is playing
    FADE = 1  # cross-fade out non-group SFX, then play
    WAIT = 2  # wait until no non-group SFX is playing (loops only)


class CueLoopFrequency(object):
    """Loop SFX interval presets. Values match CueLoopContext.get_delay()."""

    SLOWEST = 4  # ~6.3s
    SLOW = 0  # ~3.8s
    MEDIUM = 1  # ~2.1s
    FAST = 2  # ~0.6s
    FASTEST = 3  # ~0.2s


class CuePage(object):
    """Overlay sidebar page tabs."""

    SFX = 0  # SFX editor (markers / library)
    MUSIC = 1  # Music page
    SETTINGS = 2  # Settings page
    IMPORT = 3  # Import / Export page


class CueImportCategory(object):
    """Import/export categories; each maps to a shared-root path prefix via
    _cue_import_category (the single source of that mapping).  UNKNOWN catches
    paths outside the 5 categories."""

    MARKERS = 0
    SFX = 1
    MUSIC = 2
    SPEED_VARIANTS = 3
    PRESETS = 4
    UNKNOWN = 5


class CueExportScope(object):
    """What the export button packs: whole game, or selected replays."""

    ALL_REPLAYS = 0
    SPECIFIC_REPLAYS = 1


class CueExportFileTypes(object):
    """Export file-type filter: everything, or only the checked categories."""

    ALL = 0
    SPECIFIC = 1


class CueImportMatch(object):
    """game_id match levels between an import and the current game."""

    AUTO = 0  # exact -- no user action needed
    CONFIRM = 1  # heuristic -- surface as a guess the user confirms
    MISMATCH = 2  # no match -- manual remap required


class CueContextType(object):
    """SFX library target contexts for the [+] assign button.  Values are the
    CueMarkerManager attribute names, so dispatch is getattr(manager, ctx_id)."""

    VIDEO = "video"
    IMAGE = "image"
    DIALOGUE = "dialogue"
    LOOP = "loop"


# Marker trigger key prefixes; db.py and util.py helpers key on these strings.
CUE_IMG_KEY_PREFIX = "i_"
CUE_LOOP_KEY_PREFIX = "l_"
CUE_DLG_KEY_PREFIX = "d_"
CUE_VID_KEY_PREFIX = "v_"

CUE_DEBUG = _cue_env_flag("RENPY_CUE_DEBUG", False)

# Dedicated SFX channels on the "sfx" mixer, named _cue_1.._cue_N.
# 16 gives 8 SFX + 8 simultaneous dialogue/image one-shots headroom, so an
# exclusive cut-in rarely has to steal a channel from a playing one-shot.
CUE_SFX_CHANNEL_COUNT = 16

# Default video playback speed (1.0 = original speed).
CUE_DEFAULT_VIDEO_SPEED = 1.0

# Minimum speed variants required for auto-speed presets.
CUE_AUTO_SPEED_MIN_VARIANTS = 4

# Ideal speed variants for rich auto-speed rhythm generation.
CUE_AUTO_SPEED_IDEAL_VARIANTS = 8

CUE_INTENSITY_IDEAL_LEVELS = 3
# SFX Library section header.  A constant because the toggle-SFX hotkey in
# cue_runtime_driver references the same string from a second location.
CUE_SFX_LIBRARY_HEADER = "SFX Library"

# Delete-button tooltip suffix; shared across pool-tab, preset, and import
# buttons so the shift+click escape hatch stays consistent.
CUE_HELP_SHIFT_SKIP_DELETE = "\nShift+Click to skip delete confirmation"

# Audio extensions accepted by the SFX library and My Music scans.
CUE_AUDIO_EXTS = (".ogg", ".mp3", ".wav", ".opus")

# Prefix for My Music files stored under the shared root
# ("music/Folder/song.ogg").  user_music.py adds it; music.py strips it.
CUE_MUSIC_PREFIX = "music/"

# Display-only top-level folders in the combined Music Library tree, so the
# page always shows exactly two top-level folders.
CUE_MY_MUSIC_FOLDER = "My Music/"
CUE_GAME_MUSIC_FOLDER = "Game Music/"

# Source tags for stored music refs.  Both sources can hold a "music/" folder,
# so the tag records which cache the ref came from.  Shared by music.py,
# music_tree.py, and recent.py.
CUE_MUSIC_USER_TAG = "u:"
CUE_MUSIC_GAME_TAG = "g:"

# Default pool / preset volume (1.0 = identity).  CueVolumeManager.VOL_DEFAULT
# aliases this for legacy _cue.volume.VOL_DEFAULT references.
CUE_VOLUME_DEFAULT = 1.0

# Intensity groups persist as shared presets under data/presets/, reusing the
# db preset-store machinery (save/delete/atomic write, _key injection).
CUE_INTENSITY_PRESET_TYPE = "intensity"

# Ramp ceilings for per-level intensity multipliers.  Volume stays within
# [pool level, +25%]; frequency scales delay as base_delay / multiplier.
CUE_INTENSITY_VOLUME_MAX = 1.25
CUE_INTENSITY_FREQ_MAX = 1.5

# Clamp for intensity-scaled loop delay (seconds): base_delay / level_mult
# stays in this window.
CUE_INTENSITY_DELAY_MIN = 0.2
CUE_INTENSITY_DELAY_MAX = 6.0

# Intensity-hint accent: the 2px bar drawn on intensity-hooked UI (video
# marker tabs, level folders in a hooked pool's file list).
CUE_INTENSITY_HINT_COLOR = "#ff8800"

# Tooltip note paired with the hint bar, identifying a marker as an
# intensity-hooked target.
CUE_INTENSITY_NOTE = "Intensity mode active"

# SFX Library sidebar: default width and clamp bounds (logical px, pre-zoom).
CUE_SIDEBAR_DEFAULT_WIDTH = 320
CUE_SIDEBAR_MIN_WIDTH = 270
CUE_SIDEBAR_MAX_WIDTH_RATIO = 0.3  # max width % of screen width

# persistent._cue keys for the SFX sidebar state.
CUE_PERSIST_SIDEBAR_MODE = "sfx_sidebar_mode"
CUE_PERSIST_SIDEBAR_WIDTH = "sfx_sidebar_width"

# Z-order within cue_layer: sidebar sits below the mod's dialogs and the
# overlay so dialogs always paint on top of the sidebar.
CUE_SIDEBAR_ZORDER = 8000
CUE_DIALOG_ZORDER = 9000

# Keymap names for rebindable cue hotkeys (registered in config.keymap).
CUE_KEYMAP_TOGGLE_OVERLAY = "cue_toggle_overlay"
CUE_KEYMAP_QUIT_RELAUNCH = "cue_quit_relaunch"
CUE_KEYMAP_COPY_CONTEXT = "cue_copy_context"
CUE_KEYMAP_PASTE_CONTEXT = "cue_paste_context"
CUE_KEYMAP_TOGGLE_SFX_ACTIVE = "cue_toggle_sfx_active"
CUE_KEYMAP_PAUSE = "cue_pause"
CUE_KEYMAP_UNDO = "cue_undo"
CUE_KEYMAP_REDO = "cue_redo"
CUE_KEYMAP_SPEED_UP = "cue_speed_up"
CUE_KEYMAP_SPEED_DOWN = "cue_speed_down"
CUE_KEYMAP_TOGGLE_SFX_LIBRARY = "cue_toggle_sfx_library"
CUE_KEYMAP_TOGGLE_SFX_SIDEBAR = "cue_toggle_sfx_sidebar"
CUE_KEYMAP_PAGE_SFX = "cue_page_sfx"
CUE_KEYMAP_PAGE_MUSIC = "cue_page_music"
CUE_KEYMAP_PAGE_IMPORT = "cue_page_import"
CUE_KEYMAP_PAGE_SETTINGS = "cue_page_settings"
CUE_KEYMAP_TARGET_VIDEO = "cue_target_video"
CUE_KEYMAP_TARGET_IMAGE = "cue_target_image"
CUE_KEYMAP_TARGET_DIALOGUE = "cue_target_dialogue"
CUE_KEYMAP_TARGET_LOOP = "cue_target_loop"

# Shared-config JSON at {shared}/data/cue_config.json (disabled_files, keybinds).
CUE_SHARED_CONFIG_FILENAME = "cue_config.json"

# The single manual backup is {shared}/backups/renpy_cue_backup.zip.
CUE_MANUAL_BACKUP_NAME = "renpy_cue_backup.zip"

# Manifest filename inside an import zip; drives validation, merge filter, and
# summary counts.
CUE_IMPORT_MANIFEST_NAME = "manifest.json"

# Characters kept from a SHA1 hex digest for file naming.  Shared by
# db._preset_path and sharing.importer_io._cue_preset_files -- keep in sync.
CUE_HASH_TRUNC_LEN = 8

# Canonical checkbox order and labels for the 5 categories.  Labels are
# user-facing; keep them in sync with the order here.
CUE_IMPORT_CATEGORY_ORDER = (
    CueImportCategory.MARKERS,
    CueImportCategory.SFX,
    CueImportCategory.MUSIC,
    CueImportCategory.SPEED_VARIANTS,
    CueImportCategory.PRESETS,
)
CUE_IMPORT_CATEGORY_LABELS = {
    CueImportCategory.MARKERS: "Markers",
    CueImportCategory.SFX: "SFX files",
    CueImportCategory.MUSIC: "Music files",
    CueImportCategory.SPEED_VARIANTS: "Speed variant files",
    CueImportCategory.PRESETS: "Presets",
}
