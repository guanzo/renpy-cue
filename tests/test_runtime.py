# -*- coding: utf-8 -*-
# Tests for cue_lib.runtime -- the overlay show/hide, context detection,
# channel detection, tick engine, and SFX playback drivers.
#
# Every function reads the module-global _cue (imported at module top), so the
# shared `cue` fixture monkeypatches runtime._cue to a fresh make_runtime_cue()
# graph per test -- the same singleton-isolation pattern as the markers
# persistence tests.  Call side effects land in cue.calls; mutable manager
# state (files, channel, flags) is driven directly to reach branches.

import types

import pytest

import renpy as _renpy
import renpy.audio.audio as _aaudio
import renpy.audio.music as _music_mock
import renpy.store as _store

import cue_lib.audio.sfx_manager as _sfx_manager
import cue_lib.logger as _logger_mod
import cue_lib.markers as _markers
import cue_lib.runtime as _runtime
import cue_lib.settings as _settings
import cue_lib.ui.overlay as _overlay
import cue_lib.util as _util
from cue_lib.audio.sfx_manager import CueSfxManager
from cue_lib.constants import CuePage, CUE_SFX_CHANNEL_COUNT, CUE_SHARED_KEY_MUSIC_FOLDERS, CUE_SHARED_KEY_SFX_FOLDERS
from cue_lib.state import _cue
from tests.fakes import make_runtime_cue
from types import SimpleNamespace


@pytest.fixture
def cue(monkeypatch, tmp_path):
    """Fresh _cue graph per test, isolated from the real singleton."""
    root = str(tmp_path / "cue_root")
    c = make_runtime_cue(root=root, audio_dir=root + "/audio/")
    monkeypatch.setattr(_runtime, "_cue", c)
    monkeypatch.setattr(_overlay, "_cue", c)  # overlay actions read overlay._cue
    monkeypatch.setattr(_markers, "_cue", c)  # _cue_full_reload reads markers._cue
    monkeypatch.setattr(_util, "_cue", c)  # _cue_resolve_files/_cue_pick_file
    monkeypatch.setattr(_settings, "_cue", c)  # CueSettings methods read _cue
    _store.persistent._cue = None  # fresh scalar-migration state per test
    _music_mock._reset_all()
    _aaudio.channels.clear()
    _runtime._cue_slow_tick_last = 0.0
    return c


# ==========================================================================
# Overlay visibility
# ==========================================================================


def test_toggle_overlay_hides_when_visible(cue, monkeypatch):
    cue.is_overlay_visible = True
    hidden = []
    monkeypatch.setattr(_overlay, "_cue_hide_overlay", lambda: hidden.append(1))
    _overlay._cue_toggle_overlay()
    assert hidden == [1]


def test_toggle_overlay_shows_when_hidden(cue, monkeypatch):
    cue.is_overlay_visible = False
    shown = []
    monkeypatch.setattr(_overlay, "_cue_show_overlay", lambda: shown.append(1))
    _overlay._cue_toggle_overlay()
    assert shown == [1]


def test_show_overlay_never_scans(cue):
    # Scans (and the WAV warm) run at init via _cue_full_reload; an overlay
    # open stays on the cheap path even for empty libraries.
    cue.sfx.library.files = []
    cue.music.library.user_files = []
    _overlay._cue_show_overlay()
    assert cue.is_overlay_visible is True
    assert "sfx_manager.scan" not in cue.calls
    assert "music.library.scan" not in cue.calls
    assert "sfx_manager.warm_cache" not in cue.calls
    assert cue.calls["sfx_manager.maybe_rebuild"] == [((), {})]
    assert cue.calls["video_editor.refresh"] == [((), {"restart_interaction": False})]


def test_hide_overlay(cue, monkeypatch):
    cue.is_overlay_visible = True
    calls = []
    monkeypatch.setattr(_overlay.CueVideoMarkerTimeline, "reset_timeline_drag", lambda: calls.append(None))
    _overlay._cue_hide_overlay()
    assert cue.is_overlay_visible is False
    # Hide aborts an in-flight marker drag so a stale one doesn't resurface
    # on the next show (the timeline outlives the overlay).
    assert calls == [None]


def test_full_reload_scans_and_reloads(cue):
    _runtime._cue_full_reload()
    assert cue.calls["markers.load_persistent"] == [((), {})]
    assert cue.calls["music.reload_presets"] == [((), {})]
    assert cue.calls["sfx_manager.scan"] == [((), {})]
    assert cue.calls["music.library.scan"] == [((), {})]


def test_full_reload_hydrates_external_folders(cue):
    """Boot/apply hydration contract: shared-config folder lists seed the
    trees' external sources and the loader roots on every full reload."""
    cue.db.shared = {CUE_SHARED_KEY_MUSIC_FOLDERS: ["E:/Music/A"], CUE_SHARED_KEY_SFX_FOLDERS: ["E:/SFX/B"]}
    _runtime._cue_full_reload()
    assert cue.music.library.external_folders == ["E:/Music/A"]
    assert cue.sfx.library.external_folders == ["E:/SFX/B"]
    assert cue.paths._extra_loader_roots == ["E:/SFX/B", "E:/Music/A"]


def test_full_reload_migrates_intensity_hooks(cue):
    """Migration contract: every reload path runs the one-time folder-hook
    migration on the freshly loaded markers.  Boot, import activate/deactivate,
    and post-restore all funnel through _cue_full_reload, so a legacy pool a
    user saves mid-session is converted before the next save persists it."""
    cue.marker_store = SimpleNamespace(_data={"v_scene.ogv": {"pools": [{"files": ["intensity/light/"]}]}})
    cue.intensity = SimpleNamespace(_load=lambda: {"Light": {"levels": [{"id": 1, "files": ["intensity/light/"]}]}})
    _runtime._cue_full_reload()
    pool = cue.marker_store._data["v_scene.ogv"]["pools"][0]
    assert pool["igroup"] == "Light"
    assert pool["ilevel_id"] == 1
    assert pool["files"] == []


