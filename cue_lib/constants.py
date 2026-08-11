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
CUE_MIN_SPEEDS_FOR_SEQUENCE = 2

# Popper displayable defaults — distance from anchor and viewport edge clearance.
CUE_POPPER_DEFAULT_OFFSET = 5
CUE_POPPER_DEFAULT_MARGIN = 8
