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
    return os.path.normpath(os.path.join(base, "renpy_cue")).replace("\\", "/")


# ---------------------------------------------------------------------------
# Key sanitisation for filesystem safety
# ---------------------------------------------------------------------------
# Marker keys: {prefix}_{file}, dialogue appends _{hash} for the text.
#   v_anim_envy_bj3_ep10.json
#   d_bg anim_jade_insert_ep9 movie_a1b2c3d4.json
# Full key is stored in the JSON's "_key" field.

import hashlib as _hashlib

def _key_to_filename(key):
    # type: (str) -> str
    # Dialogue key: d_file__dialogue -> d_{file}_{hash}
    if key.startswith("d_"):
        sep = key.find("__")
        if sep != -1:
            file_part = key[2:sep]
            dlg_hash = _hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
            return "d_{}_{}.json".format(file_part, dlg_hash)
    # Other keys: just the key itself
    return key + ".json"


def _filename_to_key(filename):
    # type: (str) -> str
    """Fallback. The _key field in the JSON is authoritative."""
    return ""


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

    Markers are namespaced by game_id.  Presets are game-agnostic.
    """

    def __init__(self, path, game_id):
        # type: (str, str) -> None
        self._path = path          # root dir (e.g. %APPDATA%/renpy_cue)
        self._game_id = game_id
        self._open = False

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
        safe = name.replace("/", "_").replace("\\", "_")
        h = _hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self._preset_dir(preset_type),
                            "{}_{}.json".format(safe, h))

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
        for key, entry in markers.items():
            self._write_file_atomic(self._marker_path(key), key, entry)
        for name, entry in presets.items():
            self._write_file_atomic(self._preset_path("audio", name), name, entry)
        for name, entry in video_presets.items():
            self._write_file_atomic(self._preset_path("video", name), name, entry)

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

