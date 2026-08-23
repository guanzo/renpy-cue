# -*- coding: utf-8 -*-
# Tests for cue_lib.trigger -- CueTriggerEngine dispatch state machines.
#
# The engine is constructor-injected (store/repeater/speed_resolver/vid_manager/
# markers), so every collaborator is a fake and the tick/context state machines
# run headlessly.  _cue_resolve_files is auto-patched to identity -- file
# resolution reads the _cue singleton's sfx_manager, which unit tests don't wire
# up.  play_pool / fade_out live on the _cue singleton's sfx_manager, so the
# playback fixtures fake that surface instead of a runtime module function.

import types

import pytest

import renpy.store as _store
import renpy.audio.music as _music

import cue_lib.trigger as _trigger
from cue_lib.trigger import (
    CueTriggerEngine, CUE_EXCL_KIND_LOOP, CUE_EXCL_KIND_ONESHOT,
    _cue_effective_delay, _cue_loop_still_playing)
from cue_lib.constants import (
    CUE_INTENSITY_DELAY_MAX, CUE_INTENSITY_DELAY_MIN, CueExclusiveStart, CueLoopFrequency)

from tests.fakes import (
    FakeMarkerStore, FakeMarkers, FakeRepeater, FakeSpeedResolver, FakeVidManager,
)


@pytest.fixture(autouse=True)
def _identity_resolve_files(monkeypatch):
    import cue_lib.intensity.intensity as _intensity
    monkeypatch.setattr(_trigger, "_cue_resolve_files", lambda files: list(files))
    monkeypatch.setattr(_intensity, "_cue_resolve_files", lambda files: list(files))


@pytest.fixture(autouse=True)
def _no_intensity(monkeypatch):
    """Stub _cue.intensity so no pool ever hooks.  Intensity tests override
    this with a real manager."""
    from cue_lib.intensity import CueIntensityFlags
    stub = types.SimpleNamespace(
        resolve_intensity=lambda *a, **k: None,
        video_level=lambda *a, **k: None,
        flags_from_entry=lambda *a, **k: CueIntensityFlags(),
    )
    monkeypatch.setattr(_trigger._cue, "intensity", stub)


@pytest.fixture
def sfx_playback(monkeypatch):
    """Fake _cue.sfx surface trigger.py drives: play_pool + fade_out."""
    mgr = types.SimpleNamespace(play_pool=None, fade_out=None)
    calls = types.SimpleNamespace(play=[], fade=[])
    monkeypatch.setattr(_trigger._cue, "sfx", mgr)
    return mgr, calls


@pytest.fixture
def play_stub(sfx_playback):
    """Record (key, pool_index, file) for _cue.sfx.play_pool calls."""
    mgr, calls = sfx_playback

    def fake_play(entry, key, pool, pool_index, **kw):
        calls.play.append((key, pool_index, kw.get("file")))
        return "cue_sfx_1"

    mgr.play_pool = fake_play
    return calls.play


@pytest.fixture
def fade_stub(sfx_playback):
    """Record kwargs for _cue.sfx.fade_out calls."""
    mgr, calls = sfx_playback

    def fake_fade(**kw):
        calls.fade.append(kw)
        return []

    mgr.fade_out = fake_fade
    return calls.fade


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
    """Keep every tracked channel alive through _prune_excl_channels."""
    monkeypatch.setattr(_trigger._music, "is_playing", lambda channel="music", **kw: True)


def loop_store():
    return FakeMarkerStore({
        "l_scene.ogg": {"pools": [
            {"files": ["a.ogg"], "frequency": CueLoopFrequency.MEDIUM}]}})


# ---------------------------------------------------------------------------
# _cue_loop_still_playing (moved here from util.py with the trigger engine)
# ---------------------------------------------------------------------------

def test_loop_still_playing_all_silent(monkeypatch):
    monkeypatch.setattr(_music, "is_playing", lambda channel="music", **k: False)
    assert _cue_loop_still_playing(["a", "b"]) is False


def test_loop_still_playing_one_playing(monkeypatch):
    def _is_playing(channel="music", **k):
        return channel == "b"
    monkeypatch.setattr(_music, "is_playing", _is_playing)
    assert _cue_loop_still_playing(["a", "b"]) is True


def test_loop_still_playing_unknown_channel_skipped(monkeypatch):
    def _is_playing(channel="music", **k):
        raise Exception("unknown channel")
    monkeypatch.setattr(_music, "is_playing", _is_playing)
    assert _cue_loop_still_playing(["x"]) is False


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


