# -*- coding: utf-8 -*-
# cue_lib/backup.py -- Backup of the shared data/ tree.
#
# The composite CueBackupManager is a top-level _cue manager, built in the
# init -900 wiring block and injected into CueDatabase as self._backup.  It
# splits the two backup flows into sub-managers:
#
#   .auto   -- CueAutoBackupManager.  After any disk CRUD in data/, the
#              owning database calls maybe(); if at least CUE_BACKUP_INTERVAL
#              has passed since the last backup, the data/ tree is zipped into
#              {shared}/backups/auto/auto_backup_<unix_ts>.zip on a daemon
#              thread and the CUE_BACKUP_MAX most recent backups are kept.
#   .manual -- CueManualBackupManager.  The Back Up / Restore buttons.  The
#              disk phases (zip / restore merge) run on daemon threads; the
#              in-memory reload after a restore is handed to an injected
#              callback, polled from a screen timer via poll().
#
# Media (audio/, music/, video/) is deliberately excluded from the auto
# backup.  It is already-compressed, so DEFLATED zips it at ~1.0 ratio --
# a full-core pass plus double I/O for no size gain -- and with
# CUE_BACKUP_MAX (720) a month of auto-backups would eat tens of GB of
# drive for media.  The manual backup button covers media on demand, where
# the user has chosen to pay that cost.
#
# All paths resolve against the real shared root (CuePaths.original_root),
# never an active import, so a backup always captures the user's live tree.
#
# Pure Python stdlib -- no C extensions.  Works on any Ren'Py build.

import errno
import json as _json
import os
import shutil as _shutil
import threading as _threading
import time as _time
import zipfile as _zipfile

from renpy.store import Function

from cue_lib.constants import (
    CUE_MANUAL_BACKUP_NAME,
    CUE_SHARED_CONFIG_FILENAME,
)
from cue_lib.util import _cue_log, _cue_replace_file, _to_str

# Automatic backup of the data/ tree.  After any disk CRUD, when at least
# CUE_BACKUP_INTERVAL seconds have passed since the last backup, zip the
# data/ tree into {shared}/backups/auto/auto_backup_<unix_ts>.zip and keep
# the CUE_BACKUP_MAX most recent files.
CUE_BACKUP_INTERVAL = 3600  # once an hour (every 60 min)
CUE_BACKUP_MAX = 720  # ~a month at one backup/hour
CUE_BACKUP_PREFIX = "auto_backup_"

# Manual backup/restore: a single named zip in {shared}/backups/ that the
# user controls, plus the pre-restore safety net and staging dirs.
CUE_BAK_DIR = "data_bak"
CUE_RESTORE_TMP_DIR = "_restore_tmp"

# User-media folders at the shared root (audio_dir / music_dir) that the
# manual backup/restore carries alongside the internal data/ tree.  Shared by
# zip_shared_tree() and restore_pieces() so the two stay in sync.
CUE_MEDIA_DIRS = ("audio", "music")

# Per-game speed-variant video tree ({root}/video/{game_id}/).  Backed up as a
# whole tree like the media folders; restored only for this game's subdir
# (mirrors markers/{game_id}).
CUE_VIDEO_DIR = "video"

MYPY = False
if MYPY:
    from typing import Any, Callable, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths


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
    # type: (str, str) -> Optional[str]
    """Join a zip arcname under out_dir, rejecting parent-traversal names.

    Backslashes are folded to '/' first so Windows-style traversal
    (..\\..\\evil.txt) can't slip past the '..' filter.  Any name carrying a
    '..' segment is rejected outright -- the mod never writes such arcnames,
    so one means the archive is lying about its layout, and rewriting it
    (dropping the '..') would land the file at an unclaimed path.  The result
    is then verified to still sit under out_dir.  Returns None for rejected
    names (traversal or a drive-absolute name on Windows) -- callers skip."""
    name = _to_str(name).replace("\\", "/")
    parts = [p for p in name.split("/") if p]
    if ".." in parts:
        _cue_log("CUE: blocked path traversal: {}".format(name))
        return None
    dest = os.path.normpath(os.path.join(out_dir, *parts))
    base = os.path.normpath(out_dir)
    if dest != base and not dest.startswith(base + os.sep):
        _cue_log("CUE: blocked path escape: {}".format(name))
        return None
    return dest


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
    _cue_replace_file(tmp_path, zip_path)
    return count


