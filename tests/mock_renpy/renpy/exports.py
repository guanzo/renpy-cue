# -*- coding: utf-8 -*-
"""Mock of renpy.exports for unit tests.

cue_lib/__init__.py copies every public name from this module onto the
renpy module, mirroring the real runtime.  Function stubs are no-ops with
harmless defaults; tests that care about behavior monkeypatch them.
"""


def restart_interaction(*args, **kwargs):
    pass


def in_rollback(*args, **kwargs):
    return False


version_tuple = (8, 0, 0)


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
    return (None, None, None, None)


def capture_focus(*args, **kwargs):
    pass


def clear_capture_focus(*args, **kwargs):
    pass


class Render(object):
    """Stub for renpy.Render -- records draw ops so displayable render()
    branches can run headlessly."""

    def __init__(self, width, height, **kwargs):
        self.width = width
        self.height = height
        self.blits = []  # type: list
        self._canvas = None

    def canvas(self):
        if self._canvas is None:
            self._canvas = RenderCanvas()
        return self._canvas

    def blit(self, other, pos=(0, 0)):
        self.blits.append((other, pos))

    def get_size(self):
        return (self.width, self.height)


class RenderCanvas(object):
    """Records canvas draw operations for assertion."""

    def __init__(self):
        self.ops = []  # type: list

    def rect(self, color, rect, width=0):
        self.ops.append(("rect", color, rect, width))

    def line(self, color, a, b, width):
        self.ops.append(("line", color, a, b, width))

    def circle(self, color, center, radius):
        self.ops.append(("circle", color, center, radius))

    def polygon(self, color, points):
        self.ops.append(("polygon", color, points))


def render(child, width, height, st, at, *args, **kwargs):
    return Render(width, height)


def loadable(name, *args, **kwargs):
    return True


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
