# -*- coding: utf-8 -*-
# Tests for cue_lib.backup -- zip_shared_tree, validate_backup_zip,
# restore_pieces, and the CueBackupManager composite (auto throttle/prune +
# manual backup/restore orchestration).
#
# restore_pieces must MERGE the backup over the live tree, never removing
# data the backup does not carry (markers made after the backup survive,
# shared presets/config and other games' markers are untouched), and must
# cover the shared audio/ and music/ folders as well as data/.

import errno
import os
import shutil
import zipfile

import pytest

import cue_lib.backup as _backup
from cue_lib.backup import (
    CUE_BACKUP_MAX,
    CUE_BACKUP_PREFIX,
    CUE_BAK_DIR,
    CUE_RESTORE_TMP_DIR,
    CueBackupManager,
    _backup_ts_from_name,
    restore_pieces,
    validate_backup_zip,
    zip_shared_tree,
    zip_tree,
)
from cue_lib.constants import (
    CUE_BACKUP_AUTO_DIR,
    CUE_BACKUP_DIR,
    CUE_MANUAL_BACKUP_NAME,
    CUE_SHARED_CONFIG_FILENAME,
)
from cue_lib.db import CueDatabase
from cue_lib.paths import CuePaths

GAME_ID = "test_game"


@pytest.fixture
def shared(tmp_path):
    """A shared root with data/markers/<gid>, presets, config, audio, music."""
    root = str(tmp_path / "shared")
    marker_dir = os.path.join(root, "data", "markers", GAME_ID)
    presets_dir = os.path.join(root, "data", "presets")
    for d in (marker_dir, presets_dir):
        os.makedirs(d)
    _write(root, os.path.join("data", CUE_SHARED_CONFIG_FILENAME), '{"flag": true}')
    return root


@pytest.fixture
def manual(cue_env):
    """The manual backup manager, wired to the live db with a no-op reload."""
    bm = cue_env.db._backup
    bm.manual.wire(cue_env.db, lambda count: None, None)
    return bm.manual


def _write(root, rel, content):
    """Write a file under root (rel uses '/'), creating parents."""
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _exists(root, rel):
    return os.path.isfile(os.path.join(root, *rel.split("/")))


def _read(root, rel):
    with open(os.path.join(root, *rel.split("/"))) as f:
        return f.read()


def _marker(shared, name):
    return _write(shared, os.path.join("data", "markers", GAME_ID, name),
                  '{"pools": []}')


# ---------------------------------------------------------------------------
# zip_shared_tree
# ---------------------------------------------------------------------------

def test_zip_shared_tree_arcnames(shared, tmp_path):
    _marker(shared, "v_a.json")
    _write(shared, os.path.join("data", "presets", "p.json"), '{"files": []}')
    _write(shared, "audio/loop/hit.ogg", "AUDIO")
    _write(shared, "music/ost/song.ogg", "MUSIC")
    _write(shared, "video/{}/speed.ogv".format(GAME_ID), "VIDEO")

    zip_path = str(tmp_path / "backup.zip")
    count = zip_shared_tree(shared, zip_path)

    assert count == 6
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    # data/ stays flat for backward compatibility; media under their own dirs.
    assert "markers/{}/v_a.json".format(GAME_ID) in names
    assert "presets/p.json" in names
    assert CUE_SHARED_CONFIG_FILENAME in names
    assert "audio/loop/hit.ogg" in names
    assert "music/ost/song.ogg" in names
    assert "video/{}/speed.ogv".format(GAME_ID) in names


def test_zip_shared_tree_reports_progress(shared, tmp_path):
    _write(shared, "audio/a.ogg", "AUDIO")
    _write(shared, "audio/b.ogg", "BBBB")
    _write(shared, os.path.join("data", "presets", "p.json"), '{"files": []}')
    _write(shared, "music/c.ogg", "CCCCCC")

    zip_path = str(tmp_path / "backup.zip")
    seen = []

    def _collect(written, total):
        seen.append((written / float(total)) if total else 1.0)

    zip_shared_tree(shared, zip_path, progress=_collect)

    assert seen  # at least one tick
    assert all(0.0 < f <= 1.0 for f in seen)
    assert seen == sorted(seen)  # nondecreasing
    assert seen[-1] == 1.0


