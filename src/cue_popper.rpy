# CuePopper — Reusable positioned popup for Ren'Py.
#
# Usage:
#   screen my_screen():
#       $ anchor_id = "my_anchor"
#       textbutton "Hover me":
#           properties _cue_popper_anchor_props(anchor_id)
#       popper target anchor_id placement "top" offset 8:
#           frame:
#               text "Tooltip content"
#
# The anchor calls _cue_store_focus_rect(name) on hovered (via the
# properties helper). The popper positions its child relative to the
# anchor with flip + clamp, and auto-dismisses 300ms after the mouse
# leaves both the anchor and popup area.
# =============================================================================

python early:
    def _cue_popper_factory(target, placement, offset, viewport_margin, **kwargs):
        """Factory for register_sl_displayable. Returns a CuePopper instance.

        Defined in python early so it exists when register_sl_displayable
        is called. CuePopper is resolved at call time (screen execution),
        by which point the init python block has defined it.
        """
        return CuePopper(
            target=target,
            placement=placement,
            offset=offset,
            viewport_margin=viewport_margin,
            style=kwargs.get("style", "default"),
        )

    renpy.register_sl_displayable(
        "popper",
        _cue_popper_factory,
        style="default",
        nchildren=1,
        default_keywords={
            "placement": "top",
            "offset": 0,
            "viewport_margin": 8,
        },
    ).add_property("target").add_property("placement")


