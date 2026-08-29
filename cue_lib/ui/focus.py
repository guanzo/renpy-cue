# -*- coding: utf-8 -*-
# Field edit-focus glue for the Cue overlay.
#
# Cue's inline text inputs aren't focusable (an SL `input:` is fed keystrokes via
# Ren'Py's default_input_value path, independent of the focus engine), and the
# overlay's full-panel backdrop button is always the focused widget.  The focus
# engine therefore can't identify the field being edited -- but a real displayable
# (the field's textbutton) occupies the exact same box before editing starts, so
# we capture that box on the click that starts editing and hit-test clicks against
# it later.  This module wraps the focus engine's mouse handler to do both.

import pygame
import renpy

from cue_lib.state import _cue

MYPY = False
if MYPY:
    from typing import Any, Optional


def _cue_action_manages_input(action):
    # type: (Any) -> bool
    """True if running `action` sets _cue.active_input (a field's own control).

    A field's textbutton uses SetField(_cue, "active_input", <field>) and its
    clear/commit actions are lists ending in SetField(_cue, "active_input", "").
    The backdrop and toolbar buttons carry Function actions, so they return False.
    """
    if action is None:
        return False
    if isinstance(action, (list, tuple)):
        return any(_cue_action_manages_input(a) for a in action)
    # A SetField whose target is the Cue singleton and field is active_input --
    # only Cue's own field buttons do that.  Checking `.object` rules out an
    # unrelated SetField that happens to target some other object's active_input.
    return getattr(action, "field", None) == "active_input" and getattr(action, "object", None) is _cue


def _cue_field_control(f):
    # type: (Any) -> bool
    """True if the focusable `f` is a Cue field's own control."""
    return _cue_action_manages_input(getattr(f.widget, "action", None))


def _cue_focusable_at_point(x, y, keep=None):
    # type: (Any, Any, Optional[Any]) -> Optional[Any]
    """Return the innermost focusable containing (x, y), or None.

    Innermost = smallest rect, since a backdrop button wraps the whole panel and
    would otherwise claim every point.  `keep` filters which focusables count.
    """
    best = None  # (area, Focus)
    focus = getattr(renpy.display, "focus")
    for f in getattr(focus, "focus_list", ()):
        if f.x is not None and f.y is not None:
            if f.x <= x < f.x + f.w and f.y <= y < f.y + f.h:
                if keep is not None and not keep(f):
                    continue
                area = f.w * f.h
                if best is None or area < best[0]:
                    best = (area, f)
    return best[1] if best is not None else None


def _cue_install_focus_pin():
    # type: () -> None
    """Pin keyboard focus to the field being edited so mouse hover doesn't steal it.

    Ren'Py's keyboard focus follows the mouse (there is no config.keyboard_focus
    toggle since 7.4), so while a text input is in edit mode, hovering any other
    focusable moves focus off the field and typing stops.  Wrapping the focus
    engine's mouse handler pins focus during hover; a click still lands normally.
    """
    focus = getattr(renpy.display, "focus")

    if getattr(focus.mouse_handler, "_cue_focus_pin", False):
        return

    orig = focus.mouse_handler

    def _cue_pin_focus(ev, x, y, default=False):
        # Only pin while one of Cue's own fields is in edit mode.
        editing = getattr(_cue, "active_input", "")

        # Hover keeps focus pinned; a click still lands normally.
        is_hover = editing and ev is not None and ev.type == pygame.MOUSEMOTION
        if is_hover:
            return None

        if not editing and ev is not None and ev.type == pygame.MOUSEBUTTONDOWN:
            # Capture the field's rect on click: the input replaces its button but
            # isn't focusable, so the box is otherwise unknown.
            f = _cue_focusable_at_point(x, y, _cue_field_control)
            _cue.active_input_rect = (f.x, f.y, f.w, f.h) if f is not None else None

        rv = orig(ev, x, y, default=default)

        # Click outside the active field's rect ends the edit.
        if editing and ev is not None and ev.type == pygame.MOUSEBUTTONDOWN:
            r = _cue.active_input_rect
            on_input = r is not None and (r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3])
            if not on_input:
                # A field control (clear button, other textbutton) flips active_input
                # on its UP action; exiting mid-click restarts and swallows it.
                # Re-capture its rect. Dead space / non-field controls end the edit.
                f = _cue_focusable_at_point(x, y, _cue_field_control)
                if f is not None:
                    _cue.active_input_rect = (f.x, f.y, f.w, f.h)
                else:
                    _cue.active_input = ""
                    _cue.active_input_rect = None
                    renpy.restart_interaction()
        return rv

    setattr(_cue_pin_focus, "_cue_focus_pin", True)
    focus.mouse_handler = _cue_pin_focus
