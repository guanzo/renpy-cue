# -*- coding: utf-8 -*-
"""Mock of renpy.display.layout for unit tests."""


class Container(object):
    """Stub base class for layout containers."""

    def __init__(self, *args, **kwargs):
        pass


class DynamicDisplayable(Container):
    """Stub for dynamic displayables."""

    def __init__(self, function, *args, **kwargs):
        Container.__init__(self, *args, **kwargs)
        self.function = function


class Window(Container):
    """Stub for Window containers."""

    def __init__(self, *args, **kwargs):
        Container.__init__(self, *args, **kwargs)
