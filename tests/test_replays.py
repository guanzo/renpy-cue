# -*- coding: utf-8 -*-
# Tests for cue_lib.replays -- the current game's replays-with-markers list.

import json as _json
import os
import types as _types

from cue_lib.replays import CueReplayCast, CueReplayLibrary, _cue_replay_labels, _cue_speaker_label

GAME_ID = "test_game"


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
