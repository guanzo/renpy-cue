# -*- coding: utf-8 -*-
# Tests for the pure logic in cue_lib.util -- key helpers, time formatting,
# persistent unwrapping, file-tree / file-picking, OS-safe file replace, and
# the displayable/movie/SFX helpers.  Functions that reach the _cue singleton
# or Ren'Py runtime monkeypatch the specific seam (e.g. _cue.sfx)
# instead of touching the real runtime.

import functools
import os
from types import SimpleNamespace

import cue_lib.util as _util
from cue_lib.util import _cue_is_str
import cue_lib.constants as _constants
import cue_lib.logger as _logger_mod
import pygame
import renpy
import renpy.atl as _atl
import renpy.config as _config
import renpy.display.video as _video

from cue_lib.state import _cue
from cue_lib.logger import _cue_logger

from cue_lib.util import (
    _cue_atl_child_displayables,
    _cue_build_tree,
    _cue_clamp_time,
    _cue_escape_text,
    _cue_expand_folder_ref,
    _cue_format_time,
    _cue_get_movie_play,
    _cue_is_screenshake,
    _cue_log,
    _cue_consume_return,
    _cue_make_tab_action,
    _cue_open_in_os_file_explorer,
    _cue_parse_time,
    _cue_pick_file,
    _cue_replace_file,
    _cue_remove_ref,
    _cue_resolve_files,
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


def test_format_time_centiseconds_round():
    # 0.99 is not exactly representable in binary floats; format rounds to
    # the nearest centisecond so a display -> parse -> display round trip is
    # stable. (The old int() truncation dropped the display one centisecond
    # on click + Enter: 1.2000000000000002 showed 1.20, but float("1.20")
    # re-formatted to 1.19.)
    assert _cue_format_time(3599.99) == "59:59.99"


def test_format_time_rounds_to_nearest_centisecond():
    # float("1.20") is 1.1999999999999999556, a hair below 1.20; rounding
    # keeps it displaying as 1.20 instead of truncating to 1.19.
    assert _cue_format_time(1.2) == "00:01.20"
    assert _cue_format_time(1.2000000000000002) == "00:01.20"


def test_format_parse_round_trip_is_display_stable():
    # Clicking the time field then pressing Enter commits parse(format(t)).
    # For every t the display must not move: format(parse(format(t))) == format(t).
    for t in (0.0, 1.1, 1.2, 1.23, 1.295, 1.5, 1.6, 3599.99):
        reparsed = _cue_parse_time(_cue_format_time(t))
        assert _cue_format_time(reparsed) == _cue_format_time(t)


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
    assert _cue_build_tree(["b.ogg", "a.ogg"]) == [{"type": "file", "name": "a.ogg"}, {"type": "file", "name": "b.ogg"}]


def test_build_tree_folders_before_files_nested():
    tree = _cue_build_tree(["a/b/c.ogg", "a/b/d.ogg", "a/x.ogg", "z.ogg"])
    assert [n["name"] for n in tree] == ["a/", "z.ogg"]
    a = tree[0]
    assert a["type"] == "folder"
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
    monkeypatch.setattr(
        _cue,
        "sfx",
        SimpleNamespace(
            library=SimpleNamespace(
                files=["music/a.ogg", "music/b.ogg", "other.ogg"], disabled_files=set(["music/b.ogg"])
            )
        ),
    )
    assert _cue_resolve_files(["music/"]) == ["music/a.ogg"]


def test_resolve_files_passthrough_and_dedupe(monkeypatch):
    monkeypatch.setattr(
        _cue, "sfx", SimpleNamespace(library=SimpleNamespace(files=["music/a.ogg"], disabled_files=set()))
    )
    assert _cue_resolve_files(["music/", "music/a.ogg", "other.ogg"]) == ["music/a.ogg", "other.ogg"]


def test_resolve_files_skips_disabled_direct(monkeypatch):
    monkeypatch.setattr(
        _cue,
        "sfx",
        SimpleNamespace(library=SimpleNamespace(files=["music/a.ogg"], disabled_files=set(["music/a.ogg"]))),
    )
    assert _cue_resolve_files(["music/a.ogg"]) == []


def test_resolve_files_nested_folder_prefix(monkeypatch):
    # A folder ref expands every nested descendant but not a sibling path that
    # merely shares the prefix up to the slash ("music.ogg" < "music/...").
    monkeypatch.setattr(
        _cue,
        "sfx",
        SimpleNamespace(
            library=SimpleNamespace(
                files=["music.ogg", "music/a.ogg", "music/sub/b.ogg", "music/sub/deep/c.ogg", "sfx/boom.ogg"],
                disabled_files=set(),
            )
        ),
    )
    assert _cue_resolve_files(["music/"]) == ["music/a.ogg", "music/sub/b.ogg", "music/sub/deep/c.ogg"]


def test_resolve_files_dedupes_overlapping_folder_refs(monkeypatch):
    # Two folder refs where one nests inside the other resolve to a single
    # dedup'd list, preserving first-occurrence order (the dedup used to be a
    # linear scan of the result list -- O(R^2) on overlapping folders).
    monkeypatch.setattr(
        _cue,
        "sfx",
        SimpleNamespace(
            library=SimpleNamespace(
                files=["music/a.ogg", "music/sub/b.ogg", "music/sub/deep/c.ogg"], disabled_files=set()
            )
        ),
    )
    assert _cue_resolve_files(["music/", "music/sub/"]) == ["music/a.ogg", "music/sub/b.ogg", "music/sub/deep/c.ogg"]


def test_expand_folder_ref_prefix_boundary():
    # "b.ogg" shares the "b" prefix but not "b/" -- it must not match.
    files = ["b.ogg", "b/one.ogg", "b/sub/two.ogg"]
    assert _cue_expand_folder_ref(files, "b/") == ["b/one.ogg", "b/sub/two.ogg"]


def test_expand_folder_ref_skips_disabled():
    files = ["b/one.ogg", "b/two.ogg", "b/three.ogg"]
    assert _cue_expand_folder_ref(files, "b/", disabled=set(["b/two.ogg"])) == ["b/one.ogg", "b/three.ogg"]


def test_expand_folder_ref_no_match():
    assert _cue_expand_folder_ref(["a/x.ogg", "c/y.ogg"], "b/") == []


def test_remove_ref_direct_match():
    files = ["a.ogg", "b.ogg"]
    result, removed = _cue_remove_ref(files, "a.ogg")
    assert removed is True
    assert result == ["b.ogg"]


def test_remove_ref_absent_path_is_noop():
    files = ["a.ogg", "b.ogg"]
    result, removed = _cue_remove_ref(files, "zzz.ogg")
    assert removed is False
    assert result == ["a.ogg", "b.ogg"]


def test_remove_ref_folder_child_expands_and_drops(monkeypatch):
    # A child under a covering folder ref: the ref becomes its children minus
    # the dropped file.
    monkeypatch.setattr(
        _cue, "sfx", SimpleNamespace(library=SimpleNamespace(files=["b/one.ogg", "b/two.ogg"], disabled_files=set()))
    )
    files = ["a.ogg", "b/"]
    result, removed = _cue_remove_ref(files, "b/two.ogg")
    assert removed is True
    assert result == ["a.ogg", "b/one.ogg"]


def test_remove_ref_folder_equal_to_path_drops_ref():
    # Removing the folder ref itself pops it outright (no expansion).
    files = ["a.ogg", "b/"]
    result, removed = _cue_remove_ref(files, "b/")
    assert removed is True
    assert result == ["a.ogg"]


def test_remove_ref_expand_fn_injection():
    # The expansion seam is injectable for tests: a stub expand_fn decides the
    # children without touching the _cue singleton.
    files = ["b/"]
    result, removed = _cue_remove_ref(files, "b/two.ogg", expand_fn=lambda refs: ["b/one.ogg", "b/two.ogg"])
    assert removed is True
    assert result == ["b/one.ogg"]


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
# _cue_open_in_os_file_explorer (platform file-explorer dispatch)
# ---------------------------------------------------------------------------


def test_open_folder_linux_uses_xdg_open(tmp_path, monkeypatch):
    target = str(tmp_path)
    calls = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(_util.sys, "platform", "linux")
    monkeypatch.setattr(_util._subprocess, "Popen", lambda cmd: calls.append(cmd))
    _cue_open_in_os_file_explorer(target)
    assert calls == [["xdg-open", target]]


def test_open_folder_macos_uses_open(tmp_path, monkeypatch):
    target = str(tmp_path)
    calls = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(_util.sys, "platform", "darwin")
    monkeypatch.setattr(_util._subprocess, "Popen", lambda cmd: calls.append(cmd))
    _cue_open_in_os_file_explorer(target)
    assert calls == [["open", target]]


def test_open_folder_windows_uses_startfile(tmp_path, monkeypatch):
    target = str(tmp_path)
    calls = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)
    _cue_open_in_os_file_explorer(target)
    assert calls == [target]


