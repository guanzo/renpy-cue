# -*- coding: utf-8 -*-
# Cue Editor -- Utility Functions
# Key helpers, persistent unwrap, audio scanning, time formatting,
# debug logging, file resolution, displayable name helpers.

import os
import time
import random as _random
import functools as _functools
import pygame
import renpy
import renpy.atl as _atl
import renpy.config as _config
import renpy.display.video as _video
import renpy.display.im as _im
import renpy.audio.music as _music

from cue_lib.state import _cue
from renpy.store import Function

# Import time again for _logtime alias used by _cue_log
_logtime = time

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, List, Optional, Tuple, Union
    from renpy.display.video import Movie


# --------------------------------------------------------------------------
# UI Refresh Decorator
# --------------------------------------------------------------------------

def _cue_ui_refresh(fn):
    # type: (Callable[..., Any]) -> Callable[..., Any]
    """Decorator for screen-action methods. Calls renpy.restart_interaction()
    in a finally block so every return/exception path gets a UI refresh
    automatically -- methods can drop their explicit restart calls."""
    def _wrapper(*args, **kwargs):
        # type: (*Any, **Any) -> Any
        try:
            return fn(*args, **kwargs)
        finally:
            renpy.restart_interaction()
    return _wrapper


# --------------------------------------------------------------------------
# Key Utility Functions
# --------------------------------------------------------------------------

def create_img_key(file):
    # type: (str) -> str
    """Build an image trigger key: 'i:<file>'."""
    return _cue.IMG_KEY_PREFIX + file

def create_vid_key(file):
    # type: (str) -> str
    """Build a video trigger key: 'v:<file>'."""
    return _cue.VID_KEY_PREFIX + file

def create_loop_key(file):
    # type: (str) -> str
    """Build a loop trigger key: 'l:<file>'. file may be '' for global pool."""
    return _cue.LOOP_KEY_PREFIX + file

def create_dlg_key(dlg_pair):
    # type: (Tuple[str, str]) -> str
    """Build a dialogue trigger key from a (file, dialogue) pair.
    Usage: create_dlg_key((_cue.current_file, _cue.current_dialogue))"""
    file, dialogue = dlg_pair
    return _cue.DLG_KEY_PREFIX + file + "__" + dialogue

def is_img_key(key):
    # type: (str) -> bool
    """Check if key is an image trigger key."""
    return key.startswith(_cue.IMG_KEY_PREFIX)

def is_vid_key(key):
    # type: (str) -> bool
    """Check if key is a video trigger key."""
    return key.startswith(_cue.VID_KEY_PREFIX)

def is_dlg_key(key):
    # type: (str) -> bool
    """Check if key is a dialogue trigger key."""
    return key.startswith(_cue.DLG_KEY_PREFIX)

def is_loop_key(key):
    # type: (str) -> bool
    """Check if key is a loop trigger key."""
    return key.startswith(_cue.LOOP_KEY_PREFIX)

def _cue_strip_key_prefix(key):
    # type: (str) -> str
    """Strip the leading type prefix ('i_', 'v_', 'l_', 'd_') from a trigger key."""
    for prefix in (_cue.IMG_KEY_PREFIX, _cue.VID_KEY_PREFIX,
                   _cue.LOOP_KEY_PREFIX, _cue.DLG_KEY_PREFIX):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key

def get_key_file(key):
    # type: (str) -> str
    """Strip the 2-char prefix from any key, returning the file portion."""
    file_part = key[len(_cue.IMG_KEY_PREFIX):]
    if is_dlg_key(key):
        # Handle both legacy | and current __ separators
        sep = file_part.find("__")
        if sep == -1:
            sep = file_part.find("|")
        if sep != -1:
            file_part = file_part[:sep]
    return file_part

def get_key_dialogue(key):
    # type: (str) -> str
    file_part = key[len(_cue.DLG_KEY_PREFIX):]
    # Handle both legacy | and current __ separators
    for sep_str in ("__", "|"):
        parts = file_part.split(sep_str, 1)
        if len(parts) == 2:
            return parts[1]
    return ""

def get_key_prefix(key):
    # type: (str) -> str
    """Return the 2-char prefix of a key ('i:', 'v:', 'd:', or 'l:')."""
    return key[:len(_cue.IMG_KEY_PREFIX)]