def test_full_reload_serves_markers_from_effective_root(cue, tmp_path):
    """Import isolation contract: activating an import swaps the in-memory
    markers, not just the path pointer.  _cue_full_reload reloads markers
    from paths.marker_dir, which follows _active_root, so a refresh after the
    swap serves the package's markers instead of the live tree's.

    Regression test: activation used to leave the live tree's markers in
    memory (the path swapped but the data did not)."""
    import os

    from cue_lib.db import CueDatabase
    from cue_lib.marker_store import CueMarkerStore
    from cue_lib.markers import CueMarkerManager
    from cue_lib.paths import CuePaths
    from cue_lib.state import CueContext
    from tests.fakes import FakeSfxManager, FakeVidManager

    root = str(tmp_path / "cue_root")
    paths = CuePaths(root, game_id="test_game")
    db = CueDatabase(paths)
    db.open()
    store = CueMarkerStore(db, paths, lambda: None)
    cue.markers = CueMarkerManager(CueContext(), store, FakeVidManager(duration=10.0), FakeSfxManager(), None, None)

    # CueDatabase.open() created the live marker dir; write the live marker.
    live_marker_dir = paths.marker_dir
    with open(os.path.join(live_marker_dir, "v_live.json"), "w") as f:
        f.write('{"_key": "v_live", "pools": []}')

    imp_root = os.path.join(root, "imports", "pkg")
    imp_marker_dir = os.path.join(imp_root, "data", "markers", "test_game")
    os.makedirs(imp_marker_dir)
    with open(os.path.join(imp_marker_dir, "v_import.json"), "w") as f:
        f.write('{"_key": "v_import", "pools": []}')

    # Live root: the editor serves the live tree's markers.
    _runtime._cue_full_reload()
    assert "v_live" in cue.markers
    assert "v_import" not in cue.markers

    # Activate an import: swap the effective root, then the same reload the
    # imports manager runs must serve the package's markers instead.
    paths._active_root = imp_root
    _runtime._cue_full_reload()
    assert "v_import" in cue.markers
    assert "v_live" not in cue.markers


# ==========================================================================
# Trigger / page state
# ==========================================================================


def test_set_page_same_page_noop(cue):
    cue.overlay_active_page = CuePage.SFX
    _overlay._cue_set_page(CuePage.SFX)
    assert cue.overlay_active_page == CuePage.SFX


def test_set_page_settings_preps_shared_dir_input(cue):
    cue.overlay_active_page = CuePage.SFX
    cue.settings.shared_dir_error = "stale error"
    cue.settings.shared_dir_success = "stale success"
    _overlay._cue_set_page(CuePage.SETTINGS)
    assert cue.overlay_active_page == CuePage.SETTINGS
    assert cue.settings.setup_dir_text == cue.paths.root
    assert cue.settings.shared_dir_error == ""
    assert cue.settings.shared_dir_success == ""


def test_set_page_plain_page_switch(cue):
    cue.overlay_active_page = CuePage.SFX
    cue.settings.setup_dir_text = "SHOULD-NOT-LEAK"
    _overlay._cue_set_page(CuePage.MUSIC)
    assert cue.overlay_active_page == CuePage.MUSIC
    assert cue.settings.setup_dir_text == "SHOULD-NOT-LEAK"  # no settings prep


def test_set_page_import_refreshes_importer_and_exporter(cue):
    cue.overlay_active_page = CuePage.SFX
    _overlay._cue_set_page(CuePage.IMPORT)
    assert cue.overlay_active_page == CuePage.IMPORT
    assert cue.calls["importer.scan"] == [((), {})]
    assert cue.calls["exporter.refresh"] == [((), {})]


# ==========================================================================
# Shared dir (Settings page)
# ==========================================================================


def test_confirm_shared_dir_empty_path(cue):
    cue.settings.setup_dir_text = "   "
    cue.settings.confirm_shared_dir()
    assert cue.settings.shared_dir_error == "Path cannot be empty."
    assert cue.settings.shared_dir_success == ""


def test_confirm_shared_dir_success(cue, monkeypatch, tmp_path):
    new_root = str(tmp_path / "new_root")
    saved = []
    monkeypatch.setattr(_settings.CuePaths, "save_root", lambda path: saved.append(path))
    cue.settings.setup_dir_text = new_root
    cue.settings.confirm_shared_dir()
    assert saved == [new_root]
    assert cue.settings.shared_dir_error == ""
    assert cue.settings.setup_dir_text == new_root
    assert cue.settings.shared_dir_success.startswith("Success")


