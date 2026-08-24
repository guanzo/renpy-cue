# -*- coding: utf-8 -*-
# Tests for the Cue*Context classes in cue_lib.marker_context.
#
# Contexts are constructed with a manager (constructor injection) and read
# entries via self._mgr.get(key).  The real manager is wired to _cue and
# Ren'Py; tests use FakeManager and pin the _cue-coupled seams (_key,
# get_duration) via small subclasses, so the pool logic runs headlessly.

import pytest

from cue_lib.marker_context import CUE_DUPLICATE_GAP_FRAC, CUE_INTERVAL_SELECT_TOLERANCE
from cue_lib.marker_context import CueImageContext, CueLoopContext, CueVideoContext
from cue_lib.markers import CueExclusiveStart, CueLoopFrequency, ResolvedExclusive, ResolvedPool
from cue_lib.intensity import CueIntensityManager

from tests.fakes import FakeManager, FakeRecent, FakeSfxManager


class VideoCtx(CueVideoContext):
    """CueVideoContext with _key and get_duration pinned to test values."""

    def __init__(self, mgr, key="v_key", duration=0.0):
        super(VideoCtx, self).__init__(mgr)
        self.test_key = key
        self.test_duration = duration

    def _key(self):
        return self.test_key

    def get_duration(self):
        return self.test_duration


class ImageCtx(CueImageContext):
    """CueImageContext with _key pinned (the real one reads _cue.current_file)."""

    def __init__(self, mgr, key="i_file"):
        super(ImageCtx, self).__init__(mgr)
        self.test_key = key

    def _key(self):
        return self.test_key


class LoopCtx(CueLoopContext):
    """CueLoopContext with _key pinned (the real one reads _cue.current_file)."""

    def __init__(self, mgr, key="l_file"):
        super(LoopCtx, self).__init__(mgr)
        self.test_key = key

    def _key(self):
        return self.test_key


# ---------------------------------------------------------------------------
# Base read methods (active pool / has pools)
# ---------------------------------------------------------------------------


def test_get_active_pool_returns_active_pool():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 1
    assert ctx.get_active_pool() == {"time": 2.0}


def test_get_active_pool_clamps_stale_target_high():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 99
    assert ctx.get_active_pool() == {"time": 2.0}


def test_get_active_pool_clamps_stale_target_low():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = -5
    assert ctx.get_active_pool() == {"time": 1.0}


def test_get_active_pool_empty_when_entry_missing():
    assert VideoCtx(FakeManager()).get_active_pool() == {}


def test_get_active_pool_empty_when_no_pools():
    mgr = FakeManager({"v_key": {}})
    assert VideoCtx(mgr).get_active_pool() == {}


def test_has_pools_true_and_false():
    assert VideoCtx(FakeManager({"v_key": {"pools": [{}]}})).has_pools()
    assert not VideoCtx(FakeManager({"v_key": {}})).has_pools()
    assert not VideoCtx(FakeManager()).has_pools()


def test_entry_and_pools_returns_entry_and_pools():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    entry, pools = ctx._entry_and_pools()
    assert entry == {"pools": [{"time": 1.0}]}
    assert pools == [{"time": 1.0}]


def test_entry_and_pools_empty_when_key_missing():
    ctx = VideoCtx(FakeManager())
    assert ctx._entry_and_pools() == (None, [])


# ---------------------------------------------------------------------------
# CueImageContext.toggle_shake_trigger
# ---------------------------------------------------------------------------


def test_toggle_shake_trigger_no_current_file():
    mgr = FakeManager(current_file="")
    ctx = ImageCtx(mgr, key="i_file")
    ctx.toggle_shake_trigger()
    assert mgr._data == {}
    assert mgr.saved_keys == []


def test_toggle_shake_trigger_toggles_on_and_saves():
    mgr = FakeManager(current_file="scene.ogv")
    ctx = ImageCtx(mgr, key="i_scene.ogv")
    ctx.toggle_shake_trigger()
    pool = mgr._data["i_scene.ogv"]["pools"][0]
    assert pool["trigger_on_shake"] is True
    assert mgr.saved_keys == ["i_scene.ogv"]


def test_toggle_shake_trigger_toggles_off():
    mgr = FakeManager(current_file="scene.ogv", data={"i_scene.ogv": {"pools": [{"trigger_on_shake": True}]}})
    ctx = ImageCtx(mgr, key="i_scene.ogv")
    ctx.toggle_shake_trigger()
    pool = mgr._data["i_scene.ogv"]["pools"][0]
    assert pool["trigger_on_shake"] is False
    assert mgr.saved_keys == ["i_scene.ogv"]


# ---------------------------------------------------------------------------
# Pool mutation helpers (_sort_and_track, _append_pool)
# ---------------------------------------------------------------------------


def test_sort_and_track_sorts_by_time_and_reindexes():
    mgr = FakeManager()
    ctx = VideoCtx(mgr)
    pools = [{"time": 3.0}, {"time": 1.0}, {"time": 2.0}]
    tracked = pools[2]  # the 2.0 pool
    idx = ctx._sort_and_track(pools, tracked)
    assert pools == [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]
    assert idx == 1
    assert ctx.active_pool == 1


