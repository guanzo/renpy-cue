# -*- coding: utf-8 -*-
# Tests for cue_lib.video.auto_speed -- the procedural speed-sequence
# generator (CueAutoSpeedGenerator) and its preset metadata.
#
# The generator is pure given random.seed(): every preset builds a list of
# speeds (rungs) over a target time-unit budget, using the module-level
# random module.  Tests seed it for determinism and assert structural
# invariants (valid rungs, guaranteed peak/bottom/spike visits) rather than
# exact sequences -- those invariants hold for ANY seed, so the tests are
# stable against generator tweaks that only change the details.
#
# The generator is wired to the REAL resolver / sequence / store (like
# test_speed.py) so enabled_speeds, toggle_speed, select_preset, and the
# AUTO-mode lifecycle exercise the exact code paths production uses.

import os
import random as _random
import types

import pytest

import renpy.config as _config

from cue_lib.state import CueContext
from cue_lib.paths import CuePaths
from cue_lib.db import CueDatabase
from cue_lib.marker_store import CueMarkerStore
from cue_lib.video.video import CueVideoManager
from cue_lib.video.speed import (
    CueSpeedMode, CueSpeedToast, CueVidSpeedResolver, CueVidSpeedSequence,
)
from cue_lib.video.auto_speed import (
    CueAutoSpeedGenerator, _cue_auto_preset_description, _cue_auto_preset_label,
)
from cue_lib.constants import CUE_AUTO_SPEED_MIN_VARIANTS, CUE_DEFAULT_VIDEO_SPEED
from cue_lib.util import create_vid_key

import cue_lib.state as _state


