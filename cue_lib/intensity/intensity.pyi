from typing import Callable, List, Optional, Tuple, Union

from cue_lib._types import IgroupHookDict, MarkerEntry
from cue_lib.db import CueDatabase
from cue_lib.preset_store import CueIntensityPresets

def _level_ramp(count: int, max_value: float) -> List[float]: ...
def _cue_intensity_volume_mult(level_mult: float) -> float: ...

class CueIntensityFlags:
    enabled: bool
    sfx_levels: bool
    volume: bool
    frequency: bool

    def __init__(
        self, enabled: bool = True, sfx_levels: bool = True, volume: bool = True, frequency: bool = True
    ) -> None: ...

class CueIntensityResolution:
    group: str
    level: int
    volume_mult: float
    freq_mult: float
    files: List[str]

    def __init__(
        self, group: str, level: int, volume_mult: float, freq_mult: float, files: Optional[List[str]] = None
    ) -> None: ...

class CueIntensityManager:
    _presets: CueIntensityPresets

    def __init__(self, db: CueDatabase, presets: Optional[CueIntensityPresets] = None) -> None: ...
    def add_level(self, name: str) -> Optional[int]: ...
    def add_level_file(self, name: str, ilevel_id: int, file_ref: str) -> Optional[str]: ...
    def remove_level_file(self, name: str, ilevel_id: int, file_ref: str) -> None: ...
    def remove_level(self, name: str, index: int) -> None: ...
    def move_level(self, name: str, index: int, delta: int) -> None: ...
    def level_files(self, name: str, level_index: int) -> Optional[List[str]]: ...
    def level_files_by_id(self, name: str, ilevel_id: int) -> Optional[List[str]]: ...
    def level_multipliers(self, name: str, level_index: int) -> Tuple[float, float]: ...
    def flags_from_entry(self, entry: Optional[MarkerEntry]) -> CueIntensityFlags: ...
    def resolve_pool_intensity(
        self,
        igroup: Optional[str],
        ilevel_id: Optional[int],
        current_speed: float,
        variants: Optional[List[float]],
        flags: Optional[CueIntensityFlags] = None,
        resolve_files: Optional[Callable[[List[str]], List[str]]] = None,
    ) -> Optional[CueIntensityResolution]: ...
    def resolve_video_intensity(
        self,
        pool_hooks: List[Optional[IgroupHookDict]],
        current_speed: float,
        variants: Optional[List[float]],
        flags: Optional[CueIntensityFlags] = None,
        resolve_files: Optional[Callable[[List[str]], List[str]]] = None,
    ) -> Optional[CueIntensityResolution]: ...
    def current_level(
        self,
        pool_hooks: List[Optional[IgroupHookDict]],
        current_speed: float,
        variants: Optional[List[float]],
        flags: Optional[CueIntensityFlags] = None,
    ) -> Optional[Tuple[int, int]]: ...
    def video_hook(self, pool_hooks: List[Optional[IgroupHookDict]]) -> Optional[str]: ...
    def is_pool_intensity_active(
        self,
        igroup: Optional[Union[str, IgroupHookDict]],
        variants: Optional[List[float]],
        flags: Optional[CueIntensityFlags] = None,
    ) -> bool: ...
    def variant_levels(self, group_name: str, variants: List[float]) -> Optional[List[Tuple[float, int]]]: ...
