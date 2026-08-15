# -*- coding: utf-8 -*-
# Tests for cue_lib.trigger -- CueTriggerEngine dispatch state machines.
#
# The engine is constructor-injected (store/repeater/speed_resolver/vid_manager/
# markers), so every collaborator is a fake and the tick/context state machines
# run headlessly.  _cue_play_pool / _cue_fade_out_sfx are imported lazily from
# cue_lib.runtime at call time, so they're monkeypatched on that module.
# _cue_resolve_files is auto-patched to identity -- file resolution reads the
# _cue singleton's sfx_manager, which unit tests don't wire up.

import pytest

import cue_lib.trigger as _trigger
import cue_lib.runtime as _runtime
from cue_lib.trigger import CueTriggerEngine, CUE_EXCL_KIND_LOOP, CUE_EXCL_KIND_ONESHOT
from cue_lib.constants import CueExclusiveStart, CueLoopFrequency

from tests.fakes import (
    FakeMarkerStore, FakeMarkers, FakeRepeater, FakeSpeedResolver, FakeVidManager,
)


@pytest.fixture(autouse=True)
def _identity_resolve_files(monkeypatch):
    monkeypatch.setattr(_trigger, "_cue_resolve_files", lambda files: list(files))


@pytest.fixture
def play_stub(monkeypatch):
    """Stub _cue_play_pool that records (key, pool_index, file) and returns a
    truthy channel so the caller records a play."""
    calls = []

    def fake_play(entry, key, pool, pool_index, **kw):
        calls.append((key, pool_index, kw.get("file")))
        return "cue_sfx_1"

    monkeypatch.setattr(_runtime, "_cue_play_pool", fake_play)
    return calls


@pytest.fixture
def fade_stub(monkeypatch):
    """Stub _cue_fade_out_sfx recording its kwargs."""
    calls = []

    def fake_fade(**kw):
        calls.append(kw)
        return []

    monkeypatch.setattr(_runtime, "_cue_fade_out_sfx", fake_fade)
    return calls


def make_engine(store=None, repeater=None, speed=None, vid=None, markers=None):
    return CueTriggerEngine(
        store if store is not None else FakeMarkerStore(),
        repeater if repeater is not None else FakeRepeater(),
        speed if speed is not None else FakeSpeedResolver(),
        vid if vid is not None else FakeVidManager(),
        markers=markers)


def pick(monkeypatch, value="a.ogg"):
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: value)


def keep_playing(monkeypatch):
    """Keep every tracked channel alive through _prune_excl."""
    monkeypatch.setattr(_trigger._music, "is_playing", lambda channel="music", **kw: True)


def loop_store():
    return FakeMarkerStore({
        "l_scene.ogg": {"pools": [
            {"files": ["a.ogg"], "frequency": CueLoopFrequency.NORMAL}]}})


# ---------------------------------------------------------------------------
# constructor / _markers_ctx
# ---------------------------------------------------------------------------

def test_constructor_defaults():
    eng = make_engine()
    assert eng.active is True
    assert eng.loop_states == {}
    assert eng.excl_channels == {}
    assert eng._prev_eff_elapsed == -1.0


def test_markers_ctx_injected():
    fake = FakeMarkers()
    assert make_engine(markers=fake)._markers_ctx() is fake


def test_markers_ctx_falls_back_to_singleton(monkeypatch):
    from cue_lib.state import _cue
    fake = FakeMarkers()
    monkeypatch.setattr(_cue, "markers", fake)
    eng = CueTriggerEngine(FakeMarkerStore(), FakeRepeater(),
                           FakeSpeedResolver(), FakeVidManager())
    assert eng._markers_ctx() is fake


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

def test_tick_inactive_is_noop(monkeypatch):
    eng = make_engine()
    eng.active = False
    seen = []
    monkeypatch.setattr(eng, "_tick_loop", lambda now, tick, cf: seen.append("loop"))
    monkeypatch.setattr(eng, "_tick_video", lambda cf, layer: seen.append("video"))
    eng.tick("scene.ogg", "movie")
    assert eng._tick_count == 0
    assert seen == []


