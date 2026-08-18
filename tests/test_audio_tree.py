# -*- coding: utf-8 -*-
# Tests for the audio-library file-tree search: the pure _cue_filter_tree
# helper (util.py) and the CueAudioTreeManager search/rebuild/clear behavior.
# CueAudioTreeManager takes no constructor args and rebuild_tree() reads only
# self.tree / self.expanded_folders / self.search_query, so the manager is
# tested headlessly without touching the _cue singleton.

import copy

from cue_lib.audio.audio_tree import CUE_SEARCH_MAX_ROWS, CueAudioTreeManager
from cue_lib.audio.game_music import CueGameMusic
from cue_lib.audio.user_music import CueUserMusic
from cue_lib.util import _cue_build_tree, _cue_filter_tree

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


# ---------------------------------------------------------------------------
# _cue_filter_tree (pure)
# ---------------------------------------------------------------------------

def test_filter_tree_case_insensitive_file_match():
    tree = _cue_build_tree(["v2/agrat/02_IntenseMo.mp3", "v2/amira/01_NormalMo.mp3"])
    filtered = _cue_filter_tree(tree, "intense")
    # v2/ and agrat/ survive as ancestors of the match; amira/ is pruned.
    assert _children_names(filtered) == ["v2/"]
    v2 = filtered[0]
    assert _children_names(v2["children"]) == ["agrat/"]
    assert _children_names(v2["children"][0]["children"]) == ["02_IntenseMo.mp3"]


def test_filter_tree_folder_match_keeps_full_contents():
    tree = _cue_build_tree(["v2/agrat/01_SubtleMo.mp3", "v2/agrat/02_IntenseMo.mp3",
                            "v2/agrat/03_ClosedMo.mp3"])
    filtered = _cue_filter_tree(tree, "agrat")
    assert _children_names(filtered) == ["v2/"]
    agrat = filtered[0]["children"][0]
    assert _children_names(agrat["children"]) == [
        "01_SubtleMo.mp3", "02_IntenseMo.mp3", "03_ClosedMo.mp3",
    ]


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


# ---------------------------------------------------------------------------
# CueAudioTreeManager search/rebuild/clear
# ---------------------------------------------------------------------------

def test_rebuild_tree_search_filters_and_expands_all():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.search_query = "intense"
    mgr.rebuild_tree()
    folders = [row for row in mgr.visible_tree if row["type"] == "folder"]
    assert folders
    assert all(row["expanded"] for row in folders)
    files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    assert files == [
        "v2/agrat/02_IntenseMo.mp3",
        "v2/anya/04_IntenseMo.mp3",
        "v2/nora/03_IntenseMo.mp3",
    ]


def test_rebuild_tree_idle_respects_expansion():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(["v2/a.mp3", "v2/b.mp3"])
    mgr.expanded_folders = {"v2/": False}
    mgr.rebuild_tree()
    # Collapsed v2/ shows as a folder row only; children stay hidden.
    assert [row["type"] for row in mgr.visible_tree] == ["folder"]
    assert len(mgr.visible_tree) == 1


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


# ---------------------------------------------------------------------------
# Search result cap + debounced rebuild
# ---------------------------------------------------------------------------

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


def test_maybe_rebuild_only_on_query_change():
    mgr = CueAudioTreeManager()
    mgr.tree = _cue_build_tree(FILES)
    mgr.search_query = "intense"
    mgr.maybe_rebuild()
    files = [row["full_path"] for row in mgr.visible_tree if row["type"] == "file"]
    assert files == [
        "v2/agrat/02_IntenseMo.mp3",
        "v2/anya/04_IntenseMo.mp3",
        "v2/nora/03_IntenseMo.mp3",
    ]
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
