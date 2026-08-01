# CDD: Self-updating label — redraws itself on a timer without restarting
# interaction, so the time display stays live without jitter or input focus loss.
# =============================================================================

init python:
    class SelfUpdatingLabel(renpy.Displayable):
        """A text label that calls renpy.redraw() to update itself periodically.

        `getter` is a zero-argument function that returns a string.
        `style` is the Ren'Py text style to apply.
        `interval` is the redraw interval in seconds (default 0.05 = 20 Hz)."""

        def __init__(self, getter, style="default", interval=0.05, **properties):
            # Let the base class resolve the string to a proper style object
            # (so per_interact doesn't crash on self.style.prefix).
            super(SelfUpdatingLabel, self).__init__(style=style, **properties)
            self._text_style = style  # raw string for child Text creation
            self.getter = getter
            self.interval = interval

        def render(self, width, height, st, at):
            from renpy.text.text import Text as Txt
            text = self.getter()
            t = Txt(text, style=self._text_style)
            cr = renpy.render(t, width, height, st, at)
            cw, ch = cr.get_size()
            r = renpy.Render(cw, ch)
            r.blit(cr, (0, 0))
            renpy.redraw(self, self.interval)
            return r


    class VideoTimeline(renpy.Displayable):
        """Video-editor-style timeline bar with a playhead line.
        Redraws at ~60 Hz (16 ms) for smooth playhead movement."""

        BAR_H = 16  # bar height in pixels

        def __init__(self, interval=0.016, **properties):
            super(VideoTimeline, self).__init__(**properties)
            self.interval = interval

        def render(self, width, height, st, at):
            r = renpy.Render(width, height)

            dur = _sfx_editor_get_duration()
            elapsed = _sfx_editor_get_elapsed()
            paused = _sfx.paused

            # Determine hover state for subtle brightness change
            hovered = False
            try:
                hovered = self in renpy.get_hovered()
            except Exception:
                pass

            bar_y = max(0, (height - self.BAR_H) // 2)

            # Bar background (slightly brighter on hover)
            bg = "#3a3a3a" if hovered else "#333333"
            canvas = r.canvas()
            canvas.rect(bg, (0, bar_y, width, self.BAR_H))

            # Playhead line (inside the bar)
            if dur > 0 and width > 0:
                frac = max(0.0, min(1.0, elapsed / float(dur)))
                px = int(frac * width)
                px = max(0, min(px, width - 1))

                ph_color = "#ffaa00" if paused else "#ffffff"
                canvas.rect(ph_color, (px, bar_y, 2, self.BAR_H))

            renpy.redraw(self, self.interval)
            return r


    class _VideoMarkerTimeline(renpy.Displayable):
        """Timeline with draggable marker tabs. Click to select, drag to adjust.
        Renders its own tooltip inline — no separate tooltip CDD needed."""

        TRACK_H = 10
        TAB_H = 16
        LINE_H = 8
        TAB_W = 14
        DRAG_THRESH = 4
        TIP_H = 22  # height of the floating tooltip

        def __init__(self, get_markers, get_active, set_active, set_time, get_dur, **kw):
            super(_VideoMarkerTimeline, self).__init__(**kw)
            self.get_markers = get_markers
            self.get_active = get_active
            self.set_active = set_active
            self.set_time = set_time
            self.get_dur = get_dur
            self._drag_idx = getattr(_sfx, '_mtl_drag_idx', -1)
            self._drag_on = getattr(_sfx, '_mtl_drag_on', False)
            self._drag_start_x = getattr(_sfx, '_mtl_drag_start_x', 0)
            self._tip_text = ""
            self._tip_x = 0
            self._tip_y = 0
            self._hover_idx = -1

        def _total_h(self):
            return self.TAB_H + self.TRACK_H + 4

        def render(self, width, height, st, at):
            self._w = width
            r = renpy.Render(width, self._total_h())
            c = r.canvas()
            dur = max(0.001, self.get_dur())
            markers = self.get_markers()
            active = self.get_active()

            # Draw marker lines and tabs (hover state managed by event())
            for i, m in enumerate(markers):
                t = m.get("time", 0.0)
                frac = max(0.0, min(1.0, t / dur))
                px = int(frac * width)

                # Vertical line
                lc = "#669966" if i == active else "#666666"
                c.rect(lc, (px - 1, 0, 2, self.TRACK_H + self.LINE_H))

                # Tab button geometry
                bx_pos = px - self.TAB_W // 2
                by_pos = self.TRACK_H - 2

                # Tab background
                if i == self._drag_idx and self._drag_on:
                    bg = "#7777cc"
                elif i == active:
                    bg = "#669966"
                elif self._hover_idx == i:
                    bg = "#666666"
                else:
                    bg = "#444444"
                c.rect(bg, (bx_pos, by_pos, self.TAB_W, self.TAB_H))

                # Tab number
                txt = Text(str(i + 1), style="sfx_btn_text", size=12, color="#ffffff")
                tr = renpy.render(txt, self.TAB_W, self.TAB_H, st, at)
                tw, _ = tr.get_size()
                r.blit(tr, (bx_pos + (self.TAB_W - tw) // 2, by_pos))

            # Render tooltip if there's text (set by event())
            if self._tip_text:
                tip_widget = Text(self._tip_text, style="sfx_txt", size=11,
                                  color="#cccccc", italic=True, substitute=False)
                tip_render = renpy.render(tip_widget, 300, self.TIP_H, st, at)
                tw, _ = tip_render.get_size()
                fw = min(tw + 8, 300)
                fh = self.TIP_H - 2

                tip = renpy.Render(fw, fh)
                tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
                tip.blit(tip_render, (4, 1))

                # Position tooltip to right of the cursor
                tx = self._tip_x + 10
                ty = self._tip_y
                r.blit(tip, (tx, ty))

            renpy.redraw(self, 0.05)
            return r

        def event(self, ev, x, y, st):
            dur = max(0.001, self.get_dur())
            markers = self.get_markers()
            w = getattr(self, '_w', 1)

            import pygame
            if ev.type == pygame.MOUSEMOTION:
                if self._drag_idx >= 0:
                    if not self._drag_on and abs(x - self._drag_start_x) > self.DRAG_THRESH:
                        self._drag_on = True
                        _sfx._mtl_drag_on = True
                    if self._drag_on:
                        f = max(0.0, min(1.0, x / float(max(1, w))))
                        self.set_time(self._drag_idx, f * dur)
                        self._tip_text = "Pool {} ({})".format(
                            self._drag_idx + 1, _sfx_editor_format_time(f * dur))
                        self._tip_x = x
                        self._tip_y = y
                    renpy.redraw(self, 0)
                    raise renpy.display.core.IgnoreEvent()
                # Hover tooltip
                self._hover_idx = -1
                for i, m in enumerate(markers):
                    t = m.get("time", 0.0)
                    px = int((t / dur) * w)
                    bx = px - self.TAB_W // 2
                    by = self.TRACK_H - 2
                    if bx <= x <= bx + self.TAB_W and by <= y <= by + self.TAB_H:
                        self._tip_text = "Pool {} ({})".format(
                            i + 1, _sfx_editor_format_time(t))
                        self._tip_x = x
                        self._tip_y = y
                        self._hover_idx = i
                        return None
                self._tip_text = ""
                return None

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i, m in enumerate(markers):
                    t = m.get("time", 0.0)
                    px = int((t / dur) * w)
                    bx = px - self.TAB_W // 2
                    by = self.TRACK_H - 2
                    if bx <= x <= bx + self.TAB_W and by <= y <= by + self.TAB_H:
                        self._drag_idx = i
                        self._drag_start_x = x
                        self._drag_on = False
                        _sfx._mtl_drag_idx = i
                        _sfx._mtl_drag_on = False
                        _sfx._mtl_drag_start_x = x
                        self.set_active(i)
                        renpy.redraw(self, 0)
                        raise renpy.display.core.IgnoreEvent()
                return None

            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self._drag_idx >= 0:
                    was_drag = self._drag_on
                    self._drag_idx = -1
                    self._drag_on = False
                    _sfx._mtl_drag_idx = -1
                    _sfx._mtl_drag_on = False
                    if was_drag:
                        _sfx_editor_mtl_finalize()
                    renpy.redraw(self, 0)
                    renpy.restart_interaction()
                    raise renpy.display.core.IgnoreEvent()
                return None

            return None

    class _MouseFollowerTooltip(renpy.Displayable):
        """Tooltip that continuously re-positions itself at the mouse cursor."""

        def __init__(self, **properties):
            super(_MouseFollowerTooltip, self).__init__(**properties)

        def render(self, width, height, st, at):
            tt = getattr(_sfx, '_tooltip_text', None) or ""
            if not tt:
                return renpy.Render(1, 1)

            mx, my = renpy.get_mouse_pos()

            text_widget = Text(
                tt, style="sfx_txt", size=11, color="#cccccc",
                italic=True, substitute=False,
            )
            text_render = renpy.render(text_widget, 300, 22, st, at)
            tw, th = text_render.get_size()

            pad_x, pad_y = 4, 2
            fw = min(tw + pad_x * 2, 300)
            fh = 22

            tip = renpy.Render(fw, fh)
            tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
            tip.blit(text_render, (pad_x, pad_y))

            r = renpy.Render(1, 1)
            r.blit(tip, (mx + 12, my - 8))

            renpy.redraw(self, 0.05)
            return r