def test_sort_and_track_unfound_tracked_clamps_target():
    mgr = FakeManager()
    ctx = VideoCtx(mgr)
    ctx.active_pool = 5
    pools = [{"time": 1.0}, {"time": 2.0}]
    idx = ctx._sort_and_track(pools, {"time": 9.0})  # not in the list
    assert idx == -1
    assert ctx.active_pool == 1


def test_append_pool_adds_sorts_and_clears_selection():
    mgr = FakeManager()
    ctx = VideoCtx(mgr)
    entry = {"pools": [{"time": 3.0}]}
    pools = entry["pools"]
    ctx.selected = {0}
    ctx._append_pool(entry, pools, {"time": 2.0})
    assert pools == [{"time": 2.0}, {"time": 3.0}]
    assert ctx.active_pool == 0
    assert ctx.selected == set()


# ---------------------------------------------------------------------------
# has_markers / selection / delete message
# ---------------------------------------------------------------------------


def test_has_markers():
    assert VideoCtx(FakeManager({"v_key": {"pools": [{"time": 1.0}]}})).has_markers()
    assert not VideoCtx(FakeManager()).has_markers()


def test_get_selected_returns_selection():
    ctx = VideoCtx(FakeManager())
    ctx.selected = {1, 3}
    assert ctx.get_selected() == {1, 3}


def test_add_interval_selection_selects_spacing_chain():
    # User's example: 1 active (0.0s), click 3 (1.0s). Spacing 1.0s.
    # Markers 5 (2.0s) and 7 (2.99s) continue the grid; 2/4/6 (half-beats) don't.
    mgr = FakeManager(
        {
            "v_key": {
                "pools": [
                    {"time": 0.0},
                    {"time": 0.5},
                    {"time": 1.0},
                    {"time": 1.5},
                    {"time": 2.0},
                    {"time": 2.5},
                    {"time": 2.99},
                ]
            }
        }
    )
    ctx = VideoCtx(mgr)
    ctx.active_pool = 0  # active marker 1
    ctx.add_interval_selection(2)  # click marker 3
    assert ctx.selected == {0, 2, 4, 6}  # markers 1, 3, 5, 7


def test_add_interval_selection_forward_click_does_not_reach_behind_active():
    # User's example: 1,2,3,4,5 at 1s spacing, active is marker 2 (index 1,
    # 1.0s), alt+shift+click marker 3 (index 2, 2.0s).  Only markers at or
    # after the active in the click's direction join -- marker 1 (index 0,
    # behind the active) must NOT be selected.
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 1.0}, {"time": 2.0}, {"time": 3.0}, {"time": 4.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 1
    ctx.add_interval_selection(2)
    assert ctx.selected == {1, 2, 3, 4}


def test_add_interval_selection_backward_click_does_not_reach_ahead_of_active():
    # Mirror case: active marker 2 (index 1), alt+shift+click marker 1
    # (index 0).  Only markers at or before the active join; 3/4/5 (ahead)
    # must NOT be selected.
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 1.0}, {"time": 2.0}, {"time": 3.0}, {"time": 4.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 1
    ctx.add_interval_selection(0)
    assert ctx.selected == {0, 1}


def test_add_interval_selection_reversed_anchor():
    # Click a marker behind the active: active at 2.0s, click 0.0s,
    # spacing 2.0s. Grid: 0.0, 2.0 (and 4.0, none). 1.0s marker is off-grid.
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 2
    ctx.add_interval_selection(0)
    assert ctx.selected == {0, 2}


def test_add_interval_selection_merges_into_existing_selection():
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 0.5}, {"time": 1.0}, {"time": 1.5}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 0
    ctx.selected = {1}  # off-grid half-beat stays selected
    ctx.add_interval_selection(2)
    assert ctx.selected == {0, 1, 2, 4}


def test_add_interval_selection_keeps_active_marker():
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 0.5}, {"time": 1.0}, {"time": 1.5}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 0
    ctx.add_interval_selection(2)
    assert ctx.active_pool == 0


def test_add_interval_selection_tolerance_boundaries():
    # Gap of 0.99s vs 1.0s spacing is exactly at tolerance (included);
    # gap of 0.97s is beyond it (excluded).
    mgr = FakeManager(
        {"v_key": {"pools": [{"time": 0.0}, {"time": 1.0}, {"time": 2.0}, {"time": 2.99}, {"time": 2.97}]}}
    )
    ctx = VideoCtx(mgr)
    ctx.active_pool = 0
    ctx.add_interval_selection(1)
    assert ctx.selected == {0, 1, 2, 3}


