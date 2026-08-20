# -*- coding: utf-8 -*-
# Cross-file constants shared by multiple cue_lib modules.
# Every constant has a CUE_ prefix to avoid collisions in the flat Ren'Py store.

import os

# Debug mode, from the RENPY_CUE_DEBUG env var (1/true/yes/on, case-
# insensitive).  Unset keeps debug on.  Read at import time, so the var must
# be set before the game launches.
def _cue_env_flag(name, default=False):
    # type: (str, bool) -> bool
    """Parse a boolean env var: 1/true/yes/on (case-insensitive) are true.

    Unset/empty falls back to ``default``; any other value is false, so a
    Windows user pasting a stray value can't silently flip a feature on."""
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")

class CueExclusiveStart(object):
    """Exclusive 'start' behavior values (exclusive.start)."""
    PLAY = 0   # start immediately, overlapping whatever is playing
    FADE = 1   # cross-fade out non-group SFX, then play
    WAIT = 2   # wait until no non-group SFX is playing (loops only)


class CueLoopFrequency(object):
    """Loop SFX interval presets. Values match CueLoopContext.get_delay()."""
    SLOWEST = 4   # ~6.3s
    SLOW = 0      # ~3.8s
    MEDIUM = 1    # ~2.1s
    FAST = 2      # ~0.6s
    FASTEST = 3   # ~0.2s


class CuePage(object):
    """Overlay sidebar page tabs."""
    SFX = 0       # SFX editor (markers / library)
    MUSIC = 1     # Music page
    SETTINGS = 2  # Settings page
    IMPORT = 3    # Import / Export page


class CueImportCategory(object):
    """Import/export categories.  Each maps to a shared-root path prefix via
    _cue_import_category in cue_lib/importer_io.py (the single source of that
    mapping).  UNKNOWN is the catch-all for paths outside the 5 categories."""
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
    """File-type filter for the export: everything, or only the checked
    categories."""
    ALL = 0
    SPECIFIC = 1


class CueImportMatch(object):
    """game_id match levels between an import and the current game."""
    AUTO = 0       # exact -- no user action needed
    CONFIRM = 1    # heuristic -- surface as a guess the user confirms
    MISMATCH = 2   # no match -- manual remap required


class CueContextType(object):
    """SFX library target contexts for the [+] assign button. Values are the
    CueMarkerManager attribute names, so dispatch is getattr(manager, ctx_id)."""
    VIDEO = "video"
    IMAGE = "image"
    DIALOGUE = "dialogue"
    LOOP = "loop"


# Key prefixes for marker trigger keys.  Single source of truth -- db.py keys
# on the same strings, and util.py key helpers read them directly.
CUE_IMG_KEY_PREFIX = "i_"
CUE_LOOP_KEY_PREFIX = "l_"
CUE_DLG_KEY_PREFIX = "d_"
CUE_VID_KEY_PREFIX = "v_"

CUE_DEBUG = _cue_env_flag("RENPY_CUE_DEBUG", False)

# Debug log filename, written into the in-game base dir.
CUE_DEBUG_LOG_FILENAME = "debug.log"

# Debug lines buffer in memory before writing to disk (auto-flush threshold).
CUE_DEBUG_LOG_BUFFER_LINES = 64

# Number of dedicated SFX channels on the "sfx" mixer.
# Channels are named _cue_1 through _cue_N.
CUE_SFX_CHANNEL_COUNT = 8

# Maximum FPS cap for frame interpolation (minterpolate filter).
# Doubled source framerate is clamped to this ceiling.
CUE_MAX_INTERP_FPS = 60

# ffmpeg/ffprobe subprocess hang guards.  A hung binary can't block a thread
# forever: _cue_run_proc joins a communicate() thread with CUE_SUBPROC_TIMEOUT
# and _cue_wait_proc polls with CUE_KILL_WAIT_TIMEOUT.  The thread/poll
# implementations work on both Python 2.7 (Ren'Py 7.x) and Python 3 (8.x) --
# the native communicate(timeout=) kwarg only exists on Py3, so it isn't used.
CUE_SUBPROC_TIMEOUT = 10.0   # probe / encoder discovery communicate()
CUE_KILL_WAIT_TIMEOUT = 5.0  # post-kill reap in _kill_proc

