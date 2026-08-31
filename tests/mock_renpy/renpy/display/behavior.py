# -*- coding: utf-8 -*-
"""Mock of renpy.display.behavior for unit tests."""


class Button(object):
    """Stub for Button displayables."""

    def __init__(self, *args, **kwargs):
        self.children = []

    def add(self, child):
        self.children.append(child)


class Adjustment(object):
    """Stub of the scroll adjustment used by the windowed cue_tree_rows.

    Matches the real signature (range first); the screen reads .value and
    .page and the viewport writes them back on scroll."""

    def __init__(self, range=1, value=0, step=None, page=None, **kwargs):
        self.range = range
        self.value = value
        self.step = step
        self.page = page


def clear_keymap_cache():
    """Stub for renpy.display.behavior.clear_keymap_cache (no-op)."""
    pass
