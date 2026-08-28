# -*- coding: utf-8 -*-
# CueVideoTrigger -- v_ key marker-timed SFX.  One domain of CueTriggerEngine;
# the engine owns tick cadence and passes the current video-level global
# volume scale in.

from cue_lib.state import _cue
from cue_lib.trigger.exclusive import CUE_EXCL_KIND_VIDEO
from cue_lib.trigger.helpers import _cue_marker_lead, _cue_marker_reached
from cue_lib.util import _cue_log, _cue_pick_file, create_vid_key

MYPY = False
if MYPY:
    from typing import List, Optional
    from cue_lib.trigger.engine import CueTriggerEngine  # pyright: ignore[reportUnusedImport]


class CueVideoTrigger(object):
    """Video pool triggers for v_ keys -- fires SFX at marked times.

    Uses two complementary checks so markers aren't missed when playback
    position jumps more than marker_tolerance between ticks (common on
    short videos, high-speed playback, or coarse get_pos() steps):

      1. Forward window:  mt <= eff < mt + tolerance    (stationary / first tick)
      2. Cross check:     prev_eff < mt <= eff           (jumped past marker)
    """

    def __init__(self, engine):
        # type: (CueTriggerEngine) -> None
        self._engine = engine
        self.reset()

    def reset(self):
        # type: () -> None
        """Drop video trigger state on a file change."""
        self.played_keys = set()
        self._prev_eff_elapsed = -1.0
        self._last_fire_eff = None
        self._last_fired_mt = None

    def tick(self, current_file, top_layer_type, speed, variants, tick_interval=0.0, vid_scale=1.0):
        # type: (str, str, float, Optional[List[float]], float, float) -> None
        """Per-frame video marker pass for the current movie channel.

        vid_scale is the video-level global volume for markers not hooked to an
        intensity group (computed by the engine from the per-tick resolution)."""
        vm = self._engine._vid_manager
        ch = vm.channel
        if not ch or top_layer_type != 'movie' or not current_file:
            return

        elapsed = vm.get_elapsed()

        # Autoscale: markers are stored at 1x reference time, so convert
        # variant elapsed to reference time when speed != 1.0.
        effective_elapsed = elapsed * speed

        if vm.is_restart:
            self.played_keys.clear()
            self._prev_eff_elapsed = -1.0
            self._last_fire_eff = None
            self._last_fired_mt = None
            self._engine._debug.note_restart()
            vm.clear_sfx_breadcrumbs()

        self._fire_markers(
            current_file, effective_elapsed, self._prev_eff_elapsed, speed, variants, tick_interval, vid_scale
        )

        # Store for next tick's cross-between-ticks detection.  vm.last_elapsed
        # is written by vm.poll_restart() (the restart source of truth).
        self._prev_eff_elapsed = effective_elapsed

    def _fire_markers(
        self, current_file, effective_elapsed, prev_eff, speed, variants, tick_interval=0.0, vid_scale=1.0
    ):
        # type: (str, float, float, float, Optional[List[float]], float, float) -> None
        """Fire SFX for this video's markers passed since the last tick.

        Preview markers from the repeat dialog ride along as extra pools.
        Skips markers already fired (played_keys) and pools missing a
        time (logged, not crashed).  The dedup set and prev_eff bookkeeping
        live in tick()."""
        vid_key = create_vid_key(current_file)
        markers = self._engine._markers_ctx().video.get_markers()
        vid_entry = self._engine._store.get(vid_key)

        if not markers:
            return

        # Tack preview markers onto the list -- they're already pool dicts
        # shaped like real video markers (time/files/volume).
        preview_count = 0
        if self._engine._repeater.dialog_visible and self._engine._repeater.preview_sfx_enabled:
            preview_pools = self._engine._repeater.compute_preview_pools()
            markers.extend(preview_pools)
            preview_count = len(preview_pools)

        # Breadcrumb axis: the playhead paints at get_elapsed()/get_duration()
        # (file-frac), so stamp each fire at that same frac to compare against
        # the moving playhead.  Dur read once per call (fires are sparse).
        vid = self._engine._vid_manager
        dur = vid.get_duration()

        flags = _cue.intensity.flags_from_entry(vid_entry)
        # Per-time counter so same-time markers get unique stable keys.  Keyed
        # by time instead of list index -- adding/removing markers at other
        # timestamps doesn't invalidate already-fired keys.
        time_counts = {}
        marker_tolerance = 0.08
        # Lead compensation: fire up to half a tick's expected advance before
        # each marker so deltas center on 0 instead of always landing late.
        marker_lead = _cue_marker_lead(tick_interval, speed)

        for idx, pool_entry in enumerate(markers):
            is_preview = idx >= len(markers) - preview_count
            entry = {"pools": [pool_entry]} if is_preview else vid_entry
            pool_index = 0 if is_preview else idx

            if "time" not in pool_entry:
                if not is_preview:
                    _cue_log("MISSING TIME " + vid_key + " " + str(vid_entry) + " " + str(pool_entry))
                continue

            ts = pool_entry["time"]
            count = time_counts.setdefault(ts, 0) + 1
            time_counts[ts] = count
            ts_key = "{}@{:.3f}#{}".format(vid_key, ts, count)

            if ts_key in self.played_keys:
                continue

            if not _cue_marker_reached(ts, effective_elapsed, prev_eff, marker_tolerance, marker_lead):
                continue

            resolved = self._engine._store.resolve_pool(pool_entry, speed, variants, flags=flags, expand=True)
            files = resolved.files or []
            vol_mult = resolved.volume_mult if resolved.intensity is not None else vid_scale
            f = _cue_pick_file(files, avoid_repeats=False)
            # gap is the reference-time spacing consumed since the previous
            # fire; None on the first marker of a loop (no predecessor).  In a
            # double-fire w/o a restart, gap collapses to ~0 -- the tell.
            gap = (effective_elapsed - self._last_fire_eff) if self._last_fire_eff is not None else None
            # Expected gap is the marker-time spacing (ts_now - ts_prev), the
            # value gap% in the log is measured against.
            expected_gap = (ts - self._last_fired_mt) if self._last_fired_mt is not None else None
            if f is not None:
                f = _cue.sfx.play_pool(
                    entry,  # pyright: ignore[reportArgumentType]
                    vid_key,
                    pool_entry,
                    pool_index,
                    file=f,
                    volume_mult=vol_mult,
                    marker_time=ts,
                    marker_elapsed=effective_elapsed,
                    marker_err=effective_elapsed - ts,
                    marker_gap=gap,
                    marker_gap_expected=expected_gap,
                )
            if f:
                # Track as its own kind so exclusive cut-ins spare it.
                # Overwrites any stale entry on the reused channel (dlg loops
                # etc.), which is what makes the immunity deterministic.
                self._engine.excl.track_channel(f, CUE_EXCL_KIND_VIDEO, current_file, None, False)

                self.played_keys.add(ts_key)
                self._last_fire_eff = effective_elapsed
                self._last_fired_mt = ts

                # Stamp the playhead position this SFX fired at (file-frac), so
                # the timeline trail can be compared to the moving playhead.
                if speed > 0 and dur > 0:
                    vid.record_sfx_breadcrumb((effective_elapsed / speed) / dur)
                self._engine._debug.note_fire(ts, effective_elapsed, current_file)
            elif not is_preview:
                # Reached but playback produced nothing (empty intensity
                # folder / play_sfx exception).  Mark it fired so it doesn't
                # retry every tick and noisily re-enter the missed check; the
                # play-failed report carries the accuracy signal.
                self.played_keys.add(ts_key)
                self._engine._debug.note_failed_fire(ts, effective_elapsed, current_file)

        self._engine._debug.end_fire_loop(current_file, effective_elapsed, self.played_keys, markers, preview_count)
