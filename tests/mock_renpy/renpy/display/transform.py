# -*- coding: utf-8 -*-
"""Mock of renpy.display.transform for unit tests."""


class Transform(object):
    """Stub for the Transform displayable."""

    def __init__(self, *args, **kwargs):
        self.child = None
