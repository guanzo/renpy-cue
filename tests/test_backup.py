# -*- coding: utf-8 -*-
# Tests for cue_lib.backup -- zip_shared_tree, validate_backup_zip,
# restore_pieces.
#
# restore_pieces must MERGE the backup over the live tree, never removing
# data the backup does not carry (markers made after the backup survive,
# shared presets/config and other games' markers are untouched), and must
# cover the shared audio/ and music/ folders as well as data/.

import errno
import os
import zipfile

import pytest

from cue_lib.backup import (
    CUE_BACKUP_AUTO_DIR,
    CUE_BACKUP_DIR,
    CUE_BACKUP_PREFIX,
    CUE_BAK_DIR,
    CUE_MANUAL_BACKUP_NAME,
    CUE_RESTORE_TMP_DIR,
    restore_pieces,
    validate_backup_zip,
    zip_shared_tree,
)
from cue_lib.constants import CUE_SHARED_CONFIG_FILENAME
from cue_lib.marker_store import CueMarkerStore

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

    zip_path = str(tmp_path / "backup.zip")
    count = zip_shared_tree(shared, zip_path)

    assert count == 5
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    # data/ stays flat for backward compatibility; media under their own dirs.
    assert "markers/{}/v_a.json".format(GAME_ID) in names
    assert "presets/p.json" in names
    assert CUE_SHARED_CONFIG_FILENAME in names
    assert "audio/loop/hit.ogg" in names
    assert "music/ost/song.ogg" in names


def test_validate_backup_zip_accepts_media_only(shared, tmp_path):
    _write(shared, "audio/hit.ogg", "AUDIO")
    zip_path = str(tmp_path / "backup.zip")
    zip_shared_tree(shared, zip_path)

    ok, _reason = validate_backup_zip(zip_path)
    assert ok


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
# CueMarkerStore.backup_to_file / auto-backup scope
# ---------------------------------------------------------------------------

def test_backup_to_file_includes_media(cue_env):
    # The manual backup (the floppy-disk button) zips audio/ and music/ too.
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    store._data["v_a"] = {"pools": []}
    store.save_all()
    _write(cue_env.paths.root, "audio/hit.ogg", "A")
    _write(cue_env.paths.root, "music/song.ogg", "M")

    store.backup_to_file()

    zip_path = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR, CUE_MANUAL_BACKUP_NAME)
    with zipfile.ZipFile(zip_path) as zf:
        entries = zf.namelist()
    assert any(n.startswith("markers/") for n in entries)
    assert "audio/hit.ogg" in entries
    assert "music/song.ogg" in entries


def test_backup_to_file_eeexist_race_benign(cue_env, monkeypatch):
    # The auto-backup thread can create {root}/backups/ between backup_to_file's
    # isdir check and its own makedirs. EEXIST is benign -- the backup proceeds.
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    _write(cue_env.paths.root, os.path.join("data", "markers", "test_game", "v_a.json"),
           '{"pools": []}')

    backups_dir = os.path.join(cue_env.paths.root, CUE_BACKUP_DIR)
    real_makedirs = os.makedirs

    def _racing_makedirs(path):
        real_makedirs(path)
        if path == backups_dir:
            raise OSError(errno.EEXIST, "exists")

    monkeypatch.setattr(os, "makedirs", _racing_makedirs)

    store.backup_to_file()  # must not raise

    zip_path = os.path.join(backups_dir, CUE_MANUAL_BACKUP_NAME)
    assert os.path.exists(zip_path)


def test_auto_backup_excludes_media(cue_env):
    # The hourly rolling backup stays data-only; media rides only in the
    # manual backup.zip.
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
