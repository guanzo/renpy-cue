###############################################################################
# Cue Editor — Utility Functions
# Key helpers, persistent unwrap, audio scanning, time formatting,
# debug logging, file resolution, displayable name helpers.
###############################################################################

init python:
    import os

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

    def _cue_unwrap_displayable(name_or_displayable):
        """Recursively unwrap Transform (.child) and ImageReference (.target)
        wrappers to find the underlying Image/Movie displayable.
        Returns the unwrapped displayable, or None if input was None.
        Guards against reference cycles with a max iteration count."""
        if isinstance(name_or_displayable, str):
            d = renpy.displayable(name_or_displayable)
        else:
            d = name_or_displayable

        seen = 0
        while d is not None and seen < 50:
            if hasattr(d, "child") and d.child is not None:
                d = d.child
            elif hasattr(d, "_target") and callable(d._target):
                try:
                    resolved = d._target()
                except Exception:
                    resolved = None
                if resolved is None or resolved is d:
                    break
                d = resolved
            elif hasattr(d, "target") and d.target is not None:
                d = d.target
            else:
                break
            seen += 1
        return d


    def _cue_get_movie_or_image(name_or_displayable):
        """Given an image tag/name (str) or a displayable object, returns
        (kind, displayable) where kind is 'movie', 'image', or None if
        neither could be resolved."""

        d = _cue_unwrap_displayable(name_or_displayable)

        if isinstance(d, renpy.display.video.Movie):
            return "movie", d
        if isinstance(d, renpy.display.im.Image):
            return "image", d
        return None, d

    # --------------------------------------------------------------------------
    # Persistent Data Helpers
    # --------------------------------------------------------------------------

    def _cue_unwrap_persistent(data):
        """Recursively convert Ren'Py RevertableDict/RevertableList/RevertableSet
        wrappers to plain Python dict/list/set. Duck-typing avoids isinstance
        which fails on wrapped types; json.dumps also fails for the same reason.
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
        # Set before list — sets are also iterable but have add/discard
        if hasattr(data, "add") and hasattr(data, "discard"):
            return python_set(_cue_unwrap_persistent(v) for v in data)
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
        rpy_files = []
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
                os.path.normpath(os.path.join(renpy.config.gamedir, _cue.audio_dir))
            )
        else:
            _cue.scan_error = None

        # Rebuild visible tree for sidebar
        _cue.file_tree.rebuild_tree()


    # --------------------------------------------------------------------------
    # Utility: Time Formatting
    # --------------------------------------------------------------------------

    def _cue_clamp_time(t, dur):
        """Clamp time t to [0, dur - END_MARGIN], handling dur <= 0."""
        if dur > 0:
            return max(0.0, min(t, dur - _cue.END_MARGIN))
        return max(0.0, t)

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


    # --------------------------------------------------------------------------
    # Debug Logging
    # --------------------------------------------------------------------------

    def _cue_log(msg):
        """Append a debug message to renpy_cue/debug.log."""
        try:
            import time as _logtime
            log_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir)
            log_path = os.path.join(log_dir, _cue.debug_log_filename)
            with open(log_path, "a") as f:
                ts = _logtime.strftime("%H:%M:%S") + ".{:03d}".format(int(_logtime.time() * 1000) % 1000)
                f.write("[{}] {}\n".format(ts, msg))
        except Exception:
            pass  # Never let logging break the game


    # --------------------------------------------------------------------------
    # File Resolution & Random Picking
    # --------------------------------------------------------------------------

    def _cue_resolve_files(files):
        """Resolve a files list: expand folder refs (trailing '/') to matching
        available files, skip disabled files, pass through direct references."""
        result = []
        for item in files:
            if item.endswith("/"):
                # Folder reference — expand to all matching available files
                for f in _cue.available_files:
                    if f.startswith(item) and f not in _cue.file_tree.disabled_files and f not in result:
                        result.append(f)
            elif item not in _cue.file_tree.disabled_files and item not in result:
                result.append(item)
        return result

    def _cue_pick_file(files, avoid_repeats=True):
        """Pick a random file from a list.
        If avoid_repeats is True, avoids files in the global last_played list.
        Repeat avoidance is shared across all non-video contexts.
        Video markers should pass avoid_repeats=False — they always fire.
        """
        import random as _random
        if not files:
            return None
        if len(files) == 1:
            f = files[0]
        elif avoid_repeats:
            last = _cue.last_played
            f = _random.choice(files)
            tries = 0
            while f in last and tries < 10:
                f = _random.choice(files)
                tries += 1
            last.append(f)
            if len(last) > 2:
                last.pop(0)
        else:
            f = _random.choice(files)
        return f


    # --------------------------------------------------------------------------
    # Displayable Name Helpers
    # --------------------------------------------------------------------------

    def _cue_top_layer_name(name):
        """Normalize a displayable name to a single string.
        Image names are tuples like ('bg', 'forest') — use the tag ('bg')."""
        if name is None:
            return None
        if isinstance(name, tuple) and name:
            name = name[0]
        name = str(name)
        if not name:
            return None
        return name


    def _cue_top_movie_name(movie):
        """Context name for a Movie on the master layer.
        Movie has no 'name' in Ren'Py 7/8 — fall back to the file basename
        from its 'play' attribute (which may be a list of paths)."""
        name = _cue_top_layer_name(getattr(movie, "name", None))
        if name:
            return name
        play = getattr(movie, "play", None)
        if isinstance(play, list):
            play = play[0] if play else None
        if play:
            return str(play).replace("\\", "/").rsplit("/", 1)[-1]
        return None


    # --------------------------------------------------------------------------
    # Transition Helpers
    # --------------------------------------------------------------------------

    def _is_screenshake(trans):
        """Detect whether a transition is a screenshake (Move with bounce,
        repeat, and short delay). Used to trigger SFX on shake events."""
        import functools
        try:
            if trans is None:
                return False

            if not isinstance(trans, functools.partial):
                return False

            func_name = getattr(trans.func, "__name__", "")
            if func_name != "Move":
                return False

            kw = trans.keywords or {}
            return (
                kw.get("bounce", False) == True
                and kw.get("repeat", False) == True
                and kw.get("delay") is not None
                and kw.get("delay") < 0.5
            )
        except Exception:
            return False


    # --------------------------------------------------------------------------
    # SFX Playback Helpers
    # --------------------------------------------------------------------------

    def _cue_loop_still_playing(channels):
        """True if any channel in the list is currently playing.
        Unknown/unregistered channels are treated as silent."""
        for ch in channels:
            try:
                if renpy.music.is_playing(channel=ch):
                    return True
            except Exception:
                pass
        return False
