# Type stub for cue_lib.replays
from typing import Any, Dict, List, Optional, Tuple

from cue_lib.paths import CuePaths

def _cue_replay_labels(root: str, game_id: str) -> List[Tuple[str, int]]: ...

class CueReplayLibrary:
    def __init__(self, paths: CuePaths) -> None: ...
    def scan(self) -> None: ...
    def play(self, label: str) -> None: ...

    entries: List[Dict[str, Any]]
    pending_replay: Optional[str]
