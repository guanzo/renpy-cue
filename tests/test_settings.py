# -*- coding: utf-8 -*-
# Tests for cue_lib.settings -- the Settings-page folder-list actions
# (Settings > Data Folder > SFX Folders / Music Folders).
#
# CueSettings methods read the module-global _cue (monkeypatched per test to a
# fresh make_runtime_cue() graph, matching test_runtime.py's isolation), so
# folder actions persist through the fake db and fan out to the runtime apply
# helpers (monkeypatched here to record -- the tree restructure they drive is
# covered by test_music_library / test_audio_tree).

import pytest

import cue_lib.settings as _settings
from cue_lib.constants import CUE_SHARED_KEY_MUSIC_FOLDERS, CUE_SHARED_KEY_SFX_FOLDERS
from tests.fakes import make_runtime_cue


@pytest.fixture
def cue(monkeypatch):
    """Fresh _cue graph + apply-recorder per test."""
    c = make_runtime_cue(root="/cue_root", audio_dir="/cue_root/audio/")
    monkeypatch.setattr(_settings, "_cue", c)
    c.applied = {"music": [], "sfx": []}
    monkeypatch.setattr(_settings, "_cue_apply_music_folders", lambda folders: c.applied["music"].append(list(folders)))
    monkeypatch.setattr(_settings, "_cue_apply_sfx_folders", lambda folders: c.applied["sfx"].append(list(folders)))
    return c


def _mkfolder(tmp_path, name):
    """Create a real dir and return its normalized absolute path."""
    p = tmp_path / name
    p.mkdir()
    return str(p).replace("\\", "/")


# ==========================================================================
# Hydration
# ==========================================================================


def test_prepare_for_page_hydrates_folder_lists(cue):
    cue.db.shared = {
        CUE_SHARED_KEY_MUSIC_FOLDERS: ["E:/Music/A", "E:/Music/B"],
        CUE_SHARED_KEY_SFX_FOLDERS: ["E:/SFX/A"],
    }
    cue.settings.prepare_for_page()
    assert cue.settings.music_folders == ["E:/Music/A", "E:/Music/B"]
    assert cue.settings.sfx_folders == ["E:/SFX/A"]
    assert cue.settings.music_folder_drafts == ["E:/Music/A", "E:/Music/B"]
    assert cue.settings.sfx_folder_drafts == ["E:/SFX/A"]
    assert cue.settings.music_folder_errors == ["", ""]
    assert cue.settings.sfx_folder_errors == [""]


def test_prepare_for_page_clears_stale_errors(cue):
    cue.settings.music_folder_errors = ["stale"]
    cue.settings.prepare_for_page()
    assert cue.settings.music_folder_errors == []


# ==========================================================================
# Add rows
# ==========================================================================


def test_add_music_folder_appends_empty_row(cue):
    cue.settings.music_folders = ["E:/Music/A"]
    cue.settings.music_folder_drafts = ["E:/Music/A"]
    cue.settings.music_folder_errors = [""]
    cue.settings.add_music_folder()
    assert cue.settings.music_folders == ["E:/Music/A", ""]
    assert cue.settings.music_folder_drafts == ["E:/Music/A", ""]
    assert cue.settings.music_folder_errors == ["", ""]


def test_add_sfx_folder_appends_empty_row(cue):
    cue.settings.add_sfx_folder()
    assert cue.settings.sfx_folders == [""]
    assert cue.settings.sfx_folder_drafts == [""]
    assert cue.settings.sfx_folder_errors == [""]


# ==========================================================================
# Commit -- music
# ==========================================================================


def test_commit_music_folder_valid_persists_and_applies(cue, tmp_path):
    folder = _mkfolder(tmp_path, "my_music")
    cue.settings.add_music_folder()
    cue.settings.music_folder_drafts[0] = folder
    cue.settings.commit_music_folder(0)
    assert cue.settings.music_folder_errors[0] == ""
    assert cue.settings.music_folders == [folder]
    assert cue.settings.music_folder_drafts == [folder]
    assert cue.db.saved[-1] == {CUE_SHARED_KEY_MUSIC_FOLDERS: [folder]}
    assert cue.applied["music"] == [[folder]]


def test_commit_music_folder_missing_dir_errors(cue):
    cue.settings.add_music_folder()
    cue.settings.music_folder_drafts[0] = "/definitely/not/a/real/folder"
    cue.settings.commit_music_folder(0)
    assert cue.settings.music_folder_errors[0] != ""
    # The raw text is kept in the draft so the user can fix it without retyping;
    # the committed list (and thus config) is untouched.
    assert cue.settings.music_folder_drafts[0] == "/definitely/not/a/real/folder"
    assert cue.settings.music_folders == [""]
    assert cue.db.saved == []
    assert cue.applied["music"] == []


def test_commit_music_folder_empty_errors(cue):
    cue.settings.add_music_folder()
    cue.settings.music_folder_drafts[0] = "   "
    cue.settings.commit_music_folder(0)
    assert cue.settings.music_folder_errors[0] != ""
    assert cue.db.saved == []


