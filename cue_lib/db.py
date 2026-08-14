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

from cue_lib.util import _cue_log, _to_str
from cue_lib.backup import CueBackupManager

# Number of characters to keep from a SHA1 hex digest for file naming.
CUE_HASH_TRUNC_LEN = 8

# Filename for the per-replay default music trigger log, stored under the
# markers/{game_id}/music/ subdir.
CUE_DEFAULT_MUSIC_TRIGGERS_FILENAME = "default_music_triggers.json"

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


# =========================================================================
# CueDatabase
# =========================================================================

class CueDatabase(object):
    """File-backed store for markers, presets, and speed-variant videos.

    Directory layout:
        {root}/data/markers/{game_id}/              -- one .json file per marker key
        {root}/data/markers/{game_id}/music/        -- default music triggers file
        {root}/data/presets/audio/                  -- one .json file per audio preset
        {root}/data/presets/video/                  -- one .json file per video preset
        {root}/video/{game_id}/                     -- speed-variant video files

    Markers and videos are namespaced by game_id.  Presets are game-agnostic.
    """

    def __init__(self, paths):
        # type: (CuePaths) -> None
        self.paths = paths         # the one CuePaths (shared with _cue for the live db)
        self._open = False
        self._backup = CueBackupManager(paths.root, paths.game_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self):
        # type: () -> None
        """Ensure directory structure exists."""
        for _dir in [
            self.paths.marker_dir,
            self.paths.music_triggers_dir,
            self.paths.audio_preset_dir,
            self.paths.video_preset_dir,
            self.paths.video_dir,
            self.paths.music_dir,
        ]:
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

    def _preset_dir(self, preset_type):
        # type: (str) -> str
        if preset_type == "audio":
            return self.paths.audio_preset_dir
        return self.paths.video_preset_dir

    def _marker_path(self, key):
        # type: (str) -> str
        return os.path.join(self.paths.marker_dir, _key_to_filename(key))

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
            for _name in os.listdir(self.paths.marker_dir):
                if _name.endswith(".json"):
                    return False
        except Exception:
            _cue_log("DB-FRESH: listdir failed for {}".format(self.paths.marker_dir))
        return True

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
        self._backup.maybe()

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
        with open(fpath, "w") as f:
            _json.dump(entry, f, sort_keys=True)

    def _write_entry(self, fpath, key, data):
        # type: (str, str, Any) -> None
        entry = dict(data)
        entry["_key"] = key
        self._write_file(fpath, entry)
        self._backup.maybe()

    # ------------------------------------------------------------------
    # Shared config -- lightweight cross-game settings
    # ------------------------------------------------------------------

    def _shared_config_path(self):
        # type: () -> str
        return self.paths.shared_config_path

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
        self._backup.maybe()

    def update_shared_config(self, data):
        # type: (Dict[str, Any]) -> None
        """Merge data into the shared config and save."""
        config = self.load_shared_config()
        config.update(data)
        self.save_shared_config(config)

    # ------------------------------------------------------------------
    # Default music triggers -- per-replay log of the original game's music
    # ------------------------------------------------------------------
    # Shape: {replay_label: [ {"key_before": ..., "filepath": ...,
    # "key_after": ...}, ... ]}.  key_before = scene at the play call
    # (deterministic trigger); key_after = settled scene the user sees.
    # Lives in the music/ subdir of the marker dir so load_markers() (which
    # only scans direct children for .json) never sweeps it up as a marker.

    def _music_triggers_path(self):
        # type: () -> str
        return os.path.join(self.paths.music_triggers_dir, CUE_DEFAULT_MUSIC_TRIGGERS_FILENAME)

    def load_default_music_triggers(self):
        # type: () -> Dict[str, Any]
        """Load the default music trigger log. Returns {} if absent."""
        fpath = self._music_triggers_path()
        if not os.path.isfile(fpath):
            return {}
        try:
            with open(fpath, "r") as f:
                return _json.load(f)
        except Exception:
            _cue_log("MUSIC-TRIGGERS: load failed for {}".format(fpath))
            return {}

    def save_default_music_triggers(self, data):
        # type: (Dict[str, Any]) -> None
        """Write the whole default music trigger log."""
        fpath = self._music_triggers_path()
        dpath = os.path.dirname(fpath)
        try:
            if not os.path.isdir(dpath):
                os.makedirs(dpath)
            with open(fpath, "w") as f:
                _json.dump(data, f, indent=2, sort_keys=True)
        except Exception:
            _cue_log("MUSIC-TRIGGERS: save failed for {}".format(fpath))

    def update_default_music_triggers(self, replay_id, key_before, path, key_after=None):
        # type: (str, str, str, Optional[str]) -> None
        """Record one default music trigger for a replay.

        One entry per scene (key_before) per replay: re-read the log from
        disk, update the matching entry in place (or append), then resave --
        so unrelated replay entries are never clobbered by a stale in-memory
        copy.

        `key_before` is the scene on screen at the `play music` call (the
        deterministic trigger); `key_after` is the settled scene the user
        sees, captured once the scene batch lands (None until then).
        """
        data = self.load_default_music_triggers()
        items = data.setdefault(replay_id, [])
        for item in items:
            if item.get("key_before") == key_before:
                item["key_before"] = key_before
                item["filepath"] = path
                if key_after is not None:
                    item["key_after"] = key_after
                break
        else:
            entry = {"key_before": key_before, "filepath": path}
            if key_after is not None:
                entry["key_after"] = key_after
            items.append(entry)
        self.save_default_music_triggers(data)

