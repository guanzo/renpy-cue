# -*- coding: utf-8 -*-
# CueMarkerManager -- unified marker CRUD with typed context accessors.
# Instantiated once at _cue.markers, lives on the NoRollback _cue object.

import os
import copy as _copy
import random as _random
import json as _json
import renpy.config as _config

from renpy.store import persistent

from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, _cue_unwrap_persistent, _cue_format_time, _cue_parse_time,
    _cue_clamp_time, _cue_resolve_files,
    create_img_key, create_vid_key, create_dlg_key, create_loop_key,
    is_img_key, is_vid_key, is_dlg_key, is_loop_key,
    get_key_file,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, ItemsView, KeysView, List, Optional, Set, Tuple
    from cue_lib._types import (
        ClipboardData, MarkerEntry, PoolDict, VideoPoolDict, VideoPreset,
    )

# =========================================================================
# CueMarkerContext -- pool-based markers (shared by .image and .dialogue)
# =========================================================================

class CueMarkerContext(object):
    """Abstract base for pool-based marker contexts."""

    def __init__(self, manager):
        self._mgr = manager

    def _key(self):
        # type: () -> str
        raise NotImplementedError("_key must be overridden")

    def _get_target(self):
        # type: () -> int
        raise NotImplementedError("_get_target must be overridden")

    def _set_target(self, value):
        # type: (int) -> None
        raise NotImplementedError("_set_target must be overridden")

    def add_file(self, file_index):
        # type: (int) -> None
        if not _cue.available_files:
            return
        if file_index < 0 or file_index >= len(_cue.available_files):
            return
        key = self._key()
        filename = _cue.available_files[file_index]
        if filename in _cue.file_tree.disabled_files:
            return
        self._mgr._add_file_to_pool(key, filename, self.get_active())

    def remove_file(self, pool_index, file_index):
        # type: (int, int) -> None
        key = self._key()
        self._mgr._remove_file_from_pool(key, file_index, pool_index)

    def clear(self):
        # type: () -> None
        key = self._key()
        self._mgr.pop(key, None)
        self._mgr._db_save_marker(key)

    def add_pool(self):
        # type: () -> None
        key = self._key()
        entry = self._mgr._get_or_create_entry(key)
        entry["pools"].append({
            "files": [],
            "volume": _cue.VOL_DEFAULT,
        })
        self._set_target(len(entry["pools"]) - 1)
        self._mgr._db_save_marker(key)

    def remove_pool(self, pool_index):
        # type: (int) -> None
        key = self._key()
        entry = self._mgr.get(key)
        if entry is None:
            return
        pools = entry.get("pools")
        if not pools or not (0 <= pool_index < len(pools)):
            return
        pools.pop(pool_index)
        if not pools:
            del self._mgr[key]
        remaining = len(pools)
        if remaining:
            self._set_target(min(self._get_target(), remaining - 1))
        else:
            self._set_target(0)
        self._mgr._db_save_marker(key)

    def get_active(self):
        # type: () -> int
        return self._get_target()

    def set_active(self, pool_index):
        # type: (int) -> None
        self._set_target(pool_index)

    def apply_preset(self, preset_name):
        # type: (str) -> None
        key = self._key()
        self._mgr._stamp_preset(key, preset_name, self.get_active())

    def add_folder(self, folder_path):
        # type: (str) -> None
        key = self._key()
        folder_ref = folder_path.rstrip("/") + "/"
        self._mgr._detach_pool(key, self.get_active())
        pool = self._mgr._ensure_pool(key, self.get_active())
        files = pool.setdefault("files", [])
        if folder_ref not in files:
            files.append(folder_ref)
        self._mgr._db_save_marker(key)


class ResolvedPool(object):
    """Immutable snapshot of a resolved pool."""
    def __init__(self, files, volume, frequency, trigger_on_shake, exclusive=False):
        self.files = files
        self.volume = volume
        self.frequency = frequency
        self.trigger_on_shake = trigger_on_shake
        self.exclusive = exclusive


# =========================================================================
# CueImageContext
# =========================================================================

class CueImageContext(CueMarkerContext):
    def _key(self):
        # type: () -> str
        return create_img_key(_cue.current_file)

    def _get_target(self):
        # type: () -> int
        return self._mgr._img_target

    def _set_target(self, value):
        # type: (int) -> None
        self._mgr._img_target = int(value)


# =========================================================================
# CueDialogueContext
# =========================================================================

class CueDialogueContext(CueMarkerContext):
    def _key(self):
        # type: () -> str
        return create_dlg_key((_cue.current_file, _cue.current_dialogue or ""))

    def _get_target(self):
        # type: () -> int
        return self._mgr._dlg_target

    def _set_target(self, value):
        # type: (int) -> None
        self._mgr._dlg_target = int(value)


# =========================================================================
# CueVideoContext
# =========================================================================