def test_toggle_active_flips_trigger_and_persists():
    eng = make_engine()
    eng.active = True
    _store.persistent._cue = {"triggers_active": True}
    eng.toggle_active()
    assert eng.active is False
    assert _store.persistent._cue["triggers_active"] is False


def test_toggle_active_reverse():
    eng = make_engine()
    eng.active = False
    _store.persistent._cue = {"triggers_active": False}
    eng.toggle_active()
    assert eng.active is True
    assert _store.persistent._cue["triggers_active"] is True


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

def test_tick_inactive_is_noop(monkeypatch):
    eng = make_engine()
    eng.active = False
    seen = []
    monkeypatch.setattr(eng, "_tick_loop", lambda now, tick, cf, speed, variants: seen.append("loop"))
    monkeypatch.setattr(eng, "_tick_video", lambda cf, layer, speed, variants: seen.append("video"))
    eng.tick("scene.ogg", "movie")
    assert eng._tick_count == 0
    assert seen == []


def test_tick_dispatches_loop_then_video(monkeypatch):
    eng = make_engine()
    seen = []
    monkeypatch.setattr(eng, "_tick_loop", lambda now, tick, cf, speed, variants: seen.append("loop"))
    monkeypatch.setattr(eng, "_tick_video", lambda cf, layer, speed, variants: seen.append("video"))
    eng.tick("scene.ogg", "movie")
    assert eng._tick_count == 1
    assert seen == ["loop", "video"]


# ---------------------------------------------------------------------------
# exclusive helpers
# ---------------------------------------------------------------------------

def test_track_excl_channel_stores_info():
    eng = make_engine()
    eng._track_excl_channel("cue_sfx_1", CUE_EXCL_KIND_ONESHOT, "scene.ogg", None, False)
    assert eng.excl_channels["cue_sfx_1"] == {
        "kind": CUE_EXCL_KIND_ONESHOT, "scene": "scene.ogg", "line": None, "hold": False}


def test_track_excl_channel_none_channel_ignored():
    eng = make_engine()
    eng._track_excl_channel(None, CUE_EXCL_KIND_ONESHOT, "scene.ogg", None, False)
    assert eng.excl_channels == {}


def test_prune_excl_channels_drops_finished():
    eng = make_engine()
    eng.excl_channels = {"ch1": {"kind": CUE_EXCL_KIND_LOOP},
                         "ch2": {"kind": CUE_EXCL_KIND_ONESHOT}}
    eng._prune_excl_channels()  # mock is_playing -> False, so both dropped
    assert eng.excl_channels == {}


def test_prune_excl_channels_keeps_playing(monkeypatch):
    eng = make_engine()
    eng.excl_channels = {"ch1": {"kind": CUE_EXCL_KIND_LOOP}}
    keep_playing(monkeypatch)
    eng._prune_excl_channels()
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
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
    assert eng.loop_states == {}


def test_tick_loop_pool_without_files():
    store = FakeMarkerStore({"l_scene.ogg": {"pools": [{"files": []}]}})
    eng = make_engine(store=store)
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
    assert eng.loop_states == {}


def test_tick_loop_plays_when_ready(monkeypatch, play_stub):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    eng = make_engine(store=loop_store(), markers=FakeMarkers())
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["channels"] == ["cue_sfx_1"]
    assert pst["play_start"] == 100.0
    assert eng.excl_channels["cue_sfx_1"]["kind"] == CUE_EXCL_KIND_LOOP


def test_tick_loop_not_ready_defers(monkeypatch):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 5.0)
    eng = make_engine(store=loop_store(), markers=FakeMarkers())
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
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
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
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
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["ready_at"] == 100.1
    assert pst["blocked_logged"] is True
    assert play_stub == []


def test_tick_loop_wait_defers(monkeypatch, play_stub):
    pick(monkeypatch)
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    keep_playing(monkeypatch)
    store = FakeMarkerStore({"l_scene.ogg": {"pools": [
        {"files": ["a.ogg"], "frequency": CueLoopFrequency.MEDIUM,
         "exclusive": {"start": CueExclusiveStart.WAIT}}]}})
    eng = make_engine(store=store, markers=FakeMarkers())
    eng.excl_channels = {
        "busy": {"kind": CUE_EXCL_KIND_LOOP, "scene": "other.ogg", "line": None, "hold": False}}
    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["ready_at"] == 100.1
    assert play_stub == []