def zip_shared_tree(root, zip_path, tmp_path=None, progress=None):
    # type: (str, str, Optional[str], Optional[Any]) -> int
    """Zip the shared tree's data/, audio/, music/, and video/ folders into
    zip_path.

    data/ entries keep their flat arcnames (markers/, presets/,
    cue_config.json) for backward compatibility with older backup.zip files;
    audio/, music/, and video/ entries are stored under their own top-level
    dirs.  Writes tmp_path first (default zip_path + ".tmp"), then moves it
    over zip_path.  Returns file count.  When progress is given it is called
    as progress(written_bytes, total_bytes) after each file; total is the
    pre-computed sum of sizes of the files that exist."""
    if tmp_path is None:
        tmp_path = zip_path + ".tmp"
    sources = [(os.path.join(root, "data"), "")]
    for media in CUE_MEDIA_DIRS:
        sources.append((os.path.join(root, media), media))
    sources.append((os.path.join(root, CUE_VIDEO_DIR), CUE_VIDEO_DIR))
    total = 0
    if progress is not None:
        for src_dir, _prefix in sources:
            if not os.path.isdir(src_dir):
                continue
            for walk_root, _dirs, files in os.walk(src_dir):
                for name in files:
                    total += os.path.getsize(
                        _to_str(os.path.join(walk_root, name)))
    count = 0
    written = 0
    with _zipfile.ZipFile(tmp_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        for src_dir, prefix in sources:
            if not os.path.isdir(src_dir):
                continue
            for walk_root, _dirs, files in os.walk(src_dir):
                for name in files:
                    fpath = _to_str(os.path.join(walk_root, name))
                    rel = _to_str(os.path.relpath(fpath, src_dir))
                    arcname = _to_str(os.path.join(prefix, rel))
                    zf.write(fpath, arcname)
                    count += 1
                    if progress is not None:
                        written += os.path.getsize(fpath)
                        progress(written, total)
    _cue_replace_file(tmp_path, zip_path)
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
            or _matches_any(n, list(CUE_MEDIA_DIRS))
            or n.startswith(CUE_VIDEO_DIR + "/")
            for n in names
        )
        if not looks_like_data:
            return (False, "not a data backup (no markers/, presets/, "
                    "audio/, music/, video/, or {})".format(CUE_SHARED_CONFIG_FILENAME))
        # Spot-check that embedded JSON parses (stops after a few).  Only
        # mod-data entries are checked -- a stray .json dropped into audio/
        # or music/ isn't marker data and shouldn't invalidate the backup.
        checked = 0
        for n in names:
            if not n.endswith(".json"):
                continue
            if not (n.startswith("markers/") or n.startswith("presets/")
                    or n == CUE_SHARED_CONFIG_FILENAME):
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
            if target is None:
                continue
            parent = os.path.dirname(target)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with open(target, "wb") as f:
                f.write(zf.read(name))
            count += 1
    return count


