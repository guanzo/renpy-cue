# Type stub for cue_lib.ui.icons
from typing import Any, Dict, Optional, Tuple

class CueIconManager:
    _displayables: Dict[Tuple[str, Optional[str]], Any]

    def __init__(self) -> None: ...
    def displayable_for(self, name: str, color: Optional[str] = None) -> Optional[Any]: ...