def test_validate_backup_zip_accepts_media_only(shared, tmp_path):
    _write(shared, "audio/hit.ogg", "AUDIO")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    ok, _reason = validate_backup_zip(zip_path)
    assert ok


def test_validate_backup_zip_accepts_video_only(shared, tmp_path):
    _write(shared, "video/{}/speed.ogv".format(GAME_ID), "VIDEO")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    ok, _reason = validate_backup_zip(zip_path)
    assert ok


def test_restore_video_scoped_to_this_game(shared, tmp_path):
    # Video is namespaced per game: the backup carries the whole video/ tree,
    # restore touches only this game's video/{game_id}/ subdir.
    other = "other_game"
    _write(shared, "video/{}/speed.ogv".format(GAME_ID), "MINE")
    _write(shared, "video/{}/theirs.ogv".format(other), "THEIRS")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    # This game's video edited after the backup: restore brings the backup
    # copy.  Other game's video (even one added after the backup) is untouched.
    _write(shared, "video/{}/speed.ogv".format(GAME_ID), "EDITED")
    _write(shared, "video/{}/new_theirs.ogv".format(other), "NEW")

    restore_pieces(zip_path, shared, GAME_ID)

    assert _read(shared, "video/{}/speed.ogv".format(GAME_ID)) == "MINE"
    assert _read(shared, "video/{}/theirs.ogv".format(other)) == "THEIRS"
    assert _read(shared, "video/{}/new_theirs.ogv".format(other)) == "NEW"


def test_validate_backup_zip_ignores_nonjson_media_file(shared, tmp_path):
    # A stray non-JSON .json dropped into audio/ is not marker data -- it
    # must not invalidate the backup or block the restore.
    _marker(shared, "v_a.json")
    _write(shared, "audio/notes.json", "definitely not json")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    ok, reason = validate_backup_zip(zip_path)
    assert ok, reason

    restore_pieces(zip_path, shared, GAME_ID)
    assert _read(shared, "audio/notes.json") == "definitely not json"


# ---------------------------------------------------------------------------
# restore_pieces -- merge semantics
# ---------------------------------------------------------------------------

def test_restore_keeps_files_made_after_backup(shared, tmp_path):
    _marker(shared, "v_old.json")
    _write(shared, "audio/hit.ogg", "OLD")
    _write(shared, "music/song.ogg", "OLD")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    # Made after the backup: must survive the restore untouched.
    _marker(shared, "v_scene_a.json")
    _write(shared, "audio/new.ogg", "NEW")
    _write(shared, "music/new2.ogg", "NEW2")
    # Backed-up file edited after the backup: restore brings the backup copy.
    _write(shared, "audio/hit.ogg", "EDITED")

    restore_pieces(zip_path, shared, GAME_ID)

    assert _exists(shared, os.path.join("data", "markers", GAME_ID, "v_scene_a.json"))
    assert _exists(shared, "audio/new.ogg")
    assert _exists(shared, "music/new2.ogg")
    assert _read(shared, "audio/hit.ogg") == "OLD"
    assert _read(shared, "music/song.ogg") == "OLD"
    # Staging dir is cleaned up.
    assert not os.path.exists(os.path.join(shared, CUE_RESTORE_TMP_DIR))


def test_restore_revives_file_deleted_after_backup(shared, tmp_path):
    _marker(shared, "v_a.json")
    _write(shared, "audio/hit.ogg", "A")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    os.remove(os.path.join(shared, "data", "markers", GAME_ID, "v_a.json"))
    os.remove(os.path.join(shared, "audio", "hit.ogg"))

    restore_pieces(zip_path, shared, GAME_ID)

    assert _exists(shared, os.path.join("data", "markers", GAME_ID, "v_a.json"))
    assert _exists(shared, "audio/hit.ogg")


