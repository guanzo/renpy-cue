# -*- coding: utf-8 -*-
# Tests for cue_lib.replays -- the current game's replays-with-markers list.

import json as _json
import os
import types as _types

import pytest

from cue_lib.replays import (
    CueCastFilter,
    CueReplayCast,
    CueReplayLibrary,
    _cue_replay_labels,
    _cue_speaker_display,
    _cue_speaker_label,
)
from cue_lib.state import _cue
from cue_lib.ui.overlay import CueOverlay

GAME_ID = "test_game"


@pytest.fixture(autouse=True)
def _wire_overlay(monkeypatch):
    """Give _cue a real overlay so the cast filter's open/close state lives
    somewhere real in tests."""
    monkeypatch.setattr(_cue, "overlay", CueOverlay())


def _write(root, rel, content):
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _write_marker(cue_env, name, entry):
    """Write one marker JSON to the game's marker dir."""
    _write(cue_env.paths.original_root, "data/markers/{}/{}.json".format(GAME_ID, name), _json.dumps(entry))


def test_replay_labels_counts_per_replay(cue_env):
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "b", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "c", {"replay": "Run 2", "pools": []})
    _write_marker(cue_env, "d", {"pools": []})  # never edited in a replay

    labels = _cue_replay_labels(cue_env.paths.original_root, GAME_ID)

    assert labels == [("Run 1", 2), ("Run 2", 1)]


def test_scan_populates_entries_sorted(cue_env):
    _write_marker(cue_env, "a", {"replay": "Run 2", "pools": []})
    _write_marker(cue_env, "b", {"replay": "Run 1", "pools": []})

    lib = CueReplayLibrary(cue_env.paths)
    lib.scan()

    assert lib.entries == [{"replay": "Run 1", "marker_count": 1}, {"replay": "Run 2", "marker_count": 1}]


def test_scan_empty_when_no_markers_dir(cue_env):
    lib = CueReplayLibrary(cue_env.paths)
    lib.scan()
    assert lib.entries == []


def test_scan_refreshes_after_new_markers(cue_env):
    lib = CueReplayLibrary(cue_env.paths)
    lib.scan()
    assert lib.entries == []

    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": []})
    lib.scan()

    assert lib.entries == [{"replay": "Run 1", "marker_count": 1}]


# ---------------------------------------------------------------------------
# play -- start vs replace
# ---------------------------------------------------------------------------


def _fake_renpy(monkeypatch, has_label=True, in_replay=None):
    """Stub the three renpy hooks play() touches.  Returns the recorded calls."""
    import renpy as _renpy

    calls = {"call_replay": [], "end_replay": []}
    monkeypatch.setattr(_renpy, "has_label", lambda label: has_label, raising=False)
    monkeypatch.setattr(_renpy, "call_replay", lambda label: calls["call_replay"].append(label), raising=False)
    monkeypatch.setattr(_renpy, "end_replay", lambda: calls["end_replay"].append(1), raising=False)
    monkeypatch.setattr(_renpy.store, "_in_replay", in_replay, raising=False)
    return calls


def test_play_starts_replay_when_idle(monkeypatch, cue_env):
    lib = CueReplayLibrary(cue_env.paths)
    calls = _fake_renpy(monkeypatch, in_replay=None)

    lib.play("Run 1")

    assert calls["call_replay"] == ["Run 1"]
    assert calls["end_replay"] == []
    assert lib.pending_replay is None


def test_play_replaces_active_replay(monkeypatch, cue_env):
    # Clicking a scene while another replay runs must not nest: pending_replay
    # records the label so the after_replay hook can chain it, and the active
    # replay is ended instead of pushed under.
    lib = CueReplayLibrary(cue_env.paths)
    calls = _fake_renpy(monkeypatch, in_replay="Run 1")

    lib.play("Run 2")

    assert calls["call_replay"] == []
    assert calls["end_replay"] == [1]
    assert lib.pending_replay == "Run 2"


def test_play_missing_label_noop(monkeypatch, cue_env):
    lib = CueReplayLibrary(cue_env.paths)
    calls = _fake_renpy(monkeypatch, has_label=False, in_replay="Run 1")

    lib.play("ghost")

    assert calls["call_replay"] == []
    assert calls["end_replay"] == []
    assert lib.pending_replay is None


# ---------------------------------------------------------------------------
# CueReplayCast -- speaking cast per replay
# ---------------------------------------------------------------------------


def _read_replay(cue_env, replay_id):
    with open(cue_env.paths.replay_path(replay_id), "r") as f:
        return _json.load(f)