def restore_pieces(zip_path, shared_dir, game_id):
    # type: (str, str, str) -> int
    """Merge this game's markers + shared presets + shared config + the
    shared audio/ and music/ folders + this game's video/ subdir from a
    manual backup zip into the live tree.

    Merge rule: every file the backup carries is written over the live
    tree, and the previous version is moved aside into {shared}/data_bak
    first (a safety net, replaced on the next restore).  Anything not in
    the backup is left untouched -- restore never removes data it doesn't
    know about, so markers made after the backup survive.  Other games'
    marker and video dirs are left untouched.  Returns the number of files
    extracted.  Raises ValueError if the zip fails validation."""
    ok, reason = validate_backup_zip(zip_path)
    if not ok:
        raise ValueError("invalid backup: {}".format(reason))

    data_dir = os.path.join(shared_dir, "data")
    staging = os.path.join(shared_dir, CUE_RESTORE_TMP_DIR)
    bak_dir = os.path.join(shared_dir, CUE_BAK_DIR)

    if not os.path.isdir(data_dir):
        os.makedirs(data_dir)

    # Stage the affected pieces before touching the live tree.
    if os.path.isdir(staging):
        _shutil.rmtree(staging)
    os.makedirs(staging)
    matchers = ["markers/{}".format(game_id), "presets", CUE_SHARED_CONFIG_FILENAME]
    matchers += list(CUE_MEDIA_DIRS)
    matchers.append("{}/{}".format(CUE_VIDEO_DIR, game_id))
    count = extract_matching(zip_path, staging, matchers)

    # Replace the previous safety net with the current state.
    if os.path.isdir(bak_dir):
        _shutil.rmtree(bak_dir)
    os.makedirs(bak_dir)

    # Merge the backup over the live tree, file by file.  For each entry
    # the backup carries, move the current version aside to data_bak, then
    # write the restored file in its place.  Anything not in the backup is
    # left untouched -- restore never removes data it doesn't know about.
    # audio/, music/, and video/ live at the shared root; the rest lives
    # under data/.
    for walk_root, _dirs, files in os.walk(staging):
        for name in files:
            staged = _to_str(os.path.join(walk_root, name))
            rel = _to_str(os.path.relpath(staged, staging))
            first = rel.split("/", 1)[0]
            base = shared_dir if (first in CUE_MEDIA_DIRS
                                  or first == CUE_VIDEO_DIR) else data_dir
            target = os.path.join(base, rel)
            if os.path.lexists(target):
                bak_target = os.path.join(bak_dir, rel)
                parent = os.path.dirname(bak_target)
                if not os.path.isdir(parent):
                    os.makedirs(parent)
                _cue_replace_file(target, bak_target)
            parent = os.path.dirname(target)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            _cue_replace_file(staged, target)

    _shutil.rmtree(staging, ignore_errors=True)
    return count


# =========================================================================
# CueAutoBackupManager
# =========================================================================

class CueAutoBackupManager(object):
    """Throttled, background zipping of the shared data/ tree."""

    def __init__(self, owner):
        # type: (CueBackupManager) -> None
        self._owner = owner
        self._last_backup_ts = self._latest_backup_timestamp()
        self._backup_in_progress = False
        # Master switch for automatic backups.  True by default; the owning
        # database seeds it from cue_config.json at open() and the Settings
        # page toggles it via set_auto_backups().
        self.enabled = True

    def _backups_dir(self):
        # type: () -> str
        """Directory holding automatic backups."""
        return self._owner._paths.auto_backups_dir

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
        if not self.enabled:
            return
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
            root = self._owner._paths.original_root
            data_dir = os.path.join(root, "data")
            if not os.path.isdir(data_dir):
                return
            backup_dir = self._backups_dir()
            if not os.path.isdir(backup_dir):
                os.makedirs(backup_dir)
            # Temp name is unique per game so two games backing up in the
            # same second never write the same file; the final move replaces
            # any same-second zip, so a collision resolves to one complete file.
            tmp_path = os.path.join(backup_dir, "{}{}_{}.zip.tmp".format(
                CUE_BACKUP_PREFIX, ts, self._owner._paths.game_id))
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


# =========================================================================
# CueManualBackupManager
# =========================================================================

