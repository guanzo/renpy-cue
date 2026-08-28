# -*- coding: utf-8 -*-
# CuePresetStore -- the preset data leaf: audio + video + music + intensity
# presets shared across games.
#
# CuePresets is the base preset collection: one kind's name->entry dict, the
# session-created set, and unified CRUD + persistence.  CueAudioPresets /
# CueVideoPresets / CueMusicPresets / CueIntensityPresets specialize the kind
# (load source, migration passes, kind-specific views and create transforms).
# CuePresetStore is the thin container: it owns the shared session-created set,
# holds the collections as self.audio / self.video / self.music /
# self.intensity, and keeps only cross-kind persistence (load/reload/save_all/
# delete_removed_files).
#
# Lives at _cue.presets (wired in cue_z.rpy) and is injected into CueMarkerStore
# for the two preset reads it makes (resolve_pool defaults, detach
# materialization).
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


class CuePresets(object):
    """One preset kind (audio | video | music): the name->entry dict plus
    unified CRUD and file-backed persistence.

    ``_kind`` names the DB preset type; ``_disk()`` is the on-disk dict source
    (load/reload); ``_migrate()`` runs the kind's load-time passes.
    ``_session_created`` is the container's shared set, so a restore can tell
    session-created presets apart from presets loaded from disk."""

    _kind = ""  # type: str

    def __init__(self, db, session_created, on_save=None):
        # type: (CueDatabase, Set[Tuple[str, str]], Optional[Callable[[], None]]) -> None
        self._db = db
        self._session_created = session_created
        self._on_save = on_save
        self._presets = {}

    # -- unified CRUD --

    def create(self, name, data):
        # type: (str, Any) -> None
        self._do_create(name, data)
        self._log_create(name, data)

    def _do_create(self, name, data):
        # type: (str, Any) -> None
        """Shared create mechanics (deepcopy, session mark, persist); the
        kind-specific log line lives in _log_create / the create override."""
        self._presets[name] = _copy.deepcopy(data)
        self._session_created.add((self._kind, name))
        self._db_save(name)

    def _log_create(self, name, data):
        # type: (str, Any) -> None
        _cue_log("CREATE-PRESET kind={} name={}".format(self._kind, name))

    def delete(self, name):
        # type: (str) -> None
        if name in self._presets:
            del self._presets[name]
            self._session_created.discard((self._kind, name))
            self._db_save(name)
            _cue_log("DELETE-{}-PRESET name={}".format(self._kind.upper(), name))

    def get(self, name):
        # type: (str) -> Optional[Any]
        return self._presets.get(name)

    def list(self):
        # type: () -> List[str]
        return sorted(self._presets.keys())

    def items(self):
        # type: () -> Any
        return self._presets.items()

    def view(self, name, index=0):
        # type: (str, int) -> Any
        """Ephemeral view over one preset row for file ops (add/remove/clear).

        ``index`` targets a sub-row for kinds that have one (video pool rows);
        kinds whose view is the whole preset ignore it.  One view = one op."""
        raise NotImplementedError

    # -- persistence --

    def save(self, name):
        # type: (str) -> None
        self._db_save(name)

    def _db_save(self, name):
        # type: (str) -> None
        db = self._db
        if db is not None and db.is_open():
            if name in self._presets:
                db.save_preset(self._kind, name, self._presets[name])
            else:
                db.delete_preset(self._kind, name)
        self._post_save()

    def _db_save_all(self):
        # type: () -> None
        """Persist every preset without firing on_save (the container fires it
        once across all three kinds)."""
        db = self._db
        if db is not None and db.is_open():
            for name, data in self._presets.items():
                db.save_preset(self._kind, name, data)

    def _post_save(self):
        # type: () -> None
        if self._on_save is not None:
            self._on_save()

    def load_from_db(self, data=None):
        # type: (Optional[Dict[str, Any]]) -> None
        """Replace with on-disk presets and run the kind's migration passes."""
        if data is None:
            data = self._disk()
        self._presets = data
        self._migrate()

    def reload(self, data=None):
        # type: (Optional[Dict[str, Any]]) -> None
        """Merge new/updated presets from disk (other games may have added
        them). Never deletes."""
        if data is None:
            data = self._disk()
        self._presets.update(data)

    def _disk(self):
        # type: () -> Dict[str, Any]
        raise NotImplementedError

    def _migrate(self):
        # type: () -> None
        pass

    def delete_removed_files(self, old_presets, old_session_created):
        # type: (Dict[str, Any], Set[Tuple[str, str]]) -> None
        """Delete DB files for preset keys a restore just dropped.

        ``old_presets`` / ``old_session_created`` capture the live stores
        BEFORE the restore swapped in new data.  Preset files are shared across
        games and reloadable mid-session, so a preset is removed only when it
        was created in this session AND the on-disk entry still matches the
        entry being dropped.  Never a directory sweep: files the store never
        loaded are left untouched."""
        db = self._db
        if db is None or not db.is_open():
            return
        for name, dropped in old_presets.items():
            if name in self._presets:
                continue
            if (self._kind, name) in old_session_created and db.preset_file_matches(self._kind, name, dropped):
                db.delete_preset(self._kind, name)


