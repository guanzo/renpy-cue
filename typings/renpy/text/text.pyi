from typing import Any, Optional
from renpy.display.core import Displayable

class Text(Displayable):
    def __init__(self, text: str, style: Any = None, **properties: Any) -> None: ...
