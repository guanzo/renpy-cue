# -*- coding: utf-8 -*-
# Tests for the pure helper functions extracted from cue_lib.trigger.
#
# _cue_pick_deduped and _cue_marker_reached take all inputs as arguments and
# touch no _cue / renpy state, so they run headlessly. _cue_pick_file is
# monkeypatched to make the dedupe draws deterministic.

import cue_lib.trigger as _trigger


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
