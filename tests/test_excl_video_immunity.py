# -*- coding: utf-8 -*-
# Video-marker SFX (v_key pools) are immune to exclusive cut-ins.
#
# fire_context's one-shot FADE sweep fades out-of-group one-shots and loops on
# the shared _cue_ channels -- but never SFX fired by video markers.  Video SFX
# are tracked in excl_channels under CUE_EXCL_KIND_VIDEO and spared by the
# sweep, so an exclusive dialogue cut-in never stops a v_-marker sound.
#
# These tests drive a real CueSfxManager (real channel scan + real fade_out)
# and fire video markers through _tick_video so the tracking path is the one
# under test.

import types

import pytest

import renpy.audio.music as _music
import renpy.store as _store

import cue_lib.runtime as _runtime
import cue_lib.trigger as _trigger
import cue_lib.util as _util
from cue_lib.trigger import CueTriggerEngine
from cue_lib.constants import CueExclusiveStart
from cue_lib.audio.sfx_manager import CueSfxManager

from tests.fakes import FakeMarkerStore, FakeMarkers, FakeRepeater, FakeSpeedResolver, FakeVidManager, make_runtime_cue


@pytest.fixture
def cue(monkeypatch, tmp_path):
    """Fresh _cue graph per test (mirrors test_runtime.py's fixture)."""
    root = str(tmp_path / "cue_root")
    c = make_runtime_cue(root=root, audio_dir=root + "/audio/")
    monkeypatch.setattr(_runtime, "_cue", c)
    monkeypatch.setattr(_trigger, "_cue", c)
    monkeypatch.setattr(_util, "_cue", c)
    _store.persistent._cue = None
    _music._reset_all()
    return c


@pytest.fixture(autouse=True)
def _identity_resolve_files(monkeypatch):
    import cue_lib.intensity.intensity as _intensity

    monkeypatch.setattr(_trigger, "_cue_resolve_files", lambda files: list(files))
    monkeypatch.setattr(_intensity, "_cue_resolve_files", lambda files: list(files))


@pytest.fixture(autouse=True)
def _no_intensity(cue, monkeypatch):
    """Stub _cue.intensity so no pool hooks (matches test_trigger_engine)."""
    stub = types.SimpleNamespace(
        resolve_pool_intensity=lambda *a, **k: None,
        resolve_video_intensity=lambda *a, **k: None,
        flags_from_entry=lambda *a, **k: None,
    )
    monkeypatch.setattr(cue, "intensity", stub)


@pytest.fixture
def real_sfx(cue, monkeypatch):
    """Real CueSfxManager wired in as _cue.sfx so fade_out sweeps real channels.

    cue.markers.resolve_pool is replaced with one that carries the pool's
    files/exclusive (the make_runtime_cue default only exposes
    trigger_on_shake)."""

    def _resolve_pool(pool):
        excl = pool.get("exclusive", {})
        if not isinstance(excl, dict):
            excl = {}
        return types.SimpleNamespace(
            files=pool.get("files", []),
            volume=pool.get("volume", 1.0),
            frequency=pool.get("frequency", 1),
            trigger_on_shake=pool.get("trigger_on_shake", False),
            exclusive=types.SimpleNamespace(
                start=excl.get("start", 0), hold=excl.get("hold", False), group=excl.get("group", 0)
            ),
        )

    cue.markers.resolve_pool = _resolve_pool
    mgr = CueSfxManager(cue.paths, types.SimpleNamespace(), cue.volume, cue.ctx, cue._has_relative_volume)
    mgr.bind_markers(cue.markers)
    cue.sfx = mgr
    return mgr


def _channel_playing(filename):
    """Channel currently playing a file containing `filename`, or None."""
    for ch, st in _music._registry.items():
        if st.get("playing") and filename in st["playing"]:
            return ch
    return None


def _video_still_playing(ch):
    """True if `ch` is still playing the v:-marker SFX (not cut + reused)."""
    p = _music.get_playing(channel=ch)
    return p is not None and "moan.ogg" in p


def _fire_video_sfx(eng):
    """Fire the t=0 video marker and return the channel it played on."""
    eng._tick_video("scene.ogv", "movie", 1.0, None)
    return _channel_playing("moan.ogg")


def _excl_dlg_engine(store):
    return CueTriggerEngine(
        store,
        FakeRepeater(),
        FakeSpeedResolver(),
        FakeVidManager(),
        markers=FakeMarkers(markers=[{"time": 0.0, "files": ["moan.ogg"]}]),
    )


