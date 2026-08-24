# -*- coding: utf-8 -*-
# Tests for the audio-library tree managers: the pure _cue_filter_tree search
# helper (util.py), CueAudioTreeManager (scan, tree walk, search cap,
# debounced rebuild), CueUserMusic / CueGameMusic (scan sources), and
# CueSfxLibraryTree (file enable toggle, preset/folder expand state, pool-ref
# rows, sidebar mode).

import copy
import os
import random as _random
import types

import pytest

import renpy
import renpy as _renpy

from renpy.store import persistent

import cue_lib.audio.audio_tree as _tree
import cue_lib.audio.game_music as _game
import cue_lib.audio.user_music as _user
import cue_lib.util as _util
from cue_lib.audio.audio_tree import CUE_SEARCH_MAX_ROWS, CueAudioTreeManager
from cue_lib.audio.game_music import CueGameMusic
from cue_lib.audio.sfx_manager import CueSfxManager, _cue_sfx_channel_index, _cue_sfx_channel_name
from cue_lib.audio.user_music import CueUserMusic
from cue_lib.constants import (
    CUE_PERSIST_SIDEBAR_MODE,
    CUE_SIDEBAR_DEFAULT_WIDTH,
    CUE_SIDEBAR_MIN_WIDTH,
    CUE_SIDEBAR_MAX_WIDTH_RATIO,
)
from cue_lib.util import _cue_build_tree, _cue_filter_tree

from tests.fakes import FakeDb

# Small tree spanning folder-name, file-name, and multi-term matches.
FILES = [
    "v2/agrat/01_SubtleMo.mp3",
    "v2/agrat/02_IntenseMo.mp3",
    "v2/agrat/03_ClosedMo.mp3",
    "v2/amira/01_NormalMo.mp3",
    "v2/anya/04_IntenseMo.mp3",
    "v2/nora/03_IntenseMo.mp3",
]


def _children_names(items):
    return [c["name"] for c in items]


class _ScanSrc(CueAudioTreeManager):
    """Scan-source stub: fills results_set from a configured file list."""

    def __init__(self, files):
        super(_ScanSrc, self).__init__()
        self._files = files

    def _discover(self, results_set):
        results_set.update(self._files)


def _rows(manager):
    return [(r["type"], r["name"], r["full_path"], r["depth"]) for r in manager.visible_tree]


# ==========================================================================
# _cue_filter_tree (pure)
# ==========================================================================


def test_filter_tree_case_insensitive_file_match():
    tree = _cue_build_tree(["v2/agrat/02_IntenseMo.mp3", "v2/amira/01_NormalMo.mp3"])
    filtered = _cue_filter_tree(tree, "intense")
    # v2/ and agrat/ survive as ancestors of the match; amira/ is pruned.
    assert _children_names(filtered) == ["v2/"]
    v2 = filtered[0]
    assert _children_names(v2["children"]) == ["agrat/"]
    assert _children_names(v2["children"][0]["children"]) == ["02_IntenseMo.mp3"]


def test_filter_tree_folder_match_keeps_full_contents():
    tree = _cue_build_tree(["v2/agrat/01_SubtleMo.mp3", "v2/agrat/02_IntenseMo.mp3", "v2/agrat/03_ClosedMo.mp3"])
    filtered = _cue_filter_tree(tree, "agrat")
    assert _children_names(filtered) == ["v2/"]
    agrat = filtered[0]["children"][0]
    assert _children_names(agrat["children"]) == ["01_SubtleMo.mp3", "02_IntenseMo.mp3", "03_ClosedMo.mp3"]


def test_filter_tree_prunes_unrelated_branches():
    filtered = _cue_filter_tree(_cue_build_tree(FILES), "intense")
    assert _children_names(filtered) == ["v2/"]
    v2 = filtered[0]
    # amira/ removed entirely; siblings keep only their matching file.
    assert _children_names(v2["children"]) == ["agrat/", "anya/", "nora/"]
    assert _children_names(v2["children"][0]["children"]) == ["02_IntenseMo.mp3"]
    assert _children_names(v2["children"][1]["children"]) == ["04_IntenseMo.mp3"]
    assert _children_names(v2["children"][2]["children"]) == ["03_IntenseMo.mp3"]


