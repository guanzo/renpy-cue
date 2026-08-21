# -*- coding: utf-8 -*-
# CueTriggerEngine -- trigger dispatch for i:, d:, l:, v: keys and shake.
# Instantiated once at _cue.trigger, lives on the NoRollback _cue object.

import time as _time
import random as _random
import renpy.audio.music as _music

from renpy.store import persistent

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.markers import CueExclusiveStart
from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, _cue_resolve_files, _cue_pick_file,
    create_loop_key, create_vid_key, get_key_file, is_dlg_key,
)

MYPY = False
if MYPY:
    from typing import Any, List, Optional
    from cue_lib.marker_store import CueMarkerStore  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.repeater import CueMarkerRepeater  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.speed import CueVidSpeedResolver  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video import CueVideoManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.markers import CueMarkerManager  # pyright: ignore[reportUnusedImport]


# Exclusive domains: loops and one-shots never interact. An exclusive SFX
# only waits for / fades / blocks other SFX in its own domain, so an
# exclusive loop leaves image/dialogue SFX untouched and vice versa.
CUE_EXCL_KIND_LOOP = "loop"
CUE_EXCL_KIND_ONESHOT = "oneshot"


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


def _cue_pick_deduped(files, picked, max_tries=3):
    # type: (List[str], List[str], int) -> Optional[str]
    """Pick a file from `files` not already in `picked` (dedupe rule).

    Re-picks up to max_tries when a draw collides with an already-picked file,
    so multi-pool triggers don't play the same file twice (echo artifacts).
    Returns None when the dedupe can't be satisfied -- the caller should skip
    that pool (a single-file pool repeating legitimately falls through here)."""
    picked_set = set(picked)
    tries = 0
    while True:
        file = _cue_pick_file(files)
        if file not in picked_set or len(files) <= 1 or tries >= max_tries:
            return None if file in picked_set else file
        tries += 1


def _cue_marker_reached(mt, effective_elapsed, prev_eff, marker_tolerance):
    # type: (float, float, float, float) -> bool
    """True if a marker at time mt was reached or crossed since the last tick.

    Two complementary checks so markers aren't missed when playback position
    jumps more than marker_tolerance between ticks (common on short videos,
    high-speed playback, or coarse get_pos() steps):

      1. Forward window:  mt <= eff < mt + tolerance    (stationary / first tick)
      2. Cross check:     prev_eff < mt <= eff           (jumped past marker)
    """
    # Forward window: current position is within tolerance past the marker
    if mt <= effective_elapsed < mt + marker_tolerance:
        return True
    # Cross check: we jumped past the marker since the last tick
    if prev_eff < mt <= effective_elapsed:
        return True
    return False


