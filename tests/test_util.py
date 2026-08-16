# -*- coding: utf-8 -*-
# Tests for the pure logic in cue_lib.util -- key helpers, time formatting,
# persistent unwrapping, file-tree / file-picking, OS-safe file replace, and
# the displayable/movie/SFX helpers.  Functions that reach the _cue singleton
# or Ren'Py runtime monkeypatch the specific seam (e.g. _cue.sfx_manager,
# _music.is_playing) instead of touching the real runtime.

import functools
import os
from types import SimpleNamespace

import cue_lib.util as _util
import cue_lib.constants as _constants
import pygame
import renpy
import renpy.atl as _atl
import renpy.audio.music as _music
import renpy.config as _config
import renpy.display.im as _im
import renpy.display.video as _video

from cue_lib.state import _cue

from cue_lib.util import (
    _cue_atl_child_displayables,
    _cue_build_tree,
    _cue_clamp_time,
    _cue_clear_debug_log,
    _cue_format_time,
    _cue_get_movie_or_image,
    _cue_get_movie_play,
    _cue_is_screenshake,
    _cue_loop_still_playing,
    _cue_log,
    _cue_make_tab_action,
    _cue_parse_time,
    _cue_pick_file,
    _cue_replace_file,
    _cue_resolve_files,
    _cue_sfx_channel_index,
    _cue_sfx_channel_name,
    _cue_shift_held,
    _cue_speed_label,
    _cue_strip_key_prefix,
    _cue_top_layer_name,
    _cue_top_movie_name,
    _cue_ui_refresh,
    _cue_unwrap_displayable,
    _cue_unwrap_persistent,
    create_dlg_key,
    create_img_key,
    create_loop_key,
    create_vid_key,
    get_key_dialogue,
    get_key_file,
    get_key_prefix,
    is_dlg_key,
    is_img_key,
    is_loop_key,
    is_vid_key,
)


def Move(**kwargs):
    """Stand-in for renpy.transitions.Move (a plain callable named Move)."""
    return None


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def test_create_img_key():
    assert create_img_key("bg beach") == "i_bg beach"


def test_create_vid_key():
    assert create_vid_key("anim_envy_bj3") == "v_anim_envy_bj3"


def test_create_loop_key():
    assert create_loop_key("file") == "l_file"


def test_create_loop_key_empty_file_for_global_pool():
    assert create_loop_key("") == "l_"


def test_create_dlg_key():
    assert create_dlg_key(("file", "dialogue")) == "d_file__dialogue"


def test_is_key_type_checks():
    assert is_img_key("i_bg")
    assert not is_img_key("v_anim")
    assert is_vid_key("v_anim")
    assert not is_vid_key("i_bg")
    assert is_dlg_key("d_file__dlg")
    assert not is_dlg_key("i_bg")
    assert is_loop_key("l_file")
    assert not is_loop_key("d_file__dlg")


def test_get_key_file_strips_prefix():
    assert get_key_file("i_bg beach") == "bg beach"
    assert get_key_file("v_movie") == "movie"
    assert get_key_file("l_file") == "file"


def test_get_key_file_dialogue_strips_text():
    assert get_key_file("d_file__dialogue") == "file"
    # Legacy | separator
    assert get_key_file("d_file|dialogue") == "file"


def test_get_key_dialogue():
    assert get_key_dialogue("d_file__dialogue") == "dialogue"
    # Legacy | separator
    assert get_key_dialogue("d_file|dialogue") == "dialogue"


def test_get_key_dialogue_without_separator_returns_empty():
    assert get_key_dialogue("d_plain") == ""
    assert get_key_dialogue("i_bg") == ""


def test_get_key_prefix():
    assert get_key_prefix("i_bg") == "i_"
    assert get_key_prefix("v_anim") == "v_"
    assert get_key_prefix("d_file__dlg") == "d_"
    assert get_key_prefix("l_file") == "l_"


# ---------------------------------------------------------------------------
# Time clamping
# ---------------------------------------------------------------------------

def test_clamp_time_within_range():
    assert _cue_clamp_time(5.0, 10.0) == 5.0


def test_clamp_time_below_zero():
    assert _cue_clamp_time(-5.0, 10.0) == 0.0


def test_clamp_time_above_duration():
    assert _cue_clamp_time(15.0, 10.0) == 10.0


def test_clamp_time_zero_duration_keeps_positive_time():
    assert _cue_clamp_time(5.0, 0.0) == 5.0