def test_tick_dispatches_loop_then_video(monkeypatch):
    eng = make_engine()
    seen = []
    monkeypatch.setattr(eng, "_tick_loop", lambda now, tick, cf: seen.append("loop"))
    monkeypatch.setattr(eng, "_tick_video", lambda cf, layer: seen.append("video"))
    eng.tick("scene.ogg", "movie")
    assert eng._tick_count == 1
    assert seen == ["loop", "video"]


# ---------------------------------------------------------------------------
# exclusive helpers
# ---------------------------------------------------------------------------

def test_excl_track_stores_info():
    eng = make_engine()
    eng._excl_track("cue_sfx_1", CUE_EXCL_KIND_ONESHOT, "scene.ogg", None, False)
    assert eng.excl_channels["cue_sfx_1"] == {
        "kind": CUE_EXCL_KIND_ONESHOT, "scene": "scene.ogg", "line": None, "hold": False}


def test_excl_track_none_channel_ignored():
    eng = make_engine()
    eng._excl_track(None, CUE_EXCL_KIND_ONESHOT, "scene.ogg", None, False)
    assert eng.excl_channels == {}


def test_prune_excl_drops_finished_channels():
    eng = make_engine()
    eng.excl_channels = {"ch1": {"kind": CUE_EXCL_KIND_LOOP},
                         "ch2": {"kind": CUE_EXCL_KIND_ONESHOT}}
    eng._prune_excl()  # mock is_playing -> False, so both dropped
    assert eng.excl_channels == {}


def test_prune_excl_keeps_playing(monkeypatch):
    eng = make_engine()
    eng.excl_channels = {"ch1": {"kind": CUE_EXCL_KIND_LOOP}}
    keep_playing(monkeypatch)
    eng._prune_excl()
    assert eng.excl_channels == {"ch1": {"kind": CUE_EXCL_KIND_LOOP}}


def test_excl_same_group_loop_never_shared():
    eng = make_engine()
    info = {"kind": CUE_EXCL_KIND_LOOP, "scene": "a", "line": None}
    assert not eng._excl_same_group(info, CUE_EXCL_KIND_LOOP, "a", None)


def test_excl_same_group_scene_mismatch():
    eng = make_engine()
    info = {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "a", "line": None}
    assert not eng._excl_same_group(info, CUE_EXCL_KIND_ONESHOT, "b", None)


def test_excl_same_group_scene_match_any_line():
    # image/shake one-shot (line None) shares the group with a dialogue one-shot
    eng = make_engine()
    info = {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "a", "line": None}
    assert eng._excl_same_group(info, CUE_EXCL_KIND_ONESHOT, "a", "d_a__hi")


def test_excl_same_group_line_match():
    eng = make_engine()
    info = {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "a", "line": "d_a__hi"}
    assert eng._excl_same_group(info, CUE_EXCL_KIND_ONESHOT, "a", "d_a__hi")


def test_excl_same_group_line_mismatch():
    eng = make_engine()
    info = {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "a", "line": "d_a__old"}
    assert not eng._excl_same_group(info, CUE_EXCL_KIND_ONESHOT, "a", "d_a__new")


def test_excl_group_channels_filters_kind_and_group():
    eng = make_engine()
    eng.excl_channels = {
        "ch1": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "a", "line": None, "hold": False},
        "ch2": {"kind": CUE_EXCL_KIND_LOOP, "scene": "a", "line": None, "hold": False},
    }
    assert eng._excl_group_channels(CUE_EXCL_KIND_ONESHOT, "a", None) == ["ch1"]


def test_excl_kind_channels():
    eng = make_engine()
    eng.excl_channels = {"ch1": {"kind": CUE_EXCL_KIND_ONESHOT},
                         "ch2": {"kind": CUE_EXCL_KIND_LOOP}}
    assert eng._excl_kind_channels(CUE_EXCL_KIND_LOOP) == ["ch2"]