# --------------------------------------------------------------------------
# Displayable Helpers
# --------------------------------------------------------------------------

def _cue_unwrap_displayable(name_or_displayable):
    # type: (Union[str, Any]) -> Any
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
        if hasattr(d, "child") and d.child is not None:  # pyright: ignore[reportAttributeAccessIssue]
            d = d.child  # pyright: ignore[reportAttributeAccessIssue]
        elif hasattr(d, "_target") and callable(d._target):  # pyright: ignore[reportAttributeAccessIssue]
            try:
                resolved = d._target()  # pyright: ignore[reportAttributeAccessIssue]
            except Exception:
                resolved = None
            if resolved is None or resolved is d:
                break
            d = resolved
        elif hasattr(d, "target") and d.target is not None:  # pyright: ignore[reportAttributeAccessIssue]
            d = d.target  # pyright: ignore[reportAttributeAccessIssue]
        else:
            break
        seen += 1
    return d


def _cue_get_movie_or_image(name_or_displayable):
    # type: (Union[str, Any]) -> Tuple[Any, Any]
    """Given an image tag/name (str) or a displayable object, returns
    (kind, displayable) where kind is 'movie', 'image', or None if
    neither could be resolved."""

    d = _cue_unwrap_displayable(name_or_displayable)

    if isinstance(d, _video.Movie):
        return "movie", d
    if isinstance(d, _im.Image):
        return "image", d
    return None, d


def _cue_atl_child_displayables(d):
    # type: (Any) -> Optional[List[Any]]
    """Return the displayable children (renpy.atl.Child statements) of an
    ATL image definition, or None if d is not an ATL transform or its block
    can't be compiled.

    Used by wrap_all_movies() to link ATL-wrapped movies -- one-way videos
    shown via multi-part tags like 'bg <name> movie' -- to the Movie images
    they display."""
    if not isinstance(d, _atl.ATLTransformBase):
        return None
    block = getattr(d, "block", None)
    if block is None:
        try:
            d.compile()
        except Exception:
            return None
        block = getattr(d, "block", None)
    if block is None or not hasattr(block, "statements"):
        return None
    children = []
    for stmt in block.statements:
        try:
            if isinstance(stmt, _atl.Child):
                children.append(stmt.child)
        except Exception:
            continue
    return children if children else None


# --------------------------------------------------------------------------
# Persistent Data Helpers
# --------------------------------------------------------------------------

def _to_str(obj):
    # type: (Any) -> Any
    """Recursively encode unicode keys and values to UTF-8 str (Python 2).

    In Python 3 this is a no-op -- str and unicode are the same type.
    """
    try:
        unicode  # pyright: ignore[reportUndefinedVariable, reportUnusedExpression]
    except NameError:
        return obj

    if isinstance(obj, unicode):  # pyright: ignore[reportUndefinedVariable]
        return obj.encode("utf-8")
    if isinstance(obj, str):
        return obj
    if hasattr(obj, "items") and hasattr(obj, "keys"):
        return {_to_str(k): _to_str(v) for k, v in obj.items()}
    if hasattr(obj, "__iter__"):
        return [_to_str(v) for v in obj]
    return obj


def _cue_unwrap_persistent(data):
    # type: (Any) -> Any
    """Recursively convert Ren'Py RevertableDict/RevertableList/RevertableSet
    wrappers to plain Python dict/list/set. Duck-typing avoids isinstance
    which fails on wrapped types; json.dumps also fails for the same reason.
    Strings/basestrings must be guarded -- they are iterable."""
    if isinstance(data, (str, bytes)):
        return data
    try:
        if isinstance(data, unicode):  # pyright: ignore[reportUndefinedVariable]
            return data
    except NameError:
        pass
    if hasattr(data, "items") and hasattr(data, "keys"):
        return dict((k, _cue_unwrap_persistent(v)) for k, v in data.items())
    # Set before list -- sets are also iterable but have add/discard
    if hasattr(data, "add") and hasattr(data, "discard"):
        return set(_cue_unwrap_persistent(v) for v in data)
    if hasattr(data, "__iter__"):
        return list(_cue_unwrap_persistent(v) for v in data)
    return data


