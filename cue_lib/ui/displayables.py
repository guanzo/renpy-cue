# -*- coding: utf-8 -*-
# Creator-Defined Displayables for the Cue overlay.
# CueSelfUpdatingLabel, CueVideoTimeline, CueVideoMarkerTimeline, CueTooltip,
# CueVideoMarkerTooltip, CueSidebarResizeHandle.

import colorsys
import pygame
import renpy
from renpy.text.text import Text as Txt
from renpy.display.core import Displayable, IgnoreEvent

from cue_lib.state import _cue
from cue_lib.util import _cue_escape_text, _cue_format_time, create_vid_key
from cue_lib.constants import CUE_DEBUG, CUE_INTENSITY_HINT_COLOR, CUE_INTENSITY_NOTE

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple
    from cue_lib._types import VideoPoolDict
    from cue_lib.intensity.intensity import CueIntensityFlags  # pyright: ignore[reportUnusedImport]


# Intensity line gradient endpoints: Level 1 (softest) is a cool blue,
# Level N (hardest) a hot red.  Interpolated along the HSL hue path so
# mid levels sweep through green/yellow/orange.
CUE_INTENSITY_COLOR_LOW = "#f2c14e"
CUE_INTENSITY_COLOR_HIGH = "#ff1f1f"

# ---------------------------------------------------------------------------
# Key-capture helpers for the rebindable keybinds system
# ---------------------------------------------------------------------------

# Bare modifier keycodes — these cannot be bound as standalone keys.
_BARE_MOD_NAMES = frozenset(
    {
        "K_LSHIFT",
        "K_RSHIFT",
        "K_LCTRL",
        "K_RCTRL",
        "K_LALT",
        "K_RALT",
        "K_LSUPER",
        "K_RSUPER",
        "K_LGUI",
        "K_RGUI",
        "K_LMETA",
        "K_RMETA",
        "K_MODE",
    }
)

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


# ---------------------------------------------------------------------------
# Sidebar resize + mouse cursor helpers
# ---------------------------------------------------------------------------


def _cue_sidebar_width_from_mouse(mx, zoom, panel):
    # type: (int, float, int) -> int
    """Sidebar width (physical px) for a logical cursor x at the given zoom."""
    return int(mx * zoom) - panel


def _cue_sidebar_set_cursor(name):
    # type: (str) -> None
    """Force the hardware cursor for the rest of this interaction.

    Ren'Py picks the cursor from the focused widget's style.mouse, then
    interface.mouse, then default_mouse. Setting interface.mouse is the only
    path that doesn't depend on focus, but it resets at the top of each
    interact(), so callers re-assert it whenever the state that needs it is
    active.
    """
    iface = getattr(renpy.display, "interface", None)
    if iface is not None:
        iface.mouse = name


def _cue_sidebar_poll_cursor():
    # type: () -> None
    """Periodic: keep the resize cursor up for the whole drag.

    interface.mouse resets to the default at the top of every interact(), so
    a drag MOTION that restarts the interaction would let the default cursor
    flash back. This runs on every PERIODIC tick immediately before
    update_mouse, so while the handle is dragging it re-asserts the resize
    cursor after any reset.
    """
    handle = CueSidebarResizeHandle._instance
    if handle is not None and handle._dragging:
        _cue_sidebar_set_cursor("cue_resize")


def _cue_setup_mouse_cursor():
    # type: () -> None
    """Register the mod's custom hardware cursors in config.mouse."""
    base = renpy.config.mouse or {}
    mouse = dict(base)
    if "default" not in mouse:
        # No mouse theme (config.mouse is None on stock Ren'Py / theme-less
        # games; the game's GUI defines the entries when present). Making
        # config.mouse non-empty switches the engine off the OS cursor, and
        # 7.x get_mouse_info falls back to config.mouse["default"] -- so a
        # "default" entry is mandatory or every interaction crashes.  The
        # bundled arrow becomes the game's pointer; it's the only way custom
        # cursors can exist in such games.
        mouse["default"] = [(_cue.paths.icon("arrow-pointer-solid.png"), 5, 0)]
    mouse["cue_resize"] = [(_cue.paths.icon("arrows-left-right-solid.png"), 16, 16)]
    mouse["cue_pointer"] = [(_cue.paths.icon("hand-pointer-solid.png"), 16, 16)]
    renpy.config.mouse = mouse


