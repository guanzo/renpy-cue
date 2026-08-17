# -*- coding: utf-8 -*-
# Tests for cue_lib.runtime -- main-loop callback guards (review F1).
#
# _cue_tick_trigger (50 Hz screen timer) and _cue_refresh_context (every
# interaction start) must swallow any exception raised by a collaborator and
# log it, so one malformed marker or an unexpected None can't wedge the
# per-frame callback chain.  The heavy manager graph is stubbed with fakes;
# the failing collaborator raises, and we assert the call returns cleanly and
# the guard logged.

import pytest

from types import SimpleNamespace

import cue_lib.runtime as _runtime
from cue_lib.state import _cue


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


class _RaisingTrigger(object):
    def tick(self, current_file, top_layer_type):
        raise RuntimeError("boom in trigger tick")


# The _cue singleton attrs the guard tests touch; snapshot + restore so we
# don't leak fakes into other test modules.
_CUE_ATTRS = [
    "ctx", "vid_manager", "video_sequence", "trigger", "volume",
    "video_editor", "sfx_manager", "music",
]


@pytest.fixture
def isolated_cue():
    saved = {}
    for name in _CUE_ATTRS:
        saved[name] = getattr(_cue, name, None)
    yield
    for name, value in saved.items():
        setattr(_cue, name, value)


@pytest.fixture
def captured_log(monkeypatch):
    calls = []
    monkeypatch.setattr(_runtime, "_cue_log", lambda *a: calls.append(a))
    return calls


def _install_tick_collaborators(trigger=None):
    """Install the quiet manager graph the tick path touches and return it.

    trigger defaults to a raising fake so the fast lane fails; pass a quiet
    trigger to let the slow lane run instead."""
    _cue.current_file = None
    _cue.top_layer_type = None
    _cue.vid_manager = SimpleNamespace(
        sync_paused=lambda: None, poll_autopause=lambda: None)
    _cue.video_sequence = SimpleNamespace(tick=lambda: None)
    _cue.trigger = trigger if trigger is not None else _RaisingTrigger()
    _cue.volume = SimpleNamespace(flush_pending_saves=lambda: None)
    _cue.video_editor = SimpleNamespace(processing=False)
    _cue.sfx_manager = SimpleNamespace(maybe_rebuild=lambda: None)
    _cue.music = SimpleNamespace(
        user_music=SimpleNamespace(maybe_rebuild=lambda: None),
        game_music=SimpleNamespace(maybe_rebuild=lambda: None))
    # Force the slow lane to fire so it's exercised too.
    _runtime._cue_slow_tick_last = 0.0


def test_tick_guard_contains_fast_lane_error(isolated_cue, captured_log):
    _install_tick_collaborators()

    _cue_tick_trigger = _runtime._cue_tick_trigger
    _cue_tick_trigger()  # trigger.tick raises -> must not propagate

    assert any(c[0].startswith("TICK-ERR") for c in captured_log)


def test_tick_guard_contains_slow_lane_error(isolated_cue, captured_log):
    _install_tick_collaborators(trigger=SimpleNamespace(tick=lambda *a, **k: None))
    _cue.volume = SimpleNamespace(flush_pending_saves=lambda: None)
    _cue.video_editor = SimpleNamespace(
        processing=True, job_queue=SimpleNamespace(poll=lambda: None))
    _cue.sfx_manager = SimpleNamespace(maybe_rebuild=lambda: None)
    _cue.music = SimpleNamespace(
        user_music=SimpleNamespace(maybe_rebuild=_boom),
        game_music=SimpleNamespace(maybe_rebuild=lambda: None))

    _cue_tick_trigger = _runtime._cue_tick_trigger
    _cue_tick_trigger()  # slow-lane maybe_rebuild raises -> must not propagate

    assert any(c[0].startswith("TICK-ERR") for c in captured_log)


def test_refresh_context_guard_contains_collaborator_error(isolated_cue, captured_log, monkeypatch):
    # Top layer resolves to a real scene; music capture blows up right after.
    monkeypatch.setattr(_runtime, "_cue_get_top_layer",
                        lambda: ("scene_name", "image", object()))
    _cue.vid_manager = SimpleNamespace(channel=None)
    _cue.current_file = ""
    _cue.top_layer_type = None
    _cue.music = SimpleNamespace(capture_display=_boom)

    _cue_refresh_context = _runtime._cue_refresh_context
    _cue_refresh_context()  # capture_display raises -> must not propagate

    assert any(c[0].startswith("REFRESH-CTX-ERR") for c in captured_log)