def test_confirm_shared_dir_db_open_failure(cue, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(_settings.CueDatabase, "open", _boom)
    cue.settings.setup_dir_text = "/does/not/matter"
    cue.settings.confirm_shared_dir()
    assert cue.settings.shared_dir_error == "Could not create that directory."
    assert cue.settings.shared_dir_success == ""


def test_confirm_shared_dir_save_failure(cue, monkeypatch, tmp_path):
    new_root = str(tmp_path / "probe")

    def _boom(path):
        raise OSError("boom")

    monkeypatch.setattr(_settings.CuePaths, "save_root", _boom)
    cue.settings.setup_dir_text = new_root
    cue.settings.confirm_shared_dir()
    assert cue.settings.shared_dir_error == "Could not save the directory setting."
    assert cue.settings.shared_dir_success == ""


# ==========================================================================
# Shake / mute toggles
# ==========================================================================


def test_toggle_video_mute_no_current_file(cue):
    cue.current_file = ""
    _markers._cue_toggle_video_mute()
    assert cue.calls == {}


def test_toggle_video_mute_no_entry_noop(cue):
    cue.current_file = "scene.ogv"
    _markers._cue_toggle_video_mute()  # markers.get returns None -> no entry
    assert "markers.save_marker" not in cue.calls


def test_toggle_video_mute_mutes_then_unmutes(cue):
    _music_mock.register_channel("movie")
    cue.current_file = "scene.ogv"
    entry = {"video_file_muted": False}
    cue.markers.get = lambda key, default=None: entry if key == "v_scene.ogv" else default
    cue.vid_manager.channel = "movie"
    _markers._cue_toggle_video_mute()
    assert _music_mock._registry["movie"]["volume"] == 0.0
    assert cue.calls["markers.save_marker"] == [(("v_scene.ogv",), {})]
    _markers._cue_toggle_video_mute()
    assert _music_mock._registry["movie"]["volume"] == 1.0


def test_toggle_video_mute_no_channel_skips_volume(cue):
    cue.current_file = "scene.ogv"
    cue.markers.get = lambda key, default=None: {"video_file_muted": False}
    cue.vid_manager.channel = None
    _markers._cue_toggle_video_mute()
    assert "movie" not in _music_mock._registry  # set_volume never called
    assert cue.calls["markers.save_marker"] == [(("v_scene.ogv",), {})]


# ==========================================================================
# _cue_get_top_layer -- scene-list inspection
# ==========================================================================


class _FakeEntry(object):
    def __init__(self, tag="", name=None, displayable=None):
        self.tag = tag
        self.name = name
        self.displayable = displayable


def _set_top_layer(monkeypatch, tag, name, displayable):
    """Point the mock scene lists at a single master-layer entry."""
    scene = types.SimpleNamespace()
    scene.scene_lists = types.SimpleNamespace(layers={"master": [_FakeEntry(tag, name, displayable)]})
    monkeypatch.setattr(_renpy.game, "context", lambda: scene)
    monkeypatch.setattr(_renpy, "get_showing_tags", lambda layer="master": ["anything"])
    return scene


def test_get_top_layer_no_tags(cue):
    # Mock default: get_showing_tags -> [] -> nothing showing.
    assert _runtime._cue_get_top_layer() == (None, None, None)


def test_get_top_layer_no_layers(cue, monkeypatch):
    scene = types.SimpleNamespace()
    scene.scene_lists = types.SimpleNamespace(layers={})
    monkeypatch.setattr(_renpy.game, "context", lambda: scene)
    monkeypatch.setattr(_renpy, "get_showing_tags", lambda layer="master": ["x"])
    assert _runtime._cue_get_top_layer() == (None, None, None)


def test_get_top_layer_no_name(cue, monkeypatch):
    _set_top_layer(monkeypatch, tag="", name=None, displayable=None)
    assert _runtime._cue_get_top_layer() == (None, None, None)


def test_get_top_layer_movie(cue, monkeypatch):
    from renpy.display.video import Movie

    d = Movie(play="scene.webm", channel="movie")
    _set_top_layer(monkeypatch, tag="bg", name=("bg", "scene"), displayable=d)
    name, typ, disp = _runtime._cue_get_top_layer()
    assert name == "bg scene"  # entry.name joined, not the tag
    assert typ == "movie"
    assert disp is d


def test_get_top_layer_image(cue, monkeypatch):
    from renpy.display.im import Image

    d = Image("scene.png")
    _set_top_layer(monkeypatch, tag="scene", name=None, displayable=d)
    name, typ, disp = _runtime._cue_get_top_layer()
    assert name == "scene"  # falls back to tag when entry.name is empty
    assert typ == "image"
    assert disp is d


def test_get_top_layer_exception_returns_none(cue, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_renpy, "get_showing_tags", _boom)
    monkeypatch.setattr(_logger_mod._cue_logger, "log_error", lambda *a: None)
    assert _runtime._cue_get_top_layer() == (None, None, None)


# ==========================================================================
# _cue_refresh_context
# ==========================================================================


def test_refresh_context_no_top_layer_returns(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: (None, None, None))
    _runtime._cue_refresh_context()
    assert "music.capture_display" not in cue.calls
    assert cue.current_file == "scene.ogv"  # untouched by the early return


def test_refresh_context_no_change(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    cue.vid_manager.channel = None
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    assert cue.calls["music.capture_display"] == [((), {})]
    # Context refresh does not rebuild the SFX tree -- its inputs (files,
    # search, expanded folders) only change on scan/toggle, not on scene change.
    assert "sfx_manager.maybe_rebuild" not in cue.calls
    assert "trigger.fire_context" not in cue.calls
    assert "video_sequence.handle" not in cue.calls


def test_refresh_context_file_change_fires(cue, monkeypatch):
    cue.current_file = ""
    cue.top_layer_type = "image"
    cue.vid_manager.channel = None
    cue.is_overlay_visible = False
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    assert cue.calls["music.play_custom_music"] == [((), {})]
    assert cue.calls["video_sequence.handle"] == [(("scene.ogv",), {})]
    assert cue.calls["speed_resolver.clear_pending"] == [((), {})]
    assert cue.calls["trigger.reset"] == [((), {})]
    assert cue.calls["trigger.fire_context"] == [((("i_scene.ogv",), {}))]
    assert "video_editor.refresh" not in cue.calls  # overlay hidden


def test_refresh_context_file_change_overlay_visible(cue, monkeypatch):
    cue.current_file = ""
    cue.is_overlay_visible = True
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    assert "video_editor.refresh" in cue.calls


def test_refresh_context_channel_change(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    cue.vid_manager.channel = "old_ch"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    # refresh_channel swept the stale channel (no candidates) -> ch branch
    assert cue.vid_manager.channel is None
    assert "trigger.fire_context" not in cue.calls


def test_refresh_context_dialogue_change(cue, monkeypatch):
    monkeypatch.setattr(_renpy, "get_screen", lambda name: object())
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    cue.vid_manager.channel = None
    cue.current_dialogue = "Hello there"
    cue.prev_dialogue = "Goodbye"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    assert cue.calls["trigger.fire_context"] == [((("d_scene.ogv__Hello there",), {}))]


def test_refresh_context_type_change(cue, monkeypatch):
    from renpy.display.video import Movie

    d = Movie(play="scene.webm", channel="movie")
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    cue.vid_manager.channel = None
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "movie", d))
    _runtime._cue_refresh_context()
    assert cue.ctx.top_layer_type == "movie"
    assert cue.ctx.top_displayable is d
    assert "trigger.fire_context" not in cue.calls


def test_refresh_context_shake_fires_only_shake(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    cue.vid_manager.channel = None
    cue.ctx._shake_just_happened = True
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    assert cue.ctx._shake_just_happened is False
    # img_key is None (no file change); shake_key differs -> only-shake fire
    assert cue.calls["trigger.fire_context"] == [(("i_scene.ogv",), {"only_shake_pools": True})]


def test_refresh_context_shake_skips_duplicate_after_file_change(cue, monkeypatch):
    cue.current_file = ""
    cue.ctx._shake_just_happened = True
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_refresh_context()
    # file-change fire set img_key == shake_key, so the shake fire is skipped
    assert cue.calls["trigger.fire_context"] == [((("i_scene.ogv",), {}))]


# ==========================================================================
# _cue_log_context
# ==========================================================================


def _rec_log(monkeypatch):
    msgs = []
    monkeypatch.setattr(_runtime, "_cue_log", lambda m: msgs.append(m))
    monkeypatch.setattr(_sfx_manager, "_cue_log", lambda m: msgs.append(m))
    return msgs


def test_log_context_top_type_present(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_log_context()
    assert "type=image" in msgs[0]
    assert "video=(none)" in msgs[0]
    assert "ch=(none)" in msgs[0]


def test_log_context_video_playing(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)
    _music_mock.play("scene.webm", channel="movie")
    cue.vid_manager.channel = "movie"
    cue.vid_manager.get_video_path = lambda: "movies/scene.webm"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: (None, None, None))
    _runtime._cue_log_context()
    assert "video=scene.webm" in msgs[0]
    assert "playing=1" in msgs[0]
    assert "type=video" in msgs[0]


def test_log_context_none(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)
    cue.vid_manager.channel = None
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: (None, None, None))
    _runtime._cue_log_context()
    assert "playing=?" in msgs[0]
    assert "type=none" in msgs[0]


def test_log_context_is_playing_exception(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "is_playing", _boom)
    cue.vid_manager.channel = "movie"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: (None, None, None))
    _runtime._cue_log_context()
    assert "LOG-CONTEXT: is_playing probe failed" in msgs[0]