# ---------------------------------------------------------------------------
# Tooltip + intensity color helpers
# ---------------------------------------------------------------------------


def _cue_render_tooltip(text, anchor, st, at):
    # type: (str, Tuple[int, int, int, int], float, float) -> Any
    """Render an auto-sized tooltip positioned relative to an anchor rect.

    `anchor` is the hovered element's screen bounds (fx, fy, fw, fh). The
    tooltip centers above it, flipping below when there's no room above, and
    clamps to the screen. Shared by CueTooltip and CueVideoMarkerTooltip.
    """
    text_widget = Txt(
        _cue_escape_text(text, brackets=False) or "",
        style="cue_text",
        size=12,
        color="#cccccc",
        italic=False,
        substitute=False,
    )
    max_width = 350
    text_render = renpy.render(text_widget, max_width, 100, st, at)
    tw, th = text_render.get_size()

    pad_x, pad_y = 4, 2
    fw = tw + pad_x * 2
    fh = th + pad_y * 2

    # Outer footprint: 1px border on every side plus a 2px drop shadow on
    # the right/bottom. Positioned as a whole so the border never clips.
    BORDER = 1
    SHADOW = 2
    ow = fw + BORDER * 2 + SHADOW
    oh = fh + BORDER * 2 + SHADOW

    sw = renpy.config.screen_width
    sh = renpy.config.screen_height

    fx, fy, fw_elem, fh_elem = anchor
    # Anchor to the hovered element (not the cursor) so the tooltip never
    # covers it: centered above, flipping below when there's no room above.
    tx = fx + (fw_elem - ow) // 2
    ty = fy - oh - 4
    if ty < 0:
        ty = fy + fh_elem + 4

    # Clamp to keep the tooltip fully on screen
    if tx + ow > sw:
        tx = sw - ow
    if ty + oh > sh:
        ty = sh - oh
    if tx < 0:
        tx = 0
    if ty < 0:
        ty = 0

    r = renpy.Render(1, 1)
    tip = renpy.Render(ow, oh)

    # Drop shadow: translucent black offset 2px past the bottom-right border.
    shadow = renpy.Render(ow - SHADOW, oh - SHADOW)
    shadow.canvas().rect("#000000", (0, 0, ow - SHADOW, oh - SHADOW))
    shadow.alpha = 0.45
    tip.blit(shadow, (SHADOW, SHADOW))

    # 1px border (palette _cue_color_divider) around the interior fill.
    tip.canvas().rect("#555555", (0, 0, ow - SHADOW, oh - SHADOW), 1)
    tip.canvas().rect("#2e2e2e", (BORDER, BORDER, fw, fh))

    tip.blit(text_render, (BORDER + pad_x, BORDER + pad_y))
    r.blit(tip, (tx, ty))
    return r


