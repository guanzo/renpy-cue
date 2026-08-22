# -*- coding: utf-8 -*-
# Tests for cue_lib.undo -- CueUndoManager snapshot-on-save undo/redo.
#
# The manager takes its collaborators as constructor args (store, ctx,
# markers), so the fixture is a plain factory call -- no _cue
# singleton mutation.  renpy.restart_interaction() is mocked by conftest.

import time

import pytest

from cue_lib.state import CueContext
from cue_lib.undo import CueUndoManager


class FakePoolContext(object):
    def __init__(self):
        self.active_pool = 0


class FakeVideoContext(object):
    def __init__(self):
        self.active_pool = 0
        self.selected = set()
        self.sync_text_calls = 0

    def sync_text(self):
        self.sync_text_calls += 1


class FakeMarkers(object):
    """Coordinator stand-in -- the UI attributes _clamp_ui() touches."""

    def __init__(self):
        self.image = FakePoolContext()
        self.dialogue = FakePoolContext()
        self.loop = FakePoolContext()
        self.video = FakeVideoContext()


class FakeStore(object):
    """Data store stand-in: the three dicts plus the persistence calls
    _restore() makes.  Undo logic is about snapshots, not disk layout, so a
    fake keeps these tests focused; the real store is covered by
    test_marker_store.py."""

    def __init__(self):
        self._data = {}
        self._presets = {}
        self._video_presets = {}
        self._session_created = set()
        self.save_count = 0
        self.deleted = []

    def save_all(self):
        self.save_count += 1

    def delete_removed_files(self, old_marker_keys, old_presets, old_video_presets, old_session_created):
        self.deleted.append(
            (set(old_marker_keys), old_presets, old_video_presets, set(old_session_created)))


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def undo(store):
    return CueUndoManager(CueContext(), store, markers=FakeMarkers())


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_state_has_no_undo_or_redo(undo):
    assert not undo.can_undo()
    assert not undo.can_redo()


def test_capture_without_seed_does_not_create_entry(undo):
    undo.capture()
    assert not undo.can_undo()


# ---------------------------------------------------------------------------
# Seed + capture + undo + redo
# ---------------------------------------------------------------------------

def test_seed_then_capture_enables_undo(undo, store):
    undo.seed()
    store._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()
    assert undo.can_undo()


def test_undo_restores_previous_state(undo, store):
    undo.seed()
    store._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()

    undo.undo()
    assert "k" not in store._data
    assert undo.can_redo()


def test_redo_reapplies_undone_state(undo, store):
    undo.seed()
    store._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()

    undo.undo()
    undo.redo()
    assert store._data["k"] == {"pools": [[1.0, 2.0]]}
    assert not undo.can_redo()
    assert undo.can_undo()


def test_undo_with_empty_stack_is_noop(undo):
    undo.undo()
    assert not undo.can_redo()


def test_redo_with_empty_stack_is_noop(undo):
    undo.redo()
    assert not undo.can_undo()


def test_new_capture_after_undo_clears_redo(undo, store):
    undo.seed()
    store._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()
    undo.undo()
    assert undo.can_redo()

    store._data["k2"] = {"pools": []}
    undo.capture()
    assert not undo.can_redo()


def test_restore_repersists_and_recording_flag_resets(undo, store):
    undo.seed()
    store._data["k"] = {"pools": [[1.0, 2.0]]}
    undo.capture()

    undo.undo()
    # _restore calls save_all() while _recording is False, then resets it.
    assert store.save_count == 1
    assert undo._recording is True


def test_multiple_undo_steps_walk_back_history(undo, store, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    store._data["a"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    store._data["b"] = {"pools": []}
    clock.now = 2.0
    undo.capture()

    undo.undo()
    assert "b" not in store._data
    assert "a" in store._data
    undo.undo()
    assert "a" not in store._data


# ---------------------------------------------------------------------------
# Dedupe window
# ---------------------------------------------------------------------------

def test_rapid_captures_share_an_undo_slot(undo, store, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    store._data["a"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    store._data["b"] = {"pools": []}
    clock.now = 1.05  # within DEDUPE_WINDOW (0.15s)
    undo.capture()

    # One undo step for the compound op, targeting the pre-op state --
    # the first save's entry is kept, not overwritten by the mid-flight
    # state.  Undo fully reverses both mutations.
    assert len(undo._undo) == 1
    undo.undo()
    assert "a" not in store._data
    assert "b" not in store._data
    assert not undo.can_undo()


def test_captures_outside_window_create_separate_slots(undo, store, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    store._data["a"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    store._data["b"] = {"pools": []}
    clock.now = 2.0  # outside DEDUPE_WINDOW
    undo.capture()

    assert len(undo._undo) == 2


# ---------------------------------------------------------------------------
# MAX_UNDO trimming
# ---------------------------------------------------------------------------

def test_undo_stack_is_capped_at_max_undo(undo, store, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    for i in range(CueUndoManager.MAX_UNDO + 5):
        store._data["step"] = {"pools": [[float(i), float(i)]]}
        clock.now += 1.0
        undo.capture()

    assert len(undo._undo) == CueUndoManager.MAX_UNDO


def test_reset_clears_stacks_and_reseeds(undo, store, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    store._data["k"] = {"pools": []}
    clock.now = 1.0
    undo.capture()
    store._data["k2"] = {"pools": []}
    clock.now = 2.0
    undo.capture()
    assert undo.can_undo()

    undo.reset()
    assert not undo.can_undo()
    assert not undo.can_redo()
    assert undo._last_ts == 0.0
    assert undo._previous is not None  # re-seeded to current state


def test_capture_skips_when_not_recording(undo, store):
    undo.seed()
    store._data["k"] = {"pools": []}
    undo._recording = False
    undo.capture()
    assert undo._recording is True
    assert not undo.can_undo()  # restore's re-persist is not a new undo step


def test_redo_trims_undo_overflow(undo, store, monkeypatch):
    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(time, "time", clock.time)

    undo.seed()
    for i in range(CueUndoManager.MAX_UNDO):
        store._data["step"] = {"pools": [[float(i)]]}
        clock.now += 1.0
        undo.capture()
    assert len(undo._undo) == CueUndoManager.MAX_UNDO
    undo._redo.append(undo._snapshot())
    undo.redo()
    assert len(undo._undo) == CueUndoManager.MAX_UNDO


# ---------------------------------------------------------------------------
# _clamp_ui branches
# ---------------------------------------------------------------------------

def test_clamp_ui_clamps_all_targets(undo, store):
    undo._ctx.current_file = "movies/x.webm"
    undo._ctx.current_dialogue = "hi"
    store._data["i_movies/x.webm"] = {"pools": [[1.0], [2.0]]}
    store._data["d_movies/x.webm__hi"] = {"pools": [[1.0]]}
    store._data["v_movies/x.webm"] = {"pools": [[1.0], [2.0], [3.0]]}
    undo._markers.image.active_pool = 5
    undo._markers.dialogue.active_pool = 5
    undo._markers.video.active_pool = 5
    undo._clamp_ui()
    assert undo._markers.image.active_pool == 1     # min(5, 2 - 1)
    assert undo._markers.dialogue.active_pool == 0  # min(5, 1 - 1)
    assert undo._markers.video.active_pool == 2     # min(5, 3 - 1)
    assert undo._markers.video.selected == set()
    assert undo._markers.video.sync_text_calls == 1