# ==========================================================================
# CueSfxManager.play_pool
# ==========================================================================


@pytest.fixture
def sfx_mgr(cue):
    """Real CueSfxManager with injected collaborators.  paths/volume/markers/
    ctx are the same objects the cue fixture exposes, so tests keep driving
    them through cue.* -- only the relative-volume flag is snapshotted (set
    it via sfx_mgr._supports_relative_volume)."""
    mgr = CueSfxManager(cue.paths, types.SimpleNamespace(), cue.volume, cue.ctx, cue._has_relative_volume)
    mgr.bind_markers(cue.markers)
    return mgr


def test_play_pool_no_files_returns_none(cue, sfx_mgr):
    cue.markers.resolve_pool = lambda pool, expand=False: types.SimpleNamespace(files=[])
    assert sfx_mgr.play_pool(None, "i_scene.ogv", {}, 0) is None


def test_play_pool_file_override(cue, sfx_mgr, monkeypatch):
    cue.markers.resolve_pool = lambda pool, expand=False: types.SimpleNamespace(files=["a.ogg", "b.ogg"])
    cue.sfx.library.files = ["a.ogg", "b.ogg"]
    played = []
    monkeypatch.setattr(
        sfx_mgr, "play_sfx", lambda f, key, volume=1.0, **kwargs: played.append((f, key, volume)) or "cue_1"
    )
    cue.volume.get_effective = lambda entry, key, pool_index: 0.5
    ch = sfx_mgr.play_pool(None, "i_scene.ogv", {}, 0, file="b.ogg")
    assert ch == "cue_1"
    assert played == [("b.ogg", "i_scene.ogv", 0.5)]


def test_play_pool_picks_file(cue, sfx_mgr, monkeypatch):
    cue.markers.resolve_pool = lambda pool, expand=False: types.SimpleNamespace(files=["a.ogg"])
    played = []
    monkeypatch.setattr(sfx_mgr, "play_sfx", lambda f, key, volume=1.0, **kwargs: played.append(f) or "cue_1")
    sfx_mgr.play_pool(None, "i_scene.ogv", {}, 0)
    assert played == ["a.ogg"]


def test_play_pool_file_override_empty_pool(cue, sfx_mgr, monkeypatch):
    # Intensity-hooked pools carry no own files (files=[]); the trigger hands
    # the resolved file explicitly. play_pool must honor it instead of bailing
    # on the empty pool.
    cue.markers.resolve_pool = lambda pool, expand=False: types.SimpleNamespace(files=[])
    played = []
    monkeypatch.setattr(
        sfx_mgr, "play_sfx", lambda f, key, volume=1.0, **kwargs: played.append((f, key, volume)) or "cue_1"
    )
    cue.volume.get_effective = lambda entry, key, pool_index: 0.5
    ch = sfx_mgr.play_pool(None, "l_scene", {"igroup": "G", "ilevel_id": 1, "files": []}, 0, file="hard/1.ogg")
    assert ch == "cue_1"
    assert played == [("hard/1.ogg", "l_scene", 0.5)]


# ==========================================================================
# _cue_refresh_channel
# ==========================================================================


def _movie_channel(name, playing, dur=10.0, **attrs):
    """Register a playing movie channel in the mock audio registry."""
    ch = types.SimpleNamespace(movie=True)
    for k, v in attrs.items():
        setattr(ch, k, v)
    _aaudio.channels[name] = ch
    _music_mock.play(playing, channel=name)
    _music_mock._registry[name]["duration"] = dur
    return ch


def test_refresh_channel_refreshing_guard(cue):
    cue.vid_manager.refreshing = True
    cue.vid_manager.channel = "movie"
    _runtime._cue_refresh_channel()
    assert cue.vid_manager.channel == "movie"  # untouched
    assert cue.vid_manager.refreshing is True  # early return, finally skipped


def test_refresh_channel_no_candidates_clears(cue):
    cue.vid_manager.channel = "old"
    _runtime._cue_refresh_channel()
    assert cue.vid_manager.channel is None
    assert cue.vid_manager.refreshing is False


def test_refresh_channel_applies_first_candidate(cue):
    _movie_channel("movie", "scene.webm", dur=10.0, framerate=30)
    _runtime._cue_refresh_channel()
    assert cue.calls["vid_manager.reset"] == [(("movie",), {})]
    assert cue.calls["vid_manager.set_fps"] == [((30,), {})]
    assert "video_editor.refresh" in cue.calls
    assert cue.vid_manager.channel == "movie"