def test_partial_zip_leaves_other_pieces_untouched(shared, tmp_path):
    _marker(shared, "v_a.json")
    _write(shared, os.path.join("data", "presets", "p.json"), '{"files": []}')
    _write(shared, "audio/hit.ogg", "A")
    _write(shared, "music/song.ogg", "M")

    # A markers-only zip (still valid).
    zip_path = str(tmp_path / "backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(os.path.join(shared, "data", "markers", GAME_ID, "v_a.json"),
                 "markers/{}/v_a.json".format(GAME_ID))

    ok, _reason = validate_backup_zip(zip_path)
    assert ok
    restore_pieces(zip_path, shared, GAME_ID)

    # Shared pieces the zip lacks survive -- no eviction.
    assert _read(shared, os.path.join("data", "presets", "p.json")) == '{"files": []}'
    assert _read(shared, os.path.join("data", CUE_SHARED_CONFIG_FILENAME)) == '{"flag": true}'
    assert _read(shared, "audio/hit.ogg") == "A"
    assert _read(shared, "music/song.ogg") == "M"


def test_other_games_markers_untouched(shared, tmp_path):
    _marker(shared, "v_a.json")
    _write(shared, os.path.join("data", "markers", "other_game", "v_b.json"),
           '{"pools": []}')
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    restore_pieces(zip_path, shared, GAME_ID)

    assert _exists(shared, os.path.join("data", "markers", "other_game", "v_b.json"))


def test_data_bak_holds_only_overwritten(shared, tmp_path):
    _marker(shared, "v_a.json")
    _write(shared, "audio/hit.ogg", "A")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    _write(shared, "audio/hit.ogg", "EDITED")
    _write(shared, "audio/after.ogg", "AFTER")  # not in the backup

    restore_pieces(zip_path, shared, GAME_ID)

    bak = os.path.join(shared, CUE_BAK_DIR)
    # The overwritten file is preserved; the one made after the backup was
    # never moved aside, so it is not in data_bak.
    assert _read(bak, "audio/hit.ogg") == "EDITED"
    assert not os.path.exists(os.path.join(bak, "audio", "after.ogg"))
    # Live copy now holds the restored version.
    assert _read(shared, "audio/hit.ogg") == "A"


def test_restore_media_only_zip_creates_data_dir(tmp_path):
    # A media-only backup (no data/ at all) still restores, merging media to
    # the shared root and creating data/ for the other pieces.
    root = str(tmp_path / "shared")
    _write(root, "audio/hit.ogg", "A")
    _write(root, "music/song.ogg", "M")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(root, zip_path)

    restore_pieces(zip_path, root, GAME_ID)

    assert _read(root, "audio/hit.ogg") == "A"
    assert _read(root, "music/song.ogg") == "M"
    assert os.path.isdir(os.path.join(root, "data"))


def test_restore_returns_extracted_count(shared, tmp_path):
    # The fixture also writes data/cue_config.json, so the backup carries
    # 4 entries (marker + media pair + config).
    _marker(shared, "v_a.json")
    _write(shared, "audio/hit.ogg", "A")
    _write(shared, "music/song.ogg", "M")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    count = restore_pieces(zip_path, shared, GAME_ID)
    assert count == 4


# ---------------------------------------------------------------------------
# Manual backup -- the Back Up button (zip to backups/renpy_cue_backup.zip)
# ---------------------------------------------------------------------------

def test_manual_zip_includes_media(manual, cue_env):
    # The manual backup zips audio/, music/, and video/ alongside the
    # internal data/ tree.
    _write(cue_env.paths.root, "audio/hit.ogg", "A")
    _write(cue_env.paths.root, "music/song.ogg", "M")
    _write(cue_env.paths.root, "video/test_game/speed.ogv", "V")
    _write(cue_env.paths.root,
           os.path.join("data", "markers", "test_game", "v_a.json"),
           '{"pools": []}')

    manual._zip_to_file()

    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    with zipfile.ZipFile(zip_path) as zf:
        entries = zf.namelist()
    assert any(n.startswith("markers/") for n in entries)
    assert "audio/hit.ogg" in entries
    assert "music/song.ogg" in entries
    assert "video/test_game/speed.ogv" in entries


