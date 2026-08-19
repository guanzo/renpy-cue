# -*- coding: utf-8 -*-
# Tests for cue_lib.audio.music: the music-channel interceptor
# (play/queue/stop wrapping), the per-replay default-trigger log, music
# trigger editing, and the scene-music override pool.
#
# The manager is built against a real CueMarkerStore + CueDatabase on tmp
# paths; the mock renpy.audio.music registry records every play/stop so
# interception is asserted on real channel state.

import os
import types

import pytest

import renpy as _renpy
import renpy.audio.music as _music_mock
import renpy.store as _store

import cue_lib.audio.music as _music_mod
from cue_lib.constants import (
    CUE_GAME_MUSIC_FOLDER, CUE_MUSIC_PREFIX, CUE_MY_MUSIC_FOLDER,
)
from cue_lib.audio.music import (
    CUE_DEFAULT_MUSIC_CHANNEL, CUE_MUSIC_GAME_TAG, CUE_MUSIC_USER_TAG,
    _SUPPRESS_MUSIC, CueMusicManager,
)
from cue_lib.marker_store import CueMarkerStore
from cue_lib.state import CueContext
from tests.fakes import FakeRecent

# The mock module's un-wrapped functions, captured at import time (before any
# install() has replaced them).  Each test fixture restores these so no
# wrapper leaks across tests.
_MUSIC_PLAY_ORIG = _music_mock.play
_MUSIC_QUEUE_ORIG = _music_mock.queue
_MUSIC_STOP_ORIG = _music_mock.stop


def _set_scene(mgr, file, layer):
    mgr._ctx.current_file = file
    mgr._ctx.top_layer_type = layer


@pytest.fixture
def mgr(cue_env, monkeypatch):
    _music_mock.play = _MUSIC_PLAY_ORIG
    _music_mock.queue = _MUSIC_QUEUE_ORIG
    _music_mock.stop = _MUSIC_STOP_ORIG
    _music_mock._reset_all()
    monkeypatch.setattr(_music_mod, "_ORIGINALS", None)
    monkeypatch.setattr(_renpy, "in_rollback", lambda: False)
    _store._in_replay = False
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    m = CueMusicManager(CueContext(), store, cue_env.db, cue_env.paths)
    return m


# ==========================================================================
# install / _ORIGINALS caching
# ==========================================================================

def test_install_wraps_music_functions(mgr):
    mgr.install()
    # Bound-method identity: __self__ pins the wrapped manager.
    assert _music_mock.play.__self__ is mgr
    assert _music_mock.queue.__self__ is mgr
    assert _music_mock.stop.__self__ is mgr
    assert mgr._is_installed is True
    assert mgr._triggers == {}  # load_triggers ran


def test_install_second_call_no_double_wrap(mgr):
    mgr.install()
    first = _music_mock.play
    mgr.install()
    assert _music_mock.play is first


def test_install_caches_originals_across_managers(mgr, cue_env):
    mgr.install()
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    m2 = CueMusicManager(CueContext(), store, cue_env.db, cue_env.paths)
    m2.install()
    assert m2._original_music_play is _MUSIC_PLAY_ORIG
    assert m2._original_music_queue is _MUSIC_QUEUE_ORIG
    assert m2._original_music_stop is _MUSIC_STOP_ORIG


# ==========================================================================
# play_untracked / now_playing
# ==========================================================================

def test_play_untracked_relative_volume(mgr, monkeypatch):
    fake = types.SimpleNamespace(_has_relative_volume=True)
    monkeypatch.setattr(_music_mod, "_cue", fake)
    mgr.install()
    mgr.play_untracked("music/song.ogg", volume=0.5)
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == "music/song.ogg"


def test_play_untracked_absolute_volume(mgr, monkeypatch):
    fake = types.SimpleNamespace(_has_relative_volume=False)
    monkeypatch.setattr(_music_mod, "_cue", fake)
    mgr.install()
    mgr.play_untracked("music/song.ogg", volume=0.5)
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["volume"] == 0.5


