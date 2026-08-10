# -*- coding: utf-8 -*-
# cue_lib/db.py -- SQLite-backed persistence for markers and presets.
#
# Replaces the monolithic cue_config.json blob with per-row writes so only
# changed data hits disk.  Markers and presets live in the DB; lightweight
# scalars (triggers_active, encode_mode, seamless_transition, disabled_files)
# stay on Ren'Py persistent.
#
# The DB file lives in a platform-standard application-data directory so
# multiple games can share one database (partitioned by config.save_directory).

import os
import json as _json
import time as _time
import sqlite3 as _sqlite3
import threading as _threading

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Platform path helpers
# ---------------------------------------------------------------------------

def _cue_get_shared_dir():
    # type: () -> str
    """Return the platform-standard shared directory for cue data.

    Respects the CUE_DB_DIR environment override.  Otherwise:
      Windows : %%APPDATA%%/renpy_cue
      macOS   : ~/Library/Application Support/renpy_cue
      Linux   : $XDG_DATA_HOME/renpy_cue or ~/.local/share/renpy_cue
    """
    import sys as _sys
    env = os.environ.get("CUE_DB_DIR", "")
    if env:
        return os.path.normpath(env)

    if _sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
    elif _sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get(
            "XDG_DATA_HOME",
            os.path.expanduser("~/.local/share"),
        )
    return os.path.normpath(os.path.join(base, "renpy_cue"))


# ---------------------------------------------------------------------------
# Python 2 unicode safety
# ---------------------------------------------------------------------------

def _to_str(obj):
    # type: (Any) -> Any
    """Recursively encode unicode keys and values to UTF-8 str (Python 2).

    In Python 3 this is a no-op -- str and unicode are the same type.
    In Python 2, json.loads returns unicode objects which will not compare
    equal to the native str keys used throughout the codebase.
    """
    try:
        unicode  # Python 2 only
    except NameError:
        return obj  # Python 3 -- str is already str

    if isinstance(obj, unicode):
        return obj.encode("utf-8")
    if isinstance(obj, str):
        return obj
    if hasattr(obj, "items") and hasattr(obj, "keys"):
        return {_to_str(k): _to_str(v) for k, v in obj.items()}
    if hasattr(obj, "__iter__"):
        return [_to_str(v) for v in obj]
    return obj


# =========================================================================
# CueDatabase
# =========================================================================

