# -*- coding: utf-8 -*-
"""Mock of renpy.display.video for unit tests."""


class Movie(object):
    """Stub for the Movie displayable."""

    def __init__(self, *args, **kwargs):
        self.play = kwargs.get("play", "")
        self.channel = kwargs.get("channel", "movie")
        self.loop = kwargs.get("loop", True)


def default_play_callback(*args, **kwargs):
    """Stub -- real one handles movie play callbacks."""
    return None