def test_add_interval_selection_uses_imported_tolerance():
    assert CUE_INTERVAL_SELECT_TOLERANCE == 0.010
    mgr = FakeManager(
        {
            "v_key": {
                "pools": [
                    {"time": 0.0},
                    {"time": 1.0},
                    {"time": 1.0 + CUE_INTERVAL_SELECT_TOLERANCE / 2},  # 5ms inside edge
                    {"time": 2.0 + CUE_INTERVAL_SELECT_TOLERANCE / 2},  # 5ms inside next edge
                ]
            }
        }
    )
    ctx = VideoCtx(mgr)
    ctx.active_pool = 0
    ctx.add_interval_selection(1)
    assert ctx.selected == {0, 1, 2, 3}


def test_add_interval_selection_clicking_active_selects_it():
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 0.5}, {"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 0
    ctx.add_interval_selection(0)  # zero spacing
    assert ctx.selected == {0}


def test_add_interval_selection_invalid_index_noop():
    ctx = VideoCtx(FakeManager({"v_key": {"pools": [{"time": 1.0}]}}))
    ctx.add_interval_selection(5)
    assert ctx.selected == set()


def test_add_interval_selection_no_pools_noop():
    ctx = VideoCtx(FakeManager())
    ctx.add_interval_selection(0)
    assert ctx.selected == set()


def test_delete_message_no_selection_no_markers():
    assert VideoCtx(FakeManager()).get_delete_message() == ""


def test_delete_message_default_pool_when_none_selected():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    assert ctx.get_delete_message() == "Delete marker 1?"


def test_delete_message_single_selected():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.selected = {1}
    assert ctx.get_delete_message() == "Delete marker 2?"


def test_delete_message_multiple_selected():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.selected = {0, 2}
    assert ctx.get_delete_message() == "Delete markers 1, 3?"


# ---------------------------------------------------------------------------
# Time edits (set_time, nudge, commit_text, sync_text)
# ---------------------------------------------------------------------------


def test_set_time_updates_pool_and_clamps_to_duration():
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.set_time(0, 99.0)  # clamps to duration
    assert mgr._data["v_key"]["pools"][0]["time"] == 10.0
    ctx.set_time(1, 3.5)
    assert mgr._data["v_key"]["pools"][1]["time"] == 3.5
    ctx.set_time(9, 7.0)  # out of range -> no-op
    assert len(mgr._data["v_key"]["pools"]) == 2


def test_nudge_moves_pool_time_and_resorts():
    mgr = FakeManager({"v_key": {"pools": [{"time": 3.0}, {"time": 1.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0  # the 3.0 pool
    ctx.nudge(-1.5)
    assert mgr._data["v_key"]["pools"] == [{"time": 1.0}, {"time": 1.5}]
    assert ctx.active_pool == 1  # target follows the nudged pool
    assert ctx.edit_text == "00:01.50"
    assert ctx.selected == set()


def test_commit_text_parses_and_writes_time():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.edit_text = "00:05.00"
    ctx.commit_text()
    # commit_text re-sorts on write, so the edited pool (now 5.0) moves to index 1.
    assert mgr._data["v_key"]["pools"] == [{"time": 2.0}, {"time": 5.0}]
    assert ctx.active_pool == 1
    assert ctx.edit_text == "00:05.00"


def test_sync_text_formats_active_pool_time():
    mgr = FakeManager({"v_key": {"pools": [{"time": 83.45}]}})
    ctx = VideoCtx(mgr)
    ctx.sync_text()
    assert ctx.edit_text == "01:23.45"


def test_sync_text_out_of_range_target_leaves_text():
    mgr = FakeManager({"v_key": {"pools": [{"time": 83.45}]}})
    ctx = VideoCtx(mgr)
    ctx.edit_text = "keep"
    ctx.active_pool = 5
    ctx.sync_text()
    assert ctx.edit_text == "keep"


# ---------------------------------------------------------------------------
# Multi-select time edits (multi loops _shift_pool_time via nudge/commit_text)
# ---------------------------------------------------------------------------


def test_nudge_multi_selection_shifts_all_selected_and_preserves_selection():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0  # active = earliest selected
    ctx.selected = {0, 2}
    ctx.nudge(0.5)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.5}, {"time": 3.0}, {"time": 5.5}]
    assert ctx.selected == {0, 2}  # preserved for chained edits
    assert ctx.active_pool == 0  # earliest selected stays active
    assert ctx.edit_text == "00:01.50"
    assert mgr.saved_keys == ["v_key"]  # one save = one undo step


def test_nudge_multi_selection_remaps_selection_by_identity_after_sort():
    # The unselected middle pool keeps its slot, so selection indices move
    # to wherever the identity-shifted pools land after re-sort.
    mgr = FakeManager({"v_key": {"pools": [{"time": 4.0}, {"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0  # the 4.0 pool
    ctx.selected = {0, 2}  # the 4.0 and 2.0 pools
    ctx.nudge(-2.0)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 0.0}, {"time": 1.0}, {"time": 2.0}]
    assert ctx.selected == {0, 2}
    assert ctx.active_pool == 0
    assert ctx.edit_text == "00:00.00"


def test_nudge_multi_selection_clamps_to_zero():
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.5}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.nudge(-1.0)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 0.0}, {"time": 2.0}]
    assert ctx.selected == {0, 1}


def test_commit_text_multi_selection_shifts_all_by_delta():
    # Anchor-style: field shows active (1.0), commit to 4.0 shifts the
    # selection by delta = 3.0. The untouched middle pool re-sorts between
    # them, so selection indices remap to {1, 2}.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 2}
    ctx.edit_text = "00:04.00"
    ctx.commit_text()
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 3.0}, {"time": 4.0}, {"time": 8.0}]
    assert ctx.selected == {1, 2}
    assert ctx.active_pool == 1
    assert ctx.edit_text == "00:04.00"
    assert mgr.saved_keys == ["v_key"]


def test_commit_text_multi_selection_clamps_at_duration():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 9.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.edit_text = "00:08.00"
    ctx.commit_text()
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 8.0}, {"time": 10.0}]
    assert ctx.selected == {0, 1}