def test_manual_zip_eexist_race_benign(manual, cue_env, monkeypatch):
    # The auto-backup thread can create {root}/backups/ between _zip_to_file's
    # isdir check and its own makedirs. EEXIST is benign -- the backup proceeds.
    _write(cue_env.paths.root,
           os.path.join("data", "markers", "test_game", "v_a.json"),
           '{"pools": []}')

    backups_dir = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR)
    real_makedirs = os.makedirs

    def _racing_makedirs(path):
        real_makedirs(path)
        if path == backups_dir:
            raise OSError(errno.EEXIST, "exists")

    monkeypatch.setattr(os, "makedirs", _racing_makedirs)

    manual._zip_to_file()  # must not raise

    zip_path = os.path.join(backups_dir, CUE_MANUAL_BACKUP_NAME)
    assert os.path.exists(zip_path)


def test_manual_zip_no_db_returns(cue_env):
    # Not wired -> no db -> no-op (the entry point guards on db open).
    assert cue_env.db._backup.manual._zip_to_file() == 0


def test_manual_zip_no_data_dir_logs(manual, cue_env):
    shutil.rmtree(os.path.join(cue_env.paths.root, "data"))
    assert manual._zip_to_file() == 0


def test_manual_backup_reports_fraction(manual, cue_env):
    _write(cue_env.paths.root,
           os.path.join("data", "markers", "test_game", "v_a.json"),
           '{"pools": []}')
    _write(cue_env.paths.root, "audio/hit.ogg", "A")
    _write(cue_env.paths.root, "music/song.ogg", "M")
    _write(cue_env.paths.root, "video/test_game/speed.ogv", "V")

    manual._zip_to_file()
    assert manual.backup_fraction == 1.0


def test_manual_backup_resets_fraction(manual, monkeypatch):
    monkeypatch.setattr(manual, "_zip_to_file", lambda: 0)
    manual.backup_fraction = 0.5
    manual.backup()
    assert manual.backup_fraction == 0.0
    manual._backup_thread.join(timeout=10)


def test_manual_zip_makedirs_error_raises(manual, cue_env, monkeypatch):
    def _boom(path):
        raise OSError(errno.EACCES, "denied")
    monkeypatch.setattr(os, "makedirs", _boom)

    # EACCES is a real failure (EEXIST is the benign race); _zip_to_file
    # raises so the worker can surface it as backup_error status.
    with pytest.raises(OSError):
        manual._zip_to_file()


def test_manual_backup_spawns_worker(manual):
    manual.backup()
    assert manual.is_backing_up is True
    assert manual._backup_thread is not None
    manual._backup_thread.join(timeout=10)
    assert manual.is_backing_up is False
    assert manual.backup_status.startswith("Backed up 0 files")


def test_manual_backup_busy_noop(manual):
    manual.is_backing_up = True
    manual._backup_thread = None
    manual.backup()
    assert manual._backup_thread is None  # busy guard swallowed the spawn


def test_manual_backup_worker_error_sets_error(manual, monkeypatch):
    def _boom():
        raise OSError("denied")
    monkeypatch.setattr(manual, "_zip_to_file", _boom)

    manual._backup_worker()
    assert "Backup failed" in manual.backup_error
    assert manual.is_backing_up is False


# ---------------------------------------------------------------------------
# restore -- early-exit error surfacing (no file / invalid zip)
# ---------------------------------------------------------------------------

def test_restore_no_file_sets_error(manual, cue_env):
    # A missing backup zip must surface as restore_error, not a silent no-op.
    manual.restore()
    assert manual.restore_error == "No backup to restore -- run Back Up first."


def test_restore_invalid_zip_sets_error(manual, cue_env):
    # A garbage file at the backup path is invalid, and surfaces as an error.
    # Validation now runs on the preflight worker thread, so join it.
    backups_dir = os.path.dirname(cue_env.paths.manual_backup_path)
    if not os.path.isdir(backups_dir):
        os.makedirs(backups_dir)
    with open(cue_env.paths.manual_backup_path, "w") as f:
        f.write("not a zip")
    manual.restore()
    manual._restore_thread.join(timeout=10)
    assert "Backup is invalid" in manual.restore_error


