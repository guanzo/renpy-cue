###############################################################################
# Cue Editor — Key Utilities, Audio Scanning, Time Formatting
# Marker CRUD has moved to CueMarkerManager (cue_marker.rpy).
# All functions run in a single init python block.
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

    def create_loop_key(file):
        """Build a loop trigger key: 'l:<file>'. file may be '' for global pool."""
        return _cue.LOOP_KEY_PREFIX + file

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

    def is_loop_key(key):
        """Check if key is a loop trigger key."""
        return key.startswith(_cue.LOOP_KEY_PREFIX)

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
        """Return the 2-char prefix of a key ('i:', 'v:', 'd:', or 'l:')."""
        return key[:len(_cue.IMG_KEY_PREFIX)]


    # --------------------------------------------------------------------------
    # Persistent Data Helpers
    # --------------------------------------------------------------------------

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


    # --------------------------------------------------------------------------
    # Audio File Scanning
    # --------------------------------------------------------------------------

    def _cue_scan_audio():
        """Scan audio dir and build folder tree."""

        search_path = _cue.audio_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        audio_exts = (".ogg", ".mp3", ".wav", ".opus", ".flac")

        results_set = set()

        # Source 1: Ren'Py's cached index (covers .rpa archives)
        try:
            rpy_files = renpy.list_files()
            for f in rpy_files:
                if f.startswith(search_path):
                    relative = f[len(search_path):]
                    if relative and f.lower().endswith(audio_exts):
                        results_set.add(relative)
        except Exception:
            pass  # Fall through to filesystem scan below

        # Source 2: Live filesystem scan (picks up files added after startup)
        fs_dir = os.path.join(renpy.config.gamedir, search_path)
        if os.path.isdir(fs_dir):
            for dirpath, _dirnames, filenames in os.walk(fs_dir, followlinks=True):
                rel_dir = os.path.relpath(dirpath, fs_dir)
                if rel_dir == ".":
                    rel_dir = ""
                for fname in filenames:
                    if fname.lower().endswith(audio_exts):
                        rel_path = (rel_dir + "/" + fname) if rel_dir else fname
                        rel_path = rel_path.replace("\\", "/")
                        results_set.add(rel_path)

        if not results_set and not rpy_files:
            # Both sources failed entirely
            _cue.available_files = []
            _cue.audio_tree = []
            _cue.scan_error = "Failed to list files"
            return

        results = sorted(results_set)
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


    def _cue_is_file_in_loop_pool(full_path):
        """Check if a file is in any pool of the current context's l: entry."""
        if not _cue.current_file:
            return False
        loop_key = create_loop_key(_cue.current_file)
        entry = _cue.markers.get(loop_key)
        if entry:
            for _pool in entry.get("pools", []):
                if full_path in _cue.markers.resolve_pool(_pool).files:
                    return True
        return False


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
                    "in_pool": _cue_is_file_in_loop_pool(full),
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


    def _cue_toggle_file_ref_expand(folder_ref):
        """Toggle expand/collapse for a folder ref in a pool file list."""
        if folder_ref in _cue.expanded_file_refs:
            _cue.expanded_file_refs[folder_ref] = not _cue.expanded_file_refs[folder_ref]
        else:
            _cue.expanded_file_refs[folder_ref] = True


    def _cue_toggle_presets_expand():
        """Toggle expand/collapse for the Presets/ folder in the SFX Library."""
        _cue._presets_expanded = not _cue._presets_expanded


    def _cue_toggle_preset_expand(preset_name):
        """Toggle expand/collapse for a single preset in the SFX Library."""
        if preset_name in _cue._expanded_presets:
            _cue._expanded_presets[preset_name] = not _cue._expanded_presets[preset_name]
        else:
            _cue._expanded_presets[preset_name] = True


    def _cue_toggle_video_presets_expand():
        """Toggle expand/collapse for the Video Presets/ folder in the SFX Library."""
        _cue._video_presets_expanded = not _cue._video_presets_expanded


    def _cue_toggle_video_preset_expand(preset_name):
        """Toggle expand/collapse for a single video preset in the SFX Library."""
        if preset_name in _cue._expanded_video_presets:
            _cue._expanded_video_presets[preset_name] = not _cue._expanded_video_presets[preset_name]
        else:
            _cue._expanded_video_presets[preset_name] = True


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