def _write(path, data=b"video"):
    """Create a file on disk (creating parent dirs)."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Per-test isolation: point the toast's singleton at the test resolver."""
    monkeypatch.setattr(_state._cue, "speed_resolver", None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real speed-variant manager graph plus a bound auto-speed generator."""
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))

    ctx = CueContext()
    paths = CuePaths(str(tmp_path / "cue_root"), game_id="test_game")
    db = CueDatabase(paths)
    db.open()
    store = CueMarkerStore(db, paths)
    vid = CueVideoManager(ctx)
    seq = CueVidSpeedSequence(ctx, store, vid)
    toast = CueSpeedToast()
    resolver = CueVidSpeedResolver(ctx, store, vid, seq, toast, paths)
    seq.bind(resolver, None)
    gen = CueAutoSpeedGenerator(ctx, store, resolver, vid, seq)
    seq.bind(resolver, gen)

    video_dir = paths.video_dir
    os.makedirs(video_dir, exist_ok=True)
    base_fs = os.path.join(video_dir, "scene.webm")
    tag = "scene"

    _prev = getattr(_state._cue, "speed_resolver", None)
    _state._cue.speed_resolver = resolver
    try:
        yield types.SimpleNamespace(
            ctx=ctx, paths=paths, db=db, store=store, vid=vid,
            seq=seq, toast=toast, resolver=resolver, gen=gen,
            video_dir=video_dir, base_fs=base_fs, tag=tag,
        )
    finally:
        _state._cue.speed_resolver = _prev


def _variants(env, speeds):
    """Write the base file plus every requested variant; return paths keyed
    by speed (1.0 is not a variant -- it points at the base file)."""
    _write(env.base_fs)
    out = {}
    for sp in speeds:
        v = env.resolver.variant_path(env.base_fs, sp)
        if sp != CUE_DEFAULT_VIDEO_SPEED:
            _write(v)
            out[sp] = v
    return out


def _compact(gen):
    """Shrink the generator so a test runs fast and deterministically."""
    gen.min_duration_tu = 6.0
    gen.max_duration_tu = 7.0
    gen.min_hold_tu = 0.5
    gen.max_hold_tu = 1.0


def _movie_env(env):
    """Wire the movie context so enabled_speeds resolves real variants."""
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs


# ==========================================================================
# Preset metadata
# ==========================================================================


def test_preset_label():
    assert _cue_auto_preset_label("roller_coaster") == "Roller Coaster"
    assert _cue_auto_preset_label("bogus") == "bogus"
    assert _cue_auto_preset_label(None) == "Custom"
    assert _cue_auto_preset_label("") == "Custom"


def test_preset_description():
    assert _cue_auto_preset_description("tease") == (
        "Mostly slow with sudden, brief spikes of speed")
    assert _cue_auto_preset_description("bogus") == ""


# ==========================================================================
# generate -- fallback and structure
# ==========================================================================


def test_generate_too_few_speeds_fallback():
    ctx = CueContext()
    paths = CuePaths("/tmp/none", game_id="x")
    gen = CueAutoSpeedGenerator(ctx, None, None, None, None)
    _random.seed(1)
    gen.active_preset = "roller_coaster"
    assert gen.generate([1.0, 1.5, 2.0]) == [1.0] * 8
    assert gen.generate([]) == [CUE_DEFAULT_VIDEO_SPEED]


# Structural invariants: every assertion holds for ANY seed, so the tests
# don't need to know (or freeze) a particular random stream.
PRESET_STRUCTURAL = [
    # (preset, n, invariant) -- speeds has n entries; s is the generated list
    ("roller_coaster", 5, lambda s, sp: s and s[0] == sp[0] and sp[-1] in s),
    ("build_up", 5, lambda s, sp: s and sp[-1] in s),
    ("cool_down", 5, lambda s, sp: s and sp[0] in s),
    ("slow_groove", 5, lambda s, sp: s and sp[-1] not in s and sp[-2] not in s),
    ("fast_frenzy", 5, lambda s, sp: s and sp[0] not in s and sp[1] not in s),
    ("tease", 5, lambda s, sp: s and sp[-1] in s),
    ("plateau", 5, lambda s, sp: bool(s)),
    ("random_walk", 5, lambda s, sp: bool(s)),
    ("edge", 5, lambda s, sp: s and sp[-1] not in s and sp[-2] in s),
    ("anchor", 5, lambda s, sp: bool(s)),
    ("pulse", 5, lambda s, sp: s and len(set(s)) >= 2),
]


@pytest.mark.parametrize("preset,n,invariant", PRESET_STRUCTURAL,
                         ids=[p for p, _, _ in PRESET_STRUCTURAL])
def test_preset_structure(env, preset, n, invariant):
    _random.seed(7)
    _compact(env.gen)
    env.gen.active_preset = preset
    speeds = [0.5, 1.0, 1.5, 2.0, 2.5][:n]
    seq = env.gen.generate(speeds)
    assert invariant(seq, speeds)


def test_generate_uses_only_valid_rungs(env):
    _random.seed(3)
    _compact(env.gen)
    env.gen.active_preset = "random_walk"
    speeds = [0.5, 1.0, 1.5, 2.0, 2.5]
    seq = env.gen.generate(speeds)
    assert seq
    assert all(s in speeds for s in seq)


def test_generate_custom_mode_uses_walk(env):
    _random.seed(3)
    _compact(env.gen)
    env.gen.active_preset = None
    speeds = [0.5, 1.0, 1.5, 2.0, 2.5]
    seq = env.gen.generate(speeds)
    assert seq
    assert all(s in speeds for s in seq)


def test_generate_custom_drift_high_reaches_top(env):
    _random.seed(5)
    _compact(env.gen)
    env.gen.active_preset = None
    env.gen.custom_drift = 1.0  # strongly upward bias
    speeds = [0.5, 1.0, 1.5, 2.0, 2.5]
    seq = env.gen.generate(speeds)
    # With n=5 and a large drift, the walk spends time above the center band.
    assert speeds[0] not in seq or any(s >= speeds[1] for s in seq)


def test_generate_target_tu_scales_length(env):
    _random.seed(9)
    env.gen.active_preset = "plateau"
    env.gen.min_hold_tu = env.gen.max_hold_tu = 0.5
    speeds = [0.5, 1.0, 1.5, 2.0, 2.5]

    env.gen.min_duration_tu = env.gen.max_duration_tu = 4.0
    short = env.gen.generate(speeds)

    env.gen.min_duration_tu = env.gen.max_duration_tu = 12.0
    _random.seed(9)
    long = env.gen.generate(speeds)

    assert len(long) > len(short)


# ==========================================================================
# Shared helpers
# ==========================================================================


def test_emit_hold_rounds_plays(env):
    seq = []
    tu = env.gen._emit_hold(seq, [1.0, 2.0], 1, 1.0)
    assert seq == [2.0, 2.0]
    assert tu == 1.0


def test_emit_hold_min_one_play(env):
    seq = []
    tu = env.gen._emit_hold(seq, [1.0], 0, 0.3)
    assert seq == [1.0]
    assert tu == 1.0


def test_take_hold_clamps_to_remaining(env):
    gen = env.gen
    gen.min_hold_tu = gen.max_hold_tu = 2.0
    seq = []
    tu = gen._take_hold(seq, [1.0, 1.5], 0, 1.0)
    assert tu <= 1.0
    assert seq == [1.0]


def test_take_hold_clamps_to_video_duration(env):
    gen = env.gen
    gen.min_hold_tu = gen.max_hold_tu = 3.0
    gen._video_duration = 4.0  # max_real_s 10.0 -> max hold 2.5 TU
    seq = []
    tu = gen._take_hold(seq, [1.0], 0, 50.0)
    assert 0 < tu <= 2.5


def test_take_hold_no_video_duration_no_cap(env):
    gen = env.gen
    gen.min_hold_tu = gen.max_hold_tu = 1.0
    seq = []
    tu = gen._take_hold(seq, [1.0], 0, 50.0)
    assert tu == 1.0


def test_should_stay_respects_max_stays(env):
    gen = env.gen
    _random.seed(1)
    assert gen._should_stay(0, 1.0) is True
    assert gen._should_stay(2, 1.0) is False  # max_stays (2) reached
    assert gen._should_stay(0, 0.0) is False


# ==========================================================================
# Legacy _walk internals
# ==========================================================================


def test_weighted_pick_zero_total(env):
    assert env.gen._weighted_pick(0.0, 0.0) == 0


def test_weighted_pick_domain(env):
    _random.seed(2)
    res = [env.gen._weighted_pick(0.9, 0.1) for _ in range(50)]
    assert all(r in (-1, 1) for r in res)


def test_pick_direction_below_band_biases_up(env):
    _random.seed(4)
    gen = env.gen
    # idx 0 sits below the target band (center 0.5, intensity 0.7, n=5), so
    # direction is up-biased even accounting for the ~15% stay chance.
    res = [gen._pick_direction(0, 5, 0.0, 0.7, 0.4, 0.5, 0, 0) for _ in range(200)]
    assert 1 in res
    assert res.count(1) > res.count(-1)


def test_pick_direction_at_top_avoids_stuck(env):
    _random.seed(6)
    gen = env.gen
    # Momentum active at the top rung: stays legal and mostly reverses.
    res = [gen._pick_direction(4, 5, 0.0, 0.7, 0.4, 0.5, -1, 1) for _ in range(200)]
    assert all(r in (-1, 0, 1) for r in res)


# ==========================================================================
# enabled_speeds / toggle_speed
# ==========================================================================


def test_enabled_speeds_all_when_nothing_disabled(env):
    _movie_env(env)
    _variants(env, [1.5, 2.0, 2.5])
    assert env.gen.enabled_speeds == [1.0, 1.5, 2.0, 2.5]
    assert env.gen.is_speed_enabled(1.5) is True


def test_enabled_speeds_empty_without_tag(env):
    assert env.gen.enabled_speeds == []
    assert env.gen._get_disabled() == set()


def test_toggle_speed_roundtrip(env):
    _movie_env(env)
    _variants(env, [1.5, 2.0, 2.5, 3.0])  # 5 variants -> can disable one
    env.gen.toggle_speed(1.5)
    assert env.gen.enabled_speeds == [1.0, 2.0, 2.5, 3.0]
    assert env.gen.is_speed_enabled(1.5) is False
    env.gen.toggle_speed(1.5)
    assert env.gen.enabled_speeds == [1.0, 1.5, 2.0, 2.5, 3.0]
    assert env.gen.is_speed_enabled(1.5) is True


def test_toggle_speed_min_variant_guard(env):
    _movie_env(env)
    _variants(env, [1.5, 2.0, 2.5])  # exactly 4 variants
    env.gen.toggle_speed(1.5)
    assert env.gen.is_speed_enabled(1.5) is True  # refused: would drop below min


def test_toggle_speed_persists_disabled(env):
    _movie_env(env)
    _variants(env, [1.5, 2.0, 2.5, 3.0])
    env.gen.toggle_speed(1.5)
    assert env.seq.get_disabled_auto_speeds(env.tag) == {1.5}


# ==========================================================================
# Lifecycle: select_preset / shuffle / _regenerate / on_wrap_around
# ==========================================================================


def _auto_env(env):
    """Wire a 5-variant movie in AUTO mode so regenerate/start_auto run."""
    _movie_env(env)
    _variants(env, [1.5, 2.0, 2.5, 3.0])
    env.seq.set_mode(CueSpeedMode.AUTO)


def test_select_preset_persists_sequence(env):
    _auto_env(env)
    _random.seed(10)
    env.gen.select_preset("build_up")
    assert env.gen.active_preset == "build_up"
    assert env.gen.is_shuffle_mode is False
    entry = env.store.get(create_vid_key(env.tag))
    seq = entry["speed_sequence"]
    assert seq
    assert all(s in env.gen.enabled_speeds for s in seq)


def test_select_preset_unknown_ignored(env):
    env.ctx.current_file = env.tag
    env.gen.select_preset("bogus")
    assert env.gen.active_preset == "roller_coaster"


def test_shuffle_picks_from_pool(env):
    _auto_env(env)
    _random.seed(11)
    env.gen.shuffle()
    assert env.gen.is_shuffle_mode is True
    assert env.gen.active_preset in env.gen.shuffle_pool


def test_regenerate_noop_when_not_auto(env):
    _movie_env(env)
    _variants(env, [1.5, 2.0, 2.5, 3.0])
    env.gen.select_preset("build_up")  # mode is SINGLE -> no sequence written
    entry = env.store.get(create_vid_key(env.tag))
    assert entry is None or "speed_sequence" not in entry


def test_on_wrap_around_regenerates(env):
    _auto_env(env)
    _random.seed(12)
    env.gen.on_wrap_around()
    entry = env.store.get(create_vid_key(env.tag))
    assert entry["speed_sequence"]
    assert env.seq.active_tag == env.tag


def test_on_wrap_around_shuffle_rerandomizes(env):
    _auto_env(env)
    _random.seed(13)
    env.gen.is_shuffle_mode = True
    env.gen.on_wrap_around()
    assert env.gen.active_preset in env.gen.shuffle_pool


def test_on_wrap_around_insufficient_variants_noop(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _variants(env, [1.5])  # only 2 variants -> below min
    env.gen.on_wrap_around()
    assert env.seq.active_tag is None


def test_on_wrap_around_respects_disabled_speeds(env):
    _auto_env(env)
    env.gen.toggle_speed(1.5)  # disable 1.5 (5 variants -> allowed)
    _random.seed(14)
    env.gen.on_wrap_around()
    entry = env.store.get(create_vid_key(env.tag))
    assert 1.5 not in entry["speed_sequence"]
    assert all(s in env.gen.enabled_speeds for s in entry["speed_sequence"])