def test_open_folder_creates_missing_dir(tmp_path, monkeypatch):
    target = str(tmp_path / "music")
    calls = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(_util.sys, "platform", "linux")
    monkeypatch.setattr(_util._subprocess, "Popen", lambda cmd: calls.append(cmd))
    _cue_open_in_os_file_explorer(target)
    assert os.path.isdir(target)  # created before the explorer is asked
    assert calls == [["xdg-open", target]]


def test_open_folder_existing_dir_not_recreated(tmp_path, monkeypatch):
    target = str(tmp_path)
    makedirs = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(_util.sys, "platform", "linux")
    monkeypatch.setattr(os, "makedirs", lambda p: makedirs.append(p))
    monkeypatch.setattr(_util._subprocess, "Popen", lambda cmd: None)
    _cue_open_in_os_file_explorer(target)
    assert makedirs == []  # dir already exists -> no mkdir


def test_open_folder_swallows_mkdir_error(tmp_path, monkeypatch):
    target = str(tmp_path / "music")
    calls = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(_util.sys, "platform", "linux")
    monkeypatch.setattr(_util._subprocess, "Popen", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(os, "makedirs", lambda p: (_ for _ in ()).throw(OSError("no perms")))
    _cue_open_in_os_file_explorer(target)  # must not raise
    assert calls == []  # nothing opened when the dir can't be created


def test_open_folder_swallows_open_error(tmp_path, monkeypatch):
    target = str(tmp_path)
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(_util.sys, "platform", "linux")

    def _boom(cmd):
        raise OSError("no xdg-open")

    monkeypatch.setattr(_util._subprocess, "Popen", _boom)
    _cue_open_in_os_file_explorer(target)  # must not raise


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------


def test_log_writes_when_debug_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_log("hello world")
    _cue_logger.flush()  # buffered lines only hit disk on a flush
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
    _cue_logger.clear_debug()
    assert log_file.read_text() == ""


# ---------------------------------------------------------------------------
# Error logging (unguarded)
# ---------------------------------------------------------------------------


def test_log_error_writes_when_debug_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", False)  # unguarded guarantee
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.log_error("boom")
    # Write-through: no flush call needed.
    log_file = tmp_path / "renpy_cue" / "error.log"
    assert log_file.exists()
    assert "boom" in log_file.read_text()


def test_log_error_writes_when_debug_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.log_error("still logged")
    assert "still logged" in (tmp_path / "renpy_cue" / "error.log").read_text()


def test_log_error_appends_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.log_error("first")
    _cue_logger.log_error("second")
    text = (tmp_path / "renpy_cue" / "error.log").read_text()
    assert text.index("first") < text.index("second")


def test_log_error_appends_traceback_inside_except(monkeypatch, tmp_path):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    try:
        raise ValueError("exploded")
    except ValueError:
        _cue_logger.log_error("caught")
    text = (tmp_path / "renpy_cue" / "error.log").read_text()
    assert "exploded" in text  # the exception message
    assert "ValueError" in text  # the traceback frame


def test_log_error_no_traceback_outside_except(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.log_error("clean")
    text = (tmp_path / "renpy_cue" / "error.log").read_text()
    assert "Traceback" not in text


def test_log_error_missing_paths_never_raises(monkeypatch):
    monkeypatch.setattr(_cue, "paths", None)  # AttributeError inside -> swallowed
    _cue_logger.log_error("no paths")  # must not raise


def test_clear_error_log_truncates(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    log_file = tmp_path / "renpy_cue" / "error.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("stale content")
    _cue_logger.clear_error()
    assert log_file.read_text() == ""


def test_clear_error_log_creates_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.clear_error()  # must not raise when dir / file absent
    assert (tmp_path / "renpy_cue" / "error.log").exists()


def test_clear_logs_truncates_both(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    for name in ("debug.log", "error.log"):
        log_file = tmp_path / "renpy_cue" / name
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("stale content")
    _cue_logger.clear_logs()
    for name in ("debug.log", "error.log"):
        assert (tmp_path / "renpy_cue" / name).read_text() == ""


# ---------------------------------------------------------------------------
# Tab action / shift held
# ---------------------------------------------------------------------------


def test_make_tab_action_appends_index(monkeypatch):
    captured = {}
    monkeypatch.setattr(_util, "Function", lambda fn, *args: captured.update(fn=fn, args=args))
    result = _cue_make_tab_action(_cue_format_time, ("a", "b"), 3)
    assert captured["fn"] is _cue_format_time
    assert captured["args"] == ("a", "b", 3)
    assert result is None


def test_consume_return_runs_callable_and_drops_result():
    # A Function action returning non-None bleeds the click through the
    # overlay to the scene; the wrapper must run the callable and return None.
    calls = []

    def _mutate(x, y):
        calls.append((x, y))
        return "meaningful-bool-or-key"

    assert _cue_consume_return(_mutate, 1, "b") is None
    assert calls == [(1, "b")]


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


# ---------------------------------------------------------------------------
# _cue_matches_any / preset + igroup search matchers (search-bar content
# matching: a pool preset or intensity group surfaces when a file/folder
# inside it matches, not just its own name)
# ---------------------------------------------------------------------------


def _stub_sfx_library(monkeypatch, files):
    monkeypatch.setattr(_cue, "sfx", SimpleNamespace(library=SimpleNamespace(files=list(files), disabled_files=set())))


def test_matches_any_empty_query_matches_everything():
    assert _util._cue_matches_any("", ["music/a.ogg"])
    assert _util._cue_matches_any("   ", ["music/a.ogg"])


def test_matches_any_substring_case_insensitive():
    assert _util._cue_matches_any("scream", ["music/Scream.wav", "music/moan.wav"])
    assert not _util._cue_matches_any("zzz", ["music/Scream.wav"])


def test_matches_any_empty_items_is_false():
    assert not _util._cue_matches_any("scream", [])


def test_preset_search_matches_by_name(monkeypatch):
    monkeypatch.setattr(_cue, "presets", SimpleNamespace(audio=SimpleNamespace(get=lambda n: None)))
    assert _util._cue_preset_search_matches("Action Pack", "action")


def test_preset_search_matches_by_file_content(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav", "music/moan.wav"])
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/scream.wav", "music/moan.wav"]})),
    )
    assert _util._cue_preset_search_matches("Action Pack", "scream")


def test_preset_search_matches_folder_ref_content(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav", "music/moan.wav"])
    monkeypatch.setattr(_cue, "presets", SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/"]})))
    assert _util._cue_preset_search_matches("Ambient", "scream")


def test_preset_search_matches_nothing(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav"])
    monkeypatch.setattr(
        _cue, "presets", SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/scream.wav"]}))
    )
    assert not _util._cue_preset_search_matches("Action Pack", "zzz")


def test_preset_search_matches_missing_preset(monkeypatch):
    monkeypatch.setattr(_cue, "presets", SimpleNamespace(audio=SimpleNamespace(get=lambda n: None)))
    assert not _util._cue_preset_search_matches("Ghost", "scream")


def test_igroup_search_matches_by_name(monkeypatch):
    monkeypatch.setattr(_cue, "presets", SimpleNamespace(intensity=SimpleNamespace(get=lambda n: {"levels": []})))
    assert _util._cue_igroup_search_matches("Soft", "soft")


def test_igroup_search_matches_by_level_content(monkeypatch):
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(
            intensity=SimpleNamespace(
                get=lambda n: {"levels": [{"id": 1, "files": ["moans/soft"]}, {"id": 2, "files": ["gasps/light"]}]}
            )
        ),
    )
    assert _util._cue_igroup_search_matches("Build", "gasps")


def test_igroup_search_matches_nothing(monkeypatch):
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(intensity=SimpleNamespace(get=lambda n: {"levels": [{"id": 1, "files": ["moans/soft"]}]})),
    )
    assert not _util._cue_igroup_search_matches("Build", "zzz")


def test_igroup_search_matches_missing_group(monkeypatch):
    monkeypatch.setattr(_cue, "presets", SimpleNamespace(intensity=SimpleNamespace(get=lambda n: None)))
    assert not _util._cue_igroup_search_matches("Ghost", "soft")


# _cue_filter_preset_files: no search or a name match keeps all files; a
# content-only match keeps just the matching files (the tree's folder-match
# semantics -- matching folder keeps all descendants).


def test_filter_preset_files_no_query_all_files(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav", "music/moan.wav"])
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/scream.wav", "music/moan.wav"]})),
    )
    assert _util._cue_filter_preset_files("Action Pack", "") == ["music/scream.wav", "music/moan.wav"]


def test_filter_preset_files_name_match_keeps_all(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav", "music/moan.wav"])
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/scream.wav", "music/moan.wav"]})),
    )
    assert _util._cue_filter_preset_files("Action Pack", "action") == ["music/scream.wav", "music/moan.wav"]


def test_filter_preset_files_content_match_keeps_matches(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav", "music/moan.wav"])
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/scream.wav", "music/moan.wav"]})),
    )
    assert _util._cue_filter_preset_files("Action Pack", "scream") == ["music/scream.wav"]


def test_filter_preset_files_folder_ref_resolves_then_filters(monkeypatch):
    _stub_sfx_library(monkeypatch, ["music/scream.wav", "music/moan.wav"])
    monkeypatch.setattr(_cue, "presets", SimpleNamespace(audio=SimpleNamespace(get=lambda n: {"files": ["music/"]})))
    assert _util._cue_filter_preset_files("Ambient", "scream") == ["music/scream.wav"]


def test_filter_igroup_folders_no_query_all(monkeypatch):
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(
            intensity=SimpleNamespace(
                get=lambda n: {"levels": [{"id": 1, "files": ["moans/soft"]}, {"id": 2, "files": ["gasps/light"]}]}
            )
        ),
    )
    assert _util._cue_filter_igroup_folders("Build", "") == [
        {"id": 1, "files": ["moans/soft"]},
        {"id": 2, "files": ["gasps/light"]},
    ]


def test_filter_igroup_folders_name_match_keeps_all(monkeypatch):
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(
            intensity=SimpleNamespace(
                get=lambda n: {"levels": [{"id": 1, "files": ["moans/soft"]}, {"id": 2, "files": ["gasps/light"]}]}
            )
        ),
    )
    assert _util._cue_filter_igroup_folders("Build", "build") == [
        {"id": 1, "files": ["moans/soft"]},
        {"id": 2, "files": ["gasps/light"]},
    ]


def test_filter_igroup_folders_content_match_keeps_matches(monkeypatch):
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(
            intensity=SimpleNamespace(
                get=lambda n: {"levels": [{"id": 1, "files": ["moans/soft"]}, {"id": 2, "files": ["gasps/light"]}]}
            )
        ),
    )
    assert _util._cue_filter_igroup_folders("Build", "gasps") == [{"id": 2, "files": ["gasps/light"]}]


def test_filter_igroup_folders_content_match_keeps_per_level_files(monkeypatch):
    # A content-matched level keeps only the files that matched, and a level
    # with no matching files drops out of the result entirely.
    monkeypatch.setattr(
        _cue,
        "presets",
        SimpleNamespace(
            intensity=SimpleNamespace(
                get=lambda n: {
                    "levels": [
                        {"id": 1, "files": ["moans/soft", "gasps/deep"]},
                        {"id": 2, "files": ["gasps/light", "pants/heavy"]},
                    ]
                }
            )
        ),
    )
    assert _util._cue_filter_igroup_folders("Build", "gasps") == [
        {"id": 1, "files": ["gasps/deep"]},
        {"id": 2, "files": ["gasps/light"]},
    ]


# ---------------------------------------------------------------------------
# Branch tails -- error paths, Py2 unicode paths, dead-code fallbacks
# ---------------------------------------------------------------------------


def test_unwrap_displayable_target_callable_raises():
    # A displayable whose _target() raises resolves to None -> break keeps d.
    def _boom():
        raise RuntimeError("boom")

    outer = SimpleNamespace(_target=_boom)
    assert _cue_unwrap_displayable(outer) is outer


def test_atl_child_displayables_compile_ok_still_no_block():
    # compile() succeeds but never populates .block: the None guard returns.
    d = _atl.ATLTransformBase()
    d.compile = lambda: None
    assert _cue_atl_child_displayables(d) is None


def test_atl_child_displayables_statement_missing_child():
    # A Child with no .child attribute is skipped, not fatal.
    d = _atl.ATLTransformBase()
    d.block = SimpleNamespace(statements=[_atl.Child()])
    assert _cue_atl_child_displayables(d) is None


def test_to_str_py2_unicode_paths(monkeypatch):
    # Ren'Py 7.x runs Python 2 where unicode is a real builtin; force the
    # Py2 branches on Python 3 by pointing the module's unicode at a type
    # whose instances carry .encode() like the real builtin.
    class _Unicode(object):
        def __init__(self, value):
            self.value = value

        def encode(self, encoding="utf-8"):
            return self.value.encode(encoding)

    monkeypatch.setattr(_util, "unicode", _Unicode, raising=False)
    assert _util._to_str(_Unicode("hi")) == b"hi"
    assert _util._to_str(b"hi") == b"hi"
    assert _util._to_str({b"a": b"x"}) == {b"a": b"x"}
    assert _util._to_str([b"x"]) == [b"x"]
    assert _util._to_str(42) == 42


def test_unwrap_persistent_unicode_branch(monkeypatch):
    monkeypatch.setattr(_util, "unicode", int, raising=False)
    assert _cue_unwrap_persistent(42) == 42


def test_cue_is_str_py2_accepts_unicode(monkeypatch):
    # Ren'Py 7.x: _CUE_TEXT_TYPES is (str, unicode) -- text checks must accept
    # both, exactly like the runtime computes it under Py2.
    class _Unicode(object):
        pass

    monkeypatch.setattr(_util, "_CUE_TEXT_TYPES", (str, _Unicode))
    assert _cue_is_str("hi")
    assert _cue_is_str(_Unicode())
    assert not _cue_is_str(42)


def test_cue_is_str_py3_accepts_str_only():
    # Ren'Py 8.x: str is the only text type; bytes is not text.
    assert _cue_is_str("hi")
    assert not _cue_is_str(b"hi")
    assert not _cue_is_str(42)


def test_compile_query_skips_empty_alternative():
    match = _util._cue_compile_query("a|")
    assert match("axx") is True
    assert match("zzz") is False


def test_parse_time_non_string_returns_none():
    assert _cue_parse_time(123) is None


def test_clear_debug_log_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.clear_debug()  # dir missing -> makedirs; must not raise
    assert (tmp_path / "renpy_cue" / "debug.log").exists()


def test_clear_debug_log_swallows_error(tmp_path, monkeypatch):
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))

    def _boom(path):
        raise OSError("no perms")

    monkeypatch.setattr(os, "makedirs", _boom)

    _cue_logger.clear_debug()  # must not raise


