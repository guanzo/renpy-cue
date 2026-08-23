# -*- coding: utf-8 -*-
# Tests for cue_lib.markers persistence glue: _cue_load_scalars_from_persistent,
# _cue_paste_context, and the paste_context replay / no-duration branches.
#
# The restore flow now lives in cue_lib.backup.CueManualBackupManager: the
# background disk merge (_restore_worker) and the main-thread reload poll
# (_finish_reload) drive the marker manager's injected _reload_after_restore
# callback.  These tests wire that callback and drive the manual manager
# directly.
#
# These touch the module-level _cue singleton and renpy persistent, so every
# test monkeypatches cue_lib.markers._cue to a fake and resets the mock
# persistent -- nothing here mutates real Ren'Py state.  The _reload_after_restore
# happy path drives a real backup zip (zip_shared_tree) through the real store
# graph on cue_env, asserting the store reloads from the restored files.

import os
import types
import zipfile

import pytest

import renpy.store as _store

import cue_lib.backup as _backup
import cue_lib.markers as _markers
import cue_lib.runtime as _runtime
from cue_lib.backup import zip_shared_tree
from cue_lib.constants import CUE_MANUAL_BACKUP_NAME
from cue_lib.paths import CUE_BACKUP_DIR
from cue_lib.marker_store import CueMarkerStore
from cue_lib.markers import CueMarkerManager
from cue_lib.state import CueContext

from tests.fakes import (
    FakeDb, FakeSfxManager, FakeTrigger, FakeUndo, FakeVideoEditor, FakeVidManager,
)

GAME_ID = "test_game"


class FakeMusicRestore(object):
    """Music-manager stand-in for _cue_full_reload's re-scan + re-merge.
    The real manager is always wired by the time a restore runs (overlay button
    after init), so user_music/library/game_music/_recent must exist here too."""

    def __init__(self):
        self.user_music = types.SimpleNamespace(scan_calls=0)
        self.library = types.SimpleNamespace(maybe_rebuild_calls=0)
        self.game_music = types.SimpleNamespace(scan_calls=0)
        self.reload_presets_calls = 0
        self._recent = types.SimpleNamespace(load_calls=0)

        def _scan():
            self.user_music.scan_calls += 1
        self.user_music.scan = _scan

        def _game_music_scan():
            self.game_music.scan_calls += 1
        self.game_music.scan = _game_music_scan

        def _maybe_rebuild():
            self.library.maybe_rebuild_calls += 1
        self.library.maybe_rebuild = _maybe_rebuild

        def _reload_presets():
            self.reload_presets_calls += 1
        self.reload_presets = _reload_presets

        def _recent_load():
            self._recent.load_calls += 1
        self._recent.load = _recent_load


def _make_fake_cue():
    """Module-singleton stand-in carrying every attribute the persistence
    glue dereferences: undo (reset), music, db (shared config), the
    scalar-fan-out siblings, and the markers manager (wired by the `mgr`
    fixture -- full reload routes through _cue.markers)."""
    sfx = FakeSfxManager()
    sfx._recent = types.SimpleNamespace(load_calls=0)

    def _sfx_recent_load():
        sfx._recent.load_calls += 1
    sfx._recent.load = _sfx_recent_load

    return types.SimpleNamespace(
        undo=FakeUndo(),
        music=FakeMusicRestore(),
        db=FakeDb(),
        sfx=sfx,
        trigger=FakeTrigger(),
        video_editor=FakeVideoEditor(),
        speed_resolver=types.SimpleNamespace(seamless_transition=False),
        markers=None,
    )


@pytest.fixture
def mgr(cue_env, _fake_singletons):
    fake = _fake_singletons
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    ctx = CueContext()
    vid = FakeVidManager(duration=10.0)
    # Full reload drives _cue.sfx/_cue.video_editor, so the manager
    # must be built on the same instances the fake singleton exposes -- the
    # assertions read those call counters back through mgr.
    sfx = fake.sfx
    editor = fake.video_editor
    mgr = CueMarkerManager(ctx, store, vid, sfx, FakeTrigger(), editor)
    fake.markers = mgr
    return mgr


