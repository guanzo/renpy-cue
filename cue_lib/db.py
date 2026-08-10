# -*- coding: utf-8 -*-
# cue_lib/db.py -- File-backed persistence for markers and presets.
#
# Each marker entry is one JSON file under data/markers/{game_id}/.
# Each preset is one JSON file under data/presets/{preset_type}/.
#
# Replaces the monolithic cue_config.json with per-entity writes so only
# changed data hits disk.  Lightweight scalars (triggers_active, encode_mode,
# seamless_transition, disabled_files) stay on Ren'Py persistent.
#
# Pure Python stdlib -- no C extensions.  Works on any Ren'Py build.

import os
import json as _json
import time as _time
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
# Key sanitisation for filesystem safety
# ---------------------------------------------------------------------------
# Marker keys contain ':' and dialogue text (e.g. "d:file:hello world").
# ':' and unsafe chars are replaced with '_' for filesystem safety.
# Full key is stored in the JSON's "_key" field.

_MAX_LEN = 80
_UNSAFE = set('<>:"/\\|?*')


def _key_to_filename(key):
    # type: (str) -> str
    safe = key.replace(":", "_")
    safe = "".join(c for c in safe if c not in _UNSAFE)
    if len(safe) > _MAX_LEN:
        safe = safe[:_MAX_LEN]
    return safe + ".json"


def _filename_to_key(filename):
    # type: (str) -> str
    """Fallback key reconstruction from filename. The _key field in the
    JSON is authoritative -- this is only used if _key is missing."""
    if filename.endswith(".json"):
        filename = filename[:-5]
    return filename.replace("_", ":")


# ---------------------------------------------------------------------------
# Python 2 unicode safety
# ---------------------------------------------------------------------------

