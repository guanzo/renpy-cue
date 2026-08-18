# -*- coding: utf-8 -*-
"""Mock of renpy.display.behavior for unit tests."""


class Button(object):
    """Stub for Button displayables."""

    def __init__(self, *args, **kwargs):
        self.children = []

    def add(self, child):
        self.children.append(child)


def clear_keymap_cache():
    """Stub for renpy.display.behavior.clear_keymap_cache (no-op)."""
    pass
