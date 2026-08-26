# -*- coding: utf-8 -*-
# Tests for CueRecentManager -- the "Recently Used" list backing the SFX
# library row (and, later, the music library).
#
# The manager is pure list + persistence logic.  It takes a persistent key
# and a keep callable (existence check for prune), so tests drive it with a
# plain dict persistent and a lambda -- no Ren'Py or manager wiring needed.

import pytest

from renpy.store import persistent

from cue_lib.audio.music import CUE_MUSIC_GAME_TAG, CUE_MUSIC_USER_TAG
from cue_lib.audio.recent import CUE_RECENT_MAX_ENTRIES, CueRecentManager, _cue_keep_music, _cue_keep_sfx


@pytest.fixture(autouse=True)
def _clean_persistent(monkeypatch):
    """Fresh persistent._cue for every test in this module."""
    monkeypatch.setattr(persistent, "_cue", {})


def _all_keep(kind, ref):
    return True


# ---------------------------------------------------------------------------
# record: dedup, MRU order, cap (no auto-expand)
# ---------------------------------------------------------------------------


def test_record_moves_existing_entry_to_front():
    m = CueRecentManager("recent_entries", _all_keep)
    m.record("file", "a.ogg")
    m.record("folder", "sfx/")
    m.record("file", "a.ogg")
    assert [e["type"] for e in m.entries()] == ["file", "folder"]
    assert [e["ref"] for e in m.entries()] == ["a.ogg", "sfx/"]


def test_record_keeps_same_ref_different_kind():
    m = CueRecentManager("recent_entries", _all_keep)
    m.record("file", "a.ogg")
    m.record("folder", "a.ogg")
    assert len(m.entries()) == 2


def test_record_caps_at_max_entries():
    m = CueRecentManager("recent_entries", _all_keep)
    for i in range(CUE_RECENT_MAX_ENTRIES + 3):
        m.record("file", "f{}.ogg".format(i))
    assert len(m.entries()) == CUE_RECENT_MAX_ENTRIES
    assert m.entries()[0]["ref"] == "f{}.ogg".format(CUE_RECENT_MAX_ENTRIES + 2)


def test_record_does_not_expand_list():
    m = CueRecentManager("recent_entries", _all_keep)
    m.record("file", "a.ogg")
    assert m.expanded is False


# ---------------------------------------------------------------------------
# expand-state toggles (session-local, never persisted)
# ---------------------------------------------------------------------------


def test_toggle_flips_expanded():
    m = CueRecentManager("recent_entries", _all_keep)
    m.expanded = True
    m.toggle()
    assert m.expanded is False
    m.toggle()
    assert m.expanded is True


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_record_writes_to_persistent():
    m = CueRecentManager("recent_entries", _all_keep)
    m.record("file", "a.ogg")
    assert persistent._cue["recent_entries"] == [{"type": "file", "ref": "a.ogg"}]


def test_load_roundtrips_entries_without_expanding():
    m = CueRecentManager("recent_entries", _all_keep)
    m.record("preset", "Hurt")
    m2 = CueRecentManager("recent_entries", _all_keep)
    m2.load()
    assert [e["ref"] for e in m2.entries()] == ["Hurt"]
    assert m2.expanded is False


def test_load_no_entries_when_key_absent():
    m = CueRecentManager("recent_entries", _all_keep)
    m.load()
    assert m.entries() == []
    assert m.expanded is False


def test_load_handles_none_persistent(monkeypatch):
    monkeypatch.setattr(persistent, "_cue", None)
    m = CueRecentManager("recent_entries", _all_keep)
    m.load()
    assert m.entries() == []


def test_load_prunes_stale_entries():
    m = CueRecentManager("recent_entries", lambda kind, ref: ref == "keep.ogg")
    m.record("file", "gone.ogg")
    m.record("file", "keep.ogg")
    m2 = CueRecentManager("recent_entries", lambda kind, ref: ref == "keep.ogg")
    m2.load()
    assert [e["ref"] for e in m2.entries()] == ["keep.ogg"]
    assert m2.expanded is False


def test_load_collapses_when_all_stale():
    m = CueRecentManager("recent_entries", lambda kind, ref: False)
    m.record("file", "a.ogg")
    m2 = CueRecentManager("recent_entries", lambda kind, ref: False)
    m2.load()
    assert m2.entries() == []
    assert m2.expanded is False


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def test_prune_drops_stale_entries():
    m = CueRecentManager("recent_entries", lambda kind, ref: ref in ("keep.ogg", "sfx/keep/"))
    m.record("file", "gone.ogg")
    m.record("file", "keep.ogg")
    m.record("folder", "sfx/keep/")
    m.expanded = True
    m.prune()
    assert [e["ref"] for e in m.entries()] == ["sfx/keep/", "keep.ogg"]
    assert m.expanded is True


def test_prune_empty_when_all_stale_collapses():
    m = CueRecentManager("recent_entries", lambda kind, ref: False)
    m.expanded = True
    m.record("file", "a.ogg")
    m.prune()
    assert m.entries() == []
    assert m.expanded is False