# --------------------------------------------------------------------------
# Audio File Scanning
# --------------------------------------------------------------------------

def _cue_build_tree(flat_files):
    # type: (List[str]) -> List
    """Build a nested tree of folder/file nodes from a sorted flat list of
    relative paths.

    Folder nodes: {"type": "folder", "name": <name + "/">, "children": [...],
    "expanded": False, "has_files": bool} -- folders first, then files.
    File nodes: {"type": "file", "name": <basename>}.
    """
    root = {}
    for path in flat_files:
        parts = path.split("/")
        node = root
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # It's a file
                node.setdefault("__files__", []).append(part)
            else:
                # It's a folder
                node = node.setdefault(part, {})

    def _build(node):
        # type: (Dict[str, Any]) -> List
        items = []
        # Folders first
        for name in sorted(node.keys()):
            if name == "__files__":
                continue
            children = _build(node[name])
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

    return _build(root)


# --------------------------------------------------------------------------
# Utility: Time Formatting
# --------------------------------------------------------------------------

def _cue_clamp_time(t, dur):
    # type: (float, float) -> float
    """Clamp time t to [0, dur], handling dur <= 0."""
    if dur > 0:
        return max(0.0, min(t, dur))
    return max(0.0, t)

def _cue_format_time(seconds):
    # type: (Optional[float]) -> str
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

def _cue_speed_label(sp):
    # type: (float) -> str
    """Format a speed multiplier for UI display: 1.0 -> '1.0x', 1.5 -> '1.5x'."""
    return "{:.1f}x".format(sp)


