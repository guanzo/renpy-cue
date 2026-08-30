# -*- coding: utf-8 -*-
# Tests for cue_lib.audio.tree.music_tree: the combined "Music Library" tree that
# merges the separate My Music / Game Music trees under two synthetic top
# folders for a single UI tree and one shared search bar.  The underlying
# data models stay separate; only the display is combined.
#
# The combined view is built against two fake sub-managers (SimpleNamespace
# with a pre-built tree) and a fake music manager that records dispatch calls,
# so merge / flatten / search / dispatch are all asserted headlessly.

import os
import types

import pytest

import renpy

from renpy.store import persistent

import cue_lib.audio.tree.music_tree as _tree
from cue_lib.audio.tree.music_tree import CueMusicTree
from cue_lib.constants import (
    CUE_GAME_MUSIC_FOLDER,
    CUE_MUSIC_GAME_TAG,
    CUE_MUSIC_PREFIX,
    CUE_MUSIC_USER_TAG,
    CUE_MY_MUSIC_FOLDER,
    CUE_PERSIST_MUSIC_TREE_EXPANDED,
)
from cue_lib.util import _cue_build_tree

USER = CUE_MY_MUSIC_FOLDER
GAME = CUE_GAME_MUSIC_FOLDER


@pytest.fixture(autouse=True)
def _clean_persistent(monkeypatch):
    """Fresh persistent._cue for every test (tree toggle state writes it)."""
    monkeypatch.setattr(persistent, "_cue", {})


def _fake_split_tag(ref):
    # type: (str) -> tuple
    """Mirror of CueMusicManager._split_ref_tag for the fake manager."""
    for tag in (CUE_MUSIC_USER_TAG, CUE_MUSIC_GAME_TAG):
        if ref.startswith(tag):
            return tag, ref[len(tag) :]
    return None, ref


def _fake_tree(paths):
    # type: (tuple) -> list
    return _cue_build_tree(sorted(paths)) if paths else []


def _make_lib(user_paths=(), game_paths=()):
    # type: (tuple, tuple) -> tuple
    """Build (lib, calls) with recording dispatch + seeded per-source trees."""
    calls = []

    def _rec(name):
        # type: (str) -> object
        def _f(*args, **kwargs):
            calls.append((name, args, kwargs))

        return _f

    music = types.SimpleNamespace(
        add_user_song_to_trigger=_rec("add_user_song"),
        add_game_song_to_trigger=_rec("add_game_song"),
        add_external_song_to_trigger=_rec("add_external_song"),
        add_user_folder_to_trigger=_rec("add_user_folder"),
        add_game_folder_to_trigger=_rec("add_game_folder"),
        add_external_folder_to_trigger=_rec("add_external_folder"),
        play_untracked=_rec("play_untracked"),
        _resolve_music_path=lambda p: "ABS:" + p,
        _split_ref_tag=_fake_split_tag,
    )
    lib = CueMusicTree(music)
    lib.user_files = list(user_paths)
    lib.game_files = list(game_paths)
    lib.user_tree = _fake_tree(user_paths)
    lib.game_tree = _fake_tree(game_paths)
    lib._rebuild_merged()
    return lib, calls


def _rows(lib):
    # type: (CueMusicTree) -> dict
    return {r["full_path"]: r for r in lib.visible_tree}


# ==========================================================================
# Merge + flatten
# ==========================================================================


def test_merged_tree_wraps_both_sources():
    lib, _calls = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"), game_paths=("bgm/x.ogg", "music/y.ogg"))
    lib.rebuild_tree()
    # Both synthetic roots get the one-time default expansion.
    assert lib.expanded_folders == {USER: True, GAME: True}
    # Only the two synthetic roots are expanded by default; expand the inner
    # sub-folders so their child rows are rendered.
    lib.toggle_folder(USER + "sub/")
    lib.toggle_folder(GAME + "bgm/")
    lib.toggle_folder(GAME + "music/")
    rows = _rows(lib)
    # User "music/" root is hoisted under the synthetic "My Music/" folder.
    assert rows[USER]["type"] == "folder"
    assert rows[USER + "a.ogg"]["full_path"] == USER + "a.ogg"
    assert rows[USER + "sub/b.ogg"]["full_path"] == USER + "sub/b.ogg"
    # Game tree is wrapped under the synthetic "Game Music/" folder.
    assert rows[GAME]["type"] == "folder"
    assert rows[GAME + "bgm/x.ogg"]["full_path"] == GAME + "bgm/x.ogg"
    assert rows[GAME + "music/y.ogg"]["full_path"] == GAME + "music/y.ogg"


