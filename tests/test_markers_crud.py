# -*- coding: utf-8 -*-
# Tests for cue_lib.markers context CRUD -- the pool operations the four
# context sub-objects (image / dialogue / video / loop) perform through the
# real CueMarkerManager graph (real store on cue_env, FakeVidManager /
# FakeSfxManager / FakeTrigger collaborators).
#
# test_markers_context.py covers the pure pool math against a minimal
# FakeManager; this file drives the real graph because the video add_folder /
# add_pool / apply_preset paths read _sfx_manager.files, _vid_manager
# get_elapsed(), and call _get_or_create_entry / _detach_pool / resolve_pool.

import pytest

import cue_lib.context as _context
from cue_lib.constants import CueExclusiveStart, CueLoopFrequency, CUE_VOLUME_DEFAULT
from cue_lib.marker_store import CueMarkerStore
from cue_lib.markers import CueMarkerManager
from cue_lib.state import CueContext
from cue_lib.util import create_img_key, create_vid_key, create_dlg_key, create_loop_key

from tests.fakes import FakeSfxManager, FakeTrigger, FakeVidManager


@pytest.fixture
def mgr(cue_env):
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    ctx = CueContext()
    vid = FakeVidManager(duration=10.0)
    sfx = FakeSfxManager()
    trigger = FakeTrigger()
    return CueMarkerManager(ctx, store, vid, sfx, trigger, None, None)


@pytest.fixture(autouse=True)
def _no_shift():
    """Default: shift not held. Tests flip it via _shift()."""
    _context._cue_shift_held = lambda: False


def _shift():
    """Make the next send_* call add a fresh pool first."""
    _context._cue_shift_held = lambda: True


def _scene(mgr, file="scene.ogv", dialogue="hello"):
    mgr._ctx.current_file = file
    mgr._ctx.current_dialogue = dialogue
    return file


def _sfx(mgr, *files):
    mgr._sfx_manager.files = list(files)


def _pool(mgr, key, pools):
    mgr[key] = {"pools": pools}


# ==========================================================================
# Base CueMarkerContext -- add_file guards + happy path (via mgr.image)
# ==========================================================================

def test_add_file_no_files_noop(mgr):
    _scene(mgr)
    mgr.image.add_file(0)  # empty library -> must not create an entry
    assert create_img_key("scene.ogv") not in mgr._data