def _to_str(obj):
    # type: (Any) -> Any
    """Recursively encode unicode keys and values to UTF-8 str (Python 2).

    In Python 3 this is a no-op -- str and unicode are the same type.
    """
    try:
        unicode  # Python 2 only
    except NameError:
        return obj

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
    """File-backed store for markers and presets.

    Directory layout:
        {root}/data/markers/{game_id}/  -- one .json file per marker key
        {root}/data/presets/audio/      -- one .json file per audio preset
        {root}/data/presets/video/      -- one .json file per video preset
        {root}/backups/                 -- daily full-dump JSON snapshots

    Markers are namespaced by game_id.  Presets are game-agnostic.
    """

    BACKUP_RETENTION_DAYS = 30

    def __init__(self, path, game_id):
        # type: (str, str) -> None
        self._path = path          # root dir (e.g. %APPDATA%/renpy_cue)
        self._game_id = game_id
        self._open = False
        self._last_backup_date = ""  # type: str

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self):
        # type: () -> None
        """Ensure directory structure exists."""
        for sub in [
            os.path.join("data", "markers", self._game_id),
            os.path.join("data", "presets", "audio"),
            os.path.join("data", "presets", "video"),
        ]:
            _dir = os.path.join(self._path, sub)
            if not os.path.isdir(_dir):
                try:
                    os.makedirs(_dir)
                except Exception:
                    raise
        self._open = True

    def close(self):
        # type: () -> None
        self._open = False

    def is_open(self):
        # type: () -> bool
        return self._open

    @property
    def path(self):
        # type: () -> str
        return self._path

    @property
    def game_id(self):
        # type: () -> str
        return self._game_id

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _marker_dir(self):
        # type: () -> str
        return os.path.join(self._path, "data", "markers", self._game_id)

    def _preset_dir(self, preset_type):
        # type: (str) -> str
        return os.path.join(self._path, "data", "presets", preset_type)

    def _marker_path(self, key):
        # type: (str) -> str
        return os.path.join(self._marker_dir(), _key_to_filename(key))

    def _preset_path(self, preset_type, name):
        # type: (str, str) -> str
        safe = name.replace(":", "_")
        safe = "".join(c for c in safe if c not in _UNSAFE)
        if len(safe) > _MAX_LEN:
            safe = safe[:_MAX_LEN]
        return os.path.join(self._preset_dir(preset_type), safe + ".json")

    # ------------------------------------------------------------------
    # Freshness / migration
    # ------------------------------------------------------------------

    def is_fresh(self):
        # type: () -> bool
        """True if this game_id has no marker files yet."""
        try:
            for _name in os.listdir(self._marker_dir()):
                if _name.endswith(".json"):
                    return False
        except Exception:
            pass
        return True

    def migrate_markers_and_presets(self, markers, presets, video_presets):
        # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any]) -> None
        """Bulk-write markers and presets from a legacy dict (one-time migration)."""
        # We intentionally avoid atomic writes here -- this is a bulk import.
        for key, entry in markers.items():
            self._write_file(self._marker_path(key), entry)
        for name, entry in presets.items():
            self._write_file(self._preset_path("audio", name), entry)
        for name, entry in video_presets.items():
            self._write_file(self._preset_path("video", name), entry)

    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------

    def load_markers(self):
        # type: () -> Dict[str, Any]
        """Return {marker_key: MarkerEntry} for this game_id."""
        result = {}
        mdir = self._marker_dir()
        try:
            names = os.listdir(mdir)
        except Exception:
            return result
        for name in names:
            if not name.endswith(".json"):
                continue
            fpath = os.path.join(mdir, name)
            entry = self._read_file(fpath)
            if entry is None:
                continue
            entry = _to_str(entry)
            # Reconstruct the real key from the stored entry, falling back
            # to the filename heuristic.
            key = _to_str(entry.get("_key", _filename_to_key(name)))
            if "replay_id" in entry:
                entry["replay"] = _to_str(entry.pop("replay_id"))
            result[key] = entry
        return result

    def save_marker(self, key, entry):
        # type: (str, Any) -> None
        """Write one marker to its JSON file."""
        self._write_file_atomic(self._marker_path(key), key, entry)

    def delete_marker(self, key):
        # type: (str) -> None
        """Remove one marker JSON file."""
        fpath = self._marker_path(key)
        try:
            os.remove(fpath)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Presets (game-agnostic -- shared across all games)
    # ------------------------------------------------------------------

    def load_presets(self):
        # type: () -> Tuple[Dict[str, Any], Dict[str, Any]]
        """Return (audio_presets, video_presets)."""
        audio = self._load_preset_dir("audio")
        video = self._load_preset_dir("video")
        return audio, video

    def _load_preset_dir(self, preset_type):
        # type: (str) -> Dict[str, Any]
        result = {}
        pdir = self._preset_dir(preset_type)
        try:
            names = os.listdir(pdir)
        except Exception:
            return result
        for name in names:
            if not name.endswith(".json"):
                continue
            fpath = os.path.join(pdir, name)
            entry = self._read_file(fpath)
            if entry is None:
                continue
            entry = _to_str(entry)
            preset_name = _to_str(entry.get("_key", _filename_to_key(name)))
            result[preset_name] = entry
        return result

    def save_preset(self, preset_type, name, data):
        # type: (str, str, Any) -> None
        """Write one preset to its JSON file."""
        fpath = self._preset_path(preset_type, name)
        self._write_file_atomic(fpath, name, data)

    def delete_preset(self, preset_type, name):
        # type: (str, str) -> None
        """Remove one preset JSON file."""
        fpath = self._preset_path(preset_type, name)
        try:
            os.remove(fpath)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Low-level file I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _read_file(fpath):
        # type: (str) -> Optional[Any]
        try:
            with open(fpath, "r") as f:
                return _json.load(f)
        except Exception:
            return None

    @staticmethod
    def _write_file(fpath, entry):
        # type: (str, Any) -> None
        with open(fpath, "w") as f:
            _json.dump(entry, f, sort_keys=True)

    def _write_file_atomic(self, fpath, key, data):
        # type: (str, str, Any) -> None
        """Write via temp file + rename for atomicity."""
        # Store the original key so it can be recovered on load
        entry = dict(data)
        if "_key" not in entry:
            entry["_key"] = key
        # Hoist replay into its own field for the stored record
        if "replay" in entry:
            entry["replay_id"] = entry.pop("replay")

        tmp = fpath + ".tmp"
        try:
            with open(tmp, "w") as f:
                _json.dump(entry, f, sort_keys=True)
            os.rename(tmp, fpath)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Daily backups (JSON format, 30-day retention)
    # ------------------------------------------------------------------

    def maybe_backup(self, markers, presets, video_presets):
        # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any]) -> None
        """Write a daily JSON backup to {root}/backups/.

        Throttled by the existing 300-second timer in CueMarkerManager.
        Only writes once per calendar day.
        """
        today = _time.strftime("%Y-%m-%d")
        if today == self._last_backup_date:
            return
        self._last_backup_date = today

        backup_dir = os.path.join(self._path, "backups")
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
    db = CueDatabase(shared, game_id)
    try:
        db.open()
    except Exception:
        gamedir = _config.gamedir
        fallback = os.path.join(gamedir, "renpy_cue", "cue_data")
        db = CueDatabase(fallback, game_id)
        try:
            db.open()
        except Exception:
            pass
    return db