# ---------------------------------------------------------------------------
# _tick_video
# ---------------------------------------------------------------------------

def test_tick_video_no_channel_returns():
    eng = make_engine(vid=FakeVidManager(channel=""))
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert eng._prev_eff_elapsed == -1.0  # untouched


def test_tick_video_wrong_layer_returns():
    eng = make_engine()
    eng._tick_video("scene.ogv", "sprite", 1.0, None)
    assert eng._prev_eff_elapsed == -1.0


def test_tick_video_fires_marker(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["a.ogg"]}])
    eng = make_engine(store=store, markers=markers)
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert play_stub == [("v_scene.ogv", 0, None)]


def test_tick_video_marker_not_refired(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["a.ogg"]}])
    vid = FakeVidManager(elapsed=0.1)
    vid.last_elapsed = 0.1  # not a fresh reset -- dedup set survives
    eng = make_engine(store=store, vid=vid, markers=markers)
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert play_stub == [("v_scene.ogv", 0, None)]

    vid.last_elapsed = 0.1
    vid._elapsed = 0.15
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert play_stub == [("v_scene.ogv", 0, None)]  # no re-fire


def test_tick_video_preview_marker(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    vid = FakeVidManager(elapsed=0.05)
    vid.last_elapsed = 0.05
    repeater = FakeRepeater(dialog_visible=True, preview_sfx_enabled=True,
                            preview_pools=[{"time": 0.0, "files": ["p.ogg"]}])
    eng = make_engine(store=store, vid=vid, markers=FakeMarkers(), repeater=repeater)
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert play_stub == [("v_scene.ogv", 0, None)]


def test_tick_video_restart_clears_played(play_stub):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    vid = FakeVidManager(elapsed=0.05)
    vid.last_elapsed = 0.05
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["a.ogg"]}])
    eng = make_engine(store=store, vid=vid, markers=markers)
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert len(play_stub) == 1
    assert "v_scene.ogv@0.000#1" in eng.played_video_keys

    # restart tick: backward jump detected AFTER the marker loop, so the
    # already-played key is skipped this tick, then the dedup set clears.
    vid.last_elapsed = 5.0
    vid._elapsed = 0.05
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert len(play_stub) == 1  # not re-fired on the restart tick itself

    # next tick: the cleared set lets the time-0 marker fire again.
    vid.last_elapsed = 0.05
    vid._elapsed = 0.05
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    assert len(play_stub) == 2
    assert "v_scene.ogv@0.000#1" in eng.played_video_keys


# ---------------------------------------------------------------------------
# intensity wiring -- hooked pools + global volume scale (slice 3)
# ---------------------------------------------------------------------------

@pytest.fixture
def play_full(sfx_playback):
    """Record (key, pool_index, file, files, volume_mult) for play_pool calls."""
    mgr, calls = sfx_playback

    def fake_play(entry, key, pool, pool_index, **kw):
        calls.play.append((key, pool_index, kw.get("file"), kw.get("files"), kw.get("volume_mult")))
        return "cue_sfx_1"

    mgr.play_pool = fake_play
    return calls.play


def _igroup_engine(cue_env, monkeypatch, store, speed=1.3, variants=(0.7, 1.0, 1.3),
                   markers=None, vid=None, repeater=None):
    """Engine with a real 2-level "Impacts" igroup (soft/, hard/) wired in."""
    from cue_lib.intensity import CueIntensityManager
    m = CueIntensityManager(cue_env.db)
    assert m.create_igroup("Impacts") is None
    assert m.add_folder("Impacts", "soft/") is None
    assert m.add_folder("Impacts", "hard/") is None
    monkeypatch.setattr(_trigger._cue, "intensity", m)
    return make_engine(
        store=store,
        repeater=repeater if repeater is not None else FakeRepeater(),
        speed=FakeSpeedResolver(speed, list(variants)),
        vid=vid if vid is not None else FakeVidManager(),
        markers=markers if markers is not None else FakeMarkers())


