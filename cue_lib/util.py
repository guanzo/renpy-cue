# -*- coding: utf-8 -*-
# Cue Editor -- Utility Functions
# Key helpers, persistent unwrap, audio scanning, time formatting,
# debug logging, file resolution, displayable name helpers.

import os
import time
import random as _random
import functools as _functools
import threading as _threading
import pygame
import renpy
import renpy.atl as _atl
import renpy.config as _config
import renpy.display.video as _video
import renpy.display.im as _im
import renpy.audio.music as _music

import cue_lib.constants as _constants  # module ref so CUE_DEBUG stays live (tests flip it)

from cue_lib.constants import (
    CUE_IMG_KEY_PREFIX, CUE_LOOP_KEY_PREFIX, CUE_DLG_KEY_PREFIX, CUE_VID_KEY_PREFIX,
)
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
    """Build an image trigger key: 'i_<file>'."""
    return CUE_IMG_KEY_PREFIX + file

def create_vid_key(file):
    # type: (str) -> str
    """Build a video trigger key: 'v_<file>'."""
    return CUE_VID_KEY_PREFIX + file

def create_loop_key(file):
    # type: (str) -> str
    """Build a loop trigger key: 'l_<file>'. file may be '' for global pool."""
    return CUE_LOOP_KEY_PREFIX + file

def create_dlg_key(dlg_pair):
    # type: (Tuple[str, str]) -> str
    """Build a dialogue trigger key from a (file, dialogue) pair.
    Usage: create_dlg_key((_cue.current_file, _cue.current_dialogue))"""
    file, dialogue = dlg_pair
    return CUE_DLG_KEY_PREFIX + file + "__" + dialogue

def is_img_key(key):
    # type: (str) -> bool
    """Check if key is an image trigger key."""
    return key.startswith(CUE_IMG_KEY_PREFIX)

def is_vid_key(key):
    # type: (str) -> bool
    """Check if key is a video trigger key."""
    return key.startswith(CUE_VID_KEY_PREFIX)

def is_dlg_key(key):
    # type: (str) -> bool
    """Check if key is a dialogue trigger key."""
    return key.startswith(CUE_DLG_KEY_PREFIX)

def is_loop_key(key):
    # type: (str) -> bool
    """Check if key is a loop trigger key."""
    return key.startswith(CUE_LOOP_KEY_PREFIX)

def _cue_strip_key_prefix(key):
    # type: (str) -> str
    """Strip the leading type prefix ('i_', 'v_', 'l_', 'd_') from a trigger key."""
    for prefix in (CUE_IMG_KEY_PREFIX, CUE_VID_KEY_PREFIX,
                   CUE_LOOP_KEY_PREFIX, CUE_DLG_KEY_PREFIX):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key

def get_key_file(key):
    # type: (str) -> str
    """Strip the 2-char prefix from any key, returning the file portion."""
    file_part = key[len(CUE_IMG_KEY_PREFIX):]
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
    file_part = key[len(CUE_DLG_KEY_PREFIX):]
    # Handle both legacy | and current __ separators
    for sep_str in ("__", "|"):
        parts = file_part.split(sep_str, 1)
        if len(parts) == 2:
            return parts[1]
    return ""

def get_key_prefix(key):
    # type: (str) -> str
    """Return the 2-char prefix of a key ('i_', 'v_', 'd_', or 'l_')."""
    return key[:len(CUE_IMG_KEY_PREFIX)]


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


def _cue_split_pipes(query):
    # type: (str) -> List[str]
    """Split query into OR alternatives on unescaped pipes.

    A backslash-pipe (\\|) is a literal pipe character inside one alternative,
    so a filename that itself contains a pipe can still be matched literally
    (e.g. "a\\|b" matches the file "a|b").  A lone trailing backslash is kept
    literally."""
    parts = []
    current = []
    i = 0
    while i < len(query):
        ch = query[i]
        if ch == "\\" and i + 1 < len(query) and query[i + 1] == "|":
            current.append("|")
            i += 2
            continue
        if ch == "|":
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def _cue_compile_query(query):
    # type: (str) -> Callable[[str], bool]
    """Build a path matcher from a search query.

    The query is an OR of pipe-separated alternatives; each alternative is an
    AND of whitespace-separated terms.  So "amira|slide" matches a path
    containing "amira" OR "slide", and "nora intense|amira" matches one
    containing both "nora" and "intense" OR one containing "amira".  A query
    with no pipe matches exactly as before (AND over its terms).  A backslash
    before a pipe (\\|) escapes it -- a literal pipe inside one alternative,
    for matching filenames that themselves contain "|".  Matching is
    case-insensitive substring against the full path; an all-empty query
    matches nothing (callers that want match-all guard for it).
    """
    alternatives = _cue_split_pipes(query)

    def _match(path):
        # type: (str) -> bool
        path = path.lower()
        for alt in alternatives:
            terms = alt.lower().split()
            if not terms:
                continue
            if all(term in path for term in terms):
                return True
        return False

    return _match


