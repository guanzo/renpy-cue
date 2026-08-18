# -*- coding: utf-8 -*-
"""Mock of renpy.display.video for unit tests."""


class Movie(object):
    """Stub for the Movie displayable."""

    # 8.x adds a group_texture bridge on Movie; speed.py branches on
    # hasattr(Movie, "group") to pass group=tag through _movie_for.
    group = None

    def __init__(self, *args, **kwargs):
        play = kwargs.get("play", "")
        self.play = play
        # Real Ren'Py stores the file under _original_play/_play (the
        # group_texture feature can rewrite _play); _cue_get_movie_play
        # reads those.
        self._original_play = play
        self._play = play
        self.channel = kwargs.get("channel", "movie")
        self.loop = kwargs.get("loop", True)


def default_play_callback(*args, **kwargs):
    """Stub -- real one handles movie play callbacks."""
    return None