# Default video playback speed (1.0 = original speed).
CUE_DEFAULT_VIDEO_SPEED = 1.0

# Minimum number of speed variants required before auto / multi-speed
# sequences activate.  Fewer than this is pointless.
CUE_MULTI_SPEED_MIN_VARIANTS = 2

# Minimum number of speed variants required for auto-speed presets.
CUE_AUTO_SPEED_MIN_VARIANTS = 4

# Ideal number of speed variants for rich auto-speed rhythm generation.
CUE_AUTO_SPEED_IDEAL_VARIANTS = 8

# SFX Library section header text and lookup key.  A constant because the
# toggle-SFX hotkey in cue_key_listener references the same string from a
# second location.  Other section titles are single-use literals.
CUE_SFX_LIBRARY_HEADER = "SFX Library"

# Audio file extensions accepted by the SFX library and My Music scans.
# Ren'Py officially supported formats.
CUE_AUDIO_EXTS = (".ogg", ".mp3", ".wav", ".opus")

# Maximum entries in a "Recently Used" list (SFX library; later, music).
CUE_RECENT_MAX_ENTRIES = 8

# persistent._cue keys for the "Recently Used" lists.  Music gets its own key
# so the two type-spaces (u:/g: refs vs sfx paths/preset names) never collide.
CUE_RECENT_SFX_KEY = "recent_entries"
CUE_RECENT_MUSIC_KEY = "recent_music_entries"

# Directory-name heuristic for Game Music discovery: a game file whose path
# contains one of these segments (case-insensitive) is classified as music.
# Shared with the Music page's empty-state text.
CUE_GAME_MUSIC_DIRS = ("music", "bgm", "ost", "soundtrack")

# My Music files are stored relative to the shared root, prefixed with the
# music dir's name plus a slash ("music/Folder/song.ogg").  user_music.py adds
# the prefix during discovery; music.py strips it when resolving a stored path
# back to an absolute file.  A single constant so the two never drift.
CUE_MUSIC_PREFIX = "music/"

# Synthetic top-level folder names in the combined Music Library tree.  The
# combined view (CueCombinedMusicTree) wraps each source's tree under one of
# these display-only folders, so the Music page shows exactly two top-level
# folders no matter how many top-level dirs the Game Music heuristic finds.
CUE_MY_MUSIC_FOLDER = "My Music/"
CUE_GAME_MUSIC_FOLDER = "Game Music/"

# Source tags for stored music refs.  My Music and Game Music can both contain
# a "music/" folder, so a bare path is ambiguous; the tag records which cache
# the ref came from so resolution never probes the disk to tell them apart.
# Shared by music.py (split/display), music_tree.py (display paths), and
# recent.py (_cue_keep_music prune check).
CUE_MUSIC_USER_TAG = "u:"
CUE_MUSIC_GAME_TAG = "g:"

# Default pool / preset volume (1.0 = identity).  Shared by the marker store,
# volume manager, trigger, and repeater -- was CueVolumeManager.VOL_DEFAULT
# before the marker data layer was extracted.  CueVolumeManager.VOL_DEFAULT
# still aliases this so legacy _cue.volume.VOL_DEFAULT references keep working.
CUE_VOLUME_DEFAULT = 1.0

# Popper displayable defaults — distance from anchor and viewport edge clearance.
CUE_POPPER_DEFAULT_OFFSET = 5
CUE_POPPER_DEFAULT_MARGIN = 8

# Matching tolerance for interval selection in the video marker timeline
# (Alt+Shift+Click): a marker counts as continuing the active-to-clicked
# spacing when it lands within +/- this of the projected grid position.
CUE_INTERVAL_SELECT_TOLERANCE = 0.010

