# -*- coding: utf-8 -*-
"""Mock of renpy.store for unit tests."""


class PersistentStub(object):
    """Drop-in for persistent -- plain attribute storage."""

    def __init__(self):
        self._cue = None


def Function(*args, **kwargs):
    return None


class NullAction(object):
    def __call__(self, *args, **kwargs):
        return None


persistent = PersistentStub()