@pytest.fixture
def backups(cue_env, mgr):
    """The manual backup manager, wired to the live db and the marker reload
    callback (the same wiring cue_z.rpy init -900 performs)."""
    bm = cue_env.db._backup
    bm.manual.wire(cue_env.db, mgr._reload_after_restore, None)
    return bm.manual


@pytest.fixture(autouse=True)
def _fake_singletons(monkeypatch):
    """Fresh persistent + fake _cue per test."""
    _store.persistent._cue = None
    _store._in_replay = False
    fake = _make_fake_cue()
    monkeypatch.setattr(_markers, "_cue", fake)
    monkeypatch.setattr(_markers, "persistent", _store.persistent)
    monkeypatch.setattr(_runtime, "_cue", fake)  # _cue_full_reload lives in runtime.py
    # Full reload's tail re-derives the current context; that is runtime's
    # concern (exercised in test_runtime.py), so no-op it here to keep the
    # restore tests focused on the reload plumbing.
    monkeypatch.setattr(_runtime, "_cue_refresh_context", lambda: None)
    return fake


def _seed_marker_file(cue_env, name, content):
    path = os.path.join(cue_env.paths.root, "data", "markers", GAME_ID, name)
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as f:
        f.write(content)
    return path


def _backup_zip(cue_env):
    """Write backups/renpy_cue_backup.zip from the current live tree."""
    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    zip_shared_tree(cue_env.paths.root, zip_path)
    return zip_path


# ==========================================================================
# restore -- the disk phase (_restore_worker) + the main-thread reload
# (_finish_reload / poll), split so the merge runs in the background
# ==========================================================================

def test_restore_reloads_store_from_zip(cue_env, mgr, backups, _fake_singletons):
    # _key is authoritative (the DB writes it into every marker file; the
    # filename heuristic is only a fallback).
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')
    zip_path = _backup_zip(cue_env)

    backups._restore_worker(zip_path)
    assert backups._restore_pending is True
    backups._finish_reload()

    # Store reloaded from the restored marker file.
    assert mgr._store._data["v_scene.ogv"]["pools"][0]["files"] == ["a.ogg"]
    # Post-restore side effects all fired.
    assert mgr._sfx_manager.scan_calls == 1
    assert _fake_singletons.music.user_music.scan_calls == 1
    assert _fake_singletons.music.library.maybe_rebuild_calls == 1
    assert mgr._video_editor.refresh_calls == 1
    assert _markers._cue.undo.reset_calls == 1
    assert mgr._session_created == set()
    assert backups.restore_status.startswith("Restored 1 files")


def test_restore_busy_noop(cue_env, backups):
    backups.is_restoring = True
    backups._restore_thread = None
    backups._apply_restore("whatever.zip")
    assert backups._restore_thread is None  # busy guard swallowed the spawn


def test_restore_spawns_background_thread(cue_env, mgr, backups, _fake_singletons):
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": []}')
    zip_path = _backup_zip(cue_env)

    backups._apply_restore(zip_path)
    assert backups.is_restoring is True
    assert backups._restore_thread is not None
    backups._restore_thread.join(timeout=10)

    assert backups.is_restoring is False
    assert backups._restore_pending is True
    backups.poll()
    assert backups._restore_pending is False
    assert mgr._store._data["v_scene.ogv"]["pools"] == []


# ==========================================================================
# restore -- guard / branch coverage
# ==========================================================================

def test_restore_worker_db_closed_noop(cue_env, backups):
    cue_env.db.close()
    backups._restore_worker("whatever.zip")  # must not raise
    assert backups._restore_pending is False


