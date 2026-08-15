# -*- coding: utf-8 -*-
"""Mock of renpy.display.core for unit tests."""


class Displayable(object):
    """Stub base class for displayables."""

    def __init__(self, *args, **kwargs):
        pass


class IgnoreEvent(Exception):
    """Stub -- raised by displayables to skip an event."""
