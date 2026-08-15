# Type stub for cue_lib.trigger
from typing import Any, Dict, List, Optional, Set

from cue_lib.marker_store import CueMarkerStore
from cue_lib.video.repeater import CueMarkerRepeater
from cue_lib.video.speed import CueVidSpeedResolver
from cue_lib.video.video import CueVideoManager
from cue_lib.markers import CueMarkerManager

def _cue_pick_deduped(files: List[str], picked: List[str], max_tries: int = 3) -> Optional[str]: ...
def _cue_marker_reached(mt: float, effective_elapsed: float, prev_eff: float, marker_tolerance: float) -> bool: ...

class CueTriggerEngine:
    active: bool
    loop_states: Dict[str, Any]
    excl_channels: Dict[str, Dict[str, Any]]
    last_played: List[str]
    played_video_keys: Set[str]
    _prev_eff_elapsed: float
    _tick_count: int
    _store: CueMarkerStore
    _repeater: CueMarkerRepeater
    _speed_resolver: CueVidSpeedResolver
    _vid_manager: CueVideoManager
    _markers: Optional[CueMarkerManager]

    def __init__(
        self,
        store: CueMarkerStore,
        repeater: CueMarkerRepeater,
        speed_resolver: CueVidSpeedResolver,
        vid_manager: CueVideoManager,
        markers: Optional[CueMarkerManager] = None) -> None: ...
    def _markers_ctx(self) -> Any: ...
    def tick(self, current_file: str, top_layer_type: str) -> None: ...
    def fire_context(self, *keys: Optional[str], **kwargs: Any) -> None: ...
