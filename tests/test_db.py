# -*- coding: utf-8 -*-
# Tests for cue_lib.db -- file-backed persistence for markers and presets.
# Pure stdlib module (after the _cue_log extraction), so no Ren'Py mocks
# are needed beyond what conftest provides for the package import.

import hashlib
import os

import pytest

from cue_lib.db import (
    CUE_DEFAULT_MUSIC_TRIGGERS_FILENAME,
    CUE_HASH_TRUNC_LEN,
    CueDatabase,
    _atomic_json_write,
    _key_to_filename,
)
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
    assert os.path.isdir(os.path.join(str(tmp_path), "audio"))
    assert database.is_open()


def test_close_marks_closed(db):
    db.close()
    assert not db.is_open()


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


def test_load_shared_config_coerces_to_str(db, monkeypatch):
    """Loaded values must be native `str`, like load_markers does.

    Python 2 (Ren'Py 7.x) json decodes to `unicode`; leaving it uncoerced
    breaks consumers that guard with isinstance(x, str) -- e.g. keybind
    overrides are all rejected as "invalid" and never applied on restart.
    """
    db.save_shared_config({"keybinds": {"cue_toggle_sfx_active": "alt_K_3"}})

    import cue_lib.db as _db_module

    calls = []
    monkeypatch.setattr(
        _db_module, "_to_str", lambda obj: calls.append(obj) or obj
    )
    db.load_shared_config()
    assert calls, "load_shared_config must run loaded values through _to_str"


# ---------------------------------------------------------------------------
# Low-level file helpers
# ---------------------------------------------------------------------------

def test_write_entry_does_not_mutate_caller_dict(db):
    entry = {"pools": [[1.0, 2.0]]}
    db.save_marker("v_key", entry)
    # The caller's dict must not gain the _key stamp.
    assert "_key" not in entry


def test_atomic_write_dump_failure_leaves_no_temp(db):
    fpath = os.path.join(db.paths.marker_dir, "v_fail.json")
    # A non-serializable value makes json.dump raise mid-write.
    with pytest.raises(TypeError):
        _atomic_json_write(fpath, {"pools": [object()]})
    # The destination must be untouched and no partial temp may survive.
    assert not os.path.exists(fpath)
    assert not [n for n in os.listdir(db.paths.marker_dir) if n.endswith(".tmp")]


def test_atomic_write_uses_unique_temp_name_per_call(db, monkeypatch):
    import tempfile
    fpath = os.path.join(db.paths.marker_dir, "v_u.json")
    names = []
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(**kwargs):
        fd, name = real_mkstemp(**kwargs)
        names.append(name)
        return fd, name

    monkeypatch.setattr("cue_lib.db._tempfile.mkstemp", fake_mkstemp)
    _atomic_json_write(fpath, {"pools": []})
    _atomic_json_write(fpath, {"pools": [1]})
    # Each write must get its own temp, not a shared fixed .tmp name.
    assert len(names) == 2
    assert len(set(names)) == 2
    assert all(n.endswith(".tmp") for n in names)


def test_atomic_write_two_writes_same_path_last_wins(db):
    import json
    fpath = os.path.join(db.paths.marker_dir, "v_seq.json")
    _atomic_json_write(fpath, {"seq": 1})
    _atomic_json_write(fpath, {"seq": 2})
    with open(fpath, "r") as f:
        assert json.load(f) == {"seq": 2}


# ---------------------------------------------------------------------------
# Default music triggers -- live in the marker dir root, never read as markers
# ---------------------------------------------------------------------------

def test_load_markers_ignores_default_music_triggers(db):
    db.save_default_music_triggers(
        {"r1": [{"key_before": "v_a", "filepath": "music/x.ogg"}]})
    fpath = os.path.join(db.paths.marker_dir, CUE_DEFAULT_MUSIC_TRIGGERS_FILENAME)
    assert os.path.isfile(fpath)
    assert db.load_markers() == {}


def test_load_markers_ignores_non_marker_json(db):
    # A stray .json with no key type prefix is not a marker.
    stray = os.path.join(db.paths.marker_dir, "notes.json")
    with open(stray, "w") as _f:
        _f.write("{}")
    assert db.load_markers() == {}


