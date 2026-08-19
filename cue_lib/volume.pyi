# Type stub for cue_lib.volume
from typing import Optional, Set

from cue_lib._types import MarkerEntry
from cue_lib.marker_store import CueMarkerStore
from cue_lib.state import CueContext

class CueVolumeManager:
    VOL_MIN: float
    VOL_DEFAULT: float
    VOL_MAX: float
    _store: CueMarkerStore
    _ctx: CueContext
    _pending_saves: Set[str]

    def __init__(
        self,
        ctx: CueContext,
        store: CueMarkerStore) -> None: ...
    def get(
        self,
        entry: Optional[MarkerEntry],
        marker_key: Optional[str] = None,
        pool_index: Optional[int] = None) -> float: ...
    def write(self, marker_key: str, new_vol: float, pool_index: Optional[int] = None) -> None: ...
    def adjust(self, marker_key: str, delta: float, pool_index: Optional[int] = None) -> None: ...
    def get_master(self, marker_key: str) -> float: ...
    def set_master(self, marker_key: str, value: float) -> None: ...
    def adjust_master(self, marker_key: str, delta: float) -> None: ...
    def get_effective(
        self,
        entry: Optional[MarkerEntry],
        marker_key: Optional[str] = None,
        pool_index: Optional[int] = None) -> float: ...
    def marker_queue_save(self, key: str) -> None: ...
    def flush_pending_saves(self) -> None: ...
