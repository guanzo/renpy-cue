# -*- coding: utf-8 -*-
# Tests for cue_lib.markers persistence glue: restore_from_file / _apply_restore,
# _cue_load_scalars_from_persistent, _cue_paste_context, and the paste_context
# replay / no-duration branches.
#
# These touch the module-level _cue singleton and renpy persistent, so every
# test monkeypatches cue_lib.markers._cue to a fake and resets the mock
# persistent -- nothing here mutates real Ren'Py state.  The _apply_restore
# happy path drives a real backup zip (zip_shared_tree) through the real store
# graph on cue_env, asserting the store reloads from the restored files.

import os
import types
import zipfile

import pytest

import renpy.store as _store

import cue_lib.markers as _markers
from cue_lib.backup import (
    CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME, zip_shared_tree,
)
from cue_lib.marker_store import CueMarkerStore
from cue_lib.markers import CueMarkerManager
from cue_lib.state import CueContext

from tests.fakes import (
    FakeDb, FakeSfxManager, FakeTrigger, FakeUndo, FakeVideoEditor, FakeVidManager,
)

GAME_ID = "test_game"


def _make_fake_cue():
    """Module-singleton stand-in carrying every attribute the persistence
    glue dereferences: undo (reset), music, db (shared config), and the
    scalar-fan-out siblings."""
    return types.SimpleNamespace(
        undo=FakeUndo(),
        music=None,
        db=FakeDb(),
        sfx_manager=FakeSfxManager(),
        trigger=FakeTrigger(),
        video_editor=FakeVideoEditor(),
        speed_resolver=types.SimpleNamespace(seamless_transition=False),
    )


@pytest.fixture
def mgr(cue_env):
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    ctx = CueContext()
    vid = FakeVidManager(duration=10.0)
    sfx = FakeSfxManager()
    editor = FakeVideoEditor()
    return CueMarkerManager(ctx, store, vid, sfx, FakeTrigger(), editor, None)


@pytest.fixture(autouse=True)
def _fake_singletons(monkeypatch):
    """Fresh persistent + fake _cue per test."""
    _store.persistent._cue = None
    _store._in_replay = False
    fake = _make_fake_cue()
    monkeypatch.setattr(_markers, "_cue", fake)
    monkeypatch.setattr(_markers, "persistent", _store.persistent)
    return fake


def _seed_marker_file(cue_env, name, content):
    path = os.path.join(cue_env.paths.root, "data", "markers", GAME_ID, name)
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as f:
        f.write(content)
    return path


# ==========================================================================
# _apply_restore -- happy path through a real backup zip
# ==========================================================================

def test_apply_restore_reloads_store_from_zip(cue_env, mgr):
    # _key is authoritative (the DB writes it into every marker file; the
    # filename heuristic is only a fallback).
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')

    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    zip_shared_tree(cue_env.paths.root, zip_path)

    mgr._apply_restore(zip_path)

    # Store reloaded from the restored marker file.
    assert mgr._store._data["v_scene.ogv"]["pools"][0]["files"] == ["a.ogg"]
    # Post-restore side effects all fired.
    assert mgr._sfx_manager.scan_calls == 1
    assert mgr._video_editor.refresh_calls == 1
    assert _markers._cue.undo.reset_calls == 1
    assert mgr._session_created == set()


# ==========================================================================
# _apply_restore -- guard / branch coverage
# ==========================================================================

def test_apply_restore_db_closed_noop(cue_env, mgr):
    cue_env.db.close()
    mgr._apply_restore("whatever.zip")  # must not raise


def test_apply_restore_wait_timeout_noop(cue_env, mgr, monkeypatch):
    monkeypatch.setattr(cue_env.db._backup, "wait_until_idle", lambda: False)
    mgr._apply_restore("whatever.zip")  # must not raise


def test_apply_restore_scans_restored_music(cue_env, mgr):
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')
    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    zip_shared_tree(cue_env.paths.root, zip_path)

    scanned = []
    _markers._cue.music = types.SimpleNamespace(user_music=types.SimpleNamespace(
        scan=lambda: scanned.append(1)))
    mgr._apply_restore(zip_path)
    assert scanned == [1]


def test_apply_restore_error_handled(cue_env, mgr, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_markers, "restore_pieces", _boom)
    mgr._apply_restore("whatever.zip")  # must not raise


# ==========================================================================
# restore_from_file
# ==========================================================================

class _FakeConfirmDialog(object):
    def __init__(self):
        self.show_calls = []

    def show(self, message, action):
        self.show_calls.append((message, action))


def test_restore_from_file_db_closed_noop(cue_env, mgr):
    cue_env.db.close()
    mgr.restore_from_file()  # must not raise


def test_restore_from_file_no_zip_noop(cue_env, mgr):
    mgr.restore_from_file()  # no backup.zip on disk -> must not raise


def test_restore_from_file_invalid_zip_noop(cue_env, mgr):
    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with open(zip_path, "w") as f:
        f.write("not a zip")
    mgr.restore_from_file()  # must not raise


def test_restore_from_file_valid_zip_confirms(cue_env, mgr):
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')
    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    zip_shared_tree(cue_env.paths.root, zip_path)

    confirm = _FakeConfirmDialog()
    mgr._confirm_dialog = confirm
    mgr.restore_from_file()
    assert len(confirm.show_calls) == 1
    assert "Restore from backups/backup.zip?" in confirm.show_calls[0][0]


# ==========================================================================
# _cue_load_scalars_from_persistent
# ==========================================================================

def test_load_scalars_migrates_defaults_to_shared_config():
    _markers._cue_load_scalars_from_persistent()
    cue = _markers._cue
    # disabled_files migrated to shared config; scalars landed on managers.
    assert cue.db.shared["disabled_files"] == []
    assert cue.sfx_manager.disabled_files == set()
    assert cue.trigger.active is True
    assert cue.video_editor.encode_mode == 0  # MODE_INTERPOLATE
    assert cue.video_editor.remove_audio is True
    assert cue.speed_resolver.seamless_transition is False
    # persistent now carries the scalar dict.
    assert _store.persistent._cue["triggers_active"] is True


def test_load_scalars_shared_config_wins():
    cue = _markers._cue
    cue.db.shared["disabled_files"] = ["a.ogg"]
    _store.persistent._cue = {
        "disabled_files": {"b.ogg"},
        "triggers_active": False,
        "encode_mode": 1,
        "remove_audio": False,
        "seamless_transition": True,
    }
    _markers._cue_load_scalars_from_persistent()
    assert cue.sfx_manager.disabled_files == {"a.ogg"}  # shared wins
    assert "disabled_files" not in _store.persistent._cue
    assert cue.trigger.active is False
    assert cue.video_editor.encode_mode == 1
    assert cue.video_editor.remove_audio is False
    assert cue.speed_resolver.seamless_transition is True


# ==========================================================================
# paste_context -- replay + no-duration branches
# ==========================================================================

def test_paste_context_records_replay(mgr):
    _store._in_replay = "replay-name"
    mgr._ctx.current_file = "scene.ogv"
    mgr["v_scene.ogv"] = {"pools": [{"time": 1.0, "files": []}]}
    mgr.copy_context()
    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    assert mgr["v_new.ogv"]["replay"] == "replay-name"


def test_paste_context_no_duration_floors_negative_time(mgr):
    mgr._vid_manager.duration = 0
    mgr._ctx.current_file = "scene.ogv"
    mgr["v_scene.ogv"] = {"pools": [{"time": -5.0, "files": []}]}
    mgr.copy_context()
    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    assert mgr["v_new.ogv"]["pools"][0]["time"] == 0.0
