# -*- coding: utf-8 -*-
# CuePopper -- Reusable positioned popup for Ren'Py.
# Focus rect helpers and the CuePopper displayable class.
# The sl-displayable registration stays in cue_z.rpy (python early).

import renpy
from renpy.store import NullAction
from renpy.display.layout import Container

from cue_lib.state import _cue

MYPY = False
if MYPY:
    from typing import Any, Optional, Tuple


# --- Focus rect helpers (version-adaptive) ---

def _cue_store_focus_rect(name):
    # type: (str) -> None
    _v = getattr(renpy, 'version_tuple', (0, 0, 0))
    if _v >= (8, 0, 0):
        before = renpy.focus_coordinates()
        renpy.capture_focus(name)
        after = renpy.get_focus_rect(name)
    else:
        rect = renpy.focus_coordinates()
        anchors = getattr(_cue, '_popper_anchors', None)
        if anchors is None:
            _cue._popper_anchors = {}
            anchors = _cue._popper_anchors
        if rect[0] is not None:
            anchors[name] = rect
        else:
            anchors.pop(name, None)

def _cue_clear_focus_rect(name):
    # type: (str) -> None
    _v = getattr(renpy, 'version_tuple', (0, 0, 0))
    if _v >= (8, 0, 0):
        renpy.clear_capture_focus(name)
    else:
        anchors = getattr(_cue, '_popper_anchors', None)
        if anchors is not None:
            anchors.pop(name, None)

def _cue_get_focus_rect(name):
    # type: (str) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]
    _v = getattr(renpy, 'version_tuple', (0, 0, 0))
    if _v >= (8, 0, 0):
        rect = renpy.get_focus_rect(name)
        if rect is not None:
            return rect
        return (None, None, None, None)
    else:
        anchors = getattr(_cue, '_popper_anchors', None)
        if anchors is None:
            return (None, None, None, None)
        return anchors.get(name, (None, None, None, None))


# --- Placement algorithm ---

def _cue_compute_popup_position(ax, ay, aw, ah, cw, ch, vw, vh,
                                placement, offset, margin):
    # type: (int, int, int, int, int, int, int, int, str, int, int) -> Tuple[int, int, str]
    if placement == "top":
        x = ax + (aw - cw) // 2
        y = ay - ch - offset
        if y < margin:
            y = ay + ah + offset
            arrow_dir = "up"
        else:
            arrow_dir = "down"
    elif placement == "bottom":
        x = ax + (aw - cw) // 2
        y = ay + ah + offset
        if y + ch > vh - margin:
            y = ay - ch - offset
            arrow_dir = "down"
        else:
            arrow_dir = "up"
    elif placement == "left":
        x = ax - cw - offset
        y = ay + (ah - ch) // 2
        if x < margin:
            x = ax + aw + offset
            arrow_dir = "left"
        else:
            arrow_dir = "right"
    elif placement == "right":
        x = ax + aw + offset
        y = ay + (ah - ch) // 2
        if x + cw > vw - margin:
            x = ax - cw - offset
            arrow_dir = "right"
        else:
            arrow_dir = "left"
    else:
        x = ax + (aw - cw) // 2
        y = ay - ch - offset
        arrow_dir = "down"

    x = max(margin, min(x, vw - cw - margin))
    y = max(margin, min(y, vh - ch - margin))
    return int(x), int(y), arrow_dir


# --- Arrow drawing ---

ARROW_SZ = 6

def _cue_draw_arrow(r, px, py, pw, ph, arrow_dir):
    # type: (Any, int, int, int, int, str) -> None
    cx, cy = px + pw // 2, py + ph // 2
    color = "#000000ee"
    if arrow_dir == "down":
        pts = [(cx - ARROW_SZ, py + ph), (cx, py + ph + ARROW_SZ), (cx + ARROW_SZ, py + ph)]
    elif arrow_dir == "up":
        pts = [(cx - ARROW_SZ, py), (cx, py - ARROW_SZ), (cx + ARROW_SZ, py)]
    elif arrow_dir == "right":
        pts = [(px + pw, cy - ARROW_SZ), (px + pw + ARROW_SZ, cy), (px + pw, cy + ARROW_SZ)]
    else:  # left
        pts = [(px, cy - ARROW_SZ), (px - ARROW_SZ, cy), (px, cy + ARROW_SZ)]
    r.canvas().polygon(color, pts)


# --- CuePopper displayable ---

class CuePopper(Container):
    HIDE_DELAY = 0.1
    MAX_POPUP_W = 400
    MAX_POPUP_H = 300

    def __init__(self, target, placement="top", offset=5,
                 viewport_margin=8, **kwargs):
        super(CuePopper, self).__init__(**kwargs)
        self.target = target
        self.placement = placement
        self.offset = offset
        self.viewport_margin = viewport_margin
        self._hide_st = None
        self._stored_rect = None
        self._frame = 0

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        self._frame += 1
        r = renpy.Render(width, height)

        if not self.children:
            self.offsets = [(0, 0)]
            return renpy.Render(1, 1)

        rect = _cue_get_focus_rect(self.target)
        if rect[0] is not None:
            self._stored_rect = rect
        else:
            self._stored_rect = None

        if self._stored_rect is None:
            self._hide_st = None
            self.offsets = [(0, 0)]
            renpy.redraw(self, 0)
            return renpy.Render(1, 1)

        ax, ay, aw, ah = self._stored_rect
        # _stored_rect is only ever set when the focus rect is fully
        # populated (all elements non-None) -- see the guard above.
        assert ax is not None and ay is not None and aw is not None and ah is not None

        child = self.children[0]
        measure_w = min(width, self.MAX_POPUP_W)
        measure_h = min(height, self.MAX_POPUP_H)
        child_render = renpy.render(child, measure_w, measure_h, st, at)
        cw, ch = child_render.get_size()

        vw = renpy.config.screen_width
        vh = renpy.config.screen_height

        x, y, arrow_dir = _cue_compute_popup_position(
            ax, ay, aw, ah, cw, ch,
            vw, vh,
            self.placement, self.offset, self.viewport_margin,
        )

        _cue_draw_arrow(r, x, y, cw, ch, arrow_dir)

        mx, my = renpy.get_mouse_pos()
        in_anchor = (ax <= mx <= ax + aw and ay <= my <= ay + ah)
        in_popup = (x <= mx <= x + cw and y <= my <= y + ch)

        if in_anchor or in_popup:
            self._hide_st = None
        elif self._hide_st is None:
            self._hide_st = st + self.HIDE_DELAY

        if self._hide_st is not None and st >= self._hide_st:
            _cue_clear_focus_rect(self.target)
            self._stored_rect = None
            self._hide_st = None
            renpy.redraw(self, 0)
            return r

        r.blit(child_render, (x, y))
        renpy.redraw(self, 0)
        return r

    def add(self, child):
        # type: (Any) -> None
        from renpy.display.behavior import Button
        from renpy.display.layout import Window

        frame = Window(style="cue_popper_frame")
        frame.add(child)

        btn = Button(action=NullAction(), padding=(0, 0))
        btn.add(frame)
        super(CuePopper, self).add(btn)

    def visit(self):
        # type: () -> list
        return list(self.children)
