# Type stub for cue_lib.audio.sfx_manager
from typing import Any, Dict, List, Optional, Set

from cue_lib.audio.audio_tree import CueAudioTreeManager
from cue_lib.audio.wav_playable import CueWavPlayable
from cue_lib.db import CueDatabase
from cue_lib.markers import CueMarkerManager
from cue_lib.paths import CuePaths
from cue_lib.intensity import CueIntensityManager
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
    expanded_video_pools: Dict[str, Dict[int, bool]]
    disabled_files: Set[str]
    is_sidebar_mode: bool
    igroups_expanded: bool
    expanded_igroups: Dict[str, bool]
    igroup_add_target: Optional[str]
    _intensity: Optional[CueIntensityManager]
    add_to_pool_warning: str

    def __init__(self, paths: CuePaths, db: CueDatabase) -> None: ...
    def toggle_file_enabled(self, full_path: str) -> None: ...
    def toggle_file_ref_expand(self, folder_ref: str) -> None: ...
    def count_file_list_rows(
        self, folder_label: Optional[str], folder_children: Optional[List[str]], files: List[str]
    ) -> int: ...
    def toggle_presets_expand(self) -> None: ...
    def toggle_preset_expand(self, preset_name: str) -> None: ...
    def toggle_video_presets_expand(self) -> None: ...
    def toggle_video_preset_expand(self, preset_name: str) -> None: ...
    def toggle_video_pool_expand(self, preset_name: str, pool_index: int) -> None: ...
    def toggle_igroups_expand(self) -> None: ...
    def toggle_igroup_expand(self, group_name: str) -> None: ...
    def toggle_igroup_add_mode(self, group_name: str) -> None: ...
    def igroup_add_folder(self, group_name: str, folder_path: str) -> None: ...
    def set_add_to_pool_warning(self, message: str) -> None: ...
    def clear_add_to_pool_warning(self) -> None: ...
    def toggle_sidebar_mode(self) -> None: ...

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
    _wav_playable: CueWavPlayable
    _warm_thread: Optional[Any]

    def __init__(
        self,
        paths: CuePaths,
        db: CueDatabase,
        volume: CueVolumeManager,
        ctx: CueContext,
        supports_relative_volume: bool,
    ) -> None: ...
    def bind_markers(self, markers: CueMarkerManager) -> None: ...
    def _markers_ctx(self) -> CueMarkerManager: ...
    def warm_cache(self) -> None: ...
    def unplayable_files(self) -> Dict[str, str]: ...
    def play_sfx(
        self,
        filename: str,
        source: str = "",
        volume: float = 1.0,
        marker_time: Optional[float] = None,
        marker_elapsed: Optional[float] = None,
        marker_delta: Optional[float] = None,
    ) -> Optional[str]: ...
    def preview_sfx(self, filename: str, volume: float = 1.0) -> None: ...
    def play_pool(
        self,
        entry: Optional[MarkerEntry],
        key: str,
        pool: PoolDict,
        pool_index: int,
        file: Optional[str] = None,
        avoid_repeats: bool = True,
        files: Optional[List[str]] = None,
        volume_mult: Optional[float] = None,
        marker_time: Optional[float] = None,
        marker_elapsed: Optional[float] = None,
        marker_delta: Optional[float] = None,
    ) -> Optional[str]: ...
    def fade_out(
        self, exclude_channels: Optional[List[str]] = None, only_channels: Optional[List[str]] = None
    ) -> int: ...
    def preview_preset(self, preset_name: str) -> None: ...
    def preview_folder(self, folder_path: str, volume: float = 1.0) -> None: ...
    def preview_video_preset(self, preset_name: str) -> None: ...
    def preview_video_pool(self, preset_name: str, pool_index: int) -> None: ...