def test_flatten_renames_music_root_only_in_ui():
    # The data-model "music/" root is renamed to "My Music" in the display --
    # there must be no "My Music/music/" path.
    lib, _calls = _make_lib(user_paths=("music/a.ogg",))
    lib.rebuild_tree()
    rows = _rows(lib)
    assert "My Music/music/" not in rows
    assert rows[USER + "a.ogg"]["depth"] == 1
    # The data model is untouched: the library still owns its "music/"
    # prefixed files.
    assert lib.user_files == ["music/a.ogg"]


def test_merged_tree_skips_empty_source():
    lib, _calls = _make_lib(game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    rows = _rows(lib)
    assert USER not in rows
    assert GAME in rows


def test_music_source_accessors_parity(monkeypatch, tmp_path):
    # The base accessors must read the same per-source attrs scan() populates
    # through _scan_builtin_sources -- the contract recent.py and the rows
    # builders depend on by name.
    music_dir = str(tmp_path / "music") + "/"
    for rel in ("song.ogg",):
        p = os.path.join(music_dir, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w").close()
    monkeypatch.setattr(_tree, "_cue", types.SimpleNamespace(paths=types.SimpleNamespace(music_dir=music_dir)))
    monkeypatch.setattr(renpy, "list_files", lambda: ["bgm/x.ogg"])
    lib = CueMusicTree(types.SimpleNamespace())
    lib.scan()
    assert lib._source_files("user") == lib.user_files
    assert lib._source_tree("game") == lib.game_tree
    assert lib._source_scan_error("user") == lib.user_scan_error
    assert lib._source_scan_error("game") == lib.game_scan_error
    assert lib.user_files == ["music/song.ogg"]
    assert lib.game_files == ["bgm/x.ogg"]


def test_merged_tree_empty_when_both_empty():
    lib, _calls = _make_lib()
    lib.rebuild_tree()
    assert lib.tree == []
    assert lib.visible_tree == []


# ==========================================================================
# Search (one query over both sources)
# ==========================================================================


def test_search_filters_across_both_sources():
    lib, _calls = _make_lib(user_paths=("music/song.ogg",), game_paths=("bgm/song.ogg", "music/other.ogg"))
    lib.rebuild_tree()
    lib.search_query = "bgm"
    lib.rebuild_tree()
    rows = _rows(lib)
    # The bgm/ folder is default-collapsed, so its match appearing proves
    # search force-expands every folder.
    assert GAME + "bgm/song.ogg" in rows
    assert USER + "song.ogg" not in rows


def test_search_matches_both_sources():
    lib, _calls = _make_lib(user_paths=("music/song.ogg",), game_paths=("bgm/song.ogg",))
    lib.rebuild_tree()
    lib.search_query = "song"
    lib.rebuild_tree()
    rows = _rows(lib)
    assert USER + "song.ogg" in rows
    assert GAME + "bgm/song.ogg" in rows


def test_search_caps_rows():
    user_paths = tuple("music/song{:02d}.ogg".format(i) for i in range(120))
    lib, _calls = _make_lib(user_paths=user_paths)
    lib.rebuild_tree()
    lib.search_query = "song"
    lib.rebuild_tree()
    # 120 files + 1 "My Music/" folder row = 121, capped at 100.
    assert lib.search_truncated == 21
    assert len(lib.visible_tree) == 100


def test_clear_search_restores_collapsed_tree():
    lib, _calls = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"))
    lib.rebuild_tree()
    lib.search_query = "b"
    lib.rebuild_tree()
    assert USER + "sub/b.ogg" in _rows(lib)
    assert USER + "a.ogg" not in _rows(lib)
    lib.clear_search()
    assert lib.search_query == ""
    rows = _rows(lib)
    assert USER + "a.ogg" in rows
    # Non-root folders are collapsed again once the search is cleared: the
    # sub-folder's match is hidden and no saved expansion was left behind.
    assert USER + "sub/b.ogg" not in rows
    assert lib.expanded_folders.get(USER + "sub/", False) is False


# ==========================================================================
# Expansion state
# ==========================================================================


def test_toggle_folder_collapses_and_expands():
    lib, _calls = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"))
    lib.rebuild_tree()
    # A sub-folder starts collapsed; the first toggle expands it, the second
    # collapses it.
    lib.toggle_folder(USER + "sub/")
    assert lib.expanded_folders.get(USER + "sub/", False) is True
    assert USER + "sub/b.ogg" in _rows(lib)
    lib.toggle_folder(USER + "sub/")
    rows = _rows(lib)
    assert lib.expanded_folders.get(USER + "sub/", False) is False
    assert USER + "sub/b.ogg" not in rows


def test_toggle_folder_noop_during_search():
    lib, _calls = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"))
    lib.rebuild_tree()
    lib.search_query = "b"
    lib.rebuild_tree()
    lib.toggle_folder(USER + "sub/")
    # Toggle is a no-op during search: the match stays force-expanded and no
    # saved expansion state is recorded.
    assert USER + "sub/b.ogg" in _rows(lib)
    assert lib.expanded_folders.get(USER + "sub/", False) is False


# ==========================================================================
# maybe_rebuild / rescan detection
# ==========================================================================


def test_maybe_rebuild_skips_when_unchanged():
    lib, _calls = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    before = lib.visible_tree
    lib.maybe_rebuild()
    assert lib.visible_tree == before


def test_maybe_rebuild_skips_rebuild_after_rebuild_tree(monkeypatch):
    # A fresh rebuild_tree stamps the source-tree ids, so the next
    # maybe_rebuild must not re-merge (the tick loop calls it constantly).
    lib, _calls = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    seen = []
    monkeypatch.setattr(lib, "rebuild_tree", lambda: seen.append(1))
    lib.maybe_rebuild()
    assert seen == []


# ==========================================================================
# has_files on combined rows (UI shows "+" on folders that directly contain
# files; the synthetic Game Music root and nested-only folders get none)
# ==========================================================================


def test_folder_rows_has_files():
    lib, _calls = _make_lib(user_paths=("music/a.ogg", "music/sub/deep.ogg"), game_paths=("bgm/ost/y.ogg",))
    lib.rebuild_tree()
    rows = _rows(lib)
    # Direct file under the folder -> shows "+".
    assert rows[USER]["has_files"] is True  # My Music/ hoists music/a.ogg
    assert rows[USER + "sub/"]["has_files"] is True
    # Nested-only folder (no direct files) -> no "+".
    assert rows[GAME + "bgm/"]["has_files"] is False
    # Synthetic Game Music root -> no "+".
    assert rows[GAME]["has_files"] is False


# ==========================================================================
# Dispatch: display path -> data path (refs stay tagged u:/g:)
# ==========================================================================


def test_add_song_user_routes_stored_ref():
    lib, calls = _make_lib(user_paths=("music/a.ogg",))
    lib.add_song_to_trigger(CUE_MUSIC_USER_TAG + "music/a.ogg")
    assert calls == [("add_user_song", ("music/a.ogg",), {"record": True})]


def test_add_song_user_nested_folder():
    lib, calls = _make_lib(user_paths=("music/folder/song.ogg",))
    lib.add_song_to_trigger(CUE_MUSIC_USER_TAG + "music/folder/song.ogg")
    assert calls == [("add_user_song", ("music/folder/song.ogg",), {"record": True})]


def test_add_song_game_routes():
    lib, calls = _make_lib(game_paths=("bgm/x.ogg",))
    lib.add_song_to_trigger(CUE_MUSIC_GAME_TAG + "bgm/x.ogg")
    assert calls == [("add_game_song", ("bgm/x.ogg",), {"record": True})]


def test_add_folder_user_routes():
    lib, calls = _make_lib(user_paths=("music/sub/b.ogg",))
    lib.add_folder_to_trigger(CUE_MUSIC_USER_TAG + "music/sub/")
    assert calls == [("add_user_folder", ("music/sub/",), {"record": True})]


def test_add_folder_user_root_adds_all():
    lib, calls = _make_lib(user_paths=("music/a.ogg",))
    lib.add_folder_to_trigger(CUE_MUSIC_USER_TAG + "music/")
    assert calls == [("add_user_folder", ("music/",), {"record": True})]


def test_add_folder_game_routes():
    lib, calls = _make_lib(game_paths=("bgm/x.ogg",))
    lib.add_folder_to_trigger(CUE_MUSIC_GAME_TAG + "bgm/")
    assert calls == [("add_game_folder", ("bgm/",), {"record": True})]


def test_add_folder_game_synthetic_root_noop():
    lib, calls = _make_lib(game_paths=("bgm/x.ogg",))
    lib.add_folder_to_trigger(CUE_MUSIC_GAME_TAG)
    assert calls == []


def test_add_song_record_false_passes_through():
    lib, calls = _make_lib(user_paths=("music/a.ogg",))
    lib.add_song_to_trigger(CUE_MUSIC_USER_TAG + "music/a.ogg", record=False)
    assert calls == [("add_user_song", ("music/a.ogg",), {"record": False})]


def test_add_folder_record_false_passes_through():
    lib, calls = _make_lib(user_paths=("music/sub/b.ogg",))
    lib.add_folder_to_trigger(CUE_MUSIC_USER_TAG + "music/sub/", record=False)
    assert calls == [("add_user_folder", ("music/sub/",), {"record": False})]


def test_preview_user_resolves_music_path():
    lib, calls = _make_lib(user_paths=("music/a.ogg",))
    lib.preview(CUE_MUSIC_USER_TAG + "music/a.ogg", volume=0.5)
    assert calls == [("play_untracked", ("ABS:u:music/a.ogg",), {"volume": 0.5})]


def test_preview_game_passes_path():
    lib, calls = _make_lib(game_paths=("bgm/x.ogg",))
    lib.preview(CUE_MUSIC_GAME_TAG + "bgm/x.ogg")
    assert calls == [("play_untracked", ("ABS:g:bgm/x.ogg",), {"volume": 1.0})]


# ==========================================================================
# stored-ref -> display-path conversion (display_for_ref)
# ==========================================================================


def test_ref_display_path_user():
    lib, _calls = _make_lib()
    assert lib.display_for_ref(CUE_MUSIC_USER_TAG + "music/song.ogg") == USER + "song.ogg"


def test_ref_display_path_user_folder():
    lib, _calls = _make_lib()
    assert lib.display_for_ref(CUE_MUSIC_USER_TAG + "music/sub/") == USER + "sub/"


def test_ref_display_path_game():
    lib, _calls = _make_lib()
    assert lib.display_for_ref(CUE_MUSIC_GAME_TAG + "bgm/x.ogg") == GAME + "bgm/x.ogg"


def test_ref_display_path_game_folder():
    lib, _calls = _make_lib()
    assert lib.display_for_ref(CUE_MUSIC_GAME_TAG + "bgm/") == GAME + "bgm/"


def test_ref_display_path_untagged_treated_as_user():
    lib, _calls = _make_lib()
    assert lib.display_for_ref("music/song.ogg") == USER + "song.ogg"


def test_ref_display_path_never_leaks_data_prefix():
    # Every stored ref renders under a synthetic My Music/ or Game Music/
    # root -- the data-model "music/" prefix never appears in the UI.
    lib, _calls = _make_lib()
    refs = (
        CUE_MUSIC_USER_TAG + "music/a.ogg",
        CUE_MUSIC_USER_TAG + "music/sub/",
        CUE_MUSIC_GAME_TAG + "bgm/x.ogg",
        CUE_MUSIC_GAME_TAG + "bgm/",
    )
    for ref in refs:
        disp = lib.display_for_ref(ref)
        assert not disp.startswith(CUE_MUSIC_PREFIX)
        assert disp.startswith(USER) or disp.startswith(GAME)


# ==========================================================================
# Stored ref round-trip (display <-> stored ref via the base hooks)
# ==========================================================================


def test_music_ref_from_display_user():
    lib, _calls = _make_lib(user_paths=("music/a.ogg",))
    assert lib.ref_from_display(USER + "a.ogg") == CUE_MUSIC_USER_TAG + "music/a.ogg"


def test_music_ref_from_display_game():
    lib, _calls = _make_lib(game_paths=("bgm/x.ogg",))
    assert lib.ref_from_display(GAME + "bgm/x.ogg") == CUE_MUSIC_GAME_TAG + "bgm/x.ogg"


def test_music_ref_round_trip():
    lib, _calls = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    for ref in (CUE_MUSIC_USER_TAG + "music/a.ogg", CUE_MUSIC_GAME_TAG + "bgm/x.ogg"):
        assert lib.ref_from_display(lib.display_for_ref(ref)) == ref


def test_music_ref_round_trip_external(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib, _calls = _make_lib()
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    ref = _ext_abs(d1) + "/artist/song.ogg"
    assert lib.ref_from_display(lib.display_for_ref(ref)) == ref


def test_music_file_node_stashes_ref():
    lib, _calls = _make_lib(user_paths=("music/a.ogg",))
    rows = _rows(lib)
    assert rows[USER + "a.ogg"]["ref"] == CUE_MUSIC_USER_TAG + "music/a.ogg"


# ==========================================================================
# External sources (Settings > Data Folder music folders)
# ==========================================================================


def _ext_abs(p):
    # type: (object) -> str
    return str(p).replace("\\", "/")


def _scan_lib(tmp_path, folders, user_paths=(), game_paths=()):
    # type: (object, list, tuple, tuple) -> CueMusicTree
    """Lib with external_folders set and externals scanned (built-ins seeded)."""
    lib, _calls = _make_lib(user_paths=user_paths, game_paths=game_paths)
    lib.external_folders = [_ext_abs(p) for p in folders]
    lib._scan_external()
    return lib


def test_scan_external_builds_sources(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    (d1 / "top.ogg").write_bytes(b"x")
    d2 = tmp_path / "ExtB"
    d2.mkdir()
    (d2 / "loop.ogg").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1, d2])
    assert len(lib.external_sources) == 2
    src = lib.external_sources[0]
    root = _ext_abs(d1)
    assert src["abs_root"] == root
    assert src["label"] == "ExtA"
    assert src["files"] == [root + "/artist/song.ogg", root + "/top.ogg"]
    assert src["scan_error"] == ""
    assert lib.external_files == src["files"] + lib.external_sources[1]["files"]
    # External tree is relative (no e: tag), so it renders under the label.
    assert src["tree"][0] == {
        "type": "folder",
        "name": "artist/",
        "has_files": True,
        "children": [{"type": "file", "name": "song.ogg"}],
    }


def test_scan_external_sorts_flattened_global(tmp_path):
    # Folders added in reverse-alphabetical order: the flattened external_files
    # must still be globally sorted, because _cue_expand_folder_ref bisects it
    # (a stored folder ref expands to [] when the list isn't sorted).
    d1 = tmp_path / "Zeta"
    d1.mkdir()
    (d1 / "a.ogg").write_bytes(b"x")
    d2 = tmp_path / "Alpha"
    d2.mkdir()
    (d2 / "b.ogg").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1, d2])
    assert lib.external_files == sorted(lib.external_files)


