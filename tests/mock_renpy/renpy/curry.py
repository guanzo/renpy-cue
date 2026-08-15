# -*- coding: utf-8 -*-
"""Mock of renpy.curry for unit tests."""


class Curry(object):
    """Stub for curry.curry."""

    def __init__(self, function, *args, **kwargs):
        self.function = function
        self.args = args
        self.kwargs = kwargs
