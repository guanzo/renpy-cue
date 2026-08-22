# -*- coding: utf-8 -*-
"""Mock of renpy.store for unit tests."""


class PersistentStub(object):
    """Drop-in for persistent -- plain attribute storage."""

    def __init__(self):
        self._cue = None


class _MockFunction(object):
    """Callable Function stand-in.

    Mirrors real Ren'Py's Function.__call__: stores (fn, *args, **kwargs) and
    invokes fn when called.  Lets tests both store an action and exercise a
    code path that runs it (e.g. shift+click skip-confirm)."""

    def __init__(self, args, kwargs):
        self._args = args
        self._kwargs = kwargs

    def __call__(self):
        fn = self._args[0] if self._args else None
        if callable(fn):
            return fn(*self._args[1:], **self._kwargs)
        return None


def Function(*args, **kwargs):
    return _MockFunction(args, kwargs)


class NullAction(object):
    def __call__(self, *args, **kwargs):
        return None


# Ren'Py's store defines _in_replay (False when not replaying).  The marker
# store's _normalize_entry reads it when defaulting an entry's "replay" key,
# so the mock must provide it for headless tests.
_in_replay = False


persistent = PersistentStub()