def test_clamp_time_negative_duration_clamps_below():
    assert _cue_clamp_time(-5.0, -3.0) == 0.0


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def test_format_time_none():
    assert _cue_format_time(None) == "00:00.00"


def test_format_time_negative():
    assert _cue_format_time(-1.0) == "00:00.00"


def test_format_time_zero():
    assert _cue_format_time(0.0) == "00:00.00"


def test_format_time_minutes_and_centiseconds():
    assert _cue_format_time(65.5) == "01:05.50"


def test_format_time_under_an_hour():
    assert _cue_format_time(3599.5) == "59:59.50"


def test_format_time_over_an_hour():
    assert _cue_format_time(3723.5) == "01:02:03.50"


def test_format_time_centiseconds_truncate_like_int_cast():
    # 0.99 is not exactly representable in binary floats; the centisecond
    # fraction uses int() truncation, matching the game's formatting.
    assert _cue_format_time(3599.99) == "59:59.98"


def test_format_time_exactly_one_hour():
    assert _cue_format_time(3600.0) == "01:00:00.00"


# ---------------------------------------------------------------------------
# Speed labels
# ---------------------------------------------------------------------------

def test_speed_label():
    assert _cue_speed_label(1.0) == "1.0x"
    assert _cue_speed_label(1.5) == "1.5x"
    assert _cue_speed_label(0.5) == "0.5x"
    assert _cue_speed_label(2.0) == "2.0x"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def test_parse_time_none():
    assert _cue_parse_time(None) is None


def test_parse_time_empty_string():
    assert _cue_parse_time("") is None
    assert _cue_parse_time("   ") is None


def test_parse_time_raw_float():
    assert _cue_parse_time("90.5") == 90.5


def test_parse_time_raw_float_with_whitespace():
    assert _cue_parse_time("  90.5  ") == 90.5


def test_parse_time_negative_number_rejected():
    assert _cue_parse_time("-5") is None


def test_parse_time_minutes_seconds():
    assert _cue_parse_time("01:23.45") == 83.45


def test_parse_time_hours_minutes_seconds():
    assert _cue_parse_time("01:02:03.45") == 3723.45


def test_parse_time_comma_decimal_separator():
    assert _cue_parse_time("1:23,45") == 83.45


def test_parse_time_garbage_returns_none():
    assert _cue_parse_time("abc") is None
    assert _cue_parse_time("::") is None


# ---------------------------------------------------------------------------
# Persistent unwrapping
# ---------------------------------------------------------------------------

def test_unwrap_persistent_plain_dict():
    assert _cue_unwrap_persistent({"a": 1}) == {"a": 1}


def test_unwrap_persistent_nested():
    data = {"a": {"b": [1, {"c": 2}], "d": set([3, 4])}}
    assert _cue_unwrap_persistent(data) == {"a": {"b": [1, {"c": 2}], "d": set([3, 4])}}


def test_unwrap_persistent_list_like():
    assert _cue_unwrap_persistent([1, [2, 3]]) == [1, [2, 3]]
    assert _cue_unwrap_persistent((1, 2)) == [1, 2]


def test_unwrap_persistent_set_like():
    result = _cue_unwrap_persistent(set([1, 2, 3]))
    assert isinstance(result, set)
    assert result == set([1, 2, 3])


def test_unwrap_persistent_strings_untouched():
    assert _cue_unwrap_persistent("hello") == "hello"


def test_unwrap_persistent_scalars_untouched():
    assert _cue_unwrap_persistent(42) == 42
    assert _cue_unwrap_persistent(None) is None
    assert _cue_unwrap_persistent(3.14) == 3.14


def test_unwrap_persistent_duck_typed_mapping():
    class FakeDict(object):
        def __init__(self):
            self._data = {"x": 1, "y": [2]}

        def items(self):
            return self._data.items()

        def keys(self):
            return self._data.keys()

    result = _cue_unwrap_persistent(FakeDict())
    assert type(result) is dict
    assert result == {"x": 1, "y": [2]}


# ---------------------------------------------------------------------------
# Key-prefix stripping
# ---------------------------------------------------------------------------

def test_strip_key_prefix_each_type():
    assert _cue_strip_key_prefix("i_bg") == "bg"
    assert _cue_strip_key_prefix("v_movie") == "movie"
    assert _cue_strip_key_prefix("l_file") == "file"
    assert _cue_strip_key_prefix("d_file__dlg") == "file__dlg"