class CueVideoContext(CueMarkerContext):
    def __init__(self, manager):
        super(CueVideoContext, self).__init__(manager)
        self.target_pool = 0
        self.selected = set()
        self.edit_text = ""

    def _key(self):
        # type: () -> str
        return create_vid_key(_cue.current_file) if _cue.current_file else ""

    def _get_target(self):
        # type: () -> int
        return self.target_pool

    def _set_target(self, value):
        # type: (int) -> None
        self.target_pool = int(value)

    def _entry_and_pools(self):
        # type: () -> Tuple[Optional[MarkerEntry], List[Dict[str, Any]]]
        vid_key = self._key()
        if not vid_key:
            return None, []
        entry = self._mgr.get(vid_key)
        if entry is None:
            return None, []
        return entry, entry.get("pools", [])

    def _sort_and_track(self, pools, tracked_entry):
        # type: (List[Dict[str, Any]], Dict[str, Any]) -> int
        pools.sort(key=lambda e: e["time"])
        try:
            new_idx = pools.index(tracked_entry)
            self.target_pool = new_idx
            return new_idx
        except ValueError:
            self.target_pool = min(self.target_pool, len(pools) - 1)
            return -1

    def _append_pool(self, entry, pools, pool_dict):
        # type: (MarkerEntry, List[Dict[str, Any]], Dict[str, Any]) -> None
        pools.append(pool_dict)
        self._sort_and_track(pools, pool_dict)
        self.selected = set()

    def add_file(self, file_index):
        # type: (int) -> None
        if not _cue.available_files:
            return
        if file_index < 0 or file_index >= len(_cue.available_files):
            return
        filename = _cue.available_files[file_index]
        if filename in _cue.file_tree.disabled_files:
            return
        vid_key = self._key()
        entry = self._mgr._get_or_create_entry(vid_key)
        pools = entry["pools"]
        if pools and 0 <= self.target_pool < len(pools):
            self._mgr._detach_pool(vid_key, self.target_pool)
            files = pools[self.target_pool].setdefault("files", [])
            if filename not in files:
                files.append(filename)
        else:
            elapsed = _cue.vid_manager.get_elapsed()
            self._append_pool(entry, pools,
                {"time": elapsed, "files": [filename]})
        self._mgr._db_save_marker(vid_key)

    def remove_file(self, pool_index, file_index):
        # type: (int, int) -> None
        vid_key = self._key()
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        self._mgr._detach_pool(vid_key, pool_index)
        files = pools[pool_index].get("files", [])
        if 0 <= file_index < len(files):
            files.pop(file_index)
            self._mgr._db_save_marker(vid_key)

    def add_folder(self, folder_path):
        # type: (str) -> None
        if not _cue.current_file:
            return
        folder_ref = folder_path.rstrip("/") + "/"
        vid_key = self._key()
        entry = self._mgr._get_or_create_entry(vid_key)
        pools = entry["pools"]
        if pools and 0 <= self.target_pool < len(pools):
            self._mgr._detach_pool(vid_key, self.target_pool)
            pool_files = pools[self.target_pool].setdefault("files", [])
            if folder_ref not in pool_files:
                pool_files.append(folder_ref)
        else:
            elapsed = _cue.vid_manager.get_elapsed()
            self._append_pool(entry, pools,
                {"time": elapsed, "files": [folder_ref]})
        self._mgr._db_save_marker(vid_key)

    def clear(self):
        # type: () -> None
        super(CueVideoContext, self).clear()
        self.target_pool = 0
        self.selected = set()

    def add_pool(self):
        # type: () -> None
        elapsed = _cue.vid_manager.get_elapsed()
        vid_key = self._key()
        entry = self._mgr._get_or_create_entry(vid_key)
        pools = entry["pools"]
        self._append_pool(entry, pools,
            {"time": elapsed, "files": []})
        self._mgr._db_save_marker(vid_key)

    def apply_preset(self, preset_name):
        # type: (str) -> None
        if not _cue.current_file:
            return
        elapsed = _cue.vid_manager.get_elapsed()
        r = self._mgr.resolve_pool({"preset": preset_name})
        if not r.files:
            return
        vid_key = self._key()
        entry = self._mgr._get_or_create_entry(vid_key)
        pools = entry["pools"]
        self._append_pool(entry, pools,
            {"time": elapsed, "preset": preset_name})
        self.sync_text()
        self._mgr._db_save_marker(vid_key)

    def remove_pool(self, pool_index):
        # type: (int) -> None
        super(CueVideoContext, self).remove_pool(pool_index)
        self.selected = set()

    def duplicate_pool(self, ts_index):
        # type: (int) -> None
        vid_key = self._key()
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if not (0 <= ts_index < len(pools)):
            return
        original = pools[ts_index]
        clone = _copy.deepcopy(original)
        pools.append(clone)
        pools.sort(key=lambda e: e["time"])
        self.target_pool = next(i for i, pool in enumerate(pools) if pool is clone)
        self.selected = set()
        self._mgr._db_save_marker(vid_key)

    def remove_selected(self):
        # type: () -> None
        if not self.has_markers():
            return
        if len(self.selected) >= 1:
            entry, pools = self._entry_and_pools()
            if pools:
                for idx in sorted(self.selected, reverse=True):
                    if 0 <= idx < len(pools):
                        pools.pop(idx)
                if not pools:
                    del self._mgr[self._key()]
                    self.target_pool = 0
                else:
                    self.target_pool = min(self.target_pool, len(pools) - 1)
            self.selected = set()
            self._mgr._db_save_marker(self._key())
        else:
            self.remove_pool(self.target_pool)

    def has_markers(self):
        # type: () -> bool
        _, pools = self._entry_and_pools()
        return bool(pools)

    def get_delete_message(self):
        # type: () -> str
        if len(self.selected) > 1:
            nums = ", ".join(str(i + 1) for i in sorted(self.selected))
            return "Delete markers {}?".format(nums)
        elif len(self.selected) == 1:
            return "Delete marker {}?".format(next(iter(self.selected)) + 1)
        else:
            if not self.has_markers():
                return ""
            return "Delete marker {}?".format(self.target_pool + 1)

    def set_active(self, pool_index):
        # type: (int) -> None
        super(CueVideoContext, self).set_active(pool_index)
        self.sync_text()

    def select_tab(self, pool_index):
        # type: (int) -> None
        self.selected = set()
        self.set_active(pool_index)

    def nudge(self, delta):
        # type: (float) -> None
        entry, pools = self._entry_and_pools()
        if not (0 <= self.target_pool < len(pools)):
            return
        pool_entry = pools[self.target_pool]
        dur = self.get_duration()
        new_time = pool_entry["time"] + delta
        if dur > 0:
            new_time = _cue_clamp_time(new_time, dur)
        else:
            new_time = max(0.0, new_time)
        pool_entry["time"] = new_time
        self._sort_and_track(pools, pool_entry)
        self.edit_text = _cue_format_time(new_time)
        self.selected = set()
        self._mgr._db_save_marker(self._key())

    def set_time(self, idx, new_time):
        # type: (int, float) -> None
        entry, pools = self._entry_and_pools()
        dur = self.get_duration()
        new_time = _cue_clamp_time(new_time, dur)
        if 0 <= idx < len(pools):
            pools[idx]["time"] = new_time

    def finalize_drag(self):
        # type: () -> None
        entry, pools = self._entry_and_pools()
        if not pools:
            return
        sel_objects = set()
        for idx in self.selected:
            if 0 <= idx < len(pools):
                sel_objects.add(id(pools[idx]))
        pi = self.target_pool
        if 0 <= pi < len(pools):
            self._sort_and_track(pools, pools[pi])
        if sel_objects:
            new_sel = set()
            for i, pool in enumerate(pools):
                if id(pool) in sel_objects:
                    new_sel.add(i)
            self.selected = new_sel
            if new_sel:
                self.target_pool = min(new_sel)
        self._mgr._db_save_marker(self._key())

    def sync_text(self):
        # type: () -> None
        entry, pools = self._entry_and_pools()
        if 0 <= self.target_pool < len(pools):
            self.edit_text = _cue_format_time(pools[self.target_pool]["time"])

    def commit_text(self):
        # type: () -> None
        entry, pools = self._entry_and_pools()
        if not (0 <= self.target_pool < len(pools)):
            return
        new_time = _cue_parse_time(self.edit_text)
        if new_time is not None and new_time >= 0:
            edited_entry = pools[self.target_pool]
            dur = self.get_duration()
            if dur > 0:
                new_time = _cue_clamp_time(new_time, dur)
            edited_entry["time"] = new_time
            self._sort_and_track(pools, edited_entry)
            self.selected = set()
            self._mgr._db_save_marker(self._key())
        self.edit_text = _cue_format_time(pools[self.target_pool]["time"])

    def get_markers(self):
        # type: () -> List[VideoPoolDict]
        entry, _ = self._entry_and_pools()
        if entry is None:
            return []
        return self._mgr._resolve_video_pools(entry)

    def get_selected(self):
        # type: () -> Set[int]
        return self.selected

    def get_duration(self):
        # type: () -> float
        return _cue.vid_manager.get_duration()


