# -*- coding: utf-8 -*-
"""Mock of renpy.text.text for unit tests."""


class Text(object):
    """Stub for the Text displayable."""

    def __init__(self, text, *args, **kwargs):
        self.text = text