def test_screenshake_swallows_inner_error(monkeypatch):
    # A partial-shaped object whose func access raises is swallowed.
    class _BrokenPartial(object):
        pass

    monkeypatch.setattr(functools, "partial", _BrokenPartial)
    assert _cue_is_screenshake(_BrokenPartial()) is False


# ---------------------------------------------------------------------------
# Engine hook wrappers -- with_statement / config.show screenshake detection
# ---------------------------------------------------------------------------


def Move(bounce=False, repeat=False, delay=None):
    """Fake renpy.transitions.Move so _cue_is_screenshake recognizes it."""
    pass


def _shake(bounce=True, repeat=True, delay=0.1):
    return functools.partial(Move, bounce=bounce, repeat=repeat, delay=delay)


class _RecordingShow(object):
    """Fake original engine hook: records forwarded calls, returns a sentinel."""

    def __init__(self, result="RESULT"):
        self.result = result
        self.calls = []  # type: list

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def test_with_statement_wrapper_detects_shake():
    hook = _RecordingShow()
    wrapper = _util._cue_wrap_with_statement(hook)
    _cue.ctx._shake_just_happened = False
    wrapper(_shake())
    assert _cue.ctx._shake_just_happened is True


def test_with_statement_wrapper_non_shake_leaves_flag_clear():
    hook = _RecordingShow()
    wrapper = _util._cue_wrap_with_statement(hook)
    _cue.ctx._shake_just_happened = False
    wrapper(_shake(bounce=False))
    assert _cue.ctx._shake_just_happened is False


