# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.dialogs -- the preset/video-preset/confirm dialog
# state classes and the preset confirm/apply helpers.

import os
import types

import pytest

import cue_lib.ui.dialogs as _dlg
from cue_lib.constants import CueImportCategory, CueImportMatch
from cue_lib.ui.dialogs import (
    CueConfirmDialog,
    CueDialogs,
    CueMergeDialog,
    CueMusicPresetDialog,
    CuePoolPresetDialog,
    CueVideoPresetDialog,
    _cue_confirm_delete_music_preset,
    _cue_confirm_delete_preset,
    _cue_confirm_delete_video_preset,
    _cue_maybe_apply_video_preset,
)


@pytest.fixture
def ui_cue(monkeypatch):
    """_cue stand-in with a recording markers surface + real confirm dialog."""
    calls = {}

    def _rec(name):
        def _record(*args, **kwargs):
            calls.setdefault(name, []).append((args, kwargs))

        return _record

    markers = types.SimpleNamespace(
        get=lambda key: None,
        _detach_pool=_rec("detach_pool"),
        create_preset=_rec("create_preset"),
        create_video_preset=_rec("create_video_preset"),
        delete_preset=_rec("delete_preset"),
        delete_video_preset=_rec("delete_video_preset"),
        get_video_preset=_rec("get_video_preset"),
        video_preset_out_of_range=lambda name: 0,
        apply_video_preset=_rec("apply_video_preset"),
    )
    dialogs = CueDialogs()
    dialogs.confirm = CueConfirmDialog()
    cue = types.SimpleNamespace(markers=markers, dialogs=dialogs, current_file="", calls=calls)
    cue.music = types.SimpleNamespace(
        songs_for_trigger=lambda key: [],
        create_preset=_rec("music_create_preset"),
        delete_preset=_rec("music_delete_preset"),
    )
    cue.vid_manager = types.SimpleNamespace(get_duration=lambda: 12.5)
    monkeypatch.setattr(_dlg, "_cue", cue)
    return cue


# ==========================================================================
# CuePoolPresetDialog
# ==========================================================================


def test_preset_open_missing_entry_noop(ui_cue):
    d = CuePoolPresetDialog()
    d.open("v_scene.ogv", 0)
    assert d.marker_key is None
    assert ui_cue.dialogs.active_dialog is None


def test_preset_open_pool_out_of_range_noop(ui_cue):
    ui_cue.markers.get = lambda key: {"pools": [{"files": []}]}
    d = CuePoolPresetDialog()
    d.open("v_scene.ogv", 1)
    assert d.marker_key is None
    assert ui_cue.dialogs.active_dialog is None


def test_preset_open_happy(ui_cue):
    ui_cue.markers.get = lambda key: {"pools": [{"files": ["a.ogg"]}]}
    d = CuePoolPresetDialog()
    d.open("v_scene.ogv", 0)
    assert d.marker_key == "v_scene.ogv"
    assert d.pool_idx == 0
    assert d.name == ""
    assert ui_cue.calls["detach_pool"] == [(("v_scene.ogv", 0), {})]
    assert isinstance(ui_cue.dialogs.active_dialog, CuePoolPresetDialog)


def test_preset_commit_empty_name_no_create(ui_cue):
    d = CuePoolPresetDialog()
    d.marker_key = "v_scene.ogv"
    d.pool_idx = 0
    d.name = "   "
    d.commit()
    assert "create_preset" not in ui_cue.calls
    assert d.marker_key is None
    assert ui_cue.dialogs.active_dialog is None


def test_preset_commit_no_trigger_no_create(ui_cue):
    d = CuePoolPresetDialog()
    d.name = "Foo"
    d.commit()
    assert "create_preset" not in ui_cue.calls
    assert ui_cue.dialogs.active_dialog is None


def test_preset_commit_happy(ui_cue):
    ui_cue.markers.get = lambda key: {"pools": [{"files": ["a.ogg"]}]}
    d = CuePoolPresetDialog()
    d.marker_key = "v_scene.ogv"
    d.pool_idx = 0
    d.name = "Tense"
    d.commit()
    assert ui_cue.calls["create_preset"] == [(("Tense", {"files": ["a.ogg"]}), {})]
    assert d.marker_key is None
    assert ui_cue.dialogs.active_dialog is None


def test_preset_cancel(ui_cue):
    d = CuePoolPresetDialog()
    d.marker_key = "v_scene.ogv"
    d.cancel()
    assert d.marker_key is None
    assert ui_cue.dialogs.active_dialog is None


# ==========================================================================
# CueMusicPresetDialog
# ==========================================================================


