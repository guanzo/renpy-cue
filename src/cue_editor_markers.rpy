###############################################################################
# Cue Editor — Marker Management
# Key utilities, audio scanning, pool helpers, marker CRUD, volume, clipboard,
# time formatting. All functions run in a single init python block.
###############################################################################

init python:
    # --------------------------------------------------------------------------
    # Key Utility Functions
    # --------------------------------------------------------------------------

    def create_img_key(file):
        """Build an image trigger key: 'i:<file>'."""
        return _cue.IMG_KEY_PREFIX + file

    def create_vid_key(file):
        """Build a video trigger key: 'v:<file>'."""
        return _cue.VID_KEY_PREFIX + file

    def create_autoplay_key(file):
        """Build a autoplay trigger key: 'a:<file>'. file may be '' for global pool."""
        return _cue.AUTOPLAY_KEY_PREFIX + file

    def create_dlg_key(dlg_pair):
        """Build a dialogue trigger key from a (file, dialogue) pair.
        Usage: create_dlg_key((_cue.current_file, _cue.current_dialogue))"""
        file, dialogue = dlg_pair
        return _cue.DLG_KEY_PREFIX + file + "|" + dialogue

    def is_img_key(key):
        """Check if key is an image trigger key."""
        return key.startswith(_cue.IMG_KEY_PREFIX)

    def is_vid_key(key):
        """Check if key is a video trigger key."""
        return key.startswith(_cue.VID_KEY_PREFIX)

    def is_dlg_key(key):
        """Check if key is a dialogue trigger key."""
        return key.startswith(_cue.DLG_KEY_PREFIX)

    def is_autoplay_key(key):
        """Check if key is a autoplay trigger key."""
        return key.startswith(_cue.AUTOPLAY_KEY_PREFIX)

    def get_key_file(key):
        """Strip the 2-char prefix from any key, returning the file portion."""
        file_part = key[len(_cue.IMG_KEY_PREFIX):]
        if key.startswith("d:"):
            file_part = file_part.split("|", 1)[0]
        return file_part

    def get_key_dialogue(key):
        file_part = key[len(_cue.DLG_KEY_PREFIX):]
        parts = file_part.split("|", 1)
        if len(parts) < 2:
            return ""
        return parts[1]

    def get_key_prefix(key):
        """Return the 2-char prefix of a key ('i:', 'v:', 'd:', or 'a:')."""
        return key[:len(_cue.IMG_KEY_PREFIX)]


    # --------------------------------------------------------------------------
    # Audio File Scanning
    # --------------------------------------------------------------------------

    def _cue_scan_audio():
        """Scan audio dir and build folder tree."""

        search_path = _cue.audio_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        audio_exts = (".ogg", ".mp3", ".wav", ".opus", ".flac")

        try:
            all_files = renpy.list_files()
        except Exception:
            _cue.available_files = []
            _cue.audio_tree = []
            _cue.scan_error = "Failed to list files"
            return

        # Build flat list of relative paths
        results = []
        for f in all_files:
            if f.startswith(search_path):
                relative = f[len(search_path):]
                if relative and f.lower().endswith(audio_exts):
                    results.append(relative)
        results.sort()
        _cue.available_files = results

        # Build tree from flat list
        root = {}
        for path in results:
            parts = path.split("/")
            node = root
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    # It's a file
                    node.setdefault("__files__", []).append(part)
                else:
                    # It's a folder
                    node = node.setdefault(part, {})

        # Convert to sorted tree list
        def _build_tree(node):
            items = []
            # Folders first
            for name in sorted(node.keys()):
                if name == "__files__":
                    continue
                children = _build_tree(node[name])
                has_direct_files = len(node[name].get("__files__", [])) > 0
                items.append({
                    "type": "folder",
                    "name": name + "/",
                    "children": children,
                    "expanded": False,
                    "has_files": has_direct_files,
                })
            # Then files
            for name in sorted(node.get("__files__", [])):
                items.append({"type": "file", "name": name})
            return items

        _cue.audio_tree = _build_tree(root)

        if not results:
            _cue.scan_error = "No audio files found in: {}".format(
                _cue.audio_dir
            )
        else:
            _cue.scan_error = None

        # Rebuild visible tree for sidebar
        _cue.visible_tree = _cue_get_visible_tree()


    def _cue_is_file_in_autoplay_pool(full_path):
        """Check if a file is in the current context's a: entry."""
        if not _cue.current_file:
            return False
        autoplay_key = create_autoplay_key(_cue.current_file)
        entry = _cue.markers.get(autoplay_key)
        if entry and full_path in entry.get("files", []):
            return True
        return False


    def _cue_add_folder_to_autoplay_pool(folder_path):
        """Recursively add all files under a folder prefix to the a: pool."""
        if not _cue.current_file:
            return
        autoplay_key = create_autoplay_key(_cue.current_file)
        entry = _cue.markers.setdefault(autoplay_key, {"files": [], "frequency": 1})
        files = entry.setdefault("files", [])
        for f in _cue.available_files:
            if f.startswith(folder_path) and f not in files and f not in _cue.disabled_files:
                files.append(f)
        _cue_save_markers()

    def _cue_add_folder_to_image_markers(folder_path):
        """Add all files under a folder as image markers for current image.
        Adds to the currently targeted image pool."""
        if not _cue.current_file:
            return
        img_key = create_img_key(_cue.current_file)
        pool = _cue_ensure_pool(img_key, _cue.img_target_pool)
        files = pool.setdefault("files", [])
        for f in _cue.available_files:
            if f.startswith(folder_path) and f not in files and f not in _cue.disabled_files:
                files.append(f)
        _cue_save_markers()

    def _cue_add_folder_to_dialogue_markers(folder_path):
        """Add all files under a folder as dialogue markers for current image+dialogue.
        Adds to the currently targeted dialogue pool."""
        if not _cue.current_dialogue:
            return
        dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))
        pool = _cue_ensure_pool(dlg_key, _cue.dlg_target_pool)
        files = pool.setdefault("files", [])
        for f in _cue.available_files:
            if f.startswith(folder_path) and f not in files and f not in _cue.disabled_files:
                files.append(f)
        _cue_save_markers()

    def _cue_add_folder_to_video_markers(folder_path):
        """Add all files under a folder to the active video timestamp pool.
        Creates a new timestamp pool when none exist (requires playing video)."""
        if not _cue.current_file:
            return
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.setdefault(vid_key, {"timestamps": []})
        timestamps = entry.setdefault("timestamps", [])
        target = _cue.vid_target_pool
        if timestamps and 0 <= target < len(timestamps):
            # Add to existing active timestamp pool
            pool_files = timestamps[target].setdefault("files", [])
            for f in _cue.available_files:
                if f.startswith(folder_path) and f not in pool_files and f not in _cue.disabled_files:
                    pool_files.append(f)
        else:
            # Create new timestamp at current time (requires playing video)
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
                _cue.vid_target_pool = len(timestamps) - 1
        _cue_save_markers()


    def _cue_toggle_folder(folder_path):
        """Toggle expand/collapse for a folder in the audio tree."""
        if folder_path in _cue.expanded_folders:
            _cue.expanded_folders[folder_path] = not _cue.expanded_folders[folder_path]
        else:
            _cue.expanded_folders[folder_path] = True
        _cue.visible_tree = _cue_get_visible_tree()


    def _cue_get_visible_tree():
        """Return a flat list of visible tree items for rendering.
        Each item: {type, name, depth, full_path, index_in_flat_list}"""
        result = []
        _walk_tree(_cue.audio_tree, "", 0, result)
        return result


    def _walk_tree(items, prefix, depth, result):
        """Recursively walk tree, only descending into expanded folders."""
        for item in items:
            full = prefix + item["name"]
            if item["type"] == "folder":
                result.append({
                    "type": "folder",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "expanded": _cue.expanded_folders.get(full, False),
                    "has_files": item.get("has_files", False),
                })
                if _cue.expanded_folders.get(full, False):
                    _walk_tree(item.get("children", []), full, depth + 1, result)
            else:
                # Find index in flat list
                try:
                    idx = _cue.available_files.index(full)
                except ValueError:
                    idx = -1
                result.append({
                    "type": "file",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "index": idx,
                    "in_pool": _cue_is_file_in_autoplay_pool(full),
                    "enabled": full not in _cue.disabled_files,
                })


    def _cue_toggle_file_enabled(full_path):
        """Toggle whether a file is enabled for marker addition."""
        if full_path in _cue.disabled_files:
            _cue.disabled_files.discard(full_path)
        else:
            _cue.disabled_files.add(full_path)
        _cue.visible_tree = _cue_get_visible_tree()
        _cue_save_markers()


    # --------------------------------------------------------------------------
    # Multi-Pool Helpers (normalize, access, create, prune)
    # --------------------------------------------------------------------------

    def _cue_normalize_entry(entry):
        """Migrate legacy {'files': [...]} to {'pools': [{'files': [...]}]} in place.
        Preserves entry-level keys (volume, frequency, etc.)."""
        if entry is None:
            return entry
        if "pools" not in entry:
            entry["pools"] = [{"files": entry.pop("files", [])}]
        return entry

    def _cue_unwrap_persistent(data):
        """Recursively convert Ren'Py RevertableDict/RevertableList wrappers
        to plain Python dict/list. Duck-typing avoids isinstance which fails
        on wrapped types; json.dumps also fails for the same reason.
        Strings/basestrings must be guarded — they are iterable."""
        if isinstance(data, (str, bytes)):
            return data
        try:
            if isinstance(data, unicode):  # Python 2 only
                return data
        except NameError:
            pass
        if hasattr(data, "items") and hasattr(data, "keys"):
            return python_dict((k, _cue_unwrap_persistent(v)) for k, v in data.items())
        if hasattr(data, "__iter__"):
            return python_list(_cue_unwrap_persistent(v) for v in data)
        return data

    def _cue_normalize_all_markers():
        """Migrate all legacy i: and d: entries to pools format and persist."""
        changed = False
        for key, entry in list(_cue.markers.items()):
            if is_img_key(key) or is_dlg_key(key):
                _cue_normalize_entry(entry)
                changed = True
        return changed

    def _cue_get_or_create_entry(trigger_key):
        """Get the entry dict for trigger_key, creating it in pools format if
        needed. Migrates legacy {'files': [...]} entries in place."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            entry = {"pools": []}
            _cue.markers[trigger_key] = entry
        return _cue_normalize_entry(entry)

    def _cue_ensure_pool(trigger_key, pool_index):
        """Return the pool dict at pool_index for trigger_key, creating the
        entry/pools as needed. Clamps an out-of-range pool_index to the last
        existing pool; creates pool 0 when no pools exist yet."""
        entry = _cue_get_or_create_entry(trigger_key)
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

    def _cue_add_pool(trigger_key, kind="img"):
        """Append a new empty pool and auto-switch target to it."""
        entry = _cue_get_or_create_entry(trigger_key)
        entry["pools"].append({
            "files": [],
            "volume": _cue.VOL_DEFAULT,
        })
        new_idx = len(entry["pools"]) - 1
        if kind == "dlg":
            _cue.dlg_target_pool = new_idx
        else:
            _cue.img_target_pool = new_idx
        _cue_save_markers()

    def _cue_remove_pool(trigger_key, pool_index, kind="img"):
        """Delete a pool; delete the entry when no pools remain.
        Clamps target-pool index so the highlight stays valid."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools")
        if not pools or not (0 <= pool_index < len(pools)):
            return
        pools.pop(pool_index)
        if not pools:
            del _cue.markers[trigger_key]
        # Keep target-pool valid
        remaining = len(pools)
        if kind == "dlg":
            if remaining:
                _cue.dlg_target_pool = min(_cue.dlg_target_pool, remaining - 1)
            else:
                _cue.dlg_target_pool = 0
        else:
            if remaining:
                _cue.img_target_pool = min(_cue.img_target_pool, remaining - 1)
            else:
                _cue.img_target_pool = 0
        _cue_save_markers()

    def _cue_set_target_pool(kind, pool_index):
        """Set which pool the file-browser I/D buttons add to."""
        if kind == "dlg":
            _cue.dlg_target_pool = int(pool_index)
        else:
            _cue.img_target_pool = int(pool_index)

    # --------------------------------------------------------------------------
    # Unified Marker CRUD
    # --------------------------------------------------------------------------

    def _cue_marker_add_file(trigger_key, filename, pool_index=0):
        """Append a file to a specific pool. Creates the entry/pool if needed."""
        pool = _cue_ensure_pool(trigger_key, pool_index)
        files = pool.setdefault("files", [])
        if filename not in files:
            files.append(filename)
        _cue_save_markers()

    def _cue_marker_remove_file(trigger_key, file_index, pool_index=0):
        """Remove a file from a pool. Prunes pool when empty and entry when
        last pool is gone. Legacy entries (a: callers) use the files branch."""
        entry = _cue.markers.get(trigger_key)
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
                del _cue.markers[trigger_key]
            _cue_save_markers()
        elif "files" in entry:
            # Legacy path — a: entries and any un-migrated entries
            files = entry["files"]
            if 0 <= file_index < len(files):
                files.pop(file_index)
                if not files:
                    del _cue.markers[trigger_key]
                _cue_save_markers()

    # --- Video markers (v: prefix) ---

    def _cue_sanitize_video_timestamps():
        """Strip non-dict entries and entries missing 'time' from all video
        timestamp lists. Returns the number of entries stripped so callers can
        decide whether to log."""
        total_stripped = 0
        for key, entry in list(_cue.markers.items()):
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

    def _cue_add_video_marker(file_index):
        """Add a file to the active timestamp pool. Creates a new timestamp
        if no timestamps exist yet or the active target is out of range."""
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
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.setdefault(vid_key, {"timestamps": []})
        timestamps = entry.setdefault("timestamps", [])
        target = _cue.vid_target_pool
        if timestamps and 0 <= target < len(timestamps):
            # Add to existing active timestamp
            files = timestamps[target].setdefault("files", [])
            if filename not in files:
                files.append(filename)
        else:
            # Create new timestamp at current time
            timestamps.append({"time": elapsed, "files": [filename]})
            timestamps.sort(key=lambda e: e["time"])
            _cue.vid_target_pool = len(timestamps) - 1
            _cue.mtl_selected = set()
        _cue_save_markers()

    def _cue_clear_video_markers():
        """Remove video markers for the current context."""
        vid_key = create_vid_key(_cue.current_file)
        _cue.markers.pop(vid_key, None)
        _cue.vid_manager.played_video_keys.clear()
        _cue.vid_target_pool = 0
        _cue.mtl_selected = set()
        _cue_save_markers()

    def _cue_sync_video_ts_text():
        """Sync the edit buffer to the active pool's timestamp value."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        index = _cue.vid_target_pool
        if 0 <= index < len(timestamps):
            _cue.edit_video_ts_text = _cue_format_time(timestamps[index]["time"])

    def _cue_commit_video_ts():
        """Parse the edit text and update the active video timestamp.
        Tracks the active tab after re-sort. No-ops when the repeat dialog is open
        (Enter key events propagate cross-screen and should not commit the wrong field)."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        index = _cue.vid_target_pool
        if not (0 <= index < len(timestamps)):
            return
        new_time = _cue_parse_time(_cue.edit_video_ts_text)
        if new_time is not None and new_time >= 0:
            edited_entry = timestamps[index]
            dur = _cue.vid_manager.get_duration()
            if dur > 0:
                new_time = max(0.0, min(new_time, dur - 0.05))
            edited_entry["time"] = new_time
            timestamps.sort(key=lambda e: e["time"])
            # Track the edited entry to its new position
            try:
                _cue.vid_target_pool = timestamps.index(edited_entry)
            except ValueError:
                _cue.vid_target_pool = min(index, len(timestamps) - 1)
            _cue.vid_manager.played_video_keys.clear()
            _cue.mtl_selected = set()
            _cue_save_markers()
        # Reformat buffer to reflect current value (error feedback on parse failure)
        _cue.edit_video_ts_text = _cue_format_time(timestamps[index]["time"])

    def _cue_set_vid_target_pool(pool_index):
        """Set which timestamp pool tab is active.
        Clears multi-selection since this is an explicit single-pool operation."""
        _cue.vid_target_pool = int(pool_index)
        _cue.mtl_selected = set()
        _cue_sync_video_ts_text()

    def _cue_mtl_get_selected():
        """Get the set of selected marker indices for multi-selection.
        Returns a set of int indices, or empty set if no multi-selection."""
        return getattr(_cue, 'mtl_selected', set())

    def _cue_mtl_get_markers():
        """Get the list of timestamp dicts for the current video."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return []
        return _cue.markers.get(vid_key, {}).get("timestamps", [])

    def _cue_mtl_get_active():
        """Get the active pool index."""
        return _cue.vid_target_pool

    def _cue_mtl_set_active(idx):
        """Set the active pool index."""
        _cue.vid_target_pool = int(idx)

    def _cue_mtl_get_dur():
        """Get video duration, floored at 0.001."""
        return max(0.001, _cue.vid_manager.get_duration())

    def _cue_mtl_set_time(idx, new_time):
        """Write a marker timestamp during drag — no sort/save (done on release)."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        dur = _cue.vid_manager.get_duration()
        new_time = max(0.0, min(new_time, dur - 0.05)) if dur > 0 else max(0.0, new_time)
        if 0 <= idx < len(timestamps):
            timestamps[idx]["time"] = new_time

    def _cue_mtl_finalize():
        """Sort timestamps and save after a drag ends.
        Rebuilds multi-selection indices after re-sort since marker
        positions may change."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if not timestamps:
            return

        # Capture selected timestamp identities before sorting so we can
        # rebuild the selection set after indices shift.
        sel = getattr(_cue, 'mtl_selected', set())
        sel_objects = set()
        for idx in sel:
            if 0 <= idx < len(timestamps):
                sel_objects.add(id(timestamps[idx]))

        pi = _cue.vid_target_pool
        if 0 <= pi < len(timestamps):
            ts_entry = timestamps[pi]
            timestamps.sort(key=lambda ts: ts.get("time", 0))
            new_index = timestamps.index(ts_entry)
            _cue.vid_target_pool = new_index

        # Rebuild selection set from new indices after sort
        if sel_objects:
            new_sel = set()
            for i, ts in enumerate(timestamps):
                if id(ts) in sel_objects:
                    new_sel.add(i)
            _cue.mtl_selected = new_sel
            # Keep active as the first selected marker
            if new_sel:
                _cue.vid_target_pool = min(new_sel)

        _cue_save_markers()

    def _cue_add_video_pool():
        """Create a new empty timestamp at current elapsed time.
        Auto-switches vid_target_pool to the new timestamp."""
        ch = _cue.active_channel
        if not ch or not renpy.music.is_playing(channel=ch):
            return
        elapsed = _cue.vid_manager.get_elapsed()
        if elapsed is None or elapsed <= 0:
            return
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.setdefault(vid_key, {"timestamps": []})
        timestamps = entry.setdefault("timestamps", [])
        timestamps.append({"time": elapsed, "files": []})
        timestamps.sort(key=lambda e: e["time"])
        _cue.vid_target_pool = len(timestamps) - 1
        _cue.mtl_selected = set()
        _cue_save_markers()

    def _cue_remove_video_pool(ts_index):
        """Delete a timestamp pool by index. Clamps vid_target_pool."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if not (0 <= ts_index < len(timestamps)):
            return
        timestamps.pop(ts_index)
        if not timestamps:
            del _cue.markers[vid_key]
            _cue.vid_target_pool = 0
        else:
            _cue.vid_target_pool = min(_cue.vid_target_pool, len(timestamps) - 1)
        _cue.vid_manager.played_video_keys.clear()
        _cue.mtl_selected = set()
        _cue_save_markers()

    def _cue_get_delete_confirm_message():
        """Build the confirmation message listing which markers will be deleted."""
        sel = getattr(_cue, 'mtl_selected', set())
        if len(sel) > 1:
            nums = ", ".join(str(i + 1) for i in sorted(sel))
            return "Delete markers {}?".format(nums)
        else:
            return "Delete marker {}?".format(_cue.vid_target_pool + 1)

    def _cue_remove_selected_markers():
        """Delete selected markers (multi-selection) or active pool (single).
        Removes indices in descending order to avoid index-shift bugs.
        Falls back to active pool if no multi-selection is active."""
        sel = getattr(_cue, 'mtl_selected', set())
        if len(sel) > 1:
            vid_key = create_vid_key(_cue.current_file)
            entry = _cue.markers.get(vid_key, {})
            timestamps = entry.get("timestamps", [])
            if timestamps:
                for idx in sorted(sel, reverse=True):
                    if 0 <= idx < len(timestamps):
                        timestamps.pop(idx)
                if not timestamps:
                    del _cue.markers[vid_key]
                    _cue.vid_target_pool = 0
                else:
                    _cue.vid_target_pool = min(_cue.vid_target_pool, len(timestamps) - 1)
            _cue.vid_manager.played_video_keys.clear()
            _cue.mtl_selected = set()
            _cue_save_markers()
        else:
            # Single marker — delegate to existing per-pool delete
            _cue_remove_video_pool(_cue.vid_target_pool)

    def _cue_duplicate_video_pool(ts_index):
        """Duplicate a timestamp pool with all settings (time, volume, file list).
        Appends the clone, sorts by time, and switches to the new pool."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if not (0 <= ts_index < len(timestamps)):
            return
        original = timestamps[ts_index]
        # Deep-copy files list so the clone is independent
        clone = {
            "time": original["time"],
            "volume": original.get("volume", _cue.VOL_DEFAULT),
            "files": list(original.get("files", [])),
        }
        timestamps.append(clone)
        timestamps.sort(key=lambda e: e["time"])
        _cue.vid_target_pool = timestamps.index(clone)
        _cue.mtl_selected = set()
        _cue_save_markers()

    def _cue_remove_video_file(ts_index, file_index):
        """Remove a single file from a timestamp's files list.
        Keeps the timestamp even if files becomes empty."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if not (0 <= ts_index < len(timestamps)):
            return
        files = timestamps[ts_index].get("files", [])
        if 0 <= file_index < len(files):
            files.pop(file_index)
            _cue.vid_manager.played_video_keys.clear()
            _cue_save_markers()
    

    def _cue_nudge_video_ts(delta):
        """Nudge the active timestamp's time by delta seconds.
        If currently editing, updates both the text buffer and the entry."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        index = _cue.vid_target_pool
        if not (0 <= index < len(timestamps)):
            return
        ts_entry = timestamps[index]
        dur = _cue.vid_manager.get_duration()
        new_time = ts_entry["time"] + delta
        if dur > 0:
            new_time = max(0.0, min(new_time, dur - 0.05))
        else:
            new_time = max(0.0, new_time)
        ts_entry["time"] = new_time
        timestamps.sort(key=lambda e: e["time"])
        # Track the entry to its new position after sort
        try:
            _cue.vid_target_pool = timestamps.index(ts_entry)
        except ValueError:
            pass
        # Keep edit buffer in sync with the nudged value
        _cue.edit_video_ts_text = _cue_format_time(new_time)
        _cue.vid_manager.played_video_keys.clear()
        _cue.mtl_selected = set()
        _cue_save_markers()

    # --- Image markers (i: prefix) ---

    def _cue_add_image_marker(file_index):
        """Add a file to the i: entry for the current image."""
        if not _cue.available_files:
            return
        if file_index < 0 or file_index >= len(_cue.available_files):
            return
        if not _cue.current_file:
            return
        filename = _cue.available_files[file_index]
        if filename in _cue.disabled_files:
            return
        img_key = create_img_key(_cue.current_file)
        _cue_marker_add_file(img_key, filename, _cue.img_target_pool)

    def _cue_remove_image_marker(pool_index, file_index):
        """Remove a file from a specific pool in the i: entry."""
        img_key = create_img_key(_cue.current_file)
        _cue_marker_remove_file(img_key, file_index, pool_index)

    def _cue_clear_image_markers():
        """Remove image markers for the current context."""
        img_key = create_img_key(_cue.current_file)
        _cue.markers.pop(img_key, None)
        _cue_save_markers()

    # --- Dialogue markers (d: prefix) ---

    def _cue_add_dialogue_marker(file_index):
        """Add a file to the d: entry for the current image + dialogue."""
        if not _cue.available_files:
            return
        if file_index < 0 or file_index >= len(_cue.available_files):
            return
        if not _cue.current_dialogue:
            return
        filename = _cue.available_files[file_index]
        if filename in _cue.disabled_files:
            return
        dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))
        _cue_marker_add_file(dlg_key, filename, _cue.dlg_target_pool)

    def _cue_remove_dialogue_marker(pool_index, file_index):
        """Remove a file from a specific pool in the d: entry."""
        dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))
        _cue_marker_remove_file(dlg_key, file_index, pool_index)

    def _cue_clear_dialogue_markers():
        """Remove dialogue markers for the current context."""
        dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))
        _cue.markers.pop(dlg_key, None)
        _cue_save_markers()

    # --- Autoplay (a: prefix) ---

    def _cue_add_to_autoplay_pool(file_index):
        """Add an audio file to the a: pool for the current context."""
        if 0 <= file_index < len(_cue.available_files):
            if not _cue.current_file:
                return
            filename = _cue.available_files[file_index]
            if filename in _cue.disabled_files:
                return
            autoplay_key = create_autoplay_key(_cue.current_file)
            entry = _cue.markers.setdefault(autoplay_key, {"files": [], "frequency": 1})
            files = entry.setdefault("files", [])
            if filename not in files:
                files.append(filename)
            _cue_save_markers()

    def _cue_remove_from_autoplay_pool(file_index):
        """Remove a file from the a: pool for the current context."""
        autoplay_key = create_autoplay_key(_cue.current_file)
        _cue_marker_remove_file(autoplay_key, file_index)

    def _cue_clear_autoplay_pool():
        """Remove pool markers for the current context."""
        autoplay_key = create_autoplay_key(_cue.current_file)
        _cue.markers.pop(autoplay_key, None)
        _cue.autoplay_states.pop(autoplay_key, None)
        _cue_save_markers()

    # --- Bulk clear ---

    # --- Clipboard ---

    def _cue_copy_context():
        """Copy markers for the current context to clipboard."""
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
            entry = _cue.markers.get(key)
            if entry:
                copied[key] = _copy.deepcopy(entry)

        _cue.clipboard = {
            "markers": copied,
            "source_file": ctx_file,
            "source_dialogue": ctx_dlg,
        }

    def _cue_paste_context():
        """Paste clipboard markers into current context, remapping keys."""
        
        import copy as _copy
        if _cue.clipboard is None:
            return
        ctx_file = _cue.current_file
        ctx_dlg = _cue.current_dialogue
        source_file = _cue.clipboard.get("source_file", "")

        for source_key, entry in _cue.clipboard.get("markers", {}).items():
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
            
            # Overwrites existing
            _cue.markers[new_key] = _copy.deepcopy(entry)
            _cue_log(f"{new_key} {str(entry)}")

            # Clamp video timestamps to current video duration
            if is_vid_key(source_key):
                dur = _cue.vid_manager.get_duration()
                pasted_entry = _cue.markers[new_key]
                for ts_entry in pasted_entry.get("timestamps", []):
                    t = ts_entry.get("time", 0)
                    if dur > 0:
                        t = max(0.0, min(t, dur - 0.05))
                    else:
                        t = max(0.0, t)
                    ts_entry["time"] = t

        _cue.vid_manager.played_video_keys.clear()
        _cue.autoplay_states = {}
        _cue_save_markers()

    def _cue_dump_markers():
        """Dump entire persistent._cue_markers to cue_editor/{}.""".format(_cue.config_filename)
        try:
            import json as _json
            dump_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)
            if not os.path.isdir(dump_dir):
                os.makedirs(dump_dir)
            dump_path = os.path.join(dump_dir, _cue.config_filename)
            data = getattr(persistent, '_cue_markers', None)
            if data is None:
                # Ensure current state is saved before dumping
                _cue_save_markers()
                data = getattr(persistent, '_cue_markers', {})
            with open(dump_path, "w") as f:
                _json.dump(data, f, indent=2, sort_keys=True)
            _cue_log("DUMP-MARKERS total_keys={} path={}".format(
                len(_cue.markers), _cue.config_filename))
        except Exception as e:
            _cue_log("DUMP-MARKERS-ERROR {}".format(str(e)))

    def _cue_restore_markers_from_file():
        """Restore persistent._cue_markers from cue_editor/{}.""".format(_cue.config_filename)
        try:
            import json as _json
            dump_path = _cue.config_path
            if not os.path.isfile(dump_path):
                _cue_log("RESTORE-MARKERS-NO-FILE path={}".format(_cue.config_filename))
                return
            with open(dump_path, "r") as f:
                data = _json.load(f)
            persistent._cue_markers = data
            _cue.markers = python_dict(data.get("markers", {}))
            
            _cue.vid_manager.played_video_keys.clear()
            _cue.autoplay_states = {}
            #_cue_normalize_all_markers()
            _cue_save_markers()
            _cue_log("RESTORE-MARKERS total_keys={} path={}".format(
                len(_cue.markers), _cue.config_filename))
        except Exception as e:
            _cue_log("RESTORE-MARKERS-ERROR {}".format(str(e)))


    def _cue_get_autoplay_delay(frequency=1):
        """Return random breathing room (silence) between SFX.
        This is the gap AFTER an SFX finishes before the next one starts.
        frequency: 0=Slow, 1=Normal, 2=Fast, 3=Fastest
        """
        import random
        freq = frequency
        if freq == 3:
            return 0.15 + random.uniform(0.0, 0.05)
        elif freq == 2:
            return 0.5 + random.uniform(0.0, 0.15)
        elif freq == 1:
            return 1.7 + random.uniform(0.0, .75)
        else:
            return 3.0 + random.uniform(0.0, 1.5)

    def _cue_set_autoplay_frequency(trigger_key, freq):
        """Set autoplay frequency for a a: entry. 0 = Slow, 1 = Normal, 2 = Fast, 3 = Fastest."""
        entry = _cue.markers.get(trigger_key)
        if entry:
            entry["frequency"] = int(freq)
            _cue_save_markers()
    




    # --------------------------------------------------------------------------
    # Utility: Time Formatting
    # --------------------------------------------------------------------------

    def _cue_format_time(seconds):
        """Format seconds as MM:SS.cs (centiseconds).

        For durations >= 60 min: HH:MM:SS.cs
        """
        if seconds is None or seconds < 0:
            return "00:00.00"

        total_sec = int(seconds)
        centiseconds = int((seconds - total_sec) * 100)
        minutes = total_sec // 60
        sec_remainder = total_sec % 60

        if minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
            return "{:02d}:{:02d}:{:02d}.{:02d}".format(
                hours, minutes, sec_remainder, centiseconds
            )
        else:
            return "{:02d}:{:02d}.{:02d}".format(
                minutes, sec_remainder, centiseconds
            )


    def _cue_parse_time(time_str):
        """Parse a time string back to float seconds.

        Accepts:
          - "MM:SS.cs"   (e.g. "01:23.45" -> 83.45)
          - "HH:MM:SS.cs" (e.g. "01:02:03.45" -> 3723.45)
          - Raw number as string (e.g. "90.5" -> 90.5)

        Returns None if the string cannot be parsed.
        """
        if time_str is None:
            return None
        # Accept both str and unicode (Py2) / str (Py3)
        try:
            time_str = time_str.strip()
        except AttributeError:
            return None
        if not time_str:
            return None

        # Try raw float
        try:
            val = float(time_str)
            if val >= 0:
                return val
        except ValueError:
            pass

        # Try MM:SS.cs or HH:MM:SS.cs
        parts = time_str.split(":")
        if len(parts) < 2 or len(parts) > 3:
            return None

        try:
            if len(parts) == 2:
                # MM:SS.cs
                minutes = int(parts[0])
                sec_part = parts[1].replace(",", ".")  # accept both . and , as decimal
                seconds = float(sec_part)
                return minutes * 60.0 + seconds
            else:
                # HH:MM:SS.cs
                hours = int(parts[0])
                minutes = int(parts[1])
                sec_part = parts[2].replace(",", ".")
                seconds = float(sec_part)
                return hours * 3600.0 + minutes * 60.0 + seconds
        except (ValueError, IndexError):
            return None

