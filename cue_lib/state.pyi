from typing import Any, Dict, Optional, Tuple

from cue_lib.video.ffmpeg import CueFFmpeg
from cue_lib.audio.sfx_manager import CueSfxManager
from cue_lib.markers import CueMarkerManager
from cue_lib.marker_store import CueMarkerStore
from cue_lib._types import (
    MarkerEntry as MarkerEntry,
    PoolDict as PoolDict,
    UndoSnapshot as UndoSnapshot,
    VideoPreset as VideoPreset,
)
from cue_lib.video.auto_speed import CueAutoSpeedGenerator
from cue_lib.video.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
from cue_lib.trigger import CueTriggerEngine
from cue_lib.ui.dialogs import CueDialogs
from cue_lib.sharing import CueImportManager, CueExportManager, CueUrlImporter
from cue_lib.undo import CueUndoManager
from cue_lib.video.video import CueVideoManager
from cue_lib.video.video_editor import CueVideoEditor
from cue_lib.db import CueDatabase
from cue_lib.backup import CueBackupManager
from cue_lib.volume import CueVolumeManager
from cue_lib.music.manager import CueMusicManager
from cue_lib.settings import CueSettings
from cue_lib.keybinds import CueKeybindsManager
from cue_lib.ui.icons import CueIconManager
from cue_lib.paths import CuePaths
from cue_lib.intensity import CueIntensityManager
from cue_lib.preset_store import CuePresetStore
from cue_lib.constants import CuePage  # pyright: ignore[reportUnusedImport]  # re-exported from constants

class CueContext:
    current_file: str
    current_dialogue: str
    prev_dialogue: str
    top_layer_type: Optional[str]
    top_displayable: Any
    _shake_just_happened: bool

    def __init__(self) -> None: ...

class Cue:
    initialized: bool
    VERSION: str
    is_overlay_visible: bool
    overlay_active_page: int
    collapsed_sections: Dict[str, bool]
    ctx: CueContext
    active_input: str
    active_input_rect: Optional[Tuple[int, int, int, int]]
    current_file: str
    current_dialogue: str
    prev_dialogue: str
    top_layer_type: Optional[str]
    _has_relative_volume: bool

    db: CueDatabase
    intensity: CueIntensityManager
    presets: CuePresetStore
    backups: CueBackupManager
    paths: CuePaths
    marker_store: CueMarkerStore
    markers: CueMarkerManager
    undo: CueUndoManager
    trigger: CueTriggerEngine
    vid_manager: CueVideoManager
    volume: CueVolumeManager
    ffmpeg: CueFFmpeg
    video_editor: CueVideoEditor
    speed_resolver: CueVidSpeedResolver
    video_sequence: CueVidSpeedSequence
    speed_toast: CueSpeedToast
    auto_speed: CueAutoSpeedGenerator
    sfx: CueSfxManager
    settings: CueSettings
    dialogs: CueDialogs
    keybinds: CueKeybindsManager
    icons: CueIconManager
    music: CueMusicManager
    importer: CueImportManager
    exporter: CueExportManager
    url_importer: CueUrlImporter

    _create_delete_speed: Optional[Tuple[str, float]]

    def toggle_section(self, section_name: str) -> None: ...

_cue: Cue
