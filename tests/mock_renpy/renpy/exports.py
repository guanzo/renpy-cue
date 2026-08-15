# -*- coding: utf-8 -*-
"""Mock of renpy.exports for unit tests.

cue_lib/__init__.py copies every public name from this module onto the
renpy module, mirroring the real runtime.  Function stubs are no-ops with
harmless defaults; tests that care about behavior monkeypatch them.
"""


def restart_interaction(*args, **kwargs):
    pass


def redraw(d, when, *args, **kwargs):
    pass


def show_screen(*args, **kwargs):
    pass


def hide_screen(*args, **kwargs):
    pass


def get_screen(*args, **kwargs):
    return None


def get_mouse_pos(*args, **kwargs):
    return (0, 0)


def get_hovered(*args, **kwargs):
    return False


def get_focus_rect(*args, **kwargs):
    return (0, 0, 0, 0)


def focus_coordinates(*args, **kwargs):
    return (0, 0)


def capture_focus(*args, **kwargs):
    pass


def clear_capture_focus(*args, **kwargs):
    pass


def render(child, width, height, st, at, *args, **kwargs):
    return None


def list_files(*args, **kwargs):
    return []


def image(name, *args, **kwargs):
    return None


def file(name, *args, **kwargs):
    return None


def displayable(name, *args, **kwargs):
    return None


def get_showing_tags(*args, **kwargs):
    return []


def showing(*args, **kwargs):
    return None


def add_layer(*args, **kwargs):
    pass


def register_sl_displayable(*args, **kwargs):
    return None


def get_displayable(*args, **kwargs):
    return None
