# -*- coding: utf-8 -*-
# Cross-file constants shared by multiple cue_lib modules.
# Every constant has a CUE_ prefix to avoid collisions in the flat Ren'Py store.

# Number of dedicated SFX channels on the "sfx" mixer.
# Channels are named _cue_1 through _cue_N.
CUE_SFX_CHANNEL_COUNT = 8

# Maximum FPS cap for frame interpolation (minterpolate filter).
# Doubled source framerate is clamped to this ceiling.
CUE_MAX_INTERP_FPS = 60

# Default video playback speed (1.0 = original speed).
CUE_DEFAULT_VIDEO_SPEED = 1.0

# Minimum number of speed variants required before auto / multi-speed
# sequences activate.  Fewer than this is pointless.
CUE_MULTI_SPEED_MIN_VARIANTS = 2

# Minimum number of speed variants required for auto-speed presets.
CUE_AUTO_SPEED_MIN_VARIANTS = 4

# Ideal number of speed variants for rich auto-speed rhythm generation.
CUE_AUTO_SPEED_IDEAL_VARIANTS = 8

# SFX Library section header text and lookup key.
CUE_SFX_LIBRARY_HEADER = "SFX Library"

# Popper displayable defaults — distance from anchor and viewport edge clearance.
CUE_POPPER_DEFAULT_OFFSET = 5
CUE_POPPER_DEFAULT_MARGIN = 8

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

# Settings section header text.
CUE_KEYBINDS_SECTION_HEADER = "Keybinds"
