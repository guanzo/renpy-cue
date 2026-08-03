###############################################################################
# CueMarkerManager — unified marker CRUD with typed context accessors.
# Instantiated once at _cue.markers, lives on the NoRollback _cue object.
#
# API:
#   _cue.markers.image.add_file(idx)          Pool-based (i: prefix)
#   _cue.markers.dialogue.add_file(idx)       Pool-based (d: prefix)
#   _cue.markers.video.add_file(idx)          Timestamp-based (v: prefix)
#   _cue.markers.autoplay.add_file(idx)       Pool-based (a: prefix)
#
#   _cue.markers[key] / .get(key) / .items()  Dict-like access (backward compat)
#   _cue.markers.save() / .dump() / .restore()  Persistence
#   _cue.markers.copy_context() / .paste_context()  Clipboard
###############################################################################

init -999 python:

    # =========================================================================
    # CueMarkerContext — pool-based markers (shared by .image and .dialogue)
    # =========================================================================

    class CueMarkerContext:
        """Manage marker pools for a single context kind (image or dialogue).

        An "entry" is the dict stored at a trigger key like "i:bg_room.png":
            {"pools": [{"files": [...], "volume": 1.0}, ...]}

        Each pool is a group of SFX files that play together when the context
        is triggered. The "active" pool is the tab the UI has selected — the
        next add_file() call targets it.
        """

        def __init__(self, manager, kind):
            self._mgr = manager
            self._kind = kind  # "img" or "dlg"

        # -- internal helpers --

        def _key(self):
            """Build the trigger key for the current scene context."""
            if self._kind == "img":
                return create_img_key(_cue.current_file)
            elif self._kind == "dlg":
                if not _cue.current_dialogue:
                    return None
                return create_dlg_key((_cue.current_file, _cue.current_dialogue))
            return None

        def _get_target(self):
            if self._kind == "img":
                return self._mgr._img_target
            return self._mgr._dlg_target

        def _set_target(self, value):
            if self._kind == "img":
                self._mgr._img_target = int(value)
            else:
                self._mgr._dlg_target = int(value)

        # -- public API --

        def add_file(self, file_index):
            """Add an audio file to the active pool. Creates entry/pool as needed."""
            if not _cue.available_files:
                return
            if file_index < 0 or file_index >= len(_cue.available_files):
                return
            key = self._key()
            if key is None:
                return
            filename = _cue.available_files[file_index]
            if filename in _cue.disabled_files:
                return
            self._mgr._add_file_to_pool(key, filename, self.get_active())

        def remove_file(self, pool_index, file_index):
            """Remove a file from a specific pool."""
            key = self._key()
            if key is None:
                return
            self._mgr._remove_file_from_pool(key, file_index, pool_index)

        def clear(self):
            """Remove all pools for the current context."""
            key = self._key()
            if key is None:
                return
            self._mgr.pop(key, None)
            self._mgr.save()

        def add_pool(self):
            """Append a new empty pool and auto-switch to it."""
            key = self._key()
            if key is None:
                return
            entry = self._mgr._get_or_create_entry(key)
            entry["pools"].append({
                "files": [],
                "volume": _cue.VOL_DEFAULT,
            })
            self._set_target(len(entry["pools"]) - 1)
            self._mgr.save()

        def remove_pool(self, pool_index):
            """Delete a pool. Removes the entry when no pools remain.
            Clamps the active index so the UI highlight stays valid."""
            key = self._key()
            if key is None:
                return
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
            self._mgr.save()

        def get_active(self):
            """Return the active pool index."""
            return self._get_target()

        def set_active(self, pool_index):
            """Set which pool new files are added to."""
            self._set_target(pool_index)

        def add_folder(self, folder_path):
            """Add all files under a folder prefix to the active pool."""
            key = self._key()
            if key is None:
                return
            pool = self._mgr._ensure_pool(key, self.get_active())
            files = pool.setdefault("files", [])
            for f in _cue.available_files:
                if f.startswith(folder_path) and f not in files and f not in _cue.disabled_files:
                    files.append(f)
            self._mgr.save()


    # =========================================================================
    # CueVideoContext — timestamp-based markers (v: prefix)
    # =========================================================================

    class CueVideoContext(CueMarkerContext):
        """Manage timestamp cue-points on a video timeline.

        A video entry looks like:
            {"timestamps": [
                {"time": 12.5, "files": ["moan1.ogg"], "volume": 1.0},
                {"time": 45.2, "files": ["scream.ogg"]},
            ], "volume": 1.0}

        Extends CueMarkerContext with time-based operations: drag, nudge,
        multi-select, and the CDD callback interface.
        """

        def __init__(self, manager):
            super(CueVideoContext, self).__init__(manager, "vid")
            self.target_pool = 0     # active timestamp index
            self.selected = set()    # multi-selection indices
            self.edit_text = ""      # time-edit input buffer

        # -- internal --

        def _key(self):
            """Build the v: key for the current video context."""
            return create_vid_key(_cue.current_file) if _cue.current_file else ""

        def _entry_and_timestamps(self):
            """Return (entry, timestamps) for the current video, or (None, [])."""
            vid_key = self._key()
            if not vid_key:
                return None, []
            entry = self._mgr.get(vid_key)
            if entry is None:
                return None, []
            return entry, entry.get("timestamps", [])

        def _sort_and_track(self, timestamps, tracked_entry):
            """Sort timestamps by time and update target_pool to tracked_entry's
            new index. Returns the new index, or -1 if not found."""
            timestamps.sort(key=lambda e: e["time"])
            try:
                new_idx = timestamps.index(tracked_entry)
                self.target_pool = new_idx
                return new_idx
            except ValueError:
                self.target_pool = min(self.target_pool, len(timestamps) - 1)
                return -1

        # -- public API (extends CueMarkerContext) --

        def add_file(self, file_index):
            """Add an audio file to the active timestamp pool. Creates a new
            timestamp at the current video position if no timestamps exist or
            the active target is out of range."""
            if not _cue.available_files:
                return
            if file_index < 0 or file_index >= len(_cue.available_files):
                return
            ch = _cue.active_channel
            if not ch or not renpy.music.is_playing(channel=ch):
                return
            elapsed = _cue.vid_manager.get_elapsed()
            if elapsed is None or elapsed <= 0:
                return
            filename = _cue.available_files[file_index]
            if filename in _cue.disabled_files:
                return
            vid_key = self._key()
            entry = self._mgr.setdefault(vid_key, {"timestamps": []})
            timestamps = entry.setdefault("timestamps", [])
            if timestamps and 0 <= self.target_pool < len(timestamps):
                # Add to existing active timestamp
                files = timestamps[self.target_pool].setdefault("files", [])
                if filename not in files:
                    files.append(filename)
            else:
                # Create new timestamp at current video position
                timestamps.append({"time": elapsed, "files": [filename]})
                timestamps.sort(key=lambda e: e["time"])
                self.target_pool = len(timestamps) - 1
                self.selected = set()
            self._mgr.save()

        def remove_file(self, ts_index, file_index):
            """Remove a single file from a timestamp's files list.
            Keeps the timestamp even if files becomes empty."""
            vid_key = self._key()
            entry = self._mgr.get(vid_key, {})
            timestamps = entry.get("timestamps", [])
            if not (0 <= ts_index < len(timestamps)):
                return
            files = timestamps[ts_index].get("files", [])
            if 0 <= file_index < len(files):
                files.pop(file_index)
                _cue.played_video_keys.clear()
                self._mgr.save()

        def add_folder(self, folder_path):
            """Add all files under a folder prefix to the active timestamp pool.
            Creates a new timestamp when none exist (requires playing video)."""
            if not _cue.current_file:
                return
            vid_key = self._key()
            entry = self._mgr.setdefault(vid_key, {"timestamps": []})
            timestamps = entry.setdefault("timestamps", [])
            if timestamps and 0 <= self.target_pool < len(timestamps):
                # Add to existing active timestamp
                pool_files = timestamps[self.target_pool].setdefault("files", [])
                for f in _cue.available_files:
                    if f.startswith(folder_path) and f not in pool_files and f not in _cue.disabled_files:
                        pool_files.append(f)
            else:
                # Create new timestamp at current video position
                ch = _cue.active_channel
                if not ch or not renpy.music.is_playing(channel=ch):
                    return
                elapsed = _cue.vid_manager.get_elapsed()
                if elapsed is None or elapsed <= 0:
                    return
                new_files = []
                for f in _cue.available_files:
                    if f.startswith(folder_path) and f not in _cue.disabled_files:
                        new_files.append(f)
                if new_files:
                    timestamps.append({"time": elapsed, "files": new_files})
                    timestamps.sort(key=lambda e: e["time"])
                    self.target_pool = len(timestamps) - 1
            self._mgr.save()

        def clear(self):
            """Remove all video markers for the current context."""
            vid_key = self._key()
            self._mgr.pop(vid_key, None)
            _cue.played_video_keys.clear()
            self.target_pool = 0
            self.selected = set()
            self._mgr.save()

        def add_pool(self):
            """Create a new empty timestamp at the current video position."""
            ch = _cue.active_channel
            if not ch or not renpy.music.is_playing(channel=ch):
                return
            elapsed = _cue.vid_manager.get_elapsed()
            if elapsed is None or elapsed <= 0:
                return
            vid_key = self._key()
            entry = self._mgr.setdefault(vid_key, {"timestamps": []})
            timestamps = entry.setdefault("timestamps", [])
            timestamps.append({"time": elapsed, "files": []})
            timestamps.sort(key=lambda e: e["time"])
            self.target_pool = len(timestamps) - 1
            self.selected = set()
            self._mgr.save()

        def remove_pool(self, ts_index):
            """Delete a timestamp pool by index. Clamps target_pool."""
            entry, timestamps = self._entry_and_timestamps()
            if not timestamps or not (0 <= ts_index < len(timestamps)):
                return
            timestamps.pop(ts_index)
            if not timestamps:
                del self._mgr[self._key()]
                self.target_pool = 0
            else:
                self.target_pool = min(self.target_pool, len(timestamps) - 1)
            _cue.played_video_keys.clear()
            self.selected = set()
            self._mgr.save()

        def duplicate_pool(self, ts_index):
            """Clone a timestamp with all settings (time, volume, file list).
            Appends the clone, sorts by time, and switches to the new pool."""
            vid_key = self._key()
            entry = self._mgr.get(vid_key, {})
            timestamps = entry.get("timestamps", [])
            if not (0 <= ts_index < len(timestamps)):
                return
            original = timestamps[ts_index]
            clone = {
                "time": original["time"],
                "volume": original.get("volume", _cue.VOL_DEFAULT),
                "files": list(original.get("files", [])),
            }
            timestamps.append(clone)
            timestamps.sort(key=lambda e: e["time"])
            self.target_pool = timestamps.index(clone)
            self.selected = set()
            self._mgr.save()

        def remove_selected(self):
            """Delete selected markers (multi-selection) or the active pool
            (single). Removes in descending order to avoid index-shift bugs."""
            if len(self.selected) > 1:
                entry, timestamps = self._entry_and_timestamps()
                if timestamps:
                    for idx in sorted(self.selected, reverse=True):
                        if 0 <= idx < len(timestamps):
                            timestamps.pop(idx)
                    if not timestamps:
                        del self._mgr[self._key()]
                        self.target_pool = 0
                    else:
                        self.target_pool = min(self.target_pool, len(timestamps) - 1)
                _cue.played_video_keys.clear()
                self.selected = set()
                self._mgr.save()
            else:
                # Single — delegate to per-pool delete
                self.remove_pool(self.target_pool)

        def get_delete_message(self):
            """Build the confirmation message for marker deletion."""
            if len(self.selected) > 1:
                nums = ", ".join(str(i + 1) for i in sorted(self.selected))
                return "Delete markers {}?".format(nums)
            else:
                return "Delete marker {}?".format(self.target_pool + 1)

        def set_active(self, pool_index):
            """Set which timestamp pool tab is active.
            Clears multi-selection since this is an explicit single-pool switch."""
            self.target_pool = int(pool_index)
            self.selected = set()
            self.sync_text()

        # -- timestamp editing --

        def nudge(self, delta):
            """Nudge the active timestamp's time by delta seconds.
            Updates both the data entry and the edit text buffer."""
            entry, timestamps = self._entry_and_timestamps()
            if not (0 <= self.target_pool < len(timestamps)):
                return
            ts_entry = timestamps[self.target_pool]
            dur = self.get_duration()
            new_time = ts_entry["time"] + delta
            if dur > 0:
                new_time = max(0.0, min(new_time, dur - 0.05))
            else:
                new_time = max(0.0, new_time)
            ts_entry["time"] = new_time
            self._sort_and_track(timestamps, ts_entry)
            self.edit_text = _cue_format_time(new_time)
            _cue.played_video_keys.clear()
            self.selected = set()
            self._mgr.save()

        def set_time(self, idx, new_time):
            """Write a marker timestamp during drag — no sort/save (done on
            release). Hot path, called every frame during a drag."""
            entry, timestamps = self._entry_and_timestamps()
            dur = self.get_duration()
            new_time = max(0.0, min(new_time, dur - 0.05)) if dur > 0 else max(0.0, new_time)
            if 0 <= idx < len(timestamps):
                timestamps[idx]["time"] = new_time

        def finalize_drag(self):
            """Sort timestamps and save after a drag ends. Rebuilds the
            multi-selection set after re-sort since indices may shift."""
            entry, timestamps = self._entry_and_timestamps()
            if not timestamps:
                return

            # Capture selected timestamp identities before sorting
            sel_objects = set()
            for idx in self.selected:
                if 0 <= idx < len(timestamps):
                    sel_objects.add(id(timestamps[idx]))

            pi = self.target_pool
            if 0 <= pi < len(timestamps):
                self._sort_and_track(timestamps, timestamps[pi])

            # Rebuild selection from new indices after sort
            if sel_objects:
                new_sel = set()
                for i, ts in enumerate(timestamps):
                    if id(ts) in sel_objects:
                        new_sel.add(i)
                self.selected = new_sel
                if new_sel:
                    self.target_pool = min(new_sel)

            self._mgr.save()

        def sync_text(self):
            """Load the active timestamp's value into the edit text buffer."""
            entry, timestamps = self._entry_and_timestamps()
            if 0 <= self.target_pool < len(timestamps):
                self.edit_text = _cue_format_time(timestamps[self.target_pool]["time"])

        def commit_text(self):
            """Parse the edit text buffer and update the active timestamp.
            Tracks the active tab after re-sort."""
            entry, timestamps = self._entry_and_timestamps()
            if not (0 <= self.target_pool < len(timestamps)):
                return
            new_time = _cue_parse_time(self.edit_text)
            if new_time is not None and new_time >= 0:
                edited_entry = timestamps[self.target_pool]
                dur = self.get_duration()
                if dur > 0:
                    new_time = max(0.0, min(new_time, dur - 0.05))
                edited_entry["time"] = new_time
                self._sort_and_track(timestamps, edited_entry)
                _cue.played_video_keys.clear()
                self.selected = set()
                self._mgr.save()
            # Reformat buffer — shows current value, or feedback on parse failure
            self.edit_text = _cue_format_time(timestamps[self.target_pool]["time"])

        # -- CDD callback interface (injected into _VideoMarkerTimeline) --

        def get_markers(self):
            """Return the list of timestamp dicts for the current video."""
            _, timestamps = self._entry_and_timestamps()
            return timestamps

        def get_active(self):
            """Return the active timestamp index."""
            return self.target_pool

        def get_selected(self):
            """Return the set of multi-selected marker indices."""
            return self.selected

        def get_duration(self):
            """Return video duration, floored at 0.001."""
            return max(0.001, _cue.vid_manager.get_duration())

    # =========================================================================
    # CueAutoplayContext — pool-based (a: prefix), mirrors image/dialogue
    # =========================================================================

    class CueAutoplayContext(CueMarkerContext):
        """Manage autoplay markers — pool-based, mirrors image/dialogue.

        An autoplay entry looks like:
            {"pools": [{"files": [...], "volume": 1.0, "frequency": 1}, ...],
             "volume": 1.0}
        """

        def __init__(self, manager):
            super(CueAutoplayContext, self).__init__(manager, "auto")

        def _key(self):
            """Build the a: key for the current context."""
            if not _cue.current_file:
                return None
            return create_autoplay_key(_cue.current_file)

        def _get_target(self):
            return self._mgr._autoplay_target

        def _set_target(self, value):
            self._mgr._autoplay_target = int(value)

        def add_pool(self):
            """Append a new empty pool (with frequency) and auto-switch to it."""
            key = self._key()
            if key is None:
                return
            entry = self._mgr._get_or_create_entry(key)
            entry["pools"].append({
                "files": [],
                "volume": _cue.VOL_DEFAULT,
                "frequency": 1,
            })
            self._set_target(len(entry["pools"]) - 1)
            self._mgr.save()

        def clear(self):
            """Remove autoplay markers for the current context."""
            key = self._key()
            if key is None:
                return
            self._mgr.pop(key, None)
            _cue.autoplay_states.pop(key, None)
            self._mgr.save()

        def set_frequency(self, freq):
            """Set autoplay frequency for the active pool. 0=Slow, 1=Normal, 2=Fast, 3=Fastest."""
            key = self._key()
            if key is None:
                return
            entry = self._mgr.get(key)
            if entry:
                pools = entry.get("pools", [])
                target = self.get_active()
                if pools and 0 <= target < len(pools):
                    pools[target]["frequency"] = int(freq)
                    self._mgr.save()

        @staticmethod
        def get_delay(frequency=1):
            """Return random breathing room (silence) between SFX.
            This is the gap AFTER an SFX finishes before the next one starts."""
            import random
            if frequency == 3:
                return 0.15 + random.uniform(0.0, 0.05)
            elif frequency == 2:
                return 0.5 + random.uniform(0.0, 0.15)
            elif frequency == 1:
                return 1.7 + random.uniform(0.0, .75)
            else:
                return 3.0 + random.uniform(0.0, 1.5)

    # =========================================================================
    # CueMarkerManager — top-level marker database
    # =========================================================================

    class CueMarkerManager:
        """Unified marker database with dict-like access and typed accessors.

        Usage:
            _cue.markers["key"]          # dict-like get
            _cue.markers.image.add_file(idx)
            _cue.markers.video.nudge(0.01)
            _cue.markers.save()
        """

        def __init__(self):
            self._data = {}
            self._img_target = 0
            self._dlg_target = 0
            self._autoplay_target = 0
            self.image = CueMarkerContext(self, "img")
            self.dialogue = CueMarkerContext(self, "dlg")
            self.video = CueVideoContext(self)
            self.autoplay = CueAutoplayContext(self)
            self.clipboard = None

        # -- dict-like interface (backward compat) --

        def __getitem__(self, key):
            return self._data[key]

        def __setitem__(self, key, value):
            self._data[key] = value

        def __delitem__(self, key):
            del self._data[key]

        def __contains__(self, key):
            return key in self._data

        def get(self, key, default=None):
            return self._data.get(key, default)

        def setdefault(self, key, default):
            return self._data.setdefault(key, default)

        def pop(self, key, *args):
            return self._data.pop(key, *args)

        def items(self):
            return self._data.items()

        def keys(self):
            return self._data.keys()

        def __len__(self):
            return len(self._data)

        # -- internal helpers (used by context accessors) --

        def _normalize_entry(self, entry):
            """Migrate legacy {'files': [...]} to {'pools': [{'files': [...]}]}
            in place. Preserves entry-level keys (volume, frequency, etc.)."""
            if entry is None:
                return entry
            if "pools" not in entry:
                entry["pools"] = [{"files": entry.pop("files", [])}]
            return entry

        def _get_or_create_entry(self, trigger_key):
            """Get the entry dict for trigger_key, creating it in pools format."""
            entry = self._data.get(trigger_key)
            if entry is None:
                entry = {"pools": []}
                self._data[trigger_key] = entry
            return self._normalize_entry(entry)

        def _ensure_pool(self, trigger_key, pool_index):
            """Return the pool dict at pool_index, creating entry/pools as needed.
            Clamps out-of-range pool_index to last pool; creates pool 0 when empty."""
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
            """Append a file to a specific pool. Creates entry/pool if needed."""
            pool = self._ensure_pool(trigger_key, pool_index)
            files = pool.setdefault("files", [])
            if filename not in files:
                files.append(filename)
            self.save()

        def _remove_file_from_pool(self, trigger_key, file_index, pool_index=0):
            """Remove a file from a pool. Prunes empty pools and entries."""
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
                self.save()
            elif "files" in entry:
                # Legacy path — a: entries and un-migrated entries
                files = entry["files"]
                if 0 <= file_index < len(files):
                    files.pop(file_index)
                    if not files:
                        del self._data[trigger_key]
                    self.save()

        def _normalize_all(self):
            """Migrate all legacy i:, d:, and a: entries to pools format.
            Also moves entry-level frequency into each autoplay pool.
            Returns True if any entry was changed."""
            changed = False
            for key, entry in list(self._data.items()):
                if is_img_key(key) or is_dlg_key(key) or is_autoplay_key(key):
                    if "pools" not in entry:
                        self._normalize_entry(entry)
                        changed = True
                # Migrate entry-level frequency into each autoplay pool
                if is_autoplay_key(key) and "frequency" in entry:
                    freq = entry.pop("frequency")
                    for pool in entry.get("pools", []):
                        pool.setdefault("frequency", freq)
                    changed = True
            return changed

        def _sanitize_video_timestamps(self):
            """Strip entries missing 'time' from all video timestamp lists.
            Returns the number of entries stripped."""
            total_stripped = 0
            for key, entry in list(self._data.items()):
                if not is_vid_key(key):
                    continue
                timestamps = entry.get("timestamps")
                if not timestamps:
                    continue
                stripped = 0
                clean = []
                for ts in timestamps:
                    if ts.get("time") is not None:
                        clean.append(ts)
                    else:
                        stripped += 1
                if stripped:
                    entry["timestamps"] = clean
                    total_stripped += stripped
            return total_stripped

        # -- persistence --

        def save(self):
            """Persist markers to Ren'Py persistent storage. Automatically
            strips malformed video timestamps before writing."""
            # Sanitize before persisting
            stripped = self._sanitize_video_timestamps()
            if stripped:
                _cue_log("SAVE-MARKERS: sanitized {} malformed video timestamp(s)".format(stripped))

            data = python_dict({
                "markers": python_dict(self._data),
                "disabled_files": python_list(_cue.disabled_files),
                "triggers_active": python_list([_cue.triggers_active]),
            })
            persistent._cue_markers = data

            # Autosave backup to disk (throttled to once per 5 min)
            self._autosave_backup()

        def _autosave_backup(self):
            """Write a backup copy to disk, throttled to once per 5 minutes.

            Saves to auto_backups/ with a Unix timestamp suffix. Keeps the last
            50 copies, deleting older ones.
            """
            import time as _time
            now = _time.time()
            if now - getattr(_cue, '_last_autosave_time', 0) < 300:
                return
            _cue._last_autosave_time = now
            try:
                import json as _json
                import glob as _glob
                backup_dir = os.path.join(renpy.config.gamedir, _cue.base_dir, "auto_backups")
                if not os.path.isdir(backup_dir):
                    os.makedirs(backup_dir)
                # Generate timestamped filename
                dump_path = os.path.join(backup_dir, "cue_config_{}.json".format(int(now)))
                data = getattr(persistent, '_cue_markers', None)
                if data is None:
                    self.save()
                    data = getattr(persistent, '_cue_markers', {})
                with open(dump_path, "w") as f:
                    _json.dump(data, f, indent=2, sort_keys=True)
                # Prune to last 50 backups
                backups = sorted(_glob.glob(os.path.join(backup_dir, "cue_config_*.json")))
                if len(backups) > 50:
                    for old in backups[:-50]:
                        try:
                            os.remove(old)
                        except Exception:
                            pass
            except Exception:
                pass  # best-effort

        def dump(self):
            """Dump entire persistent._cue_markers to disk."""
            try:
                import json as _json
                dump_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)
                if not os.path.isdir(dump_dir):
                    os.makedirs(dump_dir)
                dump_path = os.path.join(dump_dir, _cue.config_filename)
                data = getattr(persistent, '_cue_markers', None)
                if data is None:
                    self.save()
                    data = getattr(persistent, '_cue_markers', {})
                with open(dump_path, "w") as f:
                    _json.dump(data, f, indent=2, sort_keys=True)
                _cue_log("DUMP-MARKERS total_keys={} path={}".format(
                    len(self._data), _cue.config_filename))
            except Exception as e:
                _cue_log("DUMP-MARKERS-ERROR {}".format(str(e)))

        def restore(self):
            """Restore markers from disk, replacing all in-memory data."""
            try:
                import json as _json
                dump_path = _cue.config_path
                if not os.path.isfile(dump_path):
                    _cue_log("RESTORE-MARKERS-NO-FILE path={}".format(_cue.config_filename))
                    return
                with open(dump_path, "r") as f:
                    data = _json.load(f)
                persistent._cue_markers = data
                self._data = _cue_unwrap_persistent(data.get("markers", {}))
                self._normalize_all()
                _cue.played_video_keys.clear()
                _cue.autoplay_states = {}
                self.save()
                _cue_log("RESTORE-MARKERS total_keys={} path={}".format(
                    len(self._data), _cue.config_filename))
            except Exception as e:
                _cue_log("RESTORE-MARKERS-ERROR {}".format(str(e)))

        # -- clipboard --

        def copy_context(self):
            """Copy all markers for the current context to the clipboard."""
            import copy as _copy
            ctx_file = _cue.current_file
            ctx_dlg = _cue.current_dialogue
            copied = {}

            all_keys = [
                create_vid_key(ctx_file),
                create_img_key(ctx_file),
                create_dlg_key((ctx_file, ctx_dlg)),
                create_autoplay_key(ctx_file),
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
            """Paste clipboard markers into the current context, remapping keys."""
            import copy as _copy
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
                elif is_autoplay_key(source_key):
                    new_key = create_autoplay_key(ctx_file)

                self._data[new_key] = _copy.deepcopy(entry)
                _cue_log("{} {}".format(new_key, str(entry)))

                # Clamp video timestamps to current video duration
                if is_vid_key(source_key):
                    dur = _cue.vid_manager.get_duration()
                    pasted_entry = self._data[new_key]
                    for ts_entry in pasted_entry.get("timestamps", []):
                        t = ts_entry.get("time", 0)
                        if dur > 0:
                            t = max(0.0, min(t, dur - 0.05))
                        else:
                            t = max(0.0, t)
                        ts_entry["time"] = t

            _cue.played_video_keys.clear()
            _cue.autoplay_states = {}
            self.save()