def test_nudge_single_selection_still_clears_selection():
    # Regression guard: the single-pool path is untouched by the multi-select
    # branch -- a lone selected marker still clears the selection.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0}
    ctx.nudge(0.5)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.5}, {"time": 2.0}]
    assert ctx.selected == set()


def test_nudge_multi_selection_no_duration_keeps_floor():
    # Duration unknown (0.0): the shared clamp falls back to max(0, t) -- no
    # upper bound. Single and multi now share one _shift_pool_time code path.
    mgr = FakeManager({"v_key": {"pools": [{"time": 8.0}, {"time": 9.0}]}})
    ctx = VideoCtx(mgr)  # default duration = 0.0
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.nudge(5.0)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 13.0}, {"time": 14.0}]
    assert ctx.selected == {0, 1}


# ---------------------------------------------------------------------------
# Multi-select volume + files (set_selected_volume, file fan-out)
# ---------------------------------------------------------------------------


def test_set_selected_volume_writes_all_selected_no_save():
    # Propagator only -- no disk save. The caller (_CueVolumeValue.changed)
    # queues the write via marker_queue_save so slider drags coalesce.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 2}
    ctx.set_selected_volume(0.3)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.0, "volume": 0.3}, {"time": 3.0}, {"time": 5.0, "volume": 0.3}]
    assert mgr.saved_keys == []


def test_set_selected_volume_preset_pool_gets_override_no_detach():
    # Volume edits on preset-backed pools are overrides (no detach), matching
    # the single-pool behavior -- the preset ref must survive.
    mgr = FakeManager({"v_key": {"pools": [{"preset": "gun", "time": 1.0}, {"time": 3.0}]}})
    mgr._presets = {"gun": {"files": ["a.mp3"], "volume": 0.8}}
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.set_selected_volume(0.5)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"preset": "gun", "time": 1.0, "volume": 0.5}, {"time": 3.0, "volume": 0.5}]
    assert "preset" in pools[0]  # not detached


def test_set_selected_volume_single_selection_noop():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0}
    ctx.set_selected_volume(0.5)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.0}, {"time": 3.0}]
    assert mgr.saved_keys == []


def test_clear_selected_files_multi():
    mgr = FakeManager(
        {
            "v_key": {
                "pools": [
                    {"time": 1.0, "files": ["a.mp3", "b.mp3"]},
                    {"time": 2.0, "files": ["c.mp3"]},
                    {"time": 3.0, "files": ["d.mp3"]},
                ]
            }
        }
    )
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 2}
    ctx.clear_selected_files()
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.0, "files": []}, {"time": 2.0, "files": ["c.mp3"]}, {"time": 3.0, "files": []}]
    assert mgr.saved_keys == ["v_key"]


def test_clear_selected_files_preset_detaches_first():
    mgr = FakeManager({"v_key": {"pools": [{"preset": "gun", "time": 1.0}, {"time": 2.0, "files": ["c.mp3"]}]}})
    mgr._presets = {"gun": {"files": ["a.mp3"], "volume": 0.8}}
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.clear_selected_files()
    pools = mgr._data["v_key"]["pools"]
    assert pools[0] == {"time": 1.0, "volume": 0.8, "files": []}  # detached, cleared
    assert pools[1]["files"] == []


def test_clear_selected_files_single_uses_active():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": ["a.mp3"]}, {"time": 2.0, "files": ["c.mp3"]}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0}
    ctx.clear_selected_files()
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.0, "files": []}, {"time": 2.0, "files": ["c.mp3"]}]


def test_add_file_multi_fans_out_deduped():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": ["b.mp3"]}, {"time": 2.0, "files": []}]}})
    mgr._sfx_manager = FakeSfxManager(files=["a.mp3", "b.mp3"])
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.add_file(1)  # "b.mp3" -- already in pool 0, so dedupe no-op there
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == ["b.mp3"]
    assert pools[1]["files"] == ["b.mp3"]
    assert mgr.saved_keys == ["v_key"]