def test_filter_tree_multi_term_and():
    filtered = _cue_filter_tree(_cue_build_tree(FILES), "nora intense")
    v2 = filtered[0]
    assert _children_names(v2["children"]) == ["nora/"]
    assert _children_names(v2["children"][0]["children"]) == ["03_IntenseMo.mp3"]


def test_filter_tree_pipe_or():
    filtered = _cue_filter_tree(_cue_build_tree(FILES), "amira|anya")
    v2 = filtered[0]
    assert _children_names(v2["children"]) == ["amira/", "anya/"]
    # Folder-name matches keep all descendants.
    assert _children_names(v2["children"][0]["children"]) == ["01_NormalMo.mp3"]


def test_filter_tree_pipe_or_with_and_alternative():
    filtered = _cue_filter_tree(_cue_build_tree(FILES), "nora intense|amira")
    v2 = filtered[0]
    # amira matches by folder name (all contents); nora matches only the file
    # that contains both "nora" and "intense".
    assert _children_names(v2["children"]) == ["amira/", "nora/"]
    assert _children_names(v2["children"][0]["children"]) == ["01_NormalMo.mp3"]
    assert _children_names(v2["children"][1]["children"]) == ["03_IntenseMo.mp3"]


def test_filter_tree_escaped_pipe_literal():
    tree = _cue_build_tree(["v2/mix|take/01.wav"])
    filtered = _cue_filter_tree(tree, "mix\\|take")
    assert _children_names(filtered) == ["v2/"]
    assert _children_names(filtered[0]["children"]) == ["mix|take/"]


def test_filter_tree_empty_query_matches_nothing():
    tree = _cue_build_tree(FILES)
    assert _cue_filter_tree(tree, "") == []
    assert _cue_filter_tree(tree, "   ") == []


def test_filter_tree_preserves_ordering():
    tree = _cue_build_tree(["b/x.mp3", "a/x.mp3"])
    filtered = _cue_filter_tree(tree, "x")
    assert _children_names(filtered) == ["a/", "b/"]


def test_filter_tree_does_not_mutate_source():
    tree = _cue_build_tree(FILES)
    snapshot = copy.deepcopy(tree)
    _cue_filter_tree(tree, "intense")
    assert tree == snapshot


# ==========================================================================
# CueAudioTreeManager -- scan
# ==========================================================================


def test_scan_discover_error_sets_scan_error():
    m = CueAudioTreeManager()  # base _discover raises NotImplementedError
    m.scan()
    assert "Failed to scan audio" in m.scan_error
    assert m.files == []
    assert m.tree == []
    assert m._file_index == {}


def test_scan_sorts_and_builds_tree():
    m = _ScanSrc(["z.ogg", "a/b.ogg", "a/c.ogg"])
    m.scan()
    assert m.files == ["a/b.ogg", "a/c.ogg", "z.ogg"]
    assert m.scan_error == ""
    assert m._file_index == {"a/b.ogg": 0, "a/c.ogg": 1, "z.ogg": 2}
    # tree: folder "a/" first, then file z.ogg
    assert [n["name"] for n in m.tree] == ["a/", "z.ogg"]
    # collapsed folder hides children
    assert _rows(m) == [("folder", "a/", "a/", 0), ("file", "z.ogg", "z.ogg", 0)]


