# -*- coding: utf-8 -*-
# CuePresetStore -- the preset data leaf: audio + video presets shared across
# games.
#
# Owns the audio/video preset dicts and the session-created preset set, plus
# preset CRUD, folder-ref removal, reload, sanitize/migrate, and the preset
# branch of file-backed persistence.  Lives at _cue.presets (wired in
# cue_z.rpy) and is injected into CueMarkerStore for the two preset reads it
# makes (resolve_pool defaults, detach materialization).
#
# No module-level _cue reads: db + on_save come in via the constructor.

import copy as _copy

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.pool import CueAudioPreset, CueVideoPresetPool
from cue_lib.util import _cue_clean_pool_list, _cue_log, _cue_migrate_exclusive_pool

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import PoolDict, VideoPreset  # pyright: ignore[reportUnusedImport]
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]


class CuePresetStore(object):
    """Audio + video preset data with file-backed persistence.

    ``on_save`` is called once after every DB write; the coordinator uses it to
    capture an undo snapshot.  ``_session_created`` tracks presets created this
    session so a restore can tell them apart from presets loaded from disk
    (shared across games)."""

    def __init__(self, db, on_save=None):
        # type: (CueDatabase, Optional[Callable[[], None]]) -> None
        self._db = db
        self._on_save = on_save
        self._presets = {}
        self._video_presets = {}
        # ("audio"|"video", name) -- presets created this session
        self._session_created = set()

    # -- audio presets --

    def create_preset(self, name, pool_dict):
        # type: (str, PoolDict) -> None
        self._presets[name] = _copy.deepcopy(pool_dict)
        self._session_created.add(("audio", name))
        self._db_save_preset(name)
        _cue_log(
            "CREATE-PRESET name={} files={} vol={:.1f}".format(
                name, len(pool_dict.get("files", [])), pool_dict.get("volume", CUE_VOLUME_DEFAULT)
            )
        )

    def delete_preset(self, name):
        # type: (str) -> None
        if name in self._presets:
            del self._presets[name]
            self._session_created.discard(("audio", name))
            self._db_save_preset(name)
            _cue_log("DELETE-PRESET name={}".format(name))

    def get_preset(self, name):
        # type: (str) -> Optional[PoolDict]
        return self._presets.get(name)

    def list_presets(self):
        # type: () -> List[str]
        return sorted(self._presets.keys())

    def audio(self, name):
        # type: (str) -> CueAudioPreset
        """Ephemeral view over one audio preset.  One view = one op; the view
        re-resolves the row from the live dict each call."""
        return CueAudioPreset(self, name)

    def preset_remove_file(self, name, file_path):
        # type: (str, str) -> None
        """Remove one ref from an audio preset via the ephemeral view (the
        single home for folder-ref expansion).  A saved preset can be empty,
        so nothing is pruned."""
        self.audio(name).remove_file(file_path)

    # -- video presets --

    def create_video_preset(self, name, entry, source_dur=0.0):
        # type: (str, Any, float) -> None
        """Save a video preset from a marker entry's pools.

        ``source_dur`` is the source video's duration, supplied by the
        coordinator (the store has no video dependency)."""
        pools = entry.get("pools", [])
        if not pools:
            return
        clean = []
        for pool in pools:
            if pool.get("time") is not None:
                clean.append(
                    {
                        "time": pool["time"],
                        "files": list(pool.get("files", [])),
                        "volume": pool.get("volume", CUE_VOLUME_DEFAULT),
                    }
                )
        if not clean:
            return
        clean.sort(key=lambda e: e["time"])
        self._video_presets[name] = {
            "pools": clean,
            "volume": entry.get("volume", CUE_VOLUME_DEFAULT),
            "source_duration": max(source_dur, 0.0),
        }
        self._session_created.add(("video", name))
        self._db_save_video_preset(name)
        _cue_log("CREATE-VIDEO-PRESET name={} markers={} dur={:.1f}".format(name, len(clean), source_dur))

    def delete_video_preset(self, name):
        # type: (str) -> None
        if name in self._video_presets:
            del self._video_presets[name]
            self._session_created.discard(("video", name))
            self._db_save_video_preset(name)
            _cue_log("DELETE-VIDEO-PRESET name={}".format(name))

    def get_video_preset(self, name):
        # type: (str) -> Optional[VideoPreset]
        return self._video_presets.get(name)

    def list_video_presets(self):
        # type: () -> List[str]
        return sorted(self._video_presets.keys())

    def video_pool(self, name, pool_index):
        # type: (str, int) -> CueVideoPresetPool
        """Ephemeral view over one pool row in a saved video preset.  One view
        = one op; the view re-resolves the row from the live dict each call."""
        return CueVideoPresetPool(self, name, pool_index)

    def remove_video_preset_pool(self, name, pool_index):
        # type: (str, int) -> None
        """Remove one pool from a video preset; a preset left with no pools is
        deleted (a saved video preset always has at least one pool)."""
        preset = self._video_presets.get(name)
        if preset is None:
            return
        pools = preset.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        del pools[pool_index]
        if not pools:
            self.delete_video_preset(name)
            return
        self._db_save_video_preset(name)
        _cue_log("REMOVE-VIDEO-POOL preset={} index={}".format(name, pool_index))

    def remove_video_preset_pool_file(self, name, pool_index, file_path):
        # type: (str, int, str) -> None
        """Remove one file from a pool in a saved video preset via the ephemeral
        view (the single home for folder-ref expansion)."""
        self.video_pool(name, pool_index).remove_file(file_path)

    # -- sanitize / migration passes --

    def _sanitize_video_presets(self):
        # type: () -> int
        total_stripped = 0
        for _, preset in list(self._video_presets.items()):
            pools = preset.get("pools")
            if not pools:
                continue
            clean, stripped = _cue_clean_pool_list(pools)
            if stripped:
                preset["pools"] = clean
                total_stripped += stripped
        return total_stripped

    def _migrate_preset_speed_mode_rename(self):
        # type: () -> None
        for preset in self._video_presets.values():
            if preset.get("speed_mode") == "sequence":
                preset["speed_mode"] = "multi"

    def _migrate_video_presets_to_pools(self):
        # type: () -> int
        presets_changed = 0
        for _, preset in list(self._video_presets.items()):
            if "timestamps" in preset:
                if "pools" not in preset:
                    preset["pools"] = preset.pop("timestamps")
                else:
                    del preset["timestamps"]
                presets_changed += 1
        return presets_changed

    def _migrate_preset_exclusive(self):
        # type: () -> int
        migrated = 0
        for preset in list(self._presets.values()):
            if _cue_migrate_exclusive_pool(preset):
                migrated += 1
        return migrated

    # -- persistence --

    def reload_presets(self):
        # type: () -> None
        """Re-read presets from the shared data store. Merges new/updated
        presets from disk (other games may have added them). Never deletes."""
        db = self._db
        if db is None or not db.is_open():
            return
        audio, video = db.load_presets()
        self._presets.update(audio)
        self._video_presets.update(video)

    def save_preset(self, name):
        # type: (str) -> None
        """Persist one audio preset to data store."""
        self._db_save_preset(name)

    def save_video_preset(self, name):
        # type: (str) -> None
        """Persist one video preset to data store."""
        self._db_save_video_preset(name)

    def _db_save_preset(self, name):
        # type: (str) -> None
        db = self._db
        if db is not None and db.is_open():
            if name in self._presets:
                db.save_preset("audio", name, self._presets[name])
            else:
                db.delete_preset("audio", name)
        self._post_save()

    def _db_save_video_preset(self, name):
        # type: (str) -> None
        db = self._db
        if db is not None and db.is_open():
            if name in self._video_presets:
                db.save_preset("video", name, self._video_presets[name])
            else:
                db.delete_preset("video", name)
        self._post_save()

    def _post_save(self):
        # type: () -> None
        if self._on_save is not None:
            self._on_save()

    def save_all(self):
        # type: () -> None
        """Full save of all presets to DB. Used by migration, restore, and
        undo/redo."""
        db = self._db
        if db is not None and db.is_open():
            for name, data in self._presets.items():
                db.save_preset("audio", name, data)
            for name, data in self._video_presets.items():
                db.save_preset("video", name, data)
        if self._on_save is not None:
            self._on_save()

    def delete_removed_files(self, old_presets, old_video_presets, old_session_created):
        # type: (Dict[str, Any], Dict[str, Any], Set[Tuple[str, str]]) -> None
        """Delete DB files for preset keys a restore just dropped.

        old_* capture the live stores BEFORE the restore swapped in new data.
        Preset files are shared across games and reloadable mid-session, so a
        preset is removed only when it was created in this session AND the
        on-disk entry still matches the entry being dropped. Never a directory
        sweep: files the store never loaded are left untouched."""
        db = self._db
        if db is None or not db.is_open():
            return
        for name, dropped in old_presets.items():
            if name in self._presets:
                continue
            if ("audio", name) in old_session_created and db.preset_file_matches("audio", name, dropped):
                db.delete_preset("audio", name)
        for name, dropped in old_video_presets.items():
            if name in self._video_presets:
                continue
            if ("video", name) in old_session_created and db.preset_file_matches("video", name, dropped):
                db.delete_preset("video", name)

    # -- load --

    def load_from_db(self):
        # type: () -> None
        """Load presets from the data store.

        This is the preset side of CueMarkerManager.load_persistent; markers
        load through CueMarkerStore.load_from_db."""
        db = self._db
        if db is None or not db.is_open():
            self._presets = {}
            self._video_presets = {}
            return
        self._presets, self._video_presets = db.load_presets()
        self._migrate_video_presets_to_pools()
        self._sanitize_video_presets()
        self._migrate_preset_speed_mode_rename()
        self._migrate_preset_exclusive()