def test_music_preset_open_empty_songs_noop(ui_cue):
    d = CueMusicPresetDialog()
    d.open("i_scene.ogv")
    assert d.music_key is None
    assert ui_cue.dialogs.active_dialog is None


def test_music_preset_open_happy(ui_cue):
    ui_cue.music.songs_for_trigger = lambda key: ["u:music/a.ogg", "u:music/b.ogg"]
    d = CueMusicPresetDialog()
    d.open("i_scene.ogv")
    assert d.music_key == "i_scene.ogv"
    assert d.songs == ["u:music/a.ogg", "u:music/b.ogg"]
    assert d.name == ""
    assert isinstance(ui_cue.dialogs.active_dialog, CueMusicPresetDialog)


def test_music_preset_commit_happy(ui_cue):
    d = CueMusicPresetDialog()
    d.music_key = "i_scene.ogv"
    d.songs = ["u:music/a.ogg"]
    d.name = "Tense"
    d.commit()
    assert ui_cue.calls["music_create_preset"] == [(("Tense", ["u:music/a.ogg"]), {})]
    assert d.music_key is None
    assert d.songs == []
    assert ui_cue.dialogs.active_dialog is None


def test_music_preset_commit_no_trigger_no_create(ui_cue):
    d = CueMusicPresetDialog()
    d.songs = ["u:music/a.ogg"]
    d.name = "Tense"
    d.commit()
    assert "music_create_preset" not in ui_cue.calls
    assert ui_cue.dialogs.active_dialog is None


def test_music_preset_commit_empty_name_no_create(ui_cue):
    d = CueMusicPresetDialog()
    d.music_key = "i_scene.ogv"
    d.songs = ["u:music/a.ogg"]
    d.name = "   "
    d.commit()
    assert "music_create_preset" not in ui_cue.calls
    assert d.music_key is None
    assert ui_cue.dialogs.active_dialog is None


def test_music_preset_cancel(ui_cue):
    d = CueMusicPresetDialog()
    d.music_key = "i_scene.ogv"
    d.songs = ["u:music/a.ogg"]
    d.cancel()
    assert d.music_key is None
    assert d.songs == []
    assert ui_cue.dialogs.active_dialog is None


# ==========================================================================
# CueVideoPresetDialog
# ==========================================================================


def test_video_preset_open_no_current_file(ui_cue):
    d = CueVideoPresetDialog()
    d.open()
    assert ui_cue.dialogs.active_dialog is None


def test_video_preset_open_missing_entry(ui_cue):
    ui_cue.current_file = "v_scene.ogv"
    d = CueVideoPresetDialog()
    d.open()
    assert ui_cue.dialogs.active_dialog is None


def test_video_preset_open_no_pools(ui_cue):
    ui_cue.current_file = "v_scene.ogv"
    ui_cue.markers.get = lambda key: {"pools": []}
    d = CueVideoPresetDialog()
    d.open()
    assert ui_cue.dialogs.active_dialog is None


def test_video_preset_open_happy(ui_cue):
    ui_cue.current_file = "v_scene.ogv"
    ui_cue.markers.get = lambda key: {"pools": [{"time": 1.0}]}
    d = CueVideoPresetDialog()
    d.open()
    assert d.name == ""
    assert isinstance(ui_cue.dialogs.active_dialog, CueVideoPresetDialog)


def test_video_preset_commit_empty_name(ui_cue):
    d = CueVideoPresetDialog()
    d.name = ""
    d.commit()
    assert "create_video_preset" not in ui_cue.calls
    assert ui_cue.dialogs.active_dialog is None


def test_video_preset_commit_happy(ui_cue):
    ui_cue.current_file = "v_scene.ogv"
    ui_cue.markers.get = lambda key: {"pools": [{"time": 1.0}]}
    d = CueVideoPresetDialog()
    d.name = "Slow"
    d.commit()
    assert ui_cue.calls["create_video_preset"] == [(("Slow", {"pools": [{"time": 1.0}]}), {})]
    assert ui_cue.dialogs.active_dialog is None


def test_video_preset_cancel(ui_cue):
    d = CueVideoPresetDialog()
    d.cancel()
    assert ui_cue.dialogs.active_dialog is None


# ==========================================================================
# CueConfirmDialog
# ==========================================================================


def test_confirm_show_hide(ui_cue):
    d = CueConfirmDialog()
    d.show("Sure?", lambda: None)
    assert d.message == "Sure?"
    assert callable(d.on_confirm)
    assert isinstance(ui_cue.dialogs.active_dialog, CueConfirmDialog)
    d.hide()
    assert d.message == ""
    assert d.on_confirm is None
    assert ui_cue.dialogs.active_dialog is None