def test_restore_no_file_clears_stale_status(manual, cue_env):
    # A previous success message must not linger once the zip is gone.
    manual.restore_status = "Restored 3 files ..."
    manual.restore()
    assert manual.restore_status == ""
    assert manual.restore_error


def test_restore_counts_overwrite_vs_added(tmp_path):
    # restore_counts mirrors restore_pieces' matchers and path bases: entries
    # under audio/music/video land at the shared root, the rest under data/.
    root = str(tmp_path / "shared")
    _write(root, os.path.join("data", "markers", GAME_ID, "v_a.json"), '{"pools": []}')
    _write(root, os.path.join("data", "markers", GAME_ID, "v_b.json"), '{"pools": []}')
    _write(root, "audio/hit.ogg", "A")
    _write(root, "music/song.ogg", "M")
    _write(root, os.path.join("data", CUE_SHARED_CONFIG_FILENAME), '{"flag": true}')
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(root, zip_path)

    # These two were in the backup but are gone from the live tree -> "added".
    os.remove(os.path.join(root, "data", "markers", GAME_ID, "v_b.json"))
    os.remove(os.path.join(root, "music", "song.ogg"))

    overwritten, added = _backup.restore_counts(zip_path, root, GAME_ID)
    assert overwritten == 3  # v_a.json + hit.ogg + cue_config.json
    assert added == 2        # v_b.json + song.ogg


def test_restore_counts_ignores_non_matching_entries(tmp_path):
    # Other games' markers/video and anything not a restore matcher are never
    # counted -- the backup may carry a whole tree only partially restored.
    root = str(tmp_path / "shared")
    _write(root, os.path.join("data", "markers", GAME_ID, "v_a.json"), '{"pools": []}')
    _write(root, os.path.join("data", "markers", "other", "v_x.json"), '{"pools": []}')
    _write(root, "video/{}/a.ogv".format(GAME_ID), "V")
    _write(root, "video/other/b.ogv", "V")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(root, zip_path)

    overwritten, added = _backup.restore_counts(zip_path, root, GAME_ID)
    assert (overwritten, added) == (2, 0)


def test_restore_confirm_message_pluralizes():
    msg = _backup.restore_confirm_message(1, 0)
    assert "1 file will be overwritten" in msg
    assert "0 new files will be added" in msg
    assert "saved to data_bak" in msg

    msg = _backup.restore_confirm_message(2, 1)
    assert "2 files will be overwritten" in msg
    assert "1 new file will be added" in msg


class _FakeConfirmDialog(object):
    def __init__(self):
        self.message = None
        self.action = None

    def show(self, message, action):
        self.message = message
        self.action = action


def test_restore_preflight_shows_dialog_with_counts(manual, cue_env, monkeypatch):
    # The heavy validate + count runs off-thread; poll() (the screen timer)
    # delivers the confirm dialog with overwrite/new counts once it is done.
    _write(cue_env.paths.root,
           os.path.join("data", "markers", "test_game", "v_a.json"),
           '{"pools": []}')
    _write(cue_env.paths.root, "audio/hit.ogg", "A")
    manual._zip_to_file()

    dialog = _FakeConfirmDialog()
    manual._confirm_dialog = dialog
    restarts = []
    # poll() runs under _update_screens=False, so the dialog only appears
    # because _finish_confirm forces a repaint.
    monkeypatch.setattr(_backup.renpy, "restart_interaction",
                        lambda: restarts.append(1))
    manual.restore()
    manual._restore_thread.join(timeout=10)
    manual.poll()

    assert dialog.message is not None
    assert "2 files will be overwritten" in dialog.message
    assert "0 new files will be added" in dialog.message
    assert restarts == [1]
    assert manual._confirm_pending is False
    assert manual.is_restore_checking is False


def test_restore_preflight_in_flight_swallows_second_click(manual):
    # A second Restore click while the preflight worker runs must not spawn
    # another thread (the button is also disabled via is_restore_checking).
    manual._restore_checking = True
    manual._restore_thread = None
    manual.restore()
    assert manual._restore_thread is None