class CueManualBackupManager(object):
    """Async manual backup/restore (the Back Up / Restore buttons).

    The disk phases (zip / restore merge) run on daemon threads so the UI
    never blocks; the main-thread reload of marker state is handed to an
    injected callback, polled from a screen timer via poll().  Status flags
    drive the settings-page text and the button busy state.
    """

    def __init__(self, owner):
        # type: (CueBackupManager) -> None
        self._owner = owner
        self._db = None          # CueDatabase, injected by wire()
        self._reload_work = None  # callable(count) -> None, wired by init -900
        self._confirm_dialog = None
        self.is_backing_up = False
        self.backup_fraction = 0.0  # 0..1 progress of the active manual zip
        self.is_restoring = False
        self.backup_status = ""
        self.backup_error = ""
        self.restore_status = ""
        self.restore_error = ""
        self._backup_thread = None
        self._restore_thread = None
        self._restore_pending = False
        self._restore_count = 0

    def wire(self, db, reload_work, confirm_dialog):
        # type: (Any, Callable[[int], None], Any) -> None
        """Attach the collaborators only available after full init: the
        shared database (open-state guard), the marker reload callback
        (main-thread, post-restore), and the confirm dialog."""
        self._db = db
        self._reload_work = reload_work
        self._confirm_dialog = confirm_dialog

    # -- backup --

    def backup(self):
        # type: () -> None
        """Zip the shared tree to backups/renpy_cue_backup.zip on a background
        thread; sets backup_status / backup_error when done."""
        if self.is_backing_up or self.is_restoring:
            return
        self.backup_status = ""
        self.backup_error = ""
        self.is_backing_up = True
        self.backup_fraction = 0.0
        t = _threading.Thread(target=self._backup_worker)
        t.daemon = True
        self._backup_thread = t
        t.start()

    def _backup_worker(self):
        # type: () -> None
        """The off-thread zip write.  Sets backup_status / backup_error and
        clears is_backing_up when done."""
        try:
            count = self._zip_to_file()
            self.backup_status = ("Backed up {} files to "
                "backups/renpy_cue_backup.zip.").format(count)
        except Exception as e:
            self.backup_error = "Backup failed: {}".format(e)
        finally:
            self.is_backing_up = False

    def _zip_to_file(self):
        # type: () -> int
        """Zip the shared data/ tree plus audio/, music/, and video/ to
        backups/renpy_cue_backup.zip.  Returns the file count; raises on
        failure."""
        db = self._db
        if db is None or not db.is_open():
            return 0
        paths = self._owner._paths
        root = paths.original_root
        if not os.path.isdir(os.path.join(root, "data")):
            _cue_log("DUMP-MARKERS-NO-DATA")
            return 0
        backups_dir = paths.backups_dir
        if not os.path.isdir(backups_dir):
            try:
                os.makedirs(backups_dir)
            except OSError as e:
                # The auto-backup thread (db._backup) can create
                # {root}/backups/ between the isdir check and here -- its
                # makedirs of backups/auto/ creates the parent first.
                # EEXIST is benign; anything else is a real failure.
                if e.errno != errno.EEXIST:
                    raise
        zip_path = paths.manual_backup_path
        tmp_path = os.path.join(
            backups_dir, "{}.{}.tmp".format(CUE_MANUAL_BACKUP_NAME, paths.game_id))
        return zip_shared_tree(root, zip_path, tmp_path, self._set_backup_progress)

    def _set_backup_progress(self, written, total):
        # type: (int, int) -> None
        """Progress callback for the manual zip; feeds the settings-page %."""
        self.backup_fraction = (written / float(total)) if total else 1.0

    # -- restore --

    def restore(self):
        # type: () -> None
        """Validate renpy_cue_backup.zip, then ask the user to confirm a restore."""
        db = self._db
        if db is None or not db.is_open():
            return
        zip_path = self._owner._paths.manual_backup_path
        if not os.path.isfile(zip_path):
            _cue_log("RESTORE-MARKERS-NO-FILE path={}".format(zip_path))
            return
        ok, reason = validate_backup_zip(zip_path)
        if not ok:
            _cue_log("RESTORE-MARKERS-INVALID {}".format(reason))
            return
        if self._confirm_dialog is not None:
            self._confirm_dialog.show(
                "Restore from backups/renpy_cue_backup.zip? This will overwrite this "
                "game's markers, presets, shared config, and the audio/ and "
                "music/ folders with the backup's version. Data not included in "
                "the backup (including anything added after, and other games' "
                "markers) is left untouched. Previous data is saved to data_bak.",
                Function(self._apply_restore, zip_path),
            )

    def _apply_restore(self, zip_path):
        # type: (str) -> None
        """Merge renpy_cue_backup.zip over the live tree in the background.
        The disk phase runs on a thread; the in-memory reload happens on the
        main thread via poll() once the disk phase sets _restore_pending."""
        if self.is_restoring or self.is_backing_up:
            return
        self.restore_status = ""
        self.restore_error = ""
        self.is_restoring = True
        self._restore_pending = False
        self._restore_count = 0
        t = _threading.Thread(target=self._restore_worker, args=(zip_path,))
        t.daemon = True
        self._restore_thread = t
        t.start()

    def _restore_worker(self, zip_path):
        # type: (str) -> None
        """The off-thread disk phase: wait for auto-backup, then merge the
        zip over the live tree.  Sets _restore_pending (for the main-thread
        reload) or restore_error, and clears is_restoring."""
        try:
            db = self._db
            if db is None or not db.is_open():
                return
            # Don't mutate the live tree while the auto-backup is zipping it.
            if not self._owner.auto.wait_until_idle():
                _cue_log("RESTORE-MARKERS: timed out waiting for auto backup")
                self.restore_error = ("Restore aborted: auto-backup is still "
                    "running.")
                return
            self._restore_count = restore_pieces(
                zip_path, self._owner._paths.original_root,
                self._owner._paths.game_id)
            self.restore_status = ("Restored {} files -- reloading..."
                ).format(self._restore_count)
            self._restore_pending = True
        except Exception as e:
            self.restore_error = "Restore failed: {}".format(e)
        finally:
            self.is_restoring = False

    def poll(self):
        # type: () -> None
        """Screen-timer hook: run the main-thread half of a finished restore
        (the in-memory reload) once the background disk phase is done.  Cheap
        no-op every other tick."""
        if self._restore_pending:
            self._finish_reload()

    def _finish_reload(self):
        # type: () -> None
        """Main-thread half of a finished restore.  Clears the pending flag,
        runs the marker reload callback, then stamps the final status."""
        self._restore_pending = False
        try:
            if self._reload_work is not None:
                self._reload_work(self._restore_count)
            self.restore_status = ("Restored {} files from backups/renpy_cue_backup.zip. "
                "Previous data saved to data_bak.").format(self._restore_count)
        except Exception as e:
            self.restore_error = "Restore reload failed: {}".format(e)