def test_hold_blocked_holding_outgroup(monkeypatch):
    eng = make_engine()
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "held": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "other.ogg", "line": None, "hold": True}}
    assert eng._excl_hold_blocked(CUE_EXCL_KIND_ONESHOT, "scene.ogg", None)


def test_hold_blocked_same_group_hold_not_blocked(monkeypatch):
    eng = make_engine()
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "held": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "scene.ogg", "line": None, "hold": True}}
    assert not eng._excl_hold_blocked(CUE_EXCL_KIND_ONESHOT, "scene.ogg", None)


def test_hold_blocked_other_domain_ignored(monkeypatch):
    eng = make_engine()
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "held": {"kind": CUE_EXCL_KIND_LOOP, "scene": "other.ogg", "line": None, "hold": True}}
    assert not eng._excl_hold_blocked(CUE_EXCL_KIND_ONESHOT, "scene.ogg", None)


def test_hold_blocked_non_hold_ignored(monkeypatch):
    eng = make_engine()
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "busy": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "other.ogg", "line": None, "hold": False}}
    assert not eng._excl_hold_blocked(CUE_EXCL_KIND_ONESHOT, "scene.ogg", None)


def test_outgroup_busy_any_outgroup_playing(monkeypatch):
    eng = make_engine()
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "ch": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "other.ogg", "line": None, "hold": False}}
    assert eng._excl_outgroup_busy(CUE_EXCL_KIND_ONESHOT, "scene.ogg", None)


def test_outgroup_busy_same_group_clears(monkeypatch):
    eng = make_engine()
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "ch": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "scene.ogg", "line": None, "hold": False}}
    assert not eng._excl_outgroup_busy(CUE_EXCL_KIND_ONESHOT, "scene.ogg", None)


# ---------------------------------------------------------------------------
# fire_context
# ---------------------------------------------------------------------------

def test_fire_context_inactive_noop():
    eng = make_engine()
    eng.active = False
    eng.fire_context("i_scene.ogg")
    assert eng.excl_channels == {}


def test_fire_context_empty_key_skipped(play_stub):
    eng = make_engine()
    eng.fire_context("", "i_scene.ogg")
    assert play_stub == []


def test_fire_context_missing_entry_skipped(play_stub):
    eng = make_engine()
    eng.fire_context("i_missing.ogg")
    assert play_stub == []


def test_fire_context_plays_pool(monkeypatch, play_stub):
    pick(monkeypatch)
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [{"files": ["a.ogg"]}]}})
    eng = make_engine(store=store)
    eng.fire_context("i_scene.ogg")
    assert play_stub == [("i_scene.ogg", 0, "a.ogg")]
    assert eng.excl_channels["cue_sfx_1"]["kind"] == CUE_EXCL_KIND_ONESHOT


def test_fire_context_multipool_dedupes(monkeypatch, play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [
        {"files": ["a.ogg", "b.ogg"]}, {"files": ["a.ogg", "b.ogg"]}]}})
    picks = iter(["a.ogg", "b.ogg"])
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: next(picks))
    eng = make_engine(store=store)
    eng.fire_context("i_scene.ogg")
    assert play_stub == [("i_scene.ogg", 0, "a.ogg"), ("i_scene.ogg", 1, "b.ogg")]


def test_fire_context_deduped_none_skips_pool(monkeypatch, play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [
        {"files": ["a.ogg"]}, {"files": ["a.ogg"]}]}})
    pick(monkeypatch)  # always "a.ogg" -- second pool can't satisfy dedupe
    eng = make_engine(store=store)
    eng.fire_context("i_scene.ogg")
    assert play_stub == [("i_scene.ogg", 0, "a.ogg")]


def test_fire_context_only_shake_pools_filters(monkeypatch, play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [
        {"files": ["a.ogg"], "trigger_on_shake": True},
        {"files": ["b.ogg"], "trigger_on_shake": False}]}})
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: files[0])
    eng = make_engine(store=store)
    eng.fire_context("i_scene.ogg", only_shake_pools=True)
    assert play_stub == [("i_scene.ogg", 0, "a.ogg")]