def test_discover_walk_dir(tmp_path):
    audio = str(tmp_path / "audio")
    for rel in ("x.ogg", "sub/y.mp3", "notes.txt"):
        p = os.path.join(audio, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    m = _ScanSrc([])
    results = set()
    m._discover_walk_dir(results, audio)
    assert results == {"x.ogg", "sub/y.mp3"}


def test_discover_walk_dir_missing_folder_empty(tmp_path):
    m = _ScanSrc([])
    results = set()
    m._discover_walk_dir(results, str(tmp_path / "nope"))
    assert results == set()


# ==========================================================================
# CueAudioTreeManager -- visible tree + search
# ==========================================================================


def test_rebuild_tree_expanded_folder_shows_children():
    m = _ScanSrc(["a/b.ogg", "a/c.ogg", "z.ogg"])
    m.scan()
    m.expanded_folders["a/"] = True
    m.rebuild_tree()
    assert _rows(m) == [
        ("folder", "a/", "a/", 0),
        ("file", "b.ogg", "a/b.ogg", 1),
        ("file", "c.ogg", "a/c.ogg", 1),
        ("file", "z.ogg", "z.ogg", 0),
    ]


def test_rebuild_tree_search_filters_and_expands_all():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.search_query = "intense"
    mgr.rebuild_tree()
    folders = [row for row in mgr.visible_tree if row["type"] == "folder"]
    assert folders
    assert all(row["expanded"] for row in folders)
    files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    assert files == ["v2/agrat/02_IntenseMo.mp3", "v2/anya/04_IntenseMo.mp3", "v2/nora/03_IntenseMo.mp3"]


def test_rebuild_tree_idle_respects_expansion():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(["v2/a.mp3", "v2/b.mp3"])
    mgr.expanded_folders = {"v2/": False}
    mgr.rebuild_tree()
    # Collapsed v2/ shows as a folder row only; children stay hidden.
    assert [row["type"] for row in mgr.visible_tree] == ["folder"]
    assert len(mgr.visible_tree) == 1


def test_rebuild_tree_search_caps_broad_query():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(["f{}.mp3".format(i) for i in range(300)])
    mgr.search_query = "f"
    mgr.rebuild_tree()
    assert len(mgr.visible_tree) <= CUE_SEARCH_MAX_ROWS
    assert mgr.search_truncated == 300 - CUE_SEARCH_MAX_ROWS


def test_rebuild_tree_idle_not_capped():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(["f{}.mp3".format(i) for i in range(300)])
    mgr.rebuild_tree()
    assert mgr.search_truncated == 0
    assert len(mgr.visible_tree) == 300


def test_clear_search_restores_tree_and_expansion_state():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.expanded_folders = {"v2/": True, "v2/amira/": True}
    mgr.rebuild_tree()
    full_before = list(mgr.visible_tree)

    mgr.search_query = "intense"
    mgr.rebuild_tree()
    # Search force-expands everything, so the view can be longer than the
    # idle one; the invariants are that unrelated branches are pruned and
    # the saved user expansion state is never touched.
    search_files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    assert "v2/amira/01_NormalMo.mp3" not in search_files
    assert all(row["expanded"] for row in mgr.visible_tree if row["type"] == "folder")
    assert mgr.expanded_folders == {"v2/": True, "v2/amira/": True}

    mgr.clear_search()
    assert mgr.search_query == ""
    assert mgr.expanded_folders == {"v2/": True, "v2/amira/": True}
    assert mgr.visible_tree == full_before


def test_clear_search_noop_when_empty(monkeypatch):
    m = _ScanSrc(["z.ogg"])
    m.scan()
    rec = []
    monkeypatch.setattr(m, "rebuild_tree", lambda: rec.append(1))
    m.clear_search()
    assert rec == []


def test_toggle_folder_noop_during_search():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.search_query = "intense"
    mgr.expanded_folders = {"v2/agrat/": False}
    mgr.rebuild_tree()
    mgr.toggle_folder("v2/agrat/")
    assert mgr.expanded_folders == {"v2/agrat/": False}


def test_toggle_folder_normal_when_idle():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(["v2/a.mp3", "v2/b.mp3"])
    mgr.rebuild_tree()
    mgr.toggle_folder("v2/")
    assert mgr.expanded_folders.get("v2/") is True


def test_toggle_folder_expands_new_and_flips_existing():
    m = _ScanSrc(["a/b.ogg"])
    m.scan()
    m.toggle_folder("a/")
    assert m.expanded_folders["a/"] is True
    m.toggle_folder("a/")
    assert m.expanded_folders["a/"] is False


def test_maybe_rebuild_only_on_query_change():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.search_query = "intense"
    mgr.maybe_rebuild()
    files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    assert files == ["v2/agrat/02_IntenseMo.mp3", "v2/anya/04_IntenseMo.mp3", "v2/nora/03_IntenseMo.mp3"]
    before = list(mgr.visible_tree)
    mgr.maybe_rebuild()  # unchanged query -> no-op
    assert mgr.visible_tree == before
    mgr.search_query = "nora"
    mgr.maybe_rebuild()
    files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    assert files == ["v2/nora/03_IntenseMo.mp3"]


def test_clear_search_resets_debounce_state():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.search_query = "intense"
    mgr.maybe_rebuild()
    assert mgr._search_applied == "intense"
    mgr.clear_search()
    assert mgr._search_applied == ""
    assert mgr.search_truncated == 0


# ==========================================================================
# CueUserMusic
# ==========================================================================


def test_user_music_discover_prefixes(monkeypatch, tmp_path):
    music_dir = str(tmp_path / "music") + "/"
    for rel in ("song.ogg", "sub/track.mp3", "notes.txt"):
        p = os.path.join(music_dir, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    fake = types.SimpleNamespace(paths=types.SimpleNamespace(music_dir=music_dir))
    monkeypatch.setattr(_user, "_cue", fake)
    m = CueUserMusic()
    results = set()
    m._discover(results)
    assert results == {"music/song.ogg", "music/sub/track.mp3"}


# ==========================================================================
# CueGameMusic
# ==========================================================================


def test_game_music_discover_filters(monkeypatch):
    files = [
        "music/bgm.ogg",
        "Bgm/Upper.OGG",  # case-insensitive dir + ext
        "bgm\\intro.mp3",  # backslash normalized to forward slash
        "ost/track.wav",
        "soundtrack/t.opus",
        "images/bg.png",  # not an audio ext
        "sfx/shot.ogg",  # audio but not a music dir
        "music/notes.txt",  # not an audio ext
    ]
    monkeypatch.setattr(_renpy, "list_files", lambda: files)
    m = CueGameMusic()
    results = set()
    m._discover(results)
    assert results == {"music/bgm.ogg", "Bgm/Upper.OGG", "bgm/intro.mp3", "ost/track.wav", "soundtrack/t.opus"}


# ==========================================================================
# CueSfxLibraryTree
# ==========================================================================


@pytest.fixture
def sfx(tmp_path):
    audio = str(tmp_path / "audio") + "/"
    # Library-tree tests only exercise the tree; volume/ctx/markers are unused.
    return CueSfxManager(
        types.SimpleNamespace(audio_dir=audio), FakeDb(), types.SimpleNamespace(), types.SimpleNamespace(), False
    ).library


def test_sfx_init_state(sfx):
    assert sfx.expanded_file_refs == {}
    assert sfx.presets_expanded is False
    assert sfx.expanded_presets == {}
    assert sfx.video_presets_expanded is False
    assert sfx.expanded_video_presets == {}
    assert sfx.expanded_video_pools == {}
    assert sfx.disabled_files == set()
    assert sfx.ilevel_add_target is None
    assert sfx.expanded_ilevels == {}
    assert sfx.is_sidebar_mode is False
    assert sfx.sidebar_width == CUE_SIDEBAR_DEFAULT_WIDTH


def test_sfx_discover_walks_audio_dir(sfx, tmp_path):
    audio = str(tmp_path / "audio") + "/"
    for rel in ("a.ogg", "sub/b.wav"):
        p = os.path.join(audio, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    results = set()
    sfx._discover(results)
    assert results == {"a.ogg", "sub/b.wav"}


def test_sfx_file_node_index_and_enabled(sfx):
    sfx._file_index = {"a.ogg": 3}
    sfx.disabled_files = {"a.ogg"}
    node = sfx._file_node({"name": "a.ogg"}, "a.ogg", 0)
    assert node["index"] == 3
    assert node["enabled"] is False


def test_sfx_toggle_file_enabled_adds(sfx, monkeypatch):
    rec = []
    monkeypatch.setattr(sfx, "rebuild_tree", lambda: rec.append(1))
    sfx.toggle_file_enabled("a.ogg")
    assert "a.ogg" in sfx.disabled_files
    assert rec == [1]
    assert sfx._db.saved[-1]["disabled_files"] == ["a.ogg"]


def test_sfx_toggle_file_enabled_removes(sfx):
    sfx.disabled_files = {"a.ogg"}
    sfx.toggle_file_enabled("a.ogg")
    assert "a.ogg" not in sfx.disabled_files
    assert sfx._db.saved[-1]["disabled_files"] == []


def test_sfx_toggle_file_ref_expand(sfx):
    sfx.toggle_file_ref_expand("pool/")
    assert sfx.expanded_file_refs["pool/"] is True
    sfx.toggle_file_ref_expand("pool/")
    assert sfx.expanded_file_refs["pool/"] is False


def test_sfx_count_file_list_rows(sfx):
    sfx.expanded_file_refs["dir/"] = True
    n = sfx.count_file_list_rows("dir/", ["a.ogg", "b.ogg"], ["c.ogg"])
    assert n == 4  # label + 2 children + direct file


def test_sfx_count_file_list_rows_expands_folder_ref(sfx, monkeypatch):
    fake = types.SimpleNamespace(
        sfx=types.SimpleNamespace(library=types.SimpleNamespace(files=["pool/a.ogg"], disabled_files=set()))
    )
    monkeypatch.setattr(_util, "_cue", fake)
    sfx.expanded_file_refs["pool/"] = True
    n = sfx.count_file_list_rows(None, None, ["pool/"])
    assert n == 2  # ref row + 1 expanded file


def test_sfx_count_file_list_rows_collapsed_ref(sfx, monkeypatch):
    fake = types.SimpleNamespace(
        sfx=types.SimpleNamespace(library=types.SimpleNamespace(files=["pool/a.ogg"], disabled_files=set()))
    )
    monkeypatch.setattr(_util, "_cue", fake)
    n = sfx.count_file_list_rows(None, None, ["pool/"])
    assert n == 1  # collapsed: ref row only


def test_sfx_toggle_presets_expand(sfx):
    sfx.toggle_presets_expand()
    assert sfx.presets_expanded is True
    sfx.toggle_presets_expand()
    assert sfx.presets_expanded is False


def test_sfx_toggle_preset_expand(sfx):
    sfx.toggle_preset_expand("p")
    assert sfx.expanded_presets["p"] is True
    sfx.toggle_preset_expand("p")
    assert sfx.expanded_presets["p"] is False


def test_sfx_toggle_video_presets_expand(sfx):
    sfx.toggle_video_presets_expand()
    assert sfx.video_presets_expanded is True
    sfx.toggle_video_presets_expand()
    assert sfx.video_presets_expanded is False


def test_sfx_toggle_video_preset_expand(sfx):
    sfx.toggle_video_preset_expand("v")
    assert sfx.expanded_video_presets["v"] is True
    sfx.toggle_video_preset_expand("v")
    assert sfx.expanded_video_presets["v"] is False


def test_sfx_toggle_video_pool_expand(sfx):
    sfx.toggle_video_pool_expand("v", 0)
    assert sfx.expanded_video_pools["v"][0] is True
    sfx.toggle_video_pool_expand("v", 0)
    assert sfx.expanded_video_pools["v"][0] is False


def test_sfx_toggle_video_pool_expand_per_pool(sfx):
    sfx.toggle_video_pool_expand("v", 0)
    sfx.toggle_video_pool_expand("v", 1)
    assert sfx.expanded_video_pools["v"] == {0: True, 1: True}


def test_sfx_toggle_sidebar_mode_persists(sfx, monkeypatch):
    rec = []
    persistent._cue = {}
    monkeypatch.setattr(_renpy, "restart_interaction", lambda: rec.append(1))
    sfx.toggle_sidebar_mode()
    assert sfx.is_sidebar_mode is True
    assert persistent._cue[CUE_PERSIST_SIDEBAR_MODE] is True
    sfx.toggle_sidebar_mode()
    assert sfx.is_sidebar_mode is False
    assert persistent._cue[CUE_PERSIST_SIDEBAR_MODE] is False
    assert rec == [1, 1]


def test_sfx_set_sidebar_width_clamps(sfx):
    sfx.set_sidebar_width(50)
    assert sfx.sidebar_width == CUE_SIDEBAR_MIN_WIDTH
    sfx.set_sidebar_width(5000)
    assert sfx.sidebar_width == int(renpy.config.screen_width * CUE_SIDEBAR_MAX_WIDTH_RATIO)
    # A width strictly inside the bounds passes through unchanged.
    mid = int((CUE_SIDEBAR_MIN_WIDTH + int(renpy.config.screen_width * CUE_SIDEBAR_MAX_WIDTH_RATIO)) / 2)
    sfx.set_sidebar_width(mid)
    assert sfx.sidebar_width == mid


def test_sfx_ilevel_add_mode_toggle_single_target(sfx):
    assert sfx.ilevel_add_target is None
    sfx.toggle_ilevel_add_mode("Impacts", 1)
    assert sfx.ilevel_add_target == ("Impacts", 1)
    # Entering add mode expands the group and the level's file rows so
    # appends land visibly.
    assert sfx.expanded_igroups.get("Impacts") is True
    assert 1 in sfx.expanded_ilevels.get("Impacts", set())
    # Toggling the active level exits add-files mode but keeps the rows
    # expanded -- the manual collapse state is untouched.
    sfx.toggle_ilevel_add_mode("Impacts", 1)
    assert sfx.ilevel_add_target is None
    assert sfx.expanded_igroups.get("Impacts") is True


def test_sfx_ilevel_add_mode_switches_level(sfx):
    sfx.toggle_ilevel_add_mode("Impacts", 1)
    sfx.toggle_ilevel_add_mode("Impacts", 2)
    assert sfx.ilevel_add_target == ("Impacts", 2)  # only one level at a time
    assert 1 in sfx.expanded_ilevels.get("Impacts", set())
    assert 2 in sfx.expanded_ilevels.get("Impacts", set())


def test_sfx_ilevel_add_file_calls_intensity(sfx):
    calls = []
    sfx._intensity = types.SimpleNamespace(
        get_igroup=lambda g: {"levels": [{"id": 1}, {"id": 2}]},
        add_level_file=lambda g, lid, ref: calls.append((g, lid, ref)),
    )
    sfx.ilevel_add_file("Impacts", 2, "soft/a.ogg")
    assert calls == [("Impacts", 2, "soft/a.ogg")]


def test_sfx_ilevel_add_folder_normalizes_ref(sfx):
    calls = []
    sfx._intensity = types.SimpleNamespace(
        get_igroup=lambda g: {"levels": [{"id": 1}]}, add_level_file=lambda g, lid, ref: calls.append((g, lid, ref))
    )
    sfx.ilevel_add_folder("Impacts", 1, "soft")
    assert calls == [("Impacts", 1, "soft/")]


def test_sfx_ilevel_add_clears_stale_group_target(sfx):
    # Deleting the active add-target group leaves a stale target; the next
    # add clears it instead of failing against a deleted group.
    sfx._intensity = types.SimpleNamespace(get_igroup=lambda g: None)
    sfx.ilevel_add_target = ("Gone", 1)
    sfx.ilevel_add_file("Gone", 1, "soft/")
    assert sfx.ilevel_add_target is None


def test_sfx_ilevel_add_file_noop_before_wired(sfx):
    sfx._intensity = None
    sfx.ilevel_add_file("Impacts", 1, "soft/")
    assert sfx.ilevel_add_target is None


def test_sfx_add_level_records_id_for_autoexpand(sfx):
    sfx._intensity = types.SimpleNamespace(add_level=lambda g: 3)
    sfx.add_level("Impacts")
    assert sfx.expanded_igroups.get("Impacts") is True
    assert 3 in sfx.expanded_ilevels.get("Impacts", set())


def test_sfx_add_level_missing_group_no_record(sfx):
    sfx._intensity = types.SimpleNamespace(add_level=lambda g: None)
    sfx.add_level("Impacts")
    assert "Impacts" not in sfx.expanded_igroups
    assert "Impacts" not in sfx.expanded_ilevels


def test_sfx_toggle_ilevel_expand(sfx):
    sfx.toggle_ilevel_expand("Impacts", 1)
    assert 1 in sfx.expanded_ilevels.get("Impacts", set())
    sfx.toggle_ilevel_expand("Impacts", 1)
    assert 1 not in sfx.expanded_ilevels.get("Impacts", set())


def test_sfx_level_has_file(sfx):
    sfx._intensity = types.SimpleNamespace(level_files_by_id=lambda g, lid: ["soft/", "a.ogg"])
    assert sfx.level_has_file("Impacts", 1, "soft/") is True
    assert sfx.level_has_file("Impacts", 1, "nope.ogg") is False
    sfx._intensity = None
    assert sfx.level_has_file("Impacts", 1, "soft/") is False


def test_sfx_preview_level_plays_random_resolved(monkeypatch):
    from cue_lib.audio.sfx_manager import CueSfxManager

    mgr = CueSfxManager(
        types.SimpleNamespace(audio_dir=""), FakeDb(), types.SimpleNamespace(), types.SimpleNamespace(), False
    )
    mgr.library._intensity = types.SimpleNamespace(level_files_by_id=lambda g, lid: ["soft/", "a.ogg"])
    # _cue_resolve_files reads _cue.sfx.library.files; stub the module _cue.
    fake = types.SimpleNamespace(
        sfx=types.SimpleNamespace(library=types.SimpleNamespace(files=["a.ogg", "soft/a.ogg"], disabled_files=set()))
    )
    monkeypatch.setattr(_util, "_cue", fake)
    picked = []
    monkeypatch.setattr(_random, "choice", lambda files: picked.append(files) or files[0])
    previewed = []
    monkeypatch.setattr(mgr, "preview_sfx", lambda f, volume=1.0: previewed.append(f))
    mgr.preview_level("Impacts", 1)
    assert picked == [["soft/a.ogg", "a.ogg"]]
    assert previewed == ["soft/a.ogg"]
    # Empty level previews nothing.
    mgr.library._intensity = types.SimpleNamespace(level_files_by_id=lambda g, lid: [])
    mgr.preview_level("Impacts", 1)
    assert previewed == ["soft/a.ogg"]


# ---------------------------------------------------------------------------
# SFX channel helpers (moved here from util.py with the playback manager)
# ---------------------------------------------------------------------------


def test_sfx_channel_name_and_index():
    assert _cue_sfx_channel_name(3) == "_cue_3"
    assert _cue_sfx_channel_index("_cue_7") == 7


# ---------------------------------------------------------------------------
# One-time root expansion on scan (opt-in, _auto_expand_roots)
# ---------------------------------------------------------------------------


# A real scan needs a working _discover(); the concrete managers read _cue
# paths, so test the base mechanism with a lightweight subclass instead.
class _ScanTree(CueAudioTreeManager):
    _auto_expand_roots = True

    def _discover(self, results_set):
        for path in self._files_in:
            results_set.add(path)


class _NoRootExpandTree(CueAudioTreeManager):
    _auto_expand_roots = False

    def _discover(self, results_set):
        for path in self._files_in:
            results_set.add(path)


def test_scan_expands_roots_once_when_opted_in():
    mgr = _ScanTree()
    mgr._files_in = ["music/a.mp3", "music/sub/b.mp3", "audio/c.mp3"]
    mgr.scan()
    # Only depth-0 folders get the default; subfolders stay collapsed.
    assert mgr.expanded_folders == {"music/": True, "audio/": True}
    root_rows = [r for r in mgr.visible_tree if r["type"] == "folder" and r["depth"] == 0]
    assert all(r["expanded"] for r in root_rows)
    # The subfolder is rendered as a collapsed row, not force-expanded.
    sub_rows = [r for r in mgr.visible_tree if r["type"] == "folder" and r["depth"] == 1]
    assert sub_rows and all(not r["expanded"] for r in sub_rows)
    # Files under the expanded roots are visible; the collapsed subfolder's
    # file stays hidden.
    file_paths = [r["full_path"] for r in mgr.visible_tree if r["type"] == "file"]
    assert file_paths == ["audio/c.mp3", "music/a.mp3"]


def test_scan_keeps_roots_collapsed_by_default():
    mgr = _NoRootExpandTree()
    mgr._files_in = ["v2/a.mp3", "v2/b.mp3"]
    mgr.scan()
    assert mgr.expanded_folders == {}
    # Collapsed root renders as a single folder row; children stay hidden.
    assert [r["type"] for r in mgr.visible_tree] == ["folder"]
    assert len(mgr.visible_tree) == 1


def test_scan_root_expansion_is_one_time():
    mgr = _ScanTree()
    mgr._files_in = ["music/a.mp3", "audio/c.mp3"]
    mgr.scan()
    assert mgr.expanded_folders == {"music/": True, "audio/": True}
    # User collapses a root...
    mgr.toggle_folder("music/")
    assert mgr.expanded_folders["music/"] is False
    # ...a re-scan must not re-expand it, and the untouched root stays open.
    mgr.scan()
    assert mgr.expanded_folders["music/"] is False
    assert mgr.expanded_folders["audio/"] is True


def test_scan_empty_first_scan_does_not_consume_root_expansion():
    mgr = _ScanTree()
    mgr._files_in = []
    mgr.scan()
    assert mgr.expanded_folders == {}
    # Files added later: the one-time default still applies on the first
    # non-empty scan.
    mgr._files_in = ["music/a.mp3"]
    mgr.scan()
    assert mgr.expanded_folders == {"music/": True}


def test_music_managers_opt_into_root_expansion():
    assert CueUserMusic._auto_expand_roots is True
    assert CueGameMusic._auto_expand_roots is True
    # The base default (shared with the SFX library) is off.
    assert CueAudioTreeManager._auto_expand_roots is False
