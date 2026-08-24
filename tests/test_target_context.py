# -*- coding: utf-8 -*-
# Tests for the SFX library target-context selection (_cue.markers.target_context):
# the CueContextType enum, availability-driven mutating fallback, and the
# send_target dispatch used by the unified [+] button.

import pytest

from cue_lib.constants import CueContextType
from cue_lib.marker_store import CueMarkerStore
from cue_lib.markers import CueMarkerManager
from cue_lib.state import CueContext
from cue_lib.util import create_dlg_key, create_img_key, create_vid_key

from tests.fakes import FakeRecent, FakeSfxManager, FakeVidManager


@pytest.fixture
def mgr(cue_env):
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    ctx = CueContext()
    vid = FakeVidManager(duration=10.0)
    sfx = FakeSfxManager(files=["a.ogg", "b.ogg"])
    return CueMarkerManager(ctx, store, vid, sfx, None, None)


# --- scene-state helpers: the same flags the SFX page derives ---


def _set_video(mgr):
    mgr._ctx.top_layer_type = "movie"
    mgr._ctx.current_file = "video.mp4"
    mgr._ctx.current_dialogue = ""


def _set_image(mgr):
    mgr._ctx.top_layer_type = ""
    mgr._ctx.current_file = "img.png"
    mgr._ctx.current_dialogue = ""


def _set_menu(mgr):
    mgr._ctx.top_layer_type = ""
    mgr._ctx.current_file = ""
    mgr._ctx.current_dialogue = ""


# --- set_target_context ---


def test_default_target_is_video(mgr):
    assert mgr.target_context == CueContextType.VIDEO


def test_set_target_context_valid(mgr):
    mgr.set_target_context(CueContextType.IMAGE)
    assert mgr.target_context == CueContextType.IMAGE
    mgr.set_target_context(CueContextType.DIALOGUE)
    assert mgr.target_context == CueContextType.DIALOGUE
    mgr.set_target_context(CueContextType.LOOP)
    assert mgr.target_context == CueContextType.LOOP


def test_set_target_context_rejects_invalid(mgr):
    mgr.set_target_context("bogus")
    assert mgr.target_context == CueContextType.VIDEO


# --- resolve_target_context (mutating fallback) ---


def test_resolve_keeps_selected_when_available(mgr):
    _set_video(mgr)
    mgr.set_target_context(CueContextType.VIDEO)
    assert mgr.resolve_target_context() == CueContextType.VIDEO


def test_resolve_falls_back_video_to_image(mgr):
    _set_image(mgr)
    mgr.set_target_context(CueContextType.VIDEO)
    assert mgr.resolve_target_context() == CueContextType.IMAGE
    assert mgr.target_context == CueContextType.IMAGE


def test_resolve_falls_back_image_to_video(mgr):
    _set_video(mgr)
    mgr.set_target_context(CueContextType.IMAGE)
    assert mgr.resolve_target_context() == CueContextType.VIDEO
    assert mgr.target_context == CueContextType.VIDEO


def test_resolve_falls_back_dialogue_to_on_screen(mgr):
    _set_video(mgr)
    mgr.set_target_context(CueContextType.DIALOGUE)
    assert mgr.resolve_target_context() == CueContextType.VIDEO

    _set_image(mgr)
    mgr.set_target_context(CueContextType.DIALOGUE)
    assert mgr.resolve_target_context() == CueContextType.IMAGE


def test_resolve_keeps_dialogue_when_available(mgr):
    _set_video(mgr)
    mgr._ctx.current_dialogue = "a line"
    mgr.set_target_context(CueContextType.DIALOGUE)
    assert mgr.resolve_target_context() == CueContextType.DIALOGUE


def test_resolve_keeps_loop(mgr):
    _set_menu(mgr)
    mgr.set_target_context(CueContextType.LOOP)
    assert mgr.resolve_target_context() == CueContextType.LOOP


def test_resolve_menu_state_keeps_selection(mgr):
    # Neither video nor image on screen: no fallback, selection stays put.
    _set_menu(mgr)
    mgr.set_target_context(CueContextType.VIDEO)
    assert mgr.resolve_target_context() == CueContextType.VIDEO


# --- target_is_available ---


def test_target_is_available(mgr):
    _set_video(mgr)
    assert mgr.target_is_available(CueContextType.VIDEO)
    assert not mgr.target_is_available(CueContextType.IMAGE)
    assert not mgr.target_is_available(CueContextType.DIALOGUE)
    assert mgr.target_is_available(CueContextType.LOOP)

    _set_image(mgr)
    assert not mgr.target_is_available(CueContextType.VIDEO)
    assert mgr.target_is_available(CueContextType.IMAGE)

    _set_menu(mgr)
    assert not mgr.target_is_available(CueContextType.VIDEO)
    assert not mgr.target_is_available(CueContextType.IMAGE)


# --- send_target dispatch ---


def test_send_target_file_dispatch(mgr):
    _set_image(mgr)
    mgr.set_target_context(CueContextType.IMAGE)
    mgr.send_target("file", 0)
    assert mgr.image.get_active_pool().get("files") == ["a.ogg"]


