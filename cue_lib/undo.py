# -*- coding: utf-8 -*-
# CueUndoManager -- snapshot-on-save undo/redo for markers, presets, and
# video_presets.
#
# Hooks into CueMarkerManager.save_persistent(): every time data is persisted,
# we snapshot the three stores. A short time window dedupes compound operations
# (e.g. remove_file where _detach_pool saves mid-flight) into a single undo step.
#
# Shift+Q = undo, Shift+W = redo.

import copy as _copy
import time as _time
import renpy

from cue_lib.state import _cue
from cue_lib.util import create_img_key, create_dlg_key, create_loop_key, create_vid_key

MYPY = False
if MYPY:
    from cue_lib._types import UndoSnapshot


class CueUndoManager(object):
    """Undo/redo via post-mutation state snapshots. Max 50 steps; any new
    mutation invalidates the redo stack."""

    MAX_UNDO = 20
    DEDUPE_WINDOW = 0.15  # seconds -- saves within this window share a slot

    def __init__(self):
        self._undo = []          # list of {"markers","presets","video_presets"}
        self._redo = []           # redo stack, same shape
        self._last_ts = 0.0       # time of last capture (for dedupe)
        self._previous = None     # state BEFORE the current mutation
        self._recording = True    # False while _restore() re-persists

    # -- snapshot helpers --

    def _snapshot(self):
        # type: () -> UndoSnapshot
        """Deep-copy the three marker stores to plain dicts."""
        m = _cue.markers
        return {
            "markers": _copy.deepcopy(m._data),
            "presets": _copy.deepcopy(m._presets),
            "video_presets": _copy.deepcopy(m._video_presets),
        }

    # -- capture (called from save_persistent) --

    def seed(self):
        # type: () -> None
        """Capture the initial state so the first user action is undoable.
        Called once after load_persistent() during init."""
        self._previous = self._snapshot()

    def capture(self):
        # type: () -> None
        """Snapshot post-mutation state and push the PREVIOUS snapshot
        (pre-mutation) onto the undo stack. Called at the end of every
        save_persistent(). Time-window dedupe merges rapid saves."""
        if not self._recording:
            # Restore just re-persisted -- re-enable and skip.
            self._recording = True
            return
        snap = self._snapshot()          # post-mutation state
        now = _time.time()
        if self._previous is not None:
            # Push pre-mutation state to undo stack
            if self._undo and (now - self._last_ts) < self.DEDUPE_WINDOW:
                self._undo[-1] = self._previous  # overwrite top of stack
            else:
                self._undo.append(self._previous)
                if len(self._undo) > self.MAX_UNDO:
                    self._undo.pop(0)
            self._redo = []   # new action invalidates redo
            self._last_ts = now
        self._previous = snap  # this becomes pre-state for next mutation

    # -- undo / redo --

    def can_undo(self):
        # type: () -> bool
        """True if there is at least one undo step available."""
        return len(self._undo) > 0

    def can_redo(self):
        # type: () -> bool
        """True if there is at least one redo step available."""
        return len(self._redo) > 0

    def undo(self):
        # type: () -> None
        """Shift+Q: restore the previous snapshot from the undo stack."""
        if not self._undo:
            return
        # Save current state to redo stack
        self._redo.append(self._snapshot())
        prev = self._undo.pop()
        self._restore(prev)

    def redo(self):
        # type: () -> None
        """Shift+W: re-apply a snapshot that was previously undone."""
        if not self._redo:
            return
        # Save current state to undo stack
        self._undo.append(self._snapshot())
        if len(self._undo) > self.MAX_UNDO:
            self._undo.pop(0)
        nxt = self._redo.pop()
        self._restore(nxt)

    # -- restore --

    def _restore(self, snap):
        # type: (UndoSnapshot) -> None
        """Replace live stores with the snapshot, re-persist without
        recording a new undo entry, and clamp UI state."""
        self._recording = False
        try:
            m = _cue.markers
            m._data = snap["markers"]
            m._presets = snap["presets"]
            m._video_presets = snap["video_presets"]
            m.save_persistent()
        finally:
            self._recording = True
        # Seed _previous so the next real mutation pushes the correct
        # pre-state. Reset _last_ts to avoid deduping across the
        # undo/redo boundary.
        self._previous = self._snapshot()
        self._last_ts = 0.0
        self._clamp_ui()
        renpy.restart_interaction()

    def _clamp_ui(self):
        # type: () -> None
        """Clamp active pool indices after a restore so they don't point
        past the end of the restored pool lists."""
        m = _cue.markers

        def _count(key):
            # type: (str) -> int
            entry = m._data.get(key)
            return len(entry.get("pools", [])) if entry else 0

        img_key = create_img_key(_cue.current_file) if _cue.current_file else ""
        dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue or "")) if _cue.current_file else ""
        loop_key = create_loop_key(_cue.current_file or "")
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""

        if img_key:
            n = _count(img_key)
            m._img_target = min(m._img_target, n - 1) if n else 0
        if dlg_key:
            n = _count(dlg_key)
            m._dlg_target = min(m._dlg_target, n - 1) if n else 0
        if loop_key:
            n = _count(loop_key)
            m._loop_target = min(m._loop_target, n - 1) if n else 0
        if vid_key:
            n = _count(vid_key)
            m.video.target_pool = min(m.video.target_pool, n - 1) if n else 0
            m.video.selected = set()
            m.video.sync_text()
        # Update the video editor UI if visible
        if _cue.is_overlay_visible:
            try:
                _cue.video_editor.refresh_ui()
            except Exception:
                pass
