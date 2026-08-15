# Type stub for cue_lib.ui.icons
from typing import Any, Dict, Optional, Tuple

from cue_lib.paths import CuePaths

class CueIconManager:
    _displayables: Dict[Tuple[str, Optional[str], int], Any]

    def __init__(self, paths: CuePaths) -> None: ...
    def displayable_for(self, name: str, color: Optional[str] = None, size: Optional[int] = None) -> Optional[Any]: ...