def test_add_file_multi_detaches_preset_pool():
    mgr = FakeManager({"v_key": {"pools": [{"preset": "gun", "time": 1.0}, {"time": 2.0, "files": ["c.mp3"]}]}})
    mgr._presets = {"gun": {"files": ["a.mp3"], "volume": 0.8}}
    mgr._sfx_manager = FakeSfxManager(files=["a.mp3", "b.mp3"])
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.add_file(1)  # "b.mp3"
    pools = mgr._data["v_key"]["pools"]
    assert pools[0] == {"time": 1.0, "volume": 0.8, "files": ["a.mp3", "b.mp3"]}
    assert pools[1]["files"] == ["c.mp3", "b.mp3"]


def test_add_file_multi_disabled_file_noop():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": []}]}})
    mgr._sfx_manager = FakeSfxManager(files=["a.mp3"], disabled_files={"a.mp3"})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0}
    ctx.add_file(0)
    assert mgr._data["v_key"]["pools"][0]["files"] == []
    assert mgr.saved_keys == []


def test_add_folder_multi_fans_out_folder_ref():
    mgr = FakeManager(
        {"v_key": {"pools": [{"time": 1.0, "files": ["a.mp3"]}, {"time": 2.0, "files": []}]}}, current_file="video.mp4"
    )
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.add_folder("sfx")
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == ["a.mp3", "sfx/"]
    assert pools[1]["files"] == ["sfx/"]
    assert mgr.saved_keys == ["v_key"]


def test_remove_file_multi_removes_path_from_all_noop_where_absent():
    mgr = FakeManager(
        {
            "v_key": {
                "pools": [
                    {"time": 1.0, "files": ["a.mp3", "b.mp3"]},
                    {"time": 2.0, "files": ["b.mp3", "c.mp3"]},
                    {"time": 3.0, "files": ["d.mp3"]},
                ]
            }
        }
    )
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 2}
    ctx.remove_file(0, 0)  # reference pool 0 file 0 = "a.mp3"
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == ["b.mp3"]
    assert pools[1]["files"] == ["b.mp3", "c.mp3"]  # untouched (not selected)
    assert pools[2]["files"] == ["d.mp3"]  # "a.mp3" absent -> no-op
    assert mgr.saved_keys == ["v_key"]


def test_remove_path_from_selected_expands_folder_ref():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": ["sfx/"]}, {"time": 2.0, "files": ["sfx/"]}]}})
    mgr._sfx_manager = FakeSfxManager(files=["sfx/one.mp3", "sfx/two.mp3", "other/three.mp3"])
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx._remove_path_from_selected("sfx/one.mp3")
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == ["sfx/two.mp3"]
    assert pools[1]["files"] == ["sfx/two.mp3"]


def test_remove_file_removes_folder_ref_entry_single():
    # Deleting a folder-ref row drops the ref, it does not expand into children.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": ["sfx/"]}]}})
    mgr._sfx_manager = FakeSfxManager(files=["sfx/one.mp3", "sfx/two.mp3"])
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0}
    ctx.remove_file(0, 0)
    assert mgr._data["v_key"]["pools"][0]["files"] == []


def test_remove_file_removes_folder_ref_entry_multi():
    # Multi fan-out removes the folder ref from every selected pool.
    mgr = FakeManager(
        {"v_key": {"pools": [{"time": 1.0, "files": ["sfx/"]}, {"time": 2.0, "files": ["sfx/", "a.mp3"]}]}}
    )
    mgr._sfx_manager = FakeSfxManager(files=["sfx/one.mp3", "sfx/two.mp3"])
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 1}
    ctx.remove_file(0, 0)
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == []
    assert pools[1]["files"] == ["a.mp3"]
    assert mgr.saved_keys == ["v_key"]


def test_apply_preset_active_multi_stamps_all_selected():
    mgr = FakeManager(
        {
            "v_key": {
                "pools": [
                    {"time": 1.0, "files": ["a.mp3"]},
                    {"time": 2.0, "files": ["b.mp3"]},
                    {"time": 3.0, "files": ["c.mp3"]},
                ]
            }
        },
        current_file="video.mp4",
    )
    mgr._presets = {"gun": {"files": ["a.mp3"], "volume": 0.8}}
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0, 2}
    ctx.apply_preset_active("gun")
    pools = mgr._data["v_key"]["pools"]
    assert pools[0] == {"time": 1.0, "preset": "gun"}
    assert pools[1] == {"time": 2.0, "files": ["b.mp3"]}  # untouched
    assert pools[2] == {"time": 3.0, "preset": "gun"}  # own time preserved
    assert mgr.saved_keys == ["v_key"]


def test_apply_preset_active_single_stamps_active_only():
    mgr = FakeManager(
        {"v_key": {"pools": [{"time": 1.0, "files": ["a.mp3"]}, {"time": 2.0, "files": ["b.mp3"]}]}},
        current_file="video.mp4",
    )
    mgr._presets = {"gun": {"files": ["a.mp3"], "volume": 0.8}}
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 1
    ctx.selected = set()
    ctx.apply_preset_active("gun")
    pools = mgr._data["v_key"]["pools"]
    assert pools[0] == {"time": 1.0, "files": ["a.mp3"]}
    assert pools[1] == {"time": 2.0, "preset": "gun"}


