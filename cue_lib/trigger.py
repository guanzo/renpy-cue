# -*- coding: utf-8 -*-
# CueTriggerEngine -- trigger dispatch for i:, d:, l:, v: keys and shake.
# Instantiated once at _cue.trigger, lives on the NoRollback _cue object.

import time as _time
import random as _random
import renpy.audio.music as _music

from cue_lib.markers import CueExclusiveStart
from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, _cue_resolve_files, _cue_pick_file, _cue_loop_still_playing,
    create_loop_key, create_vid_key,
)

MYPY = False
if MYPY:
    from typing import Any, List, Optional


# Exclusive domains: loops and one-shots never interact. An exclusive SFX
# only waits for / fades / blocks other SFX in its own domain, so an
# exclusive loop leaves image/dialogue SFX untouched and vice versa.
CUE_EXCL_KIND_LOOP = "loop"
CUE_EXCL_KIND_ONESHOT = "oneshot"


class CueTriggerEngine(object):
    """Owns trigger dispatch state and logic.

    Called by:
    - _cue_tick_trigger() every frame for time-based triggers (loop + video)
    - _cue_refresh_context() when scene/dialogue/shake context changes
    """

    def __init__(self):
        self.active = True
        self.loop_states = {}
        self.excl_channels = {}
        self.last_played = []
        self.played_video_keys = set()
        self._prev_eff_elapsed = -1.0
        self._tick_count = 0

    # -- exclusive tracking (channel -> {"scope": scope, "kind": kind, "hold": bool}) --
    # "scope" is a friendship identity: SFX sharing a scope are friends and
    # won't fade/block each other. One-shots use the trigger key (all pools
    # of a trigger fire as one unit); loops use a per-pool scope so each loop
    # competes with its siblings to "sneak in" solo.
    #
    # "kind" is the domain (loop vs one-shot). Domains never interact, so an
    # exclusive loop only waits for / fades / blocks other loops.

    def _prune_excl(self):
        # type: () -> None
        """Drop tracked channels that have finished playing."""
        for ch in list(self.excl_channels.keys()):
            if not _music.is_playing(channel=ch):
                del self.excl_channels[ch]

    def _excl_friends(self, scope, kind):
        # type: (str, str) -> List[str]
        """Channels playing a same-scope, same-kind SFX (friends)."""
        if not scope:
            return []
        return [ch for ch, info in self.excl_channels.items()
                if info.get("scope") == scope and info.get("kind") == kind]

    def _excl_kind_channels(self, kind):
        # type: (str) -> List[str]
        """Channels currently playing in the given domain (kind)."""
        return [ch for ch, info in self.excl_channels.items() if info.get("kind") == kind]

    def _excl_hold_blocked(self, scope, kind):
        # type: (str, str) -> bool
        """True if a holding SFX in the same domain but a different scope is
        playing -- a non-friend owns the air, so this SFX may not start.

        Only fire_context and _tick_loop consult this gate; SFX played
        elsewhere (video markers, preview) are hold-immune by construction.
        The cut-in sweep, by contrast, is channel-based and hits everything
        in the same domain that isn't a scope friend."""
        self._prune_excl()
        for info in self.excl_channels.values():
            if (info["hold"] and info.get("kind") == kind
                    and info.get("scope") != scope):
                return True
        return False

    def _excl_nonfriend_busy(self, scope, kind):
        # type: (str, str) -> bool
        """True if any same-domain channel that isn't a scope friend is
        playing -- polite holders wait for this to clear."""
        self._prune_excl()
        for info in self.excl_channels.values():
            if info.get("kind") != kind:
                continue
            if info.get("scope") != scope:
                return True
        return False

    def _excl_track(self, channel, scope, kind, hold):
        # type: (Optional[str], str, str, bool) -> None
        """Record a playing SFX's friendship scope, domain, and hold state."""
        if channel and scope is not None:
            self.excl_channels[channel] = {"scope": scope, "kind": kind, "hold": hold}

    # -- tick entry point --

    def tick(self, current_file, top_layer_type):
        # type: (str, str) -> None
        """Called every frame. Handles loop (l:) and video (v:) triggers."""
        if not self.active:
            return

        self._tick_count += 1
        tick = self._tick_count
        now = _time.time()

        self._tick_loop(now, tick, current_file)
        self._tick_video(current_file, top_layer_type)

    # -- context triggers (i:, d:, shake) --

    def fire_context(self, *keys, **kwargs):
        # type: (*Optional[str], **Any) -> None
        """Fire i:, d:, or shake triggers for the given keys.

        Multi-pool entries play one random file from EACH pool concurrently.
        Dedupe guard: same file in two pools of the same trigger is re-picked
        up to 3 times, then skipped to avoid echo artifacts.

        When only_shake_pools is True, pools without the trigger_on_shake flag
        are skipped -- used by screenshake triggers so each pool independently
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
            vol = entry.get("volume", _cue.volume.VOL_DEFAULT)
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
                excl = resolved.exclusive
                # Hold gate: a holding non-friend owns the air -- drop this pool.
                if self._excl_hold_blocked(key, CUE_EXCL_KIND_ONESHOT):
                    _cue_log("CTX-DROPPED key={} pool={} (held)".format(key, pi))
                    continue
                # One-shot pools can't defer: "wait" only plays into open air.
                if excl.start == CueExclusiveStart.WAIT and self._excl_nonfriend_busy(key, CUE_EXCL_KIND_ONESHOT):
                    _cue_log("CTX-DROPPED key={} pool={} (air busy)".format(key, pi))
                    continue
                file = _cue_pick_file(files)
                tries = 0
                while file in picked and len(files) > 1 and tries < 3:
                    file = _cue_pick_file(files)
                    tries += 1
                if file in picked:
                    continue
                picked.append(file)

                # _cue_play_pool is in runtime.py; import lazily to avoid cycle
                from cue_lib.runtime import _cue_play_pool, _cue_fade_out_sfx
                if excl.start == CueExclusiveStart.FADE:
                    # Cut-in: fade out one-shots from other keys, plus any
                    # playing loops and video SFX (one-shots cut loops).
                    faded = _cue_fade_out_sfx(
                        exclude_channels=self._excl_friends(key, CUE_EXCL_KIND_ONESHOT))
                    _cue_log("CTX-FADE key={} pool={} faded={}".format(
                        key, pi, faded))
                ch_used = _cue_play_pool(entry, key, pool, pi, file=file)
                self._excl_track(ch_used, key, CUE_EXCL_KIND_ONESHOT, excl.hold)

    # -- loop triggers (l: keys) --

    def _tick_loop(self, now, tick, current_file):
        # type: (float, int, str) -> None
        """Loop state machine for l: keys -- fires pooled SFX on a frequency cycle."""
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

        picked = []
        for pi, pool in enumerate(pools):
            resolved = _cue.markers.resolve_pool(pool)
            files = _cue_resolve_files(resolved.files)
            if not files:
                continue

            pst = ps.get(pi)
            if pst is None:
                init_delay = _random.uniform(0.0, _cue.markers.loop.get_delay(resolved.frequency))
                ps[pi] = {"ready_at": now + init_delay, "channels": [], "play_start": 0.0, "blocked_logged": False}
                pst = ps[pi]

            # If this pool's channels are done playing, reset for next cycle
            if pst["channels"] and not _cue_loop_still_playing(pst["channels"]):
                dur = now - pst["play_start"]
                breathing = _cue.markers.loop.get_delay(resolved.frequency)
                pst["ready_at"] = now + breathing
                pst["channels"] = []
                _cue_log("TICK#{} POOL-DONE  key={} pool={} dur={:.2f}s next_in={:.2f}s".format(
                    tick, loop_key, pi, dur, breathing))

            # Skip if not ready yet
            if pst["channels"]:
                continue
            if now < pst["ready_at"]:
                continue

            excl = resolved.exclusive
            scope = "{}#{}".format(loop_key, pi)
            # Gate: a holding non-friend owns the air -- defer and retry.
            # Logged once per blocked episode (flag clears on play) so the
            # 0.1s retry cadence doesn't spam the log.
            if self._excl_hold_blocked(scope, CUE_EXCL_KIND_LOOP):
                if not pst.get("blocked_logged"):
                    _cue_log("TICK#{} POOL-DEFER reason=hold key={} pool={}".format(tick, loop_key, pi))
                    pst["blocked_logged"] = True
                pst["ready_at"] = now + 0.1
                continue

            # Gate: wait mode defers until no non-friend loop SFX is playing.
            if excl.start == CueExclusiveStart.WAIT and self._excl_nonfriend_busy(scope, CUE_EXCL_KIND_LOOP):
                if not pst.get("blocked_logged"):
                    _cue_log("TICK#{} POOL-DEFER reason=wait key={} pool={}".format(tick, loop_key, pi))
                    pst["blocked_logged"] = True
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
            from cue_lib.runtime import _cue_play_pool, _cue_fade_out_sfx
            if excl.start == CueExclusiveStart.FADE:
                # Cut-in: fade out other loops (never image/dialogue SFX).
                faded = _cue_fade_out_sfx(
                    exclude_channels=self._excl_friends(scope, CUE_EXCL_KIND_LOOP),
                    only_channels=self._excl_kind_channels(CUE_EXCL_KIND_LOOP))
                _cue_log("TICK#{} POOL-SWEEP key={} pool={} faded={}".format(
                    tick, loop_key, pi, faded))
            ch_used = _cue_play_pool(entry, loop_key, pool, pi, file=picked_file)
            if ch_used:
                pst["channels"] = [ch_used]
                pst["play_start"] = now
                pst["blocked_logged"] = False
                self._excl_track(ch_used, scope, CUE_EXCL_KIND_LOOP, excl.hold)
                _cue_log("TICK#{} POOL-PLAY  key={} pool={} ch={} dur={:.2f}s next_in={:.2f}s".format(
                    tick, loop_key, pi, ch_used,
                    _music.get_duration(channel=ch_used) or 0.0,
                    _cue.markers.loop.get_delay(resolved.frequency)))

    # -- video triggers (v: keys) --

    def _tick_video(self, current_file, top_layer_type):
        # type: (str, str) -> None
        """Video pool triggers for v: keys -- fires SFX at marked times.

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
            # type: (float) -> bool
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

            # Tack preview markers onto the list -- they're already pool dicts
            # shaped like real video markers (time/files/volume).
            _preview_count = 0
            if _cue.repeater.dialog_visible and _cue.repeater.preview_sfx_enabled:
                preview_pools = _cue.repeater.compute_preview_pools()
                markers.extend(preview_pools)
                _preview_count = len(preview_pools)

            if markers:
                # Per-time counter so same-time markers get unique stable keys.
                # Keyed by time instead of list index -- adding/removing markers
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
                        from cue_lib.runtime import _cue_play_pool
                        f = _cue_play_pool(entry, vid_key, pool_entry, pool_index, avoid_repeats=False)  # pyright: ignore[reportArgumentType]
                        if f:
                            self.played_video_keys.add(ts_key)

        # Detect video restart -- two cases clear the dedup set:
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
