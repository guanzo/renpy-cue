# -*- coding: utf-8 -*-
# CueMarkerRepeater -- repeat-pattern dialog for video marker pools.
# Instantiated once at _cue.dialogs.repeater, lives on the NoRollback _cue object.

import renpy

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.state import _cue
from cue_lib.ui.dialogs import CueDialogBase
from cue_lib.util import create_vid_key, _cue_format_time, _cue_parse_time, _cue_clamp_time

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import PoolDict, RepeaterOffset, VideoPoolDict  # pyright: ignore[reportUnusedImport]
    from cue_lib.marker_store import CueMarkerStore  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video import CueVideoManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.state import CueContext  # pyright: ignore[reportUnusedImport]
    from cue_lib.markers import CueMarkerManager  # pyright: ignore[reportUnusedImport]


class CueMarkerRepeater(CueDialogBase):
    """Dialog state machine for repeating video marker patterns.

    Opens over the selected video markers, lets the user set an interval
    and repeat count, then clones the pattern N times at that spacing."""

    def __init__(self, ctx, store, vid_manager, markers=None):
        # type: (CueContext, CueMarkerStore, CueVideoManager, Optional[CueMarkerManager]) -> None
        self._store = store
        self._vid_manager = vid_manager
        self._ctx = ctx
        self._markers = markers
        self._vid_key = ""
        self._pools_id = 0
        # id(pool) -> raw pool dict. Tracked pools are matched by object
        # identity (`is`) against the live entry, so edits made while the
        # dialog is open propagate to the previews in real time.
        self._tracked = None  # type: Optional[Dict[int, Any]]
        self._anchor_pool = None  # type: Optional[Any]
        self._anchor_time = 0.0
        self._anchor_text = ""
        self.offsets = []  # type: List[RepeaterOffset]
        self.sel_count = 0
        self.interval_text = ""
        self.count_text = ""
        self.dialog_visible = False
        self.preview_sfx_enabled = True

    def _video_ctx(self):
        # type: () -> Any
        """Video context sub-object, reached via the markers coordinator.

        Markers is wired after repeater (it needs the trigger engine), so it
        is not a constructor dep -- fall back to the singleton at call time
        unless a fake was injected."""
        m = self._markers if self._markers is not None else _cue.markers
        return m.video

    @property
    def anchor(self):
        # type: () -> float
        """Current anchor time, refreshed by _sync_tracked() on every
        preview computation."""
        return self._anchor_time

    @property
    def anchor_text(self):
        # type: () -> str
        """Formatted anchor time, auto-synced from the tracked anchor pool."""
        return _cue_format_time(self.anchor)

    @anchor_text.setter
    def anchor_text(self, value):
        # type: (str) -> None
        self._anchor_text = value

    def _sync_tracked(self):
        # type: () -> None
        """Re-derive offsets from the live marker entry so edits to the
        tracked (anchor) markers propagate to the previews in real time.

        Tracked pools are matched by object identity against
        entry["pools"]. In-place edits (drag, nudge, files, volume, sort)
        preserve identity and propagate. Deletion removes the object:
        non-anchor ghosts drop out, and deleting the anchor (or every
        tracked marker) ends the preview session -- the dialog screen
        hides itself via a guard. A wholesale store replacement
        (undo/redo, paste, apply video preset) detaches every tracked id,
        so tracking is abandoned and no previews are shown until the
        dialog is reopened."""
        self.offsets = []
        if not self.dialog_visible or not self._vid_key:
            return

        cur_key = create_vid_key(self._ctx.current_file) if self._ctx.current_file else ""
        if cur_key != self._vid_key:
            # Video changed under the dialog: no previews, dialog stays open.
            self._tracked = None
            self._anchor_pool = None
            self._anchor_time = 0.0
            self.sel_count = 0
            return

        entry = self._store.get(self._vid_key)
        if entry is None:
            # Entry cleared: every tracked marker is gone.
            self.dialog_visible = False
            return

        pools = entry.get("pools", [])  # type: Any
        if id(pools) != self._pools_id:
            # Wholesale replacement (undo/redo, paste, apply video preset):
            # tracked identities no longer exist. Show no previews until
            # the dialog is reopened.
            self._pools_id = id(pools)
            self._tracked = None
            self._anchor_pool = None
            self._anchor_time = 0.0
            self.sel_count = 0
            return

        if self._tracked is None or self._anchor_pool is None:
            return

        tracked = []
        for i, pool in enumerate(pools):
            if self._tracked.get(id(pool)) is pool:
                tracked.append((i, pool))
        if not tracked:
            # Every tracked marker was deleted.
            self.dialog_visible = False
            return
        anchor_alive = False
        for _, pool in tracked:
            if pool is self._anchor_pool:
                anchor_alive = True
                break
        if not anchor_alive:
            # The anchor marker was deleted: end the preview session.
            self.dialog_visible = False
            return

        anchor_time = self._anchor_pool.get("time", 0.0)
        self._anchor_time = anchor_time
        for _, pool in tracked:
            r = self._store.resolve_pool(pool)
            self.offsets.append(
                {
                    "offset": pool.get("time", 0.0) - anchor_time,
                    "files": list(r.refs),
                    "volume": r.volume,
                    "igroup": r.igroup,
                    "ilevel_id": r.ilevel_id,
                }
            )
        self.sel_count = len(self.offsets)

    def _shift_selected(self, delta):
        # type: (float) -> None
        """Shift every tracked marker by *delta* seconds, clamped per marker.

        Operates on the live raw pools captured at open(), then re-sorts,
        remaps the editor selection by identity, and persists via
        CueVideoContext.finalize_drag()."""
        if not self.dialog_visible or self._tracked is None or self._anchor_pool is None:
            return
        if not self._vid_key:
            return
        entry = self._store.get(self._vid_key)
        if entry is None:
            return
        pools = entry.get("pools", [])  # type: Any
        if id(pools) != self._pools_id:
            return
        dur = self._vid_manager.get_duration()
        for pool in pools:
            if self._tracked.get(id(pool)) is pool:
                val = pool.get("time", 0.0) + delta
                pool["time"] = _cue_clamp_time(val, dur)
        self._video_ctx().finalize_drag()

    def open(self):
        # type: () -> None
        """Open the Repeat Pattern dialog for the current selection.
        Falls back to the active pool if nothing is selected."""
        markers = self._video_ctx().get_markers()
        if not markers:
            return

        sel = self._video_ctx().get_selected()
        if not sel:
            active = self._video_ctx().active_pool
            if 0 <= active < len(markers):
                sel = {active}
            else:
                return

        sorted_sel = sorted(sel)

        # Track the RAW pool dicts in the marker entry, not the resolved
        # copies get_markers() returns for preset-backed pools. Raw dicts
        # are the stable objects every edit path mutates in place, and
        # resolved order matches raw order 1:1.
        vid_key = create_vid_key(self._ctx.current_file) if self._ctx.current_file else ""
        if not vid_key:
            return
        entry = self._store.get(vid_key)
        if entry is None:
            return
        pools = entry.get("pools", [])  # type: Any
        if not pools or sorted_sel[-1] >= len(pools):
            return

        self._vid_key = vid_key
        self._pools_id = id(pools)
        self._tracked = {}
        for idx in sorted_sel:
            self._tracked[id(pools[idx])] = pools[idx]
        anchor_pool = pools[sorted_sel[0]]
        self._anchor_pool = anchor_pool
        anchor_time = anchor_pool.get("time", 0.0)

        self.dialog_visible = True
        self._sync_tracked()
        if not self.offsets:
            self.dialog_visible = False
            return

        # Default interval:
        # - 2+ markers: span * 2
        # - Single marker: anchor time (distance from 0), floored at 1.0s so a
        #   marker near the start can't balloon the default repeat count.
        max_offset = max(o["offset"] for o in self.offsets)
        if len(sorted_sel) >= 2 and max_offset > 0:
            default_interval = max_offset * 2.0
        else:
            default_interval = max(anchor_time, 1.0)

        if not self.interval_text:
            self.interval_text = "{:.2f}".format(default_interval)

        # Max repeats that fit in video duration
        if not self.count_text:
            dur = self._vid_manager.get_duration()
            if dur > 0 and default_interval > 0:
                max_count = int((dur - anchor_time - max_offset) / default_interval)
                if max_count < 0:
                    max_count = 0
            else:
                max_count = 0
            self.count_text = str(max_count)

        self._show()

    def _offset_pool(self, offset, time):
        # type: (RepeaterOffset, float) -> VideoPoolDict
        """Pool dict for one repeated marker: the offset's content at *time*,
        carrying an intensity hook (igroup/ilevel_id) when the source pool had
        one.  Non-hooked pools omit the keys, matching how pools are stored."""
        clone = {"time": time, "files": list(offset["files"]), "volume": offset.get("volume", CUE_VOLUME_DEFAULT)}
        igroup = offset.get("igroup")
        if igroup is not None:
            clone["igroup"] = igroup
            clone["ilevel_id"] = offset.get("ilevel_id")
        return clone  # pyright: ignore[reportReturnType]

    def apply(self):
        # type: () -> None
        """Apply the repeat pattern: clone markers for each repeat beyond
        the first, using the interval and count from the dialog."""
        self._sync_tracked()
        if not self.offsets or not self._vid_key:
            return
        try:
            interval = float(self.interval_text)
            count = int(self.count_text)
        except (ValueError, TypeError):
            return

        if interval <= 0 or count < 1:
            return

        vid_key = self._vid_key
        entry = self._store._get_or_create_entry(vid_key)
        if "pools" not in entry:
            return
        pools = entry["pools"]

        dur = self._vid_manager.get_duration()

        new_count = 0
        for rep_idx in range(1, count + 1):
            rep_anchor = self.anchor + interval * rep_idx
            for offset in self.offsets:
                new_time = rep_anchor + offset["offset"]
                if dur > 0 and new_time > dur:
                    continue
                if new_time < 0:
                    continue
                pools.append(self._offset_pool(offset, new_time))  # pyright: ignore[reportArgumentType]
                new_count += 1

        if new_count > 0:
            pools.sort(key=lambda e: e["time"])  # pyright: ignore[reportGeneralTypeIssues]
        self._video_ctx().selected = set()
        self._store.save_marker(vid_key)

    def hide(self):
        # type: () -> None
        """Hide the repeat pattern dialog and reset tracking state."""
        self.dialog_visible = False
        self._vid_key = ""
        self._pools_id = 0
        self._tracked = None
        self._anchor_pool = None
        self._anchor_time = 0.0
        self.offsets = []
        self.sel_count = 0
        self._hide()

    def toggle_preview_sfx(self):
        # type: () -> None
        """Toggle whether preview markers trigger SFX during playback."""
        self.preview_sfx_enabled = not self.preview_sfx_enabled

    def compute_preview_times(self):
        # type: () -> list
        """Return sorted list of preview marker times for the overlay.
        Called by CueVideoMarkerTimeline.render() while dialog is visible."""
        if not self.dialog_visible:
            return []
        self._sync_tracked()
        try:
            interval = float(self.interval_text)
            count = int(self.count_text)
        except (ValueError, TypeError):
            return []
        if interval <= 0 or count < 1:
            return []
        if not self.offsets:
            return []

        dur = self._vid_manager.get_duration()
        previews = []

        for rep_idx in range(1, count + 1):
            rep_anchor = self.anchor + interval * rep_idx
            for offset in self.offsets:
                time = rep_anchor + offset["offset"]
                if dur > 0 and time > dur:
                    continue
                if time < 0:
                    continue
                previews.append(time)

        previews.sort()

        return previews

    def compute_preview_pools(self):
        # type: () -> list
        """Return a list of pool dicts shaped like real video marker pools:
        [{"time": t, "files": [...], "volume": v}, ...]."""
        if not self.dialog_visible:
            return []
        self._sync_tracked()
        try:
            interval = float(self.interval_text)
            count = int(self.count_text)
        except (ValueError, TypeError):
            return []
        if interval <= 0 or count < 1:
            return []
        if not self.offsets:
            return []

        dur = self._vid_manager.get_duration()
        pools = []

        for rep_idx in range(1, count + 1):
            rep_anchor = self.anchor + interval * rep_idx
            for _, offset in enumerate(self.offsets):
                time = rep_anchor + offset["offset"]
                if dur > 0 and time > dur:
                    continue
                if time < 0:
                    continue
                pools.append(self._offset_pool(offset, time))

        pools.sort(key=lambda e: e["time"])

        return pools

    def preview_text(self):
        # type: () -> str
        """Return a preview string for the repeat pattern dialog."""
        new_markers = len(self.compute_preview_times())
        if new_markers > 0:
            return "Creates {} new marker(s)".format(new_markers)
        return "No new markers to create"

    def nudge_anchor(self, delta):
        # type: (float) -> None
        """Nudge the entire tracked group by *delta* seconds."""
        self._sync_tracked()
        self._shift_selected(delta)
        renpy.restart_interaction()

    def commit_anchor(self):
        # type: () -> None
        """Commit anchor text; shifts the entire tracked group."""
        self._sync_tracked()
        new_time = _cue_parse_time(self._anchor_text)
        if new_time is not None and new_time >= 0:
            delta = new_time - self.anchor
            if delta:
                self._shift_selected(delta)
        renpy.restart_interaction()

    def commit_interval(self):
        # type: () -> None
        """Commit interval text; resets to 1.00 on invalid input."""
        try:
            val = float(self.interval_text)
            if val <= 0:
                self.interval_text = "1.00"
        except (ValueError, TypeError):
            self.interval_text = "1.00"
        renpy.restart_interaction()

    def nudge_interval(self, delta):
        # type: (float) -> None
        """Nudge interval by delta seconds, clamped to >= 0.01."""
        try:
            val = float(self.interval_text)
        except (ValueError, TypeError):
            val = 1.0
        val = max(0.01, val + delta)
        self.interval_text = "{:.2f}".format(val)
        renpy.restart_interaction()

    def nudge_count(self, delta):
        # type: (int) -> None
        """Nudge repeat count by delta, clamped to >= 0."""
        try:
            val = int(self.count_text)
        except (ValueError, TypeError):
            val = 0
        val = max(0, val + delta)
        self.count_text = str(val)
        renpy.restart_interaction()

    def commit_count(self):
        # type: () -> None
        """Commit count text; resets to 0 on invalid input."""
        try:
            val = int(self.count_text)
            if val < 0:
                self.count_text = "0"
        except (ValueError, TypeError):
            self.count_text = "0"
        renpy.restart_interaction()