def test_default_music_triggers_round_trip(db):
    db.update_default_music_triggers("r1", "v_a", "music/x.ogg")
    assert db.load_default_music_triggers() == {
        "r1": [{"key_before": "v_a", "filepath": "music/x.ogg"}]}
    # Stored at the marker dir root, not in a music/ subdir.
    fpath = os.path.join(db.paths.marker_dir, CUE_DEFAULT_MUSIC_TRIGGERS_FILENAME)
    assert os.path.isfile(fpath)
    assert not os.path.isdir(os.path.join(db.paths.marker_dir, "music"))


def test_update_default_music_triggers_updates_in_place(db):
    db.update_default_music_triggers("r1", "v_a", "music/x.ogg")
    db.update_default_music_triggers("r1", "v_a", "music/y.ogg")
    db.update_default_music_triggers("r1", "v_b", "music/z.ogg")
    assert db.load_default_music_triggers() == {
        "r1": [
            {"key_before": "v_a", "filepath": "music/y.ogg"},
            {"key_before": "v_b", "filepath": "music/z.ogg"},
        ]}


def test_update_default_music_triggers_sets_key_after_in_place(db):
    db.update_default_music_triggers("r1", "v_a", "music/x.ogg")
    db.update_default_music_triggers("r1", "v_a", "music/y.ogg", key_after="v_settled")
    assert db.load_default_music_triggers() == {
        "r1": [
            {"key_before": "v_a", "filepath": "music/y.ogg", "key_after": "v_settled"}]}


# ---------------------------------------------------------------------------
# Error paths -- missing dirs, corrupt files, unwritable stores
# ---------------------------------------------------------------------------

def test_open_propagates_makedirs_error(tmp_path, monkeypatch):
    database = _make_db(str(tmp_path))

    def _boom(path):
        raise OSError("no perms")
    monkeypatch.setattr(os, "makedirs", _boom)

    with pytest.raises(OSError):
        database.open()


def test_load_presets_empty_when_dir_missing(tmp_path):
    # Never opened -- neither preset dir exists; load must not raise.
    database = _make_db(str(tmp_path))
    assert database.load_presets() == ({}, {})


def test_load_presets_skips_non_json(tmp_path):
    database = _make_db(str(tmp_path))
    database.open()
    stray = os.path.join(database.paths.audio_preset_dir, "notes.txt")
    with open(stray, "w") as f:
        f.write("x")

    audio, video = database.load_presets()
    assert audio == {}


def test_load_presets_skips_corrupt_json(tmp_path):
    database = _make_db(str(tmp_path))
    database.open()
    bad = os.path.join(database.paths.audio_preset_dir, "audio_bad.json")
    with open(bad, "w") as f:
        f.write("{not json")

    audio, video = database.load_presets()
    assert audio == {}


def test_delete_preset_missing_file_does_not_raise(tmp_path):
    database = _make_db(str(tmp_path))
    database.open()
    database.delete_preset("audio", "ghost")  # must not raise


def test_preset_file_matches_missing_is_false(db):
    assert not db.preset_file_matches("audio", "ghost", {"files": []})


def test_load_shared_config_corrupt_returns_empty(db):
    with open(db.paths.shared_config_path, "w") as f:
        f.write("{not json")
    assert db.load_shared_config() == {}


def test_save_shared_config_creates_parent_dir(tmp_path):
    database = _make_db(str(tmp_path))
    database.save_shared_config({"flag": True})
    assert database.load_shared_config() == {"flag": True}


def test_save_shared_config_logs_write_error(db, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("cue_lib.db._atomic_json_write", _boom)

    db.save_shared_config({"flag": True})  # must not raise


def test_load_default_music_triggers_corrupt_returns_empty(db):
    fpath = os.path.join(db.paths.marker_dir, CUE_DEFAULT_MUSIC_TRIGGERS_FILENAME)
    with open(fpath, "w") as f:
        f.write("{not json")
    assert db.load_default_music_triggers() == {}


def test_save_default_music_triggers_creates_parent(tmp_path):
    database = _make_db(str(tmp_path))
    database.save_default_music_triggers({"r1": []})
    assert database.load_default_music_triggers() == {"r1": []}


def test_save_default_music_triggers_logs_write_error(db, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("cue_lib.db._atomic_json_write", _boom)

    db.save_default_music_triggers({"r1": []})  # must not raise
