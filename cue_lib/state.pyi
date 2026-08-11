from typing import Any, Dict, List, Optional, Set, Tuple

from cue_lib.repeater import CueMarkerRepeater
from cue_lib.ffmpeg import CueFFmpeg
from cue_lib.file_tree import CueFileTreeManager
from cue_lib.markers import CueMarkerManager
from cue_lib._types import (
    AudioTreeNode, MarkerEntry, PoolDict, UndoSnapshot, VideoPreset,  # pyright: ignore[reportUnusedImport]
)
from cue_lib.auto_speed import CueAutoSpeedGenerator
from cue_lib.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
from cue_lib.trigger import CueTriggerEngine
from cue_lib.ui_logic import CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog
from cue_lib.undo import CueUndoManager
from cue_lib.video import CueVideoManager
from cue_lib.video_editor import CueVideoEditor
from cue_lib.db import CueDatabase
from cue_lib.volume import CueVolumeManager

class Cue:
    debug: bool
    base_dir: str
    audio_dir: str
    config_filename: str
    debug_log_filename: str
    config_path: str
    shared_dir: str

    DEFAULT_VIDEO_SPEED: float
    VOL_DEFAULT: float
    IMG_KEY_PREFIX: str
    LOOP_KEY_PREFIX: str
    DLG_KEY_PREFIX: str
    VID_KEY_PREFIX: str

    initialized: bool
    is_overlay_visible: bool
    current_file: str
    current_dialogue: str
    prev_dialogue: str
    top_layer_type: Optional[str]
    top_displayable: Any
    current_replay: Any
    scan_error: Optional[str]
    _has_relative_volume: bool

    db: CueDatabase
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
    file_tree: CueFileTreeManager
    preset_dialog: CuePresetDialog
    video_preset_dialog: CueVideoPresetDialog
    confirm_dialog: CueConfirmDialog

    available_files: List[str]
    audio_tree: List[AudioTreeNode]

    _cue_next_sfx_channel: int
    _shake_just_happened: bool
    _preview_channel: Optional[str]
    _logged_unknown_displayables: Set[Tuple[str, str]]
    _marker_tip_text: str
    _marker_tip_x: int
    _marker_tip_y: int
    _popper_anchors: Dict[str, Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]]
    _seq_popup_index: int
    _vtl_screen_x: int
    _vtl_screen_y: int
    _chart_screen_x: int
    _chart_screen_y: int

_cue: Cue