def test_scan_external_missing_folder_sets_error(tmp_path):
    missing = tmp_path / "Nope"
    lib = _scan_lib(tmp_path, [missing])
    src = lib.external_sources[0]
    assert src["files"] == []
    assert src["tree"] == []
    assert "Folder not found" in src["scan_error"]


def test_scan_external_skips_non_audio_files(tmp_path):
    d1 = tmp_path / "ExtA"
    d1.mkdir()
    (d1 / "song.ogg").write_bytes(b"x")
    (d1 / "readme.txt").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1])
    assert lib.external_sources[0]["files"] == [_ext_abs(d1) + "/song.ogg"]


def test_external_label_disambiguates_reserved(tmp_path):
    d1 = tmp_path / "My Music"
    d1.mkdir()
    (d1 / "a.ogg").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1])
    assert lib.external_sources[0]["label"] == "My Music (2)"


def test_external_label_disambiguates_duplicates(tmp_path):
    d1 = tmp_path / "A" / "Shared"
    d2 = tmp_path / "B" / "Shared"
    d1.mkdir(parents=True)
    (d1 / "x.ogg").write_bytes(b"x")
    d2.mkdir(parents=True)
    (d2 / "y.ogg").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1, d2])
    assert [s["label"] for s in lib.external_sources] == ["Shared", "Shared (2)"]


