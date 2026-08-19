# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.dialogs -- the preset/video-preset/confirm dialog
# state classes and the preset confirm/apply helpers.

import types

import pytest

import renpy as _renpy

import cue_lib.ui.dialogs as _dlg
from cue_lib.ui.dialogs import (
    CueConfirmDialog,
    CuePresetDialog,
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
    confirm = CueConfirmDialog()
    cue = types.SimpleNamespace(markers=markers, confirm_dialog=confirm,
                                current_file="", calls=calls)
    cue.music = types.SimpleNamespace(
        songs_for_trigger=lambda key: [],
        create_preset=_rec("music_create_preset"),
        delete_preset=_rec("music_delete_preset"),
    )
    cue.vid_manager = types.SimpleNamespace(get_duration=lambda: 12.5)
    monkeypatch.setattr(_dlg, "_cue", cue)
    return cue


@pytest.fixture
def screens(monkeypatch):
    shown = []
    hidden = []

    def _show(name, *args, **kwargs):
        shown.append(name)

    def _hide(name, *args, **kwargs):
        hidden.append(name)

    monkeypatch.setattr(_renpy, "show_screen", _show)
    monkeypatch.setattr(_renpy, "hide_screen", _hide)
    return shown, hidden


# ==========================================================================
# CuePresetDialog
# ==========================================================================

def test_preset_open_missing_entry_noop(ui_cue, screens):
    d = CuePresetDialog()
    d.open("v_scene.ogv", 0)
    assert d.marker_key is None
    assert screens[0] == []


def test_preset_open_pool_out_of_range_noop(ui_cue, screens):
    ui_cue.markers.get = lambda key: {"pools": [{"files": []}]}
    d = CuePresetDialog()
    d.open("v_scene.ogv", 1)
    assert d.marker_key is None
    assert screens[0] == []


def test_preset_open_happy(ui_cue, screens):
    ui_cue.markers.get = lambda key: {"pools": [{"files": ["a.ogg"]}]}
    d = CuePresetDialog()
    d.open("v_scene.ogv", 0)
    assert d.marker_key == "v_scene.ogv"
    assert d.pool_idx == 0
    assert d.name == ""
    assert ui_cue.calls["detach_pool"] == [(("v_scene.ogv", 0), {})]
    assert screens[0] == ["cue_save_preset_dialog"]


def test_preset_commit_empty_name_no_create(ui_cue, screens):
    d = CuePresetDialog()
    d.marker_key = "v_scene.ogv"
    d.pool_idx = 0
    d.name = "   "
    d.commit()
    assert "create_preset" not in ui_cue.calls
    assert d.marker_key is None
    assert screens[1] == ["cue_save_preset_dialog"]


def test_preset_commit_no_trigger_no_create(ui_cue, screens):
    d = CuePresetDialog()
    d.name = "Foo"
    d.commit()
    assert "create_preset" not in ui_cue.calls
    assert screens[1] == ["cue_save_preset_dialog"]


def test_preset_commit_happy(ui_cue, screens):
    ui_cue.markers.get = lambda key: {"pools": [{"files": ["a.ogg"]}]}
    d = CuePresetDialog()
    d.marker_key = "v_scene.ogv"
    d.pool_idx = 0
    d.name = "Tense"
    d.commit()
    assert ui_cue.calls["create_preset"] == [(("Tense", {"files": ["a.ogg"]}), {})]
    assert d.marker_key is None
    assert screens[1] == ["cue_save_preset_dialog"]


def test_preset_cancel(ui_cue, screens):
    d = CuePresetDialog()
    d.marker_key = "v_scene.ogv"
    d.cancel()
    assert d.marker_key is None
    assert screens[1] == ["cue_save_preset_dialog"]


# -- generalized dialog: music-trigger presets --

def test_preset_open_music_empty_songs_noop(ui_cue, screens):
    d = CuePresetDialog()
    d.open_music("i_scene.ogv")
    assert d.music_key is None
    assert screens[0] == []


def test_preset_open_music_happy(ui_cue, screens):
    ui_cue.music.songs_for_trigger = lambda key: ["u:music/a.ogg", "u:music/b.ogg"]
    d = CuePresetDialog()
    d.open_music("i_scene.ogv")
    assert d.music_key == "i_scene.ogv"
    assert d.marker_key is None
    assert d.songs == ["u:music/a.ogg", "u:music/b.ogg"]
    assert d.name == ""
    assert screens[0] == ["cue_save_preset_dialog"]


def test_preset_open_music_clears_sfx_state(ui_cue, screens):
    # Reusing the dialog after an SFX save must not leak the old target.
    d = CuePresetDialog()
    d.marker_key = "v_scene.ogv"
    ui_cue.music.songs_for_trigger = lambda key: ["u:music/a.ogg"]
    d.open_music("i_scene.ogv")
    assert d.music_key == "i_scene.ogv"
    assert d.marker_key is None


def test_preset_commit_music_happy(ui_cue, screens):
    d = CuePresetDialog()
    d.music_key = "i_scene.ogv"
    d.songs = ["u:music/a.ogg"]
    d.name = "Tense"
    d.commit()
    assert ui_cue.calls["music_create_preset"] == [(("Tense", ["u:music/a.ogg"]), {})]
    assert d.music_key is None
    assert d.songs == []
    assert screens[1] == ["cue_save_preset_dialog"]


def test_preset_commit_music_empty_name_no_create(ui_cue, screens):
    d = CuePresetDialog()
    d.music_key = "i_scene.ogv"
    d.songs = ["u:music/a.ogg"]
    d.name = "   "
    d.commit()
    assert "music_create_preset" not in ui_cue.calls
    assert d.music_key is None
    assert screens[1] == ["cue_save_preset_dialog"]


def test_preset_cancel_music(ui_cue, screens):
    d = CuePresetDialog()
    d.music_key = "i_scene.ogv"
    d.songs = ["u:music/a.ogg"]
    d.cancel()
    assert d.music_key is None
    assert d.songs == []
    assert screens[1] == ["cue_save_preset_dialog"]


def test_preset_commit_sfx_survives_generalization(ui_cue, screens):
    # The SFX path must keep working after the music branch is added.
    ui_cue.markers.get = lambda key: {"pools": [{"files": ["a.ogg"]}]}
    d = CuePresetDialog()
    d.marker_key = "v_scene.ogv"
    d.pool_idx = 0
    d.name = "Tense"
    d.commit()
    assert ui_cue.calls["create_preset"] == [(("Tense", {"files": ["a.ogg"]}), {})]
    assert d.marker_key is None
    assert d.music_key is None
    assert screens[1] == ["cue_save_preset_dialog"]


# ==========================================================================
# CueVideoPresetDialog
# ==========================================================================

def test_video_preset_open_no_current_file(ui_cue, screens):
    d = CueVideoPresetDialog()
    d.open()
    assert screens[0] == []


def test_video_preset_open_missing_entry(ui_cue, screens):
    ui_cue.current_file = "v_scene.ogv"
    d = CueVideoPresetDialog()
    d.open()
    assert screens[0] == []


def test_video_preset_open_no_pools(ui_cue, screens):
    ui_cue.current_file = "v_scene.ogv"
    ui_cue.markers.get = lambda key: {"pools": []}
    d = CueVideoPresetDialog()
    d.open()
    assert screens[0] == []


def test_video_preset_open_happy(ui_cue, screens):
    ui_cue.current_file = "v_scene.ogv"
    ui_cue.markers.get = lambda key: {"pools": [{"time": 1.0}]}
    d = CueVideoPresetDialog()
    d.open()
    assert d.name == ""
    assert screens[0] == ["cue_save_video_preset_dialog"]


def test_video_preset_commit_empty_name(ui_cue, screens):
    d = CueVideoPresetDialog()
    d.name = ""
    d.commit()
    assert "create_video_preset" not in ui_cue.calls
    assert screens[1] == ["cue_save_video_preset_dialog"]


def test_video_preset_commit_happy(ui_cue, screens):
    ui_cue.current_file = "v_scene.ogv"
    ui_cue.markers.get = lambda key: {"pools": [{"time": 1.0}]}
    d = CueVideoPresetDialog()
    d.name = "Slow"
    d.commit()
    assert ui_cue.calls["create_video_preset"] == [
        (("Slow", {"pools": [{"time": 1.0}]}), {})]
    assert screens[1] == ["cue_save_video_preset_dialog"]


def test_video_preset_cancel(ui_cue, screens):
    d = CueVideoPresetDialog()
    d.cancel()
    assert screens[1] == ["cue_save_video_preset_dialog"]


# ==========================================================================
# CueConfirmDialog
# ==========================================================================

def test_confirm_show_hide(ui_cue, screens):
    d = CueConfirmDialog()
    d.show("Sure?", lambda: None)
    assert d.message == "Sure?"
    assert callable(d.on_confirm)
    assert screens[0] == ["cue_confirm_dialog"]
    d.hide()
    assert d.message == ""
    assert d.on_confirm is None
    assert screens[1] == ["cue_confirm_dialog"]


# ==========================================================================
# confirm-delete / apply helpers
# ==========================================================================

def test_confirm_delete_preset(ui_cue, screens):
    _cue_confirm_delete_preset("Foo")
    assert ui_cue.confirm_dialog.message == "Delete preset 'Foo'?"
    # on_confirm is the Function() wrapper (None in the mock store).
    assert ui_cue.confirm_dialog.on_confirm is None
    assert screens[0] == ["cue_confirm_dialog"]


def test_confirm_delete_video_preset(ui_cue, screens):
    _cue_confirm_delete_video_preset("Bar")
    assert ui_cue.confirm_dialog.message == "Delete video preset 'Bar'?"
    assert screens[0] == ["cue_confirm_dialog"]


def test_confirm_delete_music_preset(ui_cue, screens):
    _cue_confirm_delete_music_preset("Foo")
    assert ui_cue.confirm_dialog.message == "Delete music preset 'Foo'?"
    assert screens[0] == ["cue_confirm_dialog"]


def test_maybe_apply_video_preset_in_range(ui_cue, screens):
    _cue_maybe_apply_video_preset("Preset")
    assert ui_cue.calls["apply_video_preset"] == [(("Preset",), {})]
    assert screens[0] == []


def test_maybe_apply_video_preset_out_of_range(ui_cue, screens):
    ui_cue.markers.video_preset_out_of_range = lambda name: 3
    ui_cue.markers.get_video_preset = lambda name: {"pools": [1, 2, 3, 4]}
    _cue_maybe_apply_video_preset("Preset")
    # out of range -> confirm dialog, message shows counts + duration.
    assert "3 of 4 marker(s)" in ui_cue.confirm_dialog.message
    assert "12.5s" in ui_cue.confirm_dialog.message
    assert "apply_video_preset" not in ui_cue.calls
    assert screens[0] == ["cue_confirm_dialog"]


def test_maybe_apply_video_preset_out_of_range_no_preset(ui_cue, screens):
    ui_cue.markers.video_preset_out_of_range = lambda name: 2
    ui_cue.markers.get_video_preset = lambda name: None
    _cue_maybe_apply_video_preset("Ghost")
    assert "2 of 0 marker(s)" in ui_cue.confirm_dialog.message
    assert "apply_video_preset" not in ui_cue.calls
