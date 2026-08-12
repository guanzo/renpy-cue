# -*- coding: utf-8 -*-
# cue_lib/db.py -- File-backed persistence for markers and presets.
#
# Each marker entry is one JSON file under data/markers/{game_id}/.
# Each preset is one JSON file under data/presets/{preset_type}/.
#
# Replaces the monolithic cue_config.json with per-entity writes so only
# changed data hits disk.  Lightweight scalars (triggers_active, encode_mode,
# seamless_transition, remove_audio) stay on Ren'Py persistent.
# disabled_files lives in shared config at data/cue_config.json.
#
# Pure Python stdlib -- no C extensions.  Works on any Ren'Py build.

import os
import json as _json

from cue_lib.util import _cue_log

# Number of characters to keep from a SHA1 hex digest for file naming.
CUE_HASH_TRUNC_LEN = 8

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]


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
    # Dialogue key: d_file__dialogue or d_file|dialogue -> d_{file}_{hash}
    if key.startswith("d_"):
        sep = key.find("__")
        if sep == -1:
            sep = key.find("|")
        if sep != -1:
            file_part = key[2:sep]
            dlg_hash = _hashlib.sha1(key.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
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
        unicode  # pyright: ignore[reportUndefinedVariable, reportUnusedExpression]
    except NameError:
        return obj

    if isinstance(obj, unicode):  # pyright: ignore[reportUndefinedVariable]
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
    """File-backed store for markers, presets, and speed-variant videos.

    Directory layout:
        {root}/data/markers/{game_id}/  -- one .json file per marker key
        {root}/data/presets/audio/      -- one .json file per audio preset
        {root}/data/presets/video/      -- one .json file per video preset
        {root}/video/{game_id}/         -- speed-variant video files

    Markers and videos are namespaced by game_id.  Presets are game-agnostic.
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
            os.path.join("video", self._game_id),
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

    @property
    def video_dir(self):
        # type: () -> str
        """Absolute path to the speed-variant video directory."""
        return os.path.join(self._path, "video", self._game_id).replace("\\", "/")

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
        h = _hashlib.sha1(name.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
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
            _cue_log("DB-FRESH: listdir failed for {}".format(self._marker_dir()))
        return True

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
            _cue_log("DB-LOAD: listdir failed for {}".format(mdir))
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
            result[key] = entry
        return result

    def save_marker(self, key, entry):
        # type: (str, Any) -> None
        """Write one marker to its JSON file."""
        self._write_entry(self._marker_path(key), key, entry)

    def delete_marker(self, key):
        # type: (str) -> None
        """Remove one marker JSON file."""
        fpath = self._marker_path(key)
        try:
            os.remove(fpath)
        except Exception:
            _cue_log("DB-DELETE: remove failed for {}".format(fpath))

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
            _cue_log("DB-LOAD: listdir failed for {}".format(pdir))
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
        self._write_entry(fpath, name, data)

    def delete_preset(self, preset_type, name):
        # type: (str, str) -> None
        """Remove one preset JSON file."""
        fpath = self._preset_path(preset_type, name)
        try:
            os.remove(fpath)
        except Exception:
            _cue_log("DB-DELETE: remove failed for {}".format(fpath))

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
            _cue_log("DB-READ: file read failed for {}".format(fpath))
            return None

    @staticmethod
    def _write_file(fpath, entry):
        # type: (str, Any) -> None
        with open(fpath, "w") as f:
            _json.dump(entry, f, sort_keys=True)

    def _write_entry(self, fpath, key, data):
        # type: (str, str, Any) -> None
        entry = dict(data)
        if "_key" not in entry:
            entry["_key"] = key
        self._write_file(fpath, entry)

    # ------------------------------------------------------------------
    # Shared config -- lightweight cross-game settings
    # ------------------------------------------------------------------

    def _shared_config_path(self):
        # type: () -> str
        return os.path.join(self._path, "data", "cue_config.json")

    def load_shared_config(self):
        # type: () -> Dict[str, Any]
        """Load the shared config dict. Returns {} if the file does not exist."""
        fpath = self._shared_config_path()
        if not os.path.isfile(fpath):
            return {}
        try:
            with open(fpath, "r") as f:
                return _json.load(f)
        except Exception:
            _cue_log("SHARED-CONFIG: load failed for {}".format(fpath))
            return {}

    def save_shared_config(self, data):
        # type: (Dict[str, Any]) -> None
        """Write the shared config dict."""
        fpath = self._shared_config_path()
        dpath = os.path.dirname(fpath)
        try:
            if not os.path.isdir(dpath):
                os.makedirs(dpath)
            with open(fpath, "w") as f:
                _json.dump(data, f, indent=2, sort_keys=True)
        except Exception:
            _cue_log("SHARED-CONFIG: save failed for {}".format(fpath))

    def update_shared_config(self, data):
        # type: (Dict[str, Any]) -> None
        """Merge data into the shared config and save."""
        config = self.load_shared_config()
        config.update(data)
        self.save_shared_config(config)

