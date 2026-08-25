# -*- coding: utf-8 -*-
# Tests for cue_lib.audio.music_tree: the combined "Music Library" tree that
# merges the separate My Music / Game Music trees under two synthetic top
# folders for a single UI tree and one shared search bar.  The underlying
# data models stay separate; only the display is combined.
#
# The combined view is built against two fake sub-managers (SimpleNamespace
# with a pre-built tree) and a fake music manager that records dispatch calls,
# so merge / flatten / search / dispatch are all asserted headlessly.

import types

from cue_lib.audio.music import CUE_MUSIC_GAME_TAG, CUE_MUSIC_USER_TAG
from cue_lib.audio.music_tree import CueCombinedMusicTree
from cue_lib.constants import CUE_GAME_MUSIC_FOLDER, CUE_MY_MUSIC_FOLDER, CUE_MUSIC_PREFIX
from cue_lib.util import _cue_build_tree

USER = CUE_MY_MUSIC_FOLDER
GAME = CUE_GAME_MUSIC_FOLDER


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
    """Build (lib, calls, user, game) with recording dispatch + fake trees."""
    calls = []

    def _rec(name):
        # type: (str) -> object
        def _f(*args, **kwargs):
            calls.append((name, args, kwargs))

        return _f

    user = types.SimpleNamespace(tree=_fake_tree(user_paths), files=list(user_paths), scan_error="")
    game = types.SimpleNamespace(tree=_fake_tree(game_paths), files=list(game_paths), scan_error="")
    music = types.SimpleNamespace(
        add_user_song_to_trigger=_rec("add_user_song"),
        add_game_song_to_trigger=_rec("add_game_song"),
        add_user_folder_to_trigger=_rec("add_user_folder"),
        add_game_folder_to_trigger=_rec("add_game_folder"),
        play_untracked=_rec("play_untracked"),
        _resolve_music_path=lambda p: "ABS:" + p,
        _split_ref_tag=_fake_split_tag,
    )
    lib = CueCombinedMusicTree(music, user, game)
    return lib, calls, user, game


def _rows(lib):
    # type: (CueCombinedMusicTree) -> dict
    return {r["full_path"]: r for r in lib.visible_tree}


# ==========================================================================
# Merge + flatten
# ==========================================================================


def test_merged_tree_wraps_both_sources():
    lib, _calls, _user, _game = _make_lib(
        user_paths=("music/a.ogg", "music/sub/b.ogg"), game_paths=("bgm/x.ogg", "music/y.ogg")
    )
    lib.rebuild_tree()
    # Only the two synthetic roots are expanded by default; expand the inner
    # sub-folders so their child rows are rendered.
    lib.toggle_folder(USER + "sub/")
    lib.toggle_folder(GAME + "bgm/")
    lib.toggle_folder(GAME + "music/")
    rows = _rows(lib)
    # User "music/" root is hoisted under the synthetic "My Music/" folder.
    assert rows[USER]["type"] == "folder"
    assert rows[USER]["expanded"] is True
    assert rows[USER + "a.ogg"]["full_path"] == USER + "a.ogg"
    assert rows[USER + "sub/b.ogg"]["full_path"] == USER + "sub/b.ogg"
    # Game tree is wrapped under the synthetic "Game Music/" folder.
    assert rows[GAME]["type"] == "folder"
    assert rows[GAME]["expanded"] is True
    assert rows[GAME + "bgm/x.ogg"]["full_path"] == GAME + "bgm/x.ogg"
    assert rows[GAME + "music/y.ogg"]["full_path"] == GAME + "music/y.ogg"


def test_flatten_renames_music_root_only_in_ui():
    # The data-model "music/" root is renamed to "My Music" in the display --
    # there must be no "My Music/music/" path.
    lib, _calls, _user, _game = _make_lib(user_paths=("music/a.ogg",))
    lib.rebuild_tree()
    rows = _rows(lib)
    assert "My Music/music/" not in rows
    assert rows[USER + "a.ogg"]["depth"] == 1
    # The data model is untouched: the sub-manager still owns its "music/"
    # prefixed files.
    assert lib.user_music.files == ["music/a.ogg"]


