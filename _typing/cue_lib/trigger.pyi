# Type stub for cue_lib.trigger
from typing import Any, Dict, List, Optional, Set

class CueTriggerEngine:
    active: bool
    loop_states: Dict[str, Any]
    loop_current: Optional[Dict[str, Any]]
    last_played: List[str]
    played_video_keys: Set[str]

    def __init__(self) -> None: ...
    def tick(self, current_file: str, top_layer_type: str) -> None: ...
    def fire_context(self, *keys: str, **kwargs: Any) -> None: ...