def test_refresh_channel_same_channel_skips_reset(cue):
    cue.vid_manager.channel = "movie"
    _movie_channel("movie", "scene.webm", dur=10.0)
    _runtime._cue_refresh_channel()
    assert "vid_manager.reset" not in cue.calls
    assert cue.vid_manager.channel == "movie"


def test_refresh_channel_fps_callable(cue):
    _movie_channel("movie", "scene.webm", dur=10.0, fps=lambda: 24.7)
    _runtime._cue_refresh_channel()
    assert cue.calls["vid_manager.set_fps"] == [((25,), {})]


def test_refresh_channel_fps_probe_exception_falls_back(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    _movie_channel("movie", "scene.webm", dur=10.0, framerate=_boom)
    _runtime._cue_refresh_channel()
    assert "APPLY-CHANNEL: attr framerate probe failed" in msgs[0]
    assert cue.calls["vid_manager.set_fps"] == [((30,), {})]  # default fps


def test_refresh_channel_movie_displayable_match(cue):
    from renpy.display.video import Movie

    d = Movie()
    cue.speed_resolver.base_path_for = lambda f: "movies/scene.webm"
    _movie_channel("movie", "movies/scene.webm", dur=10.0)
    cue.current_file = "scene.ogv"
    _runtime._cue_refresh_channel(displayable=d)
    assert cue.vid_manager.channel == "movie"
    assert cue.calls["vid_manager.reset"] == [(("movie",), {})]


def test_refresh_channel_movie_displayable_variant(cue):
    from renpy.display.video import Movie

    d = Movie()
    cue.speed_resolver.base_path_for = lambda f: "movies/scene.webm"
    cue.speed_resolver.is_variant_of = lambda path, target: True
    _movie_channel("movie", "movies/scene__cue_2.0x.webm", dur=10.0)
    _runtime._cue_refresh_channel(displayable=d)
    assert cue.vid_manager.channel == "movie"


def test_refresh_channel_movie_displayable_no_match_clears(cue):
    from renpy.display.video import Movie

    d = Movie()
    cue.speed_resolver.base_path_for = lambda f: "movies/scene.webm"
    cue.speed_resolver.is_variant_of = lambda path, target: False
    _movie_channel("movie", "movies/other.webm", dur=10.0)
    _runtime._cue_refresh_channel(displayable=d)
    assert cue.vid_manager.channel is None
    assert "vid_manager.reset" not in cue.calls


def test_refresh_channel_movie_displayable_no_target_clears(cue):
    from renpy.display.video import Movie

    d = Movie()
    cue.speed_resolver.base_path_for = lambda f: None
    _movie_channel("movie", "movies/scene.webm", dur=10.0)
    _runtime._cue_refresh_channel(displayable=d)
    assert cue.vid_manager.channel is None


def test_refresh_channel_reapplies_video_mute(cue):
    cue.current_file = "scene.ogv"
    cue.markers.get = lambda key, default=None: {"video_file_muted": True} if key == "v_scene.ogv" else default
    _movie_channel("movie", "scene.webm", dur=10.0)
    _runtime._cue_refresh_channel()
    assert _music_mock._registry["movie"]["volume"] == 0.0


def test_refresh_channel_no_mute_reapply_when_unmuted(cue):
    cue.current_file = "scene.ogv"
    cue.markers.get = lambda key, default=None: {"video_file_muted": False}
    _movie_channel("movie", "scene.webm", dur=10.0)
    _runtime._cue_refresh_channel()
    assert "volume" not in _music_mock._registry["movie"]


def test_refresh_channel_skips_non_movie_channel(cue):
    _aaudio.channels["music"] = types.SimpleNamespace(movie=False)
    _music_mock.play("song.ogg", channel="music")
    _music_mock._registry["music"]["duration"] = 30.0
    _movie_channel("movie", "scene.webm", dur=10.0)
    _runtime._cue_refresh_channel()
    assert cue.vid_manager.channel == "movie"


def test_refresh_channel_skips_none_channel(cue):
    _aaudio.channels["ghost"] = None
    _movie_channel("movie", "scene.webm", dur=10.0)
    _runtime._cue_refresh_channel()
    assert cue.vid_manager.channel == "movie"


def test_refresh_channel_skips_zero_duration(cue):
    _movie_channel("movie", "scene.webm", dur=0)
    _runtime._cue_refresh_channel()
    assert cue.vid_manager.channel is None


def test_refresh_channel_inner_scan_failure(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)
    _aaudio.channels["bad"] = types.SimpleNamespace(movie=True)

    def _boom(channel="music", **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_playing", _boom)
    _runtime._cue_refresh_channel()
    assert "REFRESH-CHANNEL: scan failed for bad" in msgs[0]
    assert cue.vid_manager.channel is None


def test_refresh_channel_outer_scan_failure(cue, monkeypatch):
    msgs = _rec_log(monkeypatch)

    class _BoomChannels(object):
        def __iter__(self):
            raise RuntimeError("boom")

        def get(self, key, default=None):
            return None

    monkeypatch.setattr(_aaudio, "channels", _BoomChannels())
    _runtime._cue_refresh_channel()
    assert "REFRESH-CHANNEL: outer scan failed" in msgs[0]


# ==========================================================================
# _cue_tick_trigger
# ==========================================================================


def test_tick_no_mismatch(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_tick_trigger()
    assert "music.capture_display" not in cue.calls  # no refresh_context
    assert cue.calls["vid_manager.sync_paused"] == [((), {})]
    assert cue.calls["vid_manager.poll_autopause"] == [((), {})]
    assert cue.calls["video_sequence.tick"] == [((), {})]
    assert cue.calls["trigger.tick"] == [(("scene.ogv", "image"), {})]


def test_tick_mismatch_refreshes_context(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("other.ogv", "image", None))
    _runtime._cue_tick_trigger()
    assert "music.capture_display" in cue.calls  # refresh_context ran


def test_tick_movie_refreshes_channel(cue, monkeypatch):
    from renpy.display.video import Movie

    d = Movie()
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "movie"
    cue.ctx.top_displayable = d
    seen = []
    monkeypatch.setattr(_runtime, "_cue_refresh_channel", lambda displayable=None: seen.append(displayable))
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "movie", None))
    _runtime._cue_tick_trigger()
    assert seen == [d]


def test_tick_non_movie_skips_channel_refresh(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    seen = []
    monkeypatch.setattr(_runtime, "_cue_refresh_channel", lambda displayable=None: seen.append(displayable))
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    _runtime._cue_tick_trigger()
    assert seen == []


def test_tick_slow_lane_flushes(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    monkeypatch.setattr(_runtime._time, "time", lambda: 1.0)
    _runtime._cue_slow_tick_last = 0.0
    _runtime._cue_tick_trigger()
    assert cue.calls["volume.flush_pending_saves"] == [((), {})]
    assert cue.calls["sfx_manager.maybe_rebuild"] == [((), {})]
    assert cue.calls["music.library.maybe_rebuild"] == [((), {})]
    assert _runtime._cue_slow_tick_last == 1.0


def test_tick_fast_lane_skips_slow_work(cue, monkeypatch):
    cue.current_file = "scene.ogv"
    cue.top_layer_type = "image"
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene.ogv", "image", None))
    monkeypatch.setattr(_runtime._time, "time", lambda: 0.1)
    _runtime._cue_slow_tick_last = 0.0
    _runtime._cue_tick_trigger()
    assert "volume.flush_pending_saves" not in cue.calls
    assert "sfx_manager.maybe_rebuild" not in cue.calls


def test_tick_pending_polls_job_queue(cue, monkeypatch):
    cue.current_file = None
    cue.video_editor.job_queue.has_pending = True
    monkeypatch.setattr(_runtime._time, "time", lambda: 1.0)
    _runtime._cue_slow_tick_last = 0.0
    _runtime._cue_tick_trigger()
    assert cue.calls["video_editor.job_queue.poll"] == [((), {})]


def test_tick_no_pending_skips_job_queue_poll(cue, monkeypatch):
    cue.current_file = None
    cue.video_editor.job_queue.has_pending = False
    monkeypatch.setattr(_runtime._time, "time", lambda: 1.0)
    _runtime._cue_slow_tick_last = 0.0
    _runtime._cue_tick_trigger()
    assert "video_editor.job_queue.poll" not in cue.calls
    assert cue.calls["trigger.tick"] == [((None, ""), {})]


# ==========================================================================
# CueSfxManager previews
# ==========================================================================


def test_preview_preset_missing(cue, sfx_mgr, monkeypatch):
    cue.markers.get_preset = lambda name: None
    played = []
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f: played.append(f))
    sfx_mgr.preview_preset("p")
    assert played == []


def test_preview_preset_plays_random(cue, sfx_mgr, monkeypatch):
    cue.markers.get_preset = lambda name: {"files": ["a.ogg", "b.ogg"]}
    cue.sfx.library.files = ["a.ogg", "b.ogg"]
    played = []
    monkeypatch.setattr(_sfx_manager._random, "choice", lambda files: files[1])
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f: played.append(f))
    sfx_mgr.preview_preset("p")
    assert played == ["b.ogg"]


def test_preview_preset_empty_files(cue, sfx_mgr, monkeypatch):
    cue.markers.get_preset = lambda name: {"files": []}
    played = []
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f: played.append(f))
    sfx_mgr.preview_preset("p")
    assert played == []


