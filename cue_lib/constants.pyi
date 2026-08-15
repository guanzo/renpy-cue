from typing import Final

CUE_IMG_KEY_PREFIX: Final = "i_"
CUE_LOOP_KEY_PREFIX: Final = "l_"
CUE_DLG_KEY_PREFIX: Final = "d_"
CUE_VID_KEY_PREFIX: Final = "v_"
CUE_SFX_CHANNEL_COUNT: Final = 8
CUE_MAX_INTERP_FPS: Final = 60
CUE_DEFAULT_VIDEO_SPEED: Final = 1.0
CUE_MULTI_SPEED_MIN_VARIANTS: Final = 2
CUE_POPPER_DEFAULT_OFFSET: Final = 5
CUE_POPPER_DEFAULT_MARGIN: Final = 8
CUE_AUTO_SPEED_MIN_VARIANTS: Final = 4
CUE_AUTO_SPEED_IDEAL_VARIANTS: Final = 8
CUE_SFX_LIBRARY_HEADER: Final = "SFX Library"
CUE_AUDIO_EXTS: Final = (".ogg", ".mp3", ".wav", ".opus")
CUE_GAME_MUSIC_DIRS: Final = ("music", "bgm", "ost", "soundtrack")
CUE_MUSIC_PREFIX: Final = "music/"
CUE_VOLUME_DEFAULT: Final = 1.0

CUE_KEYMAP_TOGGLE_OVERLAY: Final = "cue_toggle_overlay"
CUE_KEYMAP_QUIT_RELAUNCH: Final = "cue_quit_relaunch"
CUE_KEYMAP_COPY_CONTEXT: Final = "cue_copy_context"
CUE_KEYMAP_PASTE_CONTEXT: Final = "cue_paste_context"
CUE_KEYMAP_TOGGLE_ACTIVE: Final = "cue_toggle_active"
CUE_KEYMAP_PAUSE: Final = "cue_pause"
CUE_KEYMAP_UNDO: Final = "cue_undo"
CUE_KEYMAP_REDO: Final = "cue_redo"
CUE_KEYMAP_SPEED_UP: Final = "cue_speed_up"
CUE_KEYMAP_SPEED_DOWN: Final = "cue_speed_down"
CUE_KEYMAP_TOGGLE_SFX: Final = "cue_toggle_sfx"
CUE_SHARED_KEY_KEYBINDS: Final = "keybinds"
CUE_DIR_OVERRIDE_FILENAME: Final = "dir.txt"
CUE_SHARED_CONFIG_FILENAME: Final = "cue_config.json"
CUE_RECENT_MAX: Final = 10
CUE_DEBUG: bool = True  # not Final -- tests flip this to silence debug.log
CUE_DEBUG_LOG_FILENAME: Final = "debug.log"

class CueExclusiveStart:
    PLAY: Final = 0
    FADE: Final = 1
    WAIT: Final = 2

class CueLoopFrequency:
    SLOWEST: Final = 4
    SLOW: Final = 0
    NORMAL: Final = 1
    FAST: Final = 2
    FASTEST: Final = 3

class CuePage:
    SFX: Final = 0
    MUSIC: Final = 1
    SETTINGS: Final = 2

class CueRecentKind:
    FILE: Final = "file"
    FOLDER: Final = "folder"
    PRESET: Final = "preset"

def _cue_env_flag(name: str, default: bool = False) -> bool: ...