# =========================================================================
# CueBackupManager -- composite facade
# =========================================================================

class CueBackupManager(object):
    """Composite backup manager for the shared data tree.

    Owns the two backup flows as sub-managers: .auto (throttled background
    zipping of data/) and .manual (the user-driven backup/restore buttons).
    Holds the shared CuePaths identity and exposes the composite entry
    points the rest of the mod calls.
    """

    def __init__(self, paths):
        # type: (CuePaths) -> None
        self._paths = paths
        self.auto = CueAutoBackupManager(self)
        self.manual = CueManualBackupManager(self)
        self._db = None          # CueDatabase, injected by wire()

    def wire(self, db, reload_work, confirm_dialog):
        # type: (Any, Callable[[int], None], Any) -> None
        """Attach collaborators available only after full init: the open db
        (settings toggle + manual restore guard) and the marker reload
        callback."""
        self._db = db
        self.manual.wire(db, reload_work, confirm_dialog)

    @property
    def path(self):
        # type: () -> str
        """The real shared root (never an active import)."""
        return self._paths.original_root

    @property
    def game_id(self):
        # type: () -> str
        return self._paths.game_id

    def backups_root(self):
        # type: () -> str
        return self._paths.backups_dir

    # -- Auto (db.py writes -> maybe) --

    def maybe(self):
        # type: () -> None
        self.auto.maybe()

    def force_backup(self):
        # type: () -> None
        self.auto.force_backup()

    def wait_until_idle(self, timeout=10.0):
        # type: (float) -> bool
        return self.auto.wait_until_idle(timeout)

    def set_auto_backups(self, enabled):
        # type: (bool) -> None
        """Settings-page toggle for automatic backups; persisted to the shared
        config so the choice carries across every game."""
        db = self._db
        if db is not None:
            db.set_auto_backups(enabled)

    # -- Manual (UI buttons + screen timer) --

    def backup(self):
        # type: () -> None
        self.manual.backup()

    def restore(self):
        # type: () -> None
        self.manual.restore()

    def poll(self):
        # type: () -> None
        self.manual.poll()

    @property
    def is_backing_up(self):
        # type: () -> bool
        return self.manual.is_backing_up

    @property
    def backup_fraction(self):
        # type: () -> float
        return self.manual.backup_fraction

    @property
    def is_restoring(self):
        # type: () -> bool
        return self.manual.is_restoring

    @property
    def backup_status(self):
        # type: () -> str
        return self.manual.backup_status

    @property
    def backup_error(self):
        # type: () -> str
        return self.manual.backup_error

    @property
    def restore_status(self):
        # type: () -> str
        return self.manual.restore_status

    @property
    def restore_error(self):
        # type: () -> str
        return self.manual.restore_error
