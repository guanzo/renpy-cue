from typing import Any, Optional

class Movie:
    play: Any
    channel: Optional[str]
    loop: bool
    size: Optional[Any]
    def __init__(self, **properties: Any) -> None: ...