# ---------------------------------------------------------------------------
# Auto backup -- throttle, run, prune
# ---------------------------------------------------------------------------

def test_auto_backup_excludes_media(cue_env):
    # The rolling backup stays data-only; media rides only in the manual
    # renpy_cue_backup.zip.
    _write(cue_env.paths.root, os.path.join("data", "markers", "test_game", "v_a.json"),
           '{"pools": []}')
    _write(cue_env.paths.root, "audio/hit.ogg", "A")
    _write(cue_env.paths.root, "music/song.ogg", "M")

    cue_env.db._backup.force_backup()
    assert cue_env.db._backup.wait_until_idle()

    auto_dir = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR)
    names = [n for n in os.listdir(auto_dir) if n.startswith(CUE_BACKUP_PREFIX)]
    assert names
    with zipfile.ZipFile(os.path.join(auto_dir, names[-1])) as zf:
        entries = zf.namelist()
    assert any(n.startswith("markers/") for n in entries)
    assert not any(n.startswith("audio/") for n in entries)
    assert not any(n.startswith("music/") for n in entries)


def test_backup_manager_latest_timestamp(tmp_path):
    root = str(tmp_path / "shared")
    _write(root, os.path.join(CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR,
                              CUE_BACKUP_PREFIX + "100.zip"), "")
    _write(root, os.path.join(CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR,
                              CUE_BACKUP_PREFIX + "250.zip"), "")
    _write(root, os.path.join(CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR, "junk.txt"), "")

    m = CueBackupManager(CuePaths(root, GAME_ID))
    assert m.auto._latest_backup_timestamp() == 250.0


def test_maybe_throttled_within_interval(tmp_path):
    root = str(tmp_path / "shared")
    m = CueBackupManager(CuePaths(root, GAME_ID))
    m.auto._last_backup_ts = _backup._time.time()  # recent -> inside throttle window

    m.auto.maybe()

    assert m.auto._backup_in_progress is False


def test_auto_backups_enabled_by_default(tmp_path):
    m = CueBackupManager(CuePaths(str(tmp_path / "shared"), GAME_ID))
    assert m.auto.enabled is True


def test_auto_backups_disabled_gates_maybe(tmp_path):
    root = str(tmp_path / "shared")
    m = CueBackupManager(CuePaths(root, GAME_ID))
    m.auto._last_backup_ts = 0  # interval long elapsed -> would normally fire
    m.auto.enabled = False

    m.auto.maybe()

    assert m.auto._backup_in_progress is False


def test_set_auto_backups_persists_to_config(cue_env):
    db = cue_env.db

    db.set_auto_backups(False)
    assert db._backup.auto.enabled is False
    assert db.load_shared_config().get("auto_backups") is False

    db.set_auto_backups(True)
    assert db._backup.auto.enabled is True
    assert db.load_shared_config().get("auto_backups") is True


def test_backup_manager_set_auto_backups_delegates_to_db(cue_env):
    # The settings checkbox calls Function(_cue.backups.set_auto_backups, ...);
    # the composite forwards to the db, which flips the switch and persists.
    db = cue_env.db
    bm = db._backup
    bm.wire(db, lambda count: None, None)  # init -900 wires the composite

    bm.set_auto_backups(False)
    assert bm.auto.enabled is False
    assert db.load_shared_config().get("auto_backups") is False

    bm.set_auto_backups(True)
    assert bm.auto.enabled is True
    assert db.load_shared_config().get("auto_backups") is True


def test_backup_manager_set_auto_backups_unwired_noop(tmp_path):
    # Before init -900 wires _db the toggle must be a safe no-op.
    bm = CueBackupManager(CuePaths(str(tmp_path / "shared"), GAME_ID))
    bm.set_auto_backups(False)
    assert bm.auto.enabled is True


def test_backup_manager_wire_sets_db_and_forwards_to_manual(cue_env):
    db = cue_env.db
    bm = db._backup
    bm.wire(db, lambda count: None, "confirm")

    assert bm._db is db
    assert bm.manual._db is db
    assert bm.manual._reload_work is not None
    assert bm.manual._confirm_dialog == "confirm"