def test_preview_folder_plays_with_volume(cue, sfx_mgr, monkeypatch):
    cue.sfx.library.files = ["sfx/dir/a.ogg", "sfx/dir/b.ogg"]
    played = []
    monkeypatch.setattr(_sfx_manager._random, "choice", lambda files: files[0])
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f, volume=1.0: played.append((f, volume)))
    sfx_mgr.preview_folder("sfx/dir/", volume=0.5)
    assert played == [("sfx/dir/a.ogg", 0.5)]


def test_preview_folder_empty(cue, sfx_mgr, monkeypatch):
    cue.sfx.library.files = []
    played = []
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f, volume=1.0: played.append(f))
    sfx_mgr.preview_folder("sfx/dir/")
    assert played == []


def test_preview_video_pool_picks_from_pool(cue, sfx_mgr, monkeypatch):
    cue.markers.get_video_preset = lambda name: {"pools": [{"files": ["a.ogg"]}, {"files": ["b.ogg", "c.ogg"]}]}
    cue.sfx.library.files = ["a.ogg", "b.ogg", "c.ogg"]
    played = []
    monkeypatch.setattr(_sfx_manager._random, "choice", lambda files: files[0])
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f: played.append(f))
    sfx_mgr.preview_video_pool("p", 1)
    assert played == ["b.ogg"]


def test_preview_video_pool_missing_or_bad_index(cue, sfx_mgr, monkeypatch):
    cue.markers.get_video_preset = lambda name: {"pools": [{"files": ["a.ogg"]}]} if name != "gone" else None
    played = []
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f: played.append(f))
    sfx_mgr.preview_video_pool("gone", 0)
    sfx_mgr.preview_video_pool("p", 5)
    assert played == []


def test_preview_sfx_stops_previous(cue, sfx_mgr, monkeypatch):
    _music_mock.play("old.ogg", channel="_cue_1")
    sfx_mgr._preview_channel = "_cue_1"
    monkeypatch.setattr(sfx_mgr, "play_sfx", lambda f, source, volume=1.0: "cue_2")
    sfx_mgr.preview_sfx("new.ogg")
    assert _music_mock._registry["_cue_1"]["playing"] is None  # stopped
    assert sfx_mgr._preview_channel == "cue_2"


def test_preview_sfx_no_previous(cue, sfx_mgr, monkeypatch):
    sfx_mgr._preview_channel = None
    monkeypatch.setattr(sfx_mgr, "play_sfx", lambda f, source, volume=1.0: "cue_1")
    sfx_mgr.preview_sfx("new.ogg")
    assert sfx_mgr._preview_channel == "cue_1"


# ==========================================================================
# CueSfxManager.play_sfx
# ==========================================================================