def test_excl_dlg_fade_does_not_cut_video_sfx(cue, real_sfx):
    """Exclusive dlg cut-in must not fade a playing v:-key marker."""
    store = FakeMarkerStore(
        {"d_scene.ogv__L1": {"pools": [{"files": ["dlg.ogg"], "exclusive": {"start": CueExclusiveStart.FADE}}]}}
    )
    eng = _excl_dlg_engine(store)

    video_ch = _fire_video_sfx(eng)
    assert video_ch is not None, "v:-marker should be playing"

    eng.fire_context("d_scene.ogv__L1")

    assert _video_still_playing(video_ch), "exclusive dlg cut-in must not fade a playing v:-key marker"


def test_excl_dlg_stale_channel_reuse_video_survives(cue, real_sfx):
    """Regression: dlg on a channel -> channel frees -> video claims it ->
    same dlg fires again.  The video must survive (channel reuse can't make a
    stale dlg 'friend' spare or cut it)."""
    store = FakeMarkerStore(
        {"d_scene.ogv__L1": {"pools": [{"files": ["dlg.ogg"], "exclusive": {"start": CueExclusiveStart.FADE}}]}}
    )
    eng = _excl_dlg_engine(store)

    # First dlg fire claims _cue_1 and tracks it as an exclusive friend.
    eng.fire_context("d_scene.ogv__L1")
    dlg_ch = _channel_playing("dlg.ogg")
    assert dlg_ch is not None
    assert _music.is_playing(channel=dlg_ch)

    # The dlg finishes; its channel frees up.
    _music.stop(channel=dlg_ch)
    assert not _music.is_playing(channel=dlg_ch)

    # The v:-marker SFX claims the freed channel (same reuse the debug.log hit).
    video_ch = _fire_video_sfx(eng)
    assert video_ch == dlg_ch, "video must reuse the freed dlg channel"

    # Same dlg fires again -- its fade sweep must spare the video.
    eng.fire_context("d_scene.ogv__L1")

    assert _video_still_playing(video_ch), "v:-marker must survive the re-fired exclusive dlg"


def test_excl_loop_fade_leaves_video_sfx(cue, real_sfx, monkeypatch):
    """An exclusive loop's cut-in fades only loops -- never video SFX."""
    monkeypatch.setattr(_trigger._random, "uniform", lambda a, b: 0.0)
    store = FakeMarkerStore(
        {
            "l_scene.ogg": {
                "pools": [{"files": ["loop.ogg"], "frequency": 1, "exclusive": {"start": CueExclusiveStart.FADE}}]
            }
        }
    )
    eng = _excl_dlg_engine(store)

    video_ch = _fire_video_sfx(eng)
    assert video_ch is not None

    eng._tick_loop(100.0, 1, "scene.ogg", 1.0, None)

    assert _video_still_playing(video_ch), "loop cut-in must not fade video SFX"


def test_excl_dlg_fade_still_cuts_outgroup_oneshot(cue, real_sfx):
    """Kept behavior: an exclusive dlg cut-in still fades an out-group one-shot."""
    store = FakeMarkerStore(
        {
            "d_scene.ogv__L1": {"pools": [{"files": ["dlg.ogg"], "exclusive": {"start": CueExclusiveStart.FADE}}]},
            "d_scene.ogv__L2": {"pools": [{"files": ["dlg2.ogg"], "exclusive": {"start": CueExclusiveStart.FADE}}]},
        }
    )
    eng = _excl_dlg_engine(store)

    eng.fire_context("d_scene.ogv__L1")
    ch = _channel_playing("dlg.ogg")
    assert ch is not None

    eng.fire_context("d_scene.ogv__L2")

    assert _channel_playing("dlg.ogg") is None, "a new exclusive line must still cut the previous one-shot"


def test_excl_dlg_play_does_not_fade_video(cue, real_sfx):
    """Control: exclusive with start=PLAY skips the sweep entirely."""
    store = FakeMarkerStore(
        {"d_scene.ogv__L1": {"pools": [{"files": ["dlg.ogg"], "exclusive": {"start": CueExclusiveStart.PLAY}}]}}
    )
    eng = _excl_dlg_engine(store)

    video_ch = _fire_video_sfx(eng)
    assert video_ch is not None

    eng.fire_context("d_scene.ogv__L1")

    assert _video_still_playing(video_ch), "PLAY mode should leave the v:-marker alone"
