# Type stub for cue_lib.audio.sfx_manager
from typing import Dict, List, Optional

from cue_lib.audio.tree.sfx_tree import CueSfxLibraryTree
from cue_lib.audio.wav_playable import CueWavPlayable
from cue_lib.db import CueDatabase
from cue_lib.markers import CueMarkerManager
from cue_lib.paths import CuePaths
from cue_lib.preset_store import CuePresetStore
from cue_lib.state import CueContext
from cue_lib.volume import CueVolumeManager
from cue_lib._types import MarkerEntry, PoolDict

def _cue_sfx_channel_name(index: int) -> str: ...
def _cue_sfx_channel_index(ch_name: str) -> int: ...

class CueSfxManager(object):
    library: CueSfxLibraryTree
    _paths: CuePaths
    _db: CueDatabase
    _volume: CueVolumeManager
    _ctx: CueContext
    _supports_relative_volume: bool
    _presets: CuePresetStore
    _markers: Optional[CueMarkerManager]
    _next_sfx_channel: int
    _preview_channel: Optional[str]
    _wav_playable: CueWavPlayable

    def __init__(
        self,
        paths: CuePaths,
        db: CueDatabase,
        volume: CueVolumeManager,
        ctx: CueContext,
        supports_relative_volume: bool,
        presets: CuePresetStore,
    ) -> None: ...
    def bind_markers(self, markers: CueMarkerManager) -> None: ...
    def _markers_ctx(self) -> CueMarkerManager: ...
    def unplayable_files(self) -> Dict[str, str]: ...
    def play_sfx(
        self,
        filename: str,
        source: str = "",
        volume: float = 1.0,
        marker_time: Optional[float] = None,
        marker_elapsed: Optional[float] = None,
        marker_err: Optional[float] = None,
        marker_gap: Optional[float] = None,
        marker_gap_expected: Optional[float] = None,
    ) -> Optional[str]: ...
    def _build_play_log(
        self,
        filename: str,
        target_ch: str,
        source: str,
        marker_time: Optional[float],
        marker_err: Optional[float],
        marker_gap: Optional[float],
        marker_gap_expected: Optional[float],
        marker_elapsed: Optional[float],
    ) -> str: ...
    def preview_sfx(self, filename: str, volume: float = 1.0) -> None: ...
    def play_pool(
        self,
        entry: Optional[MarkerEntry],
        key: str,
        pool: PoolDict,
        pool_index: int,
        file: Optional[str] = None,
        avoid_repeats: bool = True,
        volume_mult: Optional[float] = None,
        marker_time: Optional[float] = None,
        marker_elapsed: Optional[float] = None,
        marker_err: Optional[float] = None,
        marker_gap: Optional[float] = None,
        marker_gap_expected: Optional[float] = None,
    ) -> Optional[str]: ...
    def fade_out(
        self, exclude_channels: Optional[List[str]] = None, only_channels: Optional[List[str]] = None
    ) -> int: ...
    def preview_preset(self, preset_name: str) -> None: ...
    def preview_folder(self, folder_path: str, volume: float = 1.0) -> None: ...
    def preview_level(self, group_name: str, ilevel_id: int) -> None: ...
    def preview_video_preset(self, preset_name: str) -> None: ...
    def preview_video_pool(self, preset_name: str, pool_index: int) -> None: ...
