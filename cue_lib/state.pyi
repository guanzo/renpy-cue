from typing import Any, Dict, Optional, Set, Tuple

from cue_lib.video.repeater import CueMarkerRepeater
from cue_lib.video.ffmpeg import CueFFmpeg
from cue_lib.audio.sfx_manager import CueSfxManager
from cue_lib.markers import CueMarkerManager
from cue_lib._types import (
    MarkerEntry, PoolDict, UndoSnapshot, VideoPreset,  # pyright: ignore[reportUnusedImport]
)
from cue_lib.video.auto_speed import CueAutoSpeedGenerator
from cue_lib.video.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
from cue_lib.trigger import CueTriggerEngine
from cue_lib.ui.dialogues import CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog
from cue_lib.undo import CueUndoManager
from cue_lib.video.video import CueVideoManager
from cue_lib.video.video_editor import CueVideoEditor
from cue_lib.db import CueDatabase
from cue_lib.volume import CueVolumeManager
from cue_lib.audio.music import CueMusicManager
from cue_lib.keybinds import CueKeybindsManager
from cue_lib.ui.icons import CueIconManager
from cue_lib.paths import CuePaths

class CuePage:
    SFX: int
    MUSIC: int
    SETTINGS: int


class Cue:
    debug: bool
    config_filename: str
    debug_log_filename: str

    IMG_KEY_PREFIX: str
    LOOP_KEY_PREFIX: str
    DLG_KEY_PREFIX: str
    VID_KEY_PREFIX: str

    initialized: bool
    is_overlay_visible: bool
    overlay_active_page: int
    is_exclusive_row_visible: bool
    collapsed_sections: Dict[str, bool]
    sfx_library_overlay_mode: bool
    current_file: str
    current_dialogue: str
    prev_dialogue: str
    top_layer_type: Optional[str]
    top_displayable: Any
    current_replay: Any
    setup_dir_text: str
    shared_dir_error: str
    shared_dir_success: str
    _has_relative_volume: bool

    db: CueDatabase
    paths: CuePaths
    markers: CueMarkerManager
    undo: CueUndoManager
    trigger: CueTriggerEngine
    vid_manager: CueVideoManager
    volume: CueVolumeManager
    repeater: CueMarkerRepeater
    ffmpeg: CueFFmpeg
    video_editor: CueVideoEditor
    speed_resolver: CueVidSpeedResolver
    video_sequence: CueVidSpeedSequence
    speed_toast: CueSpeedToast
    auto_speed: CueAutoSpeedGenerator
    sfx_manager: CueSfxManager
    preset_dialog: CuePresetDialog
    video_preset_dialog: CueVideoPresetDialog
    confirm_dialog: CueConfirmDialog
    keybinds: CueKeybindsManager
    icons: CueIconManager
    music_manager: CueMusicManager

    _cue_next_sfx_channel: int
    _shake_just_happened: bool
    _preview_channel: Optional[str]
    _logged_unknown_displayables: Set[Tuple[str, str]]
    _marker_tip_text: str
    _marker_tip_x: int
    _marker_tip_y: int
    _popper_anchors: Dict[str, Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]]
    _create_delete_speed: Optional[Tuple[str, float]]
    _vtl_screen_x: int
    _vtl_screen_y: int
    _chart_screen_x: int
    _chart_screen_y: int

    def toggle_section(self, section_name: str) -> None: ...
    def toggle_sfx_library_overlay_mode(self) -> None: ...

_cue: Cue