def _cue_filter_tree(tree, query):
    # type: (List[Dict[str, Any]], str) -> List[Dict[str, Any]]
    """Build a filtered copy of a nested tree for a search query.

    A file matches when the query matches its full path (see _cue_compile_query
    -- OR of pipe-separated alternatives, each an AND of whitespace-separated
    terms; case-insensitive substring).  A folder is kept when it matches the
    query itself (keeping ALL its descendants) or when it has a matching
    descendant (keeping only the matching branches).  Result nodes mirror
    _cue_build_tree's shapes; folder nodes are new dicts, file leaves are
    reused unchanged.  The source tree is never mutated, and ordering is
    preserved -- nodes are only removed, never reordered.
    """
    query = query.strip()
    if not query:
        return []

    _matches = _cue_compile_query(query)

    def _filter(items, prefix):
        # type: (List[Dict[str, Any]], str) -> List[Dict[str, Any]]
        result = []
        for item in items:
            full = prefix + item["name"]
            if item["type"] == "file":
                if _matches(full):
                    result.append(item)
            else:
                folder_matches = _matches(full)
                children = _filter(item.get("children", []), full)
                if folder_matches or children:
                    result.append({
                        "type": "folder",
                        "name": item["name"],
                        "children": item.get("children", []) if folder_matches else children,
                        "expanded": item.get("expanded", False),
                        "has_files": item.get("has_files", False),
                    })
        return result

    return _filter(tree, "")


def _cue_query_matches(name, query):
    # type: (str, str) -> bool
    """True when the query matches name (see _cue_compile_query: OR of
    pipe-separated alternatives, each an AND of terms, case-insensitive
    substring), matching _cue_filter_tree's path semantics.  An empty query
    matches everything.

    Used by the search bar to filter preset names the same way the file tree
    filters paths."""
    if not query.strip():
        return True
    return _cue_compile_query(query)(name)


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
    # Round to nearest centisecond (+0.5 is round-half-up, identical in Py2/Py3).
    # int() truncation here made a click-then-Enter commit drop the display one
    # centisecond: float("1.20") is 1.1999999999999999556, below the 1.20 bucket.
    centiseconds = int((seconds - total_sec) * 100 + 0.5)
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

# Debug lines buffer in memory and flush in batches: a burst of lines costs
# one file open instead of one per line.  The main-thread slow tick flushes
# it, so the log stays near-realtime; background threads only append under the
# lock, never write.  The log is truncated on every restart, so it never
# grows unbounded.
_cue_log_buffer = []
_cue_log_lock = _threading.Lock()


def _cue_log(msg):
    # type: (str) -> None
    """Buffer a debug message, flushing once the buffer crosses its threshold."""
    try:
        if not _constants.CUE_DEBUG:
            return
        ts = time.strftime("%H:%M:%S") + ".{:03d}".format(int(time.time() * 1000) % 1000)
        line = "[{}] {}\n".format(ts, msg)
        with _cue_log_lock:
            _cue_log_buffer.append(line)
            should_flush = len(_cue_log_buffer) >= _constants.CUE_DEBUG_LOG_BUFFER_LINES
        if should_flush:
            _cue_flush_debug_log()
    except Exception:
        pass  # Never let logging break the game

def _cue_flush_debug_log():
    # type: () -> None
    """Write all buffered debug lines to disk.  Main-thread only."""
    try:
        global _cue_log_buffer
        with _cue_log_lock:
            lines = _cue_log_buffer
            _cue_log_buffer = []
        _cue_write_debug_lines(lines)
    except Exception:
        pass  # Never let logging break the game

def _cue_write_debug_lines(lines):
    # type: (list) -> None
    log_path = _cue_log_path()
    if log_path is None:
        return
    with open(log_path, "a") as f:
        f.write("".join(lines))

def _cue_clear_debug_log():
    # type: () -> None
    """Truncate (or create) the debug log and drop any buffered lines."""
    try:
        global _cue_log_buffer
        with _cue_log_lock:
            _cue_log_buffer = []
        log_path = _cue_log_path()
        if log_path is None:
            return
        open(log_path, "w").close()
    except Exception:
        pass  # Never let clearing the log break the game

def _cue_log_path():
    # type: () -> str
    """Resolve the debug log path, creating its directory.  None on failure."""
    log_dir = os.path.join(_config.gamedir, _cue.paths.in_game_base_dir)
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    return os.path.join(log_dir, _constants.CUE_DEBUG_LOG_FILENAME)


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


def _cue_wrap_with_statement(original_with_statement):
    # type: (Any) -> Any
    """Build the renpy.with_statement wrapper.  Flags screenshake transitions
    (SFX trigger), then forwards every arg unchanged so a future engine that
    adds kwargs can't break the hook."""
    def _wrapped(*args, **kwargs):
        trans = args[0] if args else kwargs.get("trans")
        if trans is not None and _cue_is_screenshake(trans):
            _cue._shake_just_happened = True
        if original_with_statement is not None:
            return original_with_statement(*args, **kwargs)
    return _wrapped


def _cue_wrap_config_show(original_config_show):
    # type: (Any) -> Any
    """Build the renpy.config.show wrapper.  Screenshake applied via "at"
    (e.g. "scene foo at vpunch, cum1") bypasses with_statement, so at_list is
    scanned here too.  Forwards every arg unchanged -- a future engine adding
    kwargs (transient, munge_name, ...) must not break the hook."""
    def _wrapped(*args, **kwargs):
        at_list = kwargs.get("at_list")
        if at_list is None and len(args) >= 2:
            at_list = args[1]
        if at_list:
            for t in at_list:
                if _cue_is_screenshake(t):
                    _cue._shake_just_happened = True
                    break
        if original_config_show is not None:
            return original_config_show(*args, **kwargs)
    return _wrapped


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
