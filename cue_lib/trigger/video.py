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
        self.played_keys = set()
        self._prev_eff_elapsed = -1.0

    def reset(self):
        # type: () -> None
        """Drop video trigger state on a file change."""
        self.played_keys = set()
        self._prev_eff_elapsed = -1.0

    def tick(self, current_file, top_layer_type, speed, variants, tick_interval=0.0, vid_scale=1.0):
        # type: (str, str, float, Optional[List[float]], float, float) -> None
        """Per-frame video marker pass for the current movie channel.

        vid_scale is the video-level global volume for markers not hooked to an
        intensity group (computed by the engine from the per-tick resolution)."""
        vm = self._engine._vid_manager
        ch = vm.channel
        if not ch or top_layer_type != 'movie':
            return

        elapsed = vm.get_elapsed()

        # Autoscale: markers are stored at 1x reference time, so convert
        # variant elapsed to reference time when speed != 1.0.
        effective_elapsed = elapsed * speed

        # Detect video restart BEFORE firing.  Clearing after firing is one
        # tick too late for a marker at t=0: on the wrap tick its key is still
        # in the dedup set (skipped), and by the next tick the position has
        # already passed the tolerance window (missed entirely).
        #   1) last_elapsed == 0: video manager was just reset (new channel
        #      or fresh playback, e.g. after editing the multi-speed queue).
        #   2) elapsed < last_elapsed: playback looped/restarted (Ren'Py
        #      can't seek backwards, so a large backward jump means restart).
        is_fresh_reset = vm.last_elapsed == 0
        is_backward_jump = vm.last_elapsed > 0 and elapsed < vm.last_elapsed - 0.3
        if is_fresh_reset or is_backward_jump:
            self.played_keys.clear()
            self._prev_eff_elapsed = -1.0
            self._engine._debug.note_restart()

        if current_file:
            self._fire_markers(
                current_file,
                effective_elapsed,
                self._prev_eff_elapsed,
                elapsed,
                speed,
                variants,
                tick_interval,
                vid_scale,
            )

        vm.last_elapsed = elapsed
        # Store for next tick's cross-between-ticks detection
        self._prev_eff_elapsed = effective_elapsed

    def _fire_markers(
        self, current_file, effective_elapsed, prev_eff, elapsed, speed, variants, tick_interval=0.0, vid_scale=1.0
    ):
        # type: (str, float, float, float, float, Optional[List[float]], float, float) -> None
        """Fire SFX for this video's markers passed since the last tick.

        Preview markers from the repeat dialog ride along as extra pools.
        Skips markers already fired (played_keys) and pools missing a
        time (logged, not crashed).  The dedup set and prev_eff bookkeeping
        live in tick().  elapsed is the raw media position at this tick
        (effective_elapsed = elapsed * speed), passed through so the
        PLAY-SFX log can report trigger accuracy."""
        vid_key = create_vid_key(current_file)
        markers = self._engine._markers_ctx().video.get_markers()
        vid_entry = self._engine._store.get(vid_key)

        # Tack preview markers onto the list -- they're already pool dicts
        # shaped like real video markers (time/files/volume).
        preview_count = 0
        if self._engine._repeater.dialog_visible and self._engine._repeater.preview_sfx_enabled:
            preview_pools = self._engine._repeater.compute_preview_pools()
            markers.extend(preview_pools)
            preview_count = len(preview_pools)

        if not markers:
            return

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

            t = pool_entry["time"]
            count = time_counts.setdefault(t, 0) + 1
            time_counts[t] = count
            ts_key = "{}@{:.3f}#{}".format(vid_key, t, count)

            if ts_key in self.played_keys:
                continue

            if not _cue_marker_reached(t, effective_elapsed, prev_eff, marker_tolerance, marker_lead):
                continue

            resolved = self._engine._store.resolve_pool(pool_entry, speed, variants, flags=flags, expand=True)
            files = resolved.files or []
            vol_mult = resolved.volume_mult if resolved.intensity is not None else vid_scale
            f = _cue_pick_file(files, avoid_repeats=False)
            if f is not None:
                f = _cue.sfx.play_pool(
                    entry,  # pyright: ignore[reportArgumentType]
                    vid_key,
                    pool_entry,
                    pool_index,
                    file=f,
                    volume_mult=vol_mult,
                    marker_time=t,
                    marker_elapsed=elapsed,
                    marker_delta=effective_elapsed - t,
                )
            if f:
                # Track as its own kind so exclusive cut-ins spare it.
                # Overwrites any stale entry on the reused channel (dlg loops
                # etc.), which is what makes the immunity deterministic.
                self._engine.excl.track_channel(f, CUE_EXCL_KIND_VIDEO, current_file, None, False)
                self.played_keys.add(ts_key)
                self._engine._debug.note_fire(t, effective_elapsed, current_file)
            elif not is_preview:
                # Reached but playback produced nothing (empty intensity
                # folder / play_sfx exception).  Mark it fired so it doesn't
                # retry every tick and noisily re-enter the missed check; the
                # play-failed report carries the accuracy signal.
                self.played_keys.add(ts_key)
                self._engine._debug.note_failed_fire(t, effective_elapsed, current_file)

        self._engine._debug.end_fire_loop(current_file, effective_elapsed, self.played_keys, markers, preview_count)