# Duplicated markers land a fixed pixel gap after their source on the
# timeline, so the copy doesn't overlap it.  The gap is defined in pixels at a
# reference width and converted to a frac of the timeline width, then to
# seconds via frac * duration -- the same geometry the timeline's _time_to_x
# uses (frac = (t/speed)/dur, at the base speed duplicates are gated to).
CUE_DUPLICATE_GAP_PX = 28      # two 14px marker tabs of separation
CUE_TIMELINE_REF_W = 480       # reference inner width the gap is defined at
CUE_DUPLICATE_GAP_FRAC = CUE_DUPLICATE_GAP_PX / float(CUE_TIMELINE_REF_W)

# Keymap names for rebindable cue hotkeys (registered in config.keymap).
CUE_KEYMAP_TOGGLE_OVERLAY     = "cue_toggle_overlay"
CUE_KEYMAP_QUIT_RELAUNCH      = "cue_quit_relaunch"
CUE_KEYMAP_COPY_CONTEXT       = "cue_copy_context"
CUE_KEYMAP_PASTE_CONTEXT      = "cue_paste_context"
CUE_KEYMAP_TOGGLE_SFX_ACTIVE  = "cue_toggle_sfx_active"
CUE_KEYMAP_PAUSE              = "cue_pause"
CUE_KEYMAP_UNDO               = "cue_undo"
CUE_KEYMAP_REDO               = "cue_redo"
CUE_KEYMAP_SPEED_UP           = "cue_speed_up"
CUE_KEYMAP_SPEED_DOWN         = "cue_speed_down"
CUE_KEYMAP_TOGGLE_SFX_LIBRARY = "cue_toggle_sfx_library"
CUE_KEYMAP_TOGGLE_SFX_OVERLAY = "cue_toggle_sfx_overlay"
CUE_KEYMAP_PAGE_SFX           = "cue_page_sfx"
CUE_KEYMAP_PAGE_MUSIC         = "cue_page_music"
CUE_KEYMAP_PAGE_IMPORT        = "cue_page_import"
CUE_KEYMAP_PAGE_SETTINGS      = "cue_page_settings"
CUE_KEYMAP_TARGET_VIDEO       = "cue_target_video"
CUE_KEYMAP_TARGET_IMAGE       = "cue_target_image"
CUE_KEYMAP_TARGET_DIALOGUE    = "cue_target_dialogue"
CUE_KEYMAP_TARGET_LOOP        = "cue_target_loop"

# Shared-config key for persisting custom keybinds across games.
CUE_SHARED_KEY_KEYBINDS = "keybinds"

# Pointer file inside the platform-default shared dir that redirects to the
# user-chosen shared dir.  The default dir is the one anchor every game on
# the same OS user computes identically, so the choice applies to all games.
# In-game choice wins over the RENPY_CUE_DIR env var.
CUE_DIR_OVERRIDE_FILENAME = "dir.txt"

# Shared-config JSON file inside the shared data/ tree (disabled_files,
# keybinds).  Lives at {shared}/data/cue_config.json.
CUE_SHARED_CONFIG_FILENAME = "cue_config.json"

# Import format version, bumped only on breaking format changes (not the mod
# version).  The importer rejects an import whose format is NEWER than this.
CUE_IMPORT_FORMAT_VERSION = 1

# Manifest filename inside an import zip.  Drives import validation, the merge
# filter, and the summary counts.
CUE_IMPORT_MANIFEST_NAME = "manifest.json"

# Subdirs of the shared root where exported imports and dropped-in imports
# live.  Exports are written here; the user drops .zip files here to import.
# Both are computed from original_root so they never follow an active import.
CUE_EXPORT_DIR = "exports"
# Number of characters to keep from a SHA1 hex digest for file naming.
# Shared by db._preset_path and importer_io._cue_preset_files -- keep in sync.
CUE_HASH_TRUNC_LEN = 8

CUE_IMPORT_DIR = "imports"
# Subdir of imports/ where dropped zips are extracted into editable working
# copies -- keeps the drop zone archives-only.
CUE_IMPORT_UNZIP_DIR = "unzipped"

# Canonical checkbox order and labels for the 5 import/export categories.
# The labels are user-facing; keep them in sync with the order here.
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
