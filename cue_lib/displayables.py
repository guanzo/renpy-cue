# -*- coding: utf-8 -*-
# Creator-Defined Displayables for the Cue overlay.
# SelfUpdatingLabel, VideoTimeline, CueVideoMarkerTimeline, _Tooltip, _MarkerTooltipOverlay.

import pygame
import renpy
from renpy.text.text import Text as Txt
from renpy.display.core import Displayable, IgnoreEvent

from cue_lib.state import _cue
from cue_lib.util import _cue_format_time

MYPY = False
if MYPY:
    from typing import Any, List, Optional
    from cue_lib._types import VideoPoolDict


class SelfUpdatingLabel(Displayable):
    """A text label that calls renpy.redraw() to update itself periodically."""

    def __init__(self, getter, style="default", interval=0.05, **properties):
        super(SelfUpdatingLabel, self).__init__(style=style, **properties)
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


class VideoTimeline(Displayable):
    """Video-editor-style timeline bar with a playhead line."""

    BAR_H = 16

    def __init__(self, interval=0.016, **properties):
        super(VideoTimeline, self).__init__(**properties)
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
                tip_widget = Txt(tip_text, style="cue_txt", size=11,
                                  color="#cccccc", italic=True, substitute=False)
                tip_render = renpy.render(tip_widget, 300, 100, st, at)
                tw, th = tip_render.get_size()
                fw = min(tw + 8, 300)
                fh = th + 4
                tip = renpy.Render(fw, fh)
                tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
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
    TAB_H = 16
    LINE_H = 8
    TAB_W = 14
    DRAG_THRESH = 4
    PAD_X = 10

    SEL_BG = "#446688"
    SEL_LINE = "#5588cc"

    def __init__(self, get_markers, get_active, set_active, set_time, get_dur, **kw):
        super(CueVideoMarkerTimeline, self).__init__(**kw)
        self.get_markers = get_markers
        self.get_active = get_active
        self.set_active = set_active
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
        active = self.get_active()
        sel = self._get_selected()
        multi_active = len(sel) > 1
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
                elif i == active and multi_active:
                    lc = "#5599cc"
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

            txt = Txt(str(i + 1), style="cue_btn_text", size=12, color="#ffffff")
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
            ptxt = Txt("?", style="cue_btn_text", size=12, color="#ffffff")
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
                    if len(sel) > 1 and self._drag_idx in sel:
                        self._drag_orig_times = {
                            idx: markers[idx]["time"] for idx in sel
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
                    refs = sel if sel else {self.get_active()}
                    if hit_idx not in refs:
                        ref_idx = min(refs, key=lambda s: abs(markers[s]["time"] - t))
                        offset = t - markers[ref_idx]["time"]
                        sign = "+" if offset >= 0 else "-"
                        self._tip_text += "\nOffset from Pool {}: {}{}".format(
                            ref_idx + 1, sign, _cue_format_time(abs(offset)))
                if is_scaled:
                    self._tip_text += "\n[auto-scaled from 1.0x, locked]"
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
                    _cue.markers.video.selected = set()
                    return None

            if alt_held and hit_idx >= 0:
                if not sel:
                    active = self.get_active()
                    if active != hit_idx and 0 <= active < len(markers):
                        sel.add(active)
                if hit_idx in sel:
                    sel.discard(hit_idx)
                else:
                    sel.add(hit_idx)
                if sel:
                    self.set_active(min(sel))
                _cue.markers.video.selected = sel
                renpy.redraw(self, 0)
                renpy.restart_interaction()
                raise IgnoreEvent()

            elif shift_held:
                if sel:
                    nearest_idx = min(sel, key=lambda si: abs(markers[si]["time"] - click_time))
                    ref_time = markers[nearest_idx]["time"]
                else:
                    ref_time = markers[self.get_active()]["time"]
                if hit_idx >= 0:
                    target_time = markers[hit_idx]["time"]
                else:
                    target_time = click_time
                lo = min(target_time, ref_time)
                hi = max(target_time, ref_time)
                for i, m in enumerate(markers):
                    if lo <= m["time"] <= hi:
                        sel.add(i)
                if sel:
                    self.set_active(min(sel))
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
                self.set_active(hit_idx)
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


class _Tooltip(Displayable):
    """Hover tooltip that auto-sizes to fit text."""

    def __init__(self, text, **properties):
        super(_Tooltip, self).__init__(**properties)
        self._text = text

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        text_widget = Txt(
            self._text, style="cue_txt", size=12, color="#cccccc",
            italic=False, substitute=False,
        )
        text_render = renpy.render(text_widget, 300, 100, st, at)
        tw, th = text_render.get_size()

        pad_x, pad_y = 4, 2
        fw = tw + pad_x * 2
        fh = th + pad_y * 2

        mx, my = renpy.get_mouse_pos()

        r = renpy.Render(1, 1)
        tip = renpy.Render(fw, fh)
        tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
        tip.blit(text_render, (pad_x, pad_y))
        r.blit(tip, (mx + 12, my - 8))
        return r


class _MarkerTooltipOverlay(Displayable):
    """Renders the marker timeline tooltip on top of all other UI."""

    def __init__(self, **properties):
        super(_MarkerTooltipOverlay, self).__init__(**properties)

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        renpy.redraw(self, 0.05)
        text = getattr(_cue, '_marker_tip_text', None) or ""
        if not text:
            return renpy.Render(1, 1)

        tip_widget = Txt(text, style="cue_txt", size=12,
                          color="#cccccc", italic=False, substitute=False)
        tip_render = renpy.render(tip_widget, 300, 100, st, at)
        tw, th = tip_render.get_size()
        fw = min(tw + 8, 300)
        fh = th + 4

        tip = renpy.Render(fw, fh)
        tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
        tip.blit(tip_render, (4, 2))

        tx = getattr(_cue, '_marker_tip_x', 0)
        ty = getattr(_cue, '_marker_tip_y', 0)

        r = renpy.Render(1, 1)
        r.blit(tip, (tx, ty))
        return r
