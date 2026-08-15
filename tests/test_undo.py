# -*- coding: utf-8 -*-
# Tests for cue_lib.undo -- CueUndoManager snapshot-on-save undo/redo.
#
# The manager reads _cue.markers and _cue.current_file etc. off the module
# singleton, so tests swap in a fake markers object.  _cue_log is a no-op
# outside the game, and renpy.restart_interaction() is mocked by conftest.

import time

import pytest

from cue_lib.state import _cue
from cue_lib.undo import CueUndoManager


class FakeVideoContext(object):
    def __init__(self):
        self.target_pool = 0
        self.selected = set()

    def sync_text(self):
        pass


class FakeMarkers(object):
    """Minimal stand-in for CueMarkerManager -- the three stores plus the
    UI attributes _clamp_ui() touches."""

    def __init__(self):
        self._data = {}
        self._presets = {}
        self._video_presets = {}
        self._session_created = set()
        self._img_target = 0
        self._dlg_target = 0
        self._loop_target = 0
        self.video = FakeVideoContext()
        self.save_count = 0

    def save_all(self):
        # Real implementation calls _cue.undo.capture() via _post_save;
        # the fake just records the call so _restore() is observable.
        self.save_count += 1

    def delete_removed_files(self, *_args):
        # Real implementation deletes DB files for markers/presets dropped by
        # a restore.  The fake ignores it -- nothing is written to disk.
        pass


@pytest.fixture
def fake_markers():
    old_markers = _cue.markers
    old_file = _cue.current_file
    old_dialogue = _cue.current_dialogue
    old_undo = _cue.undo
    markers = FakeMarkers()
    _cue.markers = markers  # pyright: ignore[reportAttributeAccessIssue]  # test fake swaps the real manager
    _cue.current_file = ""
    _cue.current_dialogue = ""
    yield markers
    _cue.markers = old_markers
    _cue.current_file = old_file
    _cue.current_dialogue = old_dialogue
    _cue.undo = old_undo


@pytest.fixture
def undo(fake_markers):
    manager = CueUndoManager()
    _cue.undo = manager
    return manager


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_state_has_no_undo_or_redo(undo):
    assert not undo.can_undo()
    assert not undo.can_redo()


def test_capture_without_seed_does_not_create_entry(undo, fake_markers):
    undo.capture()
    assert not undo.can_undo()


# ---------------------------------------------------------------------------
# Seed + capture + undo + redo
# ---------------------------------------------------------------------------

def test_seed_then_capture_enables_undo(undo, fake_markers):
    undo.seed()
    fake_markers._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()
    assert undo.can_undo()


def test_undo_restores_previous_state(undo, fake_markers):
    undo.seed()
    fake_markers._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()

    undo.undo()
    assert "k" not in fake_markers._data
    assert undo.can_redo()


def test_redo_reapplies_undone_state(undo, fake_markers):
    undo.seed()
    fake_markers._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()

    undo.undo()
    undo.redo()
    assert fake_markers._data["k"] == {"pools": [[1.0, 2.0]]}
    assert not undo.can_redo()
    assert undo.can_undo()


def test_undo_with_empty_stack_is_noop(undo, fake_markers):
    undo.undo()
    assert not undo.can_redo()


def test_redo_with_empty_stack_is_noop(undo, fake_markers):
    undo.redo()
    assert not undo.can_undo()


def test_new_capture_after_undo_clears_redo(undo, fake_markers):
    undo.seed()
    fake_markers._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()
    undo.undo()
    assert undo.can_redo()

    fake_markers._data["k2"] = {"pools": []}
    undo.capture()
    assert not undo.can_redo()


def test_restore_repersists_and_recording_flag_resets(undo, fake_markers):
    undo.seed()
    fake_markers._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()

    undo.undo()
    # _restore calls save_all() while _recording is False, then resets it.
    assert fake_markers.save_count == 1
    assert undo._recording is True


def test_multiple_undo_steps_walk_back_history(undo, fake_markers, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    fake_markers._data["a"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    fake_markers._data["b"] = {"pools": []}
    clock.now = 2.0
    undo.capture()

    undo.undo()
    assert "b" not in fake_markers._data
    assert "a" in fake_markers._data
    undo.undo()
    assert "a" not in fake_markers._data


# ---------------------------------------------------------------------------
# Dedupe window
# ---------------------------------------------------------------------------

def test_rapid_captures_share_an_undo_slot(undo, fake_markers, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    fake_markers._data["a"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    fake_markers._data["b"] = {"pools": []}
    clock.now = 1.05  # within DEDUPE_WINDOW (0.15s)
    undo.capture()

    # One undo step for the compound op, targeting the pre-op state --
    # the first save's entry is kept, not overwritten by the mid-flight
    # state.  Undo fully reverses both mutations.
    assert len(undo._undo) == 1
    undo.undo()
    assert "a" not in fake_markers._data
    assert "b" not in fake_markers._data
    assert not undo.can_undo()


def test_captures_outside_window_create_separate_slots(undo, fake_markers, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    fake_markers._data["a"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    fake_markers._data["b"] = {"pools": []}
    clock.now = 2.0  # outside DEDUPE_WINDOW
    undo.capture()

    assert len(undo._undo) == 2


# ---------------------------------------------------------------------------
# MAX_UNDO trimming
# ---------------------------------------------------------------------------

def test_undo_stack_is_capped_at_max_undo(undo, fake_markers, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    for i in range(CueUndoManager.MAX_UNDO + 5):
        fake_markers._data["step"] = {"pools": [[float(i), float(i)]]}
        clock.now += 1.0
        undo.capture()

    assert len(undo._undo) == CueUndoManager.MAX_UNDO