def test_confirm_show_or_run_shows_without_shift(ui_cue, monkeypatch):
    monkeypatch.setattr(_dlg, "_cue_shift_held", lambda: False)
    d = CueConfirmDialog()
    d.show_or_run("Sure?", lambda: None)
    assert d.message == "Sure?"
    assert callable(d.on_confirm)
    assert isinstance(ui_cue.dialogs.active_dialog, CueConfirmDialog)


def test_confirm_show_or_run_skips_with_shift(ui_cue, monkeypatch):
    monkeypatch.setattr(_dlg, "_cue_shift_held", lambda: True)
    d = CueConfirmDialog()
    calls = []
    d.show_or_run("Sure?", lambda: calls.append(1))
    assert calls == [1]
    assert d.message == ""
    assert d.on_confirm is None
    assert ui_cue.dialogs.active_dialog is None


# ==========================================================================
# confirm-delete / apply helpers
# ==========================================================================


def test_confirm_delete_preset(ui_cue):
    _cue_confirm_delete_preset("Foo")
    assert ui_cue.dialogs.confirm.message == "Delete preset 'Foo'?"
    # on_confirm is the Function() wrapper -- callable, not run yet.
    assert callable(ui_cue.dialogs.confirm.on_confirm)
    assert "delete_preset" not in ui_cue.calls
    assert isinstance(ui_cue.dialogs.active_dialog, CueConfirmDialog)


def test_confirm_delete_video_preset(ui_cue):
    _cue_confirm_delete_video_preset("Bar")
    assert ui_cue.dialogs.confirm.message == "Delete video preset 'Bar'?"
    assert "delete_video_preset" not in ui_cue.calls
    assert isinstance(ui_cue.dialogs.active_dialog, CueConfirmDialog)


def test_confirm_delete_music_preset(ui_cue):
    _cue_confirm_delete_music_preset("Foo")
    assert ui_cue.dialogs.confirm.message == "Delete music preset 'Foo'?"
    assert "music_delete_preset" not in ui_cue.calls
    assert isinstance(ui_cue.dialogs.active_dialog, CueConfirmDialog)


def test_confirm_delete_preset_skips_with_shift(ui_cue, monkeypatch):
    monkeypatch.setattr(_dlg, "_cue_shift_held", lambda: True)
    _cue_confirm_delete_preset("Foo")
    assert ui_cue.calls["delete_preset"] == [(("Foo",), {})]
    assert ui_cue.dialogs.active_dialog is None


def test_confirm_delete_video_preset_skips_with_shift(ui_cue, monkeypatch):
    monkeypatch.setattr(_dlg, "_cue_shift_held", lambda: True)
    _cue_confirm_delete_video_preset("Bar")
    assert ui_cue.calls["delete_video_preset"] == [(("Bar",), {})]
    assert ui_cue.dialogs.active_dialog is None


def test_confirm_delete_music_preset_skips_with_shift(ui_cue, monkeypatch):
    monkeypatch.setattr(_dlg, "_cue_shift_held", lambda: True)
    _cue_confirm_delete_music_preset("Foo")
    assert ui_cue.calls["music_delete_preset"] == [(("Foo",), {})]
    assert ui_cue.dialogs.active_dialog is None


def test_maybe_apply_video_preset_in_range(ui_cue):
    _cue_maybe_apply_video_preset("Preset")
    assert ui_cue.calls["apply_video_preset"] == [(("Preset",), {})]
    assert ui_cue.dialogs.active_dialog is None


def test_maybe_apply_video_preset_out_of_range(ui_cue):
    ui_cue.markers.video_preset_out_of_range = lambda name: 3
    ui_cue.markers.get_video_preset = lambda name: {"pools": [1, 2, 3, 4]}
    _cue_maybe_apply_video_preset("Preset")
    # out of range -> confirm dialog, message shows counts + duration.
    assert "3 of 4 marker(s)" in ui_cue.dialogs.confirm.message
    assert "12.5s" in ui_cue.dialogs.confirm.message
    assert "apply_video_preset" not in ui_cue.calls
    assert isinstance(ui_cue.dialogs.active_dialog, CueConfirmDialog)


def test_maybe_apply_video_preset_out_of_range_no_preset(ui_cue):
    ui_cue.markers.video_preset_out_of_range = lambda name: 2
    ui_cue.markers.get_video_preset = lambda name: None
    _cue_maybe_apply_video_preset("Ghost")
    assert "2 of 0 marker(s)" in ui_cue.dialogs.confirm.message
    assert "apply_video_preset" not in ui_cue.calls


# ==========================================================================
# CueMergeDialog
# ==========================================================================

GAME_ID = "test_game"


