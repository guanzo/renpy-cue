from typing import Final

CUE_IMG_KEY_PREFIX: Final = "i_"
CUE_LOOP_KEY_PREFIX: Final = "l_"
CUE_DLG_KEY_PREFIX: Final = "d_"
CUE_VID_KEY_PREFIX: Final = "v_"
CUE_SFX_CHANNEL_COUNT: Final = 8
CUE_MAX_INTERP_FPS: Final = 60
CUE_SUBPROC_TIMEOUT: Final = 10.0
CUE_KILL_WAIT_TIMEOUT: Final = 5.0
CUE_DEFAULT_VIDEO_SPEED: Final = 1.0
CUE_MULTI_SPEED_MIN_VARIANTS: Final = 2
CUE_POPPER_DEFAULT_OFFSET: Final = 5
CUE_POPPER_DEFAULT_MARGIN: Final = 8
CUE_INTERVAL_SELECT_TOLERANCE: Final = 0.010
CUE_DUPLICATE_GAP_PX: Final = 28
CUE_TIMELINE_REF_W: Final = 480
CUE_DUPLICATE_GAP_FRAC: Final = 0.058333333333333334
CUE_AUTO_SPEED_MIN_VARIANTS: Final = 4
CUE_AUTO_SPEED_IDEAL_VARIANTS: Final = 8
CUE_SFX_LIBRARY_HEADER: Final = "SFX Library"
CUE_HELP_SHIFT_SKIP_DELETE: Final = "\nShift+Click to skip delete confirmation"
CUE_AUDIO_EXTS: Final = (".ogg", ".mp3", ".wav", ".opus")
CUE_RECENT_MAX_ENTRIES: Final = 8
CUE_RECENT_SFX_KEY: Final = "recent_entries"
CUE_RECENT_MUSIC_KEY: Final = "recent_music_entries"
CUE_GAME_MUSIC_DIRS: Final = ("music", "bgm", "ost", "soundtrack")
CUE_MUSIC_PREFIX: Final = "music/"
CUE_MY_MUSIC_FOLDER: Final = "My Music/"
CUE_GAME_MUSIC_FOLDER: Final = "Game Music/"
CUE_MUSIC_USER_TAG: Final = "u:"
CUE_MUSIC_GAME_TAG: Final = "g:"
CUE_VOLUME_DEFAULT: Final = 1.0

CUE_KEYMAP_TOGGLE_OVERLAY: Final = "cue_toggle_overlay"
CUE_KEYMAP_QUIT_RELAUNCH: Final = "cue_quit_relaunch"
CUE_KEYMAP_COPY_CONTEXT: Final = "cue_copy_context"
CUE_KEYMAP_PASTE_CONTEXT: Final = "cue_paste_context"
CUE_KEYMAP_TOGGLE_SFX_ACTIVE: Final = "cue_toggle_sfx_active"
CUE_KEYMAP_PAUSE: Final = "cue_pause"
CUE_KEYMAP_UNDO: Final = "cue_undo"
CUE_KEYMAP_REDO: Final = "cue_redo"
CUE_KEYMAP_SPEED_UP: Final = "cue_speed_up"
CUE_KEYMAP_SPEED_DOWN: Final = "cue_speed_down"
CUE_KEYMAP_TOGGLE_SFX_LIBRARY: Final = "cue_toggle_sfx_library"
CUE_KEYMAP_TOGGLE_SFX_OVERLAY: Final = "cue_toggle_sfx_overlay"
CUE_KEYMAP_PAGE_SFX: Final = "cue_page_sfx"
CUE_KEYMAP_PAGE_MUSIC: Final = "cue_page_music"
CUE_KEYMAP_PAGE_IMPORT: Final = "cue_page_import"
CUE_KEYMAP_PAGE_SETTINGS: Final = "cue_page_settings"
CUE_KEYMAP_TARGET_VIDEO: Final = "cue_target_video"
CUE_KEYMAP_TARGET_IMAGE: Final = "cue_target_image"
CUE_KEYMAP_TARGET_DIALOGUE: Final = "cue_target_dialogue"
CUE_KEYMAP_TARGET_LOOP: Final = "cue_target_loop"
CUE_SHARED_KEY_KEYBINDS: Final = "keybinds"
CUE_DIR_OVERRIDE_FILENAME: Final = "dir.txt"
CUE_SHARED_CONFIG_FILENAME: Final = "cue_config.json"
CUE_BACKUP_DIR: Final = "backups"
CUE_BACKUP_AUTO_DIR: Final = "auto"
CUE_MANUAL_BACKUP_NAME: Final = "renpy_cue_backup.zip"
CUE_IMPORT_FORMAT_VERSION: Final = 1
CUE_IMPORT_MANIFEST_NAME: Final = "manifest.json"
CUE_EXPORT_DIR: Final = "exports"
CUE_IMPORT_DIR: Final = "imports"
CUE_IMPORT_UNZIP_DIR: Final = "unzipped"
CUE_HASH_TRUNC_LEN: Final = 8
CUE_IMPORT_CATEGORY_ORDER: Final = (0, 1, 2, 3, 4)
CUE_IMPORT_CATEGORY_LABELS: Final = {
    0: "Markers",
    1: "SFX files",
    2: "Music files",
    3: "Speed variant files",
    4: "Presets",
}
CUE_DEBUG: bool = True  # not Final -- tests flip this to silence debug.log
CUE_DEBUG_LOG_FILENAME: Final = "debug.log"
CUE_ERROR_LOG_FILENAME: Final = "error.log"
CUE_DEBUG_LOG_BUFFER_LINES: Final = 64

class CueExclusiveStart:
    PLAY: Final = 0
    FADE: Final = 1
    WAIT: Final = 2

class CueLoopFrequency:
    SLOWEST: Final = 4
    SLOW: Final = 0
    MEDIUM: Final = 1
    FAST: Final = 2
    FASTEST: Final = 3

class CuePage:
    SFX: Final = 0
    MUSIC: Final = 1
    SETTINGS: Final = 2
    IMPORT: Final = 3

class CueImportCategory:
    MARKERS: Final = 0
    SFX: Final = 1
    MUSIC: Final = 2
    SPEED_VARIANTS: Final = 3
    PRESETS: Final = 4
    UNKNOWN: Final = 5

class CueExportScope:
    ALL_REPLAYS: Final = 0
    SPECIFIC_REPLAYS: Final = 1

class CueExportFileTypes:
    ALL: Final = 0
    SPECIFIC: Final = 1

class CueImportMatch:
    AUTO: Final = 0
    CONFIRM: Final = 1
    MISMATCH: Final = 2

class CueContextType:
    VIDEO: Final = "video"
    IMAGE: Final = "image"
    DIALOGUE: Final = "dialogue"
    LOOP: Final = "loop"

def _cue_env_flag(name: str, default: bool = False) -> bool: ...