def test_merged_tree_skips_empty_source():
    lib, _calls, _user, _game = _make_lib(game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    rows = _rows(lib)
    assert USER not in rows
    assert GAME in rows


def test_merged_tree_empty_when_both_empty():
    lib, _calls, _user, _game = _make_lib()
    lib.rebuild_tree()
    assert lib.tree == []
    assert lib.visible_tree == []


# ==========================================================================
# Search (one query over both sources)
# ==========================================================================


def test_search_filters_across_both_sources():
    lib, _calls, _user, _game = _make_lib(
        user_paths=("music/song.ogg",), game_paths=("bgm/song.ogg", "music/other.ogg")
    )
    lib.rebuild_tree()
    lib.search_query = "bgm"
    lib.rebuild_tree()
    rows = _rows(lib)
    assert GAME + "bgm/song.ogg" in rows
    assert USER + "song.ogg" not in rows
    # Matching folders are force-expanded during a search.
    assert rows[GAME + "bgm/"]["expanded"] is True


def test_search_matches_both_sources():
    lib, _calls, _user, _game = _make_lib(user_paths=("music/song.ogg",), game_paths=("bgm/song.ogg",))
    lib.rebuild_tree()
    lib.search_query = "song"
    lib.rebuild_tree()
    rows = _rows(lib)
    assert USER + "song.ogg" in rows
    assert GAME + "bgm/song.ogg" in rows


def test_search_caps_rows():
    user_paths = tuple("music/song{:02d}.ogg".format(i) for i in range(120))
    lib, _calls, _user, _game = _make_lib(user_paths=user_paths)
    lib.rebuild_tree()
    lib.search_query = "song"
    lib.rebuild_tree()
    # 120 files + 1 "My Music/" folder row = 121, capped at 100.
    assert lib.search_truncated == 21
    assert len(lib.visible_tree) == 100


def test_clear_search_restores_collapsed_tree():
    lib, _calls, _user, _game = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"))
    lib.rebuild_tree()
    lib.search_query = "b"
    lib.rebuild_tree()
    assert USER + "sub/b.ogg" in _rows(lib)
    assert USER + "a.ogg" not in _rows(lib)
    lib.clear_search()
    assert lib.search_query == ""
    rows = _rows(lib)
    assert USER + "a.ogg" in rows
    # Non-root folders are collapsed again once the search is cleared.
    assert rows[USER + "sub/"]["expanded"] is False


# ==========================================================================
# Expansion state
# ==========================================================================


def test_toggle_folder_collapses_and_expands():
    lib, _calls, _user, _game = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"))
    lib.rebuild_tree()
    # A sub-folder starts collapsed; the first toggle expands it, the second
    # collapses it.
    lib.toggle_folder(USER + "sub/")
    assert _rows(lib)[USER + "sub/"]["expanded"] is True
    assert USER + "sub/b.ogg" in _rows(lib)
    lib.toggle_folder(USER + "sub/")
    rows = _rows(lib)
    assert rows[USER + "sub/"]["expanded"] is False
    assert USER + "sub/b.ogg" not in rows


def test_toggle_folder_noop_during_search():
    lib, _calls, _user, _game = _make_lib(user_paths=("music/a.ogg", "music/sub/b.ogg"))
    lib.rebuild_tree()
    lib.search_query = "b"
    lib.rebuild_tree()
    lib.toggle_folder(USER + "sub/")
    assert _rows(lib)[USER + "sub/"]["expanded"] is True


# ==========================================================================
# maybe_rebuild / rescan detection
# ==========================================================================


def test_maybe_rebuild_skips_when_unchanged():
    lib, _calls, _user, _game = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    before = lib.visible_tree
    lib.maybe_rebuild()
    assert lib.visible_tree == before


def test_maybe_rebuild_skips_rebuild_after_rebuild_tree(monkeypatch):
    # A fresh rebuild_tree stamps the source-tree ids, so the next
    # maybe_rebuild must not re-merge (the tick loop calls it constantly).
    lib, _calls, _user, _game = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    seen = []
    monkeypatch.setattr(lib, "rebuild_tree", lambda: seen.append(1))
    lib.maybe_rebuild()
    assert seen == []


def test_maybe_rebuild_after_rescan():
    lib, _calls, user, _game = _make_lib(user_paths=("music/a.ogg",), game_paths=("bgm/x.ogg",))
    lib.rebuild_tree()
    assert USER + "new.ogg" not in _rows(lib)
    # A re-scan replaces the sub-manager's tree object.
    user.tree = _fake_tree(("music/a.ogg", "music/new.ogg"))
    lib.maybe_rebuild()
    assert USER + "new.ogg" in _rows(lib)


# ==========================================================================
# has_files on combined rows (UI shows "+" on folders that directly contain
# files; the synthetic Game Music root and nested-only folders get none)
# ==========================================================================


def test_folder_rows_has_files():
    lib, _calls, _user, _game = _make_lib(
        user_paths=("music/a.ogg", "music/sub/deep.ogg"), game_paths=("bgm/ost/y.ogg",)
    )
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


def test_add_song_user_routes_flattened_path():
    lib, calls, _user, _game = _make_lib(user_paths=("music/a.ogg",))
    lib.add_song_to_trigger(USER + "a.ogg")
    assert calls == [("add_user_song", (CUE_MUSIC_PREFIX + "a.ogg",), {"record": True})]


def test_add_song_user_nested_folder():
    lib, calls, _user, _game = _make_lib(user_paths=("music/folder/song.ogg",))
    lib.add_song_to_trigger(USER + "folder/song.ogg")
    assert calls == [("add_user_song", ("music/folder/song.ogg",), {"record": True})]


def test_add_song_game_routes():
    lib, calls, _user, _game = _make_lib(game_paths=("bgm/x.ogg",))
    lib.add_song_to_trigger(GAME + "bgm/x.ogg")
    assert calls == [("add_game_song", ("bgm/x.ogg",), {"record": True})]


def test_add_folder_user_routes():
    lib, calls, _user, _game = _make_lib(user_paths=("music/sub/b.ogg",))
    lib.add_folder_to_trigger(USER + "sub/")
    assert calls == [("add_user_folder", ("music/sub/",), {"record": True})]


def test_add_folder_user_root_adds_all():
    lib, calls, _user, _game = _make_lib(user_paths=("music/a.ogg",))
    lib.add_folder_to_trigger(USER)
    assert calls == [("add_user_folder", ("music/",), {"record": True})]


def test_add_folder_game_routes():
    lib, calls, _user, _game = _make_lib(game_paths=("bgm/x.ogg",))
    lib.add_folder_to_trigger(GAME + "bgm/")
    assert calls == [("add_game_folder", ("bgm/",), {"record": True})]


def test_add_folder_game_synthetic_root_noop():
    lib, calls, _user, _game = _make_lib(game_paths=("bgm/x.ogg",))
    lib.add_folder_to_trigger(GAME)
    assert calls == []


def test_add_song_record_false_passes_through():
    lib, calls, _user, _game = _make_lib(user_paths=("music/a.ogg",))
    lib.add_song_to_trigger(USER + "a.ogg", record=False)
    assert calls == [("add_user_song", (CUE_MUSIC_PREFIX + "a.ogg",), {"record": False})]


def test_add_folder_record_false_passes_through():
    lib, calls, _user, _game = _make_lib(user_paths=("music/sub/b.ogg",))
    lib.add_folder_to_trigger(USER + "sub/", record=False)
    assert calls == [("add_user_folder", ("music/sub/",), {"record": False})]


def test_preview_user_resolves_music_path():
    lib, calls, _user, _game = _make_lib(user_paths=("music/a.ogg",))
    lib.preview(USER + "a.ogg", volume=0.5)
    assert calls == [("play_untracked", ("ABS:music/a.ogg",), {"volume": 0.5})]


def test_preview_game_passes_path():
    lib, calls, _user, _game = _make_lib(game_paths=("bgm/x.ogg",))
    lib.preview(GAME + "bgm/x.ogg")
    assert calls == [("play_untracked", ("bgm/x.ogg",), {"volume": 1.0})]


# ==========================================================================
# stored-ref -> display-path conversion (ref_display_path)
# ==========================================================================


def test_ref_display_path_user():
    lib, _calls, _user, _game = _make_lib()
    assert lib.ref_display_path(CUE_MUSIC_USER_TAG + "music/song.ogg") == USER + "song.ogg"


def test_ref_display_path_user_folder():
    lib, _calls, _user, _game = _make_lib()
    assert lib.ref_display_path(CUE_MUSIC_USER_TAG + "music/sub/") == USER + "sub/"


def test_ref_display_path_game():
    lib, _calls, _user, _game = _make_lib()
    assert lib.ref_display_path(CUE_MUSIC_GAME_TAG + "bgm/x.ogg") == GAME + "bgm/x.ogg"


def test_ref_display_path_game_folder():
    lib, _calls, _user, _game = _make_lib()
    assert lib.ref_display_path(CUE_MUSIC_GAME_TAG + "bgm/") == GAME + "bgm/"


def test_ref_display_path_untagged_treated_as_user():
    lib, _calls, _user, _game = _make_lib()
    assert lib.ref_display_path("music/song.ogg") == USER + "song.ogg"


def test_ref_display_path_never_leaks_data_prefix():
    # Every stored ref renders under a synthetic My Music/ or Game Music/
    # root -- the data-model "music/" prefix never appears in the UI.
    lib, _calls, _user, _game = _make_lib()
    refs = (
        CUE_MUSIC_USER_TAG + "music/a.ogg",
        CUE_MUSIC_USER_TAG + "music/sub/",
        CUE_MUSIC_GAME_TAG + "bgm/x.ogg",
        CUE_MUSIC_GAME_TAG + "bgm/",
    )
    for ref in refs:
        disp = lib.ref_display_path(ref)
        assert not disp.startswith(CUE_MUSIC_PREFIX)
        assert disp.startswith(USER) or disp.startswith(GAME)


# ==========================================================================
# row_buttons (music tree)
# ==========================================================================


def _row_lib(sel_label="", selected_key=None, has_files=True):
    # type: (str, object, bool) -> CueCombinedMusicTree
    """Lib with a two-row visible_tree (folder + file) and a fake music mgr."""
    user = types.SimpleNamespace(tree=[], files=[], scan_error="")
    game = types.SimpleNamespace(tree=[], files=[], scan_error="")
    music = types.SimpleNamespace(selected_trigger_label=lambda: sel_label, selected_key=selected_key)
    lib = CueCombinedMusicTree(music, user, game)
    lib.visible_tree = [
        {
            "type": "folder",
            "name": "My Music/",
            "full_path": "My Music/",
            "depth": 0,
            "expanded": True,
            "has_files": has_files,
        },
        {"type": "file", "name": "a.ogg", "full_path": "My Music/a.ogg", "depth": 1},
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
    assert folder["buttons"][0]["action"]._args[1] == "My Music/"
    assert [b["icon"] for b in file_row["buttons"]] == ["plus", "play"]
    assert file_row["buttons"][0]["tt"] == "Add song to S1"
    assert file_row["buttons"][0]["action"]._args[0] == lib.add_song_to_trigger
    assert file_row["buttons"][1]["tt"] == "Play song"
    assert file_row["buttons"][1]["action"]._args[0] == lib.preview
    assert file_row["gap"] == 2  # music gap override


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
    assert rows3[1]["buttons"][0]["tt"] == "Add song to a new trigger for the current scene"


def test_music_folder_without_files_has_no_buttons():
    lib = _row_lib(has_files=False)
    rows = lib.tree_rows("")
    assert rows[0]["buttons"] == []