def _cue_parse_time(time_str):
    # type: (Optional[str]) -> Optional[float]
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
    # type: (str) -> None
    """Append a debug message to renpy_cue/debug.log."""
    try:
        if not _cue.debug:
            return
        log_dir = os.path.join(_config.gamedir, _cue.paths.in_game_base_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        log_path = os.path.join(log_dir, _cue.debug_log_filename)
        with open(log_path, "a") as f:
            ts = time.strftime("%H:%M:%S") + ".{:03d}".format(int(time.time() * 1000) % 1000)
            f.write("[{}] {}\n".format(ts, msg))
    except Exception:
        pass  # Never let logging break the game


# --------------------------------------------------------------------------
# File Resolution & Random Picking
# --------------------------------------------------------------------------

def _cue_resolve_files(files):
    # type: (List[str]) -> List[str]
    """Resolve a files list: expand folder refs (trailing '/') to matching
    available files, skip disabled files, pass through direct references."""
    result = []
    for item in files:
        if item.endswith("/"):
            # Folder reference -- expand to all matching available files
            for f in _cue.sfx_manager.files:
                if f.startswith(item) and f not in _cue.sfx_manager.disabled_files and f not in result:
                    result.append(f)
        elif item not in _cue.sfx_manager.disabled_files and item not in result:
            result.append(item)
    return result

def _cue_pick_file(files, avoid_repeats=True):
    # type: (List[str], bool) -> Optional[str]
    """Pick a random file from a list.
    If avoid_repeats is True, avoids files in the global last_played list.
    Repeat avoidance is shared across all non-video contexts.
    Video markers should pass avoid_repeats=False -- they always fire.
    """
    if not files:
        return None
    if len(files) == 1:
        f = files[0]
    elif avoid_repeats:
        last = _cue.trigger.last_played
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
# File System Helpers
# --------------------------------------------------------------------------

def _cue_replace_file(src, dst):
    # type: (str, str) -> None
    """Rename src over dst, overwriting an existing dst.

    POSIX os.rename overwrites atomically; on Windows it refuses with Error
    183, so a stale destination is removed first.  Reaching for this rather
    than bare os.rename is what keeps overwrite semantics working on both
    platforms (see CLAUDE.md).  Callers that rewrite a file in place should
    write a temp file first, then _cue_replace_file(tmp, final), so a
    mid-write kill never truncates the file at its real path."""
    if os.name == "nt" and os.path.lexists(dst):
        try:
            os.remove(dst)
        except Exception:
            pass  # Rename below fails loudly if the stale file persists
    os.rename(src, dst)


# --------------------------------------------------------------------------
# Screen Helpers
# --------------------------------------------------------------------------

def _cue_make_tab_action(fn, args_tuple, pi):
    # type: (Callable[..., None], tuple, int) -> Callable[..., None]
    return Function(fn, *(tuple(args_tuple) + (pi,)))


def _cue_shift_held():
    # type: () -> bool
    mods = pygame.key.get_mods()
    return bool(mods & (pygame.KMOD_LSHIFT | pygame.KMOD_RSHIFT))


# --------------------------------------------------------------------------
# Displayable Name Helpers
# --------------------------------------------------------------------------

def _cue_top_layer_name(name):
    # type: (Any) -> Optional[str]
    """Normalize a displayable name to a single string.
    Image names are tuples like ('bg', 'forest') -- use the tag ('bg')."""
    if name is None:
        return None
    if isinstance(name, tuple) and name:
        name = name[0]
    name = str(name)
    if not name:
        return None
    return name


def _cue_top_movie_name(movie):
    # type: (Movie) -> Optional[str]
    """Context name for a Movie on the master layer.
    Movie has no 'name' in Ren'Py 7/8 -- fall back to the file basename
    from its 'play' attribute (which may be a list of paths)."""
    name = _cue_top_layer_name(getattr(movie, "name", None))
    if name:
        return name
    play = getattr(movie, "play", None)
    if hasattr(play, "__iter__") and not isinstance(play, (str, bytes)):
        play = play[0] if play else None
    if play:
        return str(play).replace("\\", "/").rsplit("/", 1)[-1]
    return None

# _original_play only exists in Ren'Py 8.x; fall back to _play for 7.x
def _cue_get_movie_play(movie):
    # type: (Movie) -> str
    raw_play = getattr(movie, '_original_play', None)
    if raw_play is None:
        raw_play = getattr(movie, '_play', None)
    # Duck typing: isinstance(x, list) fails when Ren'Py shadows list->RevertableList
    if hasattr(raw_play, "__iter__") and not isinstance(raw_play, (str, bytes)):
        raw_play = raw_play[0] if raw_play else ""
    # str() is a no-op for every reachable value (str or None) and lets
    # pyright drop the bytes member of the negated-isinstance narrowing.
    return str(raw_play or "")


# --------------------------------------------------------------------------
# Transition Helpers
# --------------------------------------------------------------------------

def _cue_is_screenshake(trans):
    # type: (Any) -> bool
    """Detect whether a transition is a screenshake (Move with bounce,
    repeat, and short delay). Used to trigger SFX on shake events."""
    try:
        if trans is None:
            return False

        # Ren'Py wraps Move in either functools.partial (8.x) or
        # renpy.curry.Curry (7.x).  They have the same shape but
        # different attribute names -- duck-type to handle both.
        if isinstance(trans, _functools.partial):
            func = trans.func
            kw = trans.keywords or {}
        elif hasattr(trans, "callable") and hasattr(trans, "kwargs"):
            # renpy.curry.Curry
            func = trans.callable
            kw = trans.kwargs or {}
        else:
            return False

        func_name = getattr(func, "__name__", "")
        if func_name != "Move":
            return False

        _delay = kw.get("delay")
        return (
            kw.get("bounce", False) == True
            and kw.get("repeat", False) == True
            and _delay is not None
            and type(_delay) in (int, float)
            and _delay < 0.5
        )
    except Exception:
        return False


# --------------------------------------------------------------------------
# SFX Playback Helpers
# --------------------------------------------------------------------------

def _cue_sfx_channel_name(index):
    # type: (int) -> str
    """Channel name for a 1-based index into the shared _cue_ SFX channels."""
    return "_cue_{}".format(index)


def _cue_sfx_channel_index(ch_name):
    # type: (str) -> int
    """Reverse of _cue_sfx_channel_name: parse the 1-based index from a
    shared _cue_ SFX channel name."""
    return int(ch_name.split("_")[-1])


def _cue_loop_still_playing(channels):
    # type: (List[str]) -> bool
    """True if any channel in the list is currently playing.
    Unknown/unregistered channels are treated as silent."""
    for ch in channels:
        try:
            if _music.is_playing(channel=ch):
                return True
        except Exception:
            pass
    return False
