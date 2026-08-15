# -*- coding: utf-8 -*-
"""Mock of renpy.display.im for unit tests."""


class Image(object):
    """Stub for the Image displayable."""

    def __init__(self, *args, **kwargs):
        self.filename = args[0] if args else None


class MatrixColor(object):
    """Stub for the MatrixColor image transform (color-matrix wrapper)."""

    def __init__(self, im, *args, **kwargs):
        self.im = im


class matrix(object):
    """Stub for renpy.display.im.matrix -- a 4x4 color matrix."""

    def __init__(self, *args, **kwargs):
        pass

    def identity(self):
        return self
