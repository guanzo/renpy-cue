# -*- coding: utf-8 -*-
# Cue*Context -- typed marker contexts (image/dialogue/video/loop) that wrap
# CueMarkerManager's store surface for one trigger key.  Each context owns its
# target index and mutates pools through the manager's public mutators.

import copy as _copy
import random as _random

import renpy.python as _renpy_python

from cue_lib.constants import CUE_VOLUME_DEFAULT, CueExclusiveStart, CueLoopFrequency
from cue_lib.util import (
    _cue_clamp_time,
    _cue_format_time,
    _cue_parse_time,
    _cue_shift_held,
    create_img_key,
    create_vid_key,
    create_dlg_key,
    create_loop_key,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import (
        MarkerEntry,
        PoolDict,
        VideoPoolDict,  # pyright: ignore[reportUnusedImport]
    )

# Nonzero group marks a pool as exclusive. Grouping is derived at runtime
# (scene + line for one-shots; loops never group), so the stored group value
# is just an on/off flag -- any nonzero value works.
CUE_EXCLUSIVE_GROUP = 1

# Matching tolerance for interval selection in the video marker timeline
# (Alt+Shift+Click): a marker counts as continuing the active-to-clicked
# spacing when it lands within +/- this of the projected grid position.
CUE_INTERVAL_SELECT_TOLERANCE = 0.010

# Duplicated markers land a fixed pixel gap after their source on the
# timeline, so the copy doesn't overlap it.  The gap is defined in pixels at a
# reference width and converted to a frac of the timeline width, then to
# seconds via frac * duration -- the same geometry the timeline's _time_to_x
# uses (frac = (t/speed)/dur, at the base speed duplicates are gated to).
CUE_DUPLICATE_GAP_PX = 28  # two 14px marker tabs of separation
CUE_TIMELINE_REF_W = 480  # reference inner width the gap is defined at
CUE_DUPLICATE_GAP_FRAC = CUE_DUPLICATE_GAP_PX / float(CUE_TIMELINE_REF_W)

# =========================================================================
# CueMarkerContext -- pool-based markers (shared by .image and .dialogue)
# =========================================================================


class CueMarkerContext(_renpy_python.NoRollback):
    """Abstract base for pool-based marker contexts."""

    # One-shot contexts (image/dialogue) can't wait for open air, so the
    # "Wait for air" start option is hidden for them in the UI.
    ONE_SHOT = False

    def __init__(self, manager):
        self._mgr = manager
        self.active_pool = 0

    def _key(self):
        # type: () -> str
        raise NotImplementedError("_key must be overridden")

    def add_file(self, file_index):
        # type: (int) -> None
        if not self._mgr._sfx_manager.library.files:
            return
        if file_index < 0 or file_index >= len(self._mgr._sfx_manager.library.files):
            return
        key = self._key()
        filename = self._mgr._sfx_manager.library.files[file_index]
        if filename in self._mgr._sfx_manager.library.disabled_files:
            return
        self._mgr._store.pool(key, self.get_active_index()).add_file(filename)

    def send_file(self, file_index, record=True):
        # type: (int, bool) -> None
        if _cue_shift_held():
            self.add_pool()
        self.add_file(file_index)
        self._clear_add_to_pool_warning()
        # Record on attempt (send_* is the "user asked for this" seam); a
        # disabled or out-of-range file still counts as an attempt, but one
        # we cannot resolve to a path does not.  record=False is passed by
        # recently-used rows so acting from the list doesn't re-feed it.
        if record and 0 <= file_index < len(self._mgr._sfx_manager.library.files):
            self._record_use("file", self._mgr._sfx_manager.library.files[file_index])

    def send_folder(self, folder_path, record=True):
        # type: (str, bool) -> Optional[str]
        """Send a folder to the active pool.  Returns the guardrail error
        string when the add is rejected; a rejected add is not recorded as a
        recent use."""
        if _cue_shift_held():
            self.add_pool()
        err = self.add_folder(folder_path)
        if err is None:
            self._clear_add_to_pool_warning()
            if record:
                self._record_use("folder", folder_path.rstrip("/") + "/")
        return err

    def send_preset(self, preset_name, record=True):
        # type: (str, bool) -> None
        if _cue_shift_held():
            self.add_pool()
        self.apply_preset(preset_name)
        self._clear_add_to_pool_warning()
        if record:
            self._record_use("preset", preset_name)

    def _record_use(self, kind, ref):
        # type: (str, str) -> None
        recent = self._mgr._sfx_manager.library._recent
        if recent is not None:
            recent.record(kind, ref)

    def _clear_add_to_pool_warning(self):
        # type: () -> None
        """Dismiss the add-to-pool guardrail notice after a successful add."""
        library = self._mgr._sfx_manager.library
        if getattr(library, "clear_add_to_pool_warning", None) is not None:
            library.clear_add_to_pool_warning()

    def remove_file(self, pool_index, file_index):
        # type: (int, int) -> None
        key = self._key()
        self._mgr._store._remove_file_from_pool(key, file_index, pool_index)

    def clear(self):
        # type: () -> None
        key = self._key()
        self._mgr.pop(key, None)
        self._mgr._store._save_marker(key)

    def add_pool(self):
        # type: () -> None
        key = self._key()
        entry = self._mgr._store._get_or_create_entry(key)
        entry["pools"].append({"files": [], "volume": CUE_VOLUME_DEFAULT})
        self.active_pool = len(entry["pools"]) - 1
        self._mgr._store._save_marker(key)

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
            self.active_pool = min(self.active_pool, remaining - 1)
        else:
            self.active_pool = 0
        self._mgr._store._save_marker(key)

    def get_active_index(self):
        # type: () -> int
        return self.active_pool

    def set_active_index(self, pool_index):
        # type: (int) -> None
        self.active_pool = int(pool_index)

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
        target = max(0, min(self.get_active_index(), len(pools) - 1))
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
            target = self.get_active_index()
            if 0 <= target < len(pools):
                if payload is None:
                    pools[target].pop("exclusive", None)
                else:
                    pools[target]["exclusive"] = payload
        self._mgr._store._save_marker(key)

    def set_exclusive(self, start, hold):
        # type: (int, bool) -> None
        """Enable exclusive playback on the active pool with a start mode."""
        self._set_exclusive_payload({"group": CUE_EXCLUSIVE_GROUP, "start": int(start), "hold": bool(hold)})

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
        self._mgr._store._stamp_preset(key, preset_name, self.get_active_index())

    def add_folder(self, folder_path):
        # type: (str) -> Optional[str]
        """Add a folder ref to the active pool.  Returns None (folder adds are
        always allowed; a pool's intensity group is now set explicitly, not
        inferred from folder membership)."""
        key = self._key()
        folder_ref = folder_path.rstrip("/") + "/"
        self._mgr._store.pool(key, self.get_active_index()).add_file(folder_ref)
        return None


# =========================================================================
# CueImageContext
# =========================================================================


class CueImageContext(CueMarkerContext):
    ONE_SHOT = True

    def _key(self):
        # type: () -> str
        return create_img_key(self._mgr._ctx.current_file)

    def toggle_shake_trigger(self):
        # type: () -> None
        """Toggle the shake trigger for the current file's image marker."""
        if not self._mgr._ctx.current_file:
            return
        key = self._key()
        pool = self._mgr._store._ensure_pool(key, self.active_pool)
        resolved = self._mgr.resolve_pool(pool)
        pool["trigger_on_shake"] = not resolved.trigger_on_shake
        self._mgr._store._save_marker(key)


# =========================================================================
# CueDialogueContext
# =========================================================================


class CueDialogueContext(CueMarkerContext):
    ONE_SHOT = True

    def _key(self):
        # type: () -> str
        return create_dlg_key((self._mgr._ctx.current_file, self._mgr._ctx.current_dialogue or ""))


# =========================================================================
# CueVideoContext
# =========================================================================


class CueVideoContext(CueMarkerContext):
    def __init__(self, manager):
        super(CueVideoContext, self).__init__(manager)
        self.selected = set()
        self.edit_text = ""

    def _key(self):
        # type: () -> str
        return create_vid_key(self._mgr._ctx.current_file) if self._mgr._ctx.current_file else ""

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
            self.active_pool = new_idx
            return new_idx
        except ValueError:
            self.active_pool = min(self.active_pool, len(pools) - 1)
            return -1

    def _append_pool(self, entry, pools, pool_dict):
        # type: (MarkerEntry, List[Dict[str, Any]], Dict[str, Any]) -> None
        pools.append(pool_dict)
        self._sort_and_track(pools, pool_dict)
        self.selected = set()

    def _add_file(self, vid_key, filename, pool_index):
        # type: (str, str, int) -> None
        """Append *filename* to one pool (detaching a preset; a pool hooked to
        an intensity group owns no refs and is left untouched)."""
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if 0 <= pool_index < len(pools):
            self._mgr._store.pool(vid_key, pool_index).add_file(filename)

    def _remove_file(self, vid_key, path, pool_index):
        # type: (str, str, int) -> None
        """Remove *path* from one pool (detaching a preset; a folder-ref entry
        is removed whole, a child under a folder ref shrinks that ref)."""
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if 0 <= pool_index < len(pools):
            self._mgr._store._remove_ref_from_pool(vid_key, path, pool_index)

    def _remove_path_from_selected(self, path):
        # type: (str) -> None
        """Remove *path* from every selected pool (one save). Entry point for
        preset/folder child deletes in markers.py; no-op when not multi."""
        vid_key = self._key()
        if len(self.selected) <= 1:
            return
        for idx in sorted(self.selected):
            self._remove_file(vid_key, path, idx)
        self._mgr._store._save_marker(vid_key)

    def _add_ref(self, vid_key, ref):
        # type: (str, str) -> None
        """Add *ref* to every selected pool, the active pool, or a fresh pool
        at the playhead when there are no pools yet."""
        entry = self._mgr._store._get_or_create_entry(vid_key)
        pools = entry["pools"]
        if len(self.selected) > 1:
            for idx in sorted(self.selected):
                self._add_file(vid_key, ref, idx)
        elif pools and 0 <= self.active_pool < len(pools):
            self._add_file(vid_key, ref, self.active_pool)
        else:
            elapsed = self._mgr._vid_manager.get_elapsed()
            self._append_pool(entry, pools, {"time": elapsed, "files": [ref]})
        self._mgr._store._save_marker(vid_key)

    def add_file(self, file_index):
        # type: (int) -> None
        if not self._mgr._sfx_manager.library.files:
            return
        if file_index < 0 or file_index >= len(self._mgr._sfx_manager.library.files):
            return
        filename = self._mgr._sfx_manager.library.files[file_index]
        if filename in self._mgr._sfx_manager.library.disabled_files:
            return
        self._add_ref(self._key(), filename)

    def remove_file(self, pool_index, file_index):
        # type: (int, int) -> None
        vid_key = self._key()
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        self._mgr._store._detach_pool(vid_key, pool_index)
        ref_files = pools[pool_index].get("files", [])
        if not (0 <= file_index < len(ref_files)):
            return
        path = ref_files[file_index]
        if len(self.selected) > 1:
            for idx in sorted(self.selected):
                self._remove_file(vid_key, path, idx)
        else:
            self._remove_file(vid_key, path, pool_index)
        self._mgr._store._save_marker(vid_key)

    def add_folder(self, folder_path):
        # type: (str) -> Optional[str]
        """Add a folder ref to the target video pool(s).  Returns None (folder
        adds are always allowed; a pool's intensity group is now set explicitly,
        not inferred from folder membership)."""
        if not self._mgr._ctx.current_file:
            return None
        self._add_ref(self._key(), folder_path.rstrip("/") + "/")
        return None

    def clear(self):
        # type: () -> None
        super(CueVideoContext, self).clear()
        self.active_pool = 0
        self.selected = set()

    def add_pool(self):
        # type: () -> None
        elapsed = self._mgr._vid_manager.get_elapsed()
        vid_key = self._key()
        entry = self._mgr._store._get_or_create_entry(vid_key)
        pools = entry["pools"]
        self._append_pool(entry, pools, {"time": elapsed, "files": []})
        self._mgr._store._save_marker(vid_key)

    def apply_preset(self, preset_name):
        # type: (str) -> None
        if not self._mgr._ctx.current_file:
            return
        elapsed = self._mgr._vid_manager.get_elapsed()
        r = self._mgr.resolve_pool({"preset": preset_name})
        if not r.refs:
            return
        vid_key = self._key()
        entry = self._mgr._store._get_or_create_entry(vid_key)
        pools = entry["pools"]
        self._append_pool(entry, pools, {"time": elapsed, "preset": preset_name})
        self.sync_text()
        self._mgr._store._save_marker(vid_key)

    def apply_preset_active(self, preset_name):
        # type: (str) -> None
        """Stamp a preset onto the active (or every selected) video pool,
        creating one at the playhead if the context has no pools yet."""
        if not self._mgr._ctx.current_file:
            return
        r = self._mgr.resolve_pool({"preset": preset_name})
        if not r.refs:
            return
        vid_key = self._key()
        entry = self._mgr._store._get_or_create_entry(vid_key)
        pools = entry["pools"]
        if len(self.selected) > 1:
            for idx in sorted(self.selected):
                if 0 <= idx < len(pools):
                    time = pools[idx].get("time", self._mgr._vid_manager.get_elapsed())
                    pools[idx] = {"time": time, "preset": preset_name}
        elif not pools or not (0 <= self.active_pool < len(pools)):
            elapsed = self._mgr._vid_manager.get_elapsed()
            self._append_pool(entry, pools, {"time": elapsed, "preset": preset_name})
        else:
            pool = pools[self.active_pool]
            time = pool.get("time", self._mgr._vid_manager.get_elapsed())
            pools[self.active_pool] = {"time": time, "preset": preset_name}
        self.sync_text()
        self._mgr._store._save_marker(vid_key)

    def hook_level(self, group, ilevel_id):
        # type: (str, int) -> None
        """Attach the active (or every selected) video pool to intensity level
        *ilevel_id* of *group*, clearing each pool's own refs (the pool fires
        from the active level).  One save for the whole fan-out."""
        vid_key = self._key()
        if not vid_key:
            return
        entry = self._mgr._store._get_or_create_entry(vid_key)
        pools = entry["pools"]
        if len(self.selected) > 1:
            for idx in sorted(self.selected):
                if 0 <= idx < len(pools):
                    self._hook_level_on_pool(pools[idx], group, ilevel_id)
        elif not pools or not (0 <= self.active_pool < len(pools)):
            elapsed = self._mgr._vid_manager.get_elapsed()
            self._append_pool(
                entry, pools, {"time": elapsed, "files": [], "igroup": {"name": group, "level": ilevel_id}}
            )
        else:
            self._hook_level_on_pool(pools[self.active_pool], group, ilevel_id)
        self._mgr._store._save_marker(vid_key)

    def _hook_level_on_pool(self, pool, group, ilevel_id):
        # type: (Dict[str, Any], str, int) -> None
        """Stamp the intensity hook onto one pool: playhead time if absent,
        then the group/level, dropping the pool's own refs."""
        if "time" not in pool:
            pool["time"] = self._mgr._vid_manager.get_elapsed()
        pool["igroup"] = {"name": group, "level": ilevel_id}
        pool["files"] = []

    def send_preset(self, preset_name, record=True):
        # type: (str, bool) -> None
        if _cue_shift_held():
            self.apply_preset(preset_name)
        else:
            self.apply_preset_active(preset_name)
        if record:
            self._record_use("preset", preset_name)

    def remove_pool(self, pool_index):
        # type: (int) -> None
        super(CueVideoContext, self).remove_pool(pool_index)
        self.selected = set()

    def delete_pool_ui(self):
        # type: () -> None
        """Per-pool delete button: act on the whole selected group when
        multi-selected, else on the active pool."""
        if len(self.selected) > 1:
            self.remove_selected()
        else:
            self.remove_pool(self.active_pool)

    def _duplicate_gap(self):
        # type: () -> float
        """Time offset a duplicate sits after its source: the fixed pixel gap
        converted via the timeline's frac geometry (gap_frac * duration)."""
        return CUE_DUPLICATE_GAP_FRAC * self.get_duration()

    def duplicate_pool(self, ts_index):
        # type: (int) -> None
        """Duplicate the selected pools (multi) or the pool at *ts_index*.

        Each copy lands a fixed pixel gap after its source so it doesn't
        overlap on the timeline.  The copies become the selection; the old
        selection clears."""
        vid_key = self._key()
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if not pools:
            return
        if len(self.selected) > 1:
            targets = sorted(self.selected)
        else:
            targets = [ts_index]
        if not (0 <= targets[0] < len(pools)):
            return
        gap = self._duplicate_gap()
        copies = []
        for idx in targets:
            if not (0 <= idx < len(pools)):
                continue
            original = pools[idx]
            clone = _copy.deepcopy(original)
            clone["time"] = _cue_clamp_time(original.get("time", 0.0) + gap, self.get_duration())
            pools.append(clone)
            copies.append(clone)
        pools.sort(key=lambda e: e["time"])
        new_sel = set()
        for clone in copies:
            new_sel.add(next(i for i, pool in enumerate(pools) if pool is clone))
        self.selected = new_sel
        if new_sel:
            self.active_pool = min(new_sel)
        self._mgr._store._save_marker(vid_key)

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
                    self.active_pool = 0
                else:
                    self.active_pool = min(self.active_pool, len(pools) - 1)
            self.selected = set()
            self._mgr._store._save_marker(self._key())
        else:
            self.remove_pool(self.active_pool)

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
            return "Delete marker {}?".format(self.active_pool + 1)

    def set_active_index(self, pool_index):
        # type: (int) -> None
        super(CueVideoContext, self).set_active_index(pool_index)
        self.sync_text()

    def select_tab(self, pool_index):
        # type: (int) -> None
        self.selected = set()
        self.set_active_index(pool_index)

    def clear_selection(self):
        # type: () -> None
        """Drop the multi-select set; the active marker stays put."""
        self.selected = set()

    def set_selected_volume(self, value):
        # type: (float) -> None
        """Write *value* to every selected pool's volume.

        Multi-select edit path; preset-backed pools get a volume override
        (matching single-pool volume edits) rather than a detach. No save --
        the caller (_CueVolumeValue.changed) queues the write so slider drags
        coalesce into one disk write."""
        vid_key = self._key()
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])

        if len(self.selected) <= 1:
            return
        for idx in sorted(self.selected):
            if 0 <= idx < len(pools):
                pools[idx]["volume"] = value

    def clear_selected_files(self):
        # type: () -> None
        """Clear the files list of every selected pool (active when not
        multi-selected), detaching preset-backed pools first."""
        vid_key = self._key()
        entry = self._mgr.get(vid_key, {})
        pools = entry.get("pools", [])
        if len(self.selected) > 1:
            targets = sorted(self.selected)
        elif 0 <= self.active_pool < len(pools):
            targets = [self.active_pool]
        else:
            return
        for idx in targets:
            if 0 <= idx < len(pools):
                self._mgr._store.pool(vid_key, idx).clear_files()
        self._mgr._store._save_marker(vid_key)

    def _shift_pool_time(self, pools, idx, delta):
        # type: (List[Dict[str, Any]], int, float) -> None
        """Add *delta* to one pool's time, clamped to [0, duration]."""
        if 0 <= idx < len(pools):
            dur = self.get_duration()
            pools[idx]["time"] = _cue_clamp_time(pools[idx].get("time", 0.0) + delta, dur)

    def nudge(self, delta):
        # type: (float) -> None
        _, pools = self._entry_and_pools()
        if not (0 <= self.active_pool < len(pools)):
            return
        if len(self.selected) > 1:
            for idx in sorted(self.selected):
                self._shift_pool_time(pools, idx, delta)
            self.finalize_drag()
            self.sync_text()
            return
        self._shift_pool_time(pools, self.active_pool, delta)
        self._sort_and_track(pools, pools[self.active_pool])
        self.edit_text = _cue_format_time(pools[self.active_pool]["time"])
        self.selected = set()
        self._mgr._store._save_marker(self._key())

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
        pi = self.active_pool
        if 0 <= pi < len(pools):
            self._sort_and_track(pools, pools[pi])
        if sel_objects:
            new_sel = set()
            for i, pool in enumerate(pools):
                if id(pool) in sel_objects:
                    new_sel.add(i)
            self.selected = new_sel
            if new_sel:
                self.active_pool = min(new_sel)
        self._mgr._store._save_marker(self._key())

    def sync_text(self):
        # type: () -> None
        _, pools = self._entry_and_pools()
        if 0 <= self.active_pool < len(pools):
            self.edit_text = _cue_format_time(pools[self.active_pool]["time"])

    def commit_text(self):
        # type: () -> None
        _, pools = self._entry_and_pools()
        if not (0 <= self.active_pool < len(pools)):
            return
        new_time = _cue_parse_time(self.edit_text)
        if new_time is not None and new_time >= 0:
            if len(self.selected) > 1:
                anchor_time = pools[self.active_pool]["time"]
                for idx in sorted(self.selected):
                    self._shift_pool_time(pools, idx, new_time - anchor_time)
                self.finalize_drag()
                self.sync_text()
            else:
                self._shift_pool_time(pools, self.active_pool, new_time - pools[self.active_pool]["time"])
                self._sort_and_track(pools, pools[self.active_pool])
                self.selected = set()
                self._mgr._store._save_marker(self._key())
        self.edit_text = _cue_format_time(pools[self.active_pool]["time"])

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
        (active time + k*spacing) in the direction of the click -- markers
        behind the active are never pulled in, so an interval select extends
        only forward (or backward) from the active.  The active marker is
        left unchanged -- it stays the anchor."""
        _, pools = self._entry_and_pools()
        if not (0 <= pool_index < len(pools)):
            return
        active = self.get_active_index()
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
        direction = 1 if t_click >= t_active else -1
        for i, pool in enumerate(pools):
            offset = pool["time"] - t_active
            if offset * direction < 0:
                continue
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

    def add_pool(self):
        # type: () -> None
        key = self._key()
        entry = self._mgr._store._get_or_create_entry(key)
        entry["pools"].append({"files": [], "volume": CUE_VOLUME_DEFAULT, "frequency": CueLoopFrequency.MEDIUM})
        self.active_pool = len(entry["pools"]) - 1
        self._mgr._store._save_marker(key)

    def clear(self):
        # type: () -> None
        key = self._key()
        self._mgr.pop(key, None)
        self._mgr._trigger.loop.loop_states.pop(key, None)
        self._mgr._store._save_marker(key)

    def set_frequency(self, freq):
        # type: (int) -> None
        key = self._key()
        target = self.get_active_index()
        entry = self._mgr.get(key)
        if entry:
            pools = entry.get("pools", [])
            if pools and 0 <= target < len(pools):
                pools[target]["frequency"] = int(freq)
                self._mgr._store._save_marker(key)

    @staticmethod
    def get_delay(frequency=CueLoopFrequency.MEDIUM):
        # type: (int) -> float
        if frequency == CueLoopFrequency.SLOWEST:
            return 5.0 + _random.uniform(0.0, 2.5)
        elif frequency == CueLoopFrequency.FASTEST:
            return 0.15 + _random.uniform(0.0, 0.05)
        elif frequency == CueLoopFrequency.FAST:
            return 0.5 + _random.uniform(0.0, 0.15)
        elif frequency == CueLoopFrequency.MEDIUM:
            return 1.7 + _random.uniform(0.0, 0.75)
        else:
            return 3.0 + _random.uniform(0.0, 1.5)
