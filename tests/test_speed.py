# -*- coding: utf-8 -*-
# Tests for cue_lib.video.speed -- CueVidSpeedResolver bookkeeping, the
# CueVidSpeedSequence state machine, and the seamless-transition control flow
# (set_speed / resolve / _movie_for / _cue_seamless_play_callback).
#
# The resolver and sequence are wired to the REAL store / video manager (not
# fakes) so the tests exercise the exact code paths production uses, against
# tmp_path variant files and the stateful mock music registry.  CueSpeedToast
# dereferences the module-level _cue singleton, so the fixture points it at
# the test resolver.

import os
import types

import pytest

import renpy.config as _config
import renpy.audio.music as _music_mock
import renpy.audio.audio as _audio_mock

from renpy.store import persistent
from renpy.display.video import Movie

from cue_lib.state import CueContext
from cue_lib.paths import CuePaths
from cue_lib.db import CueDatabase
from cue_lib.marker_store import CueMarkerStore
from cue_lib.video.video import CueVideoManager
from cue_lib.video.speed import (
    CUE_TOAST_DURATION_SEAMLESS,
    CueSpeedMode,
    CueSpeedToast,
    CueVidSpeedResolver,
    CueVidSpeedSequence,
    _cue_capture_kwargs,
    _cue_seamless_play_callback,
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


def _make_orig(base_fs):
    """A Movie stub with the surface _cue_capture_kwargs reads (size etc.)."""
    m = Movie(play=base_fs, channel="movie")
    m.size = (1280, 720)
    return m


class FakeAutoSpeed(object):
    """Auto-speed generator double: enabled_speeds drives start_auto's
    min-variant guard, generate returns a canned sequence, on_wrap_around
    records its call (tick's AUTO wrap-around branch)."""

    def __init__(self, enabled=None, generated=None):
        self.enabled_speeds = enabled if enabled is not None else []
        self._generated = generated if generated is not None else []
        self.wrap_calls = 0

    def generate(self, available):
        return self._generated

    def on_wrap_around(self):
        self.wrap_calls += 1


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Per-test isolation: fresh persistent._cue, music registry, audio channels."""
    monkeypatch.setattr(persistent, "_cue", {})
    _music_mock._reset_all()
    _audio_mock.channels.clear()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real speed-variant manager graph against tmp paths.

    base_fs lives in paths.video_dir so variant_path() at 1.0 (the original)
    and non-1.0 speeds (video_dir + suffix) both resolve to existing files.
    """
    root = str(tmp_path / "cue_root")
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))

    ctx = CueContext()
    paths = CuePaths(root, game_id="test_game")
    db = CueDatabase(paths)
    db.open()
    store = CueMarkerStore(db, paths)
    vid = CueVideoManager(ctx)
    seq = CueVidSpeedSequence(ctx, store, vid)
    toast = CueSpeedToast()
    resolver = CueVidSpeedResolver(ctx, store, vid, seq, toast, paths)
    seq.bind(resolver, None)

    video_dir = paths.video_dir
    os.makedirs(video_dir, exist_ok=True)
    base_fs = os.path.join(video_dir, "scene.webm")
    # current_file is the displayable tag name (flat, no slash) in production
    # (_cue_get_top_layer returns the image tag), so a flat tag keeps the
    # store keys inside marker_dir without needing nested prefix dirs.
    tag = "scene"

    # CueSpeedToast.show() dereferences the module-level singleton. Point it
    # at the test resolver so set_speed/resolve drive the toast cleanly.
    _prev = getattr(_state._cue, "speed_resolver", None)
    _state._cue.speed_resolver = resolver
    try:
        yield types.SimpleNamespace(
            ctx=ctx, paths=paths, db=db, store=store, vid=vid,
            seq=seq, toast=toast, resolver=resolver,
            video_dir=video_dir, base_fs=base_fs, tag=tag,
            music=_music_mock,
        )
    finally:
        _state._cue.speed_resolver = _prev


def _write_variants(env, speeds):
    """Write the base file plus every requested variant on disk; returns the
    variant paths keyed by speed."""
    _write(env.base_fs)
    out = {}
    for sp in speeds:
        v = env.resolver.variant_path(env.base_fs, sp)
        if sp != CUE_DEFAULT_VIDEO_SPEED:
            _write(v)
            out[sp] = v
    return out


def _set_movie(env, path, pos=0.5):
    """Drive the mock channel into a playing state."""
    st = env.music._registry.setdefault("movie", {})
    st["playing"] = path
    st["position"] = pos


# ==========================================================================
# Resolver -- pure path utilities
# ==========================================================================


def test_split_ext_keeps_double_ext():
    assert CueVidSpeedResolver._split_ext("scene.cue.webm") == ("scene.cue", ".webm")


def test_split_ext_defaults_webm():
    assert CueVidSpeedResolver._split_ext("scene") == ("scene", ".webm")


def test_suffix_variant_format():
    assert CueVidSpeedResolver._suffix_variant(1.5, ".webm") == "_cue1.5x.webm"
    assert CueVidSpeedResolver._suffix_variant(2.0, ".mp4") == "_cue2.0x.mp4"


def test_parse_variant_speed_valid():
    parse = CueVidSpeedResolver._parse_variant_speed
    assert parse("scene_cue1.5x.webm", "scene", ".webm") == 1.5
    assert parse("scene_cue2.0x.webm", "scene", ".webm") == 2.0


def test_parse_variant_speed_rejects_non_variants():
    parse = CueVidSpeedResolver._parse_variant_speed
    assert parse("scene.webm", "scene", ".webm") is None
    assert parse("scene_cue1.5x.mp4", "scene", ".webm") is None
    assert parse("scene_otherx.webm", "scene", ".webm") is None


def test_variant_path_default_speed_abs(env):
    p = env.resolver.variant_path(env.base_fs, CUE_DEFAULT_VIDEO_SPEED)
    assert p == os.path.normpath(env.base_fs).replace("\\", "/")


def test_variant_path_default_speed_relative(env, tmp_path):
    p = env.resolver.variant_path("scene.webm", CUE_DEFAULT_VIDEO_SPEED)
    assert p == os.path.normpath(os.path.join(str(tmp_path), "scene.webm")).replace("\\", "/")