class CueTriggerEngine(object):
    """Owns trigger dispatch state and logic.

    Called by:
    - _cue_tick_trigger() every frame for time-based triggers (loop + video)
    - _cue_refresh_context() when scene/dialogue/shake context changes
    """

    def __init__(self, store, repeater, speed_resolver, vid_manager, markers=None):
        # type: (CueMarkerStore, CueMarkerRepeater, CueVidSpeedResolver, CueVideoManager, Optional[CueMarkerManager]) -> None
        self._store = store
        self._repeater = repeater
        self._speed_resolver = speed_resolver
        self._vid_manager = vid_manager
        # Context sub-objects (loop.get_delay, video.get_markers) live on the
        # markers manager, wired after trigger.  Injected in tests; in the
        # game it resolves to the singleton at call time.
        self._markers = markers
        self.active = True
        self.loop_states = {}
        self.excl_channels = {}
        self.last_played = []
        self.played_video_keys = set()
        self._prev_eff_elapsed = -1.0
        self._tick_count = 0

    def _markers_ctx(self):
        # type: () -> Any
        """Markers manager -- wired after trigger, so fall back to the
        singleton at call time unless a fake was injected."""
        return self._markers if self._markers is not None else _cue.markers

    def toggle_active(self):
        # type: () -> None
        """Flip the SFX trigger engine on/off and persist the choice."""
        self.active = not self.active
        persistent._cue["triggers_active"] = self.active

    # -- exclusive tracking (channel -> {"kind", "scene", "line", "hold"}) --
    # Grouping for one-shots is two-dimensional: the "scene" (file) plus a
    # "line" (dialogue key, None for image/shake). Two one-shots share a group
    # when they share a scene AND (either side is non-dialogue OR they share a
    # line) -- so image and dialogue coexist, but a new dialogue line cuts the
    # previous one. Loops never share a group; each loop competes with the rest.
    #
    # "kind" is the domain (loop vs one-shot). Domains never interact, so an
    # exclusive loop only waits for / fades / blocks other loops.

    def _prune_excl(self):
        # type: () -> None
        """Drop tracked channels that have finished playing."""
        for ch in list(self.excl_channels.keys()):
            if not _music.is_playing(channel=ch):
                del self.excl_channels[ch]

    def _excl_same_group(self, info, kind, scene, line):
        # type: (Any, str, Optional[str], Optional[str]) -> bool
        """True if a same-domain tracked channel shares self's group.

        Loops never share a group. One-shots share a group when they share a
        scene AND (either side is non-dialogue OR they share a line)."""
        if kind == CUE_EXCL_KIND_LOOP:
            return False
        if info.get("scene") != scene:
            return False
        if line is None or info.get("line") is None:
            return True
        return info.get("line") == line

    def _excl_group_channels(self, kind, scene, line):
        # type: (str, Optional[str], Optional[str]) -> List[str]
        """Channels in this domain that share self's group."""
        return [ch for ch, info in self.excl_channels.items()
                if info.get("kind") == kind and self._excl_same_group(info, kind, scene, line)]

    def _excl_kind_channels(self, kind):
        # type: (str) -> List[str]
        """Channels currently playing in the given domain (kind)."""
        return [ch for ch, info in self.excl_channels.items() if info.get("kind") == kind]

    def _excl_hold_blocked(self, kind, scene, line):
        # type: (str, Optional[str], Optional[str]) -> bool
        """True if a holding SFX in the same domain but not self's group is
        playing -- an out-group SFX owns the air, so this SFX may not start.

        Only fire_context and _tick_loop consult this gate; SFX played
        elsewhere (video markers, preview) are hold-immune by construction.
        The cut-in sweep, by contrast, is channel-based and hits everything
        in the same domain outside self's group."""
        self._prune_excl()
        for info in self.excl_channels.values():
            if info.get("kind") != kind:
                continue
            if info["hold"] and not self._excl_same_group(info, kind, scene, line):
                return True
        return False

    def _excl_outgroup_busy(self, kind, scene, line):
        # type: (str, Optional[str], Optional[str]) -> bool
        """True if any same-domain channel outside self's group is playing --
        polite holders wait for this to clear."""
        self._prune_excl()
        for info in self.excl_channels.values():
            if info.get("kind") != kind:
                continue
            if not self._excl_same_group(info, kind, scene, line):
                return True
        return False

    def _excl_track(self, channel, kind, scene, line, hold):
        # type: (Optional[str], str, Optional[str], Optional[str], bool) -> None
        """Record a playing SFX's domain, group identity, and hold state."""
        if channel:
            self.excl_channels[channel] = {
                "kind": kind, "scene": scene, "line": line, "hold": hold}

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
            entry = self._store.get(key)
            if not entry:
                continue
            pools = entry.get("pools", [])
            if not pools:
                continue
            vol = entry.get("volume", CUE_VOLUME_DEFAULT)
            total = sum(len(self._store.resolve_pool(p).files) for p in pools)

            _cue_log("CTX-TRIGGER key={} pools={} files={} vol={:.2f}".format(
                key, len(pools), total, vol))

            # Group identity: scene (file) + line (dialogue key, or None for
            # image/shake). Same scene AND (either is non-dialogue OR same
            # line) share a group -- image/dialogue coexist, a new line cuts
            # the previous one.
            scene = get_key_file(key)
            line = key if is_dlg_key(key) else None

            picked = []
            for pi, pool in enumerate(pools):
                resolved = self._store.resolve_pool(pool)
                if only_shake_pools and not resolved.trigger_on_shake:
                    continue
                files = _cue_resolve_files(resolved.files)
                if not files:
                    continue
                excl = resolved.exclusive
                # Hold gate: a holding out-group SFX owns the air -- drop this pool.
                if self._excl_hold_blocked(CUE_EXCL_KIND_ONESHOT, scene, line):
                    _cue_log("CTX-DROPPED key={} pool={} (held)".format(key, pi))
                    continue
                # One-shot pools can't defer: "wait" only plays into open air.
                if (excl.start == CueExclusiveStart.WAIT
                        and self._excl_outgroup_busy(CUE_EXCL_KIND_ONESHOT, scene, line)):
                    _cue_log("CTX-DROPPED key={} pool={} (air busy)".format(key, pi))
                    continue
                file = _cue_pick_deduped(files, picked)
                if file is None:
                    continue
                picked.append(file)

                if excl.start == CueExclusiveStart.FADE:
                    # Cut-in: fade out one-shots outside this group, plus any
                    # playing loops and video SFX (one-shots cut loops).
                    faded = _cue.sfx.fade_out(
                        exclude_channels=self._excl_group_channels(CUE_EXCL_KIND_ONESHOT, scene, line))
                    _cue_log("CTX-FADE key={} pool={} faded={}".format(
                        key, pi, faded))
                ch_used = _cue.sfx.play_pool(entry, key, pool, pi, file=file)
                self._excl_track(ch_used, CUE_EXCL_KIND_ONESHOT, scene, line, excl.hold)

    # -- loop triggers (l: keys) --

    def _tick_loop(self, now, tick, current_file):
        # type: (float, int, str) -> None
        """Loop state machine for l: keys -- fires pooled SFX on a frequency cycle."""
        loop_key = create_loop_key(current_file or "")

        entry = self._store.get(loop_key)
        if entry is None:
            return
        pools = entry.get("pools", [])
        # Collect frequencies from resolved pools with files, default 1
        freqs = []
        for p in pools:
            resolved = self._store.resolve_pool(p)
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
            resolved = self._store.resolve_pool(pool)
            files = _cue_resolve_files(resolved.files)
            if not files:
                continue

            pst = ps.get(pi)
            if pst is None:
                init_delay = _random.uniform(0.0, self._markers_ctx().loop.get_delay(resolved.frequency))
                ps[pi] = {"ready_at": now + init_delay, "channels": [], "play_start": 0.0, "blocked_logged": False}
                pst = ps[pi]

            # If this pool's channels are done playing, reset for next cycle
            if pst["channels"] and not _cue_loop_still_playing(pst["channels"]):
                dur = now - pst["play_start"]
                breathing = self._markers_ctx().loop.get_delay(resolved.frequency)
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
            # Gate: a holding out-group SFX owns the air -- defer and retry.
            # Logged once per blocked episode (flag clears on play) so the
            # 0.1s retry cadence doesn't spam the log.
            if self._excl_hold_blocked(CUE_EXCL_KIND_LOOP, None, None):
                if not pst.get("blocked_logged"):
                    _cue_log("TICK#{} POOL-DEFER reason=hold key={} pool={}".format(tick, loop_key, pi))
                    pst["blocked_logged"] = True
                pst["ready_at"] = now + 0.1
                continue

            # Gate: wait mode defers until no out-group loop SFX is playing.
            if excl.start == CueExclusiveStart.WAIT and self._excl_outgroup_busy(CUE_EXCL_KIND_LOOP, None, None):
                if not pst.get("blocked_logged"):
                    _cue_log("TICK#{} POOL-DEFER reason=wait key={} pool={}".format(tick, loop_key, pi))
                    pst["blocked_logged"] = True
                pst["ready_at"] = now + 0.1
                continue

            # Pick a file and play
            picked_file = _cue_pick_deduped(files, picked)
            if picked_file is None:
                continue
            picked.append(picked_file)
            if excl.start == CueExclusiveStart.FADE:
                # Cut-in: fade out other loops (never image/dialogue SFX).
                faded = _cue.sfx.fade_out(
                    exclude_channels=self._excl_group_channels(CUE_EXCL_KIND_LOOP, None, None),
                    only_channels=self._excl_kind_channels(CUE_EXCL_KIND_LOOP))
                _cue_log("TICK#{} POOL-SWEEP key={} pool={} faded={}".format(
                    tick, loop_key, pi, faded))
            ch_used = _cue.sfx.play_pool(entry, loop_key, pool, pi, file=picked_file)
            if ch_used:
                pst["channels"] = [ch_used]
                pst["play_start"] = now
                pst["blocked_logged"] = False
                self._excl_track(ch_used, CUE_EXCL_KIND_LOOP, None, None, excl.hold)
                _cue_log("TICK#{} POOL-PLAY  key={} pool={} ch={} dur={:.2f}s next_in={:.2f}s".format(
                    tick, loop_key, pi, ch_used,
                    _music.get_duration(channel=ch_used) or 0.0,
                    self._markers_ctx().loop.get_delay(resolved.frequency)))

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
        ch = self._vid_manager.channel
        if not ch or top_layer_type != 'movie':
            return

        elapsed = self._vid_manager.get_elapsed()
        marker_tolerance = 0.08

        # Autoscale: markers are stored at 1x reference time, so convert
        # variant elapsed to reference time when speed != 1.0.
        speed = self._speed_resolver.get_current_speed()
        effective_elapsed = elapsed * speed

        # Previous tick's effective position for cross-between-ticks detection.
        # Initialized to -1.0 so markers at time 0 trigger on the first tick
        # via:  prev_eff(-1) < mt(0) <= eff(0).
        prev_eff = self._prev_eff_elapsed

        # Video markers
        if current_file:
            vid_key = create_vid_key(current_file)
            markers = self._markers_ctx().video.get_markers()
            vid_entry = self._store.get(vid_key)

            # Tack preview markers onto the list -- they're already pool dicts
            # shaped like real video markers (time/files/volume).
            _preview_count = 0
            if self._repeater.dialog_visible and self._repeater.preview_sfx_enabled:
                preview_pools = self._repeater.compute_preview_pools()
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

                    if _cue_marker_reached(pool_entry["time"], effective_elapsed, prev_eff, marker_tolerance):
                        f = _cue.sfx.play_pool(entry, vid_key, pool_entry, pool_index, avoid_repeats=False)  # pyright: ignore[reportArgumentType]
                        if f:
                            self.played_video_keys.add(ts_key)

        # Detect video restart -- two cases clear the dedup set:
        #   1) last_elapsed == 0: video manager was just reset (new channel
        #      or fresh playback, e.g. after editing the multi-speed queue).
        #   2) elapsed < last_elapsed: playback looped/restarted (Ren'Py
        #      can't seek backwards, so a large backward jump means restart).
        is_fresh_reset = self._vid_manager.last_elapsed == 0
        is_backward_jump = (
            self._vid_manager.last_elapsed > 0
            and elapsed < self._vid_manager.last_elapsed - 0.3
        )
        if is_fresh_reset or is_backward_jump:
            self.played_video_keys.clear()
            self._prev_eff_elapsed = -1.0

        self._vid_manager.last_elapsed = elapsed
        # Store for next tick's cross-between-ticks detection
        self._prev_eff_elapsed = effective_elapsed