def test_remove_file_single_selection_does_not_fan_out():
    # Regression guard: a lone selected marker removes only the clicked file,
    # never triggering the multi-select fan-out.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": ["a.mp3", "b.mp3"]}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.active_pool = 0
    ctx.selected = {0}
    ctx.remove_file(0, 0)
    assert mgr._data["v_key"]["pools"][0]["files"] == ["b.mp3"]


def test_add_file_appends_or_dedupes_no_save():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0, "files": ["a.mp3"]}, {"time": 2.0, "files": ["b.mp3"]}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx._add_file("v_key", "a.mp3", 0)  # dup -> no-op
    ctx._add_file("v_key", "c.mp3", 0)  # append
    ctx._add_file("v_key", "c.mp3", 1)  # append
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == ["a.mp3", "c.mp3"]
    assert pools[1]["files"] == ["b.mp3", "c.mp3"]
    assert mgr.saved_keys == []  # caller owns the save


def test_remove_file_removes_if_present_no_save():
    mgr = FakeManager(
        {"v_key": {"pools": [{"time": 1.0, "files": ["a.mp3", "b.mp3"]}, {"time": 2.0, "files": ["a.mp3"]}]}}
    )
    ctx = VideoCtx(mgr, duration=10.0)
    ctx._remove_file("v_key", "a.mp3", 0)
    ctx._remove_file("v_key", "c.mp3", 0)  # absent -> no-op
    pools = mgr._data["v_key"]["pools"]
    assert pools[0]["files"] == ["b.mp3"]
    assert pools[1]["files"] == ["a.mp3"]  # untouched (only edited pool 0)
    assert mgr.saved_keys == []


# ---------------------------------------------------------------------------
# Pool removal / duplication
# ---------------------------------------------------------------------------


def test_remove_pool_pops_and_clamps_target():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 2
    ctx.remove_pool(2)
    assert mgr._data["v_key"]["pools"] == [{"time": 1.0}, {"time": 2.0}]
    assert ctx.active_pool == 1


def test_remove_pool_out_of_range_noop():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.remove_pool(5)
    assert len(mgr._data["v_key"]["pools"]) == 1
    assert mgr.saved_keys == []


def test_remove_pool_last_pool_deletes_entry():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.remove_pool(0)
    assert "v_key" not in mgr._data
    assert ctx.active_pool == 0


def test_remove_selected_removes_pools_and_saves():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.selected = {0, 2}
    ctx.remove_selected()
    assert mgr._data["v_key"]["pools"] == [{"time": 2.0}]
    assert ctx.selected == set()
    assert mgr.saved_keys == ["v_key"]


def test_remove_selected_last_pool_deletes_entry():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.selected = {0}
    ctx.remove_selected()
    assert "v_key" not in mgr._data
    assert ctx.active_pool == 0


def test_duplicate_pool_clones_and_targets_clone():
    # Zero duration -> no gap, so the copy shares the source's time but is a
    # fresh object and becomes the selection.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.duplicate_pool(0)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.0}, {"time": 1.0}, {"time": 3.0}]
    assert ctx.active_pool == 1
    assert pools[0] is not pools[1]  # deep-copied, not shared
    assert ctx.selected == {1}


def test_duplicate_pool_single_lands_gap_after_source_and_selects_copy():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr, duration=120.0)
    ctx.duplicate_pool(0)
    pools = mgr._data["v_key"]["pools"]
    gap = CUE_DUPLICATE_GAP_FRAC * 120.0
    assert len(pools) == 3
    assert pools[2]["time"] == pytest.approx(1.0 + gap)
    assert ctx.active_pool == 2
    assert ctx.selected == {2}
    assert pools[2] is not pools[0]
    assert mgr.saved_keys == ["v_key"]


def test_duplicate_pool_multi_fans_out_and_selects_copies():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=120.0)
    ctx.selected = {0, 2}
    ctx.duplicate_pool(0)  # ts_index is ignored under multi-select
    pools = mgr._data["v_key"]["pools"]
    gap = CUE_DUPLICATE_GAP_FRAC * 120.0
    assert len(pools) == 5
    assert [p["time"] for p in pools] == pytest.approx([1.0, 3.0, 5.0, 1.0 + gap, 5.0 + gap])
    assert ctx.selected == {3, 4}
    assert ctx.active_pool == 3
    assert mgr.saved_keys == ["v_key"]


def test_delete_pool_ui_multi_routes_to_remove_selected():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 1
    ctx.selected = {0, 2}
    ctx.delete_pool_ui()
    assert mgr._data["v_key"]["pools"] == [{"time": 2.0}]
    assert ctx.selected == set()
    assert ctx.active_pool == 0
    assert mgr.saved_keys == ["v_key"]