def test_strip_key_prefix_no_match_returns_unchanged():
    assert _cue_strip_key_prefix("plain") == "plain"


# ---------------------------------------------------------------------------
# UI refresh decorator
# ---------------------------------------------------------------------------

def test_ui_refresh_returns_result(monkeypatch):
    calls = []
    monkeypatch.setattr(renpy, "restart_interaction", lambda *a, **k: calls.append(1))

    @_cue_ui_refresh
    def _double(x):
        return x * 2

    assert _double(21) == 42
    assert calls == [1]


def test_ui_refresh_runs_on_exception(monkeypatch):
    calls = []
    monkeypatch.setattr(renpy, "restart_interaction", lambda *a, **k: calls.append(1))

    @_cue_ui_refresh
    def _boom():
        raise ValueError("nope")

    import pytest
    with pytest.raises(ValueError):
        _boom()
    assert calls == [1]


# ---------------------------------------------------------------------------
# File tree building
# ---------------------------------------------------------------------------

def test_build_tree_empty():
    assert _cue_build_tree([]) == []


def test_build_tree_root_files_only():
    assert _cue_build_tree(["b.ogg", "a.ogg"]) == [
        {"type": "file", "name": "a.ogg"},
        {"type": "file", "name": "b.ogg"},
    ]


def test_build_tree_folders_before_files_nested():
    tree = _cue_build_tree(["a/b/c.ogg", "a/b/d.ogg", "a/x.ogg", "z.ogg"])
    assert [n["name"] for n in tree] == ["a/", "z.ogg"]
    a = tree[0]
    assert a["type"] == "folder"
    assert a["expanded"] is False
    assert a["has_files"] is True
    assert [c["name"] for c in a["children"]] == ["b/", "x.ogg"]
    b = a["children"][0]
    assert b["has_files"] is True
    assert [c["name"] for c in b["children"]] == ["c.ogg", "d.ogg"]


def test_build_tree_folder_without_direct_files():
    tree = _cue_build_tree(["a/b/c.ogg"])
    assert tree[0]["name"] == "a/"
    assert tree[0]["has_files"] is False  # only a nested folder, no direct file
    assert [c["name"] for c in tree[0]["children"]] == ["b/"]
    assert tree[0]["children"][0]["has_files"] is True


# ---------------------------------------------------------------------------
# File resolution / random picking
# ---------------------------------------------------------------------------

def test_resolve_files_expands_folder_refs(monkeypatch):
    monkeypatch.setattr(_cue, "sfx_manager",
                        SimpleNamespace(files=["music/a.ogg", "music/b.ogg", "other.ogg"],
                                        disabled_files=set(["music/b.ogg"])))
    assert _cue_resolve_files(["music/"]) == ["music/a.ogg"]


def test_resolve_files_passthrough_and_dedupe(monkeypatch):
    monkeypatch.setattr(_cue, "sfx_manager",
                        SimpleNamespace(files=["music/a.ogg"], disabled_files=set()))
    assert _cue_resolve_files(["music/", "music/a.ogg", "other.ogg"]) == ["music/a.ogg", "other.ogg"]


def test_resolve_files_skips_disabled_direct(monkeypatch):
    monkeypatch.setattr(_cue, "sfx_manager",
                        SimpleNamespace(files=["music/a.ogg"], disabled_files=set(["music/a.ogg"])))
    assert _cue_resolve_files(["music/a.ogg"]) == []


def test_pick_file_empty_returns_none(monkeypatch):
    monkeypatch.setattr(_util._cue, "trigger", SimpleNamespace(last_played=[]))
    assert _cue_pick_file([]) is None


def test_pick_file_single_skips_choice(monkeypatch):
    monkeypatch.setattr(_util._cue, "trigger", SimpleNamespace(last_played=[]))
    calls = []
    monkeypatch.setattr(_util._random, "choice", lambda f: calls.append(f) or f[0])
    assert _cue_pick_file(["only.ogg"]) == "only.ogg"
    assert calls == []


def test_pick_file_avoids_repeats(monkeypatch):
    last = ["a.ogg"]
    monkeypatch.setattr(_util._cue, "trigger", SimpleNamespace(last_played=last))
    # choice returns the recent file first, then a fresh one
    choices = iter(["a.ogg", "b.ogg"])
    monkeypatch.setattr(_util._random, "choice", lambda f: next(choices))
    assert _cue_pick_file(["a.ogg", "b.ogg"]) == "b.ogg"
    assert last == ["a.ogg", "b.ogg"]


