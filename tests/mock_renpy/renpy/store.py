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


# Ren'Py's store defines _in_replay (False when not replaying).  The marker
# store's _normalize_entry reads it when defaulting an entry's "replay" key,
# so the mock must provide it for headless tests.
_in_replay = False


persistent = PersistentStub()
