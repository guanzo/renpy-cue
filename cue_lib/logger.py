# -*- coding: utf-8 -*-
# CueLogger -- debug and error log writer.
# Owns the buffered debug log (gated by CUE_DEBUG, flushed by the main-thread
# slow tick) and the write-through error log (unguarded, for critical errors
# in the per-frame hot spots).  util.py keeps a thin _cue_log delegator (that
# call site count is huge); the handful of flush/clear/error callers use
# _cue_logger directly.

import os
import sys as _sys
import threading as _threading
import time
import traceback as _traceback

import renpy.config as _config

import cue_lib.constants as _constants  # module ref so CUE_DEBUG stays live (tests flip it)

from cue_lib.state import _cue

MYPY = False
if MYPY:
    from typing import Any

# Debug / error log filenames, written into the in-game base dir.
CUE_DEBUG_LOG_FILENAME = "debug.log"
CUE_ERROR_LOG_FILENAME = "error.log"


class CueLogger(object):
    """Debug + error log writer."""

    def __init__(self, lock=None):
        # type: (Any) -> None
        self._buffer = []
        self._lock = lock if lock is not None else _threading.Lock()

    # --- Debug log (buffered, gated by CUE_DEBUG) ---

    def log(self, msg):
        # type: (str) -> None
        """Buffer a debug message, flushing once the buffer crosses its threshold."""
        try:
            if not _constants.CUE_DEBUG:
                return
            ts = time.strftime("%H:%M:%S") + ".{:03d}".format(int(time.time() * 1000) % 1000)
            line = "[{}] {}\n".format(ts, msg)
            with self._lock:
                self._buffer.append(line)
                should_flush = len(self._buffer) >= 64
            if should_flush:
                self.flush()
        except Exception:
            pass  # Never let logging break the game

    def flush(self):
        # type: () -> None
        """Write all buffered debug lines to disk.  Main-thread only."""
        try:
            with self._lock:
                lines = self._buffer
                self._buffer = []
            self._write_debug_lines(lines)
        except Exception:
            pass  # Never let logging break the game

    def clear_debug(self):
        # type: () -> None
        """Truncate (or create) the debug log and drop any buffered lines."""
        try:
            with self._lock:
                self._buffer = []
            with open(self._log_path(CUE_DEBUG_LOG_FILENAME), "w"):
                pass
        except Exception:
            pass  # Never let clearing the log break the game

    # --- Error log (write-through, unguarded) ---

    def log_error(self, msg):
        # type: (str) -> None
        """Persist a critical error to error.log, unguarded by CUE_DEBUG.

        Write-through (append, no buffering) so a crash right after logging
        still lands the line.  When called inside an except handler, the active
        traceback is appended so bug reports carry the full call stack."""
        try:
            ts = time.strftime("%H:%M:%S") + ".{:03d}".format(int(time.time() * 1000) % 1000)
            parts = ["[{}] {}\n".format(ts, msg)]
            if _sys.exc_info()[0] is not None:
                tb = _traceback.format_exc()
                if tb:
                    parts.append(tb.rstrip() + "\n")
            with self._lock:
                with open(self._log_path(CUE_ERROR_LOG_FILENAME), "a") as f:
                    f.write("".join(parts))
        except Exception:
            pass  # Never let logging break the game

    def clear_error(self):
        # type: () -> None
        """Truncate (or create) the error log.  Runs at boot so each session
        starts clean, matching debug.log's restart truncation."""
        try:
            with self._lock:
                with open(self._log_path(CUE_ERROR_LOG_FILENAME), "w"):
                    pass
        except Exception:
            pass  # Never let clearing the log break the game

    # --- Internals ---

    def _write_debug_lines(self, lines):
        # type: (list) -> None
        log_path = self._log_path(CUE_DEBUG_LOG_FILENAME)
        if log_path is None:
            return
        with open(log_path, "a") as f:
            f.write("".join(lines))

    def _log_path(self, filename):
        # type: (str) -> str
        """Resolve a log file path inside the in-game base dir, creating its
        directory if missing."""
        log_dir = os.path.join(_config.gamedir, _cue.paths.in_game_base_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        return os.path.join(log_dir, filename)


_cue_logger = CueLogger()
