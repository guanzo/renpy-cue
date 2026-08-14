# Type stub for cue_lib.ui.icons
from typing import Any, Dict, Optional

class CueIconManager:
    _displayables: Dict[str, Any]

    def __init__(self) -> None: ...
    def displayable_for(self, name: str) -> Optional[Any]: ...
