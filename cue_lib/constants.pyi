from typing import Final

CUE_VERSION: Final = "0.1.0"
CUE_DISCORD: Final = "https://discord.gg/kAVtFGcQYm"
CUE_GITHUB: Final = "https://github.com/guanzo/renpy-cue/issues"
CUE_KOFI: Final = "https://ko-fi.com/guanzo"

CUE_IMG_KEY_PREFIX: Final = "i_"
CUE_LOOP_KEY_PREFIX: Final = "l_"
CUE_DLG_KEY_PREFIX: Final = "d_"
CUE_VID_KEY_PREFIX: Final = "v_"
CUE_SFX_CHANNEL_COUNT: Final = 16
CUE_DEFAULT_VIDEO_SPEED: Final = 1.0
CUE_AUTO_SPEED_MIN_VARIANTS: Final = 4
CUE_AUTO_SPEED_IDEAL_VARIANTS: Final = 8
CUE_INTENSITY_IDEAL_LEVELS: Final = 3
CUE_SFX_LIBRARY_HEADER: Final = "SFX Library"
CUE_HELP_SHIFT_SKIP_DELETE: Final = "\nShift+Click to skip delete confirmation"
CUE_AUDIO_EXTS: Final = (".ogg", ".mp3", ".wav", ".opus")
CUE_MUSIC_PREFIX: Final = "music/"
CUE_MY_MUSIC_FOLDER: Final = "My Music/"
CUE_GAME_MUSIC_FOLDER: Final = "Game Music/"
CUE_MUSIC_USER_TAG: Final = "u:"
CUE_MUSIC_GAME_TAG: Final = "g:"
CUE_SFX_FOLDER: Final = "SFX/"
CUE_VOLUME_DEFAULT: Final = 1.0

CUE_INTENSITY_PRESET_TYPE: Final = "intensity"
CUE_INTENSITY_VOLUME_MAX: Final = 1.25
CUE_INTENSITY_FREQ_MAX: Final = 1.5
CUE_INTENSITY_DELAY_MIN: Final = 0.2
CUE_INTENSITY_DELAY_MAX: Final = 6.0
CUE_INTENSITY_HINT_COLOR: Final = "#ff8800"
CUE_INTENSITY_NOTE: Final = "Intensity mode active"

CUE_SIDEBAR_DEFAULT_WIDTH: Final = 320
CUE_SIDEBAR_MIN_WIDTH: Final = 200
CUE_SIDEBAR_MAX_WIDTH_RATIO: Final = 0.5
CUE_PERSIST_SIDEBAR_MODE: Final = "sfx_sidebar_mode"
CUE_PERSIST_SIDEBAR_WIDTH: Final = "sfx_sidebar_width"

CUE_PERSIST_SFX_TREE_EXPANDED: Final = "sfx_tree_expanded"
CUE_PERSIST_MUSIC_TREE_EXPANDED: Final = "music_tree_expanded"
CUE_PERSIST_SFX_UI_STATE: Final = "sfx_ui_state"
CUE_PERSIST_MUSIC_UI_STATE: Final = "music_ui_state"

CUE_SIDEBAR_ZORDER: Final = 8000
CUE_DIALOG_ZORDER: Final = 9000

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
CUE_KEYMAP_TOGGLE_SFX_SIDEBAR: Final = "cue_toggle_sfx_sidebar"
CUE_KEYMAP_PAGE_SFX: Final = "cue_page_sfx"
CUE_KEYMAP_PAGE_MUSIC: Final = "cue_page_music"
CUE_KEYMAP_PAGE_IMPORT: Final = "cue_page_import"
CUE_KEYMAP_PAGE_SETTINGS: Final = "cue_page_settings"
CUE_KEYMAP_TARGET_VIDEO: Final = "cue_target_video"
CUE_KEYMAP_TARGET_IMAGE: Final = "cue_target_image"
CUE_KEYMAP_TARGET_DIALOGUE: Final = "cue_target_dialogue"
CUE_KEYMAP_TARGET_LOOP: Final = "cue_target_loop"
CUE_SHARED_CONFIG_FILENAME: Final = "cue_config.json"
CUE_SHARED_KEY_MUSIC_FOLDERS: Final = "music_folders"
CUE_SHARED_KEY_SFX_FOLDERS: Final = "sfx_folders"
CUE_MANUAL_BACKUP_NAME: Final = "renpy_cue_backup.zip"
CUE_IMPORT_MANIFEST_NAME: Final = "manifest.json"
CUE_HASH_TRUNC_LEN: Final = 8
CUE_EXTERNAL_HASH_LEN: Final = 12
CUE_IMPORT_CATEGORY_ORDER: Final = (0, 1, 2, 3, 4)
CUE_IMPORT_CATEGORY_LABELS: Final = {
    0: "Markers",
    1: "SFX files",
    2: "Music files",
    3: "Speed variant files",
    4: "Presets",
}
CUE_DEBUG: bool = True  # not Final -- tests flip this to silence debug.log

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
