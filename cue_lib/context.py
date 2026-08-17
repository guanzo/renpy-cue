# -*- coding: utf-8 -*-
# Cue*Context -- typed marker contexts (image/dialogue/video/loop) that wrap
# CueMarkerManager's store surface for one trigger key.  Each context owns its
# target index and mutates pools through the manager's public mutators.

import copy as _copy
import random as _random

from cue_lib.constants import (
    CUE_INTERVAL_SELECT_TOLERANCE, CUE_VOLUME_DEFAULT, CueExclusiveStart, CueLoopFrequency,
)
from cue_lib.util import (
    _cue_clamp_time, _cue_format_time, _cue_parse_time, _cue_shift_held,
    create_img_key, create_vid_key, create_dlg_key, create_loop_key,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import (
        MarkerEntry, PoolDict, VideoPoolDict,  # pyright: ignore[reportUnusedImport]
    )

# =========================================================================
# CueMarkerContext -- pool-based markers (shared by .image and .dialogue)
# =========================================================================

class CueMarkerContext(object):
    """Abstract base for pool-based marker contexts."""

    # One-shot contexts (image/dialogue) can't wait for open air, so the
    # "Wait for air" start option is hidden for them in the UI.
    ONE_SHOT = False

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
        if not self._mgr._sfx_manager.files:
            return
        if file_index < 0 or file_index >= len(self._mgr._sfx_manager.files):
            return
        key = self._key()
        filename = self._mgr._sfx_manager.files[file_index]
        if filename in self._mgr._sfx_manager.disabled_files:
            return
        self._mgr._add_file_to_pool(key, filename, self.get_active())

    def send_file(self, file_index):
        # type: (int) -> None
        if _cue_shift_held():
            self.add_pool()
        self.add_file(file_index)

    def send_folder(self, folder_path):
        # type: (str) -> None
        if _cue_shift_held():
            self.add_pool()
        self.add_folder(folder_path)

    def send_preset(self, preset_name):
        # type: (str) -> None
        if _cue_shift_held():
            self.add_pool()
        self.apply_preset(preset_name)

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
            "volume": CUE_VOLUME_DEFAULT,
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

    def get_active_pool(self):
        # type: () -> PoolDict
        """Raw dict of the active pool, or {} if there is none.

        Clamps the target like cue_context_section does, so a stale target
        after a file switch still resolves to a valid pool."""
        entry = self._mgr.get(self._key())
        if entry is None:
            return {}
        pools = entry.get("pools", [])
        if not pools:
            return {}
        target = max(0, min(self.get_active(), len(pools) - 1))
        return pools[target]

    def has_pools(self):
        # type: () -> bool
        """True when the current key's marker entry has at least one pool."""
        entry = self._mgr.get(self._key())
        if entry is None:
            return False
        return bool(entry.get("pools"))

    def _set_exclusive_payload(self, payload):
        # type: (Optional[Dict[str, Any]]) -> None
        """Write (or clear) the exclusive config for this trigger.

        One-shots carry a single exclusive flag for the whole trigger, so it
        lands on every pool -- whichever pool fires clears the air for the
        scene. Loops keep it per-pool so one loop can "sneak in" solo while
        its siblings stay plain.

        ``payload`` is the full nested dict to store, or None to drop the
        config (plain citizen)."""
        key = self._key()
        entry = self._mgr.get(key)
        if entry is None:
            return
        pools = entry.get("pools", [])
        if not pools:
            return
        if self.ONE_SHOT:
            for pool in pools:
                if payload is None:
                    pool.pop("exclusive", None)
                else:
                    pool["exclusive"] = dict(payload)
        else:
            target = self.get_active()
            if 0 <= target < len(pools):
                if payload is None:
                    pools[target].pop("exclusive", None)
                else:
                    pools[target]["exclusive"] = payload
        self._mgr._db_save_marker(key)

    def set_exclusive(self, start, hold):
        # type: (int, bool) -> None
        """Enable exclusive playback on the active pool with a start mode."""
        self._set_exclusive_payload({
            "group": CUE_EXCLUSIVE_GROUP,
            "start": int(start),
            "hold": bool(hold),
        })

    def toggle_exclusive(self):
        # type: () -> None
        """Toggle exclusive playback for this trigger.

        One-shots toggle the whole trigger (every pool); loops toggle the
        active pool only. Off -> on uses the context default: loops wait
        then hold, one-shots fade out other SFX and play immediately.
        On -> off clears the config."""
        excl = self.get_active_pool().get("exclusive")
        if isinstance(excl, dict) and excl.get("group"):
            self._set_exclusive_payload(None)
        elif self.ONE_SHOT:
            self.set_exclusive(CueExclusiveStart.FADE, False)
        else:
            self.set_exclusive(CueExclusiveStart.WAIT, True)

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


# Nonzero group marks a pool as exclusive. Grouping is derived at runtime
# (scene + line for one-shots; loops never group), so the stored group value
# is just an on/off flag -- any nonzero value works.
CUE_EXCLUSIVE_GROUP = 1


# =========================================================================
# CueImageContext
# =========================================================================

class CueImageContext(CueMarkerContext):
    ONE_SHOT = True

    def _key(self):
        # type: () -> str
        return create_img_key(self._mgr._ctx.current_file)

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
    ONE_SHOT = True

    def _key(self):
        # type: () -> str
        return create_dlg_key((self._mgr._ctx.current_file, self._mgr._ctx.current_dialogue or ""))

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
        return create_vid_key(self._mgr._ctx.current_file) if self._mgr._ctx.current_file else ""

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
        if not self._mgr._sfx_manager.files:
            return
        if file_index < 0 or file_index >= len(self._mgr._sfx_manager.files):
            return
        filename = self._mgr._sfx_manager.files[file_index]
        if filename in self._mgr._sfx_manager.disabled_files:
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
            elapsed = self._mgr._vid_manager.get_elapsed()
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
        if not self._mgr._ctx.current_file:
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
            elapsed = self._mgr._vid_manager.get_elapsed()
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
        elapsed = self._mgr._vid_manager.get_elapsed()
        vid_key = self._key()
        entry = self._mgr._get_or_create_entry(vid_key)
        pools = entry["pools"]
        self._append_pool(entry, pools,
            {"time": elapsed, "files": []})
        self._mgr._db_save_marker(vid_key)

    def apply_preset(self, preset_name):
        # type: (str) -> None
        if not self._mgr._ctx.current_file:
            return
        elapsed = self._mgr._vid_manager.get_elapsed()
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

    def apply_preset_active(self, preset_name):
        # type: (str) -> None
        """Stamp a preset onto the active video pool, creating one at the
        playhead if the context has no pools yet."""
        if not self._mgr._ctx.current_file:
            return
        r = self._mgr.resolve_pool({"preset": preset_name})
        if not r.files:
            return
        vid_key = self._key()
        entry = self._mgr._get_or_create_entry(vid_key)
        pools = entry["pools"]
        if not pools or not (0 <= self.target_pool < len(pools)):
            elapsed = self._mgr._vid_manager.get_elapsed()
            self._append_pool(entry, pools,
                {"time": elapsed, "preset": preset_name})
        else:
            pool = pools[self.target_pool]
            time = pool.get("time", self._mgr._vid_manager.get_elapsed())
            pools[self.target_pool] = {"time": time, "preset": preset_name}
        self.sync_text()
        self._mgr._db_save_marker(vid_key)

    def send_preset(self, preset_name):
        # type: (str) -> None
        if _cue_shift_held():
            self.apply_preset(preset_name)
        else:
            self.apply_preset_active(preset_name)

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
            _, pools = self._entry_and_pools()
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
        _, pools = self._entry_and_pools()
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
        _, pools = self._entry_and_pools()
        dur = self.get_duration()
        new_time = _cue_clamp_time(new_time, dur)
        if 0 <= idx < len(pools):
            pools[idx]["time"] = new_time

    def finalize_drag(self):
        # type: () -> None
        _, pools = self._entry_and_pools()
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
        _, pools = self._entry_and_pools()
        if 0 <= self.target_pool < len(pools):
            self.edit_text = _cue_format_time(pools[self.target_pool]["time"])

    def commit_text(self):
        # type: () -> None
        _, pools = self._entry_and_pools()
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

    def add_interval_selection(self, pool_index):
        # type: (int) -> None
        """Union every marker that continues the clicked-to-active spacing
        into the selection group.

        The spacing is the interval between the clicked marker and the active
        marker.  A marker joins when it lands within
        ``CUE_INTERVAL_SELECT_TOLERANCE`` of a projected grid position
        (active time + k*spacing), so a chain of evenly spaced markers is
        selected in one click.  The active marker is left unchanged -- it
        stays the anchor."""
        _, pools = self._entry_and_pools()
        if not (0 <= pool_index < len(pools)):
            return
        active = self.get_active()
        if not (0 <= active < len(pools)):
            return
        t_click = pools[pool_index]["time"]
        t_active = pools[active]["time"]
        spacing = abs(t_click - t_active)
        if spacing <= CUE_INTERVAL_SELECT_TOLERANCE:
            # No real spacing: the span collapses to a point.
            self.selected.add(active)
            self.selected.add(pool_index)
            return
        for i, pool in enumerate(pools):
            offset = pool["time"] - t_active
            k = round(offset / spacing)
            if abs(offset - k * spacing) <= CUE_INTERVAL_SELECT_TOLERANCE:
                self.selected.add(i)

    def get_duration(self):
        # type: () -> float
        return self._mgr._vid_manager.get_duration()


# =========================================================================
# CueLoopContext
# =========================================================================

class CueLoopContext(CueMarkerContext):
    def __init__(self, manager):
        super(CueLoopContext, self).__init__(manager)

    def _key(self):
        # type: () -> str
        return create_loop_key(self._mgr._ctx.current_file or "")

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
            "volume": CUE_VOLUME_DEFAULT,
            "frequency": CueLoopFrequency.NORMAL,
        })
        self._set_target(len(entry["pools"]) - 1)
        self._mgr._db_save_marker(key)

    def clear(self):
        # type: () -> None
        key = self._key()
        self._mgr.pop(key, None)
        self._mgr._trigger.loop_states.pop(key, None)
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

    @staticmethod
    def get_delay(frequency=CueLoopFrequency.NORMAL):
        # type: (int) -> float
        if frequency == CueLoopFrequency.SLOWEST:
            return 5.0 + _random.uniform(0.0, 2.5)
        elif frequency == CueLoopFrequency.FASTEST:
            return 0.15 + _random.uniform(0.0, 0.05)
        elif frequency == CueLoopFrequency.FAST:
            return 0.5 + _random.uniform(0.0, 0.15)
        elif frequency == CueLoopFrequency.NORMAL:
            return 1.7 + _random.uniform(0.0, .75)
        else:
            return 3.0 + _random.uniform(0.0, 1.5)