def test_restore_worker_wait_timeout_noop(cue_env, backups, monkeypatch):
    monkeypatch.setattr(cue_env.db._backup.auto, "wait_until_idle", lambda: False)
    backups._restore_worker("whatever.zip")  # must not raise
    assert "auto-backup" in backups.restore_error


def test_restore_scans_restored_music(cue_env, backups, _fake_singletons):
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')
    zip_path = _backup_zip(cue_env)

    scanned = []
    _fake_singletons.music.user_music.scan = lambda: scanned.append(1)
    backups._restore_worker(zip_path)
    backups._finish_reload()
    assert scanned == [1]


def test_restore_worker_error_handled(cue_env, backups, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_backup, "restore_pieces", _boom)
    backups._restore_worker("whatever.zip")  # must not raise
    assert "Restore failed" in backups.restore_error
    assert backups._restore_pending is False


def test_finish_reload_error(cue_env, backups, monkeypatch):
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')
    zip_path = _backup_zip(cue_env)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")
    # full_reload now lives in runtime.py, so its module-global scalars call is
    # runtime's binding, not markers'.
    monkeypatch.setattr(_runtime, "_cue_load_scalars_from_persistent", _boom)

    backups._restore_worker(zip_path)
    backups._finish_reload()
    assert "Restore reload failed" in backups.restore_error
    assert backups._restore_pending is False


# ==========================================================================
# restore -- the Restore button entry point
# ==========================================================================

class _FakeConfirmDialog(object):
    def __init__(self):
        self.show_calls = []

    def show(self, message, action):
        self.show_calls.append((message, action))


def test_restore_db_closed_noop(cue_env, backups):
    cue_env.db.close()
    backups.restore()  # must not raise


def test_restore_no_zip_noop(cue_env, backups):
    backups.restore()  # no renpy_cue_backup.zip on disk -> must not raise


def test_restore_invalid_zip_noop(cue_env, backups):
    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with open(zip_path, "w") as f:
        f.write("not a zip")
    backups.restore()  # must not raise


def test_restore_valid_zip_confirms(cue_env, backups):
    _seed_marker_file(cue_env, "v_scene.ogv.json",
                      '{"_key": "v_scene.ogv", "pools": [{"time": 1.0, "files": ["a.ogg"]}]}')
    zip_path = _backup_zip(cue_env)

    confirm = _FakeConfirmDialog()
    backups._confirm_dialog = confirm
    backups.restore()
    backups._restore_thread.join(timeout=10)
    backups.poll()  # preflight finished -> confirm dialog shown from the timer
    assert len(confirm.show_calls) == 1
    assert "will be overwritten" in confirm.show_calls[0][0]


# ==========================================================================
# _cue_load_scalars_from_persistent
# ==========================================================================

def test_load_scalars_migrates_defaults_to_shared_config():
    _markers._cue_load_scalars_from_persistent()
    cue = _markers._cue
    # disabled_files migrated to shared config; scalars landed on managers.
    assert cue.db.shared["disabled_files"] == []
    assert cue.sfx.disabled_files == set()
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
    assert cue.sfx.disabled_files == {"a.ogg"}  # shared wins
    assert "disabled_files" not in _store.persistent._cue
    assert cue.trigger.active is False
    assert cue.video_editor.encode_mode == 1
    assert cue.video_editor.remove_audio is False
    assert cue.speed_resolver.seamless_transition is True


def test_load_scalars_none_values_fall_back_to_defaults():
    # A persistent._cue whose keys hold None (a partially-nulled dict) must
    # not flip these settings falsy -- remove_audio=None would otherwise
    # keep audio on every encode while the UI shows the toggle on.
    _store.persistent._cue = {
        "triggers_active": None,
        "encode_mode": None,
        "remove_audio": None,
        "seamless_transition": None,
    }
    _markers._cue_load_scalars_from_persistent()
    cue = _markers._cue
    assert cue.trigger.active is True
    assert cue.video_editor.encode_mode == 0
    assert cue.video_editor.remove_audio is True
    assert cue.speed_resolver.seamless_transition is False


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
