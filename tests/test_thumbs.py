# -*- coding: utf-8 -*-
# Tests for cue_lib.thumbs -- the scene-thumbnail library: a downloaded
# per-game replay-label -> thumb mapping, with a generic fallback to captured
# marker filepaths.

import json as _json
import os

import pytest
import renpy.config as _config

from cue_lib.paths import CuePaths
from cue_lib.thumbs import CueThumbManager
from tests.fakes import DiskBackedMarkers

GAME_ID = "test_game"
SID = "TestGame-12345"


@pytest.fixture(autouse=True)
def _mock_config(monkeypatch, tmp_path):
    """Point the mock config's gamedir at a tmp install dir holding the mod."""
    gamedir = str(tmp_path / "game")
    monkeypatch.setattr(_config, "gamedir", gamedir)
    monkeypatch.setattr(_config, "save_directory", SID)
    return gamedir


def _write(root, rel, content):
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _shipped_path(root):
    return os.path.join(root, "data", "cue_thumbs.json")


def _write_shipped(root, entries):
    _write(
        root,
        os.path.relpath(_shipped_path(root), root).replace(os.sep, "/"),
        _json.dumps(
            {
                "scraped": "2026-08-29T10:00:00",
                "games": {SID: {"game": "TestGame", "install": "Test", "entries": entries}},
            }
        ),
    )


def _write_marker(root, name, entry):
    _write(root, "data/markers/{}/{}.json".format(GAME_ID, name), _json.dumps(entry))


def _manager(tmp_path):
    root = str(tmp_path / "cue_root")
    paths = CuePaths(root, GAME_ID)
    return CueThumbManager(paths, DiskBackedMarkers(paths))


# ---------------------------------------------------------------------------
# load -- shipped mapping
# ---------------------------------------------------------------------------


def test_load_reads_shipped_mapping(tmp_path, _mock_config):
    _write_shipped(str(tmp_path / "cue_root"), {"Run 1": "images/gallery/run1.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.entries == {"Run 1": "images/gallery/run1.png"}


def test_load_missing_file_is_empty(tmp_path, _mock_config):
    m = _manager(tmp_path)
    m.load()

    assert m.entries == {}


def test_load_no_save_directory_is_empty(tmp_path, _mock_config, monkeypatch):
    monkeypatch.setattr(_config, "save_directory", "")
    _write_shipped(str(tmp_path / "cue_root"), {"Run 1": "images/gallery/run1.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.entries == {}


def test_load_replaces_previous_entries(tmp_path, _mock_config):
    m = _manager(tmp_path)
    m.load()

    _write_shipped(str(tmp_path / "cue_root"), {"Run 1": "a.png"})
    m.load()

    assert m.entries == {"Run 1": "a.png"}


# ---------------------------------------------------------------------------
# thumb_for -- shipped mapping wins, marker fallback otherwise
# ---------------------------------------------------------------------------


def test_thumb_for_shipped_wins_over_fallback(tmp_path, _mock_config):
    _write_shipped(str(tmp_path / "cue_root"), {"Run 1": "images/gallery/run1.png"})
    _write_marker(tmp_path / "cue_root", "a", {"replay": "Run 1", "filepath": "images/bg/beach.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("Run 1") == "images/gallery/run1.png"


def test_thumb_for_fallback_first_image_marker(tmp_path, _mock_config):
    # No shipped mapping file at all -- the captured marker filepath stands in.
    _write_marker(tmp_path / "cue_root", "a", {"replay": "Run 1", "filepath": "images/bg/beach.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("Run 1") == "images/bg/beach.png"


def test_thumb_for_fallback_skips_video_filepaths(tmp_path, _mock_config):
    _write_marker(tmp_path / "cue_root", "a", {"replay": "Run 1", "filepath": "videos/run1.webm"})
    _write_marker(tmp_path / "cue_root", "b", {"replay": "Run 1", "filepath": "images/bg/beach.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("Run 1") == "images/bg/beach.png"


def test_thumb_for_fallback_first_marker_wins(tmp_path, _mock_config):
    # Deterministic across a marker dir: the first image marker (sorted) wins.
    _write_marker(tmp_path / "cue_root", "b", {"replay": "Run 1", "filepath": "images/b/b.png"})
    _write_marker(tmp_path / "cue_root", "a", {"replay": "Run 1", "filepath": "images/a/a.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("Run 1") == "images/a/a.png"


def test_thumb_for_unknown_label_is_none(tmp_path, _mock_config):
    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("ghost") is None


def test_thumb_for_no_marker_dir_is_none(tmp_path, _mock_config):
    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("Run 1") is None


def test_thumb_for_marker_without_replay_field_ignored(tmp_path, _mock_config):
    _write_marker(tmp_path / "cue_root", "a", {"filepath": "images/bg/beach.png"})

    m = _manager(tmp_path)
    m.load()

    assert m.thumb_for("Run 1") is None


def test_fallback_built_lazily_on_first_miss(tmp_path, _mock_config):
    m = _manager(tmp_path)
    m.load()

    assert m._fallbacks is None
    assert m.thumb_for("Run 1") is None
    assert m._fallbacks == {}

    _write_marker(tmp_path / "cue_root", "a", {"replay": "Run 1", "filepath": "images/bg/beach.png"})
    # The lazy map is not rebuilt mid-session; a reload is required.
    assert m.thumb_for("Run 1") is None
