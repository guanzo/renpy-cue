# Type stub for cue_lib.trigger.context
from typing import Optional

from cue_lib.trigger.engine import CueTriggerEngine

class CueContextTrigger:
    def __init__(self, engine: CueTriggerEngine) -> None: ...
    def fire(self, key: Optional[str], only_shake_pools: bool = False) -> None: ...
