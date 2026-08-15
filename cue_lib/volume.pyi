# Type stub for cue_lib.volume
from typing import Optional

from cue_lib._types import MarkerEntry
from cue_lib.marker_store import CueMarkerStore
from cue_lib.state import CueContext
from cue_lib.markers import CueMarkerManager

class CueVolumeManager:
    VOL_MIN: float
    VOL_DEFAULT: float
    VOL_MAX: float
    _store: CueMarkerStore
    _ctx: CueContext
    _markers: Optional[CueMarkerManager]

    def __init__(
        self,
        store: CueMarkerStore,
        ctx: CueContext,
        markers: Optional[CueMarkerManager] = None) -> None: ...
    def get(
        self,
        entry: Optional[MarkerEntry],
        trigger_key: Optional[str] = None,
        pool_index: Optional[int] = None) -> float: ...
    def write(self, trigger_key: str, new_vol: float, pool_index: Optional[int] = None) -> None: ...
    def adjust(self, trigger_key: str, delta: float, pool_index: Optional[int] = None) -> None: ...
    def get_master(self, trigger_key: str) -> float: ...
    def set_master(self, trigger_key: str, value: float) -> None: ...
    def adjust_master(self, trigger_key: str, delta: float) -> None: ...
    def get_effective(
        self,
        entry: Optional[MarkerEntry],
        trigger_key: Optional[str] = None,
        pool_index: Optional[int] = None) -> float: ...
    def adjust_video(self, delta: float) -> None: ...
