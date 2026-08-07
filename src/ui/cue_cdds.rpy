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
        Redraws at ~60 Hz (16 ms) for smooth playhead movement.
        Click on the bar to seek the video to that position and pause."""

        BAR_H = 16  # bar height in pixels


        def __init__(self, interval=0.016, **properties):
            super(VideoTimeline, self).__init__(**properties)
            self.interval = interval
            self._w = 1
            self._bar_y = 0

        def render(self, width, height, st, at):
            self._w = width
            r = renpy.Render(width, height)

            vs = _cue.vid_manager
            dur = vs.get_duration()
            elapsed = vs.get_elapsed()
            paused = vs.paused

            # Determine hover state for subtle brightness change
            hovered = False
            try:
                hovered = self in renpy.get_hovered()
            except Exception:
                pass

            self._bar_y = max(0, (height - self.BAR_H) // 2)
            bar_y = self._bar_y

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

            # --- Hover seek-preview tooltip ---
            if dur > 0 and _cue.vid_manager.channel:
                mx, my = renpy.get_mouse_pos()
                bx = getattr(_cue, '_vtl_screen_x', -999)
                by = getattr(_cue, '_vtl_screen_y', -999)
                rx, ry = mx - bx, my - by
                if 0 <= rx <= width and bar_y <= ry <= bar_y + self.BAR_H:
                    frac = max(0.0, min(1.0, rx / float(max(1, width))))
                    t = frac * dur
                    tip_text = "Click to seek to: " + _cue_format_time(t)
                    tip_widget = Text(tip_text, style="cue_txt", size=11,
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
            import pygame
            if ev.type == pygame.MOUSEMOTION:
                mx, my = renpy.get_mouse_pos()
                _cue._vtl_screen_x = mx - x
                _cue._vtl_screen_y = my - y
                renpy.redraw(self, 0)
                return None
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                # Only handle clicks within the visible bar area
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
                            raise renpy.display.core.IgnoreEvent()
                return None
            return None


    class CueVideoMarkerTimeline(renpy.Displayable):
        """Timeline with draggable marker tabs.
        Click: select single marker (clears multi-selection).
        Alt+Click: toggle marker in/out of multi-selection.
        Shift+Click: range-select markers from nearest selected (or active) to clicked.
        Drag: single marker, or all selected markers together in multi-select mode."""

        TRACK_H = 10
        TAB_H = 16
        LINE_H = 8
        TAB_W = 14
        DRAG_THRESH = 4
        PAD_X = 10  # breathing room so edge markers don't clip


        # Selection highlight colour (blue tint for selected-but-not-active)
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
            self._drag_orig_times = {}  # {idx: original_time} for multi-drag delta
            self._drag_group_min = 0.0  # min orig time in the group (for boundary blocking)
            self._drag_group_max = 0.0  # max orig time in the group
            self._tip_text = ""
            self._tip_x = 0
            self._tip_y = 0
            self._hover_idx = -1
            self._screen_x = 0  # screen-space offset of this CDD
            self._screen_y = 0

        def _reset_drag_state(self):
            self._drag_orig_times = {}
            self._drag_group_min = 0.0
            self._drag_group_max = 0.0

        def _total_h(self):
            return self.TAB_H + self.TRACK_H + 4

        def _time_to_x(self, t, dur, w):
            """Map a time to pixel x within the padded timeline.
            Marker times are stored at 1x reference — scale to variant
            time so positions align with the speed-variant timeline.

            When duration is unavailable (video change / seek), returns
            the last known position so markers don't teleport."""
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
            """Map an inner-space pixel x to fraction [0, 1]."""
            return max(0.0, min(1.0, x / float(max(1, w))))

        def _get_selected(self):
            """Return the current set of selected marker indices."""
            return _cue.markers.video.get_selected()

        def _hit_test(self, markers, dur, w, x, y):
            """Return the index of the marker tab under (x,y), or -1.
            Autoscales marker times so hit-testing aligns with displayed positions."""
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

            # Draw marker lines and tabs (hover state managed by event())
            for i, m in enumerate(markers):
                t = m.get("time", 0.0)
                px = self._time_to_x(t, dur, inner_w)

                in_sel = i in sel

                # Colours when autoscaled (speed != 1.0): all purple, no
                # selection/drag distinction since markers are locked.
                if is_scaled:
                    if i == active:
                        lc = "#9966aa"
                        bg = "#664466"
                    else:
                        lc = "#775588"
                        bg = "#554455"
                else:
                    # Vertical line colour
                    if i == self._drag_idx and self._drag_on:
                        lc = "#7777cc"
                    elif i == active and multi_active:
                        lc = "#5599cc"  # active + multi-selected
                    elif i == active:
                        lc = "#669966"  # active, single
                    elif in_sel:
                        lc = self.SEL_LINE  # selected but not active
                    else:
                        lc = "#666666"

                    # Tab background colour
                    if i == self._drag_idx and self._drag_on:
                        bg = "#7777cc"  # purple = dragging
                    elif i == active:
                        bg = "#669966"  # green = active pool
                    elif in_sel:
                        bg = self.SEL_BG  # blue = selected but not active
                    elif self._hover_idx == i:
                        bg = "#666666"
                    else:
                        bg = "#444444"

                # Vertical line
                c.rect(lc, (px - 1, 0, 2, self.TRACK_H + self.LINE_H))

                # Tab button geometry
                bx_pos = px - self.TAB_W // 2
                by_pos = self.TRACK_H - 2
                c.rect(bg, (bx_pos, by_pos, self.TAB_W, self.TAB_H))

                # Tab number
                txt = Text(str(i + 1), style="cue_btn_text", size=12, color="#ffffff")
                tr = renpy.render(txt, self.TAB_W, self.TAB_H, st, at)
                tw, _ = tr.get_size()
                r.blit(tr, (bx_pos + (self.TAB_W - tw) // 2, by_pos))

            # --- Preview marker overlay (repeat-pattern dialog) ---
            if dur > 0.0:
                preview_times = _cue.beat.compute_preview_times()
            else:
                preview_times = []
            for ptime in preview_times:
                ppx = self._time_to_x(ptime, dur, inner_w)
                c.rect("#5c7a8c", (ppx - 1, 0, 2, self.TRACK_H + self.LINE_H))
                pbx = ppx - self.TAB_W // 2
                pby = self.TRACK_H - 2
                c.rect("#4a606e", (pbx, pby, self.TAB_W, self.TAB_H))
                ptxt = Text("?", style="cue_btn_text", size=12, color="#ffffff")
                ptr = renpy.render(ptxt, self.TAB_W, self.TAB_H, st, at)
                ptw, _ = ptr.get_size()
                r.blit(ptr, (pbx + (self.TAB_W - ptw) // 2, pby))

            # Store marker tooltip state for the overlay to render on top
            if self._tip_text:
                _cue._marker_tip_text = self._tip_text
                _cue._marker_tip_x = self._screen_x + self._tip_x + 10
                _cue._marker_tip_y = self._screen_y + self._tip_y
            else:
                _cue._marker_tip_text = ""

            renpy.redraw(self, 0.05)
            return r

        def event(self, ev, x, y, st):
            dur = self.get_dur()
            markers = self.get_markers()
            w = getattr(self, '_w', 1)
            inner_x = x - self.PAD_X  # offset for padding
            speed = _cue.speed_resolver.get_current_speed()
            is_scaled = speed != 1.0

            import pygame
            if ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                mx, my = renpy.get_mouse_pos()
                self._screen_x = mx - x
                self._screen_y = my - y
            if ev.type == pygame.MOUSEMOTION:
                if not is_scaled and self._drag_idx >= 0:
                    if not self._drag_on and abs(inner_x - self._drag_start_x) > self.DRAG_THRESH:
                        self._drag_on = True
                        
                        # Snapshot original times + group bounds for multi-drag
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
                            # Multi-drag: compute delta, clamp to keep entire
                            # group within [0, dur], then apply uniformly.
                            current_frac = self._x_to_frac(inner_x, w)
                            start_frac = self._x_to_frac(self._drag_start_x, w)
                            raw_delta = (current_frac - start_frac) * dur
                            max_dur = dur
                            # Block: leading edge hits right wall, trailing hits left
                            hi_room = max_dur - self._drag_group_max
                            lo_room = 0.0 - self._drag_group_min
                            delta_time = max(lo_room, min(hi_room, raw_delta))
                            for idx, orig_time in self._drag_orig_times.items():
                                self.set_time(idx, orig_time + delta_time)
                            # Tooltip shows the dragged marker's current time
                            drag_orig = self._drag_orig_times.get(self._drag_idx, 0)
                            cur_time = drag_orig + delta_time
                            self._tip_text = "Pool {} ({}) ({} selected)".format(
                                self._drag_idx + 1, _cue_format_time(cur_time),
                                len(self._drag_orig_times))
                        else:
                            # Single drag
                            f = self._x_to_frac(inner_x, w)
                            self.set_time(self._drag_idx, f * dur)
                            self._tip_text = "Pool {} ({})".format(
                                self._drag_idx + 1, _cue_format_time(f * dur))
                        self._tip_x = x
                        self._tip_y = y
                    renpy.redraw(self, 0)
                    raise renpy.display.core.IgnoreEvent()
                # Hover tooltip
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
                        # Show offset from nearest selected (or active) marker
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
                # When autoscaled (speed != 1.0), markers are display-only
                if is_scaled:
                    return None

                mods = pygame.key.get_mods()
                alt_held = bool(mods & (pygame.KMOD_LALT | pygame.KMOD_RALT))
                shift_held = bool(mods & (pygame.KMOD_LSHIFT | pygame.KMOD_RSHIFT))

                hit_idx = self._hit_test(markers, dur, w, inner_x, y)

                sel = self._get_selected()

                # Compute click time from x position (used by shift logic)
                click_frac = self._x_to_frac(inner_x, w)
                click_time = click_frac * dur

                # Ignore clicks outside this displayable's bounds (e.g. on
                # buttons above the timeline) — they shouldn't clear selection.
                if not (-self.PAD_X <= inner_x < w + self.PAD_X and 0 <= y < self._total_h()):
                    return None

                if hit_idx < 0:
                    # Click on empty space within the timeline area
                    if shift_held and markers:
                        # Fall through to shift logic below
                        pass
                    else:
                        _cue.markers.video.selected = set()
                        return None

                if alt_held and hit_idx >= 0:
                    # Alt+Click: toggle marker in/out of selection.
                    # If nothing is selected yet, seed with the currently
                    # active marker so the first alt+click forms a group.
                    
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
                    raise renpy.display.core.IgnoreEvent()

                elif shift_held:
                    # Shift+Click: select all markers whose time falls between
                    # the click and the nearest already-selected marker
                    # (or the active marker if nothing is selected).
                    # When clicking on a marker, use its actual time so the
                    # clicked marker is always included in the range.
                    
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
                    raise renpy.display.core.IgnoreEvent()

                elif hit_idx >= 0:
                    # Plain left click on a marker
                    
                    if hit_idx not in sel:
                        # Clicking an unselected marker → reset selection
                        _cue.markers.video.selected = set()
                    # Arm drag (preserve selection if marker was in group —
                    # reset to single happens on MOUSEBUTTONUP if no drag)
                    self._drag_idx = hit_idx
                    self._drag_start_x = inner_x
                    self._drag_on = False
                    self._reset_drag_state()
                    
                    self.set_active(hit_idx)
                    renpy.redraw(self, 0)
                    raise renpy.display.core.IgnoreEvent()

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
                        # Click (no drag) on a marker in multi-selection
                        # resets to single selection on that marker
                        sel = self._get_selected()
                        if len(sel) > 1 and clicked_idx in sel:
                            _cue.markers.video.selected = set()
                    renpy.redraw(self, 0)
                    renpy.restart_interaction()
                    raise renpy.display.core.IgnoreEvent()
                return None

            return None

    class _Tooltip(renpy.Displayable):
        """Hover tooltip that auto-sizes to fit text (single or multi-line)."""

        def __init__(self, text, **properties):
            super(_Tooltip, self).__init__(**properties)
            self._text = text

        def render(self, width, height, st, at):
            text_widget = Text(
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


    class _MarkerTooltipOverlay(renpy.Displayable):
        """Renders the marker timeline tooltip on top of all other UI.
        Reads state set by CueVideoMarkerTimeline.render()."""

        def __init__(self, **properties):
            super(_MarkerTooltipOverlay, self).__init__(**properties)

        def render(self, width, height, st, at):
            renpy.redraw(self, 0.05)
            text = getattr(_cue, '_marker_tip_text', None) or ""
            if not text:
                return renpy.Render(1, 1)

            tip_widget = Text(text, style="cue_txt", size=12,
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