def test_send_target_resolves_before_dispatch(mgr):
    # Video selected but an image is on screen: [+] routes to the image pool.
    _set_image(mgr)
    mgr.set_target_context(CueContextType.VIDEO)
    mgr.send_target("file", 0)
    assert mgr.image.get_active_pool().get("files") == ["a.ogg"]


def test_send_target_folder_dispatch(mgr):
    _set_video(mgr)
    mgr.set_target_context(CueContextType.VIDEO)
    mgr.send_target("folder", "sfx/booms/")
    assert mgr.video.get_active_pool().get("files") == ["sfx/booms/"]


def test_send_target_preset_dispatch(mgr):
    _set_image(mgr)
    mgr.create_preset("wub", {"files": ["a.ogg"], "volume": 1.0})
    mgr.set_target_context(CueContextType.IMAGE)
    mgr.send_target("preset", "wub")
    assert mgr.image.get_active_pool().get("preset") == "wub"


def test_send_target_record_flag(mgr):
    _set_image(mgr)
    mgr._sfx_manager._recent = FakeRecent()
    mgr.set_target_context(CueContextType.IMAGE)
    mgr.send_target("file", 0, record=False)
    assert mgr._sfx_manager._recent.calls == []
    mgr.send_target("file", 0, record=True)
    assert mgr._sfx_manager._recent.calls == [("file", "a.ogg")]


# --- target_active_label (context bar second line) ---


def test_target_active_label_no_pool(mgr):
    _set_image(mgr)
    mgr.set_target_context(CueContextType.IMAGE)
    assert mgr.target_active_label() == "No pool yet.  Click + to create one."


def test_target_active_label_pool(mgr):
    _set_image(mgr)
    mgr.send_target("file", 0)
    assert mgr.target_active_label() == "Pool 1"


def test_target_active_label_second_pool(mgr):
    _set_image(mgr)
    mgr.send_target("file", 0)
    mgr.image.add_pool()
    assert mgr.target_active_label() == "Pool 2"


def test_target_active_label_video_time(mgr):
    _set_video(mgr)
    mgr.send_target("file", 0)
    assert mgr.target_active_label() == "Pool 1 @ 00:00.00"


# --- _cue_send_level_to_target (intensity level hook) ---


def _hook_target(mgr, ctx_id, monkeypatch):
    import cue_lib.markers as _markers

    mgr.set_target_context(ctx_id)
    monkeypatch.setattr(_markers._cue, "markers", mgr)
    return _markers


def test_send_level_to_video_sets_hook(mgr, monkeypatch):
    _set_video(mgr)
    _markers = _hook_target(mgr, CueContextType.VIDEO, monkeypatch)
    _markers._cue_send_level_to_target("Impacts", 2)
    pool = mgr.video.get_active_pool()
    assert pool["igroup"] == "Impacts"
    assert pool["ilevel_id"] == 2
    assert pool["files"] == []


def test_send_level_to_video_stamps_time(mgr, monkeypatch):
    _set_video(mgr)
    _markers = _hook_target(mgr, CueContextType.VIDEO, monkeypatch)
    _markers._cue_send_level_to_target("Impacts", 1)
    pool = mgr.video.get_active_pool()
    assert "time" in pool
    assert mgr.video._key() == create_vid_key("video.mp4")


def test_send_level_to_loop_sets_hook(mgr, monkeypatch):
    _set_menu(mgr)
    _markers = _hook_target(mgr, CueContextType.LOOP, monkeypatch)
    _markers._cue_send_level_to_target("Impacts", 1)
    pool = mgr.loop.get_active_pool()
    assert pool["igroup"] == "Impacts"
    assert pool["ilevel_id"] == 1


def test_send_level_noop_for_image_target(mgr, monkeypatch):
    _set_image(mgr)
    _markers = _hook_target(mgr, CueContextType.IMAGE, monkeypatch)
    _markers._cue_send_level_to_target("Impacts", 1)
    assert mgr.get(create_img_key("img.png")) is None


def test_send_level_noop_for_dialogue_target(mgr, monkeypatch):
    _set_video(mgr)
    mgr._ctx.current_dialogue = "a line"
    _markers = _hook_target(mgr, CueContextType.DIALOGUE, monkeypatch)
    _markers._cue_send_level_to_target("Impacts", 1)
    assert mgr.get(create_dlg_key(("video.mp4", "a line"))) is None


def test_send_level_noop_when_video_has_no_key(mgr, monkeypatch):
    # Video context with no current file -> empty _key() -> no-op, no entry.
    _set_menu(mgr)
    _markers = _hook_target(mgr, CueContextType.VIDEO, monkeypatch)
    _markers._cue_send_level_to_target("Impacts", 1)
    assert mgr.video._key() == ""
    assert mgr._data == {}


def test_send_level_tt_disabled_for_image(mgr, monkeypatch):
    import cue_lib.markers as _markers

    _set_image(mgr)
    mgr.set_target_context(CueContextType.IMAGE)
    monkeypatch.setattr(_markers._cue, "markers", mgr)
    assert "Video or Loop" in _markers._cue_send_level_to_target_tt()