def test_delete_pool_ui_single_uses_active_pool():
    # A stray single selection is ignored: single-mode delete acts on the
    # active pool, mirroring the non-multi button behavior.
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.active_pool = 1
    ctx.selected = {0}
    ctx.delete_pool_ui()
    assert mgr._data["v_key"]["pools"] == [{"time": 1.0}, {"time": 3.0}]
    assert ctx.selected == set()
    assert ctx.active_pool == 1
    assert mgr.saved_keys == ["v_key"]


def test_duplicate_pool_out_of_range_noop():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.duplicate_pool(5)
    assert len(mgr._data["v_key"]["pools"]) == 1


def test_duplicate_pool_no_pools_noop():
    mgr = FakeManager({"v_key": {"pools": []}})
    ctx = VideoCtx(mgr, duration=120.0)
    ctx.duplicate_pool(0)
    assert mgr.saved_keys == []


def test_duplicate_pool_multi_skips_invalid_selected_index():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=120.0)
    ctx.selected = {0, 9}  # 9 is out of range and is skipped
    ctx.duplicate_pool(1)
    pools = mgr._data["v_key"]["pools"]
    gap = CUE_DUPLICATE_GAP_FRAC * 120.0
    assert len(pools) == 4
    assert ctx.selected == {3}
    assert ctx.active_pool == 3
    assert pools[3]["time"] == pytest.approx(1.0 + gap)


# ---------------------------------------------------------------------------
# Image context target semantics (active_pool on the context)
# ---------------------------------------------------------------------------


def test_image_context_active_pool_stored_on_context():
    mgr = FakeManager({"i_file": {"pools": [{"files": ["a"]}, {"files": ["b"]}]}})
    ctx = ImageCtx(mgr)
    ctx.set_active_index(1)
    assert ctx.active_pool == 1
    assert ctx.get_active_index() == 1
    assert ctx.get_active_pool() == {"files": ["b"]}


def test_image_context_get_active_pool_clamps_stale_target():
    mgr = FakeManager({"i_file": {"pools": [{"files": ["a"]}, {"files": ["b"]}]}})
    ctx = ImageCtx(mgr)
    ctx.set_active_index(99)
    assert ctx.get_active_pool() == {"files": ["b"]}


# ---------------------------------------------------------------------------
# Loop context (set_frequency, get_delay)
# ---------------------------------------------------------------------------


def test_loop_set_frequency_writes_pool_and_saves():
    mgr = FakeManager({"l_file": {"pools": [{"frequency": 1}, {"frequency": 2}]}})
    ctx = LoopCtx(mgr)
    ctx.set_active_index(0)
    ctx.set_frequency(CueLoopFrequency.FASTEST)
    assert mgr._data["l_file"]["pools"][0]["frequency"] == CueLoopFrequency.FASTEST
    assert mgr.saved_keys == ["l_file"]


def test_loop_set_frequency_missing_entry_noop():
    mgr = FakeManager()
    LoopCtx(mgr).set_frequency(CueLoopFrequency.FASTEST)
    assert mgr.saved_keys == []


def test_get_delay_bases_with_zero_jitter(monkeypatch):
    import cue_lib.marker_context as _context

    monkeypatch.setattr(_context._random, "uniform", lambda a, b: 0.0)
    assert CueLoopContext.get_delay(CueLoopFrequency.SLOWEST) == 5.0
    assert CueLoopContext.get_delay(CueLoopFrequency.FASTEST) == 0.15
    assert CueLoopContext.get_delay(CueLoopFrequency.FAST) == 0.5
    assert CueLoopContext.get_delay(CueLoopFrequency.MEDIUM) == 1.7
    assert CueLoopContext.get_delay(999) == 3.0  # unknown -> slow default


# ---------------------------------------------------------------------------
# Resolved value classes
# ---------------------------------------------------------------------------


def test_resolved_exclusive_defaults_and_to_dict():
    r = ResolvedExclusive()
    assert r.group == 0
    assert r.start == CueExclusiveStart.PLAY
    assert r.hold is False
    assert r.to_dict() == {"group": 0, "start": 0, "hold": False}


def test_resolved_pool_default_exclusive():
    r = ResolvedPool(files=[], volume=1.0, frequency=1, trigger_on_shake=False)
    assert isinstance(r.exclusive, ResolvedExclusive)
    assert r.exclusive.group == 0


# ---------------------------------------------------------------------------
# Recently Used recording (send_* -> manager._sfx_manager._recent)
# ---------------------------------------------------------------------------


def _recent_mgr(files=None):
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    mgr._sfx_manager.files = files if files is not None else []
    mgr._sfx_manager._recent = FakeRecent()
    return mgr


def test_send_file_records_resolved_filename():
    mgr = _recent_mgr(["sfx/a.ogg", "sfx/b.ogg"])
    VideoCtx(mgr).send_file(1)
    assert mgr._sfx_manager._recent.calls == [("file", "sfx/b.ogg")]


def test_send_file_records_on_non_video_context():
    mgr = _recent_mgr(["sfx/a.ogg"])
    ImageCtx(mgr).send_file(0)
    assert mgr._sfx_manager._recent.calls == [("file", "sfx/a.ogg")]


