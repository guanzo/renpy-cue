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
import tempfile as _tempfile

import renpy.python as _renpy_python

from cue_lib.util import _cue_log, _cue_replace_file, _to_str
from cue_lib.backup import CueBackupManager
from cue_lib.constants import (
    CUE_HASH_TRUNC_LEN,
    CUE_IMG_KEY_PREFIX,
    CUE_LOOP_KEY_PREFIX,
    CUE_DLG_KEY_PREFIX,
    CUE_VID_KEY_PREFIX,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]


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


def _is_marker_filename(name):
    # type: (str) -> bool
    """True if `name` is a marker file: a .json carrying a key type prefix.

    Marker filenames always start with one of the type prefixes (i_, l_, d_,
    v_) -- see _key_to_filename().  Whitelisting keeps non-marker JSON that
    shares the marker dir from being swept up as a marker by load_markers().
    The music_triggers/ subdir is excluded because load_markers() only lists
    direct children of the marker dir."""
    return name.endswith(".json") and name.startswith(
        (CUE_IMG_KEY_PREFIX, CUE_LOOP_KEY_PREFIX, CUE_DLG_KEY_PREFIX, CUE_VID_KEY_PREFIX)
    )


def _atomic_json_write(fpath, data, indent=None):
    # type: (str, Any, Optional[int]) -> None
    """Write `data` as JSON to fpath atomically."""
    tmpfd, tmp = _tempfile.mkstemp(dir=os.path.dirname(fpath), prefix=".", suffix=".tmp")
    try:
        with os.fdopen(tmpfd, "w") as _f:
            _json.dump(data, _f, sort_keys=True, indent=indent)
        _cue_replace_file(tmp, fpath)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


# =========================================================================
# CueDatabase
# =========================================================================


