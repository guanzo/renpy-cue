# Type stub for cue_lib.trigger.loop
from typing import Any, Dict, List, Optional

from cue_lib.trigger.engine import CueTriggerEngine

class CueLoopTrigger:
    loop_states: Dict[str, Any]

    def __init__(self, engine: CueTriggerEngine) -> None: ...
    def reset(self) -> None: ...
    def _loop_delay(self, frequency: int, freq_mult: Optional[float]) -> float: ...
    def tick(
        self,
        now: float,
        tick: int,
        current_file: str,
        speed: float,
        variants: Optional[List[float]],
        vid_scale: float = 1.0,
    ) -> None: ...