def test_add_file_out_of_range_noop(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr.image.add_file(5)
    mgr.image.add_file(-1)
    assert create_img_key("scene.ogv") not in mgr._data


def test_add_file_disabled_noop(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr._sfx_manager.disabled_files = {"a.ogg"}
    mgr.image.add_file(0)
    assert create_img_key("scene.ogv") not in mgr._data


def test_add_file_happy_path(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr.image.add_file(1)
    entry = mgr.get(create_img_key("scene.ogv"))
    assert entry["pools"][0]["files"] == ["b.ogg"]


def test_add_file_appends_within_pool(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr.image.add_file(0)
    mgr.image.add_file(1)
    entry = mgr.get(create_img_key("scene.ogv"))
    assert entry["pools"][0]["files"] == ["a.ogg", "b.ogg"]


# ==========================================================================
# send_file / send_folder / send_preset -- shift vs normal
# ==========================================================================

def test_send_file_normal_appends_to_active_pool(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr.image.add_file(0)
    mgr.image.send_file(1)
    entry = mgr.get(create_img_key("scene.ogv"))
    assert entry["pools"][0]["files"] == ["a.ogg", "b.ogg"]
    assert len(entry["pools"]) == 1


def test_send_file_shift_creates_new_pool(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr.image.add_file(0)
    _shift()
    mgr.image.send_file(1)
    entry = mgr.get(create_img_key("scene.ogv"))
    assert len(entry["pools"]) == 2
    assert entry["pools"][0]["files"] == ["a.ogg"]
    assert entry["pools"][1]["files"] == ["b.ogg"]
    assert mgr._img_target == 1


def test_send_folder_normal(mgr):
    _scene(mgr)
    mgr.image.send_folder("music/")
    entry = mgr.get(create_img_key("scene.ogv"))
    assert entry["pools"][0]["files"] == ["music/"]


def test_send_folder_shift_creates_new_pool(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg")
    mgr.image.add_file(0)
    _shift()
    mgr.image.send_folder("music/")
    entry = mgr.get(create_img_key("scene.ogv"))
    assert len(entry["pools"]) == 2
    assert entry["pools"][1]["files"] == ["music/"]


def test_send_preset_normal(mgr):
    _scene(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    mgr.image.send_preset("basic")
    entry = mgr.get(create_img_key("scene.ogv"))
    assert entry["pools"][0] == {"preset": "basic"}


def test_send_preset_shift_creates_new_pool(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg")
    mgr.image.add_file(0)
    mgr.create_preset("basic", {"files": ["b.ogg"], "volume": 0.8})
    _shift()
    mgr.image.send_preset("basic")
    entry = mgr.get(create_img_key("scene.ogv"))
    assert len(entry["pools"]) == 2
    assert entry["pools"][0]["files"] == ["a.ogg"]
    assert entry["pools"][1] == {"preset": "basic"}


# ==========================================================================
# remove_file / clear / add_pool / remove_pool / set_active
# ==========================================================================

def test_remove_file(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg", "b.ogg")
    mgr.image.add_file(0)
    mgr.image.add_file(1)
    mgr.image.remove_file(0, 0)
    entry = mgr.get(create_img_key("scene.ogv"))
    assert entry["pools"][0]["files"] == ["b.ogg"]


def test_remove_file_empties_pool_deletes_entry(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg")
    mgr.image.add_file(0)
    mgr.image.remove_file(0, 0)
    assert create_img_key("scene.ogv") not in mgr._data


def test_clear_drops_entry(mgr):
    _scene(mgr)
    _sfx(mgr, "a.ogg")
    mgr.image.add_file(0)
    mgr.image.clear()
    assert create_img_key("scene.ogv") not in mgr._data


def test_add_pool_creates_and_selects(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.add_pool()
    entry = mgr.get(create_img_key("scene.ogv"))
    assert len(entry["pools"]) == 2
    assert entry["pools"][0]["volume"] == CUE_VOLUME_DEFAULT
    assert mgr._img_target == 1


def test_remove_pool_no_entry_noop(mgr):
    _scene(mgr)
    mgr.image.remove_pool(0)  # must not raise


def test_remove_pool_out_of_range_noop(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.remove_pool(3)  # must not raise
    assert len(mgr.get(create_img_key("scene.ogv"))["pools"]) == 1


def test_remove_pool_middle_shifts_target(mgr):
    _scene(mgr)
    for _ in range(3):
        mgr.image.add_pool()
    mgr.image.remove_pool(1)
    entry = mgr.get(create_img_key("scene.ogv"))
    assert len(entry["pools"]) == 2
    assert mgr._img_target == 1  # clamped from 2 to remaining-1


def test_remove_pool_last_deletes_entry(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.remove_pool(0)
    assert create_img_key("scene.ogv") not in mgr._data
    assert mgr._img_target == 0


def test_set_active(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.add_pool()
    mgr.image.set_active(0)
    assert mgr._img_target == 0


def test_get_active_pool_missing_entry_empty(mgr):
    _scene(mgr)
    assert mgr.image.get_active_pool() == {}


def test_get_active_pool_empty_pools_empty(mgr):
    _scene(mgr)
    mgr["i_scene.ogv"] = {"pools": []}
    assert mgr.image.get_active_pool() == {}


def test_get_active_pool_clamps_stale_target(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.add_pool()
    mgr._img_target = 5
    assert mgr.image.get_active_pool() is mgr.get("i_scene.ogv")["pools"][1]


def test_has_pools(mgr):
    _scene(mgr)
    assert mgr.image.has_pools() is False
    mgr.image.add_pool()
    assert mgr.image.has_pools() is True
    mgr["i_scene.ogv"] = {"pools": []}
    assert mgr.image.has_pools() is False


# ==========================================================================
# Exclusive logic
# ==========================================================================

def test_set_exclusive_image_lands_on_every_pool(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.add_pool()
    mgr.image.set_exclusive(CueExclusiveStart.WAIT, True)
    for pool in mgr.get("i_scene.ogv")["pools"]:
        assert pool["exclusive"] == {
            "group": 1, "start": CueExclusiveStart.WAIT, "hold": True}


def test_set_exclusive_loop_active_pool_only(mgr):
    _scene(mgr)
    _scene(mgr)
    mgr.loop.add_pool()
    mgr.loop.add_pool()
    mgr.loop.set_active(1)
    mgr.loop.set_exclusive(CueExclusiveStart.WAIT, True)
    pools = mgr.get("l_scene.ogv")["pools"]
    assert "exclusive" not in pools[0]
    assert pools[1]["exclusive"]["start"] == CueExclusiveStart.WAIT


def test_set_exclusive_missing_entry_noop(mgr):
    _scene(mgr)
    mgr.image.set_exclusive(CueExclusiveStart.PLAY, False)  # must not raise


def test_set_exclusive_empty_pools_noop(mgr):
    _scene(mgr)
    mgr["i_scene.ogv"] = {"pools": []}
    mgr.image.set_exclusive(CueExclusiveStart.PLAY, False)  # must not raise


def test_clear_exclusive_payload(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.set_exclusive(CueExclusiveStart.PLAY, False)
    mgr.image._set_exclusive_payload(None)
    assert "exclusive" not in mgr.get("i_scene.ogv")["pools"][0]


def test_toggle_exclusive_image_off_to_on_fades(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.toggle_exclusive()
    pool = mgr.get("i_scene.ogv")["pools"][0]
    assert pool["exclusive"]["start"] == CueExclusiveStart.FADE
    assert pool["exclusive"]["hold"] is False


def test_toggle_exclusive_loop_off_to_on_waits_and_holds(mgr):
    _scene(mgr)
    mgr.loop.add_pool()
    mgr.loop.toggle_exclusive()
    pool = mgr.get("l_scene.ogv")["pools"][0]
    assert pool["exclusive"]["start"] == CueExclusiveStart.WAIT
    assert pool["exclusive"]["hold"] is True


def test_toggle_exclusive_on_to_off_clears(mgr):
    _scene(mgr)
    mgr.image.add_pool()
    mgr.image.set_exclusive(CueExclusiveStart.PLAY, True)
    mgr.image.toggle_exclusive()
    assert "exclusive" not in mgr.get("i_scene.ogv")["pools"][0]


def test_loop_clear_exclusive_active_pool_only(mgr):
    _scene(mgr)
    mgr.loop.add_pool()
    mgr.loop.add_pool()
    mgr.loop.set_active(0)
    mgr.loop.set_exclusive(CueExclusiveStart.WAIT, True)
    mgr.loop.set_active(1)
    mgr.loop._set_exclusive_payload(None)
    pools = mgr.get("l_scene.ogv")["pools"]
    assert pools[0]["exclusive"]["start"] == CueExclusiveStart.WAIT  # untouched
    assert "exclusive" not in pools[1]  # cleared on the active pool


# ==========================================================================
# Base add_folder (image context)
# ==========================================================================

def test_add_folder_dedupes_ref(mgr):
    _scene(mgr)
    mgr.image.add_folder("music/")
    mgr.image.add_folder("music/")
    entry = mgr.get("i_scene.ogv")
    assert entry["pools"][0]["files"] == ["music/"]


# ==========================================================================
# CueVideoContext -- add_file
# ==========================================================================

def _video_key(mgr, file="scene.ogv"):
    _scene(mgr, file=file)
    return create_vid_key(file)


def test_video_add_file_attaches_to_active_pool(mgr):
    key = _video_key(mgr)
    _sfx(mgr, "a.ogg")
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.target_pool = 0
    mgr.video.add_file(0)
    pools = mgr.get(key)["pools"]
    assert pools[0]["files"] == ["a.ogg"]
    assert pools[0]["time"] == 1.0  # existing pool keeps its time


def test_video_add_file_appends_at_playhead(mgr):
    key = _video_key(mgr)
    _sfx(mgr, "a.ogg")
    mgr._vid_manager._elapsed = 2.5
    mgr.video.add_file(0)
    pools = mgr.get(key)["pools"]
    assert pools[0] == {"time": 2.5, "files": ["a.ogg"]}
    assert mgr.video.target_pool == 0


def test_video_add_file_no_files_noop(mgr):
    key = _video_key(mgr)
    mgr.video.add_file(0)  # empty library
    assert key not in mgr._data


def test_video_add_file_disabled_noop(mgr):
    key = _video_key(mgr)
    _sfx(mgr, "a.ogg")
    mgr._sfx_manager.disabled_files = {"a.ogg"}
    mgr.video.add_file(0)
    assert key not in mgr._data


# ==========================================================================
# CueVideoContext -- remove_file / add_folder / clear / add_pool
# ==========================================================================

def test_video_remove_file(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": ["a.ogg", "b.ogg"]}])
    mgr.video.remove_file(0, 0)
    assert mgr.get(key)["pools"][0]["files"] == ["b.ogg"]


def test_video_remove_file_out_of_range_noop(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": ["a.ogg"]}])
    mgr.video.remove_file(3, 0)  # must not raise
    assert mgr.get(key)["pools"][0]["files"] == ["a.ogg"]


def test_video_add_folder_attaches_to_active_pool(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.add_folder("music/")
    assert mgr.get(key)["pools"][0]["files"] == ["music/"]


def test_video_add_folder_appends_at_playhead(mgr):
    key = _video_key(mgr)
    mgr._vid_manager._elapsed = 1.5
    mgr.video.add_folder("music/")
    assert mgr.get(key)["pools"][0] == {"time": 1.5, "files": ["music/"]}


def test_video_add_folder_no_current_file_noop(mgr):
    _scene(mgr, file="")
    mgr.video.add_folder("music/")  # must not raise


def test_video_clear_resets_state(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": ["a.ogg"]}])
    mgr.video.selected = {0}
    mgr.video.target_pool = 0
    mgr.video.clear()
    assert key not in mgr._data
    assert mgr.video.target_pool == 0
    assert mgr.video.selected == set()


def test_video_add_pool(mgr):
    key = _video_key(mgr)
    mgr._vid_manager._elapsed = 3.5
    mgr.video.add_pool()
    mgr._vid_manager._elapsed = 4.5
    mgr.video.add_pool()
    pools = mgr.get(key)["pools"]
    assert [p["time"] for p in pools] == [3.5, 4.5]
    assert mgr.video.target_pool == 1


# ==========================================================================
# CueVideoContext -- apply_preset / apply_preset_active / send_preset
# ==========================================================================

def test_video_apply_preset_appends(mgr):
    key = _video_key(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    mgr._vid_manager._elapsed = 2.0
    mgr.video.apply_preset("basic")
    pools = mgr.get(key)["pools"]
    assert pools[0]["preset"] == "basic"
    assert pools[0]["time"] == 2.0
    assert mgr.video.edit_text == "00:02.00"  # sync_text after append


def test_video_apply_preset_no_current_file_noop(mgr):
    _scene(mgr, file="")
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr.video.apply_preset("basic")  # must not raise


def test_video_apply_preset_empty_preset_noop(mgr):
    key = _video_key(mgr)
    mgr.create_preset("empty", {"files": []})
    mgr.video.apply_preset("empty")
    assert key not in mgr._data


def test_video_apply_preset_active_stamps_existing_pool(mgr):
    key = _video_key(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.apply_preset_active("basic")
    pools = mgr.get(key)["pools"]
    assert pools[0] == {"time": 1.0, "preset": "basic"}


def test_video_apply_preset_active_no_pool_appends(mgr):
    key = _video_key(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr._vid_manager._elapsed = 4.0
    mgr.video.apply_preset_active("basic")
    pools = mgr.get(key)["pools"]
    assert pools[0] == {"time": 4.0, "preset": "basic"}


def test_video_apply_preset_active_no_files_noop(mgr):
    key = _video_key(mgr)
    mgr.create_preset("empty", {"files": []})
    mgr.video.apply_preset_active("empty")
    assert key not in mgr._data


def test_video_send_preset_normal_stamps_active(mgr):
    key = _video_key(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.send_preset("basic")
    assert mgr.get(key)["pools"][0]["preset"] == "basic"
    assert len(mgr.get(key)["pools"]) == 1


def test_video_send_preset_shift_appends_new_pool(mgr):
    key = _video_key(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    _shift()
    mgr._vid_manager._elapsed = 2.0
    mgr.video.send_preset("basic")
    pools = mgr.get(key)["pools"]
    assert len(pools) == 2
    assert pools[1]["preset"] == "basic"


# ==========================================================================
# CueVideoContext -- remove_pool / duplicate_pool / remove_selected
# ==========================================================================

def test_video_duplicate_pool(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": ["a.ogg"]}])
    mgr.video.duplicate_pool(0)
    pools = mgr.get(key)["pools"]
    assert len(pools) == 2
    # The copy lands a fixed pixel gap after its source so it doesn't overlap.
    assert pools[1] == {"time": 1.0 + mgr.video._duplicate_gap(), "files": ["a.ogg"]}
    assert mgr.video.target_pool == 1


def test_video_duplicate_pool_out_of_range_noop(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": ["a.ogg"]}])
    mgr.video.duplicate_pool(5)  # must not raise
    assert len(mgr.get(key)["pools"]) == 1


def test_video_remove_selected_no_markers_noop(mgr):
    key = _video_key(mgr)
    mgr.video.remove_selected()  # must not raise
    assert key not in mgr._data


def test_video_remove_selected_deletes_all_and_entry(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}])
    mgr.video.selected = {0, 1, 2}
    mgr.video.target_pool = 2
    mgr.video.remove_selected()
    assert key not in mgr._data
    assert mgr.video.target_pool == 0


def test_video_remove_selected_clamps_target(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}])
    mgr.video.selected = {0}
    mgr.video.target_pool = 2
    mgr.video.remove_selected()
    pools = mgr.get(key)["pools"]
    assert len(pools) == 2
    assert mgr.video.target_pool == 1
    assert mgr.video.selected == set()


def test_video_remove_selected_empty_selection_removes_target(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.0}])
    mgr.video.target_pool = 1
    mgr.video.remove_selected()
    pools = mgr.get(key)["pools"]
    assert len(pools) == 1
    assert mgr.video.target_pool == 0


# ==========================================================================
# CueVideoContext -- get_delete_message / set_active / select_tab
# ==========================================================================

def test_delete_message_multiple_selected(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}])
    mgr.video.selected = {0, 2}
    assert mgr.video.get_delete_message() == "Delete markers 1, 3?"


def test_delete_message_single_selected(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.0}])
    mgr.video.selected = {1}
    assert mgr.video.get_delete_message() == "Delete marker 2?"


def test_delete_message_no_markers(mgr):
    key = _video_key(mgr)
    mgr.video.selected = set()
    assert mgr.video.get_delete_message() == ""


def test_delete_message_target(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.0}])
    mgr.video.target_pool = 1
    assert mgr.video.get_delete_message() == "Delete marker 2?"


def test_video_set_active_syncs_text(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": []}, {"time": 2.5, "files": []}])
    mgr.video.set_active(1)
    assert mgr.video.target_pool == 1
    assert mgr.video.edit_text == "00:02.50"


def test_video_select_tab(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}, {"time": 2.5}])
    mgr.video.selected = {0}
    mgr.video.select_tab(1)
    assert mgr.video.selected == set()
    assert mgr.video.target_pool == 1


# ==========================================================================
# CueVideoContext -- nudge / set_time / finalize_drag / sync_text / commit_text
# ==========================================================================

def test_video_nudge_guard_no_pools(mgr):
    key = _video_key(mgr)
    mgr.video.nudge(0.5)  # must not raise


def test_video_nudge_clamps_to_duration(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.nudge(20.0)
    assert mgr.get(key)["pools"][0]["time"] == 10.0
    assert mgr.video.edit_text == "00:10.00"
    assert mgr.video.selected == set()


def test_video_nudge_no_duration_clamps_floor(mgr):
    key = _video_key(mgr)
    mgr._vid_manager.duration = 0
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.nudge(-5.0)
    assert mgr.get(key)["pools"][0]["time"] == 0.0


def test_video_set_time_clamps(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.set_time(0, 99.0)
    assert mgr.get(key)["pools"][0]["time"] == 10.0


def test_video_set_time_out_of_range_noop(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}])
    mgr.video.set_time(5, 99.0)  # must not raise
    assert mgr.get(key)["pools"][0]["time"] == 1.0


def test_video_finalize_drag_no_pools_noop(mgr):
    key = _video_key(mgr)
    mgr.video.finalize_drag()  # must not raise


def test_video_finalize_drag_reindexes_selection(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 3.0}, {"time": 1.0}, {"time": 2.0}])
    mgr.video.selected = {0, 1}
    mgr.video.target_pool = 0
    mgr.video.finalize_drag()
    pools = mgr.get(key)["pools"]
    assert [p["time"] for p in pools] == [1.0, 2.0, 3.0]
    assert mgr.video.selected == {0, 2}  # reindexed by identity
    assert mgr.video.target_pool == 0


def test_video_finalize_drag_unselected_target_reindexes_only(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 2.0}, {"time": 1.0}])
    mgr.video.selected = set()
    mgr.video.target_pool = 0
    mgr.video.finalize_drag()
    assert [p["time"] for p in mgr.get(key)["pools"]] == [1.0, 2.0]
    assert mgr.video.target_pool == 1  # sorted pool now at index 1


def test_video_commit_text_parses_and_commits(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0, "files": []}])
    mgr.video.edit_text = "00:05.00"
    mgr.video.commit_text()
    assert mgr.get(key)["pools"][0]["time"] == 5.0
    assert mgr.video.edit_text == "00:05.00"


def test_video_commit_text_clamps(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}])
    mgr.video.edit_text = "99:00.00"
    mgr.video.commit_text()
    assert mgr.get(key)["pools"][0]["time"] == 10.0


def test_video_commit_text_invalid_resets_label(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}])
    mgr.video.edit_text = "garbage"
    mgr.video.commit_text()
    assert mgr.get(key)["pools"][0]["time"] == 1.0
    assert mgr.video.edit_text == "00:01.00"


def test_video_commit_text_out_of_range_target_noop(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}])
    mgr.video.target_pool = 5
    mgr.video.edit_text = "00:05.00"
    mgr.video.commit_text()  # must not raise


def test_video_sync_text(mgr):
    key = _video_key(mgr)
    _pool(mgr, key, [{"time": 1.0}])
    mgr.video.edit_text = ""
    mgr.video.sync_text()
    assert mgr.video.edit_text == "00:01.00"


# ==========================================================================
# CueVideoContext -- get_markers / get_duration
# ==========================================================================

def test_video_get_markers_no_entry(mgr):
    _video_key(mgr)
    assert mgr.video.get_markers() == []


def test_video_get_markers_resolves_preset(mgr):
    key = _video_key(mgr)
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    _pool(mgr, key, [{"preset": "basic", "time": 1.0}])
    markers = mgr.video.get_markers()
    assert markers[0]["files"] == ["a.ogg"]
    assert markers[0]["volume"] == 0.8
    assert "preset" not in markers[0]


def test_video_get_duration(mgr):
    _video_key(mgr)
    assert mgr.video.get_duration() == 10.0


# ==========================================================================
# CueLoopContext -- add_pool / clear / set_frequency
# ==========================================================================

def test_loop_add_pool_adds_frequency(mgr):
    _scene(mgr)
    mgr.loop.add_pool()
    pool = mgr.get("l_scene.ogv")["pools"][0]
    assert pool["frequency"] == CueLoopFrequency.MEDIUM
    assert mgr._loop_target == 0


def test_loop_clear_pops_trigger_state(mgr):
    _scene(mgr)
    mgr.loop.add_pool()
    mgr._trigger.loop_states["l_scene.ogv"] = {"state": "playing"}
    mgr.loop.clear()
    assert "l_scene.ogv" not in mgr._data
    assert "l_scene.ogv" not in mgr._trigger.loop_states


def test_loop_set_frequency(mgr):
    _scene(mgr)
    mgr.loop.add_pool()
    mgr.loop.set_frequency(CueLoopFrequency.FASTEST)
    assert mgr.get("l_scene.ogv")["pools"][0]["frequency"] == CueLoopFrequency.FASTEST


def test_loop_set_frequency_no_entry_noop(mgr):
    _scene(mgr)
    mgr.loop.set_frequency(CueLoopFrequency.FAST)  # must not raise


def test_loop_set_frequency_out_of_range_noop(mgr):
    _scene(mgr)
    mgr.loop.add_pool()
    mgr._loop_target = 5
    mgr.loop.set_frequency(CueLoopFrequency.FAST)
    assert mgr.get("l_scene.ogv")["pools"][0]["frequency"] == CueLoopFrequency.MEDIUM


def test_dialogue_context_keys_by_line(mgr):
    _scene(mgr, file="scene.ogv", dialogue="line one")
    _sfx(mgr, "a.ogg")
    mgr.dialogue.add_file(0)
    assert "d_scene.ogv__line one" in mgr._data
    mgr.dialogue.add_pool()
    assert mgr._dlg_target == 1
    mgr.dialogue.clear()
    assert "d_scene.ogv__line one" not in mgr._data


# ==========================================================================
# CueVideoContext -- edge branches not covered above
# ==========================================================================

def test_video_entry_and_pools_empty_file_short_circuit(mgr):
    _scene(mgr, file="")
    assert mgr.video.get_markers() == []
    assert mgr.video.has_markers() is False
    mgr.video.remove_selected()  # must not raise


def test_video_add_file_out_of_range_noop(mgr):
    key = _video_key(mgr)
    _sfx(mgr, "a.ogg")
    mgr.video.add_file(5)
    assert key not in mgr._data


def test_video_apply_preset_active_no_current_file_noop(mgr):
    _scene(mgr, file="")
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr.video.apply_preset_active("basic")  # must not raise