class CueDatabase(_renpy_python.NoRollback):
    """File-backed store for markers, presets, and speed-variant videos.

    Directory layout:
        {root}/data/markers/{game_id}/              -- one .json file per marker key
        {root}/data/markers/{game_id}/music_triggers/  -- one .json per replay (trigger log)
        {root}/data/presets/audio/                  -- one .json file per audio preset
        {root}/data/presets/video/                  -- one .json file per video preset
        {root}/data/presets/music/                  -- one .json file per music preset
        {root}/video/{game_id}/                     -- speed-variant video files

    Markers and videos are namespaced by game_id.  Presets are game-agnostic.
    """

    def __init__(self, paths, backup=None):
        # type: (CuePaths, Optional[CueBackupManager]) -> None
        self.paths = paths  # the one CuePaths (shared with _cue for the live db)
        self._open = False
        # The backup manager is a top-level _cue manager, built in the init -900
        # wiring block and injected here; the db drives it after writes and seeds
        # its switch from config.  Callers without a composite (probes, tests)
        # let the db build its own.
        self._backup = backup if backup is not None else CueBackupManager(paths)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self):
        # type: () -> None
        """Ensure directory structure exists."""
        for _dir in [
            self.paths.marker_dir,
            self.paths.audio_preset_dir,
            self.paths.video_preset_dir,
            self.paths.music_preset_dir,
            self.paths.intensity_preset_dir,
            self.paths.video_dir,
            self.paths.music_dir,
            self.paths.audio_dir,
            self.paths.imports_dir,
            self.paths.exports_dir,
        ]:
            if not os.path.isdir(_dir):
                try:
                    os.makedirs(_dir)
                except Exception:
                    raise
        self._open = True
        # The auto-backup switch lives in shared config so it carries across
        # every game; default to on when no config exists yet.
        self._backup.auto.enabled = self.load_shared_config().get("auto_backups", True)

    def close(self):
        # type: () -> None
        self._open = False

    def is_open(self):
        # type: () -> bool
        return self._open

    def _preset_dir(self, preset_type):
        # type: (str) -> str
        if preset_type == "audio":
            return self.paths.audio_preset_dir
        if preset_type == "music":
            return self.paths.music_preset_dir
        if preset_type == "intensity":
            return self.paths.intensity_preset_dir
        return self.paths.video_preset_dir

    def _marker_path(self, key):
        # type: (str) -> str
        return os.path.join(self.paths.marker_dir, _key_to_filename(key))

    def _preset_path(self, preset_type, name):
        # type: (str, str) -> str
        safe = name.replace("/", "_").replace("\\", "_")
        h = _hashlib.sha1(name.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
        return os.path.join(self._preset_dir(preset_type), "{}_{}.json".format(safe, h))

    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------

    def load_markers(self):
        # type: () -> Dict[str, Any]
        """Return {marker_key: MarkerEntry} for this game_id."""
        result = {}
        mdir = self.paths.marker_dir
        try:
            names = os.listdir(mdir)
        except Exception:
            _cue_log("DB-LOAD: listdir failed for {}".format(mdir))
            return result
        for name in names:
            if not _is_marker_filename(name):
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
        self._backup.maybe()

    # ------------------------------------------------------------------
    # Presets (game-agnostic -- shared across all games)
    # ------------------------------------------------------------------

    def load_presets(self, preset_type):
        # type: (str) -> Dict[str, Any]
        """Return {name: preset data} for one preset kind (audio | video |
        music | intensity)."""
        return self._load_preset_dir(preset_type)

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
        self._backup.maybe()

    def preset_file_matches(self, preset_type, name, expected):
        # type: (str, str, Any) -> bool
        """True if the on-disk preset still holds exactly `expected`,
        ignoring the internal _key field. Guards deletion against a preset
        another game modified or reloaded after we captured it."""
        fpath = self._preset_path(preset_type, name)
        on_disk = self._read_file(fpath)
        if not isinstance(on_disk, dict):
            return False
        on_disk = dict(on_disk)
        on_disk.pop("_key", None)
        exp = dict(expected)
        exp.pop("_key", None)
        return _to_str(on_disk) == _to_str(exp)

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
        _atomic_json_write(fpath, entry)

    def _write_entry(self, fpath, key, data):
        # type: (str, str, Any) -> None
        entry = dict(data)
        entry["_key"] = key
        self._write_file(fpath, entry)
        self._backup.maybe()

    # ------------------------------------------------------------------
    # Shared config -- lightweight cross-game settings
    # ------------------------------------------------------------------

    def load_shared_config(self):
        # type: () -> Dict[str, Any]
        """Load the shared config dict. Returns {} if the file does not exist."""
        fpath = self.paths.shared_config_path
        if not os.path.isfile(fpath):
            return {}
        try:
            with open(fpath, "r") as f:
                return _to_str(_json.load(f))
        except Exception:
            _cue_log("SHARED-CONFIG: load failed for {}".format(fpath))
            return {}

    def save_shared_config(self, data):
        # type: (Dict[str, Any]) -> None
        """Write the shared config dict."""
        fpath = self.paths.shared_config_path
        dpath = os.path.dirname(fpath)
        try:
            if not os.path.isdir(dpath):
                os.makedirs(dpath)
            _atomic_json_write(fpath, data, indent=2)
        except Exception:
            _cue_log("SHARED-CONFIG: save failed for {}".format(fpath))
        self._backup.maybe()

    def update_shared_config(self, data):
        # type: (Dict[str, Any]) -> None
        """Merge data into the shared config and save."""
        config = self.load_shared_config()
        config.update(data)
        self.save_shared_config(config)

    def set_auto_backups(self, enabled):
        # type: (bool) -> None
        """Turn automatic backups on/off; persists to cue_config.json."""
        self._backup.auto.enabled = enabled
        self.update_shared_config({"auto_backups": enabled})

    # ------------------------------------------------------------------
    # Default music triggers -- per-replay log of the original game's music
    # ------------------------------------------------------------------
    # Shape: {replay_label: [ {"key_before": ..., "filepaths": [...],
    # "key_after": ...}, ... ]}.  key_before = scene at the play call
    # (deterministic trigger); key_after = settled scene the user sees.
    # Stored one file per replay under markers/{game_id}/music_triggers/,
    # each file holding that replay's bare trigger list.  The subdir is not
    # a direct .json child of the marker dir, so load_markers() never sweeps
    # it up as a marker.  Pre-rename files (single "filepath" str) are migrated
    # by .local/scripts/migrate_cue_data.py, not at load.

    def load_default_music_triggers(self):
        # type: () -> Dict[str, Any]
        """Load the default music trigger log. Returns {} if absent."""
        dpath = self.paths.music_trigger_dir
        if not os.path.isdir(dpath):
            return {}
        result = {}
        try:
            names = os.listdir(dpath)
        except Exception:
            return result
        for name in names:
            if not name.endswith(".json"):
                continue
            replay_id = name[: -len(".json")]
            fpath = os.path.join(dpath, name)
            try:
                with open(fpath, "r") as f:
                    items = _json.load(f)
            except Exception:
                _cue_log("MUSIC-TRIGGERS: load failed for {}".format(fpath))
                continue
            if not isinstance(items, list):
                _cue_log("MUSIC-TRIGGERS: skipped non-list file {}".format(name))
                continue
            result[replay_id] = items
        return result

    def update_default_music_triggers(self, replay_id, key_before, paths, key_after=None):
        # type: (str, str, List[str], Optional[str]) -> None
        """Record one default music trigger for a replay.

        One entry per scene (key_before) per replay: re-read that replay's
        file from disk, update the matching entry in place (or append), then
        resave -- a write touches only its own file, so unrelated replays
        are never clobbered by a stale in-memory copy.

        `paths` is the full scripted file list (a `play music [a, b]` cycle
        keeps both files).  `key_before` is the scene on screen at the
        `play music` call (the deterministic trigger); `key_after` is the
        settled scene the user sees, captured once the scene batch lands
        (None until then).
        """
        fpath = self.paths.music_trigger_path(replay_id)
        items = []
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r") as f:
                    items = _json.load(f)
            except Exception:
                _cue_log("MUSIC-TRIGGERS: load failed for {}".format(fpath))
        if not isinstance(items, list):
            items = []
        for item in items:
            if item.get("key_before") == key_before:
                item["key_before"] = key_before
                item["filepaths"] = paths
                if key_after is not None:
                    item["key_after"] = key_after
                break
        else:
            entry = {"key_before": key_before, "filepaths": paths}
            if key_after is not None:
                entry["key_after"] = key_after
            items.append(entry)
        dpath = os.path.dirname(fpath)
        try:
            if not os.path.isdir(dpath):
                os.makedirs(dpath)
            _atomic_json_write(fpath, items, indent=2)
        except Exception:
            _cue_log("MUSIC-TRIGGERS: save failed for {}".format(fpath))
