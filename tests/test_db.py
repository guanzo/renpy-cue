# -*- coding: utf-8 -*-
# Tests for cue_lib.db -- file-backed persistence for markers and presets.
# Pure stdlib module (after the _cue_log extraction), so no Ren'Py mocks
# are needed beyond what conftest provides for the package import.

import hashlib
import os

import pytest

from cue_lib.db import CUE_HASH_TRUNC_LEN, CueDatabase, _key_to_filename
from cue_lib.paths import CuePaths
from cue_lib.util import _to_str


def _make_db(root, game_id="g1"):
    # type: (str, str) -> CueDatabase
    return CueDatabase(CuePaths(root, game_id=game_id))


@pytest.fixture
def db(cue_env):
    # Uses the cue_env fixture so the Cue + CueDatabase wiring pattern in
    # conftest is exercised; each test still gets a fresh tmp directory.
    return cue_env.db


# ---------------------------------------------------------------------------
# Key sanitisation
# ---------------------------------------------------------------------------

def test_key_to_filename_marker_key():
    assert _key_to_filename("v_anim_envy_bj3_ep10") == "v_anim_envy_bj3_ep10.json"


def test_key_to_filename_plain_key_with_spaces():
    assert _key_to_filename("i_bg beach") == "i_bg beach.json"


def test_key_to_filename_dialogue_key_double_underscore():
    key = "d_bg movie__some dialogue"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
    assert _key_to_filename(key) == "d_bg movie_{}.json".format(digest)


def test_key_to_filename_dialogue_key_legacy_pipe():
    key = "d_bg movie|some dialogue"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
    assert _key_to_filename(key) == "d_bg movie_{}.json".format(digest)


def test_key_to_filename_dialogue_key_without_separator():
    assert _key_to_filename("d_plain") == "d_plain.json"


# ---------------------------------------------------------------------------
# _to_str (no-op on Python 3, unicode-safe on Python 2)
# ---------------------------------------------------------------------------

def test_to_str_returns_same_objects_on_py3():
    plain = {"a": "x", "b": ["y", 1], "c": {"d": "z"}}
    result = _to_str(plain)
    assert result == plain
    assert result is plain  # untouched reference on Python 3


def test_to_str_scalars_unchanged():
    assert _to_str("hello") == "hello"
    assert _to_str(42) == 42
    assert _to_str(None) is None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_open_creates_directory_structure(tmp_path):
    database = _make_db(str(tmp_path))
    database.open()
    assert os.path.isdir(os.path.join(str(tmp_path), "data", "markers", "g1"))
    assert os.path.isdir(os.path.join(str(tmp_path), "data", "presets", "audio"))
    assert os.path.isdir(os.path.join(str(tmp_path), "data", "presets", "video"))
    assert os.path.isdir(os.path.join(str(tmp_path), "video", "g1"))
    assert database.is_open()


def test_close_marks_closed(db):
    db.close()
    assert not db.is_open()


def test_is_fresh_true_without_markers(db):
    assert db.is_fresh()


def test_is_fresh_false_after_marker_save(db):
    db.save_marker("v_key", {"pools": [[1.0, 2.0]]})
    assert not db.is_fresh()


# ---------------------------------------------------------------------------
# Marker round-trips
# ---------------------------------------------------------------------------

def test_save_and_load_marker_round_trip(db):
    entry = {"pools": [[0.0, 5.0], [10.0, 15.0]], "label": "my marker"}
    db.save_marker("v_anim", entry)

    markers = db.load_markers()
    assert "v_anim" in markers
    loaded = markers["v_anim"]
    assert loaded["pools"] == [[0.0, 5.0], [10.0, 15.0]]
    assert loaded["label"] == "my marker"
    # _key field is stamped on save
    assert loaded["_key"] == "v_anim"


def test_save_marker_stamps_key_from_save_key(db):
    # main's _write_entry always overwrites _key with the save key -- a
    # caller-supplied _key is not preserved.
    entry = {"_key": "custom_key", "pools": []}
    db.save_marker("v_anim", entry)
    loaded = db.load_markers()
    assert "v_anim" in loaded
    assert loaded["v_anim"]["_key"] == "v_anim"
    assert "custom_key" not in loaded


def test_delete_marker_removes_file(db):
    db.save_marker("v_anim", {"pools": []})
    db.delete_marker("v_anim")
    assert db.load_markers() == {}


def test_load_markers_empty_when_dir_missing(tmp_path):
    database = _make_db(str(tmp_path))
    # Never opened -- the marker dir doesn't exist; load must not raise.
    assert database.load_markers() == {}


def test_load_markers_skips_corrupt_json(db):
    db.save_marker("v_good", {"pools": []})
    # Corrupt file on disk
    corrupt_path = os.path.join(db.paths.marker_dir, "v_bad.json")
    with open(corrupt_path, "w") as f:
        f.write("{not valid json")

    markers = db.load_markers()
    assert "v_good" in markers
    assert "v_bad" not in markers


def test_load_markers_keys_off_stored_key_field(db):
    db.save_marker("d_file__dlg text", {"pools": []})
    markers = db.load_markers()
    # The stored _key is authoritative, not the filename hash.
    assert "d_file__dlg text" in markers


# ---------------------------------------------------------------------------
# Preset round-trips
# ---------------------------------------------------------------------------

def test_save_and_load_presets_round_trip(db):
    db.save_preset("audio", "My Preset", {"files": ["a.ogg", "b.ogg"]})
    db.save_preset("video", "Vid Preset", {"speed": 1.5})

    audio, video = db.load_presets()
    assert "My Preset" in audio
    assert audio["My Preset"]["files"] == ["a.ogg", "b.ogg"]
    assert audio["My Preset"]["_key"] == "My Preset"
    assert "Vid Preset" in video
    assert video["Vid Preset"]["speed"] == 1.5


def test_delete_preset_removes_file(db):
    db.save_preset("audio", "My Preset", {"files": []})
    db.delete_preset("audio", "My Preset")
    audio, _video = db.load_presets()
    assert audio == {}


def test_preset_name_with_path_separators_is_sanitized(db):
    db.save_preset("audio", "evil/name", {"files": []})
    audio, _video = db.load_presets()
    # The stored _key still resolves the original name.
    assert "evil/name" in audio
    # But no subdirectory was created from the name.
    evil_dir = os.path.join(db.paths.audio_preset_dir, "evil")
    assert not os.path.isdir(evil_dir)


# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

def test_load_shared_config_missing_file_returns_empty(db):
    assert db.load_shared_config() == {}


def test_save_and_load_shared_config_round_trip(db):
    db.save_shared_config({"disabled_files": ["a.ogg"], "keybinds": {}})
    assert db.load_shared_config() == {"disabled_files": ["a.ogg"], "keybinds": {}}


def test_update_shared_config_merges(db):
    db.save_shared_config({"disabled_files": ["a.ogg"]})
    db.update_shared_config({"keybinds": {"cue_undo": ["K_q"]}})
    config = db.load_shared_config()
    assert config["disabled_files"] == ["a.ogg"]
    assert config["keybinds"] == {"cue_undo": ["K_q"]}


# ---------------------------------------------------------------------------
# Low-level file helpers
# ---------------------------------------------------------------------------

def test_write_entry_does_not_mutate_caller_dict(db):
    entry = {"pools": [[1.0, 2.0]]}
    db.save_marker("v_key", entry)
    # The caller's dict must not gain the _key stamp.
    assert "_key" not in entry