def _cue_intensity_color(level, total, low=CUE_INTENSITY_COLOR_LOW, high=CUE_INTENSITY_COLOR_HIGH):
    # type: (int, int, str, str) -> str
    """Hex color for a 1-based intensity `level` out of `total` levels,
    interpolated along the HSL hue path from soft (low) to hard (high)."""
    if total <= 1 or level >= total:
        return high
    if level <= 1:
        return low
    t = (level - 1) / float(total - 1)

    def _hex_to_hls(hex_color):
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return colorsys.rgb_to_hls(r, g, b)

    h1, l1, s1 = _hex_to_hls(low)
    h2, l2, s2 = _hex_to_hls(high)
    r, g, b = colorsys.hls_to_rgb(h1 + (h2 - h1) * t, l1 + (l2 - l1) * t, s1 + (s2 - s1) * t)
    return "#{:02x}{:02x}{:02x}".format(int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


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
        self._screen_x = 0
        self._screen_y = 0

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

        # SFX-fire breadcrumb trail: static ticks at the file-frac where each
        # SFX fired, for comparing the fire point against the moving playhead.
        # Debug-only (CUE_DEBUG); off in production so players don't see them.
        if CUE_DEBUG:
            for bc in vs.sfx_breadcrumbs:
                bpx = int(bc * width)
                if 0 <= bpx < width:
                    canvas.rect("#33ff88", (bpx, bar_y, 1, self.BAR_H))

        if dur > 0 and width > 0:
            frac = max(0.0, min(1.0, elapsed / float(dur)))
            px = int(frac * width)
            px = max(0, min(px, width - 1))
            ph_color = "#ffaa00" if paused else "#ffffff"
            canvas.rect(ph_color, (px, bar_y, 2, self.BAR_H))

        if dur > 0 and _cue.vid_manager.channel:
            mx, my = renpy.get_mouse_pos()
            bx = self._screen_x
            by = self._screen_y
            rx, ry = mx - bx, my - by
            if 0 <= rx <= width and bar_y <= ry <= bar_y + self.BAR_H:
                frac = max(0.0, min(1.0, rx / float(max(1, width))))
                t = frac * dur
                tip_text = "Click to seek to: " + _cue_format_time(t)
                tip_widget = Txt(tip_text, style="cue_text", size=11, color="#cccccc", italic=True, substitute=False)
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
            self._screen_x = mx - x
            self._screen_y = my - y
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

    # Published for CueVideoMarkerTooltip -- one timeline is visible at a
    # time, so class-level state is the shared mailbox.
    _marker_tip_text = ""
    _marker_tip_x = 0
    _marker_tip_y = 0

    # Built once and reused across screen re-evaluations.  The SFX view adds
    # this same object every interaction, so drag/hover state set on it
    # survives a timer-fired restart_interaction (which would recreate an
    # inline-constructed timeline and wipe the state mid-gesture).
    _instance = None

    TRACK_H = 10
    TAB_H = 14
    LINE_H = 8
    TAB_W = 14
    DRAG_THRESH = 4
    PAD_X = 10

    SEL_BG = "#446688"
    SEL_LINE = "#5588cc"

    # Intensity-live marker indicator: a 2px bottom border under the tab and a
    # tooltip note.  Hot orange reads as "escalating" against the tab's
    # green/blue/purple states.  Border color is CUE_INTENSITY_HINT_COLOR.

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

    def cancel_drag(self):
        # type: () -> None
        """Abort an in-flight drag without finalizing, e.g. the overlay hidden
        mid-drag.  The instance outlives the overlay, so a stale drag must not
        survive a hide."""
        self._drag_idx = -1
        self._drag_on = False
        self._reset_drag_state()

    @classmethod
    def get_timeline(cls):
        # type: () -> CueVideoMarkerTimeline
        """The marker timeline displayable, wired to the live video context.

        Constructing it inline in the screen creates a fresh object every
        interaction, wiping drag/hover state on any restart_interaction.  The
        class keeps one instance instead."""
        if cls._instance is None:
            video = _cue.markers.video
            cls._instance = cls(
                get_markers=video.get_markers,
                get_active_index=video.get_active_index,
                set_active_index=video.set_active_index,
                set_time=video.set_time,
                get_dur=video.get_duration,
            )
        return cls._instance

    @classmethod
    def reset_timeline_drag(cls):
        # type: () -> None
        """Abort an in-flight marker drag, e.g. the overlay hidden mid-drag."""
        if cls._instance is not None:
            cls._instance.cancel_drag()

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

    def _is_intensity_marker(self, marker, flags, variants):
        # type: (VideoPoolDict, CueIntensityFlags, Optional[List[float]]) -> bool
        """True when this marker's own pool plays intensity levels: the
        video's intensity toggle is on, SFX-by-level is on, it has 2+ speed
        variants, and the pool's folder list is hooked to an intensity group."""
        if flags is not None and not flags.sfx_levels:
            return False
        return _cue.intensity.is_pool_intensity_active(marker.get("igroup"), variants, flags)

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

        # Per-video intensity inputs, shared by every marker tab (the hook is
        # per-pool, checked in the loop).  banding_speeds is cached, so this
        # stays cheap on the 0.05s redraw.
        intensity_flags = None
        intensity_variants = None
        tag = _cue.current_file
        if tag:
            entry = _cue.markers.get(create_vid_key(tag), {})
            if entry:
                intensity_flags = _cue.intensity.flags_from_entry(entry)
                intensity_variants = _cue.speed_resolver.banding_speeds(tag)

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

                if i == active:
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
            if intensity_flags is not None and self._is_intensity_marker(m, intensity_flags, intensity_variants):
                c.rect(CUE_INTENSITY_HINT_COLOR, (bx_pos, by_pos + self.TAB_H, self.TAB_W, 1))

            txt = Txt(str(i + 1), style="cue_button_text", color="#ffffff")
            tr = renpy.render(txt, self.TAB_W, self.TAB_H, st, at)
            tw, _ = tr.get_size()
            # +1: nudge the digit right so its ink reads optically centered in the tab.
            r.blit(tr, (bx_pos + (self.TAB_W - tw) // 2 + 1, by_pos))

        # Preview marker overlay
        preview_times = _cue.dialogs.repeater.compute_preview_times() if dur > 0.0 else []

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
            tip = self._tip_text
            tip_idx = self._hover_idx if self._hover_idx >= 0 else self._drag_idx
            if (
                intensity_flags is not None
                and 0 <= tip_idx < len(markers)
                and self._is_intensity_marker(markers[tip_idx], intensity_flags, intensity_variants)
            ):
                tip += "\n[" + CUE_INTENSITY_NOTE + "]"
            CueVideoMarkerTimeline._marker_tip_text = tip
            # Anchor to the hovered/dragged marker tab, not the cursor, so the
            # tip doesn't drift as the mouse moves within the tab.
            if 0 <= tip_idx < len(markers):
                px = self._time_to_x(markers[tip_idx].get("time", 0.0), dur, inner_w)
                CueVideoMarkerTimeline._marker_tip_x = self._screen_x + px
                CueVideoMarkerTimeline._marker_tip_y = self._screen_y + self.TRACK_H - 2 + self.TAB_H
            else:
                CueVideoMarkerTimeline._marker_tip_x = self._screen_x + self._tip_x
                CueVideoMarkerTimeline._marker_tip_y = self._screen_y + self._tip_y
        else:
            CueVideoMarkerTimeline._marker_tip_text = ""

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
                        self._drag_orig_times = {idx: markers[idx]["time"] for idx in valid_sel}
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
                            self._drag_idx + 1, _cue_format_time(cur_time), len(self._drag_orig_times)
                        )
                    else:
                        f = self._x_to_frac(inner_x, w)
                        self.set_time(self._drag_idx, f * dur)
                        self._tip_text = "Pool {} ({})".format(self._drag_idx + 1, _cue_format_time(f * dur))
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
                    self._tip_text = "Pool {} ({}) [{} selected]".format(hit_idx + 1, _cue_format_time(t), len(sel))
                else:
                    self._tip_text = "Pool {} ({})".format(hit_idx + 1, _cue_format_time(t))
                    refs = sel if sel else {self.get_active_index()}
                    valid_refs = [s for s in refs if 0 <= s < len(markers)]
                    if hit_idx not in valid_refs and valid_refs:
                        ref_idx = min(valid_refs, key=lambda s: abs(markers[s]["time"] - t))
                        offset = t - markers[ref_idx]["time"]
                        sign = "+" if offset >= 0 else "-"
                        self._tip_text += "\nOffset from Pool {}: {}{}".format(
                            ref_idx + 1, sign, _cue_format_time(abs(offset))
                        )
                self._tip_x = x
                self._tip_y = y
                self._hover_idx = hit_idx
                return None
            self._tip_text = ""
            return None

        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # Fresh gesture: a down never inherits a previous (possibly
            # lost-up) arm.  Scaled, outside-box, and empty clicks all clear
            # here for free; the marker path re-arms below.
            self._drag_idx = -1
            self._drag_on = False
            self._reset_drag_state()
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


class CueSidebarResizeHandle(Displayable):
    """Drag the SFX sidebar's game-facing right edge to resize it.

    The screen `dragged` callback fires only on drop with a 2-arg signature,
    so live resize needs raw mouse handling here. A container dispatches every
    mouse event to all of its children with child-relative coords, so the
    handle receives the whole gesture regardless of focus state. Drag state
    therefore lives on this instance, not the focus system.

    The "cue_resize" cursor applies on hover because the handle registers
    itself via Render.add_focus, so it becomes the focused widget and its
    style.mouse is used. During the drag the mouse outruns the 10px strip,
    focus leaves the handle, and the cursor would revert to default; each
    MOTION re-asserts interface.mouse = "cue_resize" to keep it up for the
    whole gesture.

    The strip itself renders nothing -- it is an invisible resize zone, with
    the resize cursor as the only affordance.
    """

    _instance = None

    WIDTH = 10

    def __init__(self, **properties):
        super(CueSidebarResizeHandle, self).__init__(**properties)
        self.focusable = True
        self._dragging = False

    @classmethod
    def get_handle(cls):
        # type: () -> CueSidebarResizeHandle
        if cls._instance is None:
            cls._instance = cls(style="cue_sidebar_handle")
        return cls._instance

    def _new_width(self):
        # type: () -> int
        mx, _my = renpy.get_mouse_pos()
        zoom = getattr(renpy.store, "_cue_overlay_zoom")()
        panel = getattr(renpy.store, "_cue_overlay_panel_width")
        return _cue_sidebar_width_from_mouse(mx, zoom, panel)

    def event(self, ev, x, y, st):
        # type: (Any, int, int, float) -> Optional[Any]
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            _in = 0 <= x <= self.WIDTH
            if _in:
                self._dragging = True
                # Hover already pinned the resize cursor; re-assert so the
                # gesture starts from the right cursor even if focus lagged.
                _cue_sidebar_set_cursor("cue_resize")
                raise IgnoreEvent()
            # A press off the strip ends any stale drag (missed release).
            self._dragging = False
            _cue_sidebar_set_cursor("default")
            return None

        if ev.type == pygame.MOUSEMOTION:
            if self._dragging:
                # Focus leaves the handle once the mouse outruns the 10px
                # strip, so re-assert the cursor every motion; see the class
                # docstring on why interface.mouse is the reliable path.
                _cue_sidebar_set_cursor("cue_resize")
                lib = _cue.sfx.library
                old_w = lib.sidebar_width
                lib.set_sidebar_width(self._new_width())
                if lib.sidebar_width != old_w:
                    renpy.restart_interaction()
                raise IgnoreEvent()
            return None

        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self._dragging:
                self._dragging = False
                _cue_sidebar_set_cursor("default")
                _cue.sfx.library.persist_sidebar_state()
                renpy.restart_interaction()
                raise IgnoreEvent()
            return None

        return None

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        r = renpy.Render(width, height)
        # Register the whole strip as a focus target.  focus_at_point only
        # finds displayables that called Render.add_focus during render, so
        # without this the handle never becomes the focused widget on hover
        # and its style.mouse cursor is never applied.
        r.add_focus(self, None, 0, 0, width, height, None, None, None)
        return r


class CueTooltip(Displayable):
    """Hover tooltip that auto-sizes to fit text."""

    def __init__(self, text, **properties):
        super(CueTooltip, self).__init__(**properties)
        self._text = text

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        fc = renpy.focus_coordinates()
        if fc is not None:
            fx, fy, fw_elem, fh_elem = fc
            if fx is not None and fy is not None and fw_elem is not None and fh_elem is not None:
                return _cue_render_tooltip(self._text, (fx, fy, fw_elem, fh_elem), st, at)
        # Nothing focused yet (transient) -- anchor at the cursor instead.
        mx, my = renpy.get_mouse_pos()
        return _cue_render_tooltip(self._text, (mx, my, 0, 0), st, at)


class CueVideoMarkerTooltip(Displayable):
    """Renders the marker timeline tooltip on top of all other UI."""

    def __init__(self, **properties):
        super(CueVideoMarkerTooltip, self).__init__(**properties)

    def render(self, width, height, st, at):
        # type: (int, int, float, float) -> Any
        renpy.redraw(self, 0.05)
        text = CueVideoMarkerTimeline._marker_tip_text or ""
        if not text:
            return renpy.Render(1, 1)

        # Anchor on the marker tab (the published point is its center) so the
        # tip mirrors CueTooltip: centered above, flipping below when no room.
        tab = CueVideoMarkerTimeline
        anchor = (
            CueVideoMarkerTimeline._marker_tip_x - tab.TAB_W // 2,
            CueVideoMarkerTimeline._marker_tip_y - tab.TAB_H,
            tab.TAB_W,
            tab.TAB_H,
        )
        return _cue_render_tooltip(text, anchor, st, at)


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
        self._screen_x = 0
        self._screen_y = 0

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

        # Per-video intensity inputs + per-step levels.  Each played segment is
        # colored by its own step's level, so earlier segments keep their color
        # as playback advances.  current_level stops at the band map (no file
        # listing), so this stays cheap on the 0.1s redraw.
        intensity_total = 0
        step_levels = None
        if tag:
            entry = _cue.markers.get(create_vid_key(tag), {})
            if entry:
                intensity_flags = _cue.intensity.flags_from_entry(entry)
                intensity_variants = _cue.speed_resolver.banding_speeds(tag)
                if intensity_variants:
                    intensity_pools = [p.get("igroup") for p in _cue.markers._resolve_video_pools(entry)]
                    step_levels = []
                    for sp in speeds:
                        lvl = _cue.intensity.current_level(intensity_pools, sp, intensity_variants, intensity_flags)
                        if lvl is None:
                            step_levels.append(0)
                        else:
                            step_levels.append(lvl[0])
                            intensity_total = lvl[1]

        canvas = r.canvas()

        # --- Dim line: full sequence ---
        for i in range(len(points) - 1):
            canvas.line(self.COLOR_DIM, points[i], points[i + 1], self.LINE_W)

        # --- Bright line: played portion, one color per step's level ---
        if current_idx > 0:
            for i in range(min(current_idx, len(points) - 1)):
                if step_levels is not None and step_levels[i]:
                    color = _cue_intensity_color(step_levels[i], intensity_total)
                else:
                    color = self.COLOR_BRIGHT
                canvas.line(color, points[i], points[i + 1], self.LINE_W)

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

        y_style = dict(style="cue_text", size=12, color="#888888", italic=False, substitute=False)
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
            cur_label = _fmt(cur_sp)
            if step_levels is not None and step_levels[current_idx]:
                cur_label += " (lvl {})".format(step_levels[current_idx])
            cur_w = Txt(cur_label, style="cue_text", size=12, color="#ffaa00", italic=False, substitute=False)
            # Wide enough that the "(lvl N)" suffix stays on one line.
            cur_r = renpy.render(cur_w, 200, 16, st, at)
            cw, _ch = cur_r.get_size()
            r.blit(cur_r, (cx - cw // 2, height - 14))

        # --- Hover tooltip ---
        try:
            mx, my = renpy.get_mouse_pos()
            bx = self._screen_x
            by_ = self._screen_y
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
                if step_levels is not None and step_levels[nearest_idx]:
                    tip_text += "  (lvl {})".format(step_levels[nearest_idx])
                tip_widget = Txt(tip_text, style="cue_text", size=10, color="#cccccc", italic=False, substitute=False)
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
            self._screen_x = mx - x
            self._screen_y = my - y
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