def test_pick_file_prunes_last_played(monkeypatch):
    last = ["a.ogg", "b.ogg"]
    monkeypatch.setattr(_util._cue, "trigger", SimpleNamespace(last_played=last))
    monkeypatch.setattr(_util._random, "choice", lambda f: "c.ogg")
    assert _cue_pick_file(["a.ogg", "b.ogg", "c.ogg"]) == "c.ogg"
    assert last == ["b.ogg", "c.ogg"]


def test_pick_file_reroll_capped(monkeypatch):
    last = ["a.ogg"]
    monkeypatch.setattr(_util._cue, "trigger", SimpleNamespace(last_played=last))
    # choice always returns the recent file: the 10-try guard must cap the loop
    monkeypatch.setattr(_util._random, "choice", lambda f: "a.ogg")
    assert _cue_pick_file(["a.ogg", "b.ogg"]) == "a.ogg"
    assert last == ["a.ogg", "a.ogg"]


def test_pick_file_no_avoid_does_not_touch_last(monkeypatch):
    last = ["a.ogg"]
    monkeypatch.setattr(_util._cue, "trigger", SimpleNamespace(last_played=last))
    monkeypatch.setattr(_util._random, "choice", lambda f: "a.ogg")
    assert _cue_pick_file(["a.ogg", "b.ogg"], avoid_repeats=False) == "a.ogg"
    assert last == ["a.ogg"]


# ---------------------------------------------------------------------------
# _cue_replace_file (POSIX / Windows branches)
# ---------------------------------------------------------------------------

def test_replace_file_posix_plain_rename(tmp_path):
    src = tmp_path / "src.ogg"
    dst = tmp_path / "dst.ogg"
    src.write_bytes(b"data")
    dst.write_bytes(b"old")
    _cue_replace_file(str(src), str(dst))
    assert dst.read_bytes() == b"data"
    assert not src.exists()


def test_replace_file_nt_removes_stale_dst(tmp_path, monkeypatch):
    src = tmp_path / "src.ogg"
    dst = tmp_path / "dst.ogg"
    src.write_bytes(b"data")
    dst.write_bytes(b"old")
    removed = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "remove", lambda p: removed.append(p))
    _cue_replace_file(str(src), str(dst))
    assert removed == [str(dst)]  # stale dst removed before rename
    assert dst.read_bytes() == b"data"


def test_replace_file_nt_remove_failure_swallowed(tmp_path, monkeypatch):
    src = tmp_path / "src.ogg"
    dst = tmp_path / "dst.ogg"
    src.write_bytes(b"data")
    dst.write_bytes(b"old")

    def _boom(p):
        raise OSError("locked")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "remove", _boom)
    _cue_replace_file(str(src), str(dst))  # rename below still runs
    assert dst.read_bytes() == b"data"


def test_replace_file_nt_no_stale_dst(tmp_path, monkeypatch):
    src = tmp_path / "src.ogg"
    dst = tmp_path / "dst.ogg"
    src.write_bytes(b"data")
    removed = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "remove", lambda p: removed.append(p))
    _cue_replace_file(str(src), str(dst))
    assert removed == []  # lexists(dst) false -> no remove
    assert dst.read_bytes() == b"data"


# ---------------------------------------------------------------------------
# SFX channel helpers
# ---------------------------------------------------------------------------

def test_sfx_channel_name_and_index():
    assert _cue_sfx_channel_name(3) == "_cue_3"
    assert _cue_sfx_channel_index("_cue_7") == 7


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
# Debug logging
# ---------------------------------------------------------------------------

def test_log_writes_when_debug_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_log("hello world")
    log_file = tmp_path / "renpy_cue" / "debug.log"
    assert log_file.exists()
    assert "hello world" in log_file.read_text()


def test_log_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", False)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_log("hello world")
    assert not (tmp_path / "renpy_cue" / "debug.log").exists()


