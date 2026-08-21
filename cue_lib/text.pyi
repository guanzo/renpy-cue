# Type stub for cue_lib.text
from typing import Any, Dict

from renpy.text.text import Text


class CueSafeText(Text):
    def __init__(self, text: Any, **kwargs: Dict[str, Any]) -> None: ...
