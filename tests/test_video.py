# -*- coding: utf-8 -*-
# Tests for cue_lib.video.video -- CueVideoManager playback control against
# the stateful mock music registry.
#
# The manager is constructed bare (ctx + vid only; no store/paths needed) and
# the channel is driven directly: _movie() writes the "movie" channel state
# and points vid.channel at it, mirroring what _cue_refresh_channel does in
# production.  Every test mutates the same registry the manager reads through,
# so the assertions check the manager's state transitions end-to-end.

import types

import pytest

import renpy.audio.music as _music_mock

from cue_lib.state import CueContext
from cue_lib.video.video import CueVideoManager


@pytest.fixture(autouse=True)
def _clean_state():
    """Per-test isolation: fresh music registry."""
    _music_mock._reset_all()


@pytest.fixture
def env():
    ctx = CueContext()
    vid = CueVideoManager(ctx)
    yield types.SimpleNamespace(ctx=ctx, vid=vid, music=_music_mock)


def _movie(env, position=0.5, duration=10.0, playing="scene.webm", paused=False):
    """Drive the "movie" channel into a concrete playback state."""
    st = {"position": position, "duration": duration}
    if playing is not None:
        st["playing"] = playing
    st["paused"] = paused
    env.music._registry["movie"] = st
    env.vid.channel = "movie"
    return st


# ==========================================================================
# get_elapsed / get_duration / get_video_path
# ==========================================================================


def test_get_elapsed_position_plus_offset(env):
    _movie(env, position=2.0)
    env.vid.time_offset = 3.0
    assert env.vid.get_elapsed() == 5.0


def test_get_elapsed_clamps_negative(env):
    _movie(env, position=0.5)
    env.vid.time_offset = -2.0
    assert env.vid.get_elapsed() == 0.0


def test_get_elapsed_no_channel(env):
    env.vid.channel = None
    assert env.vid.get_elapsed() == 0.0


def test_get_elapsed_exception_returns_zero(env, monkeypatch):
    _movie(env)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_pos", _boom)
    assert env.vid.get_elapsed() == 0.0


def test_get_duration(env):
    _movie(env, duration=12.0)
    assert env.vid.get_duration() == 12.0


def test_get_duration_no_channel(env):
    env.vid.channel = None
    assert env.vid.get_duration() == 0.0


def test_get_video_path(env):
    _movie(env, playing="scene.webm")
    assert env.vid.get_video_path() == "scene.webm"


def test_get_video_path_no_channel(env):
    env.vid.channel = None
    assert env.vid.get_video_path() is None


def test_get_video_path_exception_returns_none(env, monkeypatch):
    _movie(env)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_playing", _boom)
    assert env.vid.get_video_path() is None


def test_get_duration_exception_returns_zero(env, monkeypatch):
    _movie(env)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_duration", _boom)
    assert env.vid.get_duration() == 0.0


# ==========================================================================
# toggle_pause
# ==========================================================================


def test_toggle_pause_pauses_and_records_origin(env):
    _movie(env, position=3.0)
    env.vid.toggle_pause()
    assert env.vid.paused is True
    assert env.music._registry["movie"]["paused"] is True
    assert env.vid.pause_origin == 3.0


def test_toggle_pause_unpauses(env):
    _movie(env, paused=True)
    env.vid.toggle_pause()
    assert env.vid.paused is False
    assert env.music._registry["movie"]["paused"] is False


def test_toggle_pause_no_channel_noop(env):
    env.vid.channel = None
    env.vid.toggle_pause()
    assert env.vid.paused is False


def test_toggle_pause_fallback_volume(env, monkeypatch):
    _movie(env)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_pause", _boom)
    env.vid.toggle_pause()
    assert env.vid.paused is True
    assert env.music._registry["movie"]["volume"] == 0.0
    env.vid.toggle_pause()
    assert env.vid.paused is False
    assert env.music._registry["movie"]["volume"] == 1.0


# ==========================================================================
# seek_to
# ==========================================================================


def test_seek_to_no_channel_noop(env):
    env.vid.channel = None
    env.vid.seek_to(3.0)
    assert env.vid.step_target == 0.0
    assert env.vid.pause_target == 0.0


def test_seek_to_unknown_duration_noop(env):
    _movie(env, duration=0)
    env.vid.seek_to(3.0)
    assert env.vid.step_target == 0.0


def test_seek_to_forward_pause_then_unpause(env):
    _movie(env, position=0.5)
    env.vid.seek_to(3.0)
    st = env.music._registry["movie"]
    assert env.vid.step_target == 3.0
    assert env.vid.pause_origin == 3.0
    assert st["paused"] is False  # unpaused after the step