def test_log_missing_paths_never_raises(monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", None)  # AttributeError inside -> swallowed
    _cue_log("no paths")  # must not raise


def test_clear_debug_log_truncates(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    log_file = tmp_path / "renpy_cue" / "debug.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("stale content")
    _cue_clear_debug_log()
    assert log_file.read_text() == ""


# ---------------------------------------------------------------------------
# Tab action / shift held
# ---------------------------------------------------------------------------

def test_make_tab_action_appends_index(monkeypatch):
    captured = {}
    monkeypatch.setattr(_util, "Function", lambda fn, *args: captured.update(fn=fn, args=args))
    result = _cue_make_tab_action(_cue_sfx_channel_name, ("a", "b"), 3)
    assert captured["fn"] is _cue_sfx_channel_name
    assert captured["args"] == ("a", "b", 3)
    assert result is None


def test_shift_held(monkeypatch):
    mods = []
    monkeypatch.setattr(pygame, "key", SimpleNamespace(get_mods=lambda: mods[-1]), raising=False)
    monkeypatch.setattr(pygame, "KMOD_LSHIFT", 1, raising=False)
    monkeypatch.setattr(pygame, "KMOD_RSHIFT", 2, raising=False)
    mods.append(0)
    assert _cue_shift_held() is False
    mods.append(1)  # LSHIFT held
    assert _cue_shift_held() is True
    mods.append(2)  # RSHIFT held
    assert _cue_shift_held() is True


# ---------------------------------------------------------------------------
# Screenshake detection
# ---------------------------------------------------------------------------

def test_screenshake_none_is_false():
    assert _cue_is_screenshake(None) is False


def test_screenshake_partial_move_true():
    trans = functools.partial(Move, bounce=True, repeat=True, delay=0.3)
    assert _cue_is_screenshake(trans) is True


def test_screenshake_partial_wrong_func_false():
    def Other():
        return None
    assert _cue_is_screenshake(functools.partial(Other, delay=0.3)) is False


def test_screenshake_partial_delay_too_long_false():
    trans = functools.partial(Move, bounce=True, repeat=True, delay=0.5)
    assert _cue_is_screenshake(trans) is False


def test_screenshake_partial_missing_keys_false():
    assert _cue_is_screenshake(functools.partial(Move)) is False


def test_screenshake_curry_shaped_true():
    trans = SimpleNamespace(callable=Move, kwargs={"bounce": True, "repeat": True, "delay": 0.1})
    assert _cue_is_screenshake(trans) is True


def test_screenshake_plain_object_false():
    assert _cue_is_screenshake(object()) is False


def test_screenshake_partial_delay_non_numeric_false():
    trans = functools.partial(Move, bounce=True, repeat=True, delay="0.3")
    assert _cue_is_screenshake(trans) is False


# ---------------------------------------------------------------------------
# Displayable unwrapping / naming
# ---------------------------------------------------------------------------

def test_unwrap_displayable_plain_returns_self():
    d = object()
    assert _cue_unwrap_displayable(d) is d


def test_unwrap_displayable_child_chain():
    inner = object()
    outer = SimpleNamespace(child=inner)
    assert _cue_unwrap_displayable(outer) is inner


def test_unwrap_displayable_target_callable():
    inner = object()
    outer = SimpleNamespace(_target=lambda: inner)
    assert _cue_unwrap_displayable(outer) is inner


def test_unwrap_displayable_target_callable_self_breaks():
    d = SimpleNamespace(_target=lambda: None)
    assert _cue_unwrap_displayable(d) is d  # resolved None -> break keeps d


def test_unwrap_displayable_attr_target():
    inner = object()
    outer = SimpleNamespace(target=inner)
    assert _cue_unwrap_displayable(outer) is inner


def test_unwrap_displayable_string_branch(monkeypatch):
    inner = object()
    monkeypatch.setattr(renpy, "displayable", lambda name: inner)
    assert _cue_unwrap_displayable("bg forest") is inner


def test_get_movie_or_image_movie():
    m = _video.Movie(play="m.webm")
    kind, d = _cue_get_movie_or_image(m)
    assert kind == "movie"
    assert d is m


def test_get_movie_or_image_image():
    i = _im.Image("img.png")
    kind, d = _cue_get_movie_or_image(i)
    assert kind == "image"
    assert d is i


def test_get_movie_or_image_other():
    kind, d = _cue_get_movie_or_image(object())
    assert kind is None
    assert d is not None


def test_atl_child_displayables_not_atl():
    assert _cue_atl_child_displayables(object()) is None


def test_atl_child_displayables_missing_block_none():
    # ATLTransformBase with no block: the compile attempt yields nothing
    d = _atl.ATLTransformBase()
    assert _cue_atl_child_displayables(d) is None


def test_atl_child_displayables_compile_raises():
    d = _atl.ATLTransformBase()
    d.compile = lambda: (_ for _ in ()).throw(RuntimeError("bad"))
    assert _cue_atl_child_displayables(d) is None


def test_atl_child_displayables_no_statements():
    d = _atl.ATLTransformBase()
    d.block = SimpleNamespace(statements=[])
    assert _cue_atl_child_displayables(d) is None


def test_atl_child_displayables_collects_children():
    class FakeStatement(_atl.Child):
        def __init__(self, child):
            self.child = child

    disp = object()
    stmts = [FakeStatement(disp), "not-a-statement"]
    d = _atl.ATLTransformBase()
    d.block = SimpleNamespace(statements=stmts)
    assert _cue_atl_child_displayables(d) == [disp]


def test_top_layer_name():
    assert _cue_top_layer_name(None) is None
    assert _cue_top_layer_name(("bg", "forest")) == "bg"
    assert _cue_top_layer_name("bg") == "bg"
    assert _cue_top_layer_name("") is None


def test_top_movie_name():
    m = _video.Movie(play="movies/scene.webm")
    assert _cue_top_movie_name(m) == "scene.webm"


def test_top_movie_name_play_list():
    m = _video.Movie(play=["a.webm", "b.webm"])
    assert _cue_top_movie_name(m) == "a.webm"


def test_top_movie_name_explicit_name_wins():
    m = _video.Movie(play="movies/scene.webm")
    m.name = "custom_tag"
    assert _cue_top_movie_name(m) == "custom_tag"


def test_top_movie_name_no_play():
    m = _video.Movie()
    assert _cue_top_movie_name(m) is None


def test_get_movie_play_original_wins():
    m = SimpleNamespace(_original_play="orig.webm", _play="fallback.webm")
    assert _cue_get_movie_play(m) == "orig.webm"


def test_get_movie_play_falls_back_to_play():
    m = SimpleNamespace(_original_play=None, _play="fallback.webm")
    assert _cue_get_movie_play(m) == "fallback.webm"


def test_get_movie_play_list_first_item():
    m = SimpleNamespace(_original_play=None, _play=["a.webm", "b.webm"])
    assert _cue_get_movie_play(m) == "a.webm"


def test_get_movie_play_empty():
    m = SimpleNamespace()
    assert _cue_get_movie_play(m) == ""


# ---------------------------------------------------------------------------
# _cue_query_matches (search-bar preset-name matcher)
# ---------------------------------------------------------------------------

def test_query_matches_case_insensitive_substring():
    assert _util._cue_query_matches("Intense Moans", "intense")
    assert _util._cue_query_matches("Intense Moans", "MOANS")
    assert not _util._cue_query_matches("Subtle Moans", "intense")


def test_query_matches_multi_term_and():
    assert _util._cue_query_matches("Intense Moans", "intense moans")
    assert not _util._cue_query_matches("Intense Moans", "intense scream")


def test_query_matches_empty_query():
    assert _util._cue_query_matches("Anything", "")
    assert _util._cue_query_matches("Anything", "   ")


def test_split_pipes_plain_and_escaped():
    assert _util._cue_split_pipes("amira|slide") == ["amira", "slide"]
    assert _util._cue_split_pipes("mix\\|take") == ["mix|take"]
    assert _util._cue_split_pipes("a\\|b|c") == ["a|b", "c"]
    assert _util._cue_split_pipes("plain") == ["plain"]
    assert _util._cue_split_pipes("trailing\\") == ["trailing\\"]


def test_query_matches_pipe_or():
    assert _util._cue_query_matches("Amira Moans", "amira|slide")
    assert _util._cue_query_matches("Slide Whistle", "amira|slide")
    assert not _util._cue_query_matches("Footsteps", "amira|slide")


def test_query_matches_pipe_or_with_and_alternative():
    # Each pipe alternative is AND over its whitespace terms.
    assert _util._cue_query_matches("Nora Intense Moans", "nora intense|amira")
    assert _util._cue_query_matches("Amira Moans", "nora intense|amira")
    assert not _util._cue_query_matches("Nora Moans", "nora intense|amira")


def test_query_matches_escaped_pipe_literal():
    assert _util._cue_query_matches("Mix|Take.wav", "mix\\|take")
    assert not _util._cue_query_matches("MixTake.wav", "mix\\|take")