def test_with_statement_wrapper_forwards_args_verbatim():
    hook = _RecordingShow()
    wrapper = _util._cue_wrap_with_statement(hook)
    result = wrapper(_shake(), always=True, paired="p", clear=False)
    assert result == "RESULT"
    args, kwargs = hook.calls[0]
    assert kwargs == {"always": True, "paired": "p", "clear": False}


def test_config_show_wrapper_detects_shake_in_at_list_kwarg():
    show = _RecordingShow()
    wrapper = _util._cue_wrap_config_show(show)
    _cue.ctx._shake_just_happened = False
    wrapper("bg", at_list=[_shake()])
    assert _cue.ctx._shake_just_happened is True


def test_config_show_wrapper_detects_shake_in_at_list_positional():
    show = _RecordingShow()
    wrapper = _util._cue_wrap_config_show(show)
    _cue.ctx._shake_just_happened = False
    wrapper("bg", [_shake()])
    assert _cue.ctx._shake_just_happened is True


def test_config_show_wrapper_non_shake_leaves_flag_clear():
    show = _RecordingShow()
    wrapper = _util._cue_wrap_config_show(show)
    _cue.ctx._shake_just_happened = False
    wrapper("bg", at_list=[_shake(delay=0.9)])
    assert _cue.ctx._shake_just_happened is False


