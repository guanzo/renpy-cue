###############################################################################
# CueTriggerEngine — trigger dispatch for i:, d:, l:, v: keys and shake.
# Instantiated once at _cue.trigger, lives on the NoRollback _cue object.
###############################################################################

init -999 python:
    import time as _time
    import random as _random

    class CueTriggerEngine:
        """Owns trigger dispatch state and logic.

        Called by:
        - _cue_tick_trigger() every frame for time-based triggers (loop + video)
        - _cue_refresh_context() when scene/dialogue/shake context changes
        """

        def __init__(self):
            self.active = True
            self.loop_states = {}
            self.loop_current = None
            self.last_played = []
            self.played_video_keys = set()
            self._prev_eff_elapsed = -1.0
            self._tick_count = 0

        # ── tick entry point ──

        def tick(self, current_file, top_layer_type):
            """Called every frame. Handles loop (l:) and video (v:) triggers."""
            if not self.active:
                return

            self._tick_count += 1
            tick = self._tick_count
            now = _time.time()

            self._tick_loop(now, tick, current_file)
            self._tick_video(current_file, top_layer_type)

        # ── context triggers (i:, d:, shake) ──

        def fire_context(self, *keys, **kwargs):
            """Fire i:, d:, or shake triggers for the given keys.

            Multi-pool entries play one random file from EACH pool concurrently.
            Dedupe guard: same file in two pools of the same trigger is re-picked
            up to 3 times, then skipped to avoid echo artifacts.

            When only_shake_pools is True, pools without the trigger_on_shake flag
            are skipped — used by screenshake triggers so each pool independently
            opts in to firing on shake."""
            only_shake_pools = kwargs.get("only_shake_pools", False)
            if not self.active:
                return
            for key in keys:
                if not key:
                    continue
                entry = _cue.markers.get(key)
                if not entry:
                    continue
                pools = entry.get("pools", [])
                if not pools:
                    continue
                vol = entry.get("volume", 1.0)
                total = sum(len(_cue.markers.resolve_pool(p).files) for p in pools)

                _cue_log("CTX-TRIGGER key={} pools={} files={} vol={:.2f}".format(
                    key, len(pools), total, vol))

                picked = []
                for pi, pool in enumerate(pools):
                    resolved = _cue.markers.resolve_pool(pool)
                    if only_shake_pools and not resolved.trigger_on_shake:
                        continue
                    files = _cue_resolve_files(resolved.files)
                    if not files:
                        continue
                    file = _cue_pick_file(files)
                    tries = 0
                    while file in picked and len(files) > 1 and tries < 3:
                        file = _cue_pick_file(files)
                        tries += 1
                    if file in picked:
                        continue
                    picked.append(file)
                    _cue_play_pool(entry, key, pool, pi, file=file)

        # ── loop triggers (l: keys) ──

        def _tick_loop(self, now, tick, current_file):
            """Loop state machine for l: keys — fires pooled SFX on a frequency cycle."""
            loop_key = create_loop_key(current_file or "")

            entry = _cue.markers.get(loop_key)
            if entry is None:
                return
            pools = entry.get("pools", [])
            # Collect frequencies from resolved pools with files, default 1
            freqs = []
            for p in pools:
                resolved = _cue.markers.resolve_pool(p)
                if resolved.files:
                    freqs.append(resolved.frequency)
            if not freqs:
                return

            # Init per-pool states under the loop key
            if loop_key not in self.loop_states:
                self.loop_states[loop_key] = {}
            ps = self.loop_states[loop_key]

            # Collect all active loop channels and dead-air channels
            all_active = []
            exclusive_channels = []
            for pst in ps.values():
                if isinstance(pst, dict) and "channels" in pst:
                    all_active.extend(pst.get("channels", []))
                    if pst.get("is_exclusive"):
                        exclusive_channels.extend(pst.get("channels", []))

            # Post-dead-air breathing window (50-100ms) — no pool fires during this
            _exclusive_done_at = ps.get("_exclusive_done_at", 0.0)

            picked = []
            for pi, pool in enumerate(pools):
                resolved = _cue.markers.resolve_pool(pool)
                files = _cue_resolve_files(resolved.files)
                if not files:
                    continue

                pst = ps.get(pi)
                if pst is None:
                    init_delay = _random.uniform(0.0, _cue.markers.loop.get_delay(resolved.frequency))
                    ps[pi] = {"ready_at": now + init_delay, "channels": [], "play_start": 0.0, "is_exclusive": False}
                    pst = ps[pi]

                # If this pool's channels are done playing, reset for next cycle
                if pst["channels"] and not _cue_loop_still_playing(pst["channels"]):
                    dur = now - pst["play_start"]
                    was_exclusive = pst.get("is_exclusive", False)
                    breathing = _cue.markers.loop.get_delay(resolved.frequency)
                    pst["ready_at"] = now + breathing
                    pst["channels"] = []
                    pst["is_exclusive"] = False
                    if was_exclusive:
                        breathing_room = 0.05 + _random.uniform(0.0, 0.05)
                        ps["_exclusive_done_at"] = now + breathing_room
                    _cue_log("TICK#{} POOL-DONE  key={} pool={} dur={:.2f}s next_in={:.2f}s{}".format(
                        tick, loop_key, pi, dur, breathing,
                        " exclusive" if was_exclusive else ""))

                # Skip if not ready yet
                if pst["channels"]:
                    continue
                if now < pst["ready_at"]:
                    continue

                # Gate: no pool fires while dead-air SFX is playing
                if _cue_loop_still_playing(exclusive_channels):
                    pst["ready_at"] = now + 0.1
                    continue

                # Gate: no pool fires during post-dead-air breathing window
                if now < _exclusive_done_at:
                    pst["ready_at"] = _exclusive_done_at
                    continue

                # Dead-air-specific gate: skip if any loop channel is busy
                loop_channels = self.loop_current.get("channels", []) if self.loop_current else []
                any_busy = (
                    _cue_loop_still_playing(all_active)
                    or _cue_loop_still_playing(loop_channels)
                )
                if resolved.exclusive and any_busy:
                    pst["ready_at"] = now + 0.1
                    continue

                # Pick a file and play
                picked_file = _cue_pick_file(files)
                tries = 0
                while picked_file in picked and len(files) > 1 and tries < 3:
                    picked_file = _cue_pick_file(files)
                    tries += 1
                if picked_file in picked:
                    continue
                picked.append(picked_file)
                ch_used = _cue_play_pool(entry, loop_key, pool, pi, file=picked_file)
                if ch_used:
                    pst["channels"] = [ch_used]
                    pst["play_start"] = now
                    if resolved.exclusive:
                        pst["is_exclusive"] = True
                        exclusive_channels.append(ch_used)
                    all_active.append(ch_used)
                    self.loop_current = {
                        "key": loop_key,
                        "channels": python_list(all_active),
                    }
                    _cue_log("TICK#{} POOL-PLAY  key={} pool={} ch={} dur={:.2f}s next_in={:.2f}s".format(
                        tick, loop_key, pi, ch_used,
                        renpy.music.get_duration(channel=ch_used) or 0.0,
                        _cue.markers.loop.get_delay(resolved.frequency)))

        # ── video triggers (v: keys) ──

        def _tick_video(self, current_file, top_layer_type):
            """Video pool triggers for v: keys — fires SFX at marked times.

            Uses two complementary checks so markers aren't missed when playback
            position jumps more than marker_tolerance between ticks (common on
            short videos, high-speed playback, or coarse get_pos() steps):

              1. Forward window:  mt <= eff < mt + tolerance    (stationary / first tick)
              2. Cross check:     prev_eff < mt <= eff           (jumped past marker)
            """
            ch = _cue.vid_manager.channel
            if not ch or top_layer_type != 'movie':
                return

            elapsed = _cue.vid_manager.get_elapsed()
            marker_tolerance = 0.08

            # Autoscale: markers are stored at 1x reference time, so convert
            # variant elapsed to reference time when speed != 1.0.
            speed = _cue.speed_resolver.get_current_speed()
            effective_elapsed = elapsed * speed

            # Previous tick's effective position for cross-between-ticks detection.
            # Initialized to -1.0 so markers at time 0 trigger on the first tick
            # via:  prev_eff(-1) < mt(0) <= eff(0).
            prev_eff = self._prev_eff_elapsed

            # --- Helper: did we reach or cross this marker time? ---
            def _marker_reached(mt):
                """Return True if the marker at mt was reached or crossed since
                the last tick, either within the forward tolerance window or by
                jumping past it between ticks."""
                # Forward window: current position is within tolerance past the marker
                if mt <= effective_elapsed < mt + marker_tolerance:
                    return True
                # Cross check: we jumped past the marker since the last tick
                if prev_eff < mt <= effective_elapsed:
                    return True
                return False

            # Video markers
            if current_file:
                vid_key = create_vid_key(current_file)
                markers = _cue.markers.video.get_markers()
                vid_entry = _cue.markers.get(vid_key)

                # Tack preview markers onto the list — they're already pool dicts
                # shaped like real video markers (time/files/volume).
                _preview_count = 0
                if _cue.beat.dialog_visible and _cue.beat.preview_sfx_enabled:
                    preview_pools = _cue.beat.compute_preview_pools()
                    markers.extend(preview_pools)
                    _preview_count = len(preview_pools)

                if markers:
                    # Per-time counter so same-time markers get unique stable keys.
                    # Keyed by time instead of list index — adding/removing markers
                    # at other timestamps doesn't invalidate already-fired keys.
                    time_counts = {}
                    for idx, pool_entry in enumerate(markers):
                        is_preview = idx >= len(markers) - _preview_count
                        if is_preview:
                            entry = {"pools": [pool_entry]}
                            pool_index = 0
                        else:
                            entry = vid_entry
                            pool_index = idx

                        t = pool_entry["time"]
                        count = time_counts.setdefault(t, 0) + 1
                        time_counts[t] = count
                        ts_key = "{}@{:.3f}#{}".format(vid_key, t, count)

                        if ts_key in self.played_video_keys:
                            continue

                        if "time" not in pool_entry:
                            if not is_preview:
                                _cue_log("MISSING TIME " + vid_key + " " + str(vid_entry) + " " + str(pool_entry))
                            continue

                        if _marker_reached(pool_entry["time"]):
                            f = _cue_play_pool(entry, vid_key, pool_entry, pool_index, avoid_repeats=False)
                            if f:
                                self.played_video_keys.add(ts_key)

            # Detect video restart — two cases clear the dedup set:
            #   1) last_elapsed == 0: video manager was just reset (new channel
            #      or fresh playback, e.g. after editing the multi-speed queue).
            #   2) elapsed < last_elapsed: playback looped/restarted (Ren'Py
            #      can't seek backwards, so a large backward jump means restart).
            is_fresh_reset = _cue.vid_manager.last_elapsed == 0
            is_backward_jump = (
                _cue.vid_manager.last_elapsed > 0
                and elapsed < _cue.vid_manager.last_elapsed - 0.3
            )
            if is_fresh_reset or is_backward_jump:
                self.played_video_keys.clear()
                self._prev_eff_elapsed = -1.0

            _cue.vid_manager.last_elapsed = elapsed
            # Store for next tick's cross-between-ticks detection
            self._prev_eff_elapsed = effective_elapsed
