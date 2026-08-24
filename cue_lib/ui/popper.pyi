# Type stub for cue_lib.ui.popper
from typing import Any, Final, Optional, Tuple
from renpy.display.layout import Container

ARROW_SZ: int
CUE_POPPER_DEFAULT_OFFSET: Final = 5
CUE_POPPER_DEFAULT_MARGIN: Final = 8

# Focus rect helpers
def _cue_store_focus_rect(name: str) -> None: ...
def _cue_clear_focus_rect(name: str) -> None: ...
def _cue_get_focus_rect(name: str) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]: ...

# Placement
def _cue_compute_popup_position(
    ax: int, ay: int, aw: int, ah: int, cw: int, ch: int, vw: int, vh: int, placement: str, offset: int, margin: int
) -> Tuple[int, int, str]: ...

# Arrow drawing
def _cue_draw_arrow(r: Any, px: int, py: int, pw: int, ph: int, arrow_dir: str) -> None: ...

# CuePopper displayable
class CuePopper(Container):
    HIDE_DELAY: float
    MAX_POPUP_W: int
    MAX_POPUP_H: int

    def __init__(
        self,
        target: str,
        placement: str = "top",
        offset: int = CUE_POPPER_DEFAULT_OFFSET,
        viewport_margin: int = CUE_POPPER_DEFAULT_MARGIN,
        **kwargs: Any,
    ) -> None: ...
    def render(self, width: int, height: int, st: float, at: float) -> Any: ...
    def add(self, child: Any) -> None: ...
    def visit(self) -> list: ...