def test_variant_path_other_speed_goes_to_video_dir(env):
    p = env.resolver.variant_path(env.base_fs, 1.5)
    assert p == env.video_dir + "scene_cue1.5x.webm"


def test_is_variant_of(env):
    r = env.resolver
    v15 = r.variant_path(env.base_fs, 1.5)
    assert r.is_variant_of(v15, env.base_fs) is True
    assert r.is_variant_of(env.base_fs, env.base_fs) is True
    assert r.is_variant_of("other.mp4", env.base_fs) is False
    assert r.is_variant_of("", env.base_fs) is False
    assert r.is_variant_of(v15, "") is False


def test_preset_speeds():
    assert CueVidSpeedResolver.preset_speeds() == [0.5, 1.5, 2.0]


# ==========================================================================
# Resolver -- speed prefs
# ==========================================================================


def test_speed_pref_defaults_to_default_speed(env):
    assert env.resolver._get_speed_pref(env.tag) == CUE_DEFAULT_VIDEO_SPEED
    assert env.resolver.speed_for(env.tag) == CUE_DEFAULT_VIDEO_SPEED
    assert env.resolver._get_speed_pref("") == CUE_DEFAULT_VIDEO_SPEED


def test_speed_pref_set_and_read(env):
    env.resolver._set_speed_pref(env.tag, 1.5)
    assert env.resolver._get_speed_pref(env.tag) == 1.5
    assert env.resolver.speed_for(env.tag) == 1.5
    entry = env.store.get(create_vid_key(env.tag))
    assert entry["speed_pref"] == 1.5


def test_speed_pref_empty_tag_noop(env):
    env.resolver._set_speed_pref("", 1.5)
    assert env.resolver._get_speed_pref("") == CUE_DEFAULT_VIDEO_SPEED


def test_speed_pref_falls_back_through_tag_prefix(env):
    child = env.tag + " variant"
    env.resolver.paths[child] = env.base_fs
    env.resolver._set_speed_pref(child, 2.0)
    assert env.resolver._get_speed_pref(env.tag) == 2.0


def test_get_current_speed(env):
    env.ctx.current_file = env.tag
    assert env.resolver.get_current_speed() == CUE_DEFAULT_VIDEO_SPEED
    env.resolver._set_speed_pref(env.tag, 1.5)
    assert env.resolver.get_current_speed() == 1.5
    env.ctx.current_file = ""
    assert env.resolver.get_current_speed() == CUE_DEFAULT_VIDEO_SPEED


def test_get_current_speed_reflects_active_sequence_step(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    variants = _write_variants(env, [1.5])
    env.vid.channel = "movie"
    _set_movie(env, env.base_fs)
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)   # start() sees base already playing -> forced first play
    env.seq.tick()              # first play registered (play_count 1), step stays 0
    _set_movie(env, variants[1.5])
    env.seq.tick()              # identity change -> step 1
    assert env.seq.active_tag == env.tag
    assert env.seq._step_index == 1
    assert env.resolver.get_current_speed() == 1.5


# ==========================================================================
# Resolver -- base_path_for / get_available_speeds
# ==========================================================================


def test_base_path_for_exact_match(env):
    env.resolver.paths[env.tag] = env.base_fs
    assert env.resolver.base_path_for(env.tag) == env.base_fs


def test_base_path_for_empty_tag_none(env):
    assert env.resolver.base_path_for("") is None


def test_base_path_for_prefix_match(env):
    env.resolver.paths[env.tag + " x"] = env.base_fs
    assert env.resolver.base_path_for(env.tag) == env.base_fs


def test_base_path_for_channel_fallback(env):
    env.vid.channel = "movie"
    env.music._registry["movie"] = {"playing": env.base_fs, "position": 0.0}
    assert env.resolver.base_path_for(env.tag) == env.base_fs


def test_base_path_for_unmatched_returns_raw(env):
    env.vid.channel = "movie"
    env.music._registry["movie"] = {"playing": "unrelated.mp4", "position": 0.0}
    assert env.resolver.base_path_for(env.tag) == "unrelated.mp4"


def test_get_available_speeds_lists_existing_variants(env):
    _write(env.base_fs)
    _write(env.resolver.variant_path(env.base_fs, 1.5))
    _write(env.resolver.variant_path(env.base_fs, 2.0))
    assert env.resolver.get_available_speeds(env.base_fs) == [1.0, 1.5, 2.0]


def test_get_available_speeds_only_default_when_empty(env):
    assert env.resolver.get_available_speeds(env.base_fs) == [CUE_DEFAULT_VIDEO_SPEED]
    assert env.resolver.get_available_speeds("") == [CUE_DEFAULT_VIDEO_SPEED]


# ==========================================================================
# Sequence -- state machine
# ==========================================================================


def test_sequence_speeds_for_missing_entry(env):
    assert env.seq.speeds_for(env.tag) is None
    assert env.seq.speeds_for("") is None


def test_sequence_append_speed_persists(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.5)
    assert env.seq.speeds_for(env.tag) == [1.5]
    assert env.store.get(create_vid_key(env.tag))["speed_sequence"] == [1.5]


