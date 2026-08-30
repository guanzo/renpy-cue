# cue_lib/ui/components/select/select.py -- generic floating dropdown.

# A CueSelect is the manager a cue_select_input/dropdown pair render from.  It
# owns the open/close state, the selection, and the dropdown's on-screen
# geometry.  The dropdown floats below its trigger (via cue_overlay) so opening
# it never shifts the page layout.  Reusable for any option list: the cast
# filter (replays.py) is one consumer.

import renpy.python as _renpy_python

from cue_lib.state import _cue
from cue_lib.ui.displayables import _cue_scale_ui

# Dropdown metrics for the cue_select component.  OPTION_H and OPTION_GAP size
# the option rows, so they must stay in sync with the cue_select_option style's
# ysize and the dropdown vbox spacing; FRAME_PAD is the frame's vertical padding
# (4+4); MAX_H caps the list before it scrolls.
CUE_SELECT_OPTION_H = 18
CUE_SELECT_OPTION_GAP = 1
CUE_SELECT_FRAME_PAD = 8
CUE_SELECT_MAX_H = 240

MYPY = False
if MYPY:
    from typing import Any, List, Optional, Set, Tuple


class CueSelect(_renpy_python.NoRollback):
    """Generic multi-select dropdown.

    Subclasses override options()/label() (and toggle()/selected_keys() when
    selection is not a plain set).  The dropdown height is computed from the
    option count and the fixed CUE_SELECT_OPTION_H row height, so the click-
    outside rect spans the trigger plus exactly the rendered list -- a short
    list has no dead zone below it.
    """

    def __init__(self):
        # type: () -> None
        self.selected = set()  # type: Set[Any]
        # On-screen rect of the trigger at open time, so the floating dropdown
        # can anchor itself below it without shifting the page layout.
        self._trigger_rect = None  # type: Optional[Tuple[int, int, int, int]]

    # --- selection ---

    def toggle(self, key):
        # type: (Any) -> None
        """Add or remove an option from the selection."""
        if key in self.selected:
            self.selected.discard(key)
        else:
            self.selected.add(key)

    def clear(self):
        # type: () -> None
        self.selected.clear()

    def selected_keys(self):
        # type: () -> List[Any]
        """Selected option keys, sorted, for the trigger's chips."""
        return sorted(self.selected)

    def is_selected(self, key):
        # type: (Any) -> bool
        return key in self.selected

    def select(self, key):
        # type: (Any) -> None
        """Option click: flip the selection, then close the dropdown."""
        self.toggle(key)
        self.close()

    # --- options (subclasses override) ---

    def options(self):
        # type: () -> List[Any]
        """Option keys, in display order."""
        return []

    def label(self, key):
        # type: (Any) -> str
        """Display text for an option key."""
        return key

    # --- open / close ---

    def is_open(self):
        # type: () -> bool
        return _cue.overlay.active_dropdown is self

    def toggle_open(self):
        # type: () -> None
        if self.is_open():
            self.close()
        else:
            self.open()

    def open(self):
        # type: () -> None
        r = _cue.overlay.active_input_rect
        # pyright doesn't pair select.py with select.pyi while analyzing the
        # .py itself (CLAUDE.md), so Self@CueSelect and the .pyi's CueSelect
        # are distinct nominal types to it.
        _cue.overlay.active_dropdown = self  # pyright: ignore[reportAttributeAccessIssue]
        # The pin captures focus rects as floats; screen xpos/ypos/xsize treat
        # floats as fractions of the parent, so the anchor must be ints or the
        # floating dropdown lands off-screen.
        self._trigger_rect = (int(r[0]), int(r[1]), int(r[2]), int(r[3])) if r is not None else None

    def close(self):
        # type: () -> None
        _cue.overlay.active_dropdown = None
        self._trigger_rect = None

    # --- geometry ---

    def trigger_rect(self):
        # type: () -> Optional[Tuple[int, int, int, int]]
        """The trigger's on-screen rect captured when the dropdown opened."""
        return self._trigger_rect

    def _content_h(self):
        # type: () -> int
        """Unscaled height of the option rows (fixed row height, capped)."""
        n = len(self.options())
        return min(n * CUE_SELECT_OPTION_H + max(n - 1, 0) * CUE_SELECT_OPTION_GAP, CUE_SELECT_MAX_H)

    def viewport_h(self):
        # type: () -> int
        """Scaled height of the scroll area (grow_and_scroll ymin/ymax)."""
        return _cue_scale_ui(self._content_h())

    def frame_h(self):
        # type: () -> int
        """Scaled height of the whole list, frame padding included."""
        return self.viewport_h() + _cue_scale_ui(CUE_SELECT_FRAME_PAD)

    def rect(self):
        # type: () -> Optional[Tuple[int, int, int, int]]
        """The keep-open box: trigger plus the open list."""
        r = self._trigger_rect
        if r is None:
            return None
        return (r[0], r[1], r[2], r[3] + self.frame_h())

    def is_inside(self, x, y):
        # type: (float, float) -> bool
        """True when (x, y) is over the trigger or the open list."""
        r = self.rect()
        return r is not None and (r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3])