def test_seek_to_forward_clamps_to_duration(env):
    _movie(env, position=0.5, duration=10.0)
    env.vid.seek_to(20.0)
    assert env.vid.step_target == 10.0


def test_seek_to_backward_restarts_from_zero(env):
    _movie(env, position=5.0)
    env.vid.seek_to(1.0)
    st = env.music._registry["movie"]
    assert env.vid.pause_target == 1.0
    assert env.vid.step_target == 0.0
    assert st["playing"] == "scene.webm"
    assert st["position"] == 0.0
    assert st["paused"] is False


def test_seek_to_backward_no_playing_noop(env):
    _movie(env, position=5.0, playing=None)
    env.vid.seek_to(1.0)
    st = env.music._registry["movie"]
    assert env.vid.pause_target == 0.0
    assert st.get("playing") is None  # stop/play never called


# ==========================================================================
# poll_autopause
# ==========================================================================


def test_poll_autopause_no_channel_noop(env):
    env.vid.channel = None
    env.vid.poll_autopause()
    assert env.vid.paused is False


def test_poll_autopause_not_movie_noop(env):
    _movie(env)
    env.ctx.top_layer_type = "image"
    env.vid.step_target = 5.0
    env.vid.poll_autopause()
    assert env.vid.step_target == 5.0


def test_poll_autopause_pause_target_reached(env):
    _movie(env, position=6.0)
    env.ctx.top_layer_type = "movie"
    env.vid.pause_target = 5.0
    env.vid.poll_autopause()
    assert env.music._registry["movie"]["paused"] is True
    assert env.vid.paused is True
    assert env.vid.pause_target == 0.0


def test_poll_autopause_step_target_reached(env):
    _movie(env, position=6.0)
    env.ctx.top_layer_type = "movie"
    env.vid.step_target = 5.0
    env.vid.poll_autopause()
    assert env.music._registry["movie"]["paused"] is True
    assert env.vid.paused is True
    assert env.vid.step_target == 0.0


def test_poll_autopause_before_target_keeps_playing(env):
    _movie(env, position=2.0)
    env.ctx.top_layer_type = "movie"
    env.vid.step_target = 5.0
    env.vid.poll_autopause()
    assert env.vid.paused is False
    assert env.vid.step_target == 5.0


def test_poll_autopause_no_position_noop(env):
    _movie(env, position=None)
    env.ctx.top_layer_type = "movie"
    env.vid.step_target = 5.0
    env.vid.poll_autopause()
    assert env.vid.step_target == 5.0


def test_poll_autopause_get_pos_exception_safe(env, monkeypatch):
    _movie(env)
    env.ctx.top_layer_type = "movie"
    env.vid.pause_target = 5.0

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_pos", _boom)
    env.vid.poll_autopause()  # must not raise
    assert env.vid.pause_target == 5.0  # untouched


# ==========================================================================
# sync_paused
# ==========================================================================


def test_sync_paused_mirrors_channel(env):
    _movie(env, paused=True)
    env.vid.paused = False
    env.vid.sync_paused()
    assert env.vid.paused is True


def test_sync_paused_no_channel_noop(env):
    env.vid.channel = None
    env.vid.paused = False
    env.vid.sync_paused()
    assert env.vid.paused is False


def test_sync_paused_exception_safe(env, monkeypatch):
    _movie(env)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_pause", _boom)
    env.vid.sync_paused()  # must not raise


# ==========================================================================
# labels
# ==========================================================================


def test_time_label_placeholder_not_movie(env):
    _movie(env)
    env.ctx.top_layer_type = "image"
    assert env.vid.time_label() == "--:--.-- / --:--.--"


def test_time_label_movie(env):
    _movie(env, position=65.5, duration=10.0)
    env.ctx.top_layer_type = "movie"
    assert env.vid.time_label() == "01:05.50 / 00:10.00"


def test_frame_label_placeholder_not_movie(env):
    _movie(env)
    env.ctx.top_layer_type = "image"
    assert env.vid.frame_label() == "---/---"


def test_frame_label_movie(env):
    _movie(env, position=1.0, duration=2.0)
    env.ctx.top_layer_type = "movie"
    env.vid.fps = 30
    assert env.vid.frame_label() == "30/60"


# ==========================================================================
# reset / set_fps / reset_pause
# ==========================================================================


def test_reset_clears_state(env):
    _movie(env, position=2.0)
    env.vid.paused = True
    env.vid.time_offset = 4.0
    env.vid.reset()
    # reset() takes the new channel outright (production always passes one)
    assert env.vid.channel is None
    assert env.vid.paused is False
    assert env.vid.time_offset == 0.0


def test_reset_with_new_channel(env):
    _movie(env)
    env.vid.reset("other")
    assert env.vid.channel == "other"
    assert env.vid.paused is False
