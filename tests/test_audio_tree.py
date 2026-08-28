# -*- coding: utf-8 -*-
# Tests for the audio-library tree managers: the pure _cue_filter_tree search
# helper (util.py), CueAudioTreeManager (scan, tree walk, search cap,
# debounced rebuild), CueMusicTree (scan sources + merged library), and
# CueSfxLibraryTree (file enable toggle, preset/folder expand state, pool-ref
# rows, sidebar mode).

import copy
import os
import random as _random
import types

import pytest

import renpy
import renpy as _renpy

from renpy.store import Function, persistent

import cue_lib.audio.tree.music_tree as _tree
import cue_lib.audio.sfx_manager as _sfx_mod
import cue_lib.audio.tree.pool_rows as _pool_rows
import cue_lib.audio.tree.sfx_tree_rows as _sfx_rows
import cue_lib.audio.tree.tree_rows as _core_rows
import cue_lib.util as _util
from cue_lib.audio.tree.file_tree import CUE_SEARCH_MAX_ROWS, CueAudioTreeManager
from cue_lib.audio.tree.music_tree import CueMusicTree
from cue_lib.audio.sfx_manager import CueSfxManager, _cue_sfx_channel_index, _cue_sfx_channel_name
from cue_lib.audio.tree.sfx_tree import CueSfxLibraryTree
from cue_lib.preset_store import CuePresetStore
from cue_lib.constants import (
    CUE_AUDIO_EXTS,
    CUE_GAME_MUSIC_FOLDER,
    CUE_HELP_SHIFT_SKIP_DELETE,
    CUE_INTENSITY_HINT_COLOR,
    CUE_INTENSITY_NOTE,
    CUE_MY_MUSIC_FOLDER,
    CUE_PERSIST_SIDEBAR_MODE,
    CUE_PERSIST_SFX_TREE_EXPANDED,
    CUE_PERSIST_SFX_UI_STATE,
    CUE_SFX_FOLDER,
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


class _MultiSrcTree(CueAudioTreeManager):
    """Two declared built-in sources for the base multi-source scan test."""

    CUE_BUILTIN_SOURCES = (
        {"key": "a", "discover": "_discover_a", "display_root": "A/", "scan_label": "a"},
        {"key": "b", "discover": "_discover_b", "display_root": "B/", "scan_label": "b"},
    )

    def scan(self):
        self._scan_builtin_sources()
        self._scan_external()
        self._rebuild_merged()

    def _discover_a(self, results_set):
        results_set.update(["a/x.ogg", "a/y.ogg"])

    def _discover_b(self, results_set):
        results_set.update(["b/z.ogg"])


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


def test_base_multi_source_scan_fills_per_source_attrs():
    tree = _MultiSrcTree()
    tree.scan()
    assert tree.a_files == ["a/x.ogg", "a/y.ogg"]
    assert tree.a_scan_error == ""
    assert tree.b_files == ["b/z.ogg"]
    assert tree.b_scan_error == ""
    # Merged tree wraps each non-empty source under its display_root.
    assert [n["name"] for n in tree.tree] == ["A/", "B/"]
    assert tree.tree[0]["children"] == [
        {
            "type": "folder",
            "name": "a/",
            "has_files": True,
            "children": [{"type": "file", "name": "x.ogg"}, {"type": "file", "name": "y.ogg"}],
        }
    ]


def test_base_multi_source_scan_isolates_source_error(monkeypatch):
    tree = _MultiSrcTree()
    tree.CUE_BUILTIN_SOURCES = (
        {"key": "a", "discover": "_discover_boom", "display_root": "A/", "scan_label": "a"},
        {"key": "b", "discover": "_discover_b", "display_root": "B/", "scan_label": "b"},
    )

    def _boom(results_set):
        raise RuntimeError("kaput")

    setattr(tree, "_discover_boom", _boom)
    tree.scan()
    assert tree.a_files == []
    assert tree.a_tree == []
    assert "Failed to scan a: kaput" in tree.a_scan_error
    assert tree.b_files == ["b/z.ogg"]
    assert tree.b_scan_error == ""
    # The healthy source still contributes to the merged tree.
    assert [n["name"] for n in tree.tree] == ["B/"]


def test_file_node_stashes_ref_identity_default():
    tree = CueAudioTreeManager()
    node = tree._file_node({"name": "x.ogg"}, "a/x.ogg", 1)
    assert node["ref"] == "a/x.ogg"
    assert tree.display_for_ref("a/x.ogg") == "a/x.ogg"


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
    files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    # Search force-expands every folder: matches inside default-collapsed
    # subfolders all appear, and non-matches are pruned.
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
    # Search force-expands every folder: exactly the matches appear (matches
    # in collapsed folders shown, non-match branches pruned).
    assert search_files == ["v2/agrat/02_IntenseMo.mp3", "v2/anya/04_IntenseMo.mp3", "v2/nora/03_IntenseMo.mp3"]
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
# CueMusicTree scan sources
# ==========================================================================


def test_user_music_discover_prefixes(monkeypatch, tmp_path):
    music_dir = str(tmp_path / "music") + "/"
    for rel in ("song.ogg", "sub/track.mp3", "notes.txt"):
        p = os.path.join(music_dir, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    monkeypatch.setattr(_tree, "_cue", types.SimpleNamespace(paths=types.SimpleNamespace(music_dir=music_dir)))
    m = CueMusicTree(types.SimpleNamespace())
    results = set()
    m._discover_user(results)
    assert results == {"music/song.ogg", "music/sub/track.mp3"}


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
    m = CueMusicTree(types.SimpleNamespace())
    results = set()
    m._discover_game(results)
    assert results == {"music/bgm.ogg", "Bgm/Upper.OGG", "bgm/intro.mp3", "ost/track.wav", "soundtrack/t.opus"}


# ==========================================================================
# CueMusicTree scan
# ==========================================================================


def test_music_tree_scan_builds_per_source_and_merged(monkeypatch, tmp_path):
    music_dir = str(tmp_path / "music") + "/"
    for rel in ("song.ogg", "sub/track.mp3"):
        p = os.path.join(music_dir, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    monkeypatch.setattr(_tree, "_cue", types.SimpleNamespace(paths=types.SimpleNamespace(music_dir=music_dir)))
    monkeypatch.setattr(_renpy, "list_files", lambda: ["music/bgm.ogg", "sfx/shot.ogg", "images/bg.png"])
    m = _tree.CueMusicTree(types.SimpleNamespace())
    m.scan()
    assert m.user_files == ["music/song.ogg", "music/sub/track.mp3"]
    assert m.game_files == ["music/bgm.ogg"]
    assert m.user_scan_error == ""
    assert m.game_scan_error == ""
    # Merged tree has both synthetic roots (auto-expanded once), rows built.
    assert m.tree[0]["name"] == CUE_MY_MUSIC_FOLDER
    assert m.tree[1]["name"] == CUE_GAME_MUSIC_FOLDER
    assert m.expanded_folders == {CUE_MY_MUSIC_FOLDER: True, CUE_GAME_MUSIC_FOLDER: True}
    assert m.visible_tree

    # A re-scan picks up new files and rebuilds the merged rows (the old
    # object-id rescan detection in maybe_rebuild is gone; scan() is the
    # single writer and calls _rebuild_merged itself).
    open(os.path.join(music_dir, "new.ogg"), "w").close()
    monkeypatch.setattr(
        _renpy, "list_files", lambda: ["music/bgm.ogg", "sfx/shot.ogg", "images/bg.png", "ost/loop.ogg"]
    )
    m.scan()
    assert m.user_files == ["music/new.ogg", "music/song.ogg", "music/sub/track.mp3"]
    assert m.game_files == ["music/bgm.ogg", "ost/loop.ogg"]
    assert any(r["full_path"] == CUE_MY_MUSIC_FOLDER + "new.ogg" for r in m.visible_tree)
    # Game Music root stays expanded; the new ost/ sub-folder shows as a row.
    assert any(r["full_path"] == CUE_GAME_MUSIC_FOLDER + "ost/" for r in m.visible_tree)


# ==========================================================================
# CueSfxLibraryTree
# ==========================================================================


@pytest.fixture(autouse=True)
def _clean_persistent(monkeypatch):
    """Fresh persistent._cue for every test (tree toggle state writes it)."""
    monkeypatch.setattr(persistent, "_cue", {})


@pytest.fixture
def sfx(tmp_path):
    audio = str(tmp_path / "audio") + "/"
    # Library-tree tests only exercise the tree; volume/ctx/markers/presets are
    # unused.
    return CueSfxManager(
        types.SimpleNamespace(audio_dir=audio),
        FakeDb(),
        types.SimpleNamespace(),
        types.SimpleNamespace(),
        False,
        CuePresetStore(FakeDb(), None),
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


def _write_tree(root, rels):
    for rel in rels:
        p = os.path.join(root, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()


def test_sfx_scan_builds_per_source_and_merged(sfx, tmp_path):
    audio = str(tmp_path / "audio") + "/"
    _write_tree(audio, ["g1/drip.ogg", "a.ogg"])
    ext1 = str(tmp_path / "ExtA")
    _write_tree(ext1, ["x.ogg", "sub/y.mp3"])
    ext2 = str(tmp_path / "ExtB")
    _write_tree(ext2, ["w.wav"])
    sfx.external_folders = [ext1, ext2]
    sfx.scan()
    assert sfx.builtin_files == ["a.ogg", "g1/drip.ogg"]
    assert sfx.external_files == [ext1 + "/sub/y.mp3", ext1 + "/x.ogg", ext2 + "/w.wav"]
    # Flat ref list: built-in audio-relative + external bare-absolute, sorted
    # (the bisect-based folder expansion depends on the sort).
    assert sfx.files == sorted(["a.ogg", "g1/drip.ogg"] + list(sfx.external_files))
    # Merged display tree: synthetic root first, then external sources.
    assert [n["name"] for n in sfx.tree] == [CUE_SFX_FOLDER, "ExtA/", "ExtB/"]
    assert sfx.builtin_scan_error == ""
    # _file_index keys refs, so built-in AND external rows get valid indices.
    assert sfx._file_index["g1/drip.ogg"] >= 0
    assert sfx._file_index[ext1 + "/x.ogg"] >= 0


def test_sfx_scan_missing_external_folder_keeps_warning(sfx, tmp_path):
    _write_tree(str(tmp_path / "audio") + "/", ["a.ogg"])
    missing = str(tmp_path / "nope")
    sfx.external_folders = [missing]
    sfx.scan()
    assert len(sfx.external_sources) == 1
    src = sfx.external_sources[0]
    assert src["scan_error"] == "Folder not found: {}".format(missing)
    assert src["tree"] == []
    assert sfx.external_files == []
    # The missing source still appears in the merged tree (warning reachable).
    assert [n["name"] for n in sfx.tree] == [CUE_SFX_FOLDER, "nope/"]


def test_sfx_external_label_disambiguated(sfx):
    assert sfx._external_label("E:/SFX", []) == "SFX (2)"
    assert sfx._external_label("E:/Music", []) == "Music"
    assert sfx._external_label("E:/Music", ["Music"]) == "Music (2)"


def test_sfx_ref_from_display(sfx):
    sfx.external_sources = [{"label": "ExtA", "abs_root": "E:/SFX/A", "tree": [], "files": [], "scan_error": ""}]
    assert sfx.ref_from_display(CUE_SFX_FOLDER + "g1/drip.ogg") == "g1/drip.ogg"
    assert sfx.ref_from_display("ExtA/g1/drip.ogg") == "E:/SFX/A/g1/drip.ogg"
    assert sfx.ref_from_display("ExtA/g1/") == "E:/SFX/A/g1/"
    # Unknown paths (legacy / unqualified rows) pass through unchanged.
    assert sfx.ref_from_display("legacy/x.ogg") == "legacy/x.ogg"


def test_sfx_resolve_path(sfx):
    audio = sfx._paths.audio_dir
    assert sfx.resolve_path("g1/drip.ogg") == audio + "g1/drip.ogg"
    assert sfx.resolve_path("E:/SFX/A/g1/drip.ogg") == "E:/SFX/A/g1/drip.ogg"


def test_sfx_ref_round_trip(sfx, tmp_path):
    _write_tree(str(tmp_path / "audio") + "/", ["g1/drip.ogg", "a.ogg"])
    ext = str(tmp_path / "ExtA")
    _write_tree(ext, ["x.ogg"])
    sfx.external_folders = [ext]
    sfx.scan()
    # Built-in: display "SFX/..." inverts to the audio-relative ref, and back.
    assert sfx.ref_from_display(CUE_SFX_FOLDER + "g1/drip.ogg") == "g1/drip.ogg"
    assert sfx.ref_from_display(sfx.display_for_ref("g1/drip.ogg")) == "g1/drip.ogg"
    # External: the bare absolute payload round-trips through its source label.
    assert sfx.ref_from_display("ExtA/x.ogg") == ext + "/x.ogg"
    assert sfx.ref_from_display(sfx.display_for_ref(ext + "/x.ogg")) == ext + "/x.ogg"


def test_sfx_file_node_ref_index_enabled(sfx):
    sfx.external_sources = [{"label": "ExtA", "abs_root": "E:/SFX/A", "tree": [], "files": [], "scan_error": ""}]
    sfx._file_index = {"g1/drip.ogg": 2, "E:/SFX/A/x.ogg": 3}
    sfx.disabled_files = {"E:/SFX/A/x.ogg"}
    builtin = sfx._file_node({"name": "drip.ogg"}, CUE_SFX_FOLDER + "g1/drip.ogg", 1)
    assert builtin["ref"] == "g1/drip.ogg"
    assert builtin["index"] == 2
    assert builtin["enabled"] is True
    external = sfx._file_node({"name": "x.ogg"}, "ExtA/x.ogg", 1)
    assert external["ref"] == "E:/SFX/A/x.ogg"
    assert external["index"] == 3
    assert external["enabled"] is False


def test_sfx_toggle_file_enabled_external(sfx):
    ref = "E:/SFX/A/x.ogg"
    sfx.toggle_file_enabled(ref)
    assert ref in sfx.disabled_files
    assert sfx._db.saved[-1]["disabled_files"] == [ref]
    sfx.toggle_file_enabled(ref)
    assert ref not in sfx.disabled_files


def test_sfx_expand_folder_ref_sorted_files(sfx):
    ext = "E:/SFX/A"
    files = sorted(["g1/a.ogg", ext + "/g1/x.ogg", ext + "/g1/y.ogg"])
    out = _util._cue_expand_folder_ref(files, ext + "/g1/")
    assert out == [ext + "/g1/x.ogg", ext + "/g1/y.ogg"]


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


def test_sfx_toggle_presets_expand(sfx):
    sfx.toggle_presets_expand()
    assert sfx.presets_expanded is True
    sfx.toggle_presets_expand()
    assert sfx.presets_expanded is False


def _remove_ref(key, pool_index, ref_index):
    pass


def _remove_child(key, pool_index, folder_index, child):
    pass


def _fake_cue_pool_rows(monkeypatch, library, intensity=None, current_file=None):
    """Patch module-level _cue with the pieces the pool-files builder reads."""
    cue = types.SimpleNamespace(
        current_file=current_file,
        markers=types.SimpleNamespace(get=lambda key, default: default),
        sfx=types.SimpleNamespace(
            library=library, preview_sfx=lambda *a, **k: None, preview_folder=lambda *a, **k: None
        ),
        intensity=intensity,
    )
    monkeypatch.setattr(_pool_rows, "_cue", cue)
    # _cue_resolve_files (imported into _pool_rows) reads _util._cue.
    monkeypatch.setattr(_util, "_cue", cue)
    return cue


def test_pool_files_rows_regular_files(monkeypatch):
    library = types.SimpleNamespace(
        files=["pool/a.ogg", "pool/b.ogg"],
        disabled_files=set(),
        expanded_file_refs={},
        toggle_file_ref_expand=lambda *a, **k: None,
    )
    _fake_cue_pool_rows(monkeypatch, library)
    rows = _pool_rows._cue_pool_files_rows(
        ["hit.ogg", "pool/"], 0.5, None, _remove_ref, ("k", 0), _remove_child, "k", 0, None, None
    )
    # hit.ogg file row, pool/ folder row (collapsed, no children).
    assert [r["type"] for r in rows] == ["file", "folder"]
    assert rows[0]["label"] == "hit.ogg"
    assert rows[1]["label"] == "pool/"
    # File xmark wires remove_fn with the pool args + ref index.
    assert rows[0]["buttons"][0]["action"]._args[1:] == ("k", 0, 0)
    assert rows[1]["buttons"][0]["action"]._args[1:] == ("k", 0, 1)


def test_pool_files_rows_expanded_folder_ref(monkeypatch):
    library = types.SimpleNamespace(
        files=["pool/a.ogg", "pool/b.ogg"],
        disabled_files=set(),
        expanded_file_refs={"pool/": True},
        toggle_file_ref_expand=lambda *a, **k: None,
    )
    _fake_cue_pool_rows(monkeypatch, library)
    rows = _pool_rows._cue_pool_files_rows(
        ["pool/"], 0.5, None, _remove_ref, ("k", 0), _remove_child, "k", 0, None, None
    )
    # Folder row + 2 children; children strip the folder prefix, carry the
    # child-remove xmark at depth 1.
    assert [r["type"] for r in rows] == ["folder", "file", "file"]
    assert [r["label"] for r in rows[1:]] == ["a.ogg", "b.ogg"]
    assert [r["depth"] for r in rows[1:]] == [1, 1]
    assert rows[1]["buttons"][0]["action"]._args[1:] == ("k", 0, 0, "pool/a.ogg")
    assert rows[1]["size"] == 11


def test_pool_files_rows_preset_virtual(monkeypatch):
    library = types.SimpleNamespace(
        files=[],
        disabled_files=set(),
        expanded_file_refs={"Preset/": True},
        toggle_file_ref_expand=lambda *a, **k: None,
    )
    _fake_cue_pool_rows(monkeypatch, library)
    rows = _pool_rows._cue_pool_files_rows([], 0.5, "DETACH", None, (), _remove_child, "k", 0, "Preset/", ["a.ogg"])
    assert [r["type"] for r in rows] == ["folder", "file"]
    assert rows[0]["label"] == "Preset/"
    # Header xmark is the pre-built detach action (no ref index appended).
    assert rows[0]["buttons"][0]["action"] == "DETACH"
    assert rows[1]["label"] == "a.ogg"
    assert rows[1]["buttons"][0]["action"]._args[1:] == ("k", 0, 0, "a.ogg")


def test_pool_files_rows_igroup_readonly(monkeypatch):
    library = types.SimpleNamespace(
        files=["soft/a.ogg", "soft/b.ogg"],
        disabled_files=set(),
        expanded_file_refs={"soft/": True},
        toggle_file_ref_expand=lambda *a, **k: None,
    )
    flags = types.SimpleNamespace(enabled=True, sfx_levels=True)
    intensity = types.SimpleNamespace(
        level_files_by_id=lambda group, lv: ["soft/", "hit.ogg"], flags_from_entry=lambda entry: flags
    )
    _fake_cue_pool_rows(monkeypatch, library, intensity=intensity)
    rows = _pool_rows._cue_pool_files_rows(
        [], 0.5, "DETACH", None, (), None, None, None, None, None, igroup="Impacts", ilevel_id=1
    )
    assert [r["type"] for r in rows] == ["folder", "file", "file", "file"]
    # Folder row: detach xmark + hint bar; children are play-only.
    assert rows[0]["buttons"][0]["action"] == "DETACH"
    assert rows[0]["bar_color"] == CUE_INTENSITY_HINT_COLOR
    assert CUE_INTENSITY_NOTE in rows[0]["tt"]
    assert [b["icon"] for b in rows[1]["buttons"]] == ["play"]


def test_pool_files_rows_igroup_no_files(monkeypatch):
    library = types.SimpleNamespace(
        files=[], disabled_files=set(), expanded_file_refs={}, toggle_file_ref_expand=lambda *a, **k: None
    )
    intensity = types.SimpleNamespace(
        level_files_by_id=lambda group, lv: [],
        flags_from_entry=lambda entry: types.SimpleNamespace(enabled=False, sfx_levels=False),
    )
    _fake_cue_pool_rows(monkeypatch, library, intensity=intensity)
    rows = _pool_rows._cue_pool_files_rows([], 0.5, None, None, (), None, None, None, None, None, igroup="Impacts")
    assert rows == []


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
        _presets=types.SimpleNamespace(get=lambda g: {"levels": [{"id": 1}, {"id": 2}]}),
        add_level_file=lambda g, lid, ref: calls.append((g, lid, ref)),
    )
    sfx.ilevel_add_file("Impacts", 2, "soft/a.ogg")
    assert calls == [("Impacts", 2, "soft/a.ogg")]


def test_sfx_ilevel_add_folder_normalizes_ref(sfx):
    calls = []
    sfx._intensity = types.SimpleNamespace(
        _presets=types.SimpleNamespace(get=lambda g: {"levels": [{"id": 1}]}),
        add_level_file=lambda g, lid, ref: calls.append((g, lid, ref)),
    )
    sfx.ilevel_add_folder("Impacts", 1, "soft")
    assert calls == [("Impacts", 1, "soft/")]


def test_sfx_ilevel_add_clears_stale_group_target(sfx):
    # Deleting the active add-target group leaves a stale target; the next
    # add clears it instead of failing against a deleted group.
    sfx._intensity = types.SimpleNamespace(_presets=types.SimpleNamespace(get=lambda g: None))
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
        types.SimpleNamespace(audio_dir=""),
        FakeDb(),
        types.SimpleNamespace(),
        types.SimpleNamespace(),
        False,
        CuePresetStore(FakeDb(), None),
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
    # Files under the expanded roots are visible; the collapsed subfolder's
    # file (music/sub/b.mp3) stays hidden.
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


# ==========================================================================
# tree_rows builders
# ==========================================================================


def _base_rows(tree):
    # type: (CueAudioTreeManager) -> list
    """Row stream via the shared CueTreeRowsBuilder over a data tree."""
    return _core_rows.CueTreeRowsBuilder(tree).tree_rows()


def test_tree_rows_folder_and_file_shape():
    tree = _ScanSrc(["v2/01_NormalMo.mp3", "v2/02_IntenseMo.mp3"])
    tree.scan()
    tree.expanded_folders["v2/"] = True
    tree.rebuild_tree()
    rows = _base_rows(tree)
    assert [r["type"] for r in rows] == ["folder", "file", "file"]
    folder = rows[0]
    assert folder["key"] == "tree:v2/"
    assert folder["label"] == "v2/"
    assert folder["depth"] == 0
    assert folder["buttons"] == []  # base row_buttons default
    # toggle wraps the data tree's toggle_folder(full_path)
    assert folder["toggle"]._args[1] == "v2/"
    f = rows[1]
    assert f["key"] == "tree:v2/01_NormalMo.mp3"
    assert f["depth"] == 1
    assert f["gap"] == 1
    assert f["warn"] == ""
    assert f["buttons"] == []


def test_tree_rows_visible_tree_collapsed_emits_only_folder():
    tree = _ScanSrc(["v2/01_NormalMo.mp3"])
    tree.scan()  # nothing expanded -> only the top-level folder
    rows = _base_rows(tree)
    assert [r["type"] for r in rows] == ["folder"]


def test_tree_rows_ignores_search_state():
    # tree_rows is a pure reader of visible_tree (which already reflects a
    # search via rebuild_tree): it must not touch search or expand state.
    tree = _ScanSrc(["v2/01_NormalMo.mp3"])
    tree.scan()
    tree.expanded_folders["v2/"] = True
    tree.rebuild_tree()
    tree.search_query = "norm"
    before_folders = dict(tree.expanded_folders)
    rows = _base_rows(tree)
    assert [r["type"] for r in rows] == ["folder", "file"]
    assert tree.search_query == "norm"
    assert tree.expanded_folders == before_folders


# ==========================================================================
# SFX row buttons + warn reason
# ==========================================================================


def _sfx_tree_rows(sfx, target_ok=True, target_tt="Add to pool", unplayable=None):
    # type: (CueSfxLibraryTree, bool, str, object) -> list
    """Row stream for a two-row SFX tree (folder + file) with default state."""
    sfx.visible_tree = [
        {"type": "folder", "name": "v2/", "full_path": "v2/", "depth": 0, "has_files": True},
        {"type": "file", "name": "a.wav", "full_path": "v2/a.wav", "depth": 1, "index": 0},
    ]
    return sfx.tree_rows(target_ok, target_tt, unplayable or {})


def test_sfx_row_buttons_normal_mode(sfx):
    folder, file_row = _sfx_tree_rows(sfx)
    assert [b["icon"] for b in folder["buttons"]] == ["play", "plus"]
    assert folder["buttons"][0]["tt"] == "Play random file from folder"
    assert folder["buttons"][0]["action"]._args[0] == sfx._sfx.preview_folder
    assert folder["buttons"][1]["tt"] == "Add to pool"
    assert folder["buttons"][1]["enabled"] is True
    assert folder["buttons"][1]["action"]._args[0] is _sfx_rows._cue_markers_send
    assert folder["buttons"][1]["action"]._args[1] == "folder"
    assert folder["buttons"][1]["action"]._args[2] == "v2/"
    assert [b["icon"] for b in file_row["buttons"]] == ["play", "plus"]
    assert file_row["buttons"][0]["tt"] == "Preview audio"
    assert file_row["buttons"][0]["action"]._args[0] == sfx._sfx.preview_sfx
    assert file_row["buttons"][1]["action"]._args[1] == "file"
    assert file_row["buttons"][1]["action"]._args[2] == 0  # file index
    assert file_row["gap"] == 1
    assert file_row["warn"] == ""


def test_sfx_row_buttons_disabled_when_target_unavailable(sfx):
    folder, file_row = _sfx_tree_rows(sfx, target_ok=False)
    assert folder["buttons"][1]["enabled"] is False
    assert file_row["buttons"][1]["enabled"] is False


def test_sfx_row_buttons_add_mode(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#446688", raising=False)
    sfx.ilevel_add_target = ("g", 1)
    folder, file_row = _sfx_tree_rows(sfx)
    fplus = folder["buttons"][1]
    assert fplus["tt"] == "Add this folder to Level 1 of g."
    assert fplus["enabled"] is True
    assert fplus["bg"] == "#446688"
    assert fplus["action"]._args[0] == sfx.ilevel_add_folder
    assert fplus["action"]._args[1:3] == ("g", 1)
    fplus2 = file_row["buttons"][1]
    assert fplus2["tt"] == "Add this file to Level 1 of g."
    assert fplus2["action"]._args[0] == sfx.ilevel_add_file
    assert fplus2["action"]._args[1:3] == ("g", 1)


def test_sfx_row_buttons_add_mode_dup_gates(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#446688", raising=False)
    sfx.ilevel_add_target = ("g", 1)
    sfx.level_has_file = lambda g, lv, ref: True  # shadow: simulate dup
    _folder, file_row = _sfx_tree_rows(sfx)
    plus = file_row["buttons"][1]
    assert plus["enabled"] is False
    assert plus["bg"] is None


def test_sfx_folder_without_files_has_only_plus(sfx):
    # The whole folder button block (play + add) is gated on has_files, so an
    # empty folder shows no buttons -- exactly like the current screen.
    sfx.visible_tree = [{"type": "folder", "name": "empty/", "full_path": "empty/", "depth": 0, "has_files": False}]
    rows = sfx.tree_rows(False, "tt", {})
    assert rows[0]["buttons"] == []


def test_sfx_row_buttons_use_refs(sfx):
    sfx.external_sources = [{"label": "ExtA", "abs_root": "E:/SFX/A", "tree": [], "files": [], "scan_error": ""}]
    sfx.visible_tree = [
        {"type": "folder", "name": "ExtA/", "full_path": "ExtA/", "depth": 0, "has_files": True},
        {"type": "file", "name": "drip.ogg", "full_path": CUE_SFX_FOLDER + "g1/drip.ogg", "depth": 1, "index": 0},
    ]
    rows = sfx.tree_rows(True, "tt", {})
    ext_folder, builtin_file = rows
    # External folder play + add dispatch the bare-absolute ref, not the
    # display path.
    assert ext_folder["buttons"][0]["action"]._args[1] == "E:/SFX/A/"
    assert ext_folder["buttons"][1]["action"]._args[2] == "E:/SFX/A/"
    # Built-in file preview strips the synthetic wrapper back to the ref.
    assert builtin_file["buttons"][0]["action"]._args[1] == "g1/drip.ogg"


def test_sfx_row_buttons_external_add_mode(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#446688", raising=False)
    sfx.external_sources = [{"label": "ExtA", "abs_root": "E:/SFX/A", "tree": [], "files": [], "scan_error": ""}]
    sfx.ilevel_add_target = ("g", 1)
    sfx.visible_tree = [{"type": "folder", "name": "ExtA/", "full_path": "ExtA/", "depth": 0, "has_files": True}]
    rows = sfx.tree_rows(True, "tt", {})
    fplus = rows[0]["buttons"][1]
    assert fplus["action"]._args[0] == sfx.ilevel_add_folder
    assert fplus["action"]._args[3] == "E:/SFX/A/"


def test_sfx_warn_reason_external(sfx):
    sfx.external_sources = [{"label": "ExtA", "abs_root": "E:/SFX/A", "tree": [], "files": [], "scan_error": ""}]
    sfx.visible_tree = [{"type": "file", "name": "bad.wav", "full_path": "ExtA/bad.wav", "depth": 1, "index": 0}]
    rows = sfx.tree_rows(True, "tt", {"E:/SFX/A/bad.wav": "unsupported format"})
    assert rows[0]["warn"] == "unsupported format"


def test_sfx_warn_reason(sfx):
    audio = sfx._paths.audio_dir
    sfx.visible_tree = [
        {"type": "file", "name": "bad.wav", "full_path": "bad.wav", "depth": 0, "index": 0},
        {"type": "file", "name": "ok.wav", "full_path": "ok.wav", "depth": 0, "index": 1},
    ]
    rows = sfx.tree_rows(True, "tt", {audio + "bad.wav": "unsupported format"})
    assert rows[0]["warn"] == "unsupported format"
    assert rows[1]["warn"] == ""


# ==========================================================================
# Shared row helpers (section / folder / file / help)
# ==========================================================================


def test_section_rows_hidden_during_search_without_match():
    rows = _core_rows._cue_section_rows("s", "Recently Used/", lambda: None, False, True, lambda: False, lambda: [1])
    assert rows == []


def test_section_rows_header_only_when_collapsed():
    toggle = Function("toggle")
    rows = _core_rows._cue_section_rows("s", "Recently Used/", toggle, False, False, lambda: True, lambda: [1])
    assert len(rows) == 1
    header = rows[0]
    assert header["type"] == "folder"
    assert header["label"] == "Recently Used/"
    assert header["depth"] == 0
    assert header["buttons"] == []
    assert header["toggle"] == toggle


def test_section_rows_children_when_expanded():
    rows = _core_rows._cue_section_rows("s", "Recently Used/", lambda: None, True, False, lambda: True, lambda: [1, 2])
    assert len(rows) == 3
    assert rows[0]["type"] == "folder"
    assert rows[1:] == [1, 2]


def test_section_rows_auto_show_children_on_search():
    rows = _core_rows._cue_section_rows("s", "Pool Presets/", lambda: None, False, True, lambda: True, lambda: [1])
    assert len(rows) == 2


def test_section_rows_auto_show_disabled():
    rows = _core_rows._cue_section_rows(
        "s", "Video Presets/", lambda: None, False, True, lambda: True, lambda: [1], auto_show=False
    )
    assert len(rows) == 1


def test_folder_rows_open_and_closed():
    toggle = Function("toggle")
    buttons = [{"icon": "xmark"}]
    children = [1, 2]
    rows = _core_rows._cue_folder_rows("p", "p", 1, toggle, True, False, buttons, children)
    assert len(rows) == 3
    assert rows[0]["type"] == "folder"
    assert rows[0]["depth"] == 1
    assert rows[0]["buttons"] == buttons
    assert rows[0]["toggle"] == toggle
    assert rows[1:] == children
    closed = _core_rows._cue_folder_rows("p", "p", 1, toggle, False, False, buttons, children)
    assert closed == [rows[0]]


def test_folder_rows_auto_show_children_on_search():
    rows = _core_rows._cue_folder_rows("p", "p", 1, lambda: None, False, True, [], [1])
    assert len(rows) == 2


def test_file_row_shape():
    row = _core_rows._cue_file_row("k", "a.wav", 1, [{"icon": "play"}], warn="bad", gap=2, size=11)
    assert row["type"] == "file"
    assert row["key"] == "k"
    assert row["label"] == "a.wav"
    assert row["depth"] == 1
    assert row["warn"] == "bad"
    assert row["gap"] == 2
    assert row["size"] == 11


def test_file_row_defaults():
    row = _core_rows._cue_file_row("k", "a.wav", 1, [])
    assert row["warn"] == ""
    assert row["gap"] == 1
    assert "size" not in row


def test_help_row_shape():
    row = _core_rows._cue_help_row("e", "Nothing here.")
    assert row["type"] == "help"
    assert row["depth"] == 0
    assert "color" not in row
    assert "v_gap" not in row


def test_help_row_color_and_v_gap():
    row = _core_rows._cue_help_row("e", "Nothing here.", color="#f00", v_gap=2)
    assert row["color"] == "#f00"
    assert row["v_gap"] == 2


# ==========================================================================
# SFX recently-used + preset rows
# ==========================================================================


def _recent_rows(sfx, entries, target_ok=True, target_tt="Add to pool"):
    # type: (CueSfxLibraryTree, list, bool, str) -> list
    """Recently-Used row stream via the SFX builder."""
    return _sfx_rows.CueSfxTreeRows(sfx)._recent_rows(entries, target_ok, target_tt)


def test_sfx_recent_rows_empty(sfx):
    rows = _recent_rows(sfx, [])
    assert len(rows) == 1
    assert rows[0]["type"] == "help"
    assert rows[0]["label"] == "Files you add to pools show up here."
    assert rows[0]["depth"] == 0


def test_sfx_recent_rows_file(sfx):
    sfx._file_index = {"a.wav": 2}
    rows = _recent_rows(sfx, [{"type": "file", "ref": "a.wav"}])
    row = rows[0]
    assert row["type"] == "file"
    assert row["label"] == "a.wav"
    assert row["depth"] == 1
    assert row["gap"] == 1
    assert "size" not in row
    assert [b["icon"] for b in row["buttons"]] == ["play", "plus"]
    assert "tt" not in row["buttons"][0]  # recent file play has no tooltip
    assert row["buttons"][0]["action"]._args[0] == sfx._sfx.preview_sfx
    plus = row["buttons"][1]
    assert plus["action"]._args[0] is _sfx_rows._cue_markers_send
    assert plus["action"]._args[1] == "file"
    assert plus["action"]._args[2] == 2
    assert plus["action"]._args[3] is False
    assert plus["tt"] == "Add to pool"
    assert plus["enabled"] is True


def test_sfx_recent_rows_file_plus_disabled_when_unindexed(sfx):
    sfx._file_index = {}
    row = _recent_rows(sfx, [{"type": "file", "ref": "a.wav"}])[0]
    assert row["buttons"][1]["enabled"] is False


def test_sfx_recent_rows_file_plus_disabled_without_target(sfx):
    sfx._file_index = {"a.wav": 0}
    row = _recent_rows(sfx, [{"type": "file", "ref": "a.wav"}], target_ok=False)[0]
    assert row["buttons"][1]["enabled"] is False


def test_sfx_recent_rows_folder(sfx):
    row = _recent_rows(sfx, [{"type": "folder", "ref": "v2/"}])[0]
    assert row["buttons"][0]["tt"] == "Play random file from folder"
    assert row["buttons"][0]["action"]._args[0] == sfx._sfx.preview_folder
    plus = row["buttons"][1]
    assert plus["action"]._args[1] == "folder"
    assert plus["action"]._args[2] == "v2/"
    assert plus["action"]._args[3] is False
    assert plus["enabled"] is True


def test_sfx_recent_rows_preset(sfx):
    row = _recent_rows(sfx, [{"type": "preset", "ref": "p"}])[0]
    assert row["buttons"][0]["tt"] == "Play random file from preset"
    assert row["buttons"][0]["action"]._args[0] == sfx._sfx.preview_preset
    assert row["buttons"][1]["action"]._args[1] == "preset"
    assert row["buttons"][1]["action"]._args[2] == "p"
    assert row["buttons"][1]["action"]._args[3] is False


def _preset_rows(sfx, names, query="", target_ok=True, target_tt="Add to pool"):
    # type: (CueSfxLibraryTree, list, str, bool, str) -> list
    """Pool Preset row stream via the SFX builder, with presets stubs."""
    import cue_lib.util as util_mod

    util_mod._cue.presets = types.SimpleNamespace(
        audio=types.SimpleNamespace(get=lambda n: {"files": ["a.ogg", "b.ogg"]}, preset_remove_file=lambda n, f: None)
    )
    util_mod._cue.sfx = types.SimpleNamespace(library=None)
    return _sfx_rows.CueSfxTreeRows(sfx)._preset_rows(names, query, target_ok, target_tt)


def test_sfx_preset_rows_expanded(sfx):
    sfx.expanded_presets = {"p": True}
    rows = _preset_rows(sfx, ["p"])
    folder = rows[0]
    assert folder["type"] == "folder"
    assert folder["label"] == "p"
    assert folder["depth"] == 1
    assert [b["icon"] for b in folder["buttons"]] == ["xmark", "play", "plus"]
    assert folder["buttons"][0]["action"]._args[0] is _sfx_rows._cue_confirm_delete_preset
    assert folder["buttons"][0]["tt"] == "Delete preset" + CUE_HELP_SHIFT_SKIP_DELETE
    assert folder["buttons"][1]["action"]._args[0] == sfx._sfx.preview_preset
    assert folder["buttons"][2]["action"]._args[1] == "preset"
    assert folder["buttons"][2]["action"]._args[2] == "p"
    assert folder["toggle"]._args[0] == sfx.toggle_preset_expand
    assert folder["toggle"]._args[1] == "p"
    children = rows[1:]
    assert [c["label"] for c in children] == ["a.ogg", "b.ogg"]
    assert children[0]["depth"] == 2
    assert children[0]["size"] == 11
    assert children[0]["gap"] == 1
    assert [b["icon"] for b in children[0]["buttons"]] == ["xmark", "play"]
    assert children[0]["buttons"][0]["action"]._args[0] == _sfx_rows._cue.presets.audio.preset_remove_file
    assert children[0]["buttons"][0]["action"]._args[1:3] == ("p", "a.ogg")
    assert children[0]["buttons"][1]["action"]._args[0] == sfx._sfx.preview_sfx


def test_sfx_preset_rows_collapsed_no_children(sfx):
    sfx.expanded_presets = {}
    rows = _preset_rows(sfx, ["p"])
    assert len(rows) == 1
    assert rows[0]["type"] == "folder"


def test_sfx_preset_rows_auto_show_children_on_search(sfx):
    # A content-matched preset reveals its matching files without a click.
    sfx.expanded_presets = {}
    rows = _preset_rows(sfx, ["p"], query="a")
    assert len(rows) == 2
    assert rows[1]["type"] == "file"
    assert rows[1]["label"] == "a.ogg"


def _video_preset_rows(sfx, names, is_video=True):
    # type: (CueSfxLibraryTree, list, bool) -> list
    """Video Preset row stream via the SFX builder, with presets stubs."""
    import cue_lib.util as util_mod

    util_mod._cue.presets = types.SimpleNamespace(
        video=types.SimpleNamespace(
            get=lambda n: {"pools": [{"time": 1.5, "files": ["a.ogg", "b.ogg"]}]},
            remove_video_preset_pool_file=lambda n, i, f: None,
        )
    )
    util_mod._cue.sfx = types.SimpleNamespace(library=None)
    return _sfx_rows.CueSfxTreeRows(sfx)._video_preset_rows(names, is_video)


def test_sfx_video_preset_rows_expanded(sfx):
    sfx.expanded_video_presets = {"vp": True}
    sfx.expanded_video_pools = {"vp": {0: True}}
    rows = _video_preset_rows(sfx, ["vp"])
    folder = rows[0]
    assert folder["type"] == "folder"
    assert folder["label"] == "vp"
    assert folder["depth"] == 1
    assert [b["icon"] for b in folder["buttons"]] == ["xmark", "v"]
    assert folder["buttons"][0]["action"]._args[0] is _sfx_rows._cue_confirm_delete_video_preset
    assert folder["buttons"][0]["tt"] == "Delete video preset" + CUE_HELP_SHIFT_SKIP_DELETE
    assert folder["buttons"][1]["action"]._args[0] is _sfx_rows._cue_maybe_apply_video_preset
    assert folder["buttons"][1]["enabled"] is True
    assert folder["toggle"]._args[0] == sfx.toggle_video_preset_expand
    pool = rows[1]
    assert pool["type"] == "folder"
    assert pool["label"] == "00:01.50"
    assert pool["depth"] == 2
    assert [b["icon"] for b in pool["buttons"]] == ["xmark", "play"]
    assert pool["buttons"][0]["action"]._args[0] is _sfx_rows._cue_confirm_remove_video_preset_pool
    assert pool["buttons"][0]["action"]._args[1:3] == ("vp", 0)
    assert pool["buttons"][1]["action"]._args[0] == sfx._sfx.preview_video_pool
    assert pool["buttons"][1]["action"]._args[1:3] == ("vp", 0)
    assert pool["toggle"]._args[0] == sfx.toggle_video_pool_expand
    assert pool["toggle"]._args[1:3] == ("vp", 0)
    file_rows = rows[2:]
    assert [r["label"] for r in file_rows] == ["a.ogg", "b.ogg"]
    assert file_rows[0]["depth"] == 3
    assert file_rows[0]["size"] == 11
    assert file_rows[0]["gap"] == 1
    assert [b["icon"] for b in file_rows[0]["buttons"]] == ["xmark", "play"]
    assert file_rows[0]["buttons"][0]["action"]._args[0] == _sfx_rows._cue.presets.video.remove_video_preset_pool_file
    assert file_rows[0]["buttons"][0]["action"]._args[1:4] == ("vp", 0, "a.ogg")
    assert file_rows[0]["buttons"][1]["action"]._args[0] == sfx._sfx.preview_sfx


def test_sfx_video_preset_rows_apply_disabled_without_video(sfx):
    sfx.expanded_video_presets = {"vp": True}
    rows = _video_preset_rows(sfx, ["vp"], is_video=False)
    assert rows[0]["buttons"][1]["enabled"] is False


def test_sfx_video_preset_rows_collapsed_no_pools(sfx):
    sfx.expanded_video_presets = {}
    rows = _video_preset_rows(sfx, ["vp"])
    assert len(rows) == 1
    assert rows[0]["type"] == "folder"


def test_sfx_video_preset_rows_pool_collapsed_no_files(sfx):
    sfx.expanded_video_presets = {"vp": True}
    sfx.expanded_video_pools = {"vp": {0: False}}
    rows = _video_preset_rows(sfx, ["vp"])
    assert len(rows) == 2  # preset folder + pool row, no file rows


def _sfx_intensity_rows(sfx, names, query="", lv_hook_ok=True, lv_tt="Hook to pool"):
    # type: (CueSfxLibraryTree, list, str, bool, str) -> list
    """Intensity row stream via the SFX builder, with manager/dialog stubs."""
    sfx._intensity = types.SimpleNamespace(
        remove_level=lambda n, i: None, remove_level_file=lambda n, i, f: None, move_level=lambda n, i, d: None
    )
    import cue_lib.util as util_mod

    util_mod._cue.presets = types.SimpleNamespace(
        intensity=types.SimpleNamespace(get=lambda n: {"levels": [{"id": 1, "files": ["a.ogg", "pool/"]}]})
    )
    util_mod._cue.sfx = types.SimpleNamespace(library=types.SimpleNamespace(files=["pool/a.ogg"], disabled_files=set()))
    util_mod._cue.dialogs = types.SimpleNamespace(intensity=types.SimpleNamespace(open=lambda: None))
    return _sfx_rows.CueSfxTreeRows(sfx)._intensity_rows(names, query, lv_hook_ok, lv_tt)


def test_sfx_intensity_rows_empty(sfx):
    rows = _sfx_intensity_rows(sfx, [])
    assert len(rows) == 3
    plus_group = rows[0]
    assert plus_group["type"] == "action"
    assert plus_group["label"] == "+ Group"
    assert plus_group["depth"] == 1
    assert plus_group["action"] is _sfx_rows._cue.dialogs.intensity.open
    assert plus_group["tt"] == "Create a new intensity group."
    assert rows[1]["type"] == "help"
    assert rows[1]["depth"] == 0
    assert rows[1]["label"] == "No intensity groups yet."
    assert rows[2]["label"].startswith("An intensity group is a soft-to-hard")


def test_sfx_intensity_rows_empty_state_matches_parent_indent(sfx):
    # An empty state indents to its parent row: "No levels yet" under a group
    # (depth 1), "Click the folder icon" under a level (depth 2).
    import cue_lib.util as util_mod

    util_mod._cue.presets = types.SimpleNamespace(
        intensity=types.SimpleNamespace(
            get=lambda n: {"levels": []} if n == "a" else {"levels": [{"id": 1, "files": []}]}
        )
    )
    util_mod._cue.sfx = types.SimpleNamespace(library=types.SimpleNamespace(files=[], disabled_files=set()))
    util_mod._cue.dialogs = types.SimpleNamespace(intensity=types.SimpleNamespace(open=lambda: None))
    sfx._intensity = types.SimpleNamespace(
        remove_level=lambda n, i: None, remove_level_file=lambda n, i, f: None, move_level=lambda n, i, d: None
    )
    sfx.expanded_igroups = {"a": True, "b": True}
    sfx.expanded_ilevels = {"b": {1}}
    rows = _sfx_rows.CueSfxTreeRows(sfx)._intensity_rows(["a", "b"], "", True, "Hook to pool")
    nolevels = next(r for r in rows if r["label"] == "No levels yet. Click + Level to add one.")
    levelempty = next(r for r in rows if r["label"] == "Click the folder icon to add files")
    assert nolevels["depth"] == 1
    assert levelempty["depth"] == 2


def test_sfx_intensity_rows_group_and_level(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#sa", raising=False)
    monkeypatch.setattr(renpy.store, "_cue_color_bg_dialog", "#bd", raising=False)
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    rows = _sfx_intensity_rows(sfx, ["g"])
    assert rows[0]["label"] == "+ Group"
    group = rows[1]
    assert group["type"] == "folder"
    assert group["label"] == "g"
    assert group["depth"] == 1
    assert [b["icon"] for b in group["buttons"]] == ["xmark"]
    assert group["buttons"][0]["action"]._args[0] is _sfx_rows._cue_confirm_delete_igroup
    assert group["toggle"]._args[0] == sfx.toggle_igroup_expand
    add_level = rows[2]
    assert add_level["type"] == "action"
    assert add_level["label"] == "+ Level"
    assert add_level["depth"] == 2
    assert add_level["action"]._args[0] == sfx.add_level
    level = rows[3]
    assert level["type"] == "folder"
    assert level["label"] == "Level 1/"
    assert level["depth"] == 2
    assert [b["icon"] for b in level["buttons"]] == ["xmark", "play", "folder-plus", "plus"]
    assert level["buttons"][0]["action"]._args[0] == sfx._intensity.remove_level
    assert level["buttons"][0]["action"]._args[1:3] == ("g", 0)
    assert level["buttons"][1]["action"]._args[0] == sfx._sfx.preview_level
    assert level["buttons"][1]["action"]._args[1:3] == ("g", 1)
    assert level["buttons"][2]["action"]._args[0] == sfx.toggle_ilevel_add_mode
    assert level["buttons"][3]["action"]._args[0] is _sfx_rows._cue_send_level_to_target
    assert level["buttons"][3]["tt"] == "Hook to pool"
    assert level["buttons"][3]["enabled"] is True
    assert level["toggle"]._args[0] == sfx.toggle_ilevel_expand
    assert level["toggle"]._args[1:3] == ("g", 1)
    assert [hb["icon"] for hb in level["hover_buttons"]] == ["chevron-up", "chevron-down"]
    file_row = rows[4]
    assert file_row["type"] == "file"
    assert file_row["label"] == "a.ogg"
    assert file_row["depth"] == 3
    assert file_row["size"] == 11
    pool_folder = rows[5]
    assert pool_folder["type"] == "folder"
    assert pool_folder["label"] == "pool/"
    assert pool_folder["depth"] == 3
    assert [b["icon"] for b in pool_folder["buttons"]] == ["xmark", "play"]


def test_sfx_intensity_rows_chevron_bg_edges(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_bg_dialog", "#bd", raising=False)
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    rows = _sfx_intensity_rows(sfx, ["g"])
    level = rows[3]
    assert level["hover_buttons"][0]["bg"] == "#bd"  # idx 0 == first
    assert level["hover_buttons"][1]["bg"] == "#bd"  # idx 0 == last


def test_sfx_intensity_rows_search_hides_edit_buttons(sfx):
    sfx.expanded_igroups = {}
    rows = _sfx_intensity_rows(sfx, ["g"], query="a")
    assert rows[0]["label"] == "+ Group"
    group = rows[1]
    assert group["type"] == "folder"
    level = rows[2]
    assert level["type"] == "folder"
    assert [b["icon"] for b in level["buttons"]] == ["play", "folder-plus", "plus"]  # no xmark
    assert "hover_buttons" not in level  # no chevrons while searching
    assert rows[3]["label"] == "a.ogg"  # content match auto-shown


def test_sfx_intensity_rows_add_mode(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#sa", raising=False)
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    sfx.ilevel_add_target = ("g", 1)
    rows = _sfx_intensity_rows(sfx, ["g"])
    folder_btn = rows[3]["buttons"][2]
    assert folder_btn["icon"] == "folder-open"
    assert folder_btn["tt"] == "Click again to stop adding files"
    assert folder_btn["bg"] == "#sa"


def test_sfx_intensity_rows_level_hook_disabled(sfx):
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    rows = _sfx_intensity_rows(sfx, ["g"], lv_hook_ok=False)
    assert rows[3]["buttons"][3]["enabled"] is False


def test_sfx_intensity_rows_folder_ref_children(sfx):
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    sfx.expanded_file_refs = {"pool/": True}
    rows = _sfx_intensity_rows(sfx, ["g"])
    pool_folder = rows[5]
    assert pool_folder["toggle"]._args[0] == sfx.toggle_file_ref_expand
    pool_child = rows[6]
    assert pool_child["label"] == "a.ogg"
    assert [b["icon"] for b in pool_child["buttons"]] == ["play"]
    assert pool_child["buttons"][0]["action"]._args[0] == sfx._sfx.preview_sfx


# --------------------------------------------------------------------------
# SFX content_rows: full section stream (recent + presets + intensity + tree)
# --------------------------------------------------------------------------


def _content_rows(
    sfx,
    query="",
    presets=(),
    vpresets=(),
    igroups=(),
    is_video=True,
    tgt_ok=True,
    unplayable=None,
    recent_entries=(),
    recent_expanded=False,
    ctx="video",
):
    # type: (CueSfxLibraryTree, str, tuple, tuple, tuple, bool, bool, dict, tuple, bool, str) -> list
    """Full SFX section stream via the builder.  recent_entries None wires no
    recent manager; otherwise the fake returns the given (type, ref) pairs."""
    import cue_lib.util as util_mod

    if recent_entries is None:
        sfx._recent = None
    else:
        sfx._recent = types.SimpleNamespace(
            expanded=recent_expanded,
            entries=lambda: [{"type": t, "ref": r} for t, r in recent_entries],
            toggle=lambda: None,
        )
    util_mod._cue.presets = types.SimpleNamespace(
        audio=types.SimpleNamespace(get=lambda n: {"files": ["a.ogg", "b.ogg"]}, preset_remove_file=lambda n, f: None),
        video=types.SimpleNamespace(
            get=lambda n: {"pools": [{"time": 1.5, "files": ["a.ogg", "b.ogg"]}]},
            remove_video_preset_pool_file=lambda n, i, f: None,
        ),
    )
    sfx._intensity = types.SimpleNamespace(
        remove_level=lambda n, i: None, remove_level_file=lambda n, i, f: None, move_level=lambda n, i, d: None
    )
    util_mod._cue.markers = types.SimpleNamespace(
        resolve_target_context=lambda: ctx,
        target_is_available=lambda c: tgt_ok,
        video=types.SimpleNamespace(has_pools=lambda: True),
        loop=types.SimpleNamespace(has_pools=lambda: True),
        image=types.SimpleNamespace(has_pools=lambda: True),
        dialogue=types.SimpleNamespace(has_pools=lambda: True),
    )
    util_mod._cue.presets.intensity = types.SimpleNamespace(
        get=lambda n: {"levels": [{"id": 1, "files": ["a.ogg", "pool/"]}]}
    )
    util_mod._cue.sfx = types.SimpleNamespace(library=types.SimpleNamespace(files=["pool/a.ogg"], disabled_files=set()))
    util_mod._cue.dialogs = types.SimpleNamespace(intensity=types.SimpleNamespace(open=lambda: None))
    return _sfx_rows.CueSfxTreeRows(sfx).content_rows(
        query, list(presets), list(vpresets), list(igroups), is_video, tgt_ok, unplayable or {}
    )


def _all_action_buttons(rows):
    """Flatten action buttons, including those nested in 'actions' rows."""
    out = []
    for r in rows:
        if r["type"] == "actions":
            out.extend(r["actions"])
        elif r["type"] == "action":
            out.append(r)
    return out


def _find_button(rows, key):
    """Find an action button by key, whether flat or nested in an actions row."""
    for b in _all_action_buttons(rows):
        if b["key"] == key:
            return b
    return None


def _row_labels(rows):
    """Row labels; rows without a label (e.g. the actions row) are skipped."""
    return [r["label"] for r in rows if "label" in r]


def _seed_builtin(sfx):
    # Populate the built-in source so the per-source empty rows don't render --
    # content_rows only shows them when another source has content (the merged
    # tree is non-empty), which these section tests don't exercise.
    sfx.builtin_tree = [{"type": "folder", "name": "seed/", "children": [], "has_files": False}]


def test_sfx_content_rows_section_headers_collapsed(sfx):
    _seed_builtin(sfx)
    rows = _content_rows(sfx, presets=["p"], vpresets=["vp"], igroups=["g"])
    # Four collapsed section headers; sections with content keep their header,
    # and no children render while collapsed.
    labels = [r["label"] for r in rows]
    assert labels == ["Recently Used/", "Pool Presets/", "Video Presets/", "Intensity Groups/"]
    assert all(r["type"] == "folder" for r in rows)
    assert all(r["depth"] == 0 for r in rows)


def test_sfx_content_rows_recent_children_when_expanded(sfx):
    _seed_builtin(sfx)
    rows = _content_rows(sfx, recent_entries=[("file", "a.wav"), ("folder", "v2/")], recent_expanded=True)
    assert rows[0]["label"] == "Recently Used/"
    assert rows[0]["toggle"]._args[0] == sfx._recent.toggle
    file_row, folder_row = rows[1], rows[2]
    assert file_row["type"] == "file"
    assert file_row["label"] == "a.wav"
    assert file_row["depth"] == 1
    assert folder_row["label"] == "v2/"
    # plus buttons forward the resolved target tooltip
    assert file_row["buttons"][1]["tt"] == "Click: Add to Video active pool\nShift+Click: Create new Video pool and add"


def test_sfx_content_rows_no_recent_section_when_unwired(sfx):
    _seed_builtin(sfx)
    rows = _content_rows(sfx, recent_entries=None, presets=["p"])
    assert rows[0]["label"] == "Pool Presets/"
    assert "Recently Used/" not in [r["label"] for r in rows]


def test_sfx_content_rows_preset_children_expanded(sfx):
    _seed_builtin(sfx)
    sfx.presets_expanded = True
    sfx.expanded_presets = {"p": True}
    rows = _content_rows(sfx, presets=["p"])
    labels = [r["label"] for r in rows]
    assert labels == ["Recently Used/", "Pool Presets/", "p", "a.ogg", "b.ogg", "Video Presets/", "Intensity Groups/"]


def test_sfx_content_rows_preset_empty_help(sfx):
    _seed_builtin(sfx)
    sfx.presets_expanded = True
    rows = _content_rows(sfx)
    # No preset names -> the pool-presets empty line inside the expanded section.
    empty = [r for r in rows if r["label"] == "No pool presets yet. Save a pool as a preset to fill this."]
    assert len(empty) == 1
    assert empty[0]["type"] == "help"
    assert empty[0]["depth"] == 0


def test_sfx_content_rows_video_presets_no_auto_show_on_search(sfx):
    # A search match keeps the Video Presets/ header but its preset rows only
    # reveal on explicit expand (pools are timestamp folders, not the tree).
    _seed_builtin(sfx)
    rows = _content_rows(sfx, query="vp", vpresets=["vp"])
    labels = [r["label"] for r in rows]
    assert "Video Presets/" in labels
    assert "vp" not in labels


def test_sfx_content_rows_video_preset_children_expanded(sfx):
    _seed_builtin(sfx)
    sfx.video_presets_expanded = True
    sfx.expanded_video_presets = {"vp": True}
    sfx.expanded_video_pools = {"vp": {0: True}}
    rows = _content_rows(sfx, vpresets=["vp"])
    labels = [r["label"] for r in rows]
    assert labels == [
        "Recently Used/",
        "Pool Presets/",
        "Video Presets/",
        "vp",
        "00:01.50",
        "a.ogg",
        "b.ogg",
        "Intensity Groups/",
    ]


def test_sfx_content_rows_video_preset_empty_help(sfx):
    _seed_builtin(sfx)
    sfx.video_presets_expanded = True
    rows = _content_rows(sfx)
    assert "No video presets yet. Save video markers as a preset to fill this." in [r["label"] for r in rows]


def test_sfx_content_rows_intensity_children_expanded(sfx):
    _seed_builtin(sfx)
    sfx.igroups_expanded = True
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    sfx.expanded_file_refs = {"pool/": True}
    rows = _content_rows(sfx, igroups=["g"])
    labels = [r["label"] for r in rows]
    assert labels == [
        "Recently Used/",
        "Pool Presets/",
        "Video Presets/",
        "Intensity Groups/",
        "+ Group",
        "g",
        "+ Level",
        "Level 1/",
        "a.ogg",
        "pool/",
        "a.ogg",
    ]
    plus_group = rows[4]
    assert plus_group["action"] is _sfx_rows._cue.dialogs.intensity.open
    level = rows[7]
    # video context + available target -> the level [+] hooks to the pool
    assert level["buttons"][3]["enabled"] is True
    assert level["buttons"][3]["tt"].startswith("Attach this level to the Video pool.")


def test_sfx_content_rows_intensity_hook_disabled_without_target(sfx):
    _seed_builtin(sfx)
    sfx.igroups_expanded = True
    sfx.expanded_igroups = {"g": True}
    sfx.expanded_ilevels = {"g": {1}}
    rows = _content_rows(sfx, igroups=["g"], ctx="image")
    level = rows[7]
    assert level["buttons"][3]["enabled"] is False
    assert level["buttons"][3]["tt"] == "Select the Video or Loop target to hook this level."


def test_sfx_content_rows_search_filters_sections(sfx):
    # No section content matches "z": every header hides, the file tree is
    # empty, and the no-results line renders (plain, default-styled).
    _seed_builtin(sfx)
    rows = _content_rows(
        sfx, query="z", presets=["p"], vpresets=["vp"], igroups=["g"], recent_entries=[("file", "a.wav")]
    )
    assert len(rows) == 1
    assert rows[0]["type"] == "help"
    assert rows[0]["label"] == 'No files found for "z".'
    assert rows[0]["plain"] is True
    assert "plain" in rows[0]


def test_sfx_content_rows_search_reveals_preset_matches(sfx):
    # "a" matches the preset's file contents: Pool Presets header stays and its
    # matching file rows auto-show, even while collapsed.
    _seed_builtin(sfx)
    sfx.expanded_presets = {}
    rows = _content_rows(sfx, query="a", presets=["p"])
    labels = [r["label"] for r in rows]
    assert "Pool Presets/" in labels
    assert "p" in labels
    assert "a.ogg" in labels


def test_sfx_content_rows_per_source_empty_states(sfx, tmp_path):
    empty = str(tmp_path / "Empty")
    os.makedirs(empty, exist_ok=True)
    missing = str(tmp_path / "nope")
    sfx.external_folders = [empty, missing]
    sfx.scan()
    rows = _content_rows(sfx, presets=["p"])
    labels = _row_labels(rows)
    # Built-in source empty state: scan text + Open-folder action + Settings tip.
    assert "No audio files found in: {}".format(sfx._paths.audio_dir) in labels
    assert _find_button(rows, "builtin:open").get("explorer") == sfx._paths.audio_dir
    assert any("Settings > Data Folder" in label for label in labels)
    # Curated-pack download is reachable here too (built-in empty, external
    # sources present) -- it shares one row with the Open-folder button.
    row = [r for r in rows if r["type"] == "actions"][0]
    assert [b["key"] for b in row["actions"]] == ["builtin:open", "builtin:download_pack"]
    dl = _find_button(rows, "builtin:download_pack")
    assert dl["label"] == "Download Cue SFX Pack"
    assert dl.get("sensitive", True) is True
    assert dl["icon"] == "download"
    assert dl["action"]._args[0] == sfx.sfx_pack.download_sfx_pack
    # Found-but-empty external source: empty text + Open-folder action.
    assert "No audio files found in: {}".format(empty) in labels
    assert any(r["type"] == "action" and r.get("explorer") == empty for r in rows)
    # Missing external source keeps its warning (no Open action -- nothing to open).
    assert "Folder not found: {}".format(missing) in labels


def test_sfx_content_rows_truly_empty_returns_only_empty_rows(sfx):
    # No built-in files and no external folders: content_rows returns just the
    # built-in empty state -- no section chrome -- with the download row present.
    rows = _content_rows(sfx)
    labels = _row_labels(rows)
    assert labels == [
        "No audio files found in: {}".format(sfx._paths.audio_dir),
        "Add {} files there and click the refresh button.".format(", ".join(CUE_AUDIO_EXTS)),
        "Add additional folder locations in Settings > Data Folder.",
    ]
    # Open-folder + download share one action row; nothing else renders.
    row = [r for r in rows if r["type"] == "actions"][0]
    assert [b["label"] for b in row["actions"]] == ["Open Audio folder", "Download Cue SFX Pack"]
    assert "Recently Used/" not in labels
    assert "Pool Presets/" not in labels


def test_sfx_content_rows_download_label_follows_state(sfx):
    sfx.sfx_pack.state = "downloading"
    sfx.sfx_pack.progress = 0.5
    rows = _content_rows(sfx)
    dl = _find_button(rows, "builtin:download_pack")
    assert dl["label"] == "Downloading..."
    assert dl["sensitive"] is False
    assert "Downloading Cue SFX Pack... 50%" in _row_labels(rows)

    sfx.sfx_pack.state = "error"
    sfx.sfx_pack.error = "boom"
    rows = _content_rows(sfx)
    dl = _find_button(rows, "builtin:download_pack")
    assert dl["label"] == "Retry download"
    assert dl.get("sensitive", True) is True
    assert "boom" in _row_labels(rows)

    sfx.sfx_pack.state = "idle"
    rows = _content_rows(sfx)
    dl = _find_button(rows, "builtin:download_pack")
    assert dl["label"] == "Download Cue SFX Pack"
    assert dl.get("sensitive", True) is True


def test_sfx_content_rows_no_download_when_builtin_has_files(sfx, tmp_path):
    audio = str(tmp_path / "audio") + "/"
    os.makedirs(audio, exist_ok=True)
    open(os.path.join(audio, "a.ogg"), "w").close()
    sfx.scan()
    rows = _content_rows(sfx)
    labels = [r["label"] for r in rows]
    assert _find_button(rows, "builtin:download_pack") is None
    assert "No audio files found in: {}".format(sfx._paths.audio_dir) not in labels


def test_sfx_content_rows_appends_file_tree(sfx, tmp_path):
    audio = str(tmp_path / "audio") + "/"
    for rel in ("a.ogg", "sub/b.wav"):
        p = os.path.join(audio, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    sfx.scan()
    # Built-ins render under the synthetic root; expand it to see the tree.
    sfx.expanded_folders[CUE_SFX_FOLDER] = True
    sfx.rebuild_tree()
    rows = _content_rows(sfx, presets=["p"])
    tree_labels = [r["label"] for r in rows if r.get("key", "").startswith("tree:")]
    assert tree_labels == [CUE_SFX_FOLDER, "sub/", "a.ogg"]


# ==========================================================================
# Folder-expansion persistence
# ==========================================================================


def test_sfx_toggle_folder_persists(sfx):
    sfx.toggle_folder("sfx/")
    assert persistent._cue[CUE_PERSIST_SFX_TREE_EXPANDED] == {"sfx/": True}
    sfx.toggle_folder("sfx/")
    assert persistent._cue[CUE_PERSIST_SFX_TREE_EXPANDED] == {"sfx/": False}


def test_sfx_scan_default_open(sfx, monkeypatch):
    def _discover(results):
        results.update(["a.ogg", "sub/b.ogg"])

    monkeypatch.setattr(sfx, "_discover", _discover)
    sfx.scan()
    assert sfx.expanded_folders == {CUE_SFX_FOLDER: True}


def test_sfx_scan_restores_expansion(sfx, monkeypatch):
    def _discover(results):
        results.update(["a.ogg", "sub/b.ogg"])

    monkeypatch.setattr(sfx, "_discover", _discover)
    persistent._cue[CUE_PERSIST_SFX_TREE_EXPANDED] = {"sub/": True}
    sfx.scan()
    assert sfx.expanded_folders == {CUE_SFX_FOLDER: True, "sub/": True}


def test_sfx_file_ref_expand_persists(sfx):
    sfx.toggle_file_ref_expand("pool/")
    assert persistent._cue[CUE_PERSIST_SFX_UI_STATE]["expanded_file_refs"] == {"pool/": True}


def test_sfx_preset_expand_persists(sfx):
    sfx.toggle_preset_expand("Combat")
    assert persistent._cue[CUE_PERSIST_SFX_UI_STATE]["expanded_presets"] == {"Combat": True}
    sfx.toggle_presets_expand()
    assert persistent._cue[CUE_PERSIST_SFX_UI_STATE]["presets_expanded"] is True


def test_sfx_video_pool_persists_int_keys(sfx):
    sfx.toggle_video_pool_expand("Vid", 0)
    assert persistent._cue[CUE_PERSIST_SFX_UI_STATE]["expanded_video_pools"] == {"Vid": {"0": True}}


def test_sfx_intensity_expand_persists(sfx):
    sfx.expanded_ilevels.setdefault("grp", set()).add(2)
    sfx.toggle_igroup_expand("grp")
    blob = persistent._cue[CUE_PERSIST_SFX_UI_STATE]
    assert blob["expanded_igroups"] == {"grp": True}
    assert blob["expanded_ilevels"] == {"grp": [2]}


def test_sfx_restore_ui_state(sfx):
    persistent._cue[CUE_PERSIST_SFX_UI_STATE] = {
        "expanded_file_refs": {"pool/": True},
        "presets_expanded": True,
        "expanded_presets": {"Combat": True},
        "video_presets_expanded": True,
        "expanded_video_presets": {"Vid": True},
        "expanded_video_pools": {"Vid": {"0": True, "2": False}},
        "igroups_expanded": True,
        "expanded_igroups": {"grp": True},
        "expanded_ilevels": {"grp": [1, 3]},
    }
    sfx.restore_ui_state()
    assert sfx.expanded_file_refs == {"pool/": True}
    assert sfx.presets_expanded is True
    assert sfx.expanded_presets == {"Combat": True}
    assert sfx.video_presets_expanded is True
    assert sfx.expanded_video_pools == {"Vid": {0: True, 2: False}}
    assert sfx.igroups_expanded is True
    assert sfx.expanded_igroups == {"grp": True}
    assert sfx.expanded_ilevels == {"grp": set([1, 3])}


# ==========================================================================
# SFX pack download (empty-library bootstrap)
# ==========================================================================


def _write_pack_zip(url, dest_path, progress_cb=None):
    import zipfile

    with zipfile.ZipFile(dest_path, "w") as zf:
        zf.writestr("renpy_cue_sfx/g1/a.ogg", b"a")
        zf.writestr("renpy_cue_sfx/b.ogg", b"b")


def test_sfx_pack_download_extracts_then_rescans(sfx, monkeypatch):
    # The real _cue_extract_zip_to runs on the downloaded zip; only the
    # network hop is stubbed out.  The pack's renpy_cue_sfx/ wrapper dir is
    # unwrapped so its contents land directly in the audio dir.
    monkeypatch.setattr(sfx.sfx_pack._dl, "download_to", _write_pack_zip)
    sfx.sfx_pack.download_sfx_pack()
    assert sfx.sfx_pack.state == "downloading"
    sfx.sfx_pack._thread.join(timeout=5)
    assert not sfx.sfx_pack._thread.is_alive()
    assert sfx.sfx_pack.state == "done"
    sfx.sfx_pack.poll_sfx_pack()
    assert sfx.sfx_pack.state == "idle"
    assert "g1/a.ogg" in sfx.files
    assert "b.ogg" in sfx.files
    assert sfx.tree
    # The just-downloaded pack is expanded at the SFX root only; the g1/
    # subfolder stays collapsed.
    assert sfx.expanded_folders.get("SFX/") is True
    assert sfx.expanded_folders.get("SFX/g1/") is not True


def _zip_with(tmp_path, entries):
    import zipfile

    zpath = str(tmp_path / "p.zip")
    with zipfile.ZipFile(zpath, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return zpath


def test_extract_zip_to_unwraps_single_root(tmp_path):
    from cue_lib.sharing.importer_io import _cue_extract_zip_to

    out = str(tmp_path / "out")
    zpath = _zip_with(tmp_path, [("wrap/a.ogg", b"a"), ("wrap/g1/b.ogg", b"b")])
    assert _cue_extract_zip_to(zpath, out, unwrap_root=True) == 2
    assert os.path.isfile(os.path.join(out, "a.ogg"))
    assert os.path.isfile(os.path.join(out, "g1", "b.ogg"))
    assert not os.path.isdir(os.path.join(out, "wrap"))


def test_extract_zip_to_unwrap_keeps_mixed_archive(tmp_path):
    from cue_lib.sharing.importer_io import _cue_extract_zip_to

    out = str(tmp_path / "out")
    zpath = _zip_with(tmp_path, [("a.ogg", b"a"), ("wrap/b.ogg", b"b")])
    assert _cue_extract_zip_to(zpath, out, unwrap_root=True) == 2
    assert os.path.isfile(os.path.join(out, "a.ogg"))
    assert os.path.isfile(os.path.join(out, "wrap", "b.ogg"))


def test_extract_zip_to_default_keeps_wrapper_dir(tmp_path):
    from cue_lib.sharing.importer_io import _cue_extract_zip_to

    out = str(tmp_path / "out")
    zpath = _zip_with(tmp_path, [("wrap/a.ogg", b"a")])
    assert _cue_extract_zip_to(zpath, out) == 1
    assert os.path.isfile(os.path.join(out, "wrap", "a.ogg"))


def test_sfx_pack_download_error_sets_state(sfx, monkeypatch):
    def _boom(url, dest_path, progress_cb=None):
        raise IOError("no network")

    monkeypatch.setattr(sfx.sfx_pack._dl, "download_to", _boom)
    sfx.sfx_pack.download_sfx_pack()
    sfx.sfx_pack._thread.join(timeout=5)
    assert sfx.sfx_pack.state == "error"
    assert "no network" in sfx.sfx_pack.error


def test_sfx_pack_download_noop_while_running(sfx, monkeypatch):
    import threading

    started = threading.Event()
    release = threading.Event()

    def _blocked(url, dest_path, progress_cb=None):
        started.set()
        release.wait(5)

    monkeypatch.setattr(sfx.sfx_pack._dl, "download_to", _blocked)
    sfx.sfx_pack.download_sfx_pack()
    started.wait(2)
    first = sfx.sfx_pack._thread
    sfx.sfx_pack.download_sfx_pack()
    assert sfx.sfx_pack._thread is first
    release.set()
    first.join(timeout=5)


def test_sfx_pack_poll_rescans_once(sfx, monkeypatch):
    calls = []

    def _fake_scan():
        calls.append(1)

    monkeypatch.setattr(sfx, "scan", _fake_scan)
    sfx.sfx_pack.state = "done"
    sfx.sfx_pack.poll_sfx_pack()
    sfx.sfx_pack.poll_sfx_pack()
    assert len(calls) == 1
    assert sfx.sfx_pack.state == "idle"


def test_sfx_pack_poll_scan_error_becomes_error_state(sfx, monkeypatch):
    def _boom():
        raise OSError("scan failed")

    monkeypatch.setattr(sfx, "scan", _boom)
    sfx.sfx_pack.state = "done"
    sfx.sfx_pack.poll_sfx_pack()
    assert sfx.sfx_pack.state == "error"
    assert "scan failed" in sfx.sfx_pack.error