init python:
    # --- Focus rect helpers (version-adaptive) ----------------------------

    def _cue_store_focus_rect(name):
        """Capture current focus rect under `name`.
        Call from anchor hovered/action via
            properties _cue_popper_anchor_props(name)
        or directly:
            hovered Function(_cue_store_focus_rect, name)

        Uses built-in capture_focus on 8.x; manual fallback on 7.4.x.
        """
        _v = getattr(renpy, 'version_tuple', (0, 0, 0))
        if _v >= (8, 0, 0):
            before = renpy.focus_coordinates()
            renpy.capture_focus(name)
            after = renpy.get_focus_rect(name)
            _cue_log("[popper.store] v={} name={} before={} after={}".format(
                _v, name, before, after))
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
            _cue_log("[popper.store] v={} name={} rect={}".format(
                _v, name, rect))


    def _cue_clear_focus_rect(name):
        """Clear stored focus rect for `name`."""
        _v = getattr(renpy, 'version_tuple', (0, 0, 0))
        if _v >= (8, 0, 0):
            renpy.clear_capture_focus(name)
        else:
            anchors = getattr(_cue, '_popper_anchors', None)
            if anchors is not None:
                anchors.pop(name, None)


    def _cue_get_focus_rect(name):
        """Return (x, y, w, h) or (None, None, None, None)."""
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


    # --- Anchor properties helper -----------------------------------------

    def _cue_popper_anchor_props(name):
        """Return a dict of screen-language properties for a popper anchor.
        Sets id=name, hovered to _cue_store_focus_rect(name), and
        action=NullAction() (required — Ren'Py ignores hovered on buttons
        without an action).

        To override with a real click action, put it AFTER properties:
            textbutton "Click me":
                properties _cue_popper_anchor_props("btn")
                action Function(my_click_handler)

        Usage:
            textbutton "Hover me":
                properties _cue_popper_anchor_props(anchor_id)
        """
        d = python_dict()
        d["id"] = name
        d["hovered"] = Function(_cue_store_focus_rect, name)
        #d["action"] = NullAction()
        return d


    # --- Placement algorithm ----------------------------------------------

    def _cue_compute_popup_position(ax, ay, aw, ah, cw, ch, vw, vh,
                                    placement, offset, margin):
        """Compute (x, y) for popup relative to anchor rect.
        Implements popper.js-style preferred placement + flip + clamp.

        ax, ay, aw, ah — anchor rect in screen coords
        cw, ch — popup content size
        vw, vh — viewport size (game window)
        placement — "top" | "bottom" | "left" | "right"
        offset — gap between anchor edge and popup edge
        margin — minimum distance from viewport edge
        """

        if placement == "top":
            x = ax + (aw - cw) // 2
            y = ay - ch - offset
            if y < margin:
                y = ay + ah + offset
        elif placement == "bottom":
            x = ax + (aw - cw) // 2
            y = ay + ah + offset
            if y + ch > vh - margin:
                y = ay - ch - offset
        elif placement == "left":
            x = ax - cw - offset
            y = ay + (ah - ch) // 2
            if x < margin:
                x = ax + aw + offset
        elif placement == "right":
            x = ax + aw + offset
            y = ay + (ah - ch) // 2
            if x + cw > vw - margin:
                x = ax - cw - offset
        else:
            # Unknown placement — default to top.
            x = ax + (aw - cw) // 2
            y = ay - ch - offset

        # Clamp within viewport.
        x = max(margin, min(x, vw - cw - margin))
        y = max(margin, min(y, vh - ch - margin))

        return int(x), int(y)


    # --- CuePopper displayable --------------------------------------------

    class CuePopper(renpy.display.layout.Container):
        """Positioned popup that renders its child relative to an anchor.

        Dismissal: stays visible while mouse hovers the anchor OR the popup
        itself. A 300ms delay is applied before hiding, so the gap between
        anchor and popup does not break the hover chain.
        """

        HIDE_DELAY = 0.1
        MAX_POPUP_W = 400
        MAX_POPUP_H = 300

        def __init__(self, target, placement="top", offset=0,
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
            self._frame += 1
            r = renpy.Render(width, height)

            if not self.children:
                if self._frame == 1:
                    _cue_log("[popper t={}] no children".format(self.target))
                self.offsets = [(0, 0)]
                return renpy.Render(1, 1)

            # Sync stored rect from focus system.
            rect = _cue_get_focus_rect(self.target)
            if rect[0] is not None:
                self._stored_rect = rect

            if self._frame <= 3 or self._frame % 120 == 0:
                _cue_log("[popper t={}] frame={} has_children={} rect={}".format(
                    self.target, self._frame, bool(self.children),
                    self._stored_rect is not None))

            if self._stored_rect is None:
                self._hide_st = None
                self.offsets = [(0, 0)]
                renpy.redraw(self, 0)
                return renpy.Render(1, 1)

            ax, ay, aw, ah = self._stored_rect

            # Measure content — capped, so a stretch-prone child (e.g. a
            # frame without xfill False) can't blow up to the full
            # available box, regardless of what container Popper sits in.
            child = self.children[0]
            measure_w = min(width, self.MAX_POPUP_W)
            measure_h = min(height, self.MAX_POPUP_H)
            child_render = renpy.render(child, measure_w, measure_h, st, at)
            cw, ch = child_render.get_size()

            # Compute popup position against game window bounds.
            vw = renpy.config.screen_width
            vh = renpy.config.screen_height
            x, y = _cue_compute_popup_position(
                ax, ay, aw, ah, cw, ch,
                vw, vh,
                self.placement, self.offset, self.viewport_margin,
            )

            # Hover-zone check: is mouse over anchor or popup?
            mx, my = renpy.get_mouse_pos()
            in_anchor = (ax <= mx <= ax + aw and ay <= my <= ay + ah)
            in_popup = (x <= mx <= x + cw and y <= my <= y + ch)

            if in_anchor or in_popup:
                self._hide_st = None
            elif self._hide_st is None:
                self._hide_st = st + self.HIDE_DELAY

            # Timer expired — clear stored rect (popper hides next frame).
            if self._hide_st is not None and st >= self._hide_st:
                _cue_clear_focus_rect(self.target)
                self._stored_rect = None
                self._hide_st = None
                renpy.redraw(self, 0)
                return r

            # Blit child at computed position.
            r.blit(child_render, (x, y))

            renpy.redraw(self, 0)
            return r

        def add(self, child):
            """Wrap child in default popup chrome: frame + click-blocking button."""
            from renpy.display.behavior import Button
            from renpy.display.layout import Window

            frame = Window(style="cue_popper_frame")
            frame.add(child)

            btn = Button(action=NullAction())
            btn.add(frame)
            super(CuePopper, self).add(btn)

        def visit(self):
            return list(self.children)
