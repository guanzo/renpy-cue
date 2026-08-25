# -*- coding: utf-8 -*-
# Tests for the pure helper functions extracted from cue_lib.trigger.
#
# _cue_pick_deduped and _cue_marker_reached take all inputs as arguments and
# touch no _cue / renpy state, so they run headlessly. _cue_pick_file is
# monkeypatched to make the dedupe draws deterministic.

import pytest

import cue_lib.trigger as _trigger
import cue_lib.trigger_debug as _tdmod


# ---------------------------------------------------------------------------
# _cue_pick_deduped (dedupe rule from fire_context / _tick_loop)
# ---------------------------------------------------------------------------


def test_pick_deduped_fresh_pick(monkeypatch):
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: "a")
    assert _trigger._cue_pick_deduped(["a", "b"], []) == "a"


def test_pick_deduped_collision_retries(monkeypatch):
    picks = iter(["a", "b"])
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: next(picks))
    assert _trigger._cue_pick_deduped(["a", "b"], ["a"]) == "b"


def test_pick_deduped_exhausted_retries_returns_none(monkeypatch):
    # 3 retries all collide; on the max_tries check it bails with None.
    picks = iter(["a", "a", "a", "a"])
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: next(picks))
    assert _trigger._cue_pick_deduped(["a", "b"], ["a"]) is None


def test_pick_deduped_single_file_pool_duplicates_none(monkeypatch):
    # A one-file pool legitimately repeats -- dedupe can't satisfy, so skip.
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: "a")
    assert _trigger._cue_pick_deduped(["a"], ["a"]) is None


def test_pick_deduped_single_file_pool_free_returns_file(monkeypatch):
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: "a")
    assert _trigger._cue_pick_deduped(["a"], []) == "a"


def test_pick_deduped_ignores_other_picks(monkeypatch):
    # Only this trigger's own picks are deduped, not every file ever played.
    monkeypatch.setattr(_trigger, "_cue_pick_file", lambda files: "b")
    assert _trigger._cue_pick_deduped(["a", "b"], ["a"]) == "b"


# ---------------------------------------------------------------------------
# _cue_marker_reached (video marker window / cross checks)
# ---------------------------------------------------------------------------


def test_marker_reached_forward_window():
    # mt <= eff < mt + tolerance
    assert _trigger._cue_marker_reached(5.0, 5.04, 0.0, 0.08)


def test_marker_reached_exact_position():
    assert _trigger._cue_marker_reached(5.0, 5.0, 0.0, 0.08)


def test_marker_reached_cross_check_jumped_past():
    # prev_eff < mt <= eff -- position jumped more than tolerance between ticks
    assert _trigger._cue_marker_reached(5.0, 6.0, 4.9, 0.08)


def test_marker_reached_cross_check_first_tick():
    # prev_eff starts at -1.0, so time-0 markers fire on the first tick
    assert _trigger._cue_marker_reached(0.0, 0.0, -1.0, 0.08)


def test_marker_reached_not_yet():
    assert not _trigger._cue_marker_reached(5.0, 4.9, 4.8, 0.08)


def test_marker_reached_past_window_and_not_crossed():
    # eff is past the window (5.08) but prev didn't cross the marker either
    assert not _trigger._cue_marker_reached(5.0, 5.2, 5.15, 0.08)


def test_marker_reached_way_before():
    assert not _trigger._cue_marker_reached(5.0, 0.5, 0.0, 0.08)


# ---------------------------------------------------------------------------
# Lead compensation (fire before the marker to center deltas on 0)
# ---------------------------------------------------------------------------


def test_marker_reached_lead_fires_early():
    # lead=0.04 fires at mt - lead even though eff < mt
    assert _trigger._cue_marker_reached(5.0, 4.96, 4.8, 0.08, 0.04)


def test_marker_reached_lead_zero_needs_marker():
    # lead=0 reproduces the late-fire behavior: eff must reach mt
    assert not _trigger._cue_marker_reached(5.0, 4.96, 4.8, 0.08, 0.0)


def test_marker_reached_lead_before_target_no_fire():
    # eff below the lead-adjusted target -- too early
    assert not _trigger._cue_marker_reached(5.0, 4.90, 4.8, 0.08, 0.04)


def test_marker_reached_lead_cross_check():
    # jumped from below to above the lead target in one tick
    assert _trigger._cue_marker_reached(5.0, 5.2, 4.9, 0.08, 0.04)


def test_marker_lead_half_advance():
    # 16.7ms cadence at 1.0x -> half a tick's position advance
    assert _trigger._cue_marker_lead(0.0167, 1.0) == pytest.approx(0.00835)


def test_marker_lead_scales_with_speed():
    assert _trigger._cue_marker_lead(0.0167, 1.6) == pytest.approx(0.01336)


def test_marker_lead_slow_cadence_centers():
    # the 20fps/1.6x case: full centering (half of the 0.08 advance) = the cap
    assert _trigger._cue_marker_lead(0.05, 1.6) == pytest.approx(_trigger.CUE_MARKER_LEAD_MAX)


def test_marker_lead_unknown_cadence_zero():
    # first tick: no wall-clock baseline yet, cadence unknown -> no lead
    assert _trigger._cue_marker_lead(0.0, 1.0) == 0.0


def test_marker_lead_clamps_max():
    # dropped frame / focus loss: a long interval must not inflate the lead
    assert _trigger._cue_marker_lead(0.5, 1.6) == _trigger.CUE_MARKER_LEAD_MAX


# ---------------------------------------------------------------------------
# _cue_td_missed_times (anomaly detector: markers past-due but never fired)
# ---------------------------------------------------------------------------


def test_td_missed_none_when_all_fired():
    played = {"v_doggy2@0.010#1", "v_doggy2@0.680#1"}
    assert _tdmod._cue_td_missed_times([0.010, 0.680], played, 1.0, 0.12) == []


def test_td_missed_past_due_unfired():
    played = {"v_doggy2@0.010#1"}
    assert _tdmod._cue_td_missed_times([0.010, 0.680], played, 1.0, 0.12) == [0.680]


def test_td_missed_not_yet_due():
    # t above eff - tolerance is still within the fire window, not a miss.
    assert _tdmod._cue_td_missed_times([0.900], set(), 1.0, 0.12) == []


def test_td_missed_at_due_boundary():
    # t == eff - tolerance is past-due (checked), so absent key is a miss.
    assert _tdmod._cue_td_missed_times([0.88], set(), 1.0, 0.12) == [0.88]


def test_td_missed_multiple_in_order():
    played = set()
    assert _tdmod._cue_td_missed_times([0.010, 0.680, 1.360], played, 2.0, 0.12) == [0.010, 0.680, 1.360]


def test_td_missed_empty_input():
    assert _tdmod._cue_td_missed_times([], set(), 1.0, 0.12) == []


def test_td_missed_ignores_other_video_keys():
    # A key for a different video/timing must not satisfy this marker.
    played = {"v_other@9.999#1"}
    assert _tdmod._cue_td_missed_times([0.680], played, 1.0, 0.12) == [0.680]
