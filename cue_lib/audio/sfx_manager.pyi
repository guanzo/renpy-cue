# Type stub for cue_lib.audio.sfx_manager
from typing import Dict, List, Optional, Set

from cue_lib.audio.audio_tree import CueAudioTreeManager
from cue_lib.db import CueDatabase
from cue_lib.markers import CueMarkerManager
from cue_lib.paths import CuePaths
from cue_lib.state import CueContext
from cue_lib.volume import CueVolumeManager
from cue_lib._types import MarkerEntry, PoolDict


def _cue_sfx_channel_name(index: int) -> str: ...
def _cue_sfx_channel_index(ch_name: str) -> int: ...

class CueSfxLibraryTree(CueAudioTreeManager):
    expanded_file_refs: Dict[str, bool]
    presets_expanded: bool
    expanded_presets: Dict[str, bool]
    video_presets_expanded: bool
    expanded_video_presets: Dict[str, bool]
    disabled_files: Set[str]
    overlay_mode: bool

    def __init__(self, paths: CuePaths, db: CueDatabase) -> None: ...
    def toggle_file_enabled(self, full_path: str) -> None: ...
    def toggle_file_ref_expand(self, folder_ref: str) -> None: ...
    def count_file_list_rows(
        self,
        folder_label: Optional[str],
        folder_children: Optional[List[str]],
        files: List[str]) -> int: ...
    def toggle_presets_expand(self) -> None: ...
    def toggle_preset_expand(self, preset_name: str) -> None: ...
    def toggle_video_presets_expand(self) -> None: ...
    def toggle_video_preset_expand(self, preset_name: str) -> None: ...
    def toggle_overlay_mode(self) -> None: ...

class CueSfxManager(object):
    library: CueSfxLibraryTree
    _paths: CuePaths
    _db: CueDatabase
    _volume: CueVolumeManager
    _ctx: CueContext
    _supports_relative_volume: bool
    _markers: Optional[CueMarkerManager]
    _next_sfx_channel: int
    _preview_channel: Optional[str]

    def __init__(
        self,
        paths: CuePaths,
        db: CueDatabase,
        volume: CueVolumeManager,
        ctx: CueContext,
        supports_relative_volume: bool) -> None: ...
    def bind_markers(self, markers: CueMarkerManager) -> None: ...
    def _markers_ctx(self) -> CueMarkerManager: ...
    def play_sfx(self, filename: str, source: str = "", volume: float = 1.0) -> Optional[str]: ...
    def preview_sfx(self, filename: str, volume: float = 1.0) -> None: ...
    def play_pool(
        self,
        entry: Optional[MarkerEntry],
        key: str,
        pool: PoolDict,
        pool_index: int,
        file: Optional[str] = None,
        avoid_repeats: bool = True) -> Optional[str]: ...
    def fade_out(
        self,
        exclude_channels: Optional[List[str]] = None,
        only_channels: Optional[List[str]] = None) -> int: ...
    def preview_preset(self, preset_name: str) -> None: ...
    def preview_folder(self, folder_path: str, volume: float = 1.0) -> None: ...
    def preview_video_preset(self, preset_name: str) -> None: ...
