# -*- coding: utf-8 -*-
# Tests for the Cue*Context classes in cue_lib.context.
#
# Contexts are constructed with a manager (constructor injection) and read
# entries via self._mgr.get(key).  The real manager is wired to _cue and
# Ren'Py; tests use FakeManager and pin the _cue-coupled seams (_key,
# get_duration) via small subclasses, so the pool logic runs headlessly.

from cue_lib.constants import CUE_INTERVAL_SELECT_TOLERANCE
from cue_lib.context import (
    CueImageContext,
    CueLoopContext,
    CueVideoContext,
)
from cue_lib.markers import (
    CueExclusiveStart,
    CueLoopFrequency,
    ResolvedExclusive,
    ResolvedPool,
)

from tests.fakes import FakeManager


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
    ctx.target_pool = 1
    assert ctx.get_active_pool() == {"time": 2.0}


def test_get_active_pool_clamps_stale_target_high():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 99
    assert ctx.get_active_pool() == {"time": 2.0}


def test_get_active_pool_clamps_stale_target_low():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = -5
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
    assert ctx.target_pool == 1


def test_sort_and_track_unfound_tracked_clamps_target():
    mgr = FakeManager()
    ctx = VideoCtx(mgr)
    ctx.target_pool = 5
    pools = [{"time": 1.0}, {"time": 2.0}]
    idx = ctx._sort_and_track(pools, {"time": 9.0})  # not in the list
    assert idx == -1
    assert ctx.target_pool == 1


def test_append_pool_adds_sorts_and_clears_selection():
    mgr = FakeManager()
    ctx = VideoCtx(mgr)
    entry = {"pools": [{"time": 3.0}]}
    pools = entry["pools"]
    ctx.selected = {0}
    ctx._append_pool(entry, pools, {"time": 2.0})
    assert pools == [{"time": 2.0}, {"time": 3.0}]
    assert ctx.target_pool == 0
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
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 0.5}, {"time": 1.0},
        {"time": 1.5}, {"time": 2.0}, {"time": 2.5}, {"time": 2.99}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 0  # active marker 1
    ctx.add_interval_selection(2)  # click marker 3
    assert ctx.selected == {0, 2, 4, 6}  # markers 1, 3, 5, 7


def test_add_interval_selection_backward_extension():
    # Grid continues behind the active marker too: 0, 1, 2, 3 at 1s spacing,
    # active at index 1 (1.0s), click index 2 (2.0s) -> spacing 1.0s.
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 1
    ctx.add_interval_selection(2)
    assert ctx.selected == {0, 1, 2, 3}


def test_add_interval_selection_reversed_anchor():
    # Click a marker behind the active: active at 2.0s, click 0.0s,
    # spacing 2.0s. Grid: 0.0, 2.0 (and 4.0, none). 1.0s marker is off-grid.
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 2
    ctx.add_interval_selection(0)
    assert ctx.selected == {0, 2}


def test_add_interval_selection_merges_into_existing_selection():
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 0.5}, {"time": 1.0},
        {"time": 1.5}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 0
    ctx.selected = {1}  # off-grid half-beat stays selected
    ctx.add_interval_selection(2)
    assert ctx.selected == {0, 1, 2, 4}


def test_add_interval_selection_keeps_active_marker():
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 0.5}, {"time": 1.0},
        {"time": 1.5}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 0
    ctx.add_interval_selection(2)
    assert ctx.target_pool == 0


def test_add_interval_selection_tolerance_boundaries():
    # Gap of 0.99s vs 1.0s spacing is exactly at tolerance (included);
    # gap of 0.97s is beyond it (excluded).
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 1.0},
        {"time": 2.0}, {"time": 2.99}, {"time": 2.97}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 0
    ctx.add_interval_selection(1)
    assert ctx.selected == {0, 1, 2, 3}


def test_add_interval_selection_uses_imported_tolerance():
    assert CUE_INTERVAL_SELECT_TOLERANCE == 0.010
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 1.0},
        {"time": 1.0 + CUE_INTERVAL_SELECT_TOLERANCE / 2},  # 5ms inside edge
        {"time": 2.0 + CUE_INTERVAL_SELECT_TOLERANCE / 2},  # 5ms inside next edge
    ]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 0
    ctx.add_interval_selection(1)
    assert ctx.selected == {0, 1, 2, 3}