# =========================================================================
# CueLoopContext
# =========================================================================

class CueLoopContext(CueMarkerContext):
    def __init__(self, manager):
        super(CueLoopContext, self).__init__(manager)

    def _key(self):
        # type: () -> str
        return create_loop_key(_cue.current_file or "")

    def _get_target(self):
        # type: () -> int
        return self._mgr._loop_target

    def _set_target(self, value):
        # type: (int) -> None
        self._mgr._loop_target = int(value)

    def add_pool(self):
        # type: () -> None
        key = self._key()
        entry = self._mgr._get_or_create_entry(key)
        entry["pools"].append({
            "files": [],
            "volume": _cue.VOL_DEFAULT,
            "frequency": 1,
        })
        self._set_target(len(entry["pools"]) - 1)
        self._mgr._db_save_marker(key)

    def clear(self):
        # type: () -> None
        key = self._key()
        self._mgr.pop(key, None)
        _cue.trigger.loop_states.pop(key, None)
        self._mgr._db_save_marker(key)

    def set_frequency(self, freq):
        # type: (int) -> None
        key = self._key()
        target = self.get_active()
        entry = self._mgr.get(key)
        if entry:
            pools = entry.get("pools", [])
            if pools and 0 <= target < len(pools):
                pools[target]["frequency"] = int(freq)
                self._mgr._db_save_marker(key)

    def set_exclusive(self, value):
        # type: (bool) -> None
        key = self._key()
        target = self.get_active()
        entry = self._mgr.get(key)
        if entry:
            pools = entry.get("pools", [])
            if pools and 0 <= target < len(pools):
                pools[target]["exclusive"] = bool(value)
                self._mgr._db_save_marker(key)

    @staticmethod
    def get_delay(frequency=1):
        # type: (int) -> float
        if frequency == 4:
            return 5.0 + _random.uniform(0.0, 2.5)
        elif frequency == 3:
            return 0.15 + _random.uniform(0.0, 0.05)
        elif frequency == 2:
            return 0.5 + _random.uniform(0.0, 0.15)
        elif frequency == 1:
            return 1.7 + _random.uniform(0.0, .75)
        else:
            return 3.0 + _random.uniform(0.0, 1.5)