def test_commit_music_folder_rejects_builtin_dir(cue):
    cue.settings.add_music_folder()
    cue.settings.music_folder_drafts[0] = cue.paths.music_dir
    cue.settings.commit_music_folder(0)
    assert "built in" in cue.settings.music_folder_errors[0]
    assert cue.db.saved == []


def test_commit_music_folder_rejects_duplicate(cue, tmp_path):
    folder = _mkfolder(tmp_path, "my_music")
    cue.settings.music_folders = [folder]
    cue.settings.music_folder_drafts = [folder]
    cue.settings.music_folder_errors = [""]
    cue.settings.add_music_folder()  # appends an empty row
    cue.settings.music_folder_drafts[1] = folder
    cue.settings.commit_music_folder(1)
    assert "already" in cue.settings.music_folder_errors[1]


# ==========================================================================
# Commit -- SFX
# ==========================================================================


def test_commit_sfx_folder_valid_persists_and_applies(cue, tmp_path):
    folder = _mkfolder(tmp_path, "my_sfx")
    cue.settings.add_sfx_folder()
    cue.settings.sfx_folder_drafts[0] = folder
    cue.settings.commit_sfx_folder(0)
    assert cue.settings.sfx_folder_errors[0] == ""
    assert cue.db.saved[-1] == {CUE_SHARED_KEY_SFX_FOLDERS: [folder]}
    assert cue.applied["sfx"] == [[folder]]


def test_commit_sfx_folder_rejects_builtin_dir(cue):
    cue.settings.add_sfx_folder()
    cue.settings.sfx_folder_drafts[0] = cue.paths.audio_dir
    cue.settings.commit_sfx_folder(0)
    assert "built in" in cue.settings.sfx_folder_errors[0]
    assert cue.db.saved == []


# ==========================================================================
# Remove
# ==========================================================================


def test_remove_music_folder_persists_and_applies(cue):
    cue.settings.music_folders = ["E:/Music/A", "E:/Music/B"]
    cue.settings.music_folder_drafts = ["E:/Music/A", "E:/Music/B"]
    cue.settings.music_folder_errors = ["", ""]
    cue.settings.remove_music_folder(0)
    assert cue.settings.music_folders == ["E:/Music/B"]
    assert cue.settings.music_folder_drafts == ["E:/Music/B"]
    assert cue.settings.music_folder_errors == [""]
    assert cue.db.saved[-1] == {CUE_SHARED_KEY_MUSIC_FOLDERS: ["E:/Music/B"]}
    assert cue.applied["music"] == [["E:/Music/B"]]


def test_remove_sfx_folder_persists_and_applies(cue):
    cue.settings.sfx_folders = ["E:/SFX/A", "E:/SFX/B"]
    cue.settings.sfx_folder_drafts = ["E:/SFX/A", "E:/SFX/B"]
    cue.settings.sfx_folder_errors = ["", ""]
    cue.settings.remove_sfx_folder(1)
    assert cue.settings.sfx_folders == ["E:/SFX/A"]
    assert cue.settings.sfx_folder_drafts == ["E:/SFX/A"]
    assert cue.db.saved[-1] == {CUE_SHARED_KEY_SFX_FOLDERS: ["E:/SFX/A"]}
    assert cue.applied["sfx"] == [["E:/SFX/A"]]


# ==========================================================================
# Draft vs committed -- a committed row never drags in a sibling's partial
# text or an empty placeholder.
# ==========================================================================


def test_commit_sibling_drops_uncommitted_draft(cue, tmp_path):
    ok = _mkfolder(tmp_path, "ok")
    cue.settings.add_music_folder()  # row 0
    cue.settings.add_music_folder()  # row 1
    cue.settings.music_folder_drafts[0] = "E:/Music/parti"  # partial, never Enter'd
    cue.settings.music_folder_drafts[1] = ok
    cue.settings.commit_music_folder(1)
    # Only the validated row reaches config and the loader.
    assert cue.db.saved[-1] == {CUE_SHARED_KEY_MUSIC_FOLDERS: [ok]}
    assert cue.applied["music"] == [[ok]]
    # Row 0's draft survives for editing but is not committed.
    assert cue.settings.music_folder_drafts[0] == "E:/Music/parti"
    assert cue.settings.music_folders == ["", ok]


def test_commit_does_not_persist_empty_add_row(cue, tmp_path):
    ok = _mkfolder(tmp_path, "ok")
    cue.settings.add_music_folder()  # untouched empty row
    cue.settings.add_music_folder()  # row committed below
    cue.settings.music_folder_drafts[1] = ok
    cue.settings.commit_music_folder(1)
    assert cue.db.saved[-1] == {CUE_SHARED_KEY_MUSIC_FOLDERS: [ok]}
    assert cue.applied["music"] == [[ok]]