def test_open_seeds_auto_enabled_from_config(tmp_path):
    root = str(tmp_path / "shared")
    _write(root, os.path.join("data", CUE_SHARED_CONFIG_FILENAME),
           '{"auto_backups": false}')
    db = CueDatabase(CuePaths(root, GAME_ID))
    db.open()
    assert db._backup.auto.enabled is False


def test_open_defaults_auto_enabled(tmp_path):
    db = CueDatabase(CuePaths(str(tmp_path / "shared"), GAME_ID))
    db.open()
    assert db._backup.auto.enabled is True


def test_run_backup_without_data_dir(tmp_path):
    root = str(tmp_path / "shared")
    m = CueBackupManager(CuePaths(root, GAME_ID))
    m.auto._backup_in_progress = True

    m.auto._run_backup()

    assert m.auto._backup_in_progress is False  # finally reset it


def test_run_backup_logs_zip_error(tmp_path, monkeypatch):
    root = str(tmp_path / "shared")
    _write(root, os.path.join("data", "markers", GAME_ID, "v_a.json"), '{"pools": []}')
    m = CueBackupManager(CuePaths(root, GAME_ID))
    m.auto._backup_in_progress = True

    def _boom(*args, **kwargs):
        raise RuntimeError("zip failed")
    monkeypatch.setattr(_backup, "zip_tree", _boom)

    m.auto._run_backup()  # must not raise

    assert m.auto._backup_in_progress is False


def test_prune_backups_ignores_listdir_error(tmp_path, monkeypatch):
    m = CueBackupManager(CuePaths(str(tmp_path / "shared"), GAME_ID))

    def _boom(path):
        raise OSError("permission denied")
    monkeypatch.setattr(os, "listdir", _boom)

    m.auto._prune_backups()  # must not raise


def test_prune_backups_removes_oldest(tmp_path):
    root = str(tmp_path / "shared")
    auto = os.path.join(root, CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR)
    os.makedirs(auto)
    for i in range(CUE_BACKUP_MAX + 10):
        name = CUE_BACKUP_PREFIX + str(1000 + i) + ".zip"
        with open(os.path.join(auto, name), "w") as f:
            f.write("x")
    m = CueBackupManager(CuePaths(root, GAME_ID))

    m.auto._prune_backups()

    remaining = sorted(os.listdir(auto))
    assert len(remaining) == CUE_BACKUP_MAX
    assert CUE_BACKUP_PREFIX + "1000.zip" not in remaining
    assert CUE_BACKUP_PREFIX + str(1000 + CUE_BACKUP_MAX + 9) + ".zip" in remaining


def test_prune_backups_ignores_remove_error(tmp_path, monkeypatch):
    root = str(tmp_path / "shared")
    auto = os.path.join(root, CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR)
    os.makedirs(auto)
    for i in range(CUE_BACKUP_MAX + 2):
        name = CUE_BACKUP_PREFIX + str(1000 + i) + ".zip"
        with open(os.path.join(auto, name), "w") as f:
            f.write("x")
    m = CueBackupManager(CuePaths(root, GAME_ID))

    def _boom(path):
        raise OSError("locked")
    monkeypatch.setattr(os, "remove", _boom)

    m.auto._prune_backups()  # must not raise


# ---------------------------------------------------------------------------
# CueBackupManager composite facade
# ---------------------------------------------------------------------------

def test_composite_facade(cue_env):
    bm = cue_env.db._backup
    assert bm.path == cue_env.paths.original_root
    assert bm.game_id == "test_game"
    assert bm.backups_root() == cue_env.paths.backups_dir
    assert bm.auto._owner is bm
    assert bm.manual._owner is bm

    bm.manual.is_backing_up = True
    assert bm.is_backing_up is True
    bm.manual.is_restoring = True
    assert bm.is_restoring is True
    bm.manual._restore_checking = True
    assert bm.is_restore_checking is True
    bm.manual.backup_status = "s"
    assert bm.backup_status == "s"
    bm.manual.backup_error = "e"
    assert bm.backup_error == "e"
    bm.manual.restore_status = "rs"
    assert bm.restore_status == "rs"
    bm.manual.restore_error = "re"
    assert bm.restore_error == "re"