class CueDatabase(object):
    """SQLite-backed store for markers and presets.

    Markers are namespaced by config.save_directory (game_id).
    Presets are shared across all games (game-agnostic).
    """

    SCHEMA_VERSION = 1
    BACKUP_RETENTION_DAYS = 30

    def __init__(self, path, game_id):
        # type: (str, str) -> None
        self._path = path
        self._game_id = game_id
        self._conn = None  # type: Optional[_sqlite3.Connection]
        self._lock = _threading.Lock()
        self._last_backup_date = ""  # type: str

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self):
        # type: () -> None
        """Open the database (creating it if necessary), enable PRAGMAs,
        and create tables."""
        try:
            _dir = os.path.dirname(self._path)
            if _dir and not os.path.isdir(_dir):
                os.makedirs(_dir)
        except Exception:
            pass

        self._conn = _sqlite3.connect(self._path)
        self._conn.row_factory = _sqlite3.Row
        try:
            self._conn.execute("PRAGMA busy_timeout = 10000")
        except Exception:
            pass
        try:
            self._conn.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            pass

        self._create_tables()
        self._maybe_recover()

    def close(self):
        # type: () -> None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def is_open(self):
        # type: () -> bool
        return self._conn is not None

    @property
    def path(self):
        # type: () -> str
        return self._path

    @property
    def game_id(self):
        # type: () -> str
        return self._game_id

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self):
        # type: () -> None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS markers (
                game_id    TEXT NOT NULL,
                marker_key TEXT NOT NULL,
                replay_id  TEXT,
                data       TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (game_id, marker_key)
            );

            CREATE TABLE IF NOT EXISTS presets (
                preset_type TEXT NOT NULL,
                name        TEXT NOT NULL,
                data        TEXT NOT NULL,
                updated_at  INTEGER NOT NULL,
                PRIMARY KEY (preset_type, name)
            );
        """)
        self._conn.commit()

    def _maybe_recover(self):
        # type: () -> None
        """If the DB is corrupt, quarantine it and recreate."""
        try:
            self._conn.execute("SELECT count(*) FROM markers")
        except _sqlite3.DatabaseError:
            self._quarantine()
            self._conn = _sqlite3.connect(self._path)
            self._conn.row_factory = _sqlite3.Row
            self._create_tables()

    def _quarantine(self):
        # type: () -> None
        """Rename the corrupt DB file out of the way."""
        import shutil as _shutil
        ts = int(_time.time())
        try:
            self._conn.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            src = self._path + suffix
            if os.path.isfile(src):
                dst = "{}.corrupt.{}".format(src, ts)
                try:
                    _shutil.move(src, dst)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Freshness / migration
    # ------------------------------------------------------------------

    def is_fresh(self):
        # type: () -> bool
        """True if this game_id has no marker rows yet."""
        row = self._conn.execute(
            "SELECT count(*) AS cnt FROM markers WHERE game_id = ?",
            (self._game_id,),
        ).fetchone()
        return row is not None and row["cnt"] == 0

    def migrate_markers_and_presets(self, markers, presets, video_presets):
        # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any]) -> None
        """Bulk-import markers and presets from a legacy dict."""
        now = int(_time.time())
        with self._lock:
            with self._conn:
                for key, entry in markers.items():
                    self._upsert_marker(key, entry, now)
                for name, entry in presets.items():
                    self._upsert_preset("audio", name, entry, now)
                for name, entry in video_presets.items():
                    self._upsert_preset("video", name, entry, now)

    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------

    def load_markers(self):
        # type: () -> Dict[str, Any]
        """Return {marker_key: MarkerEntry} for this game_id."""
        rows = self._conn.execute(
            "SELECT marker_key, replay_id, data FROM markers WHERE game_id = ?",
            (self._game_id,),
        ).fetchall()
        result = {}
        for row in rows:
            entry = _json.loads(row["data"])
            entry = _to_str(entry)
            if row["replay_id"]:
                entry["replay"] = _to_str(row["replay_id"])
            result[_to_str(row["marker_key"])] = entry
        return result

    def save_marker(self, key, entry):
        # type: (str, Any) -> None
        """INSERT OR REPLACE one marker row."""
        with self._lock:
            self._upsert_marker(key, entry, int(_time.time()))

    def delete_marker(self, key):
        # type: (str) -> None
        """DELETE one marker row."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM markers WHERE game_id = ? AND marker_key = ?",
                (self._game_id, key),
            )
            self._conn.commit()

    def _upsert_marker(self, key, entry, ts):
        # type: (str, Any, int) -> None
        replay_id = entry.get("replay") or None
        data = _json.dumps(entry, sort_keys=True)
        self._conn.execute(
            "INSERT OR REPLACE INTO markers "
            "(game_id, marker_key, replay_id, data, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self._game_id, key, replay_id, data, ts),
        )

    # ------------------------------------------------------------------
    # Presets (game-agnostic -- shared across all games)
    # ------------------------------------------------------------------

    def load_presets(self):
        # type: () -> Tuple[Dict[str, Any], Dict[str, Any]]
        """Return (audio_presets, video_presets) -- shared across all games."""
        rows = self._conn.execute(
            "SELECT preset_type, name, data FROM presets"
        ).fetchall()
        audio = {}
        video = {}
        for row in rows:
            entry = _to_str(_json.loads(row["data"]))
            name = _to_str(row["name"])
            if row["preset_type"] == "video":
                video[name] = entry
            else:
                audio[name] = entry
        return audio, video

    def save_preset(self, preset_type, name, data):
        # type: (str, str, Any) -> None
        """INSERT OR REPLACE one preset row."""
        with self._lock:
            self._upsert_preset(preset_type, name, data, int(_time.time()))

    def delete_preset(self, preset_type, name):
        # type: (str, str) -> None
        """DELETE one preset row."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM presets WHERE preset_type = ? AND name = ?",
                (preset_type, name),
            )
            self._conn.commit()

    def _upsert_preset(self, preset_type, name, data, ts):
        # type: (str, str, Any, int) -> None
        json_data = _json.dumps(data, sort_keys=True)
        self._conn.execute(
            "INSERT OR REPLACE INTO presets (preset_type, name, data, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (preset_type, name, json_data, ts),
        )

    # ------------------------------------------------------------------
    # Daily backups (JSON format, 30-day retention)
    # ------------------------------------------------------------------

    def maybe_backup(self, markers, presets, video_presets):
        # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any]) -> None
        """Write a daily JSON backup to {shared_dir}/backups/.

        Throttled by the existing 300-second timer in CueMarkerManager.
        Only writes once per calendar day.
        """
        today = _time.strftime("%Y-%m-%d")
        if today == self._last_backup_date:
            return
        self._last_backup_date = today

        backup_dir = os.path.join(os.path.dirname(self._path), "backups")
        try:
            if not os.path.isdir(backup_dir):
                os.makedirs(backup_dir)
        except Exception:
            return

        dump_path = os.path.join(backup_dir, "{}.json".format(today))

        from cue_lib.util import _cue_unwrap_persistent
        data = {
            "markers": _cue_unwrap_persistent(markers),
            "presets": _cue_unwrap_persistent(presets),
            "video_presets": _cue_unwrap_persistent(video_presets),
            "_format": "daily_backup_v1",
        }
        try:
            with open(dump_path, "w") as f:
                _json.dump(data, f, indent=2, sort_keys=True)
            self._prune_backups(backup_dir)
        except Exception:
            pass

    def _prune_backups(self, backup_dir):
        # type: (str) -> None
        """Remove backup files older than BACKUP_RETENTION_DAYS."""
        cutoff = _time.time() - (self.BACKUP_RETENTION_DAYS * 86400)
        try:
            for name in os.listdir(backup_dir):
                if not name.endswith(".json"):
                    continue
                fpath = os.path.join(backup_dir, name)
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                except Exception:
                    pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _cue_open_database(game_id):
    # type: (str) -> CueDatabase
    """Create and open a CueDatabase at the platform-standard path.

    Falls back to a per-game path if the shared directory is not writable.
    """
    import renpy.config as _config
    shared = _cue_get_shared_dir()
    db_path = os.path.join(shared, "cue.db")
    db = CueDatabase(db_path, game_id)
    try:
        db.open()
    except Exception:
        gamedir = _config.gamedir
        fallback_dir = os.path.join(gamedir, "renpy_cue")
        fallback_path = os.path.join(fallback_dir, "cue.db")
        try:
            if not os.path.isdir(fallback_dir):
                os.makedirs(fallback_dir)
        except Exception:
            pass
        db = CueDatabase(fallback_path, game_id)
        try:
            db.open()
        except Exception:
            pass
    return db
