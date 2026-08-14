# -*- coding: utf-8 -*-
# cue_lib/backup.py -- Automatic backup of the shared data/ tree.
#
# Owned by CueDatabase as self._backup.  After any disk CRUD in data/, the
# owning database calls maybe(); if at least CUE_BACKUP_INTERVAL has passed
# since the last backup, the data/ tree is zipped into
# {shared}/backups/auto/auto_backup_<unix_ts>.zip on a daemon thread and the
# CUE_BACKUP_MAX most recent backups are kept.
#
# The manual backup/restore buttons are driven from markers.py, which calls
# zip_tree() here for the whole data/ tree into {shared}/backups/backup.zip,
# and restore_pieces() to swap the affected paths out of data/ (kept in
# {shared}/data_bak as a safety net) and in from that zip.
#
# Pure Python stdlib -- no C extensions.  Works on any Ren'Py build.

import json as _json
import os
import shutil as _shutil
import threading as _threading
import time as _time
import zipfile as _zipfile

from cue_lib.constants import CUE_SHARED_CONFIG_FILENAME
from cue_lib.util import _cue_log, _to_str

# Automatic backup of the data/ tree.  After any disk CRUD, when at least
# CUE_BACKUP_INTERVAL seconds have passed since the last backup, zip the
# data/ tree into {shared}/backups/auto/auto_backup_<unix_ts>.zip and keep
# the CUE_BACKUP_MAX most recent files.
CUE_BACKUP_INTERVAL = 3600
CUE_BACKUP_MAX = 100
CUE_BACKUP_DIR = "backups"
CUE_BACKUP_AUTO_DIR = "auto"
CUE_BACKUP_PREFIX = "auto_backup_"

# Manual backup/restore: a single named zip in {shared}/backups/ that the
# user controls, plus the pre-restore safety net and staging dirs.
CUE_MANUAL_BACKUP_NAME = "backup.zip"
CUE_BAK_DIR = "data_bak"
CUE_RESTORE_TMP_DIR = "_restore_tmp"

MYPY = False
if MYPY:
    from typing import List, Optional, Tuple  # pyright: ignore[reportUnusedImport]


def _backup_ts_from_name(name):
    # type: (str) -> Optional[int]
    """Extract the unix timestamp from an auto_backup_<ts>.zip filename.
    Returns None if the name is not a recognized backup file."""
    if not (name.startswith(CUE_BACKUP_PREFIX) and name.endswith(".zip")):
        return None
    ts_text = name[len(CUE_BACKUP_PREFIX):-len(".zip")]
    try:
        return int(ts_text)
    except Exception:
        return None


def _matches_any(name, matchers):
    # type: (str, List[str]) -> bool
    """True if name equals a matcher or lives under a matcher directory."""
    for m in matchers:
        if name == m or name.startswith(m + "/"):
            return True
    return False


def _safe_extract_path(out_dir, name):
    # type: (str, str) -> str
    """Join a zip arcname under out_dir, dropping any parent-traversal parts."""
    parts = [p for p in name.split("/") if p and p != ".."]
    return _to_str(os.path.join(out_dir, *parts))


def _replace_file(src, dst):
    # type: (str, str) -> None
    """Rename src over dst, overwriting an existing dst.

    POSIX os.rename overwrites atomically; on Windows it refuses with Error
    183, so a stale destination is removed first.  The destination here is
    always a zip we just finished writing, so the brief absence between
    remove and rename is harmless."""
    if os.name == "nt" and os.path.lexists(dst):
        try:
            os.remove(dst)
        except Exception:
            pass  # Rename below fails loudly if the stale file persists
    os.rename(src, dst)


