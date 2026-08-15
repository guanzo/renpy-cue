# -*- coding: utf-8 -*-
"""Mock of renpy.python for unit tests."""


class NoRollback(object):
    """Stub base class -- the real one marks instances invisible to rollback."""

    def __init__(self, *args, **kwargs):
        object.__init__(self)