def test_config_show_wrapper_forwards_args_verbatim():
    show = _RecordingShow()
    wrapper = _util._cue_wrap_config_show(show)
    result = wrapper("bg", at_list=[], transient=True, munge_name="x")
    assert result == "RESULT"
    args, kwargs = show.calls[0]
    assert args == ("bg",)
    assert kwargs["at_list"] == []
    assert kwargs["transient"] is True
    assert kwargs["munge_name"] == "x"


def test_config_show_wrapper_no_at_list_ok():
    show = _RecordingShow()
    wrapper = _util._cue_wrap_config_show(show)
    _cue.ctx._shake_just_happened = False
    result = wrapper("bg", layer="master")
    assert result == "RESULT"
    assert _cue.ctx._shake_just_happened is False
    assert show.calls[0][1]["layer"] == "master"


# ---------------------------------------------------------------------------
# Text escaping
# ---------------------------------------------------------------------------


def test_escape_text_none_returns_none():
    assert _cue_escape_text(None) is None


def test_escape_text_plain_string_unchanged():
    assert _cue_escape_text("plain string 123") == "plain string 123"


def test_escape_text_doubles_braces():
    assert _cue_escape_text("a{b}c") == "a{{b}c"


def test_escape_text_doubles_brackets():
    assert _cue_escape_text("a[b]c") == "a[[b]c"