def test_tick_loop_hooked_uses_level_folder(cue_env, monkeypatch, play_full):
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    store = FakeMarkerStore({"l_scene.ogg": {"pools": [
        {"files": ["soft/"], "frequency": CueLoopFrequency.MEDIUM}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # 2 levels over [0.7, 1.0, 1.3]: 1.3 -> L2 (hard/), at the level's volume.
    eng._tick_loop(100.0, 1, "scene.ogg", 1.3, [0.7, 1.0, 1.3])
    assert play_full == [("l_scene.ogg", 0, "hard/", None, 1.25)]


def test_tick_loop_level_change_restarts_timer(cue_env, monkeypatch, play_full):
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 5.0)
    store = FakeMarkerStore({"l_scene.ogg": {"pools": [
        {"files": ["soft/"], "frequency": CueLoopFrequency.MEDIUM}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # 0.7 -> L1 (soft/), init delay 5.0 -> ready at 105.0, no fire.
    eng._tick_loop(100.0, 1, "scene.ogg", 0.7, [0.7, 1.0, 1.3])
    pst = eng.loop_states["l_scene.ogg"][0]
    assert pst["ilevel"] == 1
    assert pst["ready_at"] == 105.0
    # Level changes to 2 -- pending fire dropped, timer restarts with the new
    # level's scaled delay (get_delay 2.1 / freq_mult 2.0 -> 1.05).
    eng._tick_loop(100.0, 2, "scene.ogg", 1.3, [0.7, 1.0, 1.3])
    assert pst["ilevel"] == 2
    assert pst["ready_at"] == 101.05


def test_tick_video_hooked_uses_level_folder(cue_env, monkeypatch, play_full):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": []}})
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["soft/"]}])
    eng = _igroup_engine(cue_env, monkeypatch, store, markers=markers)
    eng._tick_video("scene.ogv", "movie", 1.3, [0.7, 1.0, 1.3])
    # 1.3 -> L2: the fire list is the level folder, volume scaled by it.
    assert play_full == [("v_scene.ogv", 0, None, ["hard/"], 1.25)]


def test_tick_video_nonhooked_gets_global_scale(cue_env, monkeypatch, play_full):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": [{"files": ["soft/"]}]}})
    markers = FakeMarkers(markers=[
        {"time": 0.0, "files": ["soft/"]},        # hooked -> own resolution
        {"time": 0.1, "files": ["plain.ogg"]}])   # not hooked -> global scale
    eng = _igroup_engine(cue_env, monkeypatch, store, markers=markers,
                         vid=FakeVidManager(elapsed=0.12))
    eng.tick("scene.ogv", "movie")
    # Both fire at the video's active level volume (1.25); the hooked marker
    # also fires from the resolved level folder.
    assert play_full[0] == ("v_scene.ogv", 0, None, ["hard/"], 1.25)
    assert play_full[1] == ("v_scene.ogv", 1, None, None, 1.25)


def test_tick_loop_nonhooked_gets_global_scale(cue_env, monkeypatch, play_full):
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    store = FakeMarkerStore({
        "v_scene.ogv": {"pools": [{"files": ["soft/"]}]},
        "l_scene.ogv": {"pools": [{"files": ["plain.ogg"], "frequency": CueLoopFrequency.MEDIUM}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    eng.tick("scene.ogv", "movie")
    # Non-hooked loop plays its own file at the video's global scale.
    assert play_full == [("l_scene.ogv", 0, "plain.ogg", None, 1.25)]


def test_fire_context_gets_global_scale_during_video(cue_env, monkeypatch, play_full):
    store = FakeMarkerStore({
        "v_scene.ogv": {"pools": [{"files": ["soft/"]}]},
        "d_scene.ogv__hi": {"pools": [{"files": ["plain.ogg"]}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # Dialogue one-shot firing while the video (with intensity) is current.
    _trigger._cue.ctx.current_file = "scene.ogv"
    try:
        eng.fire_context("d_scene.ogv__hi")
    finally:
        _trigger._cue.ctx.current_file = ""
    assert play_full == [("d_scene.ogv__hi", 0, "plain.ogg", None, 1.25)]


def test_fire_context_no_video_no_scale(cue_env, monkeypatch, play_full):
    store = FakeMarkerStore({"d_img__hi": {"pools": [{"files": ["plain.ogg"]}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # Image context -- no video entry for the current file -> no intensity.
    _trigger._cue.ctx.current_file = "img.png"
    try:
        eng.fire_context("d_img__hi")
    finally:
        _trigger._cue.ctx.current_file = ""
    assert play_full == [("d_img__hi", 0, "plain.ogg", None, 1.0)]


# ==========================================================================
# per-video toggles (slice 4) -- master / sfx-levels / volume gate the path
# ==========================================================================

def test_tick_loop_master_off_plays_pool_folder(cue_env, monkeypatch, play_full):
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    store = FakeMarkerStore({
        "v_scene.ogv": {"pools": [{"files": ["soft/"]}], "intensity": {"enabled": False}},
        "l_scene.ogv": {"pools": [{"files": ["soft/"], "frequency": CueLoopFrequency.MEDIUM}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # Master off -> the pool plays its own folder plainly, unscaled.
    eng._tick_loop(100.0, 1, "scene.ogv", 1.3, [0.7, 1.0, 1.3])
    assert play_full == [("l_scene.ogv", 0, "soft/", None, 1.0)]


def test_tick_loop_sfx_levels_off_keeps_scaling(cue_env, monkeypatch, play_full):
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    store = FakeMarkerStore({
        "v_scene.ogv": {"pools": [{"files": ["soft/"]}], "intensity": {"sfx_levels": False}},
        "l_scene.ogv": {"pools": [{"files": ["soft/"], "frequency": CueLoopFrequency.MEDIUM}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # sfx_levels off -> the pool's own folder plays, but the level still
    # drives volume (1.3 -> L2 -> 1.25).
    eng._tick_loop(100.0, 1, "scene.ogv", 1.3, [0.7, 1.0, 1.3])
    assert play_full == [("l_scene.ogv", 0, "soft/", None, 1.25)]


def test_tick_video_volume_off_unscaled(cue_env, monkeypatch, play_full):
    store = FakeMarkerStore({"v_scene.ogv": {"pools": [{"files": ["soft/"]}],
                                              "intensity": {"volume": False}}})
    markers = FakeMarkers(markers=[{"time": 0.0, "files": ["soft/"]}])
    eng = _igroup_engine(cue_env, monkeypatch, store, markers=markers)
    eng._tick_video("scene.ogv", "movie", 1.3, [0.7, 1.0, 1.3])
    # Volume toggle off -> still the level folder, but at unscaled volume.
    assert play_full == [("v_scene.ogv", 0, None, ["hard/"], 1.0)]


def test_fire_context_master_off_unscaled(cue_env, monkeypatch, play_full):
    store = FakeMarkerStore({
        "v_scene.ogv": {"pools": [{"files": ["soft/"]}], "intensity": {"enabled": False}},
        "d_scene.ogv__hi": {"pools": [{"files": ["plain.ogg"]}]}})
    eng = _igroup_engine(cue_env, monkeypatch, store)
    # Dialogue one-shot during the video: master off -> no global scale.
    _trigger._cue.ctx.current_file = "scene.ogv"
    try:
        eng.fire_context("d_scene.ogv__hi")
    finally:
        _trigger._cue.ctx.current_file = ""
    assert play_full == [("d_scene.ogv__hi", 0, "plain.ogg", None, 1.0)]


# ==========================================================================
# _cue_effective_delay -- clamp(base_delay / mult, [0.2, 6])
# (moved here from the collapsed scaling.py; the loop timer is its caller)
# ==========================================================================

def test_delay_level1_identity():
    assert _cue_effective_delay(3.0, 1.0) == 3.0


def test_delay_faster_at_higher_level():
    assert _cue_effective_delay(3.0, 2.0) == 1.5


def test_delay_clamped_to_fastest():
    assert _cue_effective_delay(0.3, 2.0) == pytest.approx(CUE_INTENSITY_DELAY_MIN)


def test_delay_clamped_to_slowest():
    assert _cue_effective_delay(9.0, 1.0) == pytest.approx(CUE_INTENSITY_DELAY_MAX)


def test_delay_base_already_fastest_stays():
    assert _cue_effective_delay(CUE_INTENSITY_DELAY_MIN, 2.0) == pytest.approx(CUE_INTENSITY_DELAY_MIN)


def test_delay_base_already_slowest_stays():
    assert _cue_effective_delay(CUE_INTENSITY_DELAY_MAX, 1.0) == pytest.approx(CUE_INTENSITY_DELAY_MAX)


def test_delay_nonpositive_multiplier_guarded():
    # A malformed (<= 0) multiplier would divide by zero; treat as identity.
    assert _cue_effective_delay(3.0, 0.0) == 3.0
    assert _cue_effective_delay(3.0, -1.0) == 3.0
