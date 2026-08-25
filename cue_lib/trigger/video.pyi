# Type stub for cue_lib.trigger.video
from typing import List, Optional, Set

from cue_lib.trigger.engine import CueTriggerEngine

class CueVideoTrigger:
    played_video_keys: Set[str]
    _prev_eff_elapsed: float

    def __init__(self, engine: CueTriggerEngine) -> None: ...
    def reset(self) -> None: ...
    def tick(
        self,
        current_file: str,
        top_layer_type: str,
        speed: float,
        variants: Optional[List[float]],
        tick_interval: float = 0.0,
        vid_scale: float = 1.0,
    ) -> None: ...
    def _fire_markers(
        self,
        current_file: str,
        effective_elapsed: float,
        prev_eff: float,
        elapsed: float,
        speed: float,
        variants: Optional[List[float]],
        tick_interval: float = 0.0,
        vid_scale: float = 1.0,
    ) -> None: ...
