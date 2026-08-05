###############################################################################
# CueMarkerManager — unified marker CRUD with typed context accessors.
# Instantiated once at _cue.markers, lives on the NoRollback _cue object.
#
# API:
#   _cue.markers.image.add_file(idx)          Pool-based (i: prefix)
#   _cue.markers.dialogue.add_file(idx)       Pool-based (d: prefix)
#   _cue.markers.video.add_file(idx)          Pool-based (v: prefix)
#   _cue.markers.loop.add_file(idx)       Pool-based (l: prefix)
#
#   _cue.markers[key] / .get(key) / .items()  Dict-like access (backward compat)
#   _cue.markers.save_persistent() / .backup_to_file() / .restore_from_file()  Persistence
#   _cue.markers.copy_context() / .paste_context()  Clipboard
###############################################################################

init -999 python:

    # =========================================================================
    # CueMarkerContext — pool-based markers (shared by .image and .dialogue)
    # =========================================================================

    class CueMarkerContext:
        """Abstract base for pool-based marker contexts.

        An "entry" is the dict stored at a trigger key like "i:bg_room.png":
            {"pools": [{"files": [...], "volume": 1.0}, ...]}

        Each pool is a group of SFX files that play together when the context
        is triggered. The "active" pool is the tab the UI has selected — the
        next add_file() call targets it.

        Subclasses must override _key(), _get_target(), _set_target().
        """

        def __init__(self, manager):
            self._mgr = manager

        # -- internal helpers (override in subclasses) --

        def _key(self):
            """Build the trigger key for the current scene context.
            Subclasses must override."""
            raise NotImplementedError("_key must be overridden")

        def _get_target(self):
            """Return the active pool index for this context.
            Subclasses must override."""
            raise NotImplementedError("_get_target must be overridden")

        def _set_target(self, value):
            """Set the active pool index for this context.
            Subclasses must override."""
            raise NotImplementedError("_set_target must be overridden")

        # -- public API --

        def add_file(self, file_index):
            """Add an audio file to the active pool. Creates entry/pool as needed."""
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
            """Remove a file from a specific pool."""
            key = self._key()
            self._mgr._remove_file_from_pool(key, file_index, pool_index)

        def clear(self):
            """Remove all pools for the current context."""
            key = self._key()
            self._mgr.pop(key, None)
            self._mgr.save_persistent()

        def add_pool(self):
            """Append a new empty pool and auto-switch to it."""
            key = self._key()
            entry = self._mgr._get_or_create_entry(key)
            entry["pools"].append({
                "files": [],
                "volume": _cue.VOL_DEFAULT,
            })
            self._set_target(len(entry["pools"]) - 1)
            self._mgr.save_persistent()

        def remove_pool(self, pool_index):
            """Delete a pool. Removes the entry when no pools remain.
            Clamps the active index so the UI highlight stays valid."""
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
            self._mgr.save_persistent()

        def get_active(self):
            """Return the active pool index."""
            return self._get_target()

        def set_active(self, pool_index):
            """Set which pool new files are added to."""
            self._set_target(pool_index)

        def apply_preset(self, preset_name):
            """Replace the active pool with a preset reference."""
            key = self._key()
            self._mgr._stamp_preset(key, preset_name, self.get_active())

        def add_folder(self, folder_path):
            """Add a folder reference to the active pool.
            Stores the folder path (with trailing '/') instead of expanding to
            individual files. Files are resolved at trigger time."""
            key = self._key()
            folder_ref = folder_path.rstrip("/") + "/"
            self._mgr._detach_pool(key, self.get_active())
            pool = self._mgr._ensure_pool(key, self.get_active())
            files = pool.setdefault("files", [])
            if folder_ref not in files:
                files.append(folder_ref)
            self._mgr.save_persistent()


    class ResolvedPool:
        """Immutable snapshot of a resolved pool. Fields:
        files, volume, frequency, trigger_on_shake."""
        def __init__(self, files, volume, frequency, trigger_on_shake):
            self.files = files
            self.volume = volume
            self.frequency = frequency
            self.trigger_on_shake = trigger_on_shake


    # =========================================================================
    # CueImageContext — pool-based, i: prefix
    # =========================================================================

    class CueImageContext(CueMarkerContext):
        """Manage image-triggered SFX pools (i: prefix)."""

        def _key(self):
            return create_img_key(_cue.current_file)

        def _get_target(self):
            return self._mgr._img_target

        def _set_target(self, value):
            self._mgr._img_target = int(value)


    # =========================================================================
    # CueDialogueContext — pool-based, d: prefix
    # =========================================================================

    class CueDialogueContext(CueMarkerContext):
        """Manage dialogue-triggered SFX pools (d: prefix)."""

        def _key(self):
            return create_dlg_key((_cue.current_file, _cue.current_dialogue or ""))

        def _get_target(self):
            return self._mgr._dlg_target

        def _set_target(self, value):
            self._mgr._dlg_target = int(value)


    # =========================================================================
    # CueVideoContext — pool-based markers (v: prefix)
    # =========================================================================

    class CueVideoContext(CueMarkerContext):
        """Manage pool-based cue-points on a video timeline.

        A video entry looks like:
            {"pools": [
                {"time": 12.5, "files": ["moan1.ogg"], "volume": 1.0},
                {"time": 45.2, "files": ["scream.ogg"]},
            ], "volume": 1.0}

        Extends CueMarkerContext with time-based operations: drag, nudge,
        multi-select, and the CDD callback interface.
        """

        def __init__(self, manager):
            super(CueVideoContext, self).__init__(manager)
            self.target_pool = 0     # active pool index
            self.selected = set()    # multi-selection indices
            self.edit_text = ""      # time-edit input buffer

        # -- internal --

        def _key(self):
            """Build the v: key for the current video context."""
            return create_vid_key(_cue.current_file) if _cue.current_file else ""

        def _get_target(self):
            return self.target_pool

        def _set_target(self, value):
            self.target_pool = int(value)

        def _entry_and_pools(self):
            """Return (entry, pools) for the current video, or (None, []).
            Returns raw pools — callers that display data should use
            _mgr._resolve_video_pools(entry) for preset resolution."""
            vid_key = self._key()
            if not vid_key:
                return None, []
            entry = self._mgr.get(vid_key)
            if entry is None:
                return None, []
            return entry, entry.get("pools", [])

        def _sort_and_track(self, pools, tracked_entry):
            """Sort pools by time and update target_pool to tracked_entry's
            new index. Returns the new index, or -1 if not found."""
            pools.sort(key=lambda e: e["time"])
            try:
                new_idx = pools.index(tracked_entry)
                self.target_pool = new_idx
                return new_idx
            except ValueError:
                self.target_pool = min(self.target_pool, len(pools) - 1)
                return -1

        # -- internal helpers (used by add_file / add_folder / add_pool / apply_preset) --

        def _append_pool(self, entry, pools, pool_dict):
            """Append a pool dict, re-sort, and update target_pool + selected."""
            pools.append(pool_dict)
            self._sort_and_track(pools, pool_dict)
            self.selected = set()

        # -- public API (extends CueMarkerContext) --

        def add_file(self, file_index):
            """Add an audio file to the active pool. Creates a new
            pool at the current video position if no pools exist or
            the active target is out of range."""
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
                # Add to existing active pool
                self._mgr._detach_pool(vid_key, self.target_pool)
                files = pools[self.target_pool].setdefault("files", [])
                if filename not in files:
                    files.append(filename)
            else:
                # Create new pool at current video position
                elapsed = _cue.vid_manager.get_elapsed()
                self._append_pool(entry, pools,
                    {"time": elapsed, "files": [filename]})
            self._mgr.save_persistent()

        def remove_file(self, ts_index, file_index):
            """Remove a single file from a pool's files list.
            Keeps the pool even if files becomes empty."""
            vid_key = self._key()
            entry = self._mgr.get(vid_key, {})
            pools = entry.get("pools", [])
            if not (0 <= ts_index < len(pools)):
                return
            self._mgr._detach_pool(vid_key, ts_index)
            files = pools[ts_index].get("files", [])
            if 0 <= file_index < len(files):
                files.pop(file_index)
                _cue.played_video_keys.clear()
                self._mgr.save_persistent()

        def add_folder(self, folder_path):
            """Add a folder reference to the active pool.
            Stores the folder path (with trailing '/') instead of expanding.
            Creates a new pool when none exist (requires playing video)."""
            if not _cue.current_file:
                return
            folder_ref = folder_path.rstrip("/") + "/"
            vid_key = self._key()
            entry = self._mgr._get_or_create_entry(vid_key)
            pools = entry["pools"]
            if pools and 0 <= self.target_pool < len(pools):
                # Add to existing active pool
                self._mgr._detach_pool(vid_key, self.target_pool)
                pool_files = pools[self.target_pool].setdefault("files", [])
                if folder_ref not in pool_files:
                    pool_files.append(folder_ref)
            else:
                # Create new pool at current video position
                elapsed = _cue.vid_manager.get_elapsed()
                self._append_pool(entry, pools,
                    {"time": elapsed, "files": [folder_ref]})
            self._mgr.save_persistent()

        def clear(self):
            """Remove all video markers for the current context."""
            super(CueVideoContext, self).clear()
            self.target_pool = 0
            _cue.played_video_keys.clear()
            self.selected = set()

        def add_pool(self):
            """Create a new empty pool at the current video position."""
            elapsed = _cue.vid_manager.get_elapsed()
            vid_key = self._key()
            entry = self._mgr._get_or_create_entry(vid_key)
            pools = entry["pools"]
            self._append_pool(entry, pools,
                {"time": elapsed, "files": []})
            self._mgr.save_persistent()

        def apply_preset(self, preset_name):
            """Stamp a pool preset reference onto a new pool at the
            current playhead position. The pool carries a 'preset' key
            that is resolved at read time, matching the other context types."""
            if not _cue.current_file:
                return
            elapsed = _cue.vid_manager.get_elapsed()
            # Verify preset exists and resolves to something
            r = self._mgr.resolve_pool({"preset": preset_name})
            if not r.files:
                return
            vid_key = self._key()
            entry = self._mgr._get_or_create_entry(vid_key)
            pools = entry["pools"]
            self._append_pool(entry, pools,
                {"time": elapsed, "preset": preset_name})
            self.sync_text()
            _cue.played_video_keys.clear()
            self._mgr.save_persistent()

        def remove_pool(self, ts_index):
            """Delete a pool by index. Clamps target_pool."""
            super(CueVideoContext, self).remove_pool(ts_index)
            _cue.played_video_keys.clear()
            self.selected = set()

        def duplicate_pool(self, ts_index):
            """Clone a pool with all settings (time, volume, file list).
            Appends the clone, sorts by time, and switches to the new pool."""
            vid_key = self._key()
            entry = self._mgr.get(vid_key, {})
            pools = entry.get("pools", [])
            if not (0 <= ts_index < len(pools)):
                return
            original = pools[ts_index]
            clone = {
                "time": original["time"],
                "volume": original.get("volume", _cue.VOL_DEFAULT),
                "files": list(original.get("files", [])),
            }
            pools.append(clone)
            pools.sort(key=lambda e: e["time"])
            self.target_pool = next(i for i, pool in enumerate(pools) if pool is clone)
            self.selected = set()
            self._mgr.save_persistent()

        def remove_selected(self):
            """Delete selected markers (multi-selection) or the active pool
            (single). Removes in descending order to avoid index-shift bugs."""
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
                _cue.played_video_keys.clear()
                self.selected = set()
                self._mgr.save_persistent()
            else:
                # No selection — delegate to per-pool delete
                self.remove_pool(self.target_pool)

        def has_markers(self):
            """Return True if the current video has at least one pool."""
            _, pools = self._entry_and_pools()
            return bool(pools)

        def get_delete_message(self):
            """Build the confirmation message for marker deletion."""
            if len(self.selected) > 1:
                nums = ", ".join(str(i + 1) for i in sorted(self.selected))
                return "Delete markers {}?".format(nums)
            elif len(self.selected) == 1:
                return "Delete marker {}?".format(next(iter(self.selected)) + 1)
            else:
                # No selection — deleting the active pool
                if not self.has_markers():
                    return ""
                return "Delete marker {}?".format(self.target_pool + 1)

        def set_active(self, pool_index):
            """Set which pool tab is active (no-op on selection)."""
            super(CueVideoContext, self).set_active(pool_index)
            self.sync_text()

        def select_tab(self, pool_index):
            """Switch active pool tab and clear multi-selection.
            Called when the user explicitly clicks a pool tab button."""
            self.selected = set()
            self.set_active(pool_index)

        # -- pool time editing --

        def nudge(self, delta):
            """Nudge the active pool's time by delta seconds.
            Updates both the data entry and the edit text buffer."""
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
            _cue.played_video_keys.clear()
            self.selected = set()
            self._mgr.save_persistent()

        def set_time(self, idx, new_time):
            """Write a marker time during drag — no sort/save (done on
            release). Hot path, called every frame during a drag."""
            entry, pools = self._entry_and_pools()
            dur = self.get_duration()
            new_time = _cue_clamp_time(new_time, dur)
            if 0 <= idx < len(pools):
                pools[idx]["time"] = new_time

        def finalize_drag(self):
            """Sort pools and save after a drag ends. Rebuilds the
            multi-selection set after re-sort since indices may shift."""
            entry, pools = self._entry_and_pools()
            if not pools:
                return

            # Capture selected pool identities before sorting
            sel_objects = set()
            for idx in self.selected:
                if 0 <= idx < len(pools):
                    sel_objects.add(id(pools[idx]))

            pi = self.target_pool
            if 0 <= pi < len(pools):
                self._sort_and_track(pools, pools[pi])

            # Rebuild selection from new indices after sort
            if sel_objects:
                new_sel = set()
                for i, pool in enumerate(pools):
                    if id(pool) in sel_objects:
                        new_sel.add(i)
                self.selected = new_sel
                if new_sel:
                    self.target_pool = min(new_sel)

            self._mgr.save_persistent()

        def sync_text(self):
            """Load the active pool's time into the edit text buffer."""
            entry, pools = self._entry_and_pools()
            if 0 <= self.target_pool < len(pools):
                self.edit_text = _cue_format_time(pools[self.target_pool]["time"])

        def commit_text(self):
            """Parse the edit text buffer and update the active pool's time.
            Tracks the active tab after re-sort."""
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
                _cue.played_video_keys.clear()
                self.selected = set()
                self._mgr.save_persistent()
            # Reformat buffer — shows current value, or feedback on parse failure
            self.edit_text = _cue_format_time(pools[self.target_pool]["time"])

        # -- CDD callback interface (injected into _VideoMarkerTimeline) --

        def get_markers(self):
            """Return the list of pool dicts for the current video.
            Preset-backed pools are transparently resolved."""
            entry, _ = self._entry_and_pools()
            if entry is None:
                return []
            return self._mgr._resolve_video_pools(entry)

        def get_selected(self):
            """Return the set of multi-selected marker indices."""
            return self.selected

        def get_duration(self):
            """Return video duration, floored at 0.001."""
            return max(0.001, _cue.vid_manager.get_duration())

    # =========================================================================
    # CueLoopContext — pool-based (l: prefix), mirrors image/dialogue
    # =========================================================================

    class CueLoopContext(CueMarkerContext):
        """Manage loop markers — pool-based, mirrors image/dialogue.

        An loop entry looks like:
            {"pools": [{"files": [...], "volume": 1.0, "frequency": 1}, ...],
             "volume": 1.0}
        """

        def __init__(self, manager):
            super(CueLoopContext, self).__init__(manager)

        def _key(self):
            """Build the l: key for the current context."""
            return create_loop_key(_cue.current_file or "")

        def _get_target(self):
            return self._mgr._loop_target

        def _set_target(self, value):
            self._mgr._loop_target = int(value)

        def add_pool(self):
            """Append a new empty pool (with frequency) and auto-switch to it."""
            key = self._key()
            entry = self._mgr._get_or_create_entry(key)
            entry["pools"].append({
                "files": [],
                "volume": _cue.VOL_DEFAULT,
                "frequency": 1,
            })
            self._set_target(len(entry["pools"]) - 1)
            self._mgr.save_persistent()

        def clear(self):
            """Remove loop markers for the current context."""
            key = self._key()
            self._mgr.pop(key, None)
            _cue.loop_states.pop(key, None)
            self._mgr.save_persistent()

        def set_frequency(self, freq):
            """Set loop frequency for the active pool. 0=Slow, 1=Normal, 2=Fast, 3=Fastest.
            Pool-level override on preset-backed pools (no detach needed)."""
            key = self._key()
            target = self.get_active()
            entry = self._mgr.get(key)
            if entry:
                pools = entry.get("pools", [])
                if pools and 0 <= target < len(pools):
                    pools[target]["frequency"] = int(freq)
                    self._mgr.save_persistent()

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
            _cue.markers.save_persistent()
        """

        def __init__(self):
            self._data = {}
            self._presets = {}  # name -> {"files": [...], "volume": 1.0, ...}
            self._video_presets = {}  # name -> {"pools": [...], "volume": 1.0, ...}
            self._img_target = 0
            self._dlg_target = 0
            self._loop_target = 0
            self._last_autosave_time = 0
            self.image = CueImageContext(self)
            self.dialogue = CueDialogueContext(self)
            self.video = CueVideoContext(self)
            self.loop = CueLoopContext(self)
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
            entry = self._data.get(key)
            if entry is None:
                return default
            return self._normalize_entry(entry)

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

        # -- presets --

        def create_preset(self, name, pool_dict):
            """Save a pool dict as a named preset. Overwrites if name exists."""
            import copy as _copy
            self._presets[name] = _copy.deepcopy(pool_dict)
            self.save_persistent()
            _cue_log("CREATE-PRESET name={} files={} vol={:.1f}".format(
                name, len(pool_dict.get("files", [])), pool_dict.get("volume", _cue.VOL_DEFAULT)))

        def delete_preset(self, name):
            """Delete a preset by name. Markers referencing it will resolve to empty."""
            if name in self._presets:
                del self._presets[name]
                self.save_persistent()
                _cue_log("DELETE-PRESET name={}".format(name))

        def preset_remove_file(self, name, file_path):
            """Remove a file from a preset. If the file is in a folder ref,
            detaches the folder ref to an explicit list minus the removed file."""
            preset = self._presets.get(name)
            if preset is None:
                return
            files = preset.get("files", [])
            # Direct file removal
            if file_path in files:
                files.remove(file_path)
                self.save_persistent()
                return
            # Check folder refs — detach if the file is inside one
            for fi, f in enumerate(files):
                if f.endswith("/") and file_path.startswith(f):
                    resolved = []
                    for rf in _cue.available_files:
                        if rf.startswith(f) and rf not in _cue.file_tree.disabled_files and rf not in resolved:
                            resolved.append(rf)
                    if file_path in resolved:
                        resolved.remove(file_path)
                    files[fi:fi + 1] = resolved
                    self.save_persistent()
                    return

        def get_preset(self, name):
            """Return preset dict or None."""
            return self._presets.get(name)

        def list_presets(self):
            """Return sorted list of preset names."""
            return sorted(self._presets.keys())

        # -- video presets --

        def create_video_preset(self, name, entry):
            """Save video pools as a named preset. Overwrites if name exists."""
            import copy as _copy
            pools = entry.get("pools", [])
            if not pools:
                return
            clean = []
            for pool in pools:
                if pool.get("time") is not None:
                    clean.append({
                        "time": pool["time"],
                        "files": python_list(pool.get("files", [])),
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
            self.save_persistent()
            _cue_log("CREATE-VIDEO-PRESET name={} markers={} dur={:.1f}".format(
                name, len(clean), source_dur))

        def delete_video_preset(self, name):
            """Delete a video preset by name."""
            if name in self._video_presets:
                del self._video_presets[name]
                self.save_persistent()
                _cue_log("DELETE-VIDEO-PRESET name={}".format(name))

        def get_video_preset(self, name):
            """Return video preset dict or None."""
            return self._video_presets.get(name)

        def list_video_presets(self):
            """Return sorted list of video preset names."""
            return sorted(self._video_presets.keys())

        def video_preset_out_of_range(self, name):
            """Return how many pools in a preset exceed the current
            video's duration. Returns 0 when duration is unknown (dur <= 0)."""
            preset = self._video_presets.get(name)
            if preset is None:
                return 0
            dur = _cue.vid_manager.get_duration()
            if dur is None or dur <= 0:
                return 0
            out = 0
            for pool in preset.get("pools", []):
                t = pool.get("time")
                if t is not None and t > dur - _cue.END_MARGIN:
                    out += 1
            return out

        def apply_video_preset(self, name):
            """Copy a video preset's pools into the current video entry.
            Silently drops markers that don't fit the target video duration.
            Resets UI state so the timeline re-renders correctly."""
            import copy as _copy
            preset = self._video_presets.get(name)
            if preset is None:
                return
            if not _cue.current_file:
                return
            vid_key = create_vid_key(_cue.current_file)
            dur = _cue.vid_manager.get_duration()
            new_pools = []
            dropped = 0
            for pool in preset.get("pools", []):
                t = pool.get("time")
                if t is None:
                    dropped += 1
                    continue
                if dur and dur > 0 and t > dur - _cue.END_MARGIN:
                    dropped += 1
                    continue
                new_pools.append({
                    "time": t,
                    "files": python_list(pool.get("files", [])),
                    "volume": pool.get("volume", _cue.VOL_DEFAULT),
                })
            new_pools.sort(key=lambda e: e["time"])
            entry = self._get_or_create_entry(vid_key)
            entry["pools"] = new_pools
            entry["volume"] = preset.get("volume", _cue.VOL_DEFAULT)
            self.video.target_pool = 0
            self.video.selected = set()
            self.video.sync_text()
            _cue.played_video_keys.clear()
            self.save_persistent()
            _cue_log("APPLY-VIDEO-PRESET key={} preset={} markers={} dropped={}".format(
                vid_key, name, len(new_pools), dropped))

        @staticmethod
        def _clean_pool_list(pools):
            """Strip entries missing 'time' from a pool list.
            Returns (clean_list, stripped_count)."""
            stripped = 0
            clean = []
            for pool in pools:
                if pool.get("time") is not None:
                    clean.append(pool)
                else:
                    stripped += 1
            return clean, stripped

        def _sanitize_video_presets(self):
            """Strip entries missing 'time' from all video preset pool lists.
            Returns the number of entries stripped."""
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

        # -- pool-level preset resolution (for video entries) --

        def _resolve_video_pools(self, entry):
            """Return a resolved list of pool dicts from entry, expanding
            any preset references (stamped by CueVideoContext.apply_preset).
            The original entry is not modified. List length matches the raw list
            so that trigger-tick indices stay consistent for volume lookup."""
            raw = entry.get("pools", [])
            resolved = []
            for pool in raw:
                if "preset" in pool:
                    r = self.resolve_pool(pool)
                    resolved.append({
                        "time": pool["time"],
                        "files": python_list(r.files),
                        "volume": r.volume,
                    })
                else:
                    resolved.append(pool)
            return resolved

        def _remove_file_from_preset_pool(self, trigger_key, pool_index, _dummy_fi, child_file):
            """Detach a preset-backed pool then remove a specific file by path.
            Signature matches folder_child_remove_fn for cue_file_list."""
            self._detach_pool(trigger_key, pool_index)
            entry = self._data.get(trigger_key)
            if entry is None:
                return
            pools = entry.get("pools")
            if pools and 0 <= pool_index < len(pools):
                files = pools[pool_index].get("files", [])
                if child_file in files:
                    files.remove(child_file)
            self.save_persistent()

        def resolve_pool(self, pool):
            """Resolve a pool dict to a ResolvedPool object.

            If pool is preset-backed (has 'preset' key), merges preset defaults
            with pool-level overrides. Otherwise returns the pool's own values.

            Pool-level keys take precedence over preset keys, so users can
            tweak volume/frequency/shake on a preset-backed pool without
            detaching. Only file mutations (add/remove) trigger a detach.
            """
            if "preset" in pool:
                preset = self._presets.get(pool["preset"], {})
                files = pool.get("files", preset.get("files", []))
                volume = pool.get("volume", preset.get("volume", _cue.VOL_DEFAULT))
                frequency = pool.get("frequency", preset.get("frequency", 1))
                trigger_on_shake = pool.get("trigger_on_shake", preset.get("trigger_on_shake", False))
                return ResolvedPool(list(files), volume, frequency, trigger_on_shake)
            files = pool.get("files", [])
            volume = pool.get("volume", _cue.VOL_DEFAULT)
            frequency = pool.get("frequency", 1)
            trigger_on_shake = pool.get("trigger_on_shake", False)
            return ResolvedPool(files, volume, frequency, trigger_on_shake)

        def _detach_pool(self, trigger_key, pool_index):
            """If the pool at pool_index is preset-backed, resolve it to explicit
            values and drop the 'preset' key. Saves after detaching.
            Returns True if a detach occurred."""
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

            self.save_persistent()

            _cue_log("DETACH-POOL key={} pi={} preset={} files={}".format(
                trigger_key, pool_index, preset_name, len(r.files)))

            return True

        def _stamp_preset(self, trigger_key, preset_name, pool_index=0):
            """Replace a pool with a preset reference. Creates entry/pool if needed."""
            entry = self._get_or_create_entry(trigger_key)
            pools = entry["pools"]
            # Ensure pool exists at index
            while len(pools) <= pool_index:
                pools.append({"files": [], "volume": _cue.VOL_DEFAULT})
            pools[pool_index] = {"preset": preset_name}
            self.save_persistent()
            _cue_log("STAMP-PRESET key={} pi={} preset={}".format(
                trigger_key, pool_index, preset_name))

        def _detach_folder_ref_in_files(self, files, file_index, child_file):
            """Replace a folder ref at file_index with its resolved file list
            minus child_file. Modifies files in place. Does not save."""
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
            """Remove a child file from a folder ref in a pool.
            Detaches the pool's preset if needed, then detaches the folder ref."""
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
            self.save_persistent()

        # -- internal helpers (used by context accessors) --

        def _normalize_entry(self, entry):
            """Migrate legacy {'files': [...]} to {'pools': [{'files': [...]}]}
            in place. Preserves entry-level keys (volume, frequency, etc.)."""
            if entry is None:
                return entry
            if "pools" not in entry:
                entry["pools"] = [{"files": entry.pop("files", [])}]
            entry.setdefault("replay", _cue.current_replay)
            return entry

        def _get_or_create_entry(self, trigger_key):
            """Get the entry dict for trigger_key, creating it in pools format."""
            entry = self._data.get(trigger_key)
            if entry is None:
                entry = {"pools": []}
                self._data[trigger_key] = entry
            entry = self._normalize_entry(entry)
            return entry

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
            """Append a file to a specific pool. Creates entry/pool if needed.
            Detaches preset-backed pools before mutating."""
            self._detach_pool(trigger_key, pool_index)
            pool = self._ensure_pool(trigger_key, pool_index)
            files = pool.setdefault("files", [])
            if filename not in files:
                files.append(filename)
            self.save_persistent()

        def _remove_file_from_pool(self, trigger_key, file_index, pool_index=0):
            """Remove a file from a pool. Prunes empty pools and entries.
            Detaches preset-backed pools before mutating."""
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
                self.save_persistent()
            elif "files" in entry:
                # Legacy path — l: entries and un-migrated entries
                files = entry["files"]
                if 0 <= file_index < len(files):
                    files.pop(file_index)
                    if not files:
                        del self._data[trigger_key]
                    self.save_persistent()

        def _normalize_all(self):
            """Migrate all legacy i:, d:, and l: entries to pools format.
            Also moves entry-level frequency into each loop pool.
            Returns True if any entry was changed."""
            changed = False
            for key, entry in list(self._data.items()):
                if is_img_key(key) or is_dlg_key(key) or is_loop_key(key):
                    if "pools" not in entry:
                        self._normalize_entry(entry)
                        changed = True
                # Migrate entry-level frequency into each loop pool
                if is_loop_key(key) and "frequency" in entry:
                    freq = entry.pop("frequency")
                    for pool in entry.get("pools", []):
                        pool.setdefault("frequency", freq)
                    changed = True
            return changed

        def _migrate_video_timestamps_to_pools(self):
            """One-time: rename 'timestamps' key to 'pools' in video entries
            and video presets. Idempotent — safe to run every load.
            Returns (entries_changed, presets_changed)."""
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
            """Strip entries missing 'time' from all video pool lists.
            Returns the number of entries stripped."""
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

        def save_persistent(self):
            """Persist markers to Ren'Py persistent storage. Automatically
            strips malformed video pools before writing."""
            # Sanitize before persisting
            stripped = self._sanitize_video_pools()
            if stripped:
                _cue_log("SAVE-MARKERS: sanitized {} malformed video pool(s)".format(stripped))

            # Per-video edit history
            _edit_history = python_dict()
            for _vp, _st in _cue.video_editor._states.items():
                if _st.last_factor is not None:
                    _edit_history[_vp] = python_dict({
                        "factor": _st.last_factor,
                        "interpolate": _st.last_interpolate,
                        "fast_preview": _st.last_fast_preview,
                    })

            data = python_dict({
                "markers": _cue_unwrap_persistent(self._data),
                "presets": _cue_unwrap_persistent(self._presets),
                "video_presets": _cue_unwrap_persistent(self._video_presets),
                "disabled_files": _cue_unwrap_persistent(_cue.file_tree.disabled_files),
                "triggers_active": _cue.triggers_active,
                "interpolate": _cue.video_editor.interpolate,
                "video_edit_history": _cue_unwrap_persistent(_edit_history),
            })
            persistent._cue_config = data

            # Autosave backup to disk (throttled to once per 5 min)
            self._autosave_backup()

        def _populate_config(self, data):
            """Populate all internal state from a plain data dict.
            Called by both load() (from persistent) and restore() (from disk)."""
            self._data = _cue_unwrap_persistent(data.get("markers", {}))
            self._presets = _cue_unwrap_persistent(data.get("presets", {}))
            self._video_presets = _cue_unwrap_persistent(data.get("video_presets", {}))
            
            _cue.file_tree.disabled_files = _cue_unwrap_persistent(data.get("disabled_files", []))
            _cue.triggers_active = data.get("triggers_active", True)
            _cue.video_editor.interpolate = bool(data.get("interpolate", True))

            # Restore per-video edit history
            _edit_history = _cue_unwrap_persistent(data.get("video_edit_history", {}))
            for _vp, _cfg in _edit_history.items():
                _st = _cue.video_editor._ensure_state(_vp)
                _st.last_factor = float(_cfg.get("factor", 1.0))
                _st.last_interpolate = bool(_cfg.get("interpolate", False))
                _st.last_fast_preview = bool(_cfg.get("fast_preview", False))
                _st.factor_text = "{:.2f}".format(_st.last_factor)

            self._migrate_video_timestamps_to_pools()
            self._sanitize_video_pools()
            self._sanitize_video_presets()
            self._normalize_all()

        def load_persistent(self):
            """Load markers from persistent storage into internal state."""
            data = getattr(persistent, '_cue_config', None)
            if data is None:
                self._data = {}
                self._video_presets = {}
                return
            self._populate_config(data)
            _cue_log("LOAD-MARKERS total_keys={}".format(len(self._data)))

        def _autosave_backup(self):
            """Write a backup copy to disk, throttled to once per 5 minutes.

            Saves to auto_backups/ with a Unix timestamp suffix. Keeps the last
            50 copies, deleting older ones.
            """
            import time as _time
            import json as _json
            import glob as _glob

            now = _time.time()
            if now - self._last_autosave_time < 300:
                return

            self._last_autosave_time = now
            try:
                backup_dir = os.path.join(renpy.config.gamedir, _cue.base_dir, "auto_backups")
                if not os.path.isdir(backup_dir):
                    os.makedirs(backup_dir)

                # Generate timestamped filename
                dump_path = os.path.join(backup_dir, "cue_config_{}.json".format(int(now)))
                data = getattr(persistent, '_cue_config', None)

                if data is None:
                    self.save_persistent()
                    data = getattr(persistent, '_cue_config', {})

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

        def backup_to_file(self):
            """Dump entire persistent._cue_config to disk."""
            try:
                import json as _json
                dump_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)

                if not os.path.isdir(dump_dir):
                    os.makedirs(dump_dir)
                dump_path = os.path.join(dump_dir, _cue.config_filename)
                data = getattr(persistent, '_cue_config', None)

                if data is None:
                    self.save_persistent()
                    data = getattr(persistent, '_cue_config', {})

                with open(dump_path, "w") as f:
                    _json.dump(data, f, indent=2, sort_keys=True)

                _cue_log("DUMP-MARKERS total_keys={} path={}".format(
                    len(self._data), _cue.config_filename))
            except Exception as e:
                _cue_log("DUMP-MARKERS-ERROR {}".format(str(e)))

        def restore_from_file(self):
            """Restore markers from a disk backup, replacing persistent and in-memory state."""
            try:
                import json as _json
                dump_path = _cue.config_path

                if not os.path.isfile(dump_path):
                    _cue_log("RESTORE-MARKERS-NO-FILE path={}".format(_cue.config_filename))
                    return
                with open(dump_path, "r") as f:
                    data = _json.load(f)

                persistent._cue_config = data
                self._populate_config(data)
                self.save_persistent()

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
                elif is_loop_key(source_key):
                    new_key = create_loop_key(ctx_file)

                self._data[new_key] = _copy.deepcopy(entry)
                self._data[new_key]["replay"] = _cue.current_replay

                _cue_log("{} {}".format(new_key, str(entry)))

                # Clamp video pools to current video duration
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

            _cue.played_video_keys.clear()
            _cue.loop_states = {}
            self.save_persistent()
