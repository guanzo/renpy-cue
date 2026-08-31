from typing import Any, Optional

class Button:
    def __init__(self, action: Any = None, **properties: Any) -> None: ...
    def add(self, child: Any) -> None: ...

class Adjustment:
    def __init__(
        self,
        range: float = 1,
        value: float = 0,
        step: Optional[float] = None,
        page: Optional[float] = None,
        changed: Any = None,
        adjustable: Optional[bool] = None,
        ranged: Any = None,
        force_step: bool = False,
        raw_changed: Any = None,
    ) -> None: ...