def test_merged_tree_appends_external_wrappers(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1], user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    lib._rebuild_merged()
    assert [n["name"] for n in lib.tree] == ["My Music/", "ExtA/", "Game Music/"]
    ext = lib.tree[1]
    assert ext["has_files"] is False
    assert ext["children"][0]["name"] == "artist/"


def test_merged_tree_keeps_missing_external_wrapper(tmp_path):
    missing = tmp_path / "Nope"
    lib = _scan_lib(tmp_path, [missing], user_paths=("music/a.ogg",))
    lib._rebuild_merged()
    assert [n["name"] for n in lib.tree] == ["My Music/", "Nope/"]


def test_add_song_external_routes(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib, calls = _make_lib()
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    lib.add_song_to_trigger(_ext_abs(d1) + "/artist/song.ogg")
    assert calls[-1][0] == "add_external_song"
    assert calls[-1][1] == (_ext_abs(d1) + "/artist/song.ogg",)


def test_add_folder_external_routes(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib, calls = _make_lib()
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    lib.add_folder_to_trigger(_ext_abs(d1) + "/artist/")
    assert calls[-1][0] == "add_external_folder"
    assert calls[-1][1] == (_ext_abs(d1) + "/artist/",)


def test_add_folder_external_label_prefix_not_confused(tmp_path):
    # "ExtA2/..." must not match the "ExtA" source.
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib, calls = _make_lib()
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    lib.add_song_to_trigger("ExtA2/x.ogg")
    # Not an absolute path -> untagged user ref (falls through to user default).
    assert calls[-1][0] == "add_user_song"


def test_ref_display_path_external(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib = _scan_lib(tmp_path, [d1])
    ref = lib.external_sources[0]["files"][0]
    assert lib.display_for_ref(ref) == "ExtA/artist/song.ogg"


def test_ref_display_path_external_no_source_falls_back_to_abs(tmp_path):
    # A stored external ref whose source was removed still renders.
    lib, _calls = _make_lib()
    assert lib.display_for_ref("E:/Gone/sub/x.ogg") == "E:/Gone/sub/x.ogg"


def test_preview_external_plays_absolute(tmp_path):
    d1 = tmp_path / "ExtA"
    (d1 / "artist").mkdir(parents=True)
    (d1 / "artist" / "song.ogg").write_bytes(b"x")
    lib, calls = _make_lib()
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    lib.preview(_ext_abs(d1) + "/artist/song.ogg")
    assert calls[-1] == ("play_untracked", ("ABS:" + _ext_abs(d1) + "/artist/song.ogg",), {"volume": 1.0})


# ==========================================================================
# row_buttons (music tree)
# ==========================================================================


def _row_lib(sel_label="", selected_key=None, has_files=True):
    # type: (str, object, bool) -> CueMusicTree
    """Lib with a two-row visible_tree (folder + file) and a fake music mgr."""
    music = types.SimpleNamespace(selected_trigger_label=lambda: sel_label, selected_key=selected_key)
    lib = CueMusicTree(music)
    lib.visible_tree = [
        {"type": "folder", "name": "My Music/", "full_path": "My Music/", "depth": 0, "has_files": has_files},
        {
            "type": "file",
            "name": "a.ogg",
            "full_path": "My Music/a.ogg",
            "depth": 1,
            "ref": CUE_MUSIC_USER_TAG + "music/a.ogg",
        },
    ]
    return lib


def test_music_row_buttons_plus_play_order():
    lib = _row_lib(sel_label="S1", selected_key="replay:r")
    rows = lib.tree_rows("x.ogg")
    folder, file_row = rows
    assert [b["icon"] for b in folder["buttons"]] == ["plus"]  # no play on folders
    assert folder["buttons"][0]["tt"] == "Add folder to S1"
    assert folder["buttons"][0]["enabled"] is True
    assert folder["buttons"][0]["action"]._args[0] == lib.add_folder_to_trigger
    assert folder["buttons"][0]["action"]._args[1] == CUE_MUSIC_USER_TAG + "music/"
    assert [b["icon"] for b in file_row["buttons"]] == ["plus", "play"]
    assert file_row["buttons"][0]["tt"] == "Add song to S1"
    assert file_row["buttons"][0]["action"]._args[0] == lib.add_song_to_trigger
    assert file_row["buttons"][0]["action"]._args[1] == CUE_MUSIC_USER_TAG + "music/a.ogg"
    assert file_row["buttons"][1]["tt"] == "Play song"
    assert file_row["buttons"][1]["action"]._args[0] == lib.preview
    assert file_row["buttons"][1]["action"]._args[1] == CUE_MUSIC_USER_TAG + "music/a.ogg"
    assert file_row["gap"] == 1  # music matches SFX's label gap


def test_music_row_buttons_gates_on_selection_or_current_file():
    lib = _row_lib(sel_label="", selected_key=None)  # no selection, no current
    rows = lib.tree_rows("")
    assert rows[0]["buttons"][0]["enabled"] is False
    assert rows[1]["buttons"][0]["enabled"] is False
    lib2 = _row_lib(sel_label="", selected_key=None)
    rows2 = lib2.tree_rows("s.ogg")  # current_file alone enables
    assert rows2[0]["buttons"][0]["enabled"] is True
    lib3 = _row_lib(sel_label="", selected_key="replay:r")
    rows3 = lib3.tree_rows("")  # selected_key alone enables; default target label
    assert rows3[1]["buttons"][0]["enabled"] is True
    assert rows3[1]["buttons"][0]["tt"] == "Add song to a new trigger for the current shot"


def test_music_folder_without_files_has_no_buttons():
    lib = _row_lib(has_files=False)
    rows = lib.tree_rows("")
    assert rows[0]["buttons"] == []


# ==========================================================================
# content_rows (music section stream)
# ==========================================================================


def _content_lib(
    user_paths=("music/a.ogg",),
    game_paths=("bgm/x.ogg",),
    sel_label="S1",
    selected_key="replay:r",
    user_scan="",
    game_scan="",
):
    # type: (tuple, tuple, str, object, str, str) -> CueMusicTree
    """Lib with a full fake music manager for content_rows: presets, recent,
    selection, per-source empty/scan states."""
    music = types.SimpleNamespace(
        selected_trigger_label=lambda: sel_label,
        selected_key=selected_key,
        _paths=types.SimpleNamespace(music_dir="/music/"),
        presets_expanded=True,
        expanded_presets={},
        toggle_presets_expand=lambda: None,
        toggle_preset_expand=lambda n: None,
        _presets=types.SimpleNamespace(music=types.SimpleNamespace(get=lambda n: {"files": ["a.ogg", "b.ogg"]})),
        preset_display_files=lambda p: ["a.ogg", "b.ogg"],
        apply_preset=lambda n: None,
        preset_remove_file=lambda n, f: None,
        add_user_song_to_trigger=lambda *a, **k: None,
        add_game_song_to_trigger=lambda *a, **k: None,
        add_user_folder_to_trigger=lambda *a, **k: None,
        add_game_folder_to_trigger=lambda *a, **k: None,
        play_untracked=lambda *a, **k: None,
        _resolve_music_path=lambda p: "ABS:" + p,
        _split_ref_tag=_fake_split_tag,
    )
    lib = CueMusicTree(music)
    lib.user_files = list(user_paths)
    lib.game_files = list(game_paths)
    lib.user_tree = _fake_tree(user_paths)
    lib.game_tree = _fake_tree(game_paths)
    lib.user_scan_error = user_scan
    lib.game_scan_error = game_scan
    return lib


def _content_rows(lib, query="", presets=(), current_file=None, recent_entries=(), recent_expanded=False):
    # type: (CueMusicTree, str, tuple, object, tuple, bool) -> list
    """Full Music section stream via the builder.  recent_entries None wires
    no recent manager; otherwise the fake returns the given (type, ref) pairs."""
    import cue_lib.audio.tree.music_tree_rows as tree_rows_mod

    music = lib._music
    if recent_entries is None:
        music._recent = None
    else:
        music._recent = types.SimpleNamespace(
            expanded=recent_expanded,
            entries=lambda: [{"type": t, "ref": r} for t, r in recent_entries],
            toggle=lambda: None,
        )
    return tree_rows_mod.CueMusicTreeRows(lib).content_rows(query, list(presets), current_file)


def test_music_content_rows_recent_children_when_expanded():
    lib = _content_lib()
    rows = _content_rows(lib, recent_entries=[("file", "u:music/a.ogg"), ("folder", "g:bgm/")], recent_expanded=True)
    # The recent header, then the two recent rows (file + folder).
    assert rows[0]["type"] == "folder"
    assert rows[0]["label"] == "Recently Used/"
    file_row, folder_row = rows[1], rows[2]
    assert file_row["type"] == "file"
    assert file_row["label"] == "My Music/a.ogg"
    assert file_row["depth"] == 1
    assert file_row["gap"] == 1  # matches SFX file rows
    assert [b["icon"] for b in file_row["buttons"]] == ["plus", "play"]
    assert file_row["buttons"][0]["action"]._args[0] == lib.add_song_to_trigger
    assert folder_row["type"] == "file"
    assert folder_row["label"] == "Game Music/bgm/"
    assert [b["icon"] for b in folder_row["buttons"]] == ["plus"]
    assert folder_row["buttons"][0]["action"]._args[0] == lib.add_folder_to_trigger


def test_music_content_rows_recent_empty_help():
    lib = _content_lib()
    rows = _content_rows(lib, recent_entries=(), recent_expanded=True)
    assert any(r["type"] == "help" and r["label"] == "Songs you add to a trigger show up here." for r in rows)


def test_music_content_rows_preset_folder_and_children():
    lib = _content_lib()
    lib._music.expanded_presets = {"p1": True}
    rows = _content_rows(lib, presets=["p1"], recent_entries=None)
    labels = [r["label"] for r in rows]
    assert "Music Presets/" in labels
    pname_idx = labels.index("p1")
    assert rows[pname_idx]["type"] == "folder"
    assert rows[pname_idx]["depth"] == 1
    assert [b["icon"] for b in rows[pname_idx]["buttons"]] == ["xmark", "plus", "play"]
    child = rows[pname_idx + 1]
    assert child["label"] == "a.ogg"
    assert child["depth"] == 2
    assert child["gap"] == 1
    assert child.get("size") == 11
    assert [b["icon"] for b in child["buttons"]] == ["xmark", "play"]


def test_music_content_rows_preset_empty_help():
    lib = _content_lib()
    rows = _content_rows(lib, presets=(), recent_entries=None)
    assert any(
        r["type"] == "help" and r["label"] == "No music presets yet. Save a trigger's song list to fill this."
        for r in rows
    )


def test_music_content_rows_preset_children_do_not_auto_show_on_search():
    # Music preset files only render while the preset is expanded -- no
    # search auto-show (unlike SFX).  A search that matches the preset name
    # keeps the header and the folder row, but not the files.
    lib = _content_lib()
    lib._music.expanded_presets = {"p1": False}
    rows = _content_rows(lib, query="p1", presets=["p1"], recent_entries=None)
    assert any(r["type"] == "folder" and r["label"] == "p1" for r in rows)
    assert not any(r["label"] == "a.ogg" for r in rows)


def test_music_content_rows_external_scan_error(monkeypatch, tmp_path):
    monkeypatch.setattr(renpy.store, "_cue_color_error", "#f00", raising=False)
    lib = _content_lib(user_paths=(), game_paths=())
    missing = _ext_abs(tmp_path / "Nope")
    lib.external_folders = [missing]
    lib._scan_external()
    lib._rebuild_merged()
    rows = _content_rows(lib, recent_entries=None)
    labels = [r["label"] for r in rows]
    assert "Folder not found: {}".format(missing) in labels
    # The missing-folder wrapper still renders so the warning is reachable.
    assert any(r["type"] == "folder" and r["label"] == "Nope/" for r in rows)


def test_music_content_rows_external_empty(tmp_path):
    lib = _content_lib(user_paths=(), game_paths=())
    d1 = tmp_path / "ExtA"
    d1.mkdir()
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    lib._rebuild_merged()
    rows = _content_rows(lib, recent_entries=None)
    labels = [r["label"] for r in rows]
    assert "No music found in: {}".format(_ext_abs(d1)) in labels


def test_music_content_rows_external_only_renders_tree(tmp_path):
    # The no-results guard must treat external sources as populated.
    lib = _content_lib(user_paths=(), game_paths=())
    d1 = tmp_path / "ExtA"
    d1.mkdir()
    (d1 / "song.ogg").write_bytes(b"x")
    lib.external_folders = [_ext_abs(d1)]
    lib._scan_external()
    lib._rebuild_merged()
    rows = _content_rows(lib, recent_entries=None)
    # The wrapper folder and its file both render (external source populated).
    assert any(r["type"] == "folder" and r["label"] == "ExtA/" for r in rows)
    assert any(r["type"] == "file" and r["label"] == "song.ogg" for r in rows)


def test_music_content_rows_per_source_empty_states(monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_error", "#f00", raising=False)
    lib = _content_lib(user_paths=(), game_paths=("bgm/x.ogg",), user_scan="scan broke")
    rows = _content_rows(lib, recent_entries=None)
    labels = [r["label"] for r in rows]
    assert "scan broke" in labels
    assert "No music found in: /music/" in labels
    assert "Add .ogg, .mp3, .wav, .opus files there and click the refresh button." in labels
    # The open-folder action row resolves the explorer variant.
    open_row = next(r for r in rows if r["label"] == "Open Music folder")
    assert open_row["type"] == "action"
    assert open_row["explorer"] == "/music/"
    # The Settings > Data Folder tip follows it, matching the SFX empty state.
    tip_row = next(r for r in rows if r["key"] == "user:settings_tip")
    assert tip_row["plain"] is True
    assert tip_row["label"] == "Add additional folder locations in Settings > Data Folder."
    # scan-error line is plain (unstyled) with the error color.
    scan_row = next(r for r in rows if r["label"] == "scan broke")
    assert scan_row["plain"] is True
    assert scan_row["color"] == "#f00"
    # Game source has files, so no game empty state.
    assert not any(r["label"] == "No music found in game directory." for r in rows)


def test_music_content_rows_no_results_guard():
    lib = _content_lib()
    lib.visible_tree = []
    rows = _content_rows(lib, query="zzz", recent_entries=(), presets=())
    labels = [r["label"] for r in rows]
    assert 'No files found for "zzz".' in labels
    assert not any(r.get("explorer") for r in rows)


def test_music_tree_file_gap_matches_sfx():
    # Music file rows use the same 1px label gap as SFX (was 2).
    lib = _row_lib()
    rows = lib.tree_rows("x.ogg")
    assert rows[1]["gap"] == 1


# ==========================================================================
# Folder-expansion persistence
# ==========================================================================


def test_music_toggle_folder_persists():
    lib, _calls = _make_lib(user_paths=("music/a.ogg",))
    lib.toggle_folder(USER)  # USER is default-open -> collapse -> False
    assert persistent._cue[CUE_PERSIST_MUSIC_TREE_EXPANDED] == {USER: False}


def test_music_restore_overlays_default():
    persistent._cue[CUE_PERSIST_MUSIC_TREE_EXPANDED] = {USER: False}
    lib, _calls = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    # Restore ran inside _make_lib's _rebuild_merged: the untouched GAME root
    # keeps the default-open view while USER is explicitly collapsed.
    assert lib.expanded_folders == {USER: False, GAME: True}


def test_music_restore_expands_subfolder():
    persistent._cue[CUE_PERSIST_MUSIC_TREE_EXPANDED] = {USER + "sub/": True}
    lib, _calls = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"), game_paths=("bgm/x.ogg",))
    assert lib.expanded_folders[USER] is True
    assert lib.expanded_folders[USER + "sub/"] is True


def test_music_content_rows_memo_reuses_rows_until_state_changes():
    """Pure re-evaluations serve the cached row list; input changes rebuild."""
    import cue_lib.audio.tree.music_tree_rows as tree_rows_mod

    lib = _content_lib()
    lib._music._recent = None  # no recent manager (like recent_entries=None)
    builder = tree_rows_mod.CueMusicTreeRows(lib)
    args = ("", ["p1"], None)

    first = builder.content_rows(*args)
    second = builder.content_rows(*args)
    assert second is first  # nothing changed -> cached

    # search query changed -> rebuild
    assert builder.content_rows("p", ["p1"], None) is not first
    # current_file changed -> rebuild
    assert builder.content_rows("", ["p1"], "music/a.ogg") is not first
    # preset expansion toggled in place -> rebuild (value-fingerprinted)
    lib._music.expanded_presets["p1"] = True
    assert builder.content_rows(*args) is not first