def zip_tree(data_dir, zip_path, tmp_path=None):
    # type: (str, str, Optional[str]) -> int
    """Zip a directory tree into zip_path. Writes tmp_path first (default
    zip_path + ".tmp"), then moves it over zip_path. Returns file count."""
    if tmp_path is None:
        tmp_path = zip_path + ".tmp"
    count = 0
    with _zipfile.ZipFile(tmp_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(data_dir):
            for name in files:
                fpath = _to_str(os.path.join(root, name))
                arcname = _to_str(os.path.relpath(fpath, data_dir))
                zf.write(fpath, arcname)
                count += 1
    _replace_file(tmp_path, zip_path)
    return count


def validate_backup_zip(zip_path):
    # type: (str) -> Tuple[bool, str]
    """Heuristic validation of a manual backup zip. Returns (ok, reason)."""
    try:
        zf = _zipfile.ZipFile(zip_path, "r")
    except Exception as e:
        return (False, "not a zip: {}".format(str(e)))
    with zf:
        bad = zf.testzip()
        if bad is not None:
            return (False, "corrupt entry '{}'".format(bad))
        names = zf.namelist()
        if not names:
            return (False, "zip is empty")
        looks_like_data = any(
            n.startswith("markers/") or n.startswith("presets/")
            or n == CUE_SHARED_CONFIG_FILENAME
            for n in names
        )
        if not looks_like_data:
            return (False, "not a data backup (no markers/, presets/, or {})".format(
                CUE_SHARED_CONFIG_FILENAME))
        # Spot-check that embedded JSON parses (stops after a few).
        checked = 0
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                _json.loads(zf.read(n))
            except Exception as e:
                return (False, "bad JSON in '{}': {}".format(n, str(e)))
            checked += 1
            if checked >= 5:
                break
    return (True, "")


def extract_matching(zip_path, out_dir, matchers):
    # type: (str, str, List[str]) -> int
    """Extract zip entries matching any matcher into out_dir. Returns count."""
    count = 0
    with _zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if not _matches_any(name, matchers):
                continue
            target = _safe_extract_path(out_dir, name)
            parent = os.path.dirname(target)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with open(target, "wb") as f:
                f.write(zf.read(name))
            count += 1
    return count


def restore_pieces(zip_path, shared_dir, game_id):
    # type: (str, str, str) -> int
    """Restore this game's markers + shared presets + shared config from a
    manual backup zip into {shared}/data.

    The current affected paths (data/markers/<game_id>, data/presets,
    data/cue_config.json) are moved aside into {shared}/data_bak first --
    kept as a safety net and replaced on the next restore.  Other games'
    marker dirs are left untouched.  Returns the number of files extracted.
    Raises ValueError if the zip fails validation."""
    ok, reason = validate_backup_zip(zip_path)
    if not ok:
        raise ValueError("invalid backup: {}".format(reason))

    data_dir = os.path.join(shared_dir, "data")
    staging = os.path.join(shared_dir, CUE_RESTORE_TMP_DIR)
    bak_dir = os.path.join(shared_dir, CUE_BAK_DIR)

    if not os.path.isdir(data_dir):
        os.makedirs(data_dir)

    # Stage the affected pieces before touching data/.
    if os.path.isdir(staging):
        _shutil.rmtree(staging)
    os.makedirs(staging)
    matchers = ["markers/{}".format(game_id), "presets", CUE_SHARED_CONFIG_FILENAME]
    count = extract_matching(zip_path, staging, matchers)

    # Replace the previous safety net with the current state.
    if os.path.isdir(bak_dir):
        _shutil.rmtree(bak_dir)
    os.makedirs(bak_dir)

    rel_pieces = [
        os.path.join("markers", game_id),
        "presets",
        CUE_SHARED_CONFIG_FILENAME,
    ]
    # Move current pieces aside first so the restored ones can land.
    for rel in rel_pieces:
        cur = os.path.join(data_dir, *rel.split("/"))
        if not os.path.lexists(cur):
            continue
        bak_target = os.path.join(bak_dir, *rel.split("/"))
        parent = os.path.dirname(bak_target)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        os.rename(cur, bak_target)
    # Move restored pieces into place (only those the backup actually has).
    for rel in rel_pieces:
        staged = os.path.join(staging, *rel.split("/"))
        if not os.path.lexists(staged):
            continue
        target = os.path.join(data_dir, *rel.split("/"))
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        os.rename(staged, target)

    _shutil.rmtree(staging, ignore_errors=True)
    return count


# =========================================================================
# CueBackupManager
# =========================================================================

class CueBackupManager(object):
    """Throttled, background zipping of the shared data/ tree."""

    def __init__(self, path, game_id):
        # type: (str, str) -> None
        self._path = path
        self._game_id = game_id
        self._last_backup_ts = self._latest_backup_timestamp()
        self._backup_in_progress = False

    def _backups_dir(self):
        # type: () -> str
        """Directory holding automatic backups."""
        return os.path.join(self._path, CUE_BACKUP_DIR, CUE_BACKUP_AUTO_DIR)

    def _latest_backup_timestamp(self):
        # type: () -> float
        """Wall-clock ts of the newest auto_backup_*.zip, or 0.0 if none."""
        backup_dir = self._backups_dir()
        try:
            names = os.listdir(backup_dir)
        except Exception:
            return 0.0
        newest = 0.0
        for name in names:
            ts = _backup_ts_from_name(name)
            if ts is not None:
                newest = max(newest, float(ts))
        return newest

    def maybe(self):
        # type: () -> None
        """Throttled trigger: spawn a background zip when it is time."""
        if self._backup_in_progress:
            return
        if _time.time() - self._last_backup_ts < CUE_BACKUP_INTERVAL:
            return
        self._backup_in_progress = True
        t = _threading.Thread(target=self._run_backup)
        t.daemon = True
        t.start()

    def force_backup(self):
        # type: () -> None
        """Run a backup immediately, ignoring the interval throttle."""
        self._last_backup_ts = 0
        self.maybe()

    def wait_until_idle(self, timeout=10.0):
        # type: (float) -> bool
        """Block until the in-flight backup thread finishes.
        Returns False if the timeout expires first."""
        deadline = _time.time() + timeout
        while self._backup_in_progress and _time.time() < deadline:
            _time.sleep(0.05)
        return not self._backup_in_progress

    def _run_backup(self):
        # type: () -> None
        """Zip data/ to auto_backup_<ts>.zip on a background thread."""
        try:
            ts = int(_time.time())
            data_dir = _to_str(os.path.join(self._path, "data"))
            if not os.path.isdir(data_dir):
                return
            backup_dir = self._backups_dir()
            if not os.path.isdir(backup_dir):
                os.makedirs(backup_dir)
            # Temp name is unique per game so two games backing up in the
            # same second never write the same file; the final move replaces
            # any same-second zip, so a collision resolves to one complete file.
            tmp_path = os.path.join(backup_dir, "{}{}_{}.zip.tmp".format(
                CUE_BACKUP_PREFIX, ts, self._game_id))
            final_path = os.path.join(
                backup_dir, "{}{}.zip".format(CUE_BACKUP_PREFIX, ts))
            count = zip_tree(data_dir, final_path, tmp_path)
            self._prune_backups()
            self._last_backup_ts = _time.time()
            _cue_log("BACKUP: wrote {} ({} files)".format(final_path, count))
        except Exception as e:
            _cue_log("BACKUP-ERROR {}".format(str(e)))
        finally:
            self._backup_in_progress = False

    def _prune_backups(self):
        # type: () -> None
        """Delete the oldest backups beyond CUE_BACKUP_MAX."""
        backup_dir = self._backups_dir()
        try:
            names = os.listdir(backup_dir)
        except Exception:
            return
        matches = []
        for name in names:
            ts = _backup_ts_from_name(name)
            if ts is not None:
                matches.append((ts, name))
        if len(matches) <= CUE_BACKUP_MAX:
            return
        matches.sort(reverse=True)  # newest first
        for _ts, name in matches[CUE_BACKUP_MAX:]:
            try:
                os.remove(os.path.join(backup_dir, name))
            except Exception:
                pass
