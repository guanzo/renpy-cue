# -*- coding: utf-8 -*-
"""Mock of renpy.audio.music for unit tests.

No-ops with harmless defaults.  Tests that care about playback state can
monkeypatch these or inspect the mock channel state.
"""


def get_pos(channel="music", **kwargs):
    return 0.0


def get_duration(channel="music", **kwargs):
    return 0.0


def is_playing(channel="music", **kwargs):
    return False


def get_playing(channel="music", **kwargs):
    return None


def set_pause(value, channel="music", **kwargs):
    pass


def set_volume(volume, delay=0, channel="music", **kwargs):
    pass


def register_channel(name, mixer=None, loop=None, stop_on_mute=None, tight=False, **kwargs):
    pass


def channel_defined(name):
    return False


def play(filenames, channel="music", loop=None, **kwargs):
    pass


def stop(channel="music", **kwargs):
    pass


def queue(filenames, channel="music", loop=None, **kwargs):
    pass
