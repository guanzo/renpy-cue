# -*- coding: utf-8 -*-
# CueLoopTrigger -- the l_ key frequency-cycle state machine.  One domain of
# CueTriggerEngine; the engine drives per-tick cadence and passes the current
# video-level global volume scale in.

import random as _random
import renpy.audio.music as _music
import renpy.python as _renpy_python

from cue_lib.markers import CueExclusiveStart
from cue_lib.state import _cue
from cue_lib.trigger.exclusive import CUE_EXCL_KIND_LOOP
from cue_lib.trigger.helpers import _cue_effective_delay, _cue_loop_still_playing, _cue_pick_loop_deduped
from cue_lib.util import _cue_log, create_loop_key, create_vid_key

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional
    from cue_lib.trigger.engine import CueTriggerEngine  # pyright: ignore[reportUnusedImport]


class CueLoopTrigger(_renpy_python.NoRollback):
    """Loop state machine for l_ keys -- fires pooled SFX on a frequency cycle."""

    def __init__(self, engine):
        # type: (CueTriggerEngine) -> None
        self._engine = engine
        # Per-loop-key per-pool fire state (ready_at, channels, ...).
        self.loop_states = {}

    def reset(self):
        # type: () -> None
        """Drop loop trigger state on a file change."""
        self.loop_states = {}

    def _loop_delay(self, frequency, freq_mult):
        # type: (int, Optional[float]) -> float
        """Breathing delay for a loop pool, scaled by its intensity level.
        freq_mult is None for pools not hooked to a group -- plain delay."""
        delay = self._engine._markers_ctx().loop.get_delay(frequency)
        if freq_mult is not None:
            delay = _cue_effective_delay(delay, freq_mult)
        return delay

    def tick(self, now, tick, current_file, speed, variants, vid_scale=1.0):
        # type: (float, int, str, float, Optional[List[float]], float) -> None
        """Loop state machine for l_ keys -- fires pooled SFX on a frequency cycle.

        vid_scale is the video-level global volume for pools not hooked to an
        intensity group (computed by the engine from the per-tick resolution)."""
        loop_key = create_loop_key(current_file or "")

        entry = self._engine._store.get(loop_key)
        if entry is None:
            return
        pools = entry.get("pools", [])

        # Per-video toggles read from the current video's marker entry.
        flags = _cue.intensity.flags_from_entry(
            self._engine._store.get(create_vid_key(current_file)) if current_file else None
        )

        # Init per-pool states under the loop key
        if loop_key not in self.loop_states:
            self.loop_states[loop_key] = {}
        ps = self.loop_states[loop_key]

        # Files already picked this tick; dedup picks across pools.
        picked = []
        for pi, pool in enumerate(pools):
            # One resolve per pool: a hooked pool with nothing at its active
            # level (or a dead group) resolves to no files and is skipped below.
            resolved = self._engine._store.resolve_pool(pool, speed, variants, flags=flags, expand=True)
            if not resolved.files:
                continue
            vol_mult = resolved.volume_mult if resolved.level is not None else vid_scale

            pst = ps.get(pi)
            if pst is None:
                pst = self._new_pool_state(now, resolved)
                ps[pi] = pst

            if not self._pool_should_fire(pst, now, tick, loop_key, pi, resolved):
                continue

            picked_file = self._pool_fire(
                pst, now, tick, loop_key, pi, pool, entry, resolved, vol_mult, picked, current_file
            )
            if picked_file:
                picked.append(picked_file)

    def _new_pool_state(self, now, resolved):
        # type: (float, Any) -> Dict[str, Any]
        """Fresh fire state for one pool: armed with a random breathing delay."""
        init_delay = _random.uniform(0.0, self._loop_delay(resolved.frequency, resolved.freq_mult))
        return {
            "ready_at": now + init_delay,
            "channels": [],
            "play_start": 0.0,
            "blocked_logged": False,
            "ilevel": resolved.level,
            "recent": [],
        }

    def _pool_should_fire(self, pst, now, tick, loop_key, pi, resolved):
        # type: (Dict[str, Any], float, int, str, int, Any) -> bool
        """Advance one pool toward its next fire; True when it should fire now.

        Arms the next cycle when its channel finished, re-arms a pending fire
        on a level change, and defers through the hold/wait gates."""
        # Finished channels re-arm the timer for the next cycle.
        if pst["channels"] and not _cue_loop_still_playing(pst["channels"]):
            dur = now - pst["play_start"]
            breathing = self._loop_delay(resolved.frequency, resolved.freq_mult)
            pst["ready_at"] = now + breathing
            pst["channels"] = []
            _cue_log(
                "TICK#{} POOL-DONE  key={} pool={} dur={:.2f}s next_in={:.2f}s".format(
                    tick, loop_key, pi, dur, breathing
                )
            )

        # Level change: drop a pending/deferred fire and restart the timer
        # with the new level's delay.  A sound still playing is left to
        # finish -- POOL-DONE above re-arms with the new level.
        level = resolved.level
        if level is not None and pst.get("ilevel") != level:
            pst["ilevel"] = level
            if not pst["channels"]:
                pst["ready_at"] = now + self._loop_delay(resolved.frequency, resolved.freq_mult)

        # Skip if not ready yet
        if pst["channels"]:
            return False
        if now < pst["ready_at"]:
            return False

        excl = resolved.exclusive
        # Gate: a holding out-group SFX owns the air -- defer and retry.
        # Logged once per blocked episode (flag clears on play) so the
        # 0.1s retry cadence doesn't spam the log.
        if self._engine.excl.is_hold_blocked(CUE_EXCL_KIND_LOOP, None, None):
            if not pst.get("blocked_logged"):
                _cue_log("TICK#{} POOL-DEFER reason=hold key={} pool={}".format(tick, loop_key, pi))
                pst["blocked_logged"] = True
            pst["ready_at"] = now + 0.1
            return False

        # Gate: wait mode defers until no out-group loop SFX is playing.
        if excl.start == CueExclusiveStart.WAIT and self._engine.excl.is_outgroup_busy(CUE_EXCL_KIND_LOOP, None, None):
            if not pst.get("blocked_logged"):
                _cue_log("TICK#{} POOL-DEFER reason=wait key={} pool={}".format(tick, loop_key, pi))
                pst["blocked_logged"] = True
            pst["ready_at"] = now + 0.1
            return False

        return True

    def _pool_fire(self, pst, now, tick, loop_key, pi, pool, entry, resolved, vol_mult, picked, scene):
        # type: (Dict[str, Any], float, int, str, int, Any, Any, Any, float, List[str], Optional[str]) -> Optional[str]
        """Pick a deduped file and play it on the loop channel.

        Returns the picked file (None when deduped away); the caller records
        it in the running dedup list.  FADE mode sweeps other loop channels;
        any start mode fades loops still tailing from a previous scene."""
        # Per-pool no-repeat: avoid this pool's own recent picks (the global
        # last-2 is shared across pools, so one pool's activity launders
        # another's picks out of it).  window = len//2 guarantees enough fresh
        # files stay eligible -- a repeat beats a skipped fire.
        window = len(resolved.files) // 2
        recent = pst["recent"]
        picked_file = _cue_pick_loop_deduped(resolved.files, picked, recent)
        if picked_file is None:
            return None
        excl = resolved.exclusive

        # A loop from a previous scene may still be tailing out -- fade it so
        # this fire starts clean.  Same-scene loops are left to the exclusive
        # gates (hold/wait/fade), which is what "overlapping" means on purpose.
        stale = self._engine.excl.out_of_scene_channels(CUE_EXCL_KIND_LOOP, scene)
        if stale:
            faded = _cue.sfx.fade_out(only_channels=stale)
            _cue_log("TICK#{} POOL-STALE key={} pool={} faded={}".format(tick, loop_key, pi, faded))

        if excl.start == CueExclusiveStart.FADE:
            # Cut-in: fade out other loops (never image/dialogue SFX).
            faded = _cue.sfx.fade_out(
                exclude_channels=self._engine.excl.group_channels(CUE_EXCL_KIND_LOOP, None, None),
                only_channels=self._engine.excl.kind_channels(CUE_EXCL_KIND_LOOP),
            )
            _cue_log("TICK#{} POOL-SWEEP key={} pool={} faded={}".format(tick, loop_key, pi, faded))

        ch_used = _cue.sfx.play_pool(entry, loop_key, pool, pi, file=picked_file, volume_mult=vol_mult)
        if ch_used:
            pst["channels"] = [ch_used]
            pst["play_start"] = now
            pst["blocked_logged"] = False

            recent.append(picked_file)
            if window > 0 and len(recent) > window:
                del recent[: len(recent) - window]
            self._engine.excl.track_channel(ch_used, CUE_EXCL_KIND_LOOP, scene, None, excl.hold)

            _cue_log(
                "TICK#{} POOL-PLAY  key={} pool={} ch={} dur={:.2f}s next_in={:.2f}s".format(
                    tick,
                    loop_key,
                    pi,
                    ch_used,
                    _music.get_duration(channel=ch_used) or 0.0,
                    self._loop_delay(resolved.frequency, resolved.freq_mult),
                )
            )
        return picked_file
