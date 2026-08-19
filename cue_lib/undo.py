# -*- coding: utf-8 -*-
# CueUndoManager -- snapshot-on-save undo/redo for markers, presets, and
# video_presets.
#
# Hooks into CueMarkerManager._post_save(): every time data is persisted,
# we snapshot the three stores. A short time window dedupes compound operations
# (e.g. remove_file where _detach_pool saves mid-flight) into a single undo step.
#
# Shift+Q = undo, Shift+W = redo.

import copy as _copy
import time as _time
import renpy

from cue_lib.state import _cue
from cue_lib.util import _cue_log
from cue_lib.util import create_img_key, create_dlg_key, create_loop_key, create_vid_key

MYPY = False
if MYPY:
    from typing import Optional  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import UndoSnapshot
    from cue_lib.marker_store import CueMarkerStore
    from cue_lib.state import CueContext
    from cue_lib.video.video_editor import CueVideoEditor
    from cue_lib.markers import CueMarkerManager


class CueUndoManager(object):
    """Undo/redo via post-mutation state snapshots. Max 50 steps; any new
    mutation invalidates the redo stack."""

    MAX_UNDO = 20
    DEDUPE_WINDOW = 0.15  # seconds -- saves within this window share a slot

    def __init__(self, ctx, store, video_editor, markers=None):
        # type: (CueContext, CueMarkerStore, CueVideoEditor, Optional[CueMarkerManager]) -> None
        self._store = store
        self._ctx = ctx
        self._video_editor = video_editor
        # Coordinator for _clamp_ui()'s selection-target reads.  Injected in
        # tests; in the game it resolves to the singleton at call time because
        # the manager is wired after undo (it depends on trigger, which is
        # constructed later) -- so this stays None in cue_z.rpy.
        self._markers = markers
        self._undo = []          # list of {"markers","presets","video_presets"}
        self._redo = []           # redo stack, same shape
        self._last_ts = 0.0       # time of last capture (for dedupe)
        self._previous = None     # state BEFORE the current mutation
        self._recording = True    # False while _restore() re-persists

    # -- snapshot helpers --

    def _snapshot(self):
        # type: () -> UndoSnapshot
        """Deep-copy the three marker stores to plain dicts."""
        m = self._store
        return {
            "markers": _copy.deepcopy(m._data),
            "presets": _copy.deepcopy(m._presets),
            "video_presets": _copy.deepcopy(m._video_presets),
            "session_created": set(m._session_created),
        }

    # -- capture (called from save_marker / save_all / _post_save) --

    def seed(self):
        # type: () -> None
        """Capture the initial state so the first user action is undoable.
        Called once after load_persistent() during init."""
        self._previous = self._snapshot()

    def reset(self):
        # type: () -> None
        """Clear the undo/redo stacks and re-seed to the current state.
        Used after a full restore, where pre-restore snapshots are stale."""
        self._undo = []
        self._redo = []
        self._last_ts = 0.0
        self.seed()

    def capture(self):
        # type: () -> None
        """Snapshot post-mutation state and push the PREVIOUS snapshot
        (pre-mutation) onto the undo stack. Called at the end of every
        save_marker() / save_all(). Time-window dedupe merges rapid saves."""
        if not self._recording:
            # Restore just re-persisted -- re-enable and skip.
            self._recording = True
            return
        snap = self._snapshot()          # post-mutation state
        now = _time.time()
        if self._previous is not None:
            # Push pre-mutation state to undo stack.  Rapid saves within the
            # dedupe window are one compound operation (e.g. remove_file
            # detaches a preset and saves mid-flight) -- keep the FIRST
            # save's entry, which already holds the pre-op state, instead of
            # overwriting it with the mid-flight state.
            if not (self._undo and (now - self._last_ts) < self.DEDUPE_WINDOW):
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
            store = self._store
            old_marker_keys = set(store._data.keys())
            old_presets = store._presets
            old_video_presets = store._video_presets
            old_session_created = set(store._session_created)
            store._data = snap["markers"]
            store._presets = snap["presets"]
            store._video_presets = snap["video_presets"]
            store._session_created = set(snap["session_created"])
            store.save_all()
            store.delete_removed_files(old_marker_keys, old_presets, old_video_presets, old_session_created)
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
        m = self._markers if self._markers is not None else _cue.markers
        store = self._store

        def _count(key):
            # type: (str) -> int
            entry = store._data.get(key)
            return len(entry.get("pools", [])) if entry else 0

        file_ = self._ctx.current_file
        img_key = create_img_key(file_) if file_ else ""
        dlg_key = create_dlg_key((file_, self._ctx.current_dialogue or "")) if file_ else ""
        loop_key = create_loop_key(file_ or "")
        vid_key = create_vid_key(file_) if file_ else ""

        if img_key:
            n = _count(img_key)
            m.image.active_pool = min(m.image.active_pool, n - 1) if n else 0
        if dlg_key:
            n = _count(dlg_key)
            m.dialogue.active_pool = min(m.dialogue.active_pool, n - 1) if n else 0
        if loop_key:
            n = _count(loop_key)
            m.loop.active_pool = min(m.loop.active_pool, n - 1) if n else 0
        if vid_key:
            n = _count(vid_key)
            m.video.active_pool = min(m.video.active_pool, n - 1) if n else 0
            m.video.selected = set()
            m.video.sync_text()

        # Update the video editor UI if visible
        # TODO: This is ugly. doesn't belong here.
        if _cue.is_overlay_visible:
            try:
                self._video_editor.refresh_ui()
            except Exception:
                _cue_log("UNDO-CLAMP: refresh_ui failed")