def test_add_interval_selection_clicking_active_selects_it():
    mgr = FakeManager({"v_key": {"pools": [
        {"time": 0.0}, {"time": 0.5}, {"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 0
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
    ctx.target_pool = 0  # the 3.0 pool
    ctx.nudge(-1.5)
    assert mgr._data["v_key"]["pools"] == [{"time": 1.0}, {"time": 1.5}]
    assert ctx.target_pool == 1  # target follows the nudged pool
    assert ctx.edit_text == "00:01.50"
    assert ctx.selected == set()


def test_commit_text_parses_and_writes_time():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.target_pool = 0
    ctx.edit_text = "00:05.00"
    ctx.commit_text()
    # commit_text re-sorts on write, so the edited pool (now 5.0) moves to index 1.
    assert mgr._data["v_key"]["pools"] == [{"time": 2.0}, {"time": 5.0}]
    assert ctx.target_pool == 1
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
    ctx.target_pool = 5
    ctx.sync_text()
    assert ctx.edit_text == "keep"


# ---------------------------------------------------------------------------
# Multi-select time edits (_shift_selected via nudge / commit_text)
# ---------------------------------------------------------------------------

def test_nudge_multi_selection_shifts_all_selected_and_preserves_selection():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}, {"time": 5.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.target_pool = 0  # active = earliest selected
    ctx.selected = {0, 2}
    ctx.nudge(0.5)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.5}, {"time": 3.0}, {"time": 5.5}]
    assert ctx.selected == {0, 2}  # preserved for chained edits
    assert ctx.target_pool == 0  # earliest selected stays active
    assert ctx.edit_text == "00:01.50"
    assert mgr.saved_keys == ["v_key"]  # one save = one undo step


def test_nudge_multi_selection_remaps_selection_by_identity_after_sort():
    # The unselected middle pool keeps its slot, so selection indices move
    # to wherever the identity-shifted pools land after re-sort.
    mgr = FakeManager({"v_key": {"pools": [{"time": 4.0}, {"time": 1.0}, {"time": 2.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.target_pool = 0  # the 4.0 pool
    ctx.selected = {0, 2}  # the 4.0 and 2.0 pools
    ctx.nudge(-2.0)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 0.0}, {"time": 1.0}, {"time": 2.0}]
    assert ctx.selected == {0, 2}
    assert ctx.target_pool == 0
    assert ctx.edit_text == "00:00.00"


def test_nudge_multi_selection_clamps_to_zero():
    mgr = FakeManager({"v_key": {"pools": [{"time": 0.5}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.target_pool = 0
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
    ctx.target_pool = 0
    ctx.selected = {0, 2}
    ctx.edit_text = "00:04.00"
    ctx.commit_text()
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 3.0}, {"time": 4.0}, {"time": 8.0}]
    assert ctx.selected == {1, 2}
    assert ctx.target_pool == 1
    assert ctx.edit_text == "00:04.00"
    assert mgr.saved_keys == ["v_key"]


def test_commit_text_multi_selection_clamps_at_duration():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 9.0}]}})
    ctx = VideoCtx(mgr, duration=10.0)
    ctx.target_pool = 0
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
    ctx.target_pool = 0
    ctx.selected = {0}
    ctx.nudge(0.5)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.5}, {"time": 2.0}]
    assert ctx.selected == set()


# ---------------------------------------------------------------------------
# Pool removal / duplication
# ---------------------------------------------------------------------------

def test_remove_pool_pops_and_clamps_target():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.target_pool = 2
    ctx.remove_pool(2)
    assert mgr._data["v_key"]["pools"] == [{"time": 1.0}, {"time": 2.0}]
    assert ctx.target_pool == 1


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
    assert ctx.target_pool == 0


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
    assert ctx.target_pool == 0


def test_duplicate_pool_clones_and_targets_clone():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}, {"time": 3.0}]}})
    ctx = VideoCtx(mgr)
    ctx.duplicate_pool(0)
    pools = mgr._data["v_key"]["pools"]
    assert pools == [{"time": 1.0}, {"time": 1.0}, {"time": 3.0}]
    assert ctx.target_pool == 1
    assert pools[0] is not pools[1]  # deep-copied, not shared
    assert ctx.selected == set()


def test_duplicate_pool_out_of_range_noop():
    mgr = FakeManager({"v_key": {"pools": [{"time": 1.0}]}})
    ctx = VideoCtx(mgr)
    ctx.duplicate_pool(5)
    assert len(mgr._data["v_key"]["pools"]) == 1


# ---------------------------------------------------------------------------
# Image context target semantics (_img_target on the manager)
# ---------------------------------------------------------------------------

def test_image_context_target_stored_on_manager():
    mgr = FakeManager({"i_file": {"pools": [{"files": ["a"]}, {"files": ["b"]}]}})
    ctx = ImageCtx(mgr)
    ctx._set_target(1)
    assert mgr._img_target == 1
    assert ctx.get_active() == 1
    assert ctx.get_active_pool() == {"files": ["b"]}


def test_image_context_get_active_pool_clamps_stale_target():
    mgr = FakeManager({"i_file": {"pools": [{"files": ["a"]}, {"files": ["b"]}]}})
    ctx = ImageCtx(mgr)
    ctx._set_target(99)
    assert ctx.get_active_pool() == {"files": ["b"]}


# ---------------------------------------------------------------------------
# Loop context (set_frequency, get_delay)
# ---------------------------------------------------------------------------

def test_loop_set_frequency_writes_pool_and_saves():
    mgr = FakeManager({"l_file": {"pools": [{"frequency": 1}, {"frequency": 2}]}})
    ctx = LoopCtx(mgr)
    ctx._set_target(0)
    ctx.set_frequency(CueLoopFrequency.FASTEST)
    assert mgr._data["l_file"]["pools"][0]["frequency"] == CueLoopFrequency.FASTEST
    assert mgr.saved_keys == ["l_file"]


def test_loop_set_frequency_missing_entry_noop():
    mgr = FakeManager()
    LoopCtx(mgr).set_frequency(CueLoopFrequency.FASTEST)
    assert mgr.saved_keys == []


def test_get_delay_bases_with_zero_jitter(monkeypatch):
    import cue_lib.context as _context
    monkeypatch.setattr(_context._random, "uniform", lambda a, b: 0.0)
    assert CueLoopContext.get_delay(CueLoopFrequency.SLOWEST) == 5.0
    assert CueLoopContext.get_delay(CueLoopFrequency.FASTEST) == 0.15
    assert CueLoopContext.get_delay(CueLoopFrequency.FAST) == 0.5
    assert CueLoopContext.get_delay(CueLoopFrequency.NORMAL) == 1.7
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
