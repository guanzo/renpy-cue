# -*- coding: utf-8 -*-
"""Mock of renpy.game for unit tests."""


class _ContextStub(object):
    """Stub for the game context."""

    def __init__(self):
        self.scene_lists = _SceneListsStub()


class _SceneListsStub(object):
    def __init__(self):
        self.layers = {}


def context(*args, **kwargs):
    return _ContextStub()