class CueAudioPresets(CuePresets):
    """Audio (SFX) presets: pool dicts, the ephemeral CueAudioPreset view, and
    the exclusive-pool migration."""

    _kind = "audio"

    def __init__(self, db, session_created, on_save=None):
        # type: (CueDatabase, Set[Tuple[str, str]], Optional[Callable[[], None]]) -> None
        CuePresets.__init__(self, db, session_created, on_save)

    def _log_create(self, name, data):
        # type: (str, Any) -> None
        _cue_log(
            "CREATE-PRESET name={} files={} vol={:.1f}".format(
                name, len(data.get("files", [])), data.get("volume", CUE_VOLUME_DEFAULT)
            )
        )

    def view(self, name, index=0):
        # type: (str, int) -> CueAudioPreset
        """Ephemeral view over one audio preset (the whole row is the target,
        so ``index`` is ignored).  One view = one op."""
        return CueAudioPreset(self, name)

    def preset_remove_file(self, name, file_path):
        # type: (str, str) -> None
        """Remove one ref from an audio preset via the ephemeral view (the
        single home for folder-ref expansion).  A saved preset can be empty,
        so nothing is pruned."""
        self.view(name).remove_file(file_path)

    def _disk(self):
        # type: () -> Dict[str, Any]
        db = self._db
        if db is None or not db.is_open():
            return {}
        return db.load_presets()[0]

    def _migrate(self):
        # type: () -> None
        self._migrate_preset_exclusive()

    def _migrate_preset_exclusive(self):
        # type: () -> int
        migrated = 0
        for preset in list(self._presets.values()):
            if _cue_migrate_exclusive_pool(preset):
                migrated += 1
        return migrated


class CueVideoPresets(CuePresets):
    """Video presets: saved marker-pool timelines, ephemeral CueVideoPresetPool
    views, and the load-time sanitize/migration passes."""

    _kind = "video"

    def __init__(self, db, session_created, on_save=None):
        # type: (CueDatabase, Set[Tuple[str, str]], Optional[Callable[[], None]]) -> None
        CuePresets.__init__(self, db, session_created, on_save)

    def create(self, name, entry, source_dur=0.0):  # pyright: ignore[reportIncompatibleMethodOverride]
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
        self._do_create(
            name,
            {
                "pools": clean,
                "volume": entry.get("volume", CUE_VOLUME_DEFAULT),
                "source_duration": max(source_dur, 0.0),
            },
        )
        _cue_log("CREATE-VIDEO-PRESET name={} markers={} dur={:.1f}".format(name, len(clean), source_dur))

    def view(self, name, index=0):
        # type: (str, int) -> CueVideoPresetPool
        """Ephemeral view over one pool row in a saved video preset.  One view
        = one op; the view re-resolves the row from the live dict each call."""
        return CueVideoPresetPool(self, name, index)

    def remove_video_preset_pool(self, name, pool_index):
        # type: (str, int) -> None
        """Remove one pool from a video preset; a preset left with no pools is
        deleted (a saved video preset always has at least one pool)."""
        preset = self._presets.get(name)
        if preset is None:
            return
        pools = preset.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        del pools[pool_index]
        if not pools:
            self.delete(name)
            return
        self._db_save(name)
        _cue_log("REMOVE-VIDEO-POOL preset={} index={}".format(name, pool_index))

    def remove_video_preset_pool_file(self, name, pool_index, file_path):
        # type: (str, int, str) -> None
        """Remove one file from a pool in a saved video preset via the ephemeral
        view (the single home for folder-ref expansion)."""
        self.view(name, pool_index).remove_file(file_path)

    def _disk(self):
        # type: () -> Dict[str, Any]
        db = self._db
        if db is None or not db.is_open():
            return {}
        return db.load_presets()[1]

    def _migrate(self):
        # type: () -> None
        self._migrate_video_presets_to_pools()
        self._sanitize_video_presets()
        self._migrate_preset_speed_mode_rename()

    def _sanitize_video_presets(self):
        # type: () -> int
        total_stripped = 0
        for _, preset in list(self._presets.items()):
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
        for preset in self._presets.values():
            if preset.get("speed_mode") == "sequence":
                preset["speed_mode"] = "multi"

    def _migrate_video_presets_to_pools(self):
        # type: () -> int
        presets_changed = 0
        for _, preset in list(self._presets.items()):
            if "timestamps" in preset:
                if "pools" not in preset:
                    preset["pools"] = preset.pop("timestamps")
                else:
                    del preset["timestamps"]
                presets_changed += 1
        return presets_changed