# ---------------------------------------------------------------------------
# _backup_ts_from_name -- filename parsing branches
# ---------------------------------------------------------------------------

def test_backup_ts_from_name_rejects_unrelated_names():
    assert _backup_ts_from_name("other.txt") is None
    assert _backup_ts_from_name("notes.zip") is None


def test_backup_ts_from_name_rejects_non_numeric_ts():
    assert _backup_ts_from_name(CUE_BACKUP_PREFIX + "abc.zip") is None


# ---------------------------------------------------------------------------
# zip_tree -- default tmp path
# ---------------------------------------------------------------------------

def test_zip_tree_default_tmp_path(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "f.txt").write_text("x")
    zip_path = str(tmp_path / "out.zip")

    count = zip_tree(str(data), zip_path)

    assert count == 1
    assert os.path.exists(zip_path)
    assert not os.path.exists(zip_path + ".tmp")


# ---------------------------------------------------------------------------
# validate_backup_zip -- failure branches
# ---------------------------------------------------------------------------

def test_validate_rejects_corrupt_entry(tmp_path, monkeypatch):
    zip_path = str(tmp_path / "bad.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("markers/{}/v_a.json".format(GAME_ID), '{"pools": []}')
    monkeypatch.setattr(
        zipfile.ZipFile, "testzip",
        lambda self: "markers/{}/v_a.json".format(GAME_ID))

    ok, reason = validate_backup_zip(zip_path)
    assert not ok
    assert "corrupt" in reason


def test_validate_rejects_empty_zip(tmp_path):
    zip_path = str(tmp_path / "empty.zip")
    with zipfile.ZipFile(zip_path, "w"):
        pass

    ok, reason = validate_backup_zip(zip_path)
    assert not ok
    assert "empty" in reason


def test_validate_rejects_non_data_zip(tmp_path):
    zip_path = str(tmp_path / "other.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("random/file.txt", "x")

    ok, reason = validate_backup_zip(zip_path)
    assert not ok
    assert "not a data backup" in reason


def test_validate_rejects_bad_json(tmp_path):
    zip_path = str(tmp_path / "badjson.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("markers/{}/v_a.json".format(GAME_ID), "not json")

    ok, reason = validate_backup_zip(zip_path)
    assert not ok
    assert "bad JSON" in reason


def test_validate_stops_spot_check_after_five(tmp_path):
    zip_path = str(tmp_path / "many.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(6):
            zf.writestr("markers/{}/v_{}.json".format(GAME_ID, i), '{"pools": []}')

    ok, reason = validate_backup_zip(zip_path)
    assert ok, reason


# ---------------------------------------------------------------------------
# restore_pieces -- branch coverage
# ---------------------------------------------------------------------------

def test_restore_rejects_invalid_zip(tmp_path):
    zip_path = str(tmp_path / "bad.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("random/file.txt", "x")

    with pytest.raises(ValueError):
        restore_pieces(zip_path, str(tmp_path / "shared"), GAME_ID)


def test_restore_replaces_stale_staging_and_bak(shared, tmp_path):
    _marker(shared, "v_a.json")
    _write(shared, "audio/hit.ogg", "A")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    # Leftovers from a previous restore are swept away.
    _write(shared, os.path.join(CUE_RESTORE_TMP_DIR, "stale.txt"), "S")
    _write(shared, os.path.join(CUE_BAK_DIR, "stale2.txt"), "S2")

    restore_pieces(zip_path, shared, GAME_ID)

    assert not os.path.exists(os.path.join(shared, CUE_RESTORE_TMP_DIR, "stale.txt"))
    assert not os.path.exists(os.path.join(shared, CUE_BAK_DIR, "stale2.txt"))


def test_restore_creates_missing_target_parent(shared, tmp_path):
    # The backup carries a file whose parent dir does not exist live.
    zip_path = str(tmp_path / "backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("audio/nested/hit.ogg", "AUDIO")

    restore_pieces(zip_path, shared, GAME_ID)

    assert _read(shared, "audio/nested/hit.ogg") == "AUDIO"
