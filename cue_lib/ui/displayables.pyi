# Type stub for cue_lib.ui.displayables
from typing import Any, Callable, List, Optional
from renpy.display.core import Displayable

from cue_lib._types import VideoPoolDict

class SelfUpdatingLabel(Displayable):
    def __init__(
        self,
        getter: Callable[[], str],
        style: str = "default",
        interval: float = 0.05,
        **properties: Any) -> None: ...
    def render(self, width: int, height: int, st: float, at: float) -> Any: ...

class VideoTimeline(Displayable):
    BAR_H: int
    def __init__(self, interval: float = 0.016, **properties: Any) -> None: ...
    def render(self, width: int, height: int, st: float, at: float) -> Any: ...
    def event(self, ev: Any, x: int, y: int, st: float) -> Optional[Any]: ...

class CueVideoMarkerTimeline(Displayable):
    TRACK_H: int
    TAB_H: int
    LINE_H: int
    TAB_W: int
    DRAG_THRESH: int
    PAD_X: int
    SEL_BG: str
    SEL_LINE: str

    def __init__(
        self,
        get_markers: Callable[[], List[VideoPoolDict]],
        get_active_index: Callable[[], int],
        set_active_index: Callable[[int], None],
        set_time: Callable[[int, float], None],
        get_dur: Callable[[], float],
        **properties: Any) -> None: ...
    def render(self, width: int, height: int, st: float, at: float) -> Any: ...
    def event(self, ev: Any, x: int, y: int, st: float) -> Optional[Any]: ...

class CueTooltip(Displayable):
    def __init__(self, text: str, **properties: Any) -> None: ...
    def render(self, width: int, height: int, st: float, at: float) -> Any: ...

class CueVideoMarkerTooltip(Displayable):
    def __init__(self, **properties: Any) -> None: ...
    def render(self, width: int, height: int, st: float, at: float) -> Any: ...