def test_fire_context_all_pools_without_shake_filter(monkeypatch, play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [
        {"files": ["a.ogg"], "trigger_on_shake": True},
        {"files": ["b.ogg"], "trigger_on_shake": False}]}})
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: files[0])
    eng = make_engine(store=store)
    eng.fire_context("i_scene.ogg")
    assert len(play_stub) == 2


def test_fire_context_pool_without_files(play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [{"files": []}]}})
    eng = make_engine(store=store)
    eng.fire_context("i_scene.ogg")
    assert play_stub == []


def test_fire_context_hold_gate_drops_pool(monkeypatch, play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [{"files": ["a.ogg"]}]}})
    eng = make_engine(store=store)
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "held": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "other.ogg", "line": None, "hold": True}}
    eng.fire_context("i_scene.ogg")
    assert play_stub == []


def test_fire_context_wait_defers_when_air_busy(monkeypatch, play_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [
        {"files": ["a.ogg"], "exclusive": {"start": CueExclusiveStart.WAIT}}]}})
    eng = make_engine(store=store)
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "busy": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "other.ogg", "line": None, "hold": False}}
    eng.fire_context("i_scene.ogg")
    assert play_stub == []


def test_fire_context_fade_cuts_outgroup(monkeypatch, play_stub, fade_stub):
    store = FakeMarkerStore({"i_scene.ogg": {"pools": [
        {"files": ["a.ogg"], "exclusive": {"start": CueExclusiveStart.FADE}}]}})
    eng = make_engine(store=store)
    keep_playing(monkeypatch)
    eng.excl_channels = {
        "ch": {"kind": CUE_EXCL_KIND_ONESHOT, "scene": "scene.ogg", "line": None, "hold": False}}
    eng.fire_context("i_scene.ogg")
    assert fade_stub[0]["exclude_channels"] == ["ch"]
    assert play_stub == [("i_scene.ogg", 0, "a.ogg")]


# ---------------------------------------------------------------------------
# _tick_loop
# ---------------------------------------------------------------------------

def test_tick_loop_no_entry():
    eng = make_engine(store=FakeMarkerStore({}))
    eng._tick_loop(100.0, 1, "scene.ogg")
    assert eng.loop_states == {}


def test_tick_loop_pool_without_files():
    store = FakeMarkerStore({"l_scene.ogg": {"pools": [{"files": []}]}})
    eng = make_engine(store=store)
    eng._tick_loop(100.0, 1, "scene.ogg")
    assert eng.loop_states == {}


def test_tick_loop_plays_when_ready(monkeypatch, play_stub):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    eng = make_engine(store=loop_store(), markers=FakeMarkers())
    eng._tick_loop(100.0, 1, "scene.ogg")
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["channels"] == ["cue_sfx_1"]
    assert pst["play_start"] == 100.0
    assert eng.excl_channels["cue_sfx_1"]["kind"] == CUE_EXCL_KIND_LOOP


def test_tick_loop_not_ready_defers(monkeypatch):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 5.0)
    eng = make_engine(store=loop_store(), markers=FakeMarkers())
    eng._tick_loop(100.0, 1, "scene.ogg")
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["ready_at"] == 105.0
    assert pst["channels"] == []


def test_tick_loop_resets_when_done(monkeypatch, play_stub):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    eng = make_engine(store=loop_store(), markers=FakeMarkers())
    ps = eng.loop_states.setdefault("l_scene.ogg", {})
    ps[0] = {"ready_at": 0.0, "channels": ["cue_sfx_1"], "play_start": 50.0,
             "blocked_logged": False}
    eng._tick_loop(100.0, 1, "scene.ogg")
    pst = ps[0]
    assert pst["channels"] == []  # reset for the next cycle
    assert pst["ready_at"] == 102.1  # now + breathing delay


