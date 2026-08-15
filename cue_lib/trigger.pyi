# Type stub for cue_lib.trigger
from typing import Any, Dict, List, Optional, Set

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

    def __init__(self) -> None: ...
    def tick(self, current_file: str, top_layer_type: str) -> None: ...
    def fire_context(self, *keys: Optional[str], **kwargs: Any) -> None: ...