def test_send_file_out_of_range_does_not_record():
    mgr = _recent_mgr(["sfx/a.ogg"])
    VideoCtx(mgr).send_file(5)
    assert mgr._sfx_manager._recent.calls == []


def test_send_folder_records_normalized_ref():
    mgr = _recent_mgr()
    VideoCtx(mgr).send_folder("sfx/amb")
    assert mgr._sfx_manager._recent.calls == [("folder", "sfx/amb/")]


def test_send_preset_records_preset_name():
    mgr = _recent_mgr()
    ImageCtx(mgr).send_preset("Hurt")
    assert mgr._sfx_manager._recent.calls == [("preset", "Hurt")]


def test_video_send_preset_records_preset_name():
    mgr = _recent_mgr()
    VideoCtx(mgr).send_preset("Hurt")
    assert mgr._sfx_manager._recent.calls == [("preset", "Hurt")]


def test_send_file_no_recent_is_noop():
    mgr = FakeManager({"i_file": {"pools": []}})
    mgr._sfx_manager.files = ["sfx/a.ogg"]
    ImageCtx(mgr).send_file(0)  # _recent stays None -- must not raise
    assert mgr.added_files == [("i_file", "sfx/a.ogg", 0)]


def test_send_file_record_false_skips_record():
    mgr = _recent_mgr(["sfx/a.ogg"])
    VideoCtx(mgr).send_file(0, record=False)
    assert mgr._sfx_manager._recent.calls == []


def test_send_folder_record_false_skips_record():
    mgr = _recent_mgr()
    VideoCtx(mgr).send_folder("sfx/amb", record=False)
    assert mgr._sfx_manager._recent.calls == []


def test_send_preset_record_false_skips_record():
    mgr = _recent_mgr()
    ImageCtx(mgr).send_preset("Hurt", record=False)
    assert mgr._sfx_manager._recent.calls == []


def test_video_send_preset_record_false_skips_record():
    mgr = _recent_mgr()
    VideoCtx(mgr).send_preset("Hurt", record=False)
    assert mgr._sfx_manager._recent.calls == []


# ---------------------------------------------------------------------------
# add_folder -- folder adds are always allowed (the intensity group hook is
# set explicitly, not inferred from folder membership)
# ---------------------------------------------------------------------------


def _intensity_mgr(cue_env):
    """FakeManager wired to a real intensity manager holding two groups."""
    mgr = FakeManager({"i_file": {"pools": [{"files": [], "volume": 1.0}]}}, current_file="v")
    mgr._sfx_manager.library._intensity = CueIntensityManager(cue_env.db)
    intensity = mgr._sfx_manager.library._intensity
    assert intensity.create_igroup("Impacts") is None
    assert intensity.add_level("Impacts") == 1
    assert intensity.add_level_file("Impacts", 1, "soft/") is None
    assert intensity.create_igroup("Mouth") is None
    assert intensity.add_level("Mouth") == 1
    assert intensity.add_level_file("Mouth", 1, "lip/") is None
    return mgr


def test_image_add_folder_appends_ref_when_unwired():
    mgr = FakeManager({"i_file": {"pools": [{"files": [], "volume": 1.0}]}})
    # library._intensity stays None -- no manager, folder add just appends.
    ImageCtx(mgr).add_folder("lip/")
    assert mgr.get("i_file")["pools"][0]["files"] == ["lip/"]


def test_image_add_folder_appends_across_groups(cue_env):
    # A pool may hold folders from any group -- the one-group-per-pool
    # guardrail is gone.
    mgr = _intensity_mgr(cue_env)
    ctx = ImageCtx(mgr)
    assert ctx.add_folder("soft/") is None
    assert ctx.add_folder("lip/") is None  # second group now allowed
    assert mgr.get("i_file")["pools"][0]["files"] == ["soft/", "lip/"]


def test_video_add_folder_appends_across_groups(cue_env):
    mgr = _intensity_mgr(cue_env)
    ctx = VideoCtx(mgr)
    assert ctx.add_folder("soft/") is None
    assert ctx.add_folder("lip/") is None
    assert mgr.get("v_key")["pools"][0]["files"] == ["soft/", "lip/"]


def test_send_folder_clears_warning_on_success(cue_env):
    mgr = _intensity_mgr(cue_env)
    cleared = []
    mgr._sfx_manager.library.clear_add_to_pool_warning = lambda: cleared.append(True)
    ctx = ImageCtx(mgr)
    assert ctx.send_folder("soft/") is None
    assert cleared == [True]  # success clears the notice
    assert ctx.send_folder("lip/") is None  # always allowed now
    assert cleared == [True, True]


def test_send_file_clears_add_to_pool_warning(cue_env):
    mgr = _intensity_mgr(cue_env)
    mgr._sfx_manager.files = ["sfx/a.ogg"]
    cleared = []
    mgr._sfx_manager.library.clear_add_to_pool_warning = lambda: cleared.append(True)
    ImageCtx(mgr).send_file(0)
    assert cleared == [True]
