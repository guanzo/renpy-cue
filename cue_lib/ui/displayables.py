# -*- coding: utf-8 -*-
# Creator-Defined Displayables for the Cue overlay.
# CueSelfUpdatingLabel, CueVideoTimeline, CueVideoMarkerTimeline, CueTooltip, CueMarkerTooltipOverlay.

import pygame
import renpy
from renpy.text.text import Text as Txt
from renpy.display.core import Displayable, IgnoreEvent

from cue_lib.state import _cue
from cue_lib.util import _cue_format_time

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple
    from cue_lib._types import VideoPoolDict


# ---------------------------------------------------------------------------
# Key-capture helpers for the rebindable keybinds system
# ---------------------------------------------------------------------------

# Bare modifier keycodes — these cannot be bound as standalone keys.
_BARE_MOD_NAMES = frozenset({
    "K_LSHIFT", "K_RSHIFT",
    "K_LCTRL", "K_RCTRL",
    "K_LALT", "K_RALT",
    "K_LSUPER", "K_RSUPER",
    "K_LGUI", "K_RGUI",
    "K_LMETA", "K_RMETA",
    "K_MODE",
})

# Modifier ordering for keysym strings (alphabetical — deterministic).


def _cue_build_key_code_map():
    # type: () -> Dict[int, str]
    """Build a {pygame_keycode: "K_xxx"} map from pygame.constants.

    Filters out bare modifier keys (Shift, Ctrl, Alt, Win) because they
    cannot be bound alone.  Non-keypad names are collected first so they
    take priority over keypad aliases for codes that map to the same value.
    """
    code_map = {}  # type: Dict[int, str]
    # Two passes: non-KP first, then KP — so non-KP names win on collision.
    names = [n for n in dir(pygame.constants) if n.startswith("K_")]  # pyright: ignore[reportAttributeAccessIssue]
    non_kp = [n for n in names if not n.startswith("K_KP_")]
    kp = [n for n in names if n.startswith("K_KP_")]
    for name in non_kp + kp:
        if name in _BARE_MOD_NAMES:
            continue
        code = getattr(pygame.constants, name)  # pyright: ignore[reportAttributeAccessIssue]
        code_map[code] = name
    return code_map


_cue_key_code_map = _cue_build_key_code_map()


def _cue_keysym_from_event(ev):
    # type: (Any) -> Optional[str]
    """Reverse-map a pygame KEYDOWN event to a Ren'Py keysym string.

    Returns a string like ``"K_F5"``, ``"shift_K_1"``, or ``"ctrl_alt_K_F9"``,
    or None if the key cannot be mapped (exotic key or bare modifier).
    """
    if ev.type != pygame.KEYDOWN:
        return None

    key_name = _cue_key_code_map.get(ev.key)
    if key_name is None:
        return None

    # Build modifier prefix (consistent ordering for collision detection).
    mod_parts = []
    if ev.mod & pygame.KMOD_ALT:  # pyright: ignore[reportAttributeAccessIssue]
        mod_parts.append("alt")
    if ev.mod & pygame.KMOD_CTRL:  # pyright: ignore[reportAttributeAccessIssue]
        mod_parts.append("ctrl")
    if ev.mod & pygame.KMOD_META:  # pyright: ignore[reportAttributeAccessIssue]
        mod_parts.append("meta")
    if ev.mod & pygame.KMOD_SHIFT:  # pyright: ignore[reportAttributeAccessIssue]
        mod_parts.append("shift")

    # Sort to match canonical order (alt, ctrl, meta, shift).
    mod_parts.sort()

    if mod_parts:
        return "_".join(mod_parts) + "_" + key_name
    return key_name