def test_play_sfx_free_channel(cue, sfx_mgr, monkeypatch):
    # Legacy (<7.5) path: _has_relative_volume is True under the mock's 8.0.0,
    # so pin the snapshot to False to exercise set_volume.
    sfx_mgr._supports_relative_volume = False
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    sfx_mgr._next_sfx_channel = 0
    ch = sfx_mgr.play_sfx("a.ogg", "preview", volume=0.5)
    assert ch == "_cue_1"
    assert _music_mock._registry["_cue_1"]["playing"] == cue.paths.audio_dir + "a.ogg"
    assert _music_mock._registry["_cue_1"]["volume"] == 0.5  # set_volume path
    assert sfx_mgr._next_sfx_channel == 1


def test_play_sfx_external_resolves_abs(cue, sfx_mgr, monkeypatch):
    sfx_mgr._supports_relative_volume = False
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    sfx_mgr._next_sfx_channel = 0
    ch = sfx_mgr.play_sfx("E:/SFX/A/g1/drip.ogg", "preview")
    assert ch == "_cue_1"
    # Bare-absolute external refs resolve to their payload, independent of
    # audio_dir.
    assert _music_mock._registry["_cue_1"]["playing"] == "E:/SFX/A/g1/drip.ogg"


def test_play_sfx_folder_external(cue, sfx_mgr, monkeypatch):
    ext = "E:/SFX/A"
    cue.sfx.library.files = [ext + "/g1/x.ogg", "g1/a.ogg"]
    picked = []
    monkeypatch.setattr(_sfx_manager._random, "choice", lambda files: picked.append(files) or files[0])
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    monkeypatch.setattr(sfx_mgr, "preview_sfx", lambda f, volume=1.0: None)
    sfx_mgr.preview_folder(ext + "/g1/")
    # Folder preview resolves the external folder ref against library.files.
    assert picked == [[ext + "/g1/x.ogg"]]


def test_play_sfx_round_robin_when_all_busy(cue, sfx_mgr, monkeypatch):
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
        _music_mock.play("busy.ogg", channel="_cue_{}".format(i))
    sfx_mgr._next_sfx_channel = 3
    sfx_mgr.play_sfx("a.ogg")
    assert _music_mock._registry["_cue_4"]["playing"] == cue.paths.audio_dir + "a.ogg"
    assert sfx_mgr._next_sfx_channel == 4


def test_play_sfx_relative_volume(cue, sfx_mgr, monkeypatch):
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    recorded = {}

    def _play(filenames, channel="music", loop=None, **kwargs):
        recorded["channel"] = channel
        recorded["kwargs"] = kwargs

    monkeypatch.setattr(_music_mock, "play", _play)
    sfx_mgr._supports_relative_volume = True
    sfx_mgr.play_sfx("a.ogg", volume=0.5)
    assert recorded["channel"] == "_cue_1"
    assert recorded["kwargs"]["relative_volume"] == 0.5


def test_play_sfx_vid_mismatch_warns(cue, sfx_mgr, monkeypatch):
    msgs = _rec_log(monkeypatch)
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    cue.current_file = "actual.ogv"
    sfx_mgr.play_sfx("a.ogg", "v_expected.ogv")
    assert any("WARN CTX-MISMATCH" in m for m in msgs)


def test_play_sfx_img_mismatch_warns(cue, sfx_mgr, monkeypatch):
    msgs = _rec_log(monkeypatch)
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    cue.current_file = "actual.ogv"
    sfx_mgr.play_sfx("a.ogg", "i_expected.ogv")
    assert any("WARN CTX-MISMATCH" in m for m in msgs)


def test_play_sfx_dlg_mismatch_warns(cue, sfx_mgr, monkeypatch):
    msgs = _rec_log(monkeypatch)
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    cue.current_file = "actual.ogv"
    cue.current_dialogue = "Now"
    sfx_mgr.play_sfx("a.ogg", "d_expected.ogv__Hello")
    assert any("WARN CTX-MISMATCH" in m for m in msgs)


def test_play_sfx_matching_no_warn(cue, sfx_mgr, monkeypatch):
    msgs = _rec_log(monkeypatch)
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)
    cue.current_file = "scene.ogv"
    sfx_mgr.play_sfx("a.ogg", "i_scene.ogv")
    assert not any("WARN CTX-MISMATCH" in m for m in msgs)


def test_play_sfx_exception_returns_none(cue, sfx_mgr, monkeypatch):
    msgs = _rec_log(monkeypatch)
    monkeypatch.setattr(_sfx_manager._random, "uniform", lambda a, b: 1.0)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "play", _boom)
    assert sfx_mgr.play_sfx("a.ogg") is None
    assert any("PLAY-SFX: exception during playback" in m for m in msgs)


# ==========================================================================
# CueSfxManager.fade_out
# ==========================================================================


def test_fade_out_sfx_counts_faded(cue, sfx_mgr):
    for i in range(1, 5):
        _music_mock.play("busy.ogg", channel="_cue_{}".format(i))
    n = sfx_mgr.fade_out()
    assert n == 4
    for i in range(1, 5):
        assert _music_mock._registry["_cue_{}".format(i)]["playing"] is None


def test_fade_out_sfx_exclude_channels(cue, sfx_mgr):
    for i in range(1, 4):
        _music_mock.play("busy.ogg", channel="_cue_{}".format(i))
    n = sfx_mgr.fade_out(exclude_channels=["_cue_2"])
    assert n == 2  # _cue_2 spared


def test_fade_out_sfx_only_channels(cue, sfx_mgr):
    for i in range(1, 6):
        _music_mock.play("busy.ogg", channel="_cue_{}".format(i))
    n = sfx_mgr.fade_out(only_channels=["_cue_1", "_cue_2"])
    assert n == 2


def test_fade_out_sfx_exclude_and_only(cue, sfx_mgr):
    for i in range(1, 4):
        _music_mock.play("busy.ogg", channel="_cue_{}".format(i))
    n = sfx_mgr.fade_out(exclude_channels=["_cue_1"], only_channels=["_cue_1", "_cue_3"])
    assert n == 1  # _cue_1 excluded, _cue_3 faded