def test_prune_writes_back_to_persistent():
    m = CueRecentManager("recent_entries", lambda kind, ref: ref == "keep.ogg")
    m.record("file", "gone.ogg")
    m.record("file", "keep.ogg")
    m.prune()
    assert persistent._cue["recent_entries"] == [{"type": "file", "ref": "keep.ogg"}]


# ---------------------------------------------------------------------------
# SFX existence check (_cue_keep_sfx)
# ---------------------------------------------------------------------------


def test_keep_sfx_file_folder_preset():
    files = ["sfx/hit.ogg", "sfx/amb/loop.ogg", "music/track.ogg"]
    presets = ["Hurt", "Ambience"]
    assert _cue_keep_sfx("file", "sfx/hit.ogg", files, presets)
    assert not _cue_keep_sfx("file", "sfx/miss.ogg", files, presets)
    assert _cue_keep_sfx("folder", "sfx/", files, presets)
    assert _cue_keep_sfx("folder", "sfx/amb/", files, presets)
    assert not _cue_keep_sfx("folder", "nope/", files, presets)
    assert _cue_keep_sfx("preset", "Hurt", files, presets)
    assert not _cue_keep_sfx("preset", "Nope", files, presets)
    assert not _cue_keep_sfx("bogus", "x", files, presets)


# ---------------------------------------------------------------------------
# Music existence check (_cue_keep_music)
# ---------------------------------------------------------------------------


def _music_lib(user_files, game_files, external_files=()):
    # type: (list, list, tuple) -> object
    """Library stand-in exposing the per-source files _cue_keep_music reads."""
    return type(
        "FakeMusicLib",
        (object,),
        {"user_files": list(user_files), "game_files": list(game_files), "external_files": list(external_files)},
    )()


def test_keep_music_file_user():
    lib = _music_lib(["music/song.ogg"], [])
    assert _cue_keep_music("file", CUE_MUSIC_USER_TAG + "music/song.ogg", lib)
    assert not _cue_keep_music("file", CUE_MUSIC_USER_TAG + "music/miss.ogg", lib)


def test_keep_music_file_game():
    lib = _music_lib([], ["bgm/x.ogg"])
    assert _cue_keep_music("file", CUE_MUSIC_GAME_TAG + "bgm/x.ogg", lib)
    assert not _cue_keep_music("file", CUE_MUSIC_GAME_TAG + "bgm/nope.ogg", lib)


def test_keep_music_folder_user():
    lib = _music_lib(["music/sub/a.ogg"], [])
    assert _cue_keep_music("folder", CUE_MUSIC_USER_TAG + "music/sub/", lib)
    assert not _cue_keep_music("folder", CUE_MUSIC_USER_TAG + "music/other/", lib)


def test_keep_music_folder_game():
    lib = _music_lib([], ["bgm/loop/a.ogg"])
    assert _cue_keep_music("folder", CUE_MUSIC_GAME_TAG + "bgm/", lib)
    assert not _cue_keep_music("folder", CUE_MUSIC_GAME_TAG + "ost/", lib)


def test_keep_music_untagged_checks_both():
    lib = _music_lib(["music/a.ogg"], ["music/b.ogg"])
    assert _cue_keep_music("file", "music/a.ogg", lib)
    assert _cue_keep_music("file", "music/b.ogg", lib)
    assert not _cue_keep_music("file", "music/c.ogg", lib)


def test_keep_music_external_file():
    # External refs are bare absolute paths (untagged).
    lib = _music_lib([], [], external_files=["E:/Music/artist/song.ogg"])
    assert _cue_keep_music("file", "E:/Music/artist/song.ogg", lib)
    assert not _cue_keep_music("file", "E:/Music/artist/miss.ogg", lib)


def test_keep_music_external_folder():
    lib = _music_lib([], [], external_files=["E:/Music/artist/a.ogg"])
    assert _cue_keep_music("folder", "E:/Music/artist/", lib)
    assert not _cue_keep_music("folder", "E:/Music/other/", lib)


def test_keep_music_unknown_kind_never_kept():
    lib = _music_lib(["music/a.ogg"], [])
    assert not _cue_keep_music("preset", CUE_MUSIC_USER_TAG + "music/a.ogg", lib)


# ---------------------------------------------------------------------------
# expand-state persistence (toggle / load)
# ---------------------------------------------------------------------------


def test_toggle_persists_expanded():
    m = CueRecentManager("recent_entries", _all_keep)
    m.toggle()
    assert m.expanded is True
    assert persistent._cue["recent_entries_expanded"] is True
    m.toggle()
    assert m.expanded is False
    assert persistent._cue["recent_entries_expanded"] is False


def test_load_restores_expanded():
    persistent._cue["recent_entries"] = [{"type": "file", "ref": "a.ogg"}]
    persistent._cue["recent_entries_expanded"] = True
    m = CueRecentManager("recent_entries", _all_keep)
    m.load()
    assert m.expanded is True


def test_load_defaults_collapsed():
    m = CueRecentManager("recent_entries", _all_keep)
    m.load()
    assert m.expanded is False
