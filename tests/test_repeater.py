# -*- coding: utf-8 -*-
# Tests for cue_lib.video.repeater -- CueMarkerRepeater's open/apply/offset
# math and its live identity-tracking of the tracked marker pools.
#
# The repeater is wired to the REAL store / video manager (like test_speed.py)
# so open()/apply()/compute_preview_* exercise the exact production paths.  The
# markers coordinator is a FakeMarkers whose .video is a FakeVideoContext --
# get_markers()/get_selected()/target_pool feed the selection, and
# finalize_drag() records the drag seam.  Raw pool dicts are seeded directly
# into the store so identity tracking (`is`) has stable objects to match.

import types

import pytest

import renpy.config as _config
import renpy.audio.music as _music_mock

from cue_lib.state import CueContext
from cue_lib.paths import CuePaths
from cue_lib.db import CueDatabase
from cue_lib.marker_store import CueMarkerStore
from cue_lib.video.video import CueVideoManager
from cue_lib.video.repeater import CueMarkerRepeater
from cue_lib.util import create_vid_key

from tests.fakes import FakeMarkers


@pytest.fixture(autouse=True)
def _clean_state():
    """Per-test isolation: fresh music registry."""
    _music_mock._reset_all()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real store/video-manager graph plus an injected markers coordinator."""
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    root = str(tmp_path / "cue_root")
    ctx = CueContext()
    paths = CuePaths(root, game_id="test_game")
    db = CueDatabase(paths)
    db.open()
    store = CueMarkerStore(db, paths)
    vid = CueVideoManager(ctx)
    coord = FakeMarkers()
    rep = CueMarkerRepeater(ctx, store, vid, markers=coord)
    yield types.SimpleNamespace(
        ctx=ctx, paths=paths, db=db, store=store, vid=vid,
        coord=coord, rep=rep, tag="scene", music=_music_mock,
    )


def _pool(time, files=None, volume=1.0):
    """A raw video pool dict as the store holds them."""
    return {"time": time, "files": files if files is not None else ["a.ogg"], "volume": volume}


def _open(env, times, selected, dur=10.0, target_pool=0):
    """Seed pools, wire the movie context/duration, and open the dialog.
    Returns the raw pools list (the live objects apply/shift mutate)."""
    pools = [_pool(t) for t in times]
    env.store._data[create_vid_key(env.tag)] = {"pools": pools}
    env.ctx.current_file = env.tag
    env.coord.video.markers = pools
    env.coord.video.selected = set(selected)
    env.coord.video.target_pool = target_pool
    env.music._registry["movie"] = {"duration": dur}
    env.vid.channel = "movie"
    env.rep.open()
    return pools


def _entry(env):
    return env.store._data[create_vid_key(env.tag)]


# ==========================================================================
# open() -- selection tracking and defaults
# ==========================================================================


def test_open_tracks_selection_by_identity(env):
    pools = _open(env, [1.0, 2.0, 3.0], selected=[0, 1])
    rep = env.rep
    assert rep.dialog_visible is True
    assert rep._vid_key == create_vid_key(env.tag)
    assert rep._pools_id == id(pools)
    assert rep._tracked[id(pools[0])] is pools[0]
    assert rep._tracked[id(pools[1])] is pools[1]
    assert id(pools[2]) not in rep._tracked
    assert rep._anchor_pool is pools[0]
    assert rep.anchor == 1.0
    assert rep.sel_count == 2
    assert rep.offsets[0]["offset"] == 0.0
    assert rep.offsets[1]["offset"] == 1.0
    assert rep.offsets[1]["files"] == ["a.ogg"]
    assert rep.offsets[1]["volume"] == 1.0


def test_open_falls_back_to_target_pool(env):
    _open(env, [1.0, 2.0, 3.0], selected=[], target_pool=1)
    assert env.rep._anchor_pool is not None
    assert env.rep.anchor == 2.0
    assert env.rep.sel_count == 1


def test_open_no_markers_noop(env):
    env.coord.video.markers = []
    env.coord.video.selected = set()
    env.rep.open()
    assert env.rep.dialog_visible is False
    assert env.rep.offsets == []


def test_open_no_current_file_noop(env):
    env.coord.video.markers = [_pool(1.0)]
    env.coord.video.selected = {0}
    env.rep.open()
    assert env.rep.dialog_visible is False


def test_open_missing_entry_noop(env):
    env.coord.video.markers = [_pool(1.0)]
    env.coord.video.selected = {0}
    env.ctx.current_file = env.tag
    env.rep.open()
    assert env.rep.dialog_visible is False


def test_open_selection_out_of_range_noop(env):
    _open(env, [1.0], selected=[5])
    assert env.rep.dialog_visible is False


def test_open_default_interval_two_markers_span_times_two(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    assert env.rep.interval_text == "2.00"  # max_offset 1.0 * 2


def test_open_default_interval_single_marker_uses_anchor(env):
    _open(env, [3.0], selected=[0])
    assert env.rep.interval_text == "3.00"


def test_open_default_interval_zero_anchor_falls_back_one(env):
    _open(env, [0.0], selected=[0])
    assert env.rep.interval_text == "1.00"


def test_open_default_count_fits_duration(env):
    _open(env, [1.0, 2.0], selected=[0, 1], dur=10.0)
    # (10 - anchor 1.0 - max_offset 1.0) / interval 2.0 == 4
    assert env.rep.count_text == "4"


def test_open_anchor_text_formatted(env):
    _open(env, [1.0], selected=[0])
    assert env.rep.anchor_text == "00:01.00"


def test_open_count_negative_clamps_zero(env):
    _open(env, [11.0, 12.0], selected=[0, 1], dur=10.0)
    # (10 - 11.0 - 1.0) / 2.0 -> int(-1.0) -> clamped to 0
    assert env.rep.count_text == "0"


def test_open_count_unknown_duration_zero(env):
    _open(env, [1.0], selected=[0], dur=0)  # get_duration -> 0 -> else branch
    assert env.rep.count_text == "0"


# ==========================================================================
# _sync_tracked() -- live propagation and reset paths
# ==========================================================================


def test_sync_in_place_edit_propagates_offsets(env):
    pools = _open(env, [1.0, 2.0], selected=[0, 1])
    pools[1]["time"] = 2.5
    env.rep._sync_tracked()
    assert env.rep.anchor == 1.0
    assert env.rep.offsets[1]["offset"] == 1.5


def test_sync_video_changed_resets_tracking(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    env.ctx.current_file = "other"
    env.rep._sync_tracked()
    assert env.rep._tracked is None
    assert env.rep._anchor_pool is None
    assert env.rep.anchor == 0.0
    assert env.rep.sel_count == 0
    assert env.rep.dialog_visible is True  # stays open, no previews


def test_sync_entry_cleared_hides(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    del env.store._data[create_vid_key(env.tag)]
    env.rep._sync_tracked()
    assert env.rep.dialog_visible is False


def test_sync_wholesale_replacement_resets(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    entry = _entry(env)
    entry["pools"] = [dict(p) for p in entry["pools"]]  # new list object
    env.rep._sync_tracked()
    assert env.rep._tracked is None
    assert env.rep._anchor_pool is None
    assert env.rep.offsets == []
    assert env.rep.dialog_visible is True  # abandoned until reopened


def test_sync_anchor_deleted_hides(env):
    pools = _open(env, [1.0, 2.0], selected=[0, 1])
    del pools[0]
    env.rep._sync_tracked()
    assert env.rep.dialog_visible is False


def test_sync_all_tracked_deleted_hides(env):
    pools = _open(env, [1.0], selected=[0])
    del pools[0]
    env.rep._sync_tracked()
    assert env.rep.dialog_visible is False


def test_sync_not_visible_noop(env):
    _open(env, [1.0], selected=[0])
    env.rep.hide()
    env.rep._sync_tracked()
    assert env.rep.offsets == []
    assert env.rep.sel_count == 0


def test_sync_after_video_change_back_returns_early(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    env.ctx.current_file = "other"
    env.rep._sync_tracked()  # resets _tracked
    env.ctx.current_file = env.tag
    env.rep._sync_tracked()  # _tracked is None -> early return, no offsets
    assert env.rep._tracked is None
    assert env.rep.offsets == []


# ==========================================================================
# apply() -- cloning the pattern
# ==========================================================================


def test_apply_clones_with_expected_times(env):
    pools = _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "2"
    env.rep.apply()
    assert [p["time"] for p in pools] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert pools[2]["files"] == ["a.ogg"]
    assert pools[2]["volume"] == 1.0
    assert env.coord.video.selected == set()


def test_apply_sorted_after_insertion(env):
    pools = _open(env, [5.0, 6.0], selected=[0, 1])
    env.rep.interval_text = "1.00"
    env.rep.count_text = "1"
    env.rep.apply()
    assert [p["time"] for p in pools] == sorted(p["time"] for p in pools)


def test_apply_invalid_text_noop(env):
    pools = _open(env, [1.0], selected=[0])
    env.rep.interval_text = "abc"
    env.rep.count_text = "2"
    env.rep.apply()
    assert len(pools) == 1


def test_apply_zero_interval_noop(env):
    pools = _open(env, [1.0], selected=[0])
    env.rep.interval_text = "0"
    env.rep.count_text = "2"
    env.rep.apply()
    assert len(pools) == 1


def test_apply_count_zero_noop(env):
    pools = _open(env, [1.0], selected=[0])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "0"
    env.rep.apply()
    assert len(pools) == 1


def test_apply_skips_beyond_duration(env):
    pools = _open(env, [9.5], selected=[0], dur=10.0)
    env.rep.interval_text = "2.00"
    env.rep.count_text = "3"
    env.rep.apply()
    assert len(pools) == 1


def test_apply_hidden_noop(env):
    _open(env, [1.0], selected=[0])
    env.rep.hide()
    env.rep.apply()
    assert len(_entry(env)["pools"]) == 1


def test_apply_persists_via_save_marker(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "1"
    env.rep.apply()
    assert env.store._data[create_vid_key(env.tag)]["pools"][1]["time"] == 3.0


# ==========================================================================
# compute_preview_times / compute_preview_pools / preview_text
# ==========================================================================


def test_compute_preview_times(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "2"
    assert env.rep.compute_preview_times() == [3.0, 4.0, 5.0, 6.0]


def test_compute_preview_times_hidden_empty(env):
    _open(env, [1.0], selected=[0])
    env.rep.hide()
    assert env.rep.compute_preview_times() == []


def test_compute_preview_times_invalid_interval_empty(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "abc"
    assert env.rep.compute_preview_times() == []


def test_compute_preview_times_invalid_count_empty(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "abc"
    assert env.rep.compute_preview_times() == []


def test_compute_preview_times_zero_interval_empty(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "0"
    env.rep.count_text = "2"
    assert env.rep.compute_preview_times() == []


def test_compute_preview_times_no_tracking_empty(env):
    _open(env, [1.0], selected=[0])
    env.ctx.current_file = "other"  # resets tracking; offsets empty
    assert env.rep.compute_preview_times() == []


def test_compute_preview_times_respects_duration(env):
    _open(env, [1.0], selected=[0], dur=10.0)
    env.rep.interval_text = "6.00"
    env.rep.count_text = "5"
    # rep anchors 7,13,19,25,31 -> only 7.0 fits inside dur
    assert env.rep.compute_preview_times() == [7.0]


def test_compute_preview_pools_shape(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "1"
    pools = env.rep.compute_preview_pools()
    assert [p["time"] for p in pools] == [3.0, 4.0]
    assert pools[0]["files"] == ["a.ogg"]
    assert pools[0]["volume"] == 1.0


def test_compute_preview_pools_hidden_empty(env):
    env.rep.hide()
    assert env.rep.compute_preview_pools() == []


def test_compute_preview_pools_invalid_count_empty(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "abc"
    assert env.rep.compute_preview_pools() == []


def test_compute_preview_pools_zero_interval_empty(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "0"
    env.rep.count_text = "2"
    assert env.rep.compute_preview_pools() == []


def test_compute_preview_pools_no_tracking_empty(env):
    _open(env, [1.0], selected=[0])
    env.ctx.current_file = "other"  # resets tracking; offsets empty
    assert env.rep.compute_preview_pools() == []


def test_compute_preview_pools_respects_duration(env):
    _open(env, [1.0], selected=[0], dur=10.0)
    env.rep.interval_text = "6.00"
    env.rep.count_text = "5"
    pools = env.rep.compute_preview_pools()
    assert [p["time"] for p in pools] == [7.0]


def test_preview_text_creates(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.interval_text = "2.00"
    env.rep.count_text = "2"
    assert env.rep.preview_text() == "Creates 4 new marker(s)"


def test_preview_text_none(env):
    env.rep.hide()
    assert env.rep.preview_text() == "No new markers to create"


# ==========================================================================
# _shift_selected and anchor entry points
# ==========================================================================


def test_shift_selected_clamps_and_finalizes(env):
    pools = _open(env, [1.0, 2.0], selected=[0, 1], dur=10.0)
    env.rep._shift_selected(-5.0)
    assert pools[0]["time"] == 0.0
    assert pools[1]["time"] == 0.0
    env.rep._shift_selected(20.0)
    assert pools[0]["time"] == 10.0
    assert env.coord.video.drag_calls == 2


def test_shift_selected_untracked_pools_untouched(env):
    pools = _open(env, [1.0, 2.0], selected=[0], dur=10.0)
    env.rep._shift_selected(1.0)
    assert pools[0]["time"] == 2.0
    assert pools[1]["time"] == 2.0  # not tracked


def test_shift_selected_hidden_noop(env):
    _open(env, [1.0], selected=[0])
    env.rep.hide()
    env.rep._shift_selected(1.0)
    assert env.coord.video.drag_calls == 0


def test_shift_selected_pools_replaced_noop(env):
    _open(env, [1.0], selected=[0])
    _entry(env)["pools"] = [_pool(5.0)]
    env.rep._shift_selected(1.0)
    assert env.coord.video.drag_calls == 0


def test_shift_selected_entry_deleted_noop(env):
    _open(env, [1.0], selected=[0])
    del env.store._data[create_vid_key(env.tag)]
    env.rep._shift_selected(1.0)
    assert env.coord.video.drag_calls == 0


def test_nudge_anchor_shifts_group(env):
    pools = _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.nudge_anchor(0.5)
    assert pools[0]["time"] == 1.5
    assert pools[1]["time"] == 2.5
    assert env.coord.video.drag_calls == 1


def test_commit_anchor_parses_time(env):
    pools = _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.anchor_text = "00:02.000"  # exercises the anchor_text setter
    env.rep.commit_anchor()
    assert pools[0]["time"] == 2.0
    assert pools[1]["time"] == 3.0


def test_commit_anchor_invalid_noop(env):
    pools = _open(env, [1.0], selected=[0])
    env.rep.anchor_text = "bogus"
    env.rep.commit_anchor()
    assert pools[0]["time"] == 1.0


def test_commit_anchor_same_time_noop(env):
    pools = _open(env, [1.0], selected=[0])
    env.rep.anchor_text = "00:01.000"
    env.rep.commit_anchor()
    assert pools[0]["time"] == 1.0
    assert env.coord.video.drag_calls == 0


# ==========================================================================
# interval / count text edits
# ==========================================================================


def test_commit_interval_invalid_resets(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "abc"
    env.rep.commit_interval()
    assert env.rep.interval_text == "1.00"
    env.rep.interval_text = "0"
    env.rep.commit_interval()
    assert env.rep.interval_text == "1.00"


def test_commit_interval_valid_kept(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "2.50"
    env.rep.commit_interval()
    assert env.rep.interval_text == "2.50"


def test_nudge_interval_clamps_min(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "0.00"
    env.rep.nudge_interval(-0.5)
    assert env.rep.interval_text == "0.01"
    env.rep.nudge_interval(0.5)
    assert env.rep.interval_text == "0.51"


def test_nudge_interval_invalid_defaults_one(env):
    _open(env, [1.0], selected=[0])
    env.rep.interval_text = "abc"
    env.rep.nudge_interval(0.5)
    assert env.rep.interval_text == "1.50"


def test_nudge_count_clamps_zero(env):
    _open(env, [1.0], selected=[0])
    env.rep.count_text = "0"
    env.rep.nudge_count(-1)
    assert env.rep.count_text == "0"
    env.rep.nudge_count(2)
    assert env.rep.count_text == "2"


def test_nudge_count_invalid_defaults_zero(env):
    _open(env, [1.0], selected=[0])
    env.rep.count_text = "abc"
    env.rep.nudge_count(1)
    assert env.rep.count_text == "1"


def test_commit_count_invalid_resets(env):
    _open(env, [1.0], selected=[0])
    env.rep.count_text = "abc"
    env.rep.commit_count()
    assert env.rep.count_text == "0"
    env.rep.count_text = "-1"
    env.rep.commit_count()
    assert env.rep.count_text == "0"
    env.rep.count_text = "3"
    env.rep.commit_count()
    assert env.rep.count_text == "3"


# ==========================================================================
# hide / toggle_preview_sfx
# ==========================================================================


def test_hide_resets_state(env):
    _open(env, [1.0, 2.0], selected=[0, 1])
    env.rep.hide()
    assert env.rep.dialog_visible is False
    assert env.rep._vid_key == ""
    assert env.rep._tracked is None
    assert env.rep._anchor_pool is None
    assert env.rep.anchor == 0.0
    assert env.rep.offsets == []
    assert env.rep.sel_count == 0


def test_toggle_preview_sfx(env):
    assert env.rep.preview_sfx_enabled is True
    env.rep.toggle_preview_sfx()
    assert env.rep.preview_sfx_enabled is False
    env.rep.toggle_preview_sfx()
    assert env.rep.preview_sfx_enabled is True
