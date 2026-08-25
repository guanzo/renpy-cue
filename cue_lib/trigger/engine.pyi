# Type stub for cue_lib.trigger.engine
from typing import Any, List, Optional

from cue_lib.trigger.context import CueContextTrigger
from cue_lib.trigger.exclusive import CueExclusiveRegistry
from cue_lib.trigger.loop import CueLoopTrigger
from cue_lib.trigger.trigger_debug import CueTriggerDebug
from cue_lib.trigger.video import CueVideoTrigger

class CueTriggerEngine:
    _store: Any
    _repeater: Any
    _speed_resolver: Any
    _vid_manager: Any
    _markers: Optional[Any]
    active: bool
    last_played: List[Any]
    _tick_count: int
    _last_tick_wall: float
    _vid_intensity: Optional[Any]
    excl: CueExclusiveRegistry
    _debug: CueTriggerDebug
    context: CueContextTrigger
    loop: CueLoopTrigger
    video: CueVideoTrigger

    def __init__(
        self, store: Any, repeater: Any, speed_resolver: Any, vid_manager: Any, markers: Optional[Any] = None
    ) -> None: ...
    def _markers_ctx(self) -> Any: ...
    def toggle_active(self) -> None: ...
    def reset(self) -> None: ...
    def tick(self, current_file: str, top_layer_type: str) -> None: ...
    def fire_context(self, key: Optional[str], only_shake_pools: bool = False) -> None: ...
