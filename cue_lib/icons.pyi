# Type stub for cue_lib.icons
from typing import Any, Dict, Optional

class CueIconManager:
    _displayables: Dict[str, Any]

    def __init__(self) -> None: ...
    def displayable_for(self, glyph: str) -> Optional[Any]: ...