def test_cast_record_speaker_writes_file(cue_env):
    cast = CueReplayCast(cue_env.paths)

    cast.record_speaker("Run 1", "Dawe")

    assert _read_replay(cue_env, "Run 1") == {"replay": "Run 1", "characters": ["Dawe"]}


def test_cast_existing_speaker_is_idempotent(cue_env):
    cast = CueReplayCast(cue_env.paths)

    cast.record_speaker("Run 1", "Dawe")
    cast.record_speaker("Run 1", "Dawe")

    assert _read_replay(cue_env, "Run 1") == {"replay": "Run 1", "characters": ["Dawe"]}


def test_cast_appends_new_speaker(cue_env):
    cast = CueReplayCast(cue_env.paths)

    cast.record_speaker("Run 1", "Dawe")
    cast.record_speaker("Run 1", "SG")
    cast.record_speaker("Run 1", "Jill")

    assert _read_replay(cue_env, "Run 1") == {"replay": "Run 1", "characters": ["Dawe", "Jill", "SG"]}


def test_cast_loads_existing_cast_before_append(cue_env):
    _write(
        cue_env.paths.original_root,
        "data/markers/{}/replays/Run 1.json".format(GAME_ID),
        _json.dumps({"replay": "Run 1", "characters": ["Dawe"]}),
    )
    cast = CueReplayCast(cue_env.paths)

    cast.record_speaker("Run 1", "SG")

    assert _read_replay(cue_env, "Run 1") == {"replay": "Run 1", "characters": ["Dawe", "SG"]}


def test_cast_speakers_are_per_replay(cue_env):
    cast = CueReplayCast(cue_env.paths)

    cast.record_speaker("Run 1", "Dawe")
    cast.record_speaker("Run 2", "SG")

    assert _read_replay(cue_env, "Run 1")["characters"] == ["Dawe"]
    assert _read_replay(cue_env, "Run 2")["characters"] == ["SG"]


def test_library_owns_cast_submanager(cue_env):
    lib = CueReplayLibrary(cue_env.paths)

    lib.cast.record_speaker("Run 1", "Dawe")

    assert _read_replay(cue_env, "Run 1") == {"replay": "Run 1", "characters": ["Dawe"]}


# ---------------------------------------------------------------------------
# _cue_speaker_label -- protagonist collapse to "mc"
# ---------------------------------------------------------------------------


def _fake_mc(monkeypatch, name):
    import renpy as _renpy

    monkeypatch.setattr(_renpy.store, "mc", _types.SimpleNamespace(name=name), raising=False)


def test_speaker_label_collapses_mc_display_name(monkeypatch):
    _fake_mc(monkeypatch, "Dave")

    assert _cue_speaker_label("Dave") == "mc"


def test_speaker_label_passthrough_other_characters(monkeypatch):
    _fake_mc(monkeypatch, "Dave")

    assert _cue_speaker_label("Jill") == "Jill"


def test_speaker_label_passthrough_without_mc(monkeypatch):
    import renpy as _renpy

    monkeypatch.delattr(_renpy.store, "mc", raising=False)

    assert _cue_speaker_label("Dave") == "Dave"


# ---------------------------------------------------------------------------
# _cue_speaker_display -- tag to display name (UI only)
# ---------------------------------------------------------------------------


def test_speaker_display_resolves_static_name(monkeypatch):
    import renpy as _renpy

    monkeypatch.setattr(_renpy.store, "jill", _types.SimpleNamespace(name="Jill"), raising=False)

    assert _cue_speaker_display("jill") == "Jill"


def test_speaker_display_calls_dynamic_name(monkeypatch):
    import renpy as _renpy

    monkeypatch.setattr(_renpy.store, "jill", _types.SimpleNamespace(name=lambda: "Jill"), raising=False)

    assert _cue_speaker_display("jill") == "Jill"


def test_speaker_display_falls_back_to_tag(monkeypatch):
    import renpy as _renpy

    monkeypatch.setattr(_renpy.store, "jill", _types.SimpleNamespace(name=None), raising=False)
    assert _cue_speaker_display("jill") == "jill"

    monkeypatch.delattr(_renpy.store, "sg", raising=False)
    assert _cue_speaker_display("sg") == "sg"


# ---------------------------------------------------------------------------
# CueReplayCast -- load_all / cast_for / all_speakers
# ---------------------------------------------------------------------------


def _write_cast(cue_env, replay_id, characters):
    _write(
        cue_env.paths.original_root,
        "data/markers/{}/replays/{}.json".format(GAME_ID, replay_id),
        _json.dumps({"replay": replay_id, "characters": characters}),
    )


