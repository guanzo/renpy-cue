# -*- coding: utf-8 -*-
# Cross-file constants shared by multiple cue_lib modules.
# Every constant has a CUE_ prefix to avoid collisions in the flat Ren'Py store.

import os

# Key prefixes for marker trigger keys.  Single source of truth -- db.py keys
# on the same strings, and util.py key helpers read them directly.
CUE_IMG_KEY_PREFIX = "i_"
CUE_LOOP_KEY_PREFIX = "l_"
CUE_DLG_KEY_PREFIX = "d_"
CUE_VID_KEY_PREFIX = "v_"

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


CUE_DEBUG = _cue_env_flag("RENPY_CUE_DEBUG", False)

# Debug log filename, written into the in-game base dir.
CUE_DEBUG_LOG_FILENAME = "debug.log"

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

# Directory-name heuristic for Game Music discovery: a game file whose path
# contains one of these segments (case-insensitive) is classified as music.
# Shared with the Music page's empty-state text.
CUE_GAME_MUSIC_DIRS = ("music", "bgm", "ost", "soundtrack")

# My Music files are stored relative to the shared root, prefixed with the
# music dir's name plus a slash ("music/Folder/song.ogg").  user_music.py adds
# the prefix during discovery; music.py strips it when resolving a stored path
# back to an absolute file.  A single constant so the two never drift.
CUE_MUSIC_PREFIX = "music/"

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
CUE_KEYMAP_TOGGLE_OVERLAY  = "cue_toggle_overlay"
CUE_KEYMAP_QUIT_RELAUNCH   = "cue_quit_relaunch"
CUE_KEYMAP_COPY_CONTEXT    = "cue_copy_context"
CUE_KEYMAP_PASTE_CONTEXT   = "cue_paste_context"
CUE_KEYMAP_TOGGLE_ACTIVE   = "cue_toggle_active"
CUE_KEYMAP_PAUSE           = "cue_pause"
CUE_KEYMAP_UNDO            = "cue_undo"
CUE_KEYMAP_REDO            = "cue_redo"
CUE_KEYMAP_SPEED_UP        = "cue_speed_up"
CUE_KEYMAP_SPEED_DOWN      = "cue_speed_down"
CUE_KEYMAP_TOGGLE_SFX      = "cue_toggle_sfx"

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


# =========================================================================
# Flat enum classes -- plain-int members so screens can compare against
# stored ints (Python 2.7-safe, no enum base class).  Moved here so the
# marker data layer (cue_lib.marker_store) can use them without importing
# back into the modules that define the coordinators.
# =========================================================================

class CueExclusiveStart(object):
    """Exclusive 'start' behavior values (exclusive.start)."""
    PLAY = 0   # start immediately, overlapping whatever is playing
    FADE = 1   # cross-fade out non-group SFX, then play
    WAIT = 2   # wait until no non-group SFX is playing (loops only)


class CueLoopFrequency(object):
    """Loop SFX interval presets. Values match CueLoopContext.get_delay()."""
    SLOWEST = 4   # ~6.3s
    SLOW = 0      # ~3.8s
    NORMAL = 1    # ~2.1s
    FAST = 2      # ~0.6s
    FASTEST = 3   # ~0.2s


class CuePage(object):
    """Overlay sidebar page tabs.

    Members are plain ints so screens can compare against _cue.overlay_active_page
    (Python 2.7-safe -- no enum base class).
    """
    SFX = 0       # SFX editor (markers / library)
    MUSIC = 1     # Music page
    SETTINGS = 2  # Settings page