class CueSelfUpdatingLabel(Displayable):
    """A text label that calls renpy.redraw() to update itself periodically."""

    def __init__(self, getter, style="default", interval=0.05, **properties):
        super(CueSelfUpdatingLabel, self).__init__(style=style, **properties)
        self._text_style = style
        self.getter = getter
        self.interval = interval

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        text = self.getter()
        t = Txt(text, style=self._text_style)
        cr = renpy.render(t, width, height, st, at)
        cw, ch = cr.get_size()
        r = renpy.Render(cw, ch)
        r.blit(cr, (0, 0))
        renpy.redraw(self, self.interval)
        return r


class CueVideoTimeline(Displayable):
    """Video-editor-style timeline bar with a playhead line."""

    BAR_H = 16

    def __init__(self, interval=0.016, **properties):
        super(CueVideoTimeline, self).__init__(**properties)
        self.interval = interval
        self._w = 1
        self._bar_y = 0

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        self._w = width
        r = renpy.Render(width, height)

        vs = _cue.vid_manager
        dur = vs.get_duration()
        elapsed = vs.get_elapsed()
        paused = vs.paused

        hovered = False
        try:
            hovered = self in renpy.get_hovered()
        except Exception:
            pass

        self._bar_y = max(0, (height - self.BAR_H) // 2)
        bar_y = self._bar_y

        bg = "#3a3a3a" if hovered else "#333333"
        canvas = r.canvas()
        canvas.rect(bg, (0, bar_y, width, self.BAR_H))

        if dur > 0 and width > 0:
            frac = max(0.0, min(1.0, elapsed / float(dur)))
            px = int(frac * width)
            px = max(0, min(px, width - 1))
            ph_color = "#ffaa00" if paused else "#ffffff"
            canvas.rect(ph_color, (px, bar_y, 2, self.BAR_H))

        if dur > 0 and _cue.vid_manager.channel:
            mx, my = renpy.get_mouse_pos()
            bx = getattr(_cue, '_vtl_screen_x', -999)
            by = getattr(_cue, '_vtl_screen_y', -999)
            rx, ry = mx - bx, my - by
            if 0 <= rx <= width and bar_y <= ry <= bar_y + self.BAR_H:
                frac = max(0.0, min(1.0, rx / float(max(1, width))))
                t = frac * dur
                tip_text = "Click to seek to: " + _cue_format_time(t)
                tip_widget = Txt(tip_text, style="cue_text", size=11,
                                  color="#cccccc", italic=True, substitute=False)
                tip_render = renpy.render(tip_widget, 300, 100, st, at)
                tw, th = tip_render.get_size()
                fw = min(tw + 8, 300)
                fh = th + 4
                tip = renpy.Render(fw, fh)
                tip.canvas().rect("#2e2e2e", (0, 0, fw, fh))
                tip.blit(tip_render, (4, 2))
                tx = rx + 12
                ty = bar_y - fh - 2
                tx = max(0, min(tx, width - fw))
                r.blit(tip, (tx, ty))

        renpy.redraw(self, self.interval)
        return r

    def event(self, ev, x, y, st):
        # type: (Any, int, int, float) -> Optional[Any]
        if ev.type == pygame.MOUSEMOTION:
            mx, my = renpy.get_mouse_pos()
            _cue._vtl_screen_x = mx - x
            _cue._vtl_screen_y = my - y
            renpy.redraw(self, 0)
            return None
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            bar_y = getattr(self, '_bar_y', 0)
            if bar_y <= y <= bar_y + self.BAR_H:
                vs = _cue.vid_manager
                dur = vs.get_duration()
                if dur > 0 and _cue.vid_manager.channel:
                    w = getattr(self, '_w', 1)
                    if w > 0:
                        frac = max(0.0, min(1.0, x / float(w)))
                        vs.seek_to(frac * dur)
                        renpy.redraw(self, 0)
                        raise IgnoreEvent()
            return None
        return None


class CueVideoMarkerTimeline(Displayable):
    """Timeline with draggable marker tabs."""

    TRACK_H = 10
    TAB_H = 14
    LINE_H = 8
    TAB_W = 14
    DRAG_THRESH = 4
    PAD_X = 10

    SEL_BG = "#446688"
    SEL_LINE = "#5588cc"

    def __init__(self, get_markers, get_active_index, set_active_index, set_time, get_dur, **kw):
        super(CueVideoMarkerTimeline, self).__init__(**kw)
        self.get_markers = get_markers
        self.get_active_index = get_active_index
        self.set_active_index = set_active_index
        self.set_time = set_time
        self.get_dur = get_dur
        self._drag_idx = -1
        self._drag_on = False
        self._drag_start_x = 0
        self._drag_orig_times = {}
        self._drag_group_min = 0.0
        self._drag_group_max = 0.0
        self._tip_text = ""
        self._tip_x = 0
        self._tip_y = 0
        self._hover_idx = -1
        self._screen_x = 0
        self._screen_y = 0

    def _reset_drag_state(self):
        # type: () -> None
        self._drag_orig_times = {}
        self._drag_group_min = 0.0
        self._drag_group_max = 0.0

    def _total_h(self):
        # type: () -> int
        return self.TAB_H + self.TRACK_H + 4

    def _time_to_x(self, t, dur, w):
        # type: (float, float, int) -> int
        if dur <= 0.0:
            if hasattr(self, '_px_cache'):
                return self._px_cache.get(t, self.PAD_X)
            return self.PAD_X
        speed = _cue.speed_resolver.get_current_speed()
        frac = max(0.0, min(1.0, (t / speed) / float(dur)))
        px = self.PAD_X + int(frac * w)
        if not hasattr(self, '_px_cache'):
            self._px_cache = {}
        self._px_cache[t] = px
        return px

    def _x_to_frac(self, x, w):
        # type: (int, int) -> float
        return max(0.0, min(1.0, x / float(max(1, w))))

    def _get_selected(self):
        # type: () -> set
        return _cue.markers.video.get_selected()

    def _hit_test(self, markers, dur, w, x, y):
        # type: (List[VideoPoolDict], float, int, int, int) -> int
        if dur <= 0.0:
            return -1
        speed = _cue.speed_resolver.get_current_speed()
        for i, m in enumerate(markers):
            t = m.get("time", 0.0)
            px = int(((t / speed) / dur) * w)
            bx = px - self.TAB_W // 2
            by = self.TRACK_H - 2
            if bx <= x <= bx + self.TAB_W and by <= y <= by + self.TAB_H:
                return i
        return -1

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        inner_w = max(1, width - 2 * self.PAD_X)
        self._w = inner_w
        r = renpy.Render(width, self._total_h())
        c = r.canvas()
        dur = self.get_dur()
        markers = self.get_markers()
        active = self.get_active_index()
        sel = self._get_selected()
        speed = _cue.speed_resolver.get_current_speed()
        is_scaled = speed != 1.0

        for i, m in enumerate(markers):
            t = m.get("time", 0.0)
            px = self._time_to_x(t, dur, inner_w)
            in_sel = i in sel

            if is_scaled:
                if i == active:
                    lc = "#9966aa"
                    bg = "#664466"
                else:
                    lc = "#775588"
                    bg = "#554455"
            else:
                if i == self._drag_idx and self._drag_on:
                    lc = "#7777cc"
                elif i == active:
                    lc = "#669966"
                elif in_sel:
                    lc = self.SEL_LINE
                else:
                    lc = "#666666"

                if i == self._drag_idx and self._drag_on:
                    bg = "#7777cc"
                elif i == active:
                    bg = "#669966"
                elif in_sel:
                    bg = self.SEL_BG
                elif self._hover_idx == i:
                    bg = "#666666"
                else:
                    bg = "#444444"

            c.rect(lc, (px - 1, 0, 2, self.TRACK_H + self.LINE_H))

            bx_pos = px - self.TAB_W // 2
            by_pos = self.TRACK_H - 2
            c.rect(bg, (bx_pos, by_pos, self.TAB_W, self.TAB_H))

            txt = Txt(str(i + 1), style="cue_button_text", color="#ffffff")
            tr = renpy.render(txt, self.TAB_W, self.TAB_H, st, at)
            tw, _ = tr.get_size()
            r.blit(tr, (bx_pos + (self.TAB_W - tw) // 2, by_pos))

        # Preview marker overlay
        if dur > 0.0:
            preview_times = _cue.repeater.compute_preview_times()
        else:
            preview_times = []
        for ptime in preview_times:
            ppx = self._time_to_x(ptime, dur, inner_w)
            c.rect("#5c7a8c", (ppx - 1, 0, 2, self.TRACK_H + self.LINE_H))
            pbx = ppx - self.TAB_W // 2
            pby = self.TRACK_H - 2
            c.rect("#4a606e", (pbx, pby, self.TAB_W, self.TAB_H))
            ptxt = Txt("?", style="cue_button_text", size=12, color="#ffffff")
            ptr = renpy.render(ptxt, self.TAB_W, self.TAB_H, st, at)
            ptw, _ = ptr.get_size()
            r.blit(ptr, (pbx + (self.TAB_W - ptw) // 2, pby))

        if self._tip_text:
            _cue._marker_tip_text = self._tip_text
            _cue._marker_tip_x = self._screen_x + self._tip_x + 10
            _cue._marker_tip_y = self._screen_y + self._tip_y
        else:
            _cue._marker_tip_text = ""

        renpy.redraw(self, 0.05)
        return r

    def event(self, ev, x, y, st):
        # type: (Any, int, int, float) -> Optional[Any]
        dur = self.get_dur()
        markers = self.get_markers()
        w = getattr(self, '_w', 1)
        inner_x = x - self.PAD_X
        speed = _cue.speed_resolver.get_current_speed()
        is_scaled = speed != 1.0

        if ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            mx, my = renpy.get_mouse_pos()
            self._screen_x = mx - x
            self._screen_y = my - y
        if ev.type == pygame.MOUSEMOTION:
            if not is_scaled and self._drag_idx >= 0:
                if not self._drag_on and abs(inner_x - self._drag_start_x) > self.DRAG_THRESH:
                    self._drag_on = True
                    sel = self._get_selected()
                    valid_sel = [idx for idx in sel if 0 <= idx < len(markers)]
                    if len(valid_sel) > 1 and self._drag_idx in valid_sel:
                        self._drag_orig_times = {
                            idx: markers[idx]["time"] for idx in valid_sel
                        }
                        times = self._drag_orig_times.values()
                        self._drag_group_min = min(times)
                        self._drag_group_max = max(times)
                if self._drag_on:
                    if self._drag_orig_times:
                        current_frac = self._x_to_frac(inner_x, w)
                        start_frac = self._x_to_frac(self._drag_start_x, w)
                        raw_delta = (current_frac - start_frac) * dur
                        max_dur = dur
                        hi_room = max_dur - self._drag_group_max
                        lo_room = 0.0 - self._drag_group_min
                        delta_time = max(lo_room, min(hi_room, raw_delta))
                        for idx, orig_time in self._drag_orig_times.items():
                            self.set_time(idx, orig_time + delta_time)
                        drag_orig = self._drag_orig_times.get(self._drag_idx, 0)
                        cur_time = drag_orig + delta_time
                        self._tip_text = "Pool {} ({}) ({} selected)".format(
                            self._drag_idx + 1, _cue_format_time(cur_time),
                            len(self._drag_orig_times))
                    else:
                        f = self._x_to_frac(inner_x, w)
                        self.set_time(self._drag_idx, f * dur)
                        self._tip_text = "Pool {} ({})".format(
                            self._drag_idx + 1, _cue_format_time(f * dur))
                    self._tip_x = x
                    self._tip_y = y
                renpy.redraw(self, 0)
                raise IgnoreEvent()
            self._hover_idx = -1
            hit_idx = self._hit_test(markers, dur, w, inner_x, y)
            if hit_idx >= 0:
                t = markers[hit_idx].get("time", 0.0)
                sel = self._get_selected()
                if len(sel) > 1 and hit_idx in sel:
                    self._tip_text = "Pool {} ({}) [{} selected]".format(
                        hit_idx + 1, _cue_format_time(t), len(sel))
                else:
                    self._tip_text = "Pool {} ({})".format(
                        hit_idx + 1, _cue_format_time(t))
                    refs = sel if sel else {self.get_active_index()}
                    valid_refs = [s for s in refs if 0 <= s < len(markers)]
                    if hit_idx not in valid_refs and valid_refs:
                        ref_idx = min(valid_refs, key=lambda s: abs(markers[s]["time"] - t))
                        offset = t - markers[ref_idx]["time"]
                        sign = "+" if offset >= 0 else "-"
                        self._tip_text += "\nOffset from Pool {}: {}{}".format(
                            ref_idx + 1, sign, _cue_format_time(abs(offset)))
                if is_scaled:
                    self._tip_text += "\n[Auto-scaled from 1.0x.\nEdit markers on the 1.0x speed.]"
                self._tip_x = x
                self._tip_y = y
                self._hover_idx = hit_idx
                return None
            self._tip_text = ""
            return None

        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if is_scaled:
                return None

            mods = pygame.key.get_mods()
            alt_held = bool(mods & (pygame.KMOD_LALT | pygame.KMOD_RALT))
            shift_held = bool(mods & (pygame.KMOD_LSHIFT | pygame.KMOD_RSHIFT))

            hit_idx = self._hit_test(markers, dur, w, inner_x, y)
            sel = self._get_selected()
            click_frac = self._x_to_frac(inner_x, w)
            click_time = click_frac * dur

            if not (-self.PAD_X <= inner_x < w + self.PAD_X and 0 <= y < self._total_h()):
                return None

            if hit_idx < 0:
                if shift_held and markers:
                    pass
                else:
                    # Plain click on empty timeline: drop the multi-select group.
                    _cue.markers.video.selected = set()
                    renpy.redraw(self, 0)
                    renpy.restart_interaction()
                    raise IgnoreEvent()

            if alt_held and shift_held and hit_idx >= 0:
                # Interval-add: every marker that continues the clicked-to-
                # active spacing joins the selection group (active stays put).
                _cue.markers.video.add_interval_selection(hit_idx)
                renpy.redraw(self, 0)
                renpy.restart_interaction()
                raise IgnoreEvent()

            if alt_held and hit_idx >= 0:
                if not sel:
                    active = self.get_active_index()
                    if active != hit_idx and 0 <= active < len(markers):
                        sel.add(active)
                if hit_idx in sel:
                    sel.discard(hit_idx)
                else:
                    sel.add(hit_idx)
                # The active stays anchored while the group grows.  If the
                # active marker itself was just toggled out, re-anchor to the
                # nearest remaining group member so the panel keeps showing a
                # selected pool.
                if hit_idx == self.get_active_index() and hit_idx not in sel and sel:
                    nearest = min(sel, key=lambda i: abs(markers[i]["time"] - markers[hit_idx]["time"]))
                    self.set_active_index(nearest)
                _cue.markers.video.selected = sel
                renpy.redraw(self, 0)
                renpy.restart_interaction()
                raise IgnoreEvent()

            elif shift_held:
                valid_sel = [si for si in sel if 0 <= si < len(markers)]
                if valid_sel:
                    nearest_idx = min(valid_sel, key=lambda si: abs(markers[si]["time"] - click_time))
                    ref_time = markers[nearest_idx]["time"]
                else:
                    active = self.get_active_index()
                    if not (0 <= active < len(markers)):
                        return None
                    ref_time = markers[active]["time"]
                if hit_idx >= 0:
                    target_time = markers[hit_idx]["time"]
                else:
                    target_time = click_time
                lo = min(target_time, ref_time)
                hi = max(target_time, ref_time)
                for i, m in enumerate(markers):
                    if lo <= m["time"] <= hi:
                        sel.add(i)
                # Active stays the anchor: the reference marker is already
                # in the range, so it must not jump to the leftmost marker.
                _cue.markers.video.selected = sel
                renpy.redraw(self, 0)
                renpy.restart_interaction()
                raise IgnoreEvent()

            elif hit_idx >= 0:
                if hit_idx not in sel:
                    _cue.markers.video.selected = set()
                self._drag_idx = hit_idx
                self._drag_start_x = inner_x
                self._drag_on = False
                self._reset_drag_state()
                self.set_active_index(hit_idx)
                renpy.redraw(self, 0)
                raise IgnoreEvent()

        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self._drag_idx >= 0:
                was_drag = self._drag_on
                clicked_idx = self._drag_idx
                self._drag_idx = -1
                self._drag_on = False
                self._reset_drag_state()
                if was_drag:
                    _cue.markers.video.finalize_drag()
                else:
                    sel = self._get_selected()
                    if len(sel) > 1 and clicked_idx in sel:
                        _cue.markers.video.selected = set()
                renpy.redraw(self, 0)
                renpy.restart_interaction()
                raise IgnoreEvent()
            return None

        return None


class CueTooltip(Displayable):
    """Hover tooltip that auto-sizes to fit text."""

    def __init__(self, text, **properties):
        super(CueTooltip, self).__init__(**properties)
        self._text = text

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        text_widget = Txt(
            self._text, style="cue_text", size=12, color="#cccccc",
            italic=False, substitute=False,
        )
        max_width = 350
        text_render = renpy.render(text_widget, max_width, 100, st, at)
        tw, th = text_render.get_size()

        pad_x, pad_y = 4, 2
        fw = tw + pad_x * 2
        fh = th + pad_y * 2

        sw = renpy.config.screen_width
        sh = renpy.config.screen_height

        fx, fy, fw_elem, fh_elem = renpy.focus_coordinates()
        if fx is not None and fy is not None and fw_elem is not None and fh_elem is not None:
            # Anchor to the hovered element (not the cursor) so the tooltip
            # never covers it: centered above, flipping below when there's
            # no room above.
            tx = fx + (fw_elem - fw) // 2
            ty = fy - fh - 4
            if ty < 0:
                ty = fy + fh_elem + 4

            # Clamp to keep the tooltip fully on screen
            if tx + fw > sw:
                tx = sw - fw
            if ty + fh > sh:
                ty = sh - fh
            if tx < 0:
                tx = 0
            if ty < 0:
                ty = 0
        else:
            # Fallback (nothing focused): right and slightly above the cursor.
            mx, my = renpy.get_mouse_pos()
            tx = mx + 12
            ty = my - 8

            if tx + fw > sw:
                tx = mx - fw - 12  # flip to left of cursor
            if ty + fh > sh:
                ty = sh - fh
            if tx < 0:
                tx = 0
            if ty < 0:
                ty = 0

        r = renpy.Render(1, 1)
        tip = renpy.Render(fw, fh)
        tip.canvas().rect("#2e2e2e", (0, 0, fw, fh))
        tip.blit(text_render, (pad_x, pad_y))
        r.blit(tip, (tx, ty))
        return r


class CueMarkerTooltipOverlay(Displayable):
    """Renders the marker timeline tooltip on top of all other UI."""

    def __init__(self, **properties):
        super(CueMarkerTooltipOverlay, self).__init__(**properties)

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        renpy.redraw(self, 0.05)
        text = getattr(_cue, '_marker_tip_text', None) or ""
        if not text:
            return renpy.Render(1, 1)

        tip_widget = Txt(text, style="cue_text", size=12,
                          color="#cccccc", italic=False, substitute=False)
        tip_render = renpy.render(tip_widget, 300, 100, st, at)
        tw, th = tip_render.get_size()
        fw = min(tw + 8, 300)
        fh = th + 4

        tip = renpy.Render(fw, fh)
        tip.canvas().rect("#2e2e2e", (0, 0, fw, fh))
        tip.blit(tip_render, (4, 2))

        tx = getattr(_cue, '_marker_tip_x', 0)
        ty = getattr(_cue, '_marker_tip_y', 0)

        r = renpy.Render(1, 1)
        r.blit(tip, (tx, ty))
        return r


class CueAutoSpeedChart(Displayable):
    """Line chart that visualizes a speed sequence with a progress dot.

    Draws a polyline across all speed steps.  The played portion is
    bright, the remaining portion dim.  A filled dot marks the current
    position.  Y-axis labels show min / max speed; the current speed
    label tracks the progress dot.

    Usage in screen:  add CueAutoSpeedChart()  -- reads from _cue directly."""

    PAD_LEFT = 35
    PAD_RIGHT = 8
    PAD_TOP = 8
    PAD_BOTTOM = 18
    DOT_R = 4
    LINE_W = 2

    COLOR_DIM = "#3a3a3a"
    COLOR_BRIGHT = "#ffffff"
    COLOR_DOT = "#ffaa00"

    def __init__(self, interval=0.1, **properties):
        # type: (float, **Any) -> None
        super(CueAutoSpeedChart, self).__init__(**properties)
        self.interval = interval

    @staticmethod
    def _compute_points(speeds, width, height):
        # type: (List[float], int, int) -> Tuple[List[Tuple[int, int]], float, float]
        """Map speed values to (x, y) pixel coordinates.
        Returns (points, sp_min, sp_max)."""
        n = len(speeds)
        if n < 2:
            return ([], 0.0, 0.0)
        sp_min = min(speeds)
        sp_max = max(speeds)
        sp_range = sp_max - sp_min if sp_max > sp_min else 1.0
        w = width - CueAutoSpeedChart.PAD_LEFT - CueAutoSpeedChart.PAD_RIGHT
        h = height - CueAutoSpeedChart.PAD_TOP - CueAutoSpeedChart.PAD_BOTTOM
        points = []
        for i, sp in enumerate(speeds):
            x = CueAutoSpeedChart.PAD_LEFT + int((float(i) / max(1, n - 1)) * w)
            y = CueAutoSpeedChart.PAD_TOP + int((1.0 - (sp - sp_min) / sp_range) * h)
            points.append((x, y))
        return points, sp_min, sp_max

    def visit(self):
        # type: () -> List[Displayable]
        return []

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        r = renpy.Render(width, height)

        if width < 60 or height < 30:
            renpy.redraw(self, self.interval)
            return r

        tag = _cue.current_file
        speeds = None
        if tag and _cue.video_sequence:
            speeds = _cue.video_sequence.speeds_for(tag)

        if not speeds or len(speeds) < 2:
            renpy.redraw(self, self.interval)
            return r

        current_idx = _cue.video_sequence.current_step_index()
        points, sp_min, sp_max = self._compute_points(speeds, width, height)
        if len(points) < 2:
            renpy.redraw(self, self.interval)
            return r

        canvas = r.canvas()

        # --- Dim line: full sequence ---
        for i in range(len(points) - 1):
            canvas.line(self.COLOR_DIM, points[i], points[i + 1], self.LINE_W)

        # --- Bright line: played portion ---
        if current_idx > 0:
            for i in range(min(current_idx, len(points) - 1)):
                canvas.line(self.COLOR_BRIGHT, points[i], points[i + 1], self.LINE_W)

        # --- Progress dot ---
        cx = cy = 0
        if 0 <= current_idx < len(points):
            cx, cy = points[current_idx]
            canvas.circle(self.COLOR_DOT, (cx, cy), self.DOT_R)

        # --- Y-axis labels (min at bottom, max at top) ---
        by_top = min(py for _, py in points)
        by_bot = max(py for _, py in points)
        def _fmt(sp):
            return "{:.1f}x".format(sp)

        y_style = dict(style="cue_text", size=12, color="#888888",
                       italic=False, substitute=False)
        max_w = Txt(_fmt(sp_max), **y_style)
        max_r = renpy.render(max_w, 60, 16, st, at)
        # Top of the label aligns with the top of the y-axis.
        r.blit(max_r, (2, by_top - 10))
        min_w = Txt(_fmt(sp_min), **y_style)
        min_r = renpy.render(min_w, 60, 16, st, at)
        # Bottom of the label sits on the x-axis line.
        r.blit(min_r, (2, by_bot - 16))

        # --- Current speed below the dot ---
        if 0 <= current_idx < len(speeds):
            cur_sp = speeds[current_idx]
            cur_w = Txt(_fmt(cur_sp), style="cue_text", size=12,
                        color="#ffaa00", italic=False, substitute=False)
            cur_r = renpy.render(cur_w, 60, 16, st, at)
            cw, _ch = cur_r.get_size()
            r.blit(cur_r, (cx - cw // 2, height - 14))

        # --- Hover tooltip ---
        try:
            mx, my = renpy.get_mouse_pos()
            bx = getattr(_cue, '_chart_screen_x', -9999)
            by_ = getattr(_cue, '_chart_screen_y', -9999)
            rx, ry = mx - bx, my - by_
            # Only show tooltip when the mouse is inside the chart.
            if 0 <= rx <= width and 0 <= ry <= height:
                nearest_idx = -1
                nearest_dist = 9999
                for i, (px, py) in enumerate(points):
                    dist = abs(rx - px)
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_idx = i
            else:
                nearest_idx = -1
            if nearest_idx >= 0:
                sp = speeds[nearest_idx]
                tip_text = "{:.1f}x  step {}/{}".format(sp, nearest_idx + 1, len(speeds))
                tip_widget = Txt(tip_text, style="cue_text", size=10,
                                  color="#cccccc", italic=False, substitute=False)
                tip_render = renpy.render(tip_widget, 200, 50, st, at)
                tw, th = tip_render.get_size()
                fw = min(tw + 8, 200)
                fh = th + 4
                tip = renpy.Render(fw, fh)
                tip.canvas().rect("#2e2e2e", (0, 0, fw, fh))
                tip.blit(tip_render, (4, 2))
                px, py = points[nearest_idx]
                tx = px + 12
                ty = py - fh - 4
                tx = max(0, min(tx, width - fw))
                ty = max(0, ty)
                r.blit(tip, (tx, ty))
        except Exception:
            pass

        renpy.redraw(self, self.interval)
        return r

    def event(self, ev, x, y, st):
        # type: (Any, int, int, float) -> Optional[Any]
        if ev.type == pygame.MOUSEMOTION:
            mx, my = renpy.get_mouse_pos()
            _cue._chart_screen_x = mx - x
            _cue._chart_screen_y = my - y
            renpy.redraw(self, 0)
        return None


class CueKeyCaptureDisplayable(Displayable):
    """Invisible displayable that captures the next KEYDOWN event.

    Used by the keybind-capture modal to intercept key presses during
    rebinding.  Renders nothing (0x0) — it only exists to receive events.
    Keyboard events are not hit-tested, so a zero-size render still works.

    On KEYDOWN it calls :func:`_cue_keysym_from_event` and forwards the
    resulting keysym to :meth:`CueKeybindsManager.on_captured`.
    """

    def __init__(self, **properties):
        super(CueKeyCaptureDisplayable, self).__init__(**properties)

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        return renpy.Render(0, 0)

    def event(self, ev, x, y, st):
        # type: (Any, int, int, float) -> Optional[Any]
        if ev.type == pygame.KEYDOWN:
            keysym = _cue_keysym_from_event(ev)
            if keysym is not None and _cue.keybinds is not None:
                _cue.keybinds.on_captured(keysym)
            raise IgnoreEvent()
        return None