def test_cast_load_all_populates_speakers(cue_env):
    _write_cast(cue_env, "Run 1", ["Dawe"])
    _write_cast(cue_env, "Run 2", ["Jill", "Dawe"])
    cast = CueReplayCast(cue_env.paths)

    cast.load_all()

    assert cast.all_speakers() == ["Dawe", "Jill"]


def test_cast_load_all_empty_dir(cue_env):
    cast = CueReplayCast(cue_env.paths)

    cast.load_all()

    assert cast.all_speakers() == []


def test_cast_for_loads_single_replay(cue_env):
    _write_cast(cue_env, "Run 1", ["Dawe"])
    cast = CueReplayCast(cue_env.paths)

    assert cast.cast_for("Run 1") == set(["Dawe"])


def test_cast_for_missing_replay_is_empty(cue_env):
    cast = CueReplayCast(cue_env.paths)

    assert cast.cast_for("ghost") == set()


# ---------------------------------------------------------------------------
# CueCastFilter -- multi-select cast filter
# ---------------------------------------------------------------------------


def test_filter_toggle_adds_and_removes(cue_env):
    filter = CueCastFilter(CueReplayCast(cue_env.paths))

    filter.toggle("Dawe")
    assert filter.selected == set(["Dawe"])

    filter.toggle("Dawe")
    assert filter.selected == set()

    filter.toggle("Dawe")
    filter.toggle("Jill")
    assert filter.selected == set(["Dawe", "Jill"])


def test_filter_clear(cue_env):
    filter = CueCastFilter(CueReplayCast(cue_env.paths))

    filter.toggle("Dawe")
    filter.clear()

    assert filter.selected == set()


def test_filter_matches_intersects_cast(cue_env):
    cast = CueReplayCast(cue_env.paths)
    cast.record_speaker("Run 1", "Dawe")
    cast.record_speaker("Run 1", "SG")
    filter = CueCastFilter(cast)

    filter.toggle("SG")

    assert filter.matches("Run 1")
    assert not filter.matches("Run 2")


def test_filter_matches_empty_selects_everything(cue_env):
    cast = CueReplayCast(cue_env.paths)
    cast.record_speaker("Run 1", "Dawe")
    filter = CueCastFilter(cast)

    assert filter.matches("Run 1")
    assert filter.matches("Run 2")


def test_filter_options_are_all_speakers(cue_env):
    cast = CueReplayCast(cue_env.paths)
    cast.record_speaker("Run 1", "SG")
    cast.record_speaker("Run 1", "Dawe")
    cast.record_speaker("Run 2", "Jill")
    filter = CueCastFilter(cast)

    assert filter.options() == ["Dawe", "Jill", "SG"]


def test_filter_options_hide_mc(cue_env):
    from cue_lib.replays import CUE_MC_TAG

    cast = CueReplayCast(cue_env.paths)
    cast.record_speaker("Run 1", "SG")
    cast.record_speaker("Run 1", CUE_MC_TAG)
    filter = CueCastFilter(cast)

    assert filter.options() == ["SG"]


def test_filter_open_close_rides_focus_pin(monkeypatch, cue_env):
    monkeypatch.setattr(_cue.overlay, "active_input", "")
    monkeypatch.setattr(_cue.overlay, "active_input_rect", None)
    monkeypatch.setattr(_cue.overlay, "active_dropdown", None)
    filter = CueCastFilter(CueReplayCast(cue_env.paths))

    assert not filter.is_open()

    # Opening pins the trigger rect captured by the focus pin on the mousedown
    # and records the open dropdown on _cue.overlay.  The pin captures floats
    # (focus rects), and screen xpos/ypos/xsize treat floats as parent
    # fractions, so the anchor must be ints.
    _cue.overlay.active_input_rect = (0.0, 0.0, 300.0, 20.0)
    filter.toggle_open()

    assert filter.is_open()
    assert _cue.overlay.active_dropdown is filter
    assert filter.trigger_rect() == (0, 0, 300, 20)

    filter.toggle_open()

    assert not filter.is_open()
    assert _cue.overlay.active_dropdown is None
    assert filter.trigger_rect() is None


def test_library_owns_cast_filter(cue_env):
    lib = CueReplayLibrary(cue_env.paths)

    assert lib.cast_filter._cast is lib.cast
    lib.cast_filter.toggle("Dawe")
    assert lib.cast_filter.selected == set(["Dawe"])