def test_tick_loop_hold_defers(monkeypatch, play_stub):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    keep_playing(monkeypatch)
    eng = make_engine(store=loop_store(), markers=FakeMarkers())
    eng.excl_channels = {
        "held": {"kind": CUE_EXCL_KIND_LOOP, "scene": "other.ogg", "line": None, "hold": True}}
    eng._tick_loop(100.0, 1, "scene.ogg")
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["ready_at"] == 100.1
    assert pst["blocked_logged"] is True
    assert play_stub == []


def test_tick_loop_wait_defers(monkeypatch, play_stub):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    keep_playing(monkeypatch)
    store = FakeMarkerStore({"l_scene.ogg": {"pools": [
        {"files": ["a.ogg"], "frequency": CueLoopFrequency.NORMAL,
         "exclusive": {"start": CueExclusiveStart.WAIT}}]}})
    eng = make_engine(store=store, markers=FakeMarkers())
    eng.excl_channels = {
        "busy": {"kind": CUE_EXCL_KIND_LOOP, "scene": "other.ogg", "line": None, "hold": False}}
    eng._tick_loop(100.0, 1, "scene.ogg")
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["ready_at"] == 100.1
    assert play_stub == []


# ---------------------------------------------------------------------------
# _tick_video
# ---------------------------------------------------------------------------

def test_tick_video_no_channel_returns():
    eng = make_engine(vid=FakeVidManager(channel=""))
    eng._tick_video("scene.ogv", "movie")
    assert eng._prev_eff_elapsed == -1.0  # untouched


def test_tick_video_wrong_layer_returns():
    eng = make_engine()
    eng._tick_video("scene.ogv", "sprite")
    assert eng._prev_eff_elapsed == -1.0


def test_tick_video_fires_marker(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["a.ogg"]}])
    eng = make_engine(store=store, markers=markers)
    eng._tick_video("scene.ogv", "movie")
    assert play_stub == [("v_scene.ogv", 0, None)]


def test_tick_video_marker_not_refired(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["a.ogg"]}])
    vid = FakeVidManager(elapsed=0.1)
    vid.last_elapsed = 0.1  # not a fresh reset -- dedup set survives
    eng = make_engine(store=store, vid=vid, markers=markers)
    eng._tick_video("scene.ogv", "movie")
    assert play_stub == [("v_scene.ogv", 0, None)]

    vid.last_elapsed = 0.1
    vid._elapsed = 0.15
    eng._tick_video("scene.ogv", "movie")
    assert play_stub == [("v_scene.ogv", 0, None)]  # no re-fire


def test_tick_video_preview_marker(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    vid = FakeVidManager(elapsed=0.05)
    vid.last_elapsed = 0.05
    repeater = FakeRepeater(dialog_visible=True, preview_sfx_enabled=True,
                            preview_pools=[{"time": 0.0, "files": ["p.ogg"]}])
    eng = make_engine(store=store, vid=vid, markers=FakeMarkers(), repeater=repeater)
    eng._tick_video("scene.ogv", "movie")
    assert play_stub == [("v_scene.ogv", 0, None)]


def test_tick_video_restart_clears_played(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    vid = FakeVidManager(elapsed=0.05)
    vid.last_elapsed = 0.05
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["a.ogg"]}])
    eng = make_engine(store=store, vid=vid, markers=markers)
    eng._tick_video("scene.ogv", "movie")
    assert len(play_stub) == 1
    assert "v_scene.ogv@0.000#1" in eng.played_video_keys

    # restart tick: backward jump detected AFTER the marker loop, so the
    # already-played key is skipped this tick, then the dedup set clears.
    vid.last_elapsed = 5.0
    vid._elapsed = 0.05
    eng._tick_video("scene.ogv", "movie")
    assert len(play_stub) == 1  # not re-fired on the restart tick itself

    # next tick: the cleared set lets the time-0 marker fire again.
    vid.last_elapsed = 0.05
    vid._elapsed = 0.05
    eng._tick_video("scene.ogv", "movie")
    assert len(play_stub) == 2
    assert "v_scene.ogv@0.000#1" in eng.played_video_keys