def test_escape_text_mixed():
    assert _cue_escape_text("a{b}[c]{d}") == "a{{b}[[c]{{d}"


def test_escape_text_assorted_printables_unchanged():
    s = "ab c 09 .-_!@#$%^&*()+=|/\\;:~`'"
    assert _cue_escape_text(s) == s


def test_escape_text_brackets_false_braces_only():
    assert _cue_escape_text("a{b}[c]", brackets=False) == "a{{b}[c]"


def test_escape_text_non_string_passes_through():
    obj = object()
    assert _cue_escape_text(obj) is obj


# ---------------------------------------------------------------------------
# Anomaly snapshot (trigger-debug.log ring dump)
# ---------------------------------------------------------------------------


def test_snapshot_debug_writes_marker_and_ring(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_log("line one")
    _cue_log("line two")
    _cue_logger.snapshot_debug("TD-ANOMALY type=late vid=x delta=[1.9] t=123.00")
    # Ring is current even without a flush -- no debug.log write required.
    text = (tmp_path / "renpy_cue" / "trigger-debug.log").read_text()
    assert "TD-ANOMALY" in text
    assert "line one" in text
    assert "line two" in text


def test_snapshot_debug_appends_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    _cue_logger.snapshot_debug("first marker")
    _cue_logger.snapshot_debug("second marker")
    text = (tmp_path / "renpy_cue" / "trigger-debug.log").read_text()
    assert "first marker" in text
    assert "second marker" in text
    # Two separate dump blocks (each opens with the 60-char separator), not one overwrite.
    assert text.count("=" * 60) == 2


def test_snapshot_ring_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_cue, "paths", SimpleNamespace(in_game_base_dir="renpy_cue"))
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    n = _logger_mod.CUE_TRIGGER_SNAPSHOT_LINES + 10
    for i in range(n):
        _cue_log("ring line {}".format(i))
    _cue_logger.snapshot_debug("marker")
    text = (tmp_path / "renpy_cue" / "trigger-debug.log").read_text()
    assert "ring line 0" not in text  # oldest evicted
    assert "ring line {}".format(n - 1) in text  # newest kept