def test_now_playing_strips_root(mgr):
    root = mgr._paths.root
    _music_mock.play(root + "/" + CUE_MUSIC_PREFIX + "song.ogg",
                     channel=CUE_DEFAULT_MUSIC_CHANNEL)
    # My Music files are reported under the synthetic "My Music/" display
    # folder -- the data-model "music/" prefix is stripped.
    assert mgr.now_playing() == CUE_MY_MUSIC_FOLDER + "song.ogg"


def test_now_playing_none_when_idle(mgr):
    assert mgr.now_playing() is None


def test_now_playing_exception(mgr, monkeypatch):
    def _boom(channel="music", **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_music_mock, "get_playing", _boom)
    assert mgr.now_playing() is None


def test_now_playing_game_relative_unchanged(mgr):
    _music_mock.play("music/bgm.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    # Game-music files play game-relative and are reported under the
    # synthetic "Game Music/" display folder.
    assert mgr.now_playing() == CUE_GAME_MUSIC_FOLDER + "music/bgm.ogg"


# ==========================================================================
# _on_play / _on_queue / _on_stop interception
# ==========================================================================

def test_on_play_records_and_forwards(mgr):
    mgr.install()
    _music_mock.play("song.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert mgr.last_event["type"] == "play"
    assert mgr.last_event["channel"] == CUE_DEFAULT_MUSIC_CHANNEL
    assert mgr.last_event["filenames"] == "song.ogg"
    assert mgr.last_event["in_replay"] is False
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == "song.ogg"


def test_on_play_channel_from_args_skips_non_music(mgr):
    mgr.install()
    _music_mock.play("song.ogg", "sfx_ch")
    assert mgr.last_event is None
    assert _music_mock._registry["sfx_ch"]["playing"] == "song.ogg"


def test_on_play_default_channel(mgr):
    mgr.install()
    _music_mock.play("song.ogg")
    assert mgr.last_event["channel"] == CUE_DEFAULT_MUSIC_CHANNEL


def test_on_play_replay_override_filepath(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "music/default.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "custom.ogg"],
                                  "music_default_disabled": True}
    _music_mock.play("scripted.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == \
        mgr._paths.music_dir + "custom.ogg"


def test_on_play_replay_override_args_form(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "music/default.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "custom.ogg"],
                                  "music_default_disabled": True}
    _music_mock.play("scripted.ogg", CUE_DEFAULT_MUSIC_CHANNEL)
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == \
        mgr._paths.music_dir + "custom.ogg"


def test_on_play_replay_override_filenames_kwarg(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "music/default.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "custom.ogg"],
                                  "music_default_disabled": True}
    _music_mock.play(filenames="scripted.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == \
        mgr._paths.music_dir + "custom.ogg"


def test_on_play_replay_override_suppress(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "music/default.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [], "music_default_disabled": True}
    assert _music_mock.play("scripted.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL) is None
    assert _music_mock.get_playing(CUE_DEFAULT_MUSIC_CHANNEL) is None


def test_on_play_replay_no_override_untouched(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    # no default trigger anchored here -> override None, forwarded unchanged
    _music_mock.play("scripted.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == "scripted.ogg"
    assert mgr.last_event is not None


def test_on_play_non_music_channel_in_replay_forwarded(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _music_mock.play("sfx.ogg", channel="sound")
    assert mgr.last_event is None
    assert _music_mock._registry["sound"]["playing"] == "sfx.ogg"


def test_on_queue_records(mgr):
    mgr.install()
    _music_mock.queue("song.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert mgr.last_event["type"] == "queue"
    assert mgr.last_event["filenames"] == "song.ogg"
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["queue"] == ["song.ogg"]


def test_on_queue_non_music_skipped(mgr):
    mgr.install()
    _music_mock.queue("sfx.ogg", channel="sound")
    assert mgr.last_event is None


def test_on_stop_records(mgr):
    mgr.install()
    _music_mock.play("song.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    _music_mock.stop(channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert mgr.last_event["type"] == "stop"
    assert mgr.last_event["filenames"] is None
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] is None


def test_on_stop_non_music_skipped(mgr):
    mgr.install()
    _music_mock.stop("sound")
    assert mgr.last_event is None


def test_record_exception_silently_swallowed(mgr, monkeypatch):
    mgr.install()

    def _boom(filenames, in_replay):
        raise RuntimeError("boom")

    monkeypatch.setattr(mgr, "_record_default_trigger", _boom)
    _music_mock.play("song.ogg", channel=CUE_DEFAULT_MUSIC_CHANNEL)
    assert mgr.last_event["type"] == "play"  # set before the record step
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == "song.ogg"


# ==========================================================================
# _current_scene_key
# ==========================================================================

def test_current_scene_key_empty_without_file(mgr):
    assert mgr._current_scene_key() == ""


def test_current_scene_key_movie(mgr):
    _set_scene(mgr, "scene.ogv", "movie")
    assert mgr._current_scene_key() == "v_scene.ogv"


def test_current_scene_key_image(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    assert mgr._current_scene_key() == "i_scene.ogv"


# ==========================================================================
# _record_default_trigger / capture_display
# ==========================================================================

def test_record_default_trigger_skips_not_in_replay(mgr):
    mgr._record_default_trigger("music/a.ogg", False)
    assert mgr._triggers == {}
    assert mgr._pending is None


def test_record_default_trigger_skips_rollback(mgr, monkeypatch):
    monkeypatch.setattr(_renpy, "in_rollback", lambda: True)
    mgr._record_default_trigger("music/a.ogg", "replay1")
    assert mgr._triggers == {}


def test_record_default_trigger_unwraps_list(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    mgr._record_default_trigger(["music/a.ogg", "music/b.ogg"], "replay1")
    assert mgr._triggers["replay1"][0]["filepath"] == "music/a.ogg"


def test_record_default_trigger_empty_list(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    mgr._record_default_trigger([], "replay1")
    assert mgr._triggers == {}


def test_record_default_trigger_skips_no_scene(mgr):
    mgr._record_default_trigger("music/a.ogg", "replay1")
    assert mgr._triggers == {}


def test_record_default_trigger_appends_new(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    mgr._record_default_trigger("music/a.ogg", "replay1")
    assert mgr._triggers["replay1"] == \
        [{"key_before": "i_scene.ogv", "filepath": "music/a.ogg"}]
    assert mgr._pending == {
        "replay_id": "replay1", "key_before": "i_scene.ogv", "filepath": "music/a.ogg"}


def test_record_default_trigger_updates_existing(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "old.ogg"}]
    mgr._record_default_trigger("music/a.ogg", "replay1")
    assert mgr._triggers["replay1"][0]["filepath"] == "music/a.ogg"
    assert len(mgr._triggers["replay1"]) == 1


def test_capture_display_no_pending(mgr):
    mgr.capture_display()
    assert mgr._pending is None


def test_capture_display_rollback_skips(mgr, monkeypatch):
    monkeypatch.setattr(_renpy, "in_rollback", lambda: True)
    mgr._pending = {"replay_id": "replay1", "key_before": "i_old.ogv", "filepath": "m.ogg"}
    mgr.capture_display()
    assert mgr._pending is not None  # untouched


def test_capture_display_replay_mismatch(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay2")
    mgr._pending = {"replay_id": "replay1", "key_before": "i_old.ogv", "filepath": "m.ogg"}
    mgr.capture_display()
    assert mgr._pending is None


def test_capture_display_no_scene_change(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._pending = {"replay_id": "replay1", "key_before": "i_scene.ogv", "filepath": "m.ogg"}
    mgr.capture_display()
    assert mgr._pending is None
    assert "i_scene.ogv" not in mgr._triggers  # nothing to annotate


def test_capture_display_records_key_after(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "new.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_old.ogv", "filepath": "m.ogg"}]
    mgr._pending = {"replay_id": "replay1", "key_before": "i_old.ogv", "filepath": "m.ogg"}
    mgr.capture_display()
    assert mgr._pending is None
    assert mgr._triggers["replay1"][0]["key_after"] == "i_new.ogv"


def test_capture_display_no_matching_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "new.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_other.ogv", "filepath": "m.ogg"}]
    mgr._pending = {"replay_id": "replay1", "key_before": "i_old.ogv", "filepath": "m.ogg"}
    mgr.capture_display()
    assert mgr._pending is None
    assert "key_after" not in mgr._triggers["replay1"][0]


# ==========================================================================
# triggers_for / selection / scene-key helpers
# ==========================================================================

def test_triggers_for_sorted(mgr):
    mgr._triggers = {
        "replay1": [
            {"key_before": "i_b.ogv", "filepath": "b.ogg"},
            {"key_before": "i_a.ogv", "filepath": "a.ogg"},
        ],
    }
    assert [t["key_before"] for t in mgr.triggers_for("replay1")] == \
        ["i_a.ogv", "i_b.ogv"]


def test_triggers_for_unknown_replay(mgr):
    assert mgr.triggers_for(None) == []


def test_select_trigger_sets_key(mgr):
    mgr.select_trigger("i_scene.ogv")
    assert mgr.selected_key == "i_scene.ogv"


def test_selected_trigger_label_strips_prefix(mgr):
    mgr.selected_key = "v_scene.ogv"
    assert mgr.selected_trigger_label() == "scene.ogv"


def test_selected_trigger_label_empty(mgr):
    assert mgr.selected_trigger_label() == ""


def test_current_scene_has_trigger_falsy_key(mgr):
    assert mgr._current_scene_has_trigger("") is False


def test_current_scene_has_trigger_default(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._triggers["replay1"] = [{"key_before": "i_a.ogv", "key_after": "i_b.ogv",
                                 "filepath": "m.ogg"}]
    assert mgr._current_scene_has_trigger("i_a.ogv") is True
    assert mgr._current_scene_has_trigger("i_b.ogv") is True


def test_current_scene_has_trigger_custom(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._store["i_c.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "x.ogg"], "replay": "replay1"}
    assert mgr._current_scene_has_trigger("i_c.ogv") is True


def test_current_scene_has_trigger_other_replay(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._store["i_c.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "x.ogg"], "replay": "other"}
    assert mgr._current_scene_has_trigger("i_c.ogv") is False


def test_resolve_selection_auto_selects_scene_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    assert mgr._resolve_selection() == "i_scene.ogv"
    assert mgr.selected_key == "i_scene.ogv"


def test_resolve_selection_keeps_manual_pick(mgr):
    mgr.selected_key = "v_manual.ogv"
    _set_scene(mgr, "scene.ogv", "image")
    # scene has no trigger -> manual pick survives
    assert mgr._resolve_selection() == "v_manual.ogv"
    assert mgr.selected_key == "v_manual.ogv"


def test_resolve_selection_stable_within_scene(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    mgr.selected_key = "v_manual.ogv"
    mgr._last_auto_scene = "i_scene.ogv"
    assert mgr._resolve_selection() == "v_manual.ogv"


# ==========================================================================
# add_custom_trigger / default_path_for / default helpers
# ==========================================================================

def test_add_custom_trigger_no_scene(mgr):
    mgr.add_custom_trigger()
    assert mgr.selected_key is None
    assert dict(mgr._store.items()) == {}


def test_add_custom_trigger_creates_entry(mgr):
    _set_scene(mgr, "scene.ogv", "image")
    mgr.add_custom_trigger()
    assert mgr.selected_key == "i_scene.ogv"
    assert mgr._store.get("i_scene.ogv")["music"] == []


def test_default_path_for_found(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._triggers["replay1"] = [{"key_after": "i_a.ogv", "filepath": "m.ogg"}]
    assert mgr.default_path_for("i_a.ogv") == "m.ogg"


def test_default_path_for_none(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    assert mgr.default_path_for("i_x.ogv") is None


def test_default_trigger_by_key_before(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    trig = {"key_before": "i_a.ogv", "filepath": "m.ogg"}
    mgr._triggers["replay1"] = [trig]
    assert mgr._default_trigger_by_key_before("i_a.ogv") is trig
    assert mgr._default_trigger_by_key_before("i_b.ogv") is None


def test_is_default_trigger_scene(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._triggers["replay1"] = [{"key_before": "i_a.ogv", "filepath": "m.ogg"}]
    assert mgr._is_default_trigger_scene("i_a.ogv") is True
    assert mgr._is_default_trigger_scene("i_b.ogv") is False


# ==========================================================================
# music ref resolution
# ==========================================================================

def test_resolve_music_files_dedupes_direct(mgr):
    assert mgr.resolve_music_files(["a.ogg", "a.ogg", "b.ogg"]) == ["a.ogg", "b.ogg"]


def test_resolve_music_files_user_folder(mgr):
    mgr.user_music.files = ["music/song.ogg", "music/sub/t.ogg"]
    assert mgr.resolve_music_files([CUE_MUSIC_USER_TAG + "music/"]) == \
        ["music/song.ogg", "music/sub/t.ogg"]


def test_resolve_music_files_game_folder(mgr):
    mgr.game_music.files = ["music/bgm.ogg"]
    assert mgr.resolve_music_files([CUE_MUSIC_GAME_TAG + "music/"]) == ["music/bgm.ogg"]


def test_resolve_music_files_legacy_folder_both(mgr):
    mgr.user_music.files = ["music/user.ogg"]
    mgr.game_music.files = ["music/game.ogg"]
    assert mgr.resolve_music_files(["music/"]) == ["music/user.ogg", "music/game.ogg"]


def test_split_ref_tag(mgr):
    assert mgr._split_ref_tag(CUE_MUSIC_USER_TAG + "music/") == (CUE_MUSIC_USER_TAG, "music/")
    assert mgr._split_ref_tag(CUE_MUSIC_GAME_TAG + "x.ogg") == (CUE_MUSIC_GAME_TAG, "x.ogg")
    assert mgr._split_ref_tag("x.ogg") == (None, "x.ogg")


def test_ref_path_strips_tag(mgr):
    assert mgr.ref_path(CUE_MUSIC_USER_TAG + "music/x.ogg") == "music/x.ogg"
    assert mgr.ref_path("music/x.ogg") == "music/x.ogg"


def test_resolve_music_path_user_prefixed(mgr):
    assert mgr._resolve_music_path(CUE_MUSIC_USER_TAG + "music/x.ogg") == \
        mgr._paths.music_dir + "x.ogg"


def test_resolve_music_path_user_bare(mgr):
    assert mgr._resolve_music_path(CUE_MUSIC_USER_TAG + "x.ogg") == \
        mgr._paths.music_dir + "x.ogg"


def test_resolve_music_path_game(mgr):
    assert mgr._resolve_music_path(CUE_MUSIC_GAME_TAG + "music/x.ogg") == "music/x.ogg"


def test_resolve_music_path_legacy_disk_found(mgr):
    root = mgr._paths.root
    music_dir = mgr._paths.music_dir  # created by db.open() in the fixture
    open(os.path.join(music_dir, "song.ogg"), "w").close()
    stored = root.rstrip("/") + "/music/song.ogg"
    assert mgr._resolve_music_path(stored) == music_dir + "song.ogg"


def test_resolve_music_path_legacy_music_prefix(mgr):
    music_dir = mgr._paths.music_dir  # created by db.open() in the fixture
    open(os.path.join(music_dir, "song.ogg"), "w").close()
    assert mgr._resolve_music_path("music/song.ogg") == music_dir + "song.ogg"


def test_resolve_music_path_legacy_disk_missing(mgr):
    stored = "music/nope.ogg"
    assert mgr._resolve_music_path(stored) == stored


def test_music_pool_for_default_plus_custom(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._triggers["replay1"] = [{"key_after": "i_a.ogv", "filepath": "music/default.ogg"}]
    mgr._store["i_a.ogv"] = {"music": [CUE_MUSIC_GAME_TAG + "music/custom.ogg"]}
    assert mgr.music_pool_for("i_a.ogv") == ["music/default.ogg", "music/custom.ogg"]


def test_music_pool_for_default_disabled(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._triggers["replay1"] = [{"key_after": "i_a.ogv", "filepath": "music/default.ogg"}]
    mgr._store["i_a.ogv"] = {"music": [], "music_default_disabled": True}
    assert mgr.music_pool_for("i_a.ogv") == []


def test_music_pool_for_empty(mgr, monkeypatch):
    assert mgr.music_pool_for("i_x.ogv") == []


# ==========================================================================
# trigger editing
# ==========================================================================

def test_add_user_song_to_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "music/default.ogg"}]
    mgr.add_user_song_to_trigger("music/song.ogg")
    assert mgr._store.get("i_scene.ogv")["music"] == \
        [CUE_MUSIC_USER_TAG + "music/song.ogg"]


def test_add_game_song_to_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr.add_game_song_to_trigger("music/bgm.ogg")
    assert mgr._store.get("i_scene.ogv")["music"] == [CUE_MUSIC_GAME_TAG + "music/bgm.ogg"]


def test_add_game_folder_to_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr.add_game_folder_to_trigger("music/sub")
    assert mgr._store.get("i_scene.ogv")["music"] == [CUE_MUSIC_GAME_TAG + "music/sub/"]


def test_add_user_folder_to_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr.add_user_folder_to_trigger("music/sub")
    assert mgr._store.get("i_scene.ogv")["music"] == [CUE_MUSIC_USER_TAG + "music/sub/"]


def test_add_ref_to_trigger_no_selection(mgr):
    mgr._add_ref_to_trigger(CUE_MUSIC_USER_TAG + "x.ogg")
    assert dict(mgr._store.items()) == {}


def test_add_ref_to_trigger_no_duplicate(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr.add_user_song_to_trigger("music/song.ogg")
    mgr.add_user_song_to_trigger("music/song.ogg")
    assert mgr._store.get("i_scene.ogv")["music"] == \
        [CUE_MUSIC_USER_TAG + "music/song.ogg"]


# ==========================================================================
# recently used recording (add-to-trigger attempts only)
# ==========================================================================

def _wire_recent(mgr):
    # type: (CueMusicManager) -> FakeRecent
    """Attach a recording stand-in and return it."""
    recent = FakeRecent()
    mgr._recent = recent
    return recent


def test_add_user_song_records_recent(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    recent = _wire_recent(mgr)
    mgr.add_user_song_to_trigger("music/song.ogg")
    assert recent.calls == [("file", CUE_MUSIC_USER_TAG + "music/song.ogg")]


def test_add_game_song_records_recent(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    recent = _wire_recent(mgr)
    mgr.add_game_song_to_trigger("bgm/x.ogg")
    assert recent.calls == [("file", CUE_MUSIC_GAME_TAG + "bgm/x.ogg")]


def test_add_folder_records_normalized_ref(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    recent = _wire_recent(mgr)
    mgr.add_user_folder_to_trigger("music/sub")
    assert recent.calls == [("folder", CUE_MUSIC_USER_TAG + "music/sub/")]


def test_add_ref_no_selection_still_records(mgr):
    recent = _wire_recent(mgr)
    mgr._add_ref_to_trigger(CUE_MUSIC_GAME_TAG + "x.ogg")
    assert recent.calls == [("file", CUE_MUSIC_GAME_TAG + "x.ogg")]
    assert dict(mgr._store.items()) == {}


def test_add_without_recent_is_noop(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    # _recent stays None (the default) -- the add still lands.
    mgr.add_user_song_to_trigger("music/song.ogg")
    assert mgr._store.get("i_scene.ogv")["music"] == \
        [CUE_MUSIC_USER_TAG + "music/song.ogg"]


def test_remove_song_from_trigger(mgr):
    mgr._store["i_a.ogv"] = {"music": ["u:x.ogg", "u:y.ogg"]}
    mgr.remove_song_from_trigger("i_a.ogv", "u:x.ogg")
    assert mgr._store.get("i_a.ogv")["music"] == ["u:y.ogg"]


def test_remove_song_from_trigger_missing_entry(mgr):
    mgr.remove_song_from_trigger("i_nope.ogv", "u:x.ogg")
    assert dict(mgr._store.items()) == {}


def test_remove_song_from_trigger_missing_path(mgr):
    mgr._store["i_a.ogv"] = {"music": ["u:x.ogg"]}
    mgr.remove_song_from_trigger("i_a.ogv", "u:zzz.ogg")
    assert mgr._store.get("i_a.ogv")["music"] == ["u:x.ogg"]


def test_music_toggle_file_ref_expand(mgr):
    mgr.toggle_file_ref_expand("u:music/")
    assert mgr.expanded_file_refs["u:music/"] is True
    mgr.toggle_file_ref_expand("u:music/")
    assert mgr.expanded_file_refs["u:music/"] is False


def test_remove_song_from_folder_ref(mgr):
    mgr.user_music.files = ["music/a.ogg", "music/b.ogg"]
    mgr._store["i_a.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "music/"]}
    mgr.remove_song_from_folder_ref("i_a.ogv", 0, "music/a.ogg")
    assert mgr._store.get("i_a.ogv")["music"] == [CUE_MUSIC_USER_TAG + "music/b.ogg"]


def test_remove_song_from_folder_ref_missing_entry(mgr):
    mgr.remove_song_from_folder_ref("i_nope.ogv", 0, "music/a.ogg")
    assert dict(mgr._store.items()) == {}


def test_remove_song_from_folder_ref_index_oob(mgr):
    mgr._store["i_a.ogv"] = {"music": [CUE_MUSIC_USER_TAG + "music/"]}
    mgr.remove_song_from_folder_ref("i_a.ogv", 5, "music/a.ogg")
    assert mgr._store.get("i_a.ogv")["music"] == [CUE_MUSIC_USER_TAG + "music/"]


def test_remove_song_from_folder_ref_not_folder(mgr):
    mgr._store["i_a.ogv"] = {"music": ["u:music/x.ogg"]}
    mgr.remove_song_from_folder_ref("i_a.ogv", 0, "u:music/x.ogg")
    assert mgr._store.get("i_a.ogv")["music"] == ["u:music/x.ogg"]


def test_toggle_default(mgr):
    mgr.toggle_default("i_a.ogv")
    assert mgr._store.get("i_a.ogv")["music_default_disabled"] is True
    mgr.toggle_default("i_a.ogv")
    assert mgr._store.get("i_a.ogv")["music_default_disabled"] is False


def test_delete_trigger(mgr):
    mgr._store["i_a.ogv"] = {"music": ["u:x.ogg"], "music_default_disabled": True}
    mgr.selected_key = "i_a.ogv"
    mgr.delete_trigger("i_a.ogv")
    entry = mgr._store.get("i_a.ogv")
    assert "music" not in entry
    assert "music_default_disabled" not in entry
    assert mgr.selected_key is None
    assert mgr._last_auto_scene is None


def test_delete_trigger_missing_entry(mgr):
    mgr.delete_trigger("i_nope.ogv")
    assert dict(mgr._store.items()) == {}


# ==========================================================================
# triggers() listing
# ==========================================================================

def test_triggers_default_deduped(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._triggers["replay1"] = [
        {"key_before": "i_a.ogv", "key_after": "i_b.ogv", "filepath": "m.ogg"},
        {"key_before": "i_b.ogv", "filepath": "n.ogg"},
    ]
    mgr._store["i_b.ogv"] = {"music": ["u:x.ogg"], "music_default_disabled": True}
    trigs = mgr.triggers()
    assert [t["key"] for t in trigs] == ["i_b.ogv"]  # key_after then key_before
    t = trigs[0]
    assert t["is_default"] is True
    assert t["default_path"] == "m.ogg"
    assert t["default_enabled"] is False
    assert t["songs"] == ["u:x.ogg"]


def test_triggers_custom_scoped_to_replay(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._store["i_a.ogv"] = {"music": ["u:x.ogg"], "replay": "replay1"}
    mgr._store["i_b.ogv"] = {"music": [], "replay": "other"}
    mgr._store["i_c.ogv"] = {}
    trigs = mgr.triggers()
    assert [t["key"] for t in trigs] == ["i_a.ogv"]
    assert trigs[0]["is_default"] is False
    assert trigs[0]["songs"] == ["u:x.ogg"]


def test_triggers_empty_music_trigger_listed(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._store["i_a.ogv"] = {"music": [], "replay": "replay1"}
    trigs = mgr.triggers()
    assert [t["key"] for t in trigs] == ["i_a.ogv"]
    assert trigs[0]["songs"] == []


def test_triggers_selected_flag(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr._store["i_a.ogv"] = {"music": [], "replay": "replay1"}
    mgr.selected_key = "i_a.ogv"
    assert mgr.triggers()[0]["selected"] is True


# ==========================================================================
# _pick_for_override / play_custom_music
# ==========================================================================

def test_pick_for_override_no_scene(mgr):
    assert mgr._pick_for_override() is None


def test_pick_for_override_no_trigger(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    assert mgr._pick_for_override() is None


def test_pick_for_override_untouched_without_pool(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    assert mgr._pick_for_override() is None  # entry absent -> untouched


def test_pick_for_override_pool_choice(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    fake_rand = types.SimpleNamespace(choice=lambda pool: pool[-1])
    monkeypatch.setattr(_music_mod, "random", fake_rand)
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_GAME_TAG + "a.ogg",
                                           CUE_MUSIC_GAME_TAG + "b.ogg"]}
    assert mgr._pick_for_override() == "b.ogg"


def test_pick_for_override_suppress(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [], "music_default_disabled": True}
    assert mgr._pick_for_override() is _SUPPRESS_MUSIC


def test_play_custom_music_plays_pool(mgr, monkeypatch):
    mgr.install()
    fake_rand = types.SimpleNamespace(choice=lambda pool: pool[0])
    monkeypatch.setattr(_music_mod, "random", fake_rand)
    _set_scene(mgr, "scene.ogv", "image")
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_GAME_TAG + "music/c.ogg"]}
    mgr.play_custom_music()
    assert _music_mock._registry[CUE_DEFAULT_MUSIC_CHANNEL]["playing"] == "music/c.ogg"


def test_play_custom_music_skips_rollback(mgr, monkeypatch):
    mgr.install()
    monkeypatch.setattr(_renpy, "in_rollback", lambda: True)
    _set_scene(mgr, "scene.ogv", "image")
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_GAME_TAG + "music/c.ogg"]}
    mgr.play_custom_music()
    assert CUE_DEFAULT_MUSIC_CHANNEL not in _music_mock._registry


def test_play_custom_music_skips_no_scene(mgr):
    mgr.install()
    mgr.play_custom_music()
    assert CUE_DEFAULT_MUSIC_CHANNEL not in _music_mock._registry


def test_play_custom_music_skips_default_trigger_scene(mgr, monkeypatch):
    monkeypatch.setattr(_store, "_in_replay", "replay1")
    mgr.install()
    _set_scene(mgr, "scene.ogv", "image")
    mgr._triggers["replay1"] = [{"key_before": "i_scene.ogv", "filepath": "m.ogg"}]
    mgr._store["i_scene.ogv"] = {"music": [CUE_MUSIC_GAME_TAG + "music/c.ogg"]}
    mgr.play_custom_music()
    assert CUE_DEFAULT_MUSIC_CHANNEL not in _music_mock._registry