class CueMusicPresets(CuePresets):
    """Music presets: saved trigger song lists (game-agnostic, like SFX).

    Music preset writes stay outside the undo snapshot (on_save is None), the
    same as before the fold."""

    _kind = "music"

    def __init__(self, db, session_created, on_save=None):
        # type: (CueDatabase, Set[Tuple[str, str]], Optional[Callable[[], None]]) -> None
        CuePresets.__init__(self, db, session_created, on_save)

    def create(self, name, songs):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (str, List[str]) -> None
        """Save a trigger's song list as a preset.  ``songs`` are stored refs."""
        self._do_create(name, {"files": list(songs)})
        _cue_log("CREATE-MUSIC-PRESET name={} files={}".format(name, len(songs)))

    def _disk(self):
        # type: () -> Dict[str, Any]
        db = self._db
        if db is None or not db.is_open():
            return {}
        return db.load_music_presets()


class CueIntensityPresets(CuePresets):
    """Intensity group presets: a named, ordered level list per igroup.

    Igroups are shared presets like audio/video/music.  The level-editing and
    speed-band resolution behavior stays on CueIntensityManager; this
    collection owns the name->igroup dict and its CRUD + load-time migration
    from the legacy ``folders`` shape."""

    _kind = "intensity"

    def create(self, name):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (str) -> Optional[str]
        """Create an empty igroup.  Returns an error string, or None.

        ``name`` is stripped; blank and duplicate names are rejected (the
        save-dialog commit surfaces the error string)."""
        name = name.strip()
        if not name:
            return "Intensity group name can't be empty."
        if self.get(name) is not None:
            return "An intensity group named '{}' already exists.".format(name)
        CuePresets.create(self, name, {"levels": [], "next_ilevel_id": 1})
        return None

    def _disk(self):
        # type: () -> Dict[str, Any]
        db = self._db
        if db is None or not db.is_open():
            return {}
        return db.load_intensity_presets()

    def _migrate(self):
        # type: () -> None
        """One-time: a legacy ``folders`` igroup becomes a level list (one
        folder per level, sequential ids); the multiplier arrays are dropped
        (the ramp is now derived).  Back-writes so the migration doesn't rerun."""
        for name, data in list(self._presets.items()):
            if "levels" not in data and "folders" in data:
                folders = data.get("folders", [])
                data["levels"] = [{"id": i + 1, "files": [f]} for i, f in enumerate(folders)]
                data["next_ilevel_id"] = len(folders) + 1
                data.pop("folders", None)
                data.pop("volume_multipliers", None)
                data.pop("frequency_multipliers", None)
                db = self._db
                if db is not None and db.is_open():
                    db.save_preset(self._kind, name, data)


class CuePresetStore(object):
    """Container over the preset collections.

    Owns the shared session-created set and the cross-kind persistence
    (load/reload/save_all/delete_removed_files).  Per-kind CRUD lives on
    ``self.audio`` / ``self.video`` / ``self.music`` / ``self.intensity``.

    ``on_save`` is called once after every DB write; the coordinator uses it to
    capture an undo snapshot."""

    def __init__(self, db, on_save=None):
        # type: (CueDatabase, Optional[Callable[[], None]]) -> None
        self._db = db
        self._on_save = on_save
        self._session_created = set()  # ("audio"|"video"|"music"|"intensity", name)
        self.audio = CueAudioPresets(db, self._session_created, on_save)
        self.video = CueVideoPresets(db, self._session_created, on_save)
        self.music = CueMusicPresets(db, self._session_created, None)
        self.intensity = CueIntensityPresets(db, self._session_created, None)

    def reload_presets(self):
        # type: () -> None
        """Re-read presets from the shared data store. Merges new/updated
        presets from disk (other games may have added them). Never deletes."""
        db = self._db
        if db is None or not db.is_open():
            return
        audio, video = db.load_presets()
        self.audio.reload(audio)
        self.video.reload(video)
        self.music.reload()
        self.intensity.reload()

    def save_all(self):
        # type: () -> None
        """Full save of all presets to DB. Used by migration, restore, and
        undo/redo. Fires on_save once across all four kinds."""
        self.audio._db_save_all()
        self.video._db_save_all()
        self.music._db_save_all()
        self.intensity._db_save_all()
        self._post_save()

    def _post_save(self):
        # type: () -> None
        if self._on_save is not None:
            self._on_save()

    def delete_removed_files(self, old_presets, old_video_presets, old_session_created):
        # type: (Dict[str, Any], Dict[str, Any], Set[Tuple[str, str]]) -> None
        """Delete DB files for preset keys a restore just dropped.  See
        CuePresets.delete_removed_files; ``old_session_created`` is the
        pre-restore session-created set."""
        self.audio.delete_removed_files(old_presets, old_session_created)
        self.video.delete_removed_files(old_video_presets, old_session_created)

    # -- load --

    def load_from_db(self):
        # type: () -> None
        """Load presets from the data store.

        This is the preset side of CueMarkerManager.load_persistent; markers
        load through CueMarkerStore.load_from_db."""
        db = self._db
        if db is None or not db.is_open():
            self.audio._presets = {}
            self.video._presets = {}
            self.music._presets = {}
            self.intensity._presets = {}
            return
        audio, video = db.load_presets()
        self.audio.load_from_db(audio)
        self.video.load_from_db(video)
        self.music.load_from_db()
        self.intensity.load_from_db()