def test_sequence_append_triggers_start_at_min_variants(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    assert env.seq.active_tag is None
    env.seq.append_speed(1.5)
    assert env.seq.active_tag == env.tag


def test_sequence_contains(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    assert env.seq.contains(1.5) is True
    assert env.seq.contains(2.0) is False


def test_sequence_speeds_grouped(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    assert env.seq.speeds_grouped(env.tag) == [(1.0, 2, 0), (1.5, 1, 2)]


def test_sequence_speeds_grouped_none(env):
    assert env.seq.speeds_grouped(env.tag) is None


def test_sequence_remove_at(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.remove_at(0)
    assert env.seq.speeds_for(env.tag) == [1.5]


def test_sequence_remove_at_empty_clears_key(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.remove_at(0)
    entry = env.store.get(create_vid_key(env.tag))
    assert "speed_sequence" not in entry
    assert env.seq.speeds_for(env.tag) is None


def test_sequence_remove_at_out_of_bounds_noop(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.remove_at(5)
    assert env.seq.speeds_for(env.tag) == [1.0]


def test_sequence_move(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.move(0, 1)
    assert env.seq.speeds_for(env.tag) == [1.5, 1.0]


def test_sequence_move_out_of_bounds_noop(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.move(0, -1)
    assert env.seq.speeds_for(env.tag) == [1.0]


def test_sequence_clear_sequence(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.clear_sequence(env.tag)
    assert env.seq.speeds_for(env.tag) is None
    assert env.seq.active_tag is None


def test_sequence_get_mode_default_single(env):
    assert env.seq.get_mode(env.tag) == CueSpeedMode.SINGLE
    assert env.seq.get_mode("") == CueSpeedMode.SINGLE


def test_sequence_set_mode_persists(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.set_mode(CueSpeedMode.MULTI)
    assert env.seq.get_mode(env.tag) == CueSpeedMode.MULTI
    assert env.seq.active_tag == env.tag
    env.seq.set_mode(CueSpeedMode.SINGLE)
    assert env.seq.get_mode(env.tag) == CueSpeedMode.SINGLE
    assert env.seq.active_tag is None


def test_sequence_set_mode_invalid_noop(env):
    env.ctx.current_file = env.tag
    env.seq.set_mode("bogus")
    assert env.seq.get_mode(env.tag) == CueSpeedMode.SINGLE


def test_sequence_paths_for_existing_variants(env):
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    assert env.seq.paths_for(env.tag) == [env.base_fs, env.resolver.variant_path(env.base_fs, 1.5)]


def test_sequence_paths_for_none_when_no_speeds(env):
    env.resolver.paths[env.tag] = env.base_fs
    assert env.seq.paths_for(env.tag) is None


def test_sequence_start_first_play_force(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.vid.channel = "movie"
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    _set_movie(env, env.base_fs)
    env.seq.start(env.tag)
    assert env.seq.active_tag == env.tag
    assert env.seq.last_playing is None
    assert env.seq.last_elapsed == -1.0
    assert env.seq._step_index == 0


def test_sequence_start_no_paths_inactive(env):
    env.ctx.current_file = env.tag
    env.seq.start(env.tag)
    assert env.seq.active_tag is None


def test_sequence_cancel(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    assert env.seq.active_tag == env.tag
    env.seq.cancel()
    assert env.seq.active_tag is None


def test_sequence_handle_starts_multi_mode(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.set_mode(CueSpeedMode.MULTI)
    env.seq.cancel()
    env.seq.handle(env.tag)
    assert env.seq.active_tag == env.tag


def test_sequence_handle_stops_when_mode_single(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.set_mode(CueSpeedMode.MULTI)
    assert env.seq.active_tag == env.tag
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_mode"] = CueSpeedMode.SINGLE
    env.seq.handle(env.tag)
    assert env.seq.active_tag is None


# ==========================================================================
# Sequence -- tick()
# ==========================================================================


def _started_seq(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    env.vid.channel = "movie"
    variants = _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    _set_movie(env, env.base_fs)
    env.seq.start(env.tag)  # now == _first -> forced first play (last_playing None)
    return variants


def test_tick_advances_step_on_identity_change(env):
    variants = _started_seq(env)
    _set_movie(env, env.base_fs)
    env.seq.tick()
    assert env.seq._step_index == 0
    assert env.seq.play_count == 1
    _set_movie(env, variants[1.5])
    env.seq.tick()
    assert env.seq._step_index == 1
    assert env.seq.play_count == 2


def test_tick_wrap_around_resets_step(env):
    variants = _started_seq(env)
    _set_movie(env, env.base_fs)
    env.seq.tick()               # step 0
    _set_movie(env, variants[1.5])
    env.seq.tick()               # step 1
    _set_movie(env, env.base_fs, pos=0.05)  # wrapped: elapsed dropped
    env.seq.tick()
    assert env.seq._step_index == 0


def test_tick_noop_when_inactive(env):
    env.seq.tick()  # active_tag None -> early return
    assert env.seq.play_count == 0


def test_tick_auto_wrap_calls_on_wrap_around(env):
    fake = FakeAutoSpeed([0.5, 1.0, 1.5, 2.0], [1.0, 1.5])
    env.seq.bind(env.resolver, fake)
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    env.vid.channel = "movie"
    variants = _write_variants(env, [1.5])
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_mode"] = CueSpeedMode.AUTO
    entry["speed_sequence"] = [1.0, 1.5]
    _set_movie(env, env.base_fs)
    env.seq.start(env.tag)
    _set_movie(env, env.base_fs)
    env.seq.tick()               # step 0, play_count 1
    _set_movie(env, variants[1.5])
    env.seq.tick()               # step 1
    _set_movie(env, env.base_fs, pos=0.05)
    env.seq.tick()               # AUTO wrap -> on_wrap_around
    assert fake.wrap_calls == 1
    assert env.seq._step_index == 1  # tick returned before advancing


# ==========================================================================
# Sequence -- start_auto
# ==========================================================================


def test_start_auto_unbound_falls_back_to_start(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.cancel()
    env.seq.start_auto(env.tag)
    assert env.seq.active_tag == env.tag


def test_start_auto_generates_and_saves_sequence(env):
    fake = FakeAutoSpeed([0.5, 1.0, 1.5, 2.0], [1.0, 1.5])
    env.seq.bind(env.resolver, fake)
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.start_auto(env.tag)
    entry = env.store.get(create_vid_key(env.tag))
    assert entry["speed_sequence"] == [1.0, 1.5]
    assert env.seq.active_tag == env.tag


def test_start_auto_insufficient_variants_noop(env):
    fake = FakeAutoSpeed([1.0], [])
    env.seq.bind(env.resolver, fake)
    env.ctx.current_file = env.tag
    env.seq.start_auto(env.tag)
    assert env.seq.active_tag is None
    assert env.store.get(create_vid_key(env.tag)) is None


# ==========================================================================
# Resolver -- disabled auto speeds
# ==========================================================================


def test_disabled_auto_speeds_roundtrip(env):
    env.ctx.current_file = env.tag
    assert env.seq.get_disabled_auto_speeds(env.tag) == set()
    env.seq.set_disabled_auto_speeds(env.tag, {0.5, 1.5})
    assert env.seq.get_disabled_auto_speeds(env.tag) == {0.5, 1.5}
    env.seq.set_disabled_auto_speeds(env.tag, set())
    assert env.seq.get_disabled_auto_speeds(env.tag) == set()


# ==========================================================================
# Seamless transition -- set_speed / resolve / _movie_for
# ==========================================================================


def _seamless_env(env):
    """Common setup for seamless tests: movie context, base path + variant."""
    env.ctx.current_file = env.tag
    env.ctx.top_layer_type = "movie"
    env.resolver.paths[env.tag] = env.base_fs
    env.vid.channel = "movie"
    return _write_variants(env, [1.5])


def test_set_speed_seamless_queues_and_pends(env):
    variants = _seamless_env(env)
    env.resolver.seamless_transition = True
    env.resolver.set_speed(1.5)
    assert env.resolver._pending_speed == 1.5
    assert env.resolver._pre_pending_speed == CUE_DEFAULT_VIDEO_SPEED
    assert env.music._registry["movie"]["queue"] == [variants[1.5]]


def test_set_speed_seamless_same_speed_noop(env):
    _seamless_env(env)
    env.resolver.seamless_transition = True
    env.resolver._pending_speed = 1.5
    env.resolver.set_speed(1.5)
    assert env.resolver._pending_speed == 1.5
    assert "movie" not in env.music._registry or not env.music._registry["movie"].get("queue")


def test_set_speed_seamless_missing_variant_noop(env):
    env.ctx.current_file = env.tag
    env.ctx.top_layer_type = "movie"
    env.resolver.paths[env.tag] = env.base_fs
    env.vid.channel = "movie"
    _write(env.base_fs)  # no 1.5 variant written
    env.resolver.seamless_transition = True
    env.resolver.set_speed(1.5)
    assert env.resolver._pending_speed is None


def test_set_speed_non_seamless_persists_pref(env):
    _seamless_env(env)
    env.resolver.set_speed(1.5)
    entry = env.store.get(create_vid_key(env.tag))
    assert entry["speed_pref"] == 1.5
    assert env.resolver._pending_speed is None


def test_set_speed_not_movie_noop(env):
    _seamless_env(env)
    env.ctx.top_layer_type = "image"
    env.resolver.set_speed(1.5)
    entry = env.store.get(create_vid_key(env.tag))
    assert "speed_pref" not in entry


def test_resolve_commits_pending_when_transitioned(env):
    variants = _seamless_env(env)
    env.resolver.seamless_transition = True
    env.music._registry["movie"] = {"playing": variants[1.5], "position": 0.0}
    env.resolver._pending_speed = 1.5
    env.resolver._pre_pending_speed = 1.0
    movie, _ = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert env.resolver._pending_speed is None
    assert env.resolver._pre_pending_speed is None
    assert env.store.get(create_vid_key(env.tag))["speed_pref"] == 1.5
    assert movie is env.resolver.children.get(env.tag)
    assert env.toast.toast_duration == CUE_TOAST_DURATION_SEAMLESS


def test_resolve_pending_not_yet_transitioned(env):
    _seamless_env(env)
    env.resolver.seamless_transition = True
    env.music._registry["movie"] = {"playing": env.base_fs, "position": 0.0}
    env.resolver._pending_speed = 1.5
    movie, _ = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert env.resolver._pending_speed == 1.5
    assert movie is env.resolver.children.get(env.tag)
    entry = env.store.get(create_vid_key(env.tag))
    assert entry is None or "speed_pref" not in entry


def test_resolve_non_seamless_returns_distinct_movies(env):
    _seamless_env(env)
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_pref"] = 1.5
    m1 = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    m1_again = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    assert m1 is m1_again
    assert m1.play == env.resolver.variant_path(env.base_fs, 1.5)

    _write(env.resolver.variant_path(env.base_fs, 2.0))
    entry["speed_pref"] = 2.0
    m2 = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    m2_again = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    assert m2 is m2_again
    assert m2 is not m1  # each speed gets its own Movie so Ren'Py restarts
    assert m2.play == env.resolver.variant_path(env.base_fs, 2.0)


def test_resolve_default_speed_uses_stable_movie(env):
    _seamless_env(env)
    m1 = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    m2 = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    assert m1 is m2
    assert m1.play == env.base_fs


def test_movie_for_stable_identity(env):
    orig = _make_orig(env.base_fs)
    m1 = env.resolver._movie_for(env.tag, env.base_fs, orig)
    m2 = env.resolver._movie_for(env.tag, env.base_fs, orig)
    assert m1 is m2
    assert env.resolver.children[env.tag] is m1


def test_resolve_sequence_queue_branch(env):
    _seamless_env(env)
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # active_tag set
    movie, _ = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert movie is env.resolver.children.get((env.tag, "__queue__"))
    assert movie.play == [env.base_fs, env.resolver.variant_path(env.base_fs, 1.5)]


def test_toggle_seamless_persists_and_clears_pending(env):
    env.resolver.toggle_seamless()
    assert env.resolver.seamless_transition is True
    assert persistent._cue["seamless_transition"] is True
    env.resolver._pending_speed = 1.5
    env.resolver._pre_pending_speed = 1.0
    env.resolver.toggle_seamless()
    assert env.resolver.seamless_transition is False
    assert env.resolver._pending_speed is None
    assert env.resolver._pre_pending_speed is None
    assert persistent._cue["seamless_transition"] is False


def test_clear_pending(env):
    env.resolver._pending_speed = 1.5
    env.resolver._pre_pending_speed = 1.0
    env.resolver.clear_pending()
    assert env.resolver._pending_speed is None
    assert env.resolver._pre_pending_speed is None


def test_invalidate_pops_children(env):
    env.resolver.children["x"] = object()
    env.resolver.children[("x", 1.5)] = object()
    env.resolver.children["y"] = object()
    env.resolver.invalidate("x")
    assert "x" not in env.resolver.children
    assert ("x", 1.5) not in env.resolver.children
    assert "y" in env.resolver.children


# ==========================================================================
# Seamless -- play callback
# ==========================================================================


def test_seamless_play_callback_skips_restart_when_already_playing(env, monkeypatch):
    from cue_lib.video import speed as _speed

    calls = []
    monkeypatch.setattr(_speed, "_default_play_callback", lambda old, new: calls.append((old, new)))
    env.music._registry["movie"] = {"playing": env.base_fs, "position": 0.0}
    new = types.SimpleNamespace(channel="movie", _play=env.base_fs)
    _speed._cue_seamless_play_callback(None, new)
    assert calls == []

    # Not yet playing the new file -> falls through to default callback.
    env.music._registry["movie"] = {"playing": "unrelated.mp4", "position": 0.0}
    _speed._cue_seamless_play_callback(None, new)
    assert calls == [(None, new)]


def test_seamless_play_callback_list_play_falls_through(env, monkeypatch):
    from cue_lib.video import speed as _speed

    calls = []
    monkeypatch.setattr(_speed, "_default_play_callback", lambda old, new: calls.append((old, new)))
    env.music._registry["movie"] = {"playing": env.base_fs, "position": 0.0}
    new = types.SimpleNamespace(channel="movie", _play=[env.base_fs, "b.webm"])
    _speed._cue_seamless_play_callback(None, new)
    assert calls == [(None, new)]


# ==========================================================================
# Resolver -- capture kwargs
# ==========================================================================


def test_capture_kwargs(env):
    m = Movie(play="x", channel="movie", loop=False)
    m.size = (100, 100)
    kw = _cue_capture_kwargs(m)
    assert kw["channel"] == "movie"
    assert kw["loop"] is False
    assert kw["size"] == (100, 100)
    assert kw["side_mask"] is False
    assert kw["mask"] is None
    assert kw["play_callback"] is None


# ==========================================================================
# Resolver -- delete_variant
# ==========================================================================


def test_delete_variant_removes_file_and_resets_pref(env):
    _seamless_env(env)
    env.resolver._set_speed_pref(env.tag, 1.5)
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert not os.path.exists(env.resolver.variant_path(env.base_fs, 1.5))
    assert env.resolver._get_speed_pref(env.tag) == CUE_DEFAULT_VIDEO_SPEED


def test_delete_variant_default_speed_noop(env):
    _seamless_env(env)
    env.resolver.delete_variant(env.base_fs, CUE_DEFAULT_VIDEO_SPEED)
    assert os.path.exists(env.base_fs)


def test_delete_variant_redirects_playing_channel(env):
    _seamless_env(env)
    variant = env.resolver.variant_path(env.base_fs, 1.5)
    _audio_mock.channels["cue_vid_1"] = None
    # channel reports the variant via a gamedir-relative path, as the engine does
    rel = os.path.relpath(variant, _config.gamedir)
    env.music._registry["cue_vid_1"] = {"playing": rel, "position": 0.0}
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert env.music._registry["cue_vid_1"]["playing"] == env.base_fs


def test_delete_variant_prunes_sequence(env):
    _seamless_env(env)
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # active_tag set, seq [1.0, 1.5]
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert env.store.get(create_vid_key(env.tag))["speed_sequence"] == [1.0]


def test_delete_variant_clears_cached_child(env):
    _seamless_env(env)
    env.store._get_or_create_entry(create_vid_key(env.tag))["speed_pref"] = 1.5
    env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert (env.tag, 1.5) in env.resolver.children
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert (env.tag, 1.5) not in env.resolver.children


# ==========================================================================
# Speed toast
# ==========================================================================


def test_toast_show_requires_variants(env):
    env.resolver.paths[env.tag] = env.base_fs
    _write(env.base_fs)  # only 1.0 -> no toast
    env.toast.show(env.tag)
    assert env.toast.toast_speeds is None


def test_toast_show_with_variants(env):
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.toast.show(env.tag)
    assert env.toast.toast_speeds == [1.0, 1.5]
    assert env.toast.toast_tag == env.tag


def test_toast_show_missing_tag_noop(env):
    env.toast.show("nonexistent.webm")
    assert env.toast.toast_speeds is None


def test_toast_clear(env):
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.toast.show(env.tag)
    env.toast.clear()
    assert env.toast.toast_speeds is None


# ==========================================================================
# Create-tab delete actions (module-level wrappers)
# ==========================================================================


def test_create_delete_speed_actions(env):
    from cue_lib.video import speed as _speed

    _cue = _state._cue
    prev_file = getattr(_cue, "current_file", None)
    prev_sel = getattr(_cue, "_create_delete_speed", None)
    _cue.current_file = env.tag
    _cue._create_delete_speed = None
    try:
        _speed._cue_create_select_speed(1.5)
        assert _cue._create_delete_speed == (env.tag, 1.5)
        assert _speed._cue_create_delete_sel() == 1.5

        _speed._cue_create_select_speed(1.5)  # repeat -> deselect
        assert _cue._create_delete_speed is None
        assert _speed._cue_create_delete_sel() is None

        _speed._cue_create_select_speed(2.0)
        assert _speed._cue_create_delete_sel() == 2.0
    finally:
        _cue.current_file = prev_file
        _cue._create_delete_speed = prev_sel


def test_create_delete_speed_executes_delete(env):
    from cue_lib.video import speed as _speed

    _cue = _state._cue
    variants = _seamless_env(env)
    prev_file = getattr(_cue, "current_file", None)
    prev_sel = getattr(_cue, "_create_delete_speed", None)
    _cue.current_file = env.tag
    _cue._create_delete_speed = None
    try:
        _speed._cue_create_select_speed(1.5)
        _speed._cue_create_delete_speed()
        assert not os.path.exists(variants[1.5])
    finally:
        _cue.current_file = prev_file
        _cue._create_delete_speed = prev_sel


# ==========================================================================
# Resolver -- cycle_speed
# ==========================================================================


def test_cycle_speed_advances(env):
    _seamless_env(env)
    _write(env.resolver.variant_path(env.base_fs, 2.0))
    env.resolver._set_speed_pref(env.tag, 1.5)
    env.resolver.cycle_speed(1)
    assert env.resolver._get_speed_pref(env.tag) == 2.0


def test_cycle_speed_wraps_down(env):
    _seamless_env(env)
    _write(env.resolver.variant_path(env.base_fs, 2.0))
    env.resolver._set_speed_pref(env.tag, 1.5)
    env.resolver.cycle_speed(-1)
    assert env.resolver._get_speed_pref(env.tag) == CUE_DEFAULT_VIDEO_SPEED


def test_cycle_speed_unlisted_current_falls_back(env):
    _seamless_env(env)
    env.resolver._set_speed_pref(env.tag, 0.75)  # not in available speeds
    env.resolver.cycle_speed(1)
    assert env.resolver._get_speed_pref(env.tag) == 1.5


def test_cycle_speed_not_movie_noop(env):
    _seamless_env(env)
    env.ctx.top_layer_type = "image"
    env.resolver.cycle_speed(1)


def test_cycle_speed_no_tag_noop(env):
    _seamless_env(env)
    env.ctx.current_file = ""
    env.resolver.cycle_speed(1)


def test_cycle_speed_no_base_path_noop(env):
    env.ctx.top_layer_type = "movie"
    env.ctx.current_file = env.tag
    env.resolver.cycle_speed(1)


def test_cycle_speed_only_default_noop(env):
    env.ctx.top_layer_type = "movie"
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write(env.base_fs)
    env.resolver.cycle_speed(1)


# ==========================================================================
# Resolver -- set_speed guard branches
# ==========================================================================


def test_set_speed_no_tag_noop(env):
    env.ctx.top_layer_type = "movie"
    env.ctx.current_file = ""
    env.resolver.set_speed(1.5)
    assert env.resolver._get_speed_pref(env.tag) == CUE_DEFAULT_VIDEO_SPEED


def test_set_speed_seamless_no_base_path_noop(env):
    env.ctx.top_layer_type = "movie"
    env.ctx.current_file = env.tag
    env.resolver.seamless_transition = True
    env.resolver.set_speed(1.5)
    assert env.resolver._pending_speed is None


def test_set_speed_seamless_queue_failure_logs(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    _seamless_env(env)
    env.resolver.seamless_transition = True

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.music, "queue", _boom)
    env.resolver.set_speed(1.5)
    assert env.resolver._pending_speed == 1.5
    assert any("queue failed" in m for m in logs)


# ==========================================================================
# Resolver -- base_path_for variant fallback + resolve branches
# ==========================================================================


def test_base_path_for_resolves_variant_back_to_base(env):
    env.resolver.paths[env.tag] = env.base_fs
    env.vid.channel = "movie"
    variant = env.resolver.variant_path(env.base_fs, 1.5)
    env.music._registry["movie"] = {"playing": variant, "position": 0.0}
    assert env.resolver.base_path_for("unmapped") == env.base_fs


def test_resolve_sequence_queue_cached(env):
    _seamless_env(env)
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # active_tag set
    first = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    second = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))[0]
    assert first is second
    assert first is env.resolver.children.get((env.tag, "__queue__"))


def test_resolve_seamless_get_playing_failure(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    _seamless_env(env)
    env.resolver.seamless_transition = True
    env.resolver._pending_speed = 1.5

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.music, "get_playing", _boom)
    movie, _ = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert movie is env.resolver.children.get(env.tag)
    assert any("get_playing failed" in m for m in logs)


def test_resolve_non_seamless_missing_variant_uses_stable(env):
    variants = _seamless_env(env)
    os.remove(variants[1.5])
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_pref"] = 1.5
    movie, _ = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert movie is env.resolver.children.get(env.tag)
    assert movie.play == env.base_fs


def test_resolve_seamless_idle_stable_movie(env):
    _seamless_env(env)
    env.resolver.seamless_transition = True
    movie, _ = env.resolver.resolve(0, 0, env.tag, env.base_fs, _make_orig(env.base_fs))
    assert movie is env.resolver.children.get(env.tag)


# ==========================================================================
# Resolver -- wrap_all_movies (image registry passes)
# ==========================================================================


def _reg_movie(env):
    m = Movie(play=env.base_fs, channel="movie")
    m.size = (1280, 720)
    return m


def _atl_entry(statements):
    import renpy.atl as _atl

    atl = _atl.ATLTransformBase()
    atl.block = types.SimpleNamespace(statements=statements)
    return atl


def _child(obj):
    import renpy.atl as _atl

    stmt = _atl.Child()
    stmt.child = obj
    return stmt


def test_wrap_all_movies_first_pass(env, monkeypatch):
    import renpy as _renpy
    from renpy.display.image import images as _display_images
    from renpy.display.layout import DynamicDisplayable

    _display_images.clear()
    try:
        _display_images[("scene",)] = _reg_movie(env)
        _display_images[("noplay",)] = Movie(play="", channel="movie")
        _display_images[("obj",)] = types.SimpleNamespace()
        _display_images[("dd",)] = DynamicDisplayable(lambda *a: None)
        monkeypatch.setattr(
            _renpy, "image",
            lambda name, d, **k: _display_images.__setitem__(name, d))
        env.resolver.wrap_all_movies()
        assert env.resolver.paths[env.tag] == env.base_fs
        assert isinstance(_display_images[("scene",)], DynamicDisplayable)
        assert "noplay" not in env.resolver.paths
        assert "obj" not in env.resolver.paths
        assert "dd" not in env.resolver.paths
    finally:
        _display_images.clear()


def test_wrap_all_movies_atl_pass(env):
    from renpy.display.image import images as _display_images

    _display_images.clear()
    try:
        _display_images[("scene",)] = _reg_movie(env)
        # First child unnamed -> continue; second is a bare tag string.
        _display_images[("bg", "strtag")] = _atl_entry(
            [_child(types.SimpleNamespace()), _child("scene")])
        _display_images[("bg", "movtag")] = _atl_entry([_child(_reg_movie(env))])
        _display_images[("bg", "tuptag")] = _atl_entry(
            [_child(types.SimpleNamespace(name=("scene",)))])
        env.resolver.wrap_all_movies()
        assert env.resolver.paths["bg strtag"] == env.base_fs
        assert env.resolver.paths["bg movtag"] == env.base_fs
        assert env.resolver.paths["bg tuptag"] == env.base_fs
    finally:
        _display_images.clear()


# ==========================================================================
# Sequence -- guard branches
# ==========================================================================


def test_sequence_contains_no_seq(env):
    env.ctx.current_file = env.tag
    assert env.seq.contains(1.5) is False


def test_sequence_get_entry_empty_tag(env):
    assert env.seq._get_entry("") is None


def test_disabled_auto_speeds_empty_tag(env):
    assert env.seq.get_disabled_auto_speeds("") == set()


def test_set_disabled_auto_speeds_empty_tag(env):
    env.seq.set_disabled_auto_speeds("", {1.5})
    assert env.seq.get_disabled_auto_speeds("") == set()


def test_sequence_append_empty_tag_noop(env):
    env.seq.append_speed(1.5)
    assert env.store.get(create_vid_key(env.tag)) is None


def test_sequence_remove_at_empty_tag_noop(env):
    env.seq.remove_at(0)


def test_sequence_remove_at_no_entry_noop(env):
    env.ctx.current_file = env.tag
    env.seq.remove_at(0)
    assert env.store.get(create_vid_key(env.tag)) is None


def test_sequence_remove_at_restarts_active(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # active
    env.seq.remove_at(1)
    assert env.seq.speeds_for(env.tag) == [1.0]
    assert env.seq.active_tag == env.tag


def test_sequence_move_empty_tag_noop(env):
    env.seq.move(0, 1)


def test_sequence_move_no_entry_noop(env):
    env.ctx.current_file = env.tag
    env.seq.move(0, 1)
    assert env.store.get(create_vid_key(env.tag)) is None


def test_sequence_move_no_seq_noop(env):
    env.ctx.current_file = env.tag
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    assert "speed_sequence" not in entry
    env.seq.move(0, 1)


def test_sequence_move_inactive_restarts(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # variants missing -> no start, active stays None
    env.seq.move(0, 1)
    assert env.seq.speeds_for(env.tag) == [1.5, 1.0]
    assert env.seq.active_tag is None


def test_sequence_clear_sequence_uses_current_file(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.clear_sequence()
    assert env.seq.speeds_for(env.tag) is None
    assert env.seq.active_tag is None


def test_sequence_clear_sequence_empty_tag_noop(env):
    env.seq.clear_sequence()


def test_sequence_get_mode_uses_current_file(env):
    env.ctx.current_file = env.tag
    assert env.seq.get_mode() == CueSpeedMode.SINGLE


def test_sequence_set_mode_auto_starts_auto(env):
    fake = FakeAutoSpeed([0.5, 1.0, 1.5, 2.0], [1.0, 1.5])
    env.seq.bind(env.resolver, fake)
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.set_mode(CueSpeedMode.AUTO)
    assert env.seq.get_mode(env.tag) == CueSpeedMode.AUTO
    assert env.seq.active_tag == env.tag


def test_sequence_paths_for_no_resolver(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq._speed_resolver = None
    assert env.seq.paths_for(env.tag) is None


def test_sequence_paths_for_none_when_no_files(env):
    env.resolver.paths[env.tag] = env.base_fs
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # variants not written -> no paths exist
    assert env.seq.paths_for(env.tag) is None


# ==========================================================================
# Sequence -- start / handle / tick edge cases
# ==========================================================================


def test_sequence_start_no_resolver(env):
    env.seq._speed_resolver = None
    env.seq.start(env.tag)
    assert env.seq.active_tag is None


def test_sequence_start_get_playing_failure(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.vid.channel = "movie"
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq.cancel()

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.music, "get_playing", _boom)
    env.seq.start(env.tag)
    assert env.seq.active_tag == env.tag
    assert env.seq.last_playing is None
    assert any("get_playing failed" in m for m in logs)


def test_sequence_tick_playback_query_failure(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    _started_seq(env)

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.music, "get_playing", _boom)
    env.seq.tick()
    assert any("playback query failed" in m for m in logs)
    assert env.seq.last_playing is None
    assert env.seq.last_elapsed == 0.0


def test_sequence_handle_auto_starts_auto(env):
    fake = FakeAutoSpeed([0.5, 1.0, 1.5, 2.0], [1.0, 1.5])
    env.seq.bind(env.resolver, fake)
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_mode"] = CueSpeedMode.AUTO
    entry["speed_sequence"] = [1.0, 1.5]
    env.seq.cancel()
    env.seq.handle(env.tag)
    assert env.seq.active_tag == env.tag


def test_sequence_handle_stop_failure(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.vid.channel = "movie"
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # active
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_mode"] = CueSpeedMode.SINGLE
    env.ctx.top_layer_type = "image"

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.music, "stop", _boom)
    env.seq.handle(env.tag)
    assert env.seq.active_tag is None
    assert any("stop failed" in m for m in logs)


def test_start_auto_no_resolver(env):
    fake = FakeAutoSpeed([0.5, 1.0, 1.5, 2.0], [1.0, 1.5])
    env.seq.bind(None, fake)
    env.ctx.current_file = env.tag
    env.seq.start_auto(env.tag)
    assert env.seq.active_tag is None


def test_start_auto_too_few_enabled_speeds(env):
    fake = FakeAutoSpeed([1.0], [])
    env.seq.bind(env.resolver, fake)
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    env.seq.start_auto(env.tag)
    assert env.seq.active_tag is None
    assert env.store.get(create_vid_key(env.tag)) is None


# ==========================================================================
# Sequence -- _debug_verify_step
# ==========================================================================


def test_debug_verify_step_guards(env):
    env.seq._debug_verify_step(None)              # now_playing None
    env.seq._debug_verify_step(env.base_fs)       # no active_tag
    env.ctx.current_file = env.tag
    env.seq.active_tag = env.tag
    env.seq._debug_verify_step(env.base_fs)       # no speed_sequence
    entry = env.store._get_or_create_entry(create_vid_key(env.tag))
    entry["speed_sequence"] = [1.0, 1.5]
    env.seq._speed_resolver = None
    env.seq._debug_verify_step(env.base_fs)       # resolver None
    env.seq._speed_resolver = env.resolver
    env.seq._debug_verify_step(env.base_fs)       # no base_path


def test_debug_verify_step_no_matches(env):
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)
    env.seq._debug_verify_step("unrelated.webm")


def test_debug_verify_step_logs_desync_once(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    env.ctx.current_file = env.tag
    env.resolver.paths[env.tag] = env.base_fs
    _write_variants(env, [1.5])
    env.seq.append_speed(1.0)
    env.seq.append_speed(1.5)  # active, _step_index 0
    variant15 = env.resolver.variant_path(env.base_fs, 1.5)
    env.seq._debug_verify_step(variant15)  # step 0 vs file for step 1 -> desync
    env.seq._debug_verify_step(variant15)  # same (step, file) -> rate-limited
    assert len([m for m in logs if "VQ-DESYNC" in m]) == 1


# ==========================================================================
# Module wrappers + create-tab delete edge cases
# ==========================================================================


def test_cue_resolver_module_wrapper(env):
    from cue_lib.video import speed as _speed

    orig = _make_orig(env.base_fs)
    child, _ = _speed._cue_resolver(0, 0, env.tag, env.base_fs, orig)
    assert child is env.resolver.children.get(env.tag)


def test_seamless_play_callback_exception(env, monkeypatch):
    from cue_lib.video import speed as _speed

    calls = []
    monkeypatch.setattr(
        _speed, "_default_play_callback", lambda old, new: calls.append((old, new)))
    monkeypatch.setattr(
        env.music, "get_playing",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    new = types.SimpleNamespace(channel="movie", _play=env.base_fs)
    _speed._cue_seamless_play_callback(None, new)
    assert calls == [(None, new)]


def test_capture_kwargs_with_group(env):
    m = Movie(play="x", channel="movie")
    m.size = (1280, 720)
    m.group = "scene"
    kw = _cue_capture_kwargs(m)
    assert kw["group"] == "scene"


def test_create_delete_speed_no_selection_noop(env):
    from cue_lib.video import speed as _speed

    _cue = _state._cue
    prev_sel = getattr(_cue, "_create_delete_speed", None)
    _cue._create_delete_speed = None
    try:
        _speed._cue_create_delete_speed()
    finally:
        _cue._create_delete_speed = prev_sel


def test_create_delete_speed_stale_selection_noop(env):
    from cue_lib.video import speed as _speed

    _cue = _state._cue
    prev_file = getattr(_cue, "current_file", None)
    prev_sel = getattr(_cue, "_create_delete_speed", None)
    _cue.current_file = "other"
    _cue._create_delete_speed = ("scene", 1.5)
    try:
        _speed._cue_create_delete_speed()
        assert _cue._create_delete_speed == ("scene", 1.5)  # untouched
    finally:
        _cue.current_file = prev_file
        _cue._create_delete_speed = prev_sel


def test_create_delete_speed_default_speed_noop(env):
    from cue_lib.video import speed as _speed

    _cue = _state._cue
    prev_file = getattr(_cue, "current_file", None)
    prev_sel = getattr(_cue, "_create_delete_speed", None)
    _cue.current_file = env.tag
    _cue._create_delete_speed = (env.tag, CUE_DEFAULT_VIDEO_SPEED)
    try:
        _speed._cue_create_delete_speed()
        assert _cue._create_delete_speed is None
    finally:
        _cue.current_file = prev_file
        _cue._create_delete_speed = prev_sel


# ==========================================================================
# Resolver -- parse / list / prune / delete edge cases
# ==========================================================================


def test_parse_variant_speed_bad_float(env):
    parse = CueVidSpeedResolver._parse_variant_speed
    assert parse("scene_cue1.5x.webm", "scene", ".webm") == 1.5
    assert parse("scene_cuexyzx.webm", "scene", ".webm") is None


def test_get_available_speeds_listdir_failure(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    monkeypatch.setattr(
        os, "listdir", lambda d: (_ for _ in ()).throw(OSError("nope")))
    assert env.resolver.get_available_speeds(env.base_fs) == [CUE_DEFAULT_VIDEO_SPEED]
    assert any("os.listdir failed" in m for m in logs)


def test_prune_deleted_speed_empty_tag(env):
    env.ctx.current_file = ""
    assert env.resolver._prune_deleted_speed_from_sequence(1.5) is False


def test_prune_deleted_speed_not_in_seq(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.0)
    assert env.resolver._prune_deleted_speed_from_sequence(1.5) is False
    assert env.seq.speeds_for(env.tag) == [1.0]


def test_prune_deleted_speed_removes_last(env):
    env.ctx.current_file = env.tag
    env.seq.append_speed(1.5)
    assert env.resolver._prune_deleted_speed_from_sequence(1.5) is True
    assert "speed_sequence" not in env.store.get(create_vid_key(env.tag))


def test_delete_variant_channel_stop_failure(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    _seamless_env(env)
    _audio_mock.channels["cue_vid_1"] = None
    env.music._registry["cue_vid_1"] = {"playing": env.base_fs, "position": 0.0}

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.music, "get_playing", _boom)
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert any("channel stop failed" in m for m in logs)


def test_delete_variant_resets_current_file_pref(env):
    _seamless_env(env)
    env.resolver.paths = {}  # base not registered, but current_file is set
    env.resolver._set_speed_pref(env.tag, 1.5)
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert env.resolver._get_speed_pref(env.tag) == CUE_DEFAULT_VIDEO_SPEED


def test_delete_variant_remove_retries_then_succeeds(env, monkeypatch):
    _seamless_env(env)
    real_remove = os.remove
    attempt = []

    def _flaky(p):
        attempt.append(p)
        if len(attempt) < 3:
            raise OSError("busy")
        real_remove(p)
    monkeypatch.setattr(os, "remove", _flaky)
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert len(attempt) == 3
    assert not os.path.exists(env.resolver.variant_path(env.base_fs, 1.5))


def test_delete_variant_remove_all_failed_logs(env, monkeypatch):
    from cue_lib.video import speed as _speed

    logs = []
    monkeypatch.setattr(_speed, "_cue_log", lambda m: logs.append(m))
    _seamless_env(env)

    def _boom(p):
        raise OSError("perm denied")
    monkeypatch.setattr(os, "remove", _boom)
    env.resolver.delete_variant(env.base_fs, 1.5)
    assert any("all attempts failed" in m for m in logs)
    assert os.path.exists(env.resolver.variant_path(env.base_fs, 1.5))