def _merge_entry(contents, valid=True, match=CueImportMatch.AUTO, missing=None):
    return {
        "imp": "pack",
        "zip": "pack.zip",
        "name": "My pack",
        "author": "",
        "description": "",
        "game_id": GAME_ID,
        "contents": contents,
        "match": match,
        "match_reason": "",
        "valid": valid,
        "missing": missing or [],
        "error": "",
    }


@pytest.fixture
def merge_env(cue_env, monkeypatch):
    """Fake imports surface: import_for returns _merge_entry, merge_confirm
    records its args.  original_root is the real cue_env root so summary() can
    compute overwrites against real files.  _cue.dialogs is a real CueDialogs
    so open/commit/cancel flip the active_dialog gate."""
    calls = []
    original_root = cue_env.paths.original_root

    def _merge_confirm(imp, checked):
        calls.append((imp, checked))

    dialogs = CueDialogs()
    imp = types.SimpleNamespace(
        _paths=cue_env.paths,
        import_for=lambda imp: _merge_entry([]),
        folder_files=lambda _imp_key: imp.import_for(_imp_key)["contents"],
        merge_confirm=_merge_confirm,
    )
    monkeypatch.setattr(_dlg, "_cue", types.SimpleNamespace(dialogs=dialogs))
    return imp, calls, original_root, dialogs


def _write(original_root, rel, content):
    path = os.path.join(original_root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)


def test_merge_open_happy(merge_env):
    imp, _calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg", "audio/b.ogg", "music/m.ogg"])
    d = CueMergeDialog(imp)

    d.open("pack")

    assert d.imp == "pack"
    assert d.counts == {CueImportCategory.SFX: 2, CueImportCategory.MUSIC: 1}
    assert d.is_checked(CueImportCategory.SFX) is True
    assert d.is_category_enabled(CueImportCategory.SFX) is True
    assert d.is_category_enabled(CueImportCategory.MARKERS) is False
    assert d.total_files == 3
    assert isinstance(dialogs.active_dialog, CueMergeDialog)


def test_merge_open_invalid_noop(merge_env):
    imp, _calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg"], valid=False)
    d = CueMergeDialog(imp)

    d.open("pack")

    assert d.imp is None
    assert dialogs.active_dialog is None


def test_merge_open_mismatch_noop(merge_env):
    imp, _calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg"], match=CueImportMatch.MISMATCH)
    d = CueMergeDialog(imp)

    d.open("pack")

    assert d.imp is None
    assert dialogs.active_dialog is None


def test_merge_toggle(merge_env):
    imp, _calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg"])
    d = CueMergeDialog(imp)
    d.open("pack")

    d.toggle(CueImportCategory.SFX)
    assert d.is_checked(CueImportCategory.SFX) is False
    # absent category can't be toggled on
    d.toggle(CueImportCategory.MARKERS)
    assert d.is_checked(CueImportCategory.MARKERS) is False


def test_merge_summary_counts_overwrites(merge_env):
    imp, _calls, original_root, dialogs = merge_env
    _write(original_root, "audio/a.ogg", "old")
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg", "audio/b.ogg", "music/m.ogg"])
    d = CueMergeDialog(imp)
    d.open("pack")

    summary = d.summary()

    assert "3 file(s)" in summary
    assert "1 file will be overwritten" in summary
    assert d.overwrites == ["audio/a.ogg"]


def test_merge_summary_notes_missing_files(merge_env):
    imp, _calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg"], missing=["music/m.ogg", "video/v.mkv"])
    d = CueMergeDialog(imp)
    d.open("pack")

    summary = d.summary()

    assert "2 listed file(s) are missing" in summary
    assert "music/m.ogg" in summary
    assert "video/v.mkv" in summary


def test_merge_summary_no_missing_noise(merge_env):
    imp, _calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg"])
    d = CueMergeDialog(imp)
    d.open("pack")

    summary = d.summary()

    assert "missing" not in summary


def test_merge_confirm_records_checked_and_hides(merge_env):
    imp, calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg", "music/m.ogg"])
    d = CueMergeDialog(imp)
    d.open("pack")
    d.toggle(CueImportCategory.SFX)

    d.confirm()

    assert calls == [("pack", [CueImportCategory.MUSIC])]
    assert d.imp is None
    assert d.checked == {}
    assert dialogs.active_dialog is None


def test_merge_cancel(merge_env):
    imp, calls, _base, dialogs = merge_env
    imp.import_for = lambda imp: _merge_entry(["audio/a.ogg"])
    d = CueMergeDialog(imp)
    d.open("pack")

    d.cancel()

    assert d.imp is None
    assert calls == []
    assert dialogs.active_dialog is None