# =========================================================================
# CueMarkerManager
# =========================================================================

class CueMarkerManager(object):
    MAX_BACKUPS = 100

    def __init__(self):
        self._data = {}
        self._presets = {}
        self._video_presets = {}
        self._img_target = 0
        self._dlg_target = 0
        self._loop_target = 0
        self.image = CueImageContext(self)
        self.dialogue = CueDialogueContext(self)
        self.video = CueVideoContext(self)
        self.loop = CueLoopContext(self)
        self.clipboard = None

    # -- dict-like interface --

    def __getitem__(self, key):
        # type: (str) -> MarkerEntry
        return self._data[key]

    def __setitem__(self, key, value):
        # type: (str, MarkerEntry) -> None
        self._data[key] = value

    def __delitem__(self, key):
        # type: (str) -> None
        del self._data[key]

    def __contains__(self, key):
        # type: (str) -> bool
        return key in self._data

    def get(self, key, default=None):
        # type: (str, Optional[MarkerEntry]) -> Optional[MarkerEntry]
        entry = self._data.get(key)
        if entry is None:
            return default
        return self._normalize_entry(entry)

    def setdefault(self, key, default):
        # type: (str, MarkerEntry) -> MarkerEntry
        return self._data.setdefault(key, default)

    def pop(self, key, *args):
        # type: (str, *MarkerEntry) -> MarkerEntry
        return self._data.pop(key, *args)

    def items(self):
        # type: () -> ItemsView[str, MarkerEntry]
        return self._data.items()

    def keys(self):
        # type: () -> KeysView[str]
        return self._data.keys()

    def __len__(self):
        # type: () -> int
        return len(self._data)

    # -- presets --

    def create_preset(self, name, pool_dict):
        # type: (str, PoolDict) -> None
        self._presets[name] = _copy.deepcopy(pool_dict)
        self._db_save_preset(name)
        _cue_log("CREATE-PRESET name={} files={} vol={:.1f}".format(
            name, len(pool_dict.get("files", [])), pool_dict.get("volume", _cue.VOL_DEFAULT)))

    def delete_preset(self, name):
        # type: (str) -> None
        if name in self._presets:
            del self._presets[name]
            self._db_save_preset(name)
            _cue_log("DELETE-PRESET name={}".format(name))

    def preset_remove_file(self, name, file_path):
        # type: (str, str) -> None
        preset = self._presets.get(name)
        if preset is None:
            return
        files = preset.get("files", [])
        if file_path in files:
            files.remove(file_path)
            self._db_save_preset(name)
            return
        for fi, f in enumerate(files):
            if f.endswith("/") and file_path.startswith(f):
                resolved = []
                for rf in _cue.available_files:
                    if rf.startswith(f) and rf not in _cue.file_tree.disabled_files and rf not in resolved:
                        resolved.append(rf)
                if file_path in resolved:
                    resolved.remove(file_path)
                files[fi:fi + 1] = resolved
                self._db_save_preset(name)
                return

    def get_preset(self, name):
        # type: (str) -> Optional[PoolDict]
        return self._presets.get(name)

    def list_presets(self):
        # type: () -> List[str]
        return sorted(self._presets.keys())

    # -- video presets --

    def create_video_preset(self, name, entry):
        # type: (str, Any) -> None
        pools = entry.get("pools", [])
        if not pools:
            return
        clean = []
        for pool in pools:
            if pool.get("time") is not None:
                clean.append({
                    "time": pool["time"],
                    "files": list(pool.get("files", [])),
                    "volume": pool.get("volume", _cue.VOL_DEFAULT),
                })
        if not clean:
            return
        clean.sort(key=lambda e: e["time"])
        source_dur = _cue.vid_manager.get_duration() if hasattr(_cue, 'vid_manager') else 0.0
        self._video_presets[name] = {
            "pools": clean,
            "volume": entry.get("volume", _cue.VOL_DEFAULT),
            "source_duration": max(source_dur, 0.0),
        }
        self._db_save_video_preset(name)
        _cue_log("CREATE-VIDEO-PRESET name={} markers={} dur={:.1f}".format(
            name, len(clean), source_dur))

    def delete_video_preset(self, name):
        # type: (str) -> None
        if name in self._video_presets:
            del self._video_presets[name]
            self._db_save_video_preset(name)
            _cue_log("DELETE-VIDEO-PRESET name={}".format(name))

    def get_video_preset(self, name):
        # type: (str) -> Optional[VideoPreset]
        return self._video_presets.get(name)

    def list_video_presets(self):
        # type: () -> List[str]
        return sorted(self._video_presets.keys())

    def video_preset_out_of_range(self, name):
        # type: (str) -> int
        preset = self._video_presets.get(name)
        if preset is None:
            return 0
        dur = _cue.vid_manager.get_duration()
        if dur is None or dur <= 0:
            return 0
        out = 0
        for pool in preset.get("pools", []):
            t = pool.get("time")
            if t is not None and t > dur:
                out += 1
        return out

    def apply_video_preset(self, name):
        # type: (str) -> None
        preset = self._video_presets.get(name)
        if preset is None:
            return
        if not _cue.current_file:
            return
        vid_key = create_vid_key(_cue.current_file)
        dur = _cue.vid_manager.get_duration()
        dropped = 0
        new_pools = []
        for pool in preset.get("pools", []):
            t = pool.get("time")
            if t is None:
                dropped += 1
                continue
            if dur and dur > 0 and t > dur:
                dropped += 1
                continue
            new_pools.append({
                "time": t,
                "files": list(pool.get("files", [])),
                "volume": pool.get("volume", _cue.VOL_DEFAULT),
            })
        new_pools.sort(key=lambda e: e["time"])
        entry = self._get_or_create_entry(vid_key)
        entry["pools"] = new_pools
        entry["volume"] = preset.get("volume", _cue.VOL_DEFAULT)
        self.video.target_pool = 0
        self.video.selected = set()
        self.video.sync_text()
        self._db_save_marker(vid_key)
        _cue_log("APPLY-VIDEO-PRESET key={} preset={} markers={} dropped={}".format(
            vid_key, name, len(new_pools), dropped))

    @staticmethod
    def _clean_pool_list(pools):
        # type: (List[PoolDict]) -> Tuple[List[PoolDict], int]
        stripped = 0
        clean = []
        for pool in pools:
            if pool.get("time") is not None:
                clean.append(pool)
            else:
                stripped += 1
        return clean, stripped

    def _sanitize_video_presets(self):
        # type: () -> int
        total_stripped = 0
        for name, preset in list(self._video_presets.items()):
            pools = preset.get("pools")
            if not pools:
                continue
            clean, stripped = self._clean_pool_list(pools)
            if stripped:
                preset["pools"] = clean
                total_stripped += stripped
        return total_stripped

    def _resolve_video_pools(self, entry):
        # type: (Any) -> List[VideoPoolDict]
        raw = entry.get("pools", [])
        resolved = []
        for pool in raw:
            if "preset" in pool:
                r = self.resolve_pool(pool)
                resolved.append({
                    "time": pool["time"],
                    "files": list(r.files),
                    "volume": r.volume,
                })
            else:
                resolved.append(pool)
        return resolved

    def _remove_file_from_preset_pool(self, trigger_key, pool_index, _dummy_fi, child_file):
        # type: (str, int, int, str) -> None
        self._detach_pool(trigger_key, pool_index)
        entry = self._data.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if pools and 0 <= pool_index < len(pools):
            files = pools[pool_index].get("files", [])
            if child_file in files:
                files.remove(child_file)
        self._db_save_marker(trigger_key)

    def resolve_pool(self, pool):
        # type: (PoolDict) -> ResolvedPool
        defaults = self._presets.get(pool["preset"], {}) if "preset" in pool else {}
        files = pool.get("files", defaults.get("files", []))
        volume = pool.get("volume", defaults.get("volume", _cue.VOL_DEFAULT))
        frequency = pool.get("frequency", defaults.get("frequency", 1))
        trigger_on_shake = pool.get("trigger_on_shake", defaults.get("trigger_on_shake", False))
        exclusive = pool.get("exclusive", defaults.get("exclusive", False))
        return ResolvedPool(list(files), volume, frequency, trigger_on_shake, exclusive)

    def _detach_pool(self, trigger_key, pool_index):
        # type: (str, int) -> bool
        entry = self._data.get(trigger_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return False
        pool = pools[pool_index]
        if "preset" not in pool:
            return False
        preset_name = pool["preset"]
        preset = self._presets.get(preset_name, {})
        r = self.resolve_pool(pool)
        del pool["preset"]
        pool["files"] = r.files
        pool["volume"] = r.volume
        if "frequency" in preset:
            pool["frequency"] = r.frequency
        if "trigger_on_shake" in preset:
            pool["trigger_on_shake"] = r.trigger_on_shake
        self._db_save_marker(trigger_key)
        _cue_log("DETACH-POOL key={} pi={} preset={} files={}".format(
            trigger_key, pool_index, preset_name, len(r.files)))
        return True

    def _stamp_preset(self, trigger_key, preset_name, pool_index=0):
        # type: (str, str, int) -> None
        entry = self._get_or_create_entry(trigger_key)
        pools = entry["pools"]
        while len(pools) <= pool_index:
            pools.append({"files": [], "volume": _cue.VOL_DEFAULT})
        pools[pool_index] = {"preset": preset_name}
        self._db_save_marker(trigger_key)
        _cue_log("STAMP-PRESET key={} pi={} preset={}".format(
            trigger_key, pool_index, preset_name))

    def _detach_folder_ref_in_files(self, files, file_index, child_file):
        # type: (List[str], int, str) -> None
        folder_ref = files[file_index]
        if not folder_ref.endswith("/"):
            return
        resolved = []
        for f in _cue.available_files:
            if f.startswith(folder_ref) and f not in _cue.file_tree.disabled_files and f not in resolved:
                resolved.append(f)
        if child_file in resolved:
            resolved.remove(child_file)
        files[file_index:file_index + 1] = resolved

    def _remove_file_from_folder_ref(self, trigger_key, pool_index, file_index, child_file):
        # type: (str, int, int, str) -> None
        self._detach_pool(trigger_key, pool_index)
        entry = self._data.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return
        files = pools[pool_index].get("files", [])
        if file_index >= len(files):
            return
        self._detach_folder_ref_in_files(files, file_index, child_file)
        self._db_save_marker(trigger_key)

    def _normalize_entry(self, entry):
        # type: (Any) -> MarkerEntry
        if "pools" not in entry:
            entry["pools"] = [{"files": entry.pop("files", [])}]
        entry.setdefault("replay", _cue.current_replay)
        return entry

    def _get_or_create_entry(self, trigger_key):
        # type: (str) -> Any
        entry = self._data.get(trigger_key)
        if entry is None:
            entry = {"pools": []}
            self._data[trigger_key] = entry
        entry = self._normalize_entry(entry)
        return entry

    def _ensure_pool(self, trigger_key, pool_index):
        # type: (str, int) -> PoolDict
        entry = self._get_or_create_entry(trigger_key)
        pools = entry["pools"]
        if not pools:
            pools.append({
                "files": [],
                "volume": _cue.VOL_DEFAULT,
            })
        if pool_index < 0:
            pool_index = 0
        if pool_index >= len(pools):
            pool_index = len(pools) - 1
        return pools[pool_index]

    def _add_file_to_pool(self, trigger_key, filename, pool_index=0):
        # type: (str, str, int) -> None
        self._detach_pool(trigger_key, pool_index)
        pool = self._ensure_pool(trigger_key, pool_index)
        files = pool.setdefault("files", [])
        if filename not in files:
            files.append(filename)
        self._db_save_marker(trigger_key)

    def _remove_file_from_pool(self, trigger_key, file_index, pool_index=0):
        # type: (str, int, int) -> None
        self._detach_pool(trigger_key, pool_index)
        entry = self._data.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if pools:
            if not (0 <= pool_index < len(pools)):
                return
            pool = pools[pool_index]
            files = pool.get("files", [])
            if 0 <= file_index < len(files):
                files.pop(file_index)
            if not files:
                pools.pop(pool_index)
            if not pools:
                del self._data[trigger_key]
            self._db_save_marker(trigger_key)
        elif "files" in entry:
            files = entry["files"]
            if 0 <= file_index < len(files):
                files.pop(file_index)
                if not files:
                    del self._data[trigger_key]
                self._db_save_marker(trigger_key)

    def _normalize_all(self):
        # type: () -> bool
        changed = False
        for key, entry in list(self._data.items()):
            if is_img_key(key) or is_dlg_key(key) or is_loop_key(key):
                if "pools" not in entry:
                    self._normalize_entry(entry)
                    changed = True
            if is_loop_key(key) and "frequency" in entry:
                freq = entry.pop("frequency")
                for pool in entry.get("pools", []):
                    pool.setdefault("frequency", freq)
                changed = True
        return changed

    @staticmethod
    def _migrate_colon_key(key):
        # type: (str) -> str
        """Convert legacy colon keys (v:file) to underscore (v_file)."""
        if key.startswith("v:"):
            return "v_" + key[2:]
        if key.startswith("i:"):
            return "i_" + key[2:]
        if key.startswith("d:"):
            return "d_" + key[2:]
        if key.startswith("l:"):
            return "l_" + key[2:]
        return key

    def _migrate_speed_mode_rename(self):
        # type: () -> None
        for key, entry in list(self._data.items()):
            if is_vid_key(key) and entry.get("speed_mode") == "sequence":
                entry["speed_mode"] = "multi"
        for preset in self._video_presets.values():
            if preset.get("speed_mode") == "sequence":
                preset["speed_mode"] = "multi"

    def _migrate_video_timestamps_to_pools(self):
        # type: () -> Tuple[int, int]
        entries_changed = 0
        for key, entry in list(self._data.items()):
            if is_vid_key(key) and "timestamps" in entry:
                if "pools" not in entry:
                    entry["pools"] = entry.pop("timestamps")
                else:
                    del entry["timestamps"]
                entries_changed += 1
        presets_changed = 0
        for name, preset in list(self._video_presets.items()):
            if "timestamps" in preset:
                if "pools" not in preset:
                    preset["pools"] = preset.pop("timestamps")
                else:
                    del preset["timestamps"]
                presets_changed += 1
        if entries_changed or presets_changed:
            _cue_log("MIGRATE-VIDEO-POOLS entries={} presets={}".format(
                entries_changed, presets_changed))
        return entries_changed, presets_changed

    def _sanitize_video_pools(self):
        # type: () -> int
        total_stripped = 0
        for key, entry in list(self._data.items()):
            if not is_vid_key(key):
                continue
            pools = entry.get("pools")
            if not pools:
                continue
            clean, stripped = self._clean_pool_list(pools)
            if stripped:
                entry["pools"] = clean
                total_stripped += stripped
        return total_stripped

    # -- persistence --

    def reload_presets(self):
        # type: () -> None
        """Re-read presets from the shared data store. Merges new/updated
        presets from disk (other games may have added them). Never deletes."""
        db = _cue.db
        if db is None or not db.is_open():
            return
        audio, video = db.load_presets()
        self._presets.update(audio)
        self._video_presets.update(video)

    # ------------------------------------------------------------------
    # Public save API -- targeted data store writes for routine mutations
    # ------------------------------------------------------------------

    def save_marker(self, key):
        # type: (str) -> None
        """Persist one marker entry to data store. Call after mutating self._data[key]."""
        self._db_save_marker(key)

    def save_preset(self, name):
        # type: (str) -> None
        """Persist one audio preset to data store."""
        self._db_save_preset(name)

    def save_video_preset(self, name):
        # type: (str) -> None
        """Persist one video preset to data store."""
        self._db_save_video_preset(name)

    # ------------------------------------------------------------------
    # Internal helpers -- write one item to DB, then run side effects
    # ------------------------------------------------------------------

    def _db_save_marker(self, key):
        # type: (str) -> None
        db = _cue.db
        if db is not None and db.is_open():
            if key in self._data:
                db.save_marker(key, self._data[key])
            else:
                db.delete_marker(key)
        self._post_save()

    def _db_save_preset(self, name):
        # type: (str) -> None
        db = _cue.db
        if db is not None and db.is_open():
            if name in self._presets:
                db.save_preset("audio", name, self._presets[name])
            else:
                db.delete_preset("audio", name)
        self._post_save()

    def _db_save_video_preset(self, name):
        # type: (str) -> None
        db = _cue.db
        if db is not None and db.is_open():
            if name in self._video_presets:
                db.save_preset("video", name, self._video_presets[name])
            else:
                db.delete_preset("video", name)
        self._post_save()

    def _post_save(self):
        # type: () -> None
        """Common side effects after any DB write."""
        stripped_keys = self._sanitize_video_pools_tracked()
        db = _cue.db
        if db is not None and db.is_open():
            for key in stripped_keys:
                if key in self._data:
                    db.save_marker(key, self._data[key])
        _cue.undo.capture()

    def _sanitize_video_pools_tracked(self):
        # type: () -> Set[str]
        modified = set()
        for key, entry in list(self._data.items()):
            if not is_vid_key(key):
                continue
            pools = entry.get("pools")
            if not pools:
                continue
            clean, stripped = self._clean_pool_list(pools)
            if stripped:
                entry["pools"] = clean
                modified.add(key)
        total = len(modified)
        if total:
            _cue_log("SAVE-MARKERS: sanitized {} malformed video pool(s)".format(total))
        return modified

    def save_all(self):
        # type: () -> None
        """Full save of all markers + presets to DB.
        Used by migration, restore, and undo/redo."""
        db = _cue.db
        if db is not None and db.is_open():
            for key in self._data:
                db.save_marker(key, self._data[key])
            for name, data in self._presets.items():
                db.save_preset("audio", name, data)
            for name, data in self._video_presets.items():
                db.save_preset("video", name, data)
        _cue.undo.capture()

    # ------------------------------------------------------------------
    # Load / migration
    # ------------------------------------------------------------------

    def _populate_config(self, data):
        # type: (Any) -> None
        """Populate in-memory stores from a legacy dict (migration only)."""
        self._data = _cue_unwrap_persistent(data.get("markers", {}))
        self._data = {self._migrate_colon_key(k): v for k, v in self._data.items()}
        self._presets = _cue_unwrap_persistent(data.get("presets", {}))
        self._video_presets = _cue_unwrap_persistent(data.get("video_presets", {}))
        _cue.file_tree.disabled_files = set(_cue_unwrap_persistent(data.get("disabled_files", set())))
        _cue.trigger.active = data.get("triggers_active", True)
        _cue.video_editor.encode_mode = data.get("encode_mode", _cue.video_editor.MODE_INTERPOLATE)
        _cue.speed_resolver.seamless_transition = data.get("seamless_transition", False)
        persistent._cue_triggers_active = _cue.trigger.active
        persistent._cue_encode_mode = _cue.video_editor.encode_mode
        persistent._cue_seamless_transition = _cue.speed_resolver.seamless_transition
        persistent._cue_disabled_files = set(_cue.file_tree.disabled_files)
        self._migrate_video_timestamps_to_pools()
        self._sanitize_video_pools()
        self._sanitize_video_presets()
        self._normalize_all()
        self._migrate_speed_mode_rename()

    def load_persistent(self):
        # type: () -> None
        """Load markers + presets from data store; scalars from persistent."""
        db = _cue.db
        if db is None or not db.is_open():
            data = getattr(persistent, '_cue_config', None)
            if data is None:
                self._data = {}
                self._video_presets = {}
            else:
                self._populate_config(data)
            self._load_scalars_from_persistent()
            return

        if db.is_fresh():
            data = self._load_legacy_json()
            source = "json" if data is not None else None
            if data is None:
                data = getattr(persistent, '_cue_config', None)
                source = "persistent" if data is not None else None
            if data is not None:
                self._populate_config(data)
                db.migrate_markers_and_presets(
                    self._data, self._presets, self._video_presets,
                )
                _cue_log("MIGRATE-DB source={} keys={}".format(
                    source, len(self._data)))
            else:
                self._data = {}
                self._video_presets = {}
        else:
            self._data = db.load_markers()
            self._presets, self._video_presets = db.load_presets()
            self._migrate_video_timestamps_to_pools()
            self._sanitize_video_pools()
            self._sanitize_video_presets()
            self._normalize_all()
            self._migrate_speed_mode_rename()

        self._load_scalars_from_persistent()
        _cue_log("LOAD-MARKERS total_keys={}".format(len(self._data)))

    def _load_scalars_from_persistent(self):
        # type: () -> None
        _cue.file_tree.disabled_files = set(
            getattr(persistent, '_cue_disabled_files', set()))
        _cue.trigger.active = getattr(
            persistent, '_cue_triggers_active', True)
        _cue.video_editor.encode_mode = getattr(
            persistent, '_cue_encode_mode', _cue.video_editor.MODE_INTERPOLATE)
        _cue.speed_resolver.seamless_transition = getattr(
            persistent, '_cue_seamless_transition', False)

    def _load_legacy_json(self):
        # type: () -> Optional[Any]
        dump_path = _cue.config_path
        if not os.path.isfile(dump_path):
            return None
        try:
            with open(dump_path, "r") as f:
                return _json.load(f)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Backup / restore
    # ------------------------------------------------------------------

    def backup_to_file(self):
        # type: () -> None
        try:
            dump_dir = os.path.join(_config.gamedir, _cue.base_dir)
            if not os.path.isdir(dump_dir):
                os.makedirs(dump_dir)
            dump_path = os.path.join(dump_dir, _cue.config_filename)
            data = self._build_config_dict()
            with open(dump_path, "w") as f:
                _json.dump(data, f, indent=2, sort_keys=True)
            _cue_log("DUMP-MARKERS total_keys={} path={}".format(
                len(self._data), _cue.config_filename))
        except Exception as e:
            _cue_log("DUMP-MARKERS-ERROR {}".format(str(e)))

    def _build_config_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "markers": _cue_unwrap_persistent(self._data),
            "presets": _cue_unwrap_persistent(self._presets),
            "video_presets": _cue_unwrap_persistent(self._video_presets),
            "disabled_files": list(_cue_unwrap_persistent(_cue.file_tree.disabled_files)),
            "triggers_active": _cue.trigger.active,
            "encode_mode": _cue.video_editor.encode_mode,
            "seamless_transition": _cue.speed_resolver.seamless_transition,
        }

    def restore_from_file(self):
        # type: () -> None
        try:
            dump_path = _cue.config_path
            if not os.path.isfile(dump_path):
                _cue_log("RESTORE-MARKERS-NO-FILE path={}".format(_cue.config_filename))
                return
            with open(dump_path, "r") as f:
                data = _json.load(f)
            self._populate_config(data)
            self.save_all()
            _cue_log("RESTORE-MARKERS total_keys={} path={}".format(
                len(self._data), _cue.config_filename))
        except Exception as e:
            _cue_log("RESTORE-MARKERS-ERROR {}".format(str(e)))

    # -- clipboard --

    def copy_context(self):
        # type: () -> None
        ctx_file = _cue.current_file
        ctx_dlg = _cue.current_dialogue
        copied = {}
        all_keys = [
            create_vid_key(ctx_file),
            create_img_key(ctx_file),
            create_dlg_key((ctx_file, ctx_dlg)),
            create_loop_key(ctx_file),
        ]
        for key in all_keys:
            entry = self._data.get(key)
            if entry:
                copied[key] = _copy.deepcopy(entry)
        self.clipboard = {
            "markers": copied,
            "source_file": ctx_file,
            "source_dialogue": ctx_dlg,
        }

    def paste_context(self):
        # type: () -> None
        if self.clipboard is None:
            return
        ctx_file = _cue.current_file
        ctx_dlg = _cue.current_dialogue
        source_file = self.clipboard.get("source_file", "")
        for source_key, entry in self.clipboard.get("markers", {}).items():
            if get_key_file(source_key) != source_file:
                continue
            new_key = source_key
            if is_vid_key(source_key):
                new_key = create_vid_key(ctx_file)
            elif is_img_key(source_key):
                new_key = create_img_key(ctx_file)
            elif is_dlg_key(source_key):
                new_key = create_dlg_key((ctx_file, ctx_dlg))
            elif is_loop_key(source_key):
                new_key = create_loop_key(ctx_file)
            self._data[new_key] = _copy.deepcopy(entry)
            if _cue.current_replay:
                self._data[new_key]["replay"] = _cue.current_replay
            _cue_log("{} {}".format(new_key, str(entry)))
            if is_vid_key(source_key):
                dur = _cue.vid_manager.get_duration()
                pasted_entry = self._data[new_key]
                for pool_entry in pasted_entry.get("pools", []):
                    t = pool_entry.get("time", 0)
                    if dur > 0:
                        t = _cue_clamp_time(t, dur)
                    else:
                        t = max(0.0, t)
                    pool_entry["time"] = t
        _cue.trigger.loop_states = {}
        self.save_all()