def test_fade_out_sfx_none_playing(cue, sfx_mgr):
    assert sfx_mgr.fade_out() == 0


# ==========================================================================
# Main-loop guard containment (review F1)
#
# _cue_tick_trigger (50 Hz screen timer) and _cue_refresh_context (every
# interaction start) must swallow any exception raised by a collaborator and
# log it, so one malformed marker or an unexpected None can't wedge the
# per-frame callback chain.  The heavy manager graph is stubbed with fakes;
# the failing collaborator raises, and we assert the call returns cleanly and
# the guard logged.  These drive the real _cue singleton (not the `cue`
# fixture above), so they snapshot + restore the attrs they touch.
# ==========================================================================


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


class _RaisingTrigger(object):
    def tick(self, current_file, top_layer_type):
        raise RuntimeError("boom in trigger tick")


# The _cue singleton attrs the guard tests touch; snapshot + restore so we
# don't leak fakes into other test modules.
_CUE_ATTRS = ["ctx", "vid_manager", "video_sequence", "trigger", "volume", "video_editor", "sfx", "music"]


@pytest.fixture
def isolated_cue():
    saved = {}
    for name in _CUE_ATTRS:
        saved[name] = getattr(_cue, name, None)
    yield
    for name, value in saved.items():
        setattr(_cue, name, value)


@pytest.fixture
def captured_log(monkeypatch):
    calls = []
    monkeypatch.setattr(_runtime, "_cue_log", lambda *a: calls.append(a))
    # Guards write to the error log via the logger singleton; keep the real
    # error.log off the CWD (mock gamedir is "") and the calls visible.
    monkeypatch.setattr(_logger_mod._cue_logger, "log_error", lambda *a: calls.append(a))
    return calls


def _install_tick_collaborators(trigger=None):
    """Install the quiet manager graph the tick path touches and return it.

    trigger defaults to a raising fake so the fast lane fails; pass a quiet
    trigger to let the slow lane run instead."""
    _cue.current_file = None
    _cue.top_layer_type = None
    _cue.vid_manager = SimpleNamespace(sync_paused=lambda: None, poll_autopause=lambda: None)
    _cue.video_sequence = SimpleNamespace(tick=lambda: None)
    _cue.trigger = trigger if trigger is not None else _RaisingTrigger()
    _cue.volume = SimpleNamespace(flush_pending_saves=lambda: None)
    _cue.video_editor = SimpleNamespace(processing=False)
    _cue.sfx = SimpleNamespace(library=SimpleNamespace(maybe_rebuild=lambda: None))
    _cue.music = SimpleNamespace(library=SimpleNamespace(maybe_rebuild=lambda: None))
    # Force the slow lane to fire so it's exercised too.
    _runtime._cue_slow_tick_last = 0.0


def test_tick_guard_contains_fast_lane_error(isolated_cue, captured_log):
    _install_tick_collaborators()

    _cue_tick_trigger = _runtime._cue_tick_trigger
    _cue_tick_trigger()  # trigger.tick raises -> must not propagate

    assert any(c[0].startswith("TICK-ERR") for c in captured_log)


def test_tick_guard_contains_slow_lane_error(isolated_cue, captured_log):
    _install_tick_collaborators(trigger=SimpleNamespace(tick=lambda *a, **k: None))
    _cue.volume = SimpleNamespace(flush_pending_saves=lambda: None)
    _cue.video_editor = SimpleNamespace(processing=True, job_queue=SimpleNamespace(poll=lambda: None))
    _cue.sfx = SimpleNamespace(library=SimpleNamespace(maybe_rebuild=lambda: None))
    _cue.music = SimpleNamespace(library=SimpleNamespace(maybe_rebuild=_boom))

    _cue_tick_trigger = _runtime._cue_tick_trigger
    _cue_tick_trigger()  # slow-lane maybe_rebuild raises -> must not propagate

    assert any(c[0].startswith("TICK-ERR") for c in captured_log)


def test_refresh_context_guard_contains_collaborator_error(isolated_cue, captured_log, monkeypatch):
    # Top layer resolves to a real scene; music capture blows up right after.
    monkeypatch.setattr(_runtime, "_cue_get_top_layer", lambda: ("scene_name", "image", object()))
    _cue.vid_manager = SimpleNamespace(channel=None)
    _cue.current_file = ""
    _cue.top_layer_type = None
    _cue.music = SimpleNamespace(capture_display=_boom)

    _cue_refresh_context = _runtime._cue_refresh_context
    _cue_refresh_context()  # capture_display raises -> must not propagate

    assert any(c[0].startswith("REFRESH-CTX-ERR") for c in captured_log)


# ==========================================================================
# _cue_toggle_intensity_flag -- per-video intensity toggle persistence
# ==========================================================================


def test_toggle_intensity_flag_no_current_file(cue):
    cue.current_file = ""
    _markers._cue_toggle_intensity_flag("enabled")
    assert cue.calls == {}


def test_toggle_intensity_flag_no_entry_noop(cue):
    cue.current_file = "scene.ogv"
    _markers._cue_toggle_intensity_flag("enabled")
    assert "markers.save_marker" not in cue.calls


def test_toggle_intensity_flag_toggles_then_back(cue):
    cue.current_file = "scene.ogv"
    entry = {"intensity": {"enabled": True}}
    cue.markers.get = lambda key, default=None: entry if key == "v_scene.ogv" else default
    _markers._cue_toggle_intensity_flag("enabled")
    assert entry["intensity"]["enabled"] is False
    assert cue.calls["markers.save_marker"] == [(("v_scene.ogv",), {})]
    _markers._cue_toggle_intensity_flag("enabled")
    assert entry["intensity"]["enabled"] is True


def test_toggle_intensity_flag_absent_defaults_on(cue):
    cue.current_file = "scene.ogv"
    # A real video entry; the flag field itself is absent (reads as on).
    entry = {"volume": 1.0}
    cue.markers.get = lambda key, default=None: entry if key == "v_scene.ogv" else default
    _markers._cue_toggle_intensity_flag("volume")
    # The default is on, so the first toggle flips it off.
    assert entry["intensity"]["volume"] is False
    assert "frequency" not in entry["intensity"]
