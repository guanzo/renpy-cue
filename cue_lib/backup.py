# -*- coding: utf-8 -*-
# cue_lib/backup.py -- Automatic backup of the shared data/ tree.
#
# Owned by CueDatabase as self._backup.  After any disk CRUD in data/, the
# owning database calls maybe(); if at least CUE_BACKUP_INTERVAL has passed
# since the last backup, the data/ tree is zipped into
# {shared}/backups/auto/auto_backup_<unix_ts>.zip on a daemon thread and the
# CUE_BACKUP_MAX most recent backups are kept.
#
# Pure Python stdlib -- no C extensions.  Works on any Ren'Py build.

import os
import threading as _threading
import time as _time
import zipfile as _zipfile

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

MYPY = False
if MYPY:
    from typing import Optional  # pyright: ignore[reportUnusedImport]


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
            # same second never write the same file; the final rename is
            # atomic, so a same-second collision resolves to one complete zip.
            tmp_path = os.path.join(backup_dir, "{}{}_{}.zip.tmp".format(
                CUE_BACKUP_PREFIX, ts, self._game_id))
            final_path = os.path.join(
                backup_dir, "{}{}.zip".format(CUE_BACKUP_PREFIX, ts))
            count = 0
            with _zipfile.ZipFile(tmp_path, "w", _zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(data_dir):
                    for name in files:
                        fpath = _to_str(os.path.join(root, name))
                        arcname = _to_str(os.path.relpath(fpath, data_dir))
                        zf.write(fpath, arcname)
                        count += 1
            os.rename(tmp_path, final_path)
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
