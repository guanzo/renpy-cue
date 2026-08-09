# -*- coding: utf-8 -*-
# CueBeatManager -- repeat-pattern dialog for video marker pools.
# Instantiated once at _cue.beat, lives on the NoRollback _cue object.

import renpy

from cue_lib.state import _cue
from cue_lib.util import create_vid_key

MYPY = False
if MYPY:
    from cue_lib._types import BeatOffset, VideoPoolDict


class CueBeatManager(object):
    """Dialog state machine for repeating video marker patterns.

    Opens over the selected video markers, lets the user set an interval
    and repeat count, then clones the pattern N times at that spacing."""

    def __init__(self):
        self.anchor = 0.0
        self.offsets = []
        self.sel_count = 0
        self.interval_text = ""
        self.count_text = ""
        self.dialog_visible = False
        self.preview_sfx_enabled = True

    def open(self):
        # type: () -> None
        """Open the Repeat Pattern dialog for the current selection.
        Falls back to the active pool if nothing is selected."""
        markers = _cue.markers.video.get_markers()
        if not markers:
            return

        sel = _cue.markers.video.get_selected()
        if not sel:
            active = _cue.markers.video.target_pool
            if 0 <= active < len(markers):
                sel = {active}
            else:
                return

        sorted_sel = sorted(sel)
        anchor_time = markers[sorted_sel[0]]["time"]

        offsets = []
        for idx in sorted_sel:
            pool = markers[idx]
            offsets.append({
                "offset": pool["time"] - anchor_time,
                "files": list(pool.get("files", [])),
                "volume": pool.get("volume", _cue.volume.VOL_DEFAULT),
            })

        self.anchor = anchor_time
        self.offsets = offsets
        self.sel_count = len(sorted_sel)

        # Default interval:
        # - 2+ markers: span * 2
        # - Single marker: anchor time (distance from 0)
        max_offset = max(o["offset"] for o in offsets)
        if len(sorted_sel) >= 2 and max_offset > 0:
            default_interval = max_offset * 2.0
        else:
            default_interval = anchor_time if anchor_time > 0 else 1.0
        if default_interval <= 0:
            default_interval = 1.0

        self.interval_text = "{:.2f}".format(default_interval)

        # Max repeats that fit in video duration
        dur = _cue.vid_manager.get_duration()
        if dur > 0 and default_interval > 0:
            max_count = int((dur - anchor_time - max_offset) / default_interval)
            if max_count < 0:
                max_count = 0
        else:
            max_count = 0
        self.count_text = str(max_count)

        self.dialog_visible = True
        renpy.show_screen("cue_repeat_pattern_dialog", _layer="cue_layer")

    def apply(self):
        # type: () -> None
        """Apply the repeat pattern: clone markers for each beat beyond
        the first, using the interval and count from the dialog."""
        try:
            interval = float(self.interval_text)
            count = int(self.count_text)
        except (ValueError, TypeError):
            return

        if interval <= 0 or count < 1:
            return

        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return

        entry = _cue.markers._get_or_create_entry(vid_key)
        pools = entry["pools"]

        dur = _cue.vid_manager.get_duration()

        new_count = 0
        for beat_idx in range(1, count + 1):
            beat_anchor = self.anchor + interval * beat_idx
            for offset in self.offsets:
                new_time = beat_anchor + offset["offset"]
                if dur > 0 and new_time > dur:
                    continue
                if new_time < 0:
                    continue
                clone = {
                    "time": new_time,
                    "files": list(offset["files"]),
                    "volume": offset["volume"],
                }
                pools.append(clone)
                new_count += 1

        if new_count > 0:
            pools.sort(key=lambda e: e["time"])
        _cue.markers.video.selected = set()
        _cue.markers.save_persistent()

    def hide(self):
        # type: () -> None
        """Hide the repeat pattern dialog."""
        self.dialog_visible = False
        renpy.hide_screen("cue_repeat_pattern_dialog", layer="cue_layer")

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
        try:
            interval = float(self.interval_text)
            count = int(self.count_text)
        except (ValueError, TypeError):
            return []
        if interval <= 0 or count < 1:
            return []
        if not self.offsets:
            return []

        dur = _cue.vid_manager.get_duration()
        previews = []

        for beat_idx in range(1, count + 1):
            beat_anchor = self.anchor + interval * beat_idx
            for offset in self.offsets:
                time = beat_anchor + offset["offset"]
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
        try:
            interval = float(self.interval_text)
            count = int(self.count_text)
        except (ValueError, TypeError):
            return []
        if interval <= 0 or count < 1:
            return []
        if not self.offsets:
            return []

        dur = _cue.vid_manager.get_duration()
        pools = []

        for beat_idx in range(1, count + 1):
            beat_anchor = self.anchor + interval * beat_idx
            for offset_idx, offset in enumerate(self.offsets):
                time = beat_anchor + offset["offset"]
                if dur > 0 and time > dur:
                    continue
                if time < 0:
                    continue
                pools.append({
                    "time": time,
                    "files": list(offset.get("files", [])),
                    "volume": offset.get("volume", _cue.VOL_DEFAULT),
                })

        pools.sort(key=lambda e: e["time"])

        return pools

    def preview_text(self):
        # type: () -> str
        """Return a preview string for the repeat pattern dialog."""
        new_markers = len(self.compute_preview_times())
        if new_markers > 0:
            return "Creates {} new marker(s)".format(new_markers)
        return "No new markers to create"

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
