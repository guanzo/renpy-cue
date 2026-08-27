# -*- coding: utf-8 -*-
# Pure helpers shared by the trigger domains: marker-fire math, loop delay
# scaling, dedupe picking, and the per-video intensity resolution.  Leaf
# module -- engine.py and context.py both import from here, so nothing in the
# trigger package may import this one.

import renpy.audio.music as _music

from cue_lib.constants import CUE_INTENSITY_DELAY_MAX, CUE_INTENSITY_DELAY_MIN
from cue_lib.state import _cue
from cue_lib.util import _cue_pick_file, create_vid_key

MYPY = False
if MYPY:
    from typing import List, Optional
    from cue_lib.intensity import CueIntensityResolution  # pyright: ignore[reportUnusedImport]
    from cue_lib.marker_store import CueMarkerStore  # pyright: ignore[reportUnusedImport]

# Lead (seconds, REFERENCE time) to fire a video marker before its time.  Two
# contributions:
#   * Half the expected per-tick position advance (wall-clock tick interval *
#     speed) centers deltas around 0 instead of always firing a tick late.
#   * CUE_SFX_AUDIBLE_LEAD compensates the wall-clock delay between a marker's
#     play call and its audible onset (output buffer / channel start).  Without
#     it every SFX is HEARD lead-time late, which reads worse as speed rises
#     because the marker spacing shrinks while the latency stays fixed.
# The cap is high enough for the audible lead at max speed (~0.18 ref at 2x)
# while still bounding how far a marker can fire after a dropped frame or
# focus-loss gap.
CUE_MARKER_LEAD_MAX = 0.2
# Real-seconds audible-path latency to counter (tune by ear: play call -> heard).
CUE_SFX_AUDIBLE_LEAD = 0.09


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


def _cue_marker_lead(tick_interval, speed):
    # type: (float, float) -> float
    """Seconds (REFERENCE time) to fire a video marker early.

    Half the expected per-tick position advance (wall-clock tick interval *
    speed) centers deltas on 0, plus CUE_SFX_AUDIBLE_LEAD * speed compensates
    the fixed play-call-to-audible latency so each SFX is HEARD on its marker
    instead of behind it.  Clamped to CUE_MARKER_LEAD_MAX; zero when the
    cadence is unknown (first tick).  Sized from the real frame cadence -- not
    the previous tick's position jump -- so it stays stable through get_pos()
    chunking and speed-variant changes, which a position-derived lead misreads."""
    if tick_interval <= 0.0:
        return 0.0
    lead = (0.5 * tick_interval + CUE_SFX_AUDIBLE_LEAD) * speed
    if lead > CUE_MARKER_LEAD_MAX:
        return CUE_MARKER_LEAD_MAX
    return min(lead, CUE_MARKER_LEAD_MAX)


def _cue_marker_reached(mt, effective_elapsed, prev_eff, marker_tolerance, lead=0.0):
    # type: (float, float, float, float, float) -> bool
    """True if a marker at time mt was reached or crossed since the last tick.

    Two complementary checks so markers aren't missed when playback position
    jumps more than marker_tolerance between ticks (common on short videos,
    high-speed playback, or coarse get_pos() steps):

      1. Forward window:  mt <= eff < mt + tolerance    (stationary / first tick)
      2. Cross check:     prev_eff < mt <= eff           (jumped past marker)

    lead > 0 targets mt - lead instead of mt, firing the marker up to `lead`
    seconds EARLY to compensate the frame-bound tick cadence (deltas center on
    0 instead of always landing late).  lead=0 reproduces the late-fire
    behavior.
    """
    target = mt - lead
    # Forward window: current position is within tolerance of the target
    if target <= effective_elapsed < mt + marker_tolerance:
        return True
    # Cross check: we jumped past the target since the last tick
    if prev_eff < target <= effective_elapsed:
        return True
    return False


def _cue_effective_delay(base_delay, level_mult):
    # type: (float, float) -> float
    """Next loop delay for a level: base_delay / multiplier, clamped to
    [CUE_INTENSITY_DELAY_MIN, CUE_INTENSITY_DELAY_MAX].  A malformed
    (<= 0) multiplier would divide by zero -- treat it as identity."""
    if level_mult <= 0.0:
        level_mult = 1.0
    return min(CUE_INTENSITY_DELAY_MAX, max(CUE_INTENSITY_DELAY_MIN, base_delay / level_mult))


def _cue_vid_intensity_resolution(store, current_file, speed, variants):
    # type: (CueMarkerStore, str, float, Optional[List[float]]) -> Optional[CueIntensityResolution]
    """The current video's active intensity (its first hooked pool).

    The result's volume_mult is the global scale for non-hooked fires
    during the video.  None when the file has no video markers, no pool
    is hooked, or intensity is toggled off for the video -- i.e. no
    intensity mode, so fires play unscaled."""
    if not current_file or not variants:
        return None
    entry = store.get(create_vid_key(current_file))
    if entry is None:
        return None
    flags = _cue.intensity.flags_from_entry(entry)
    if not flags.enabled:
        return None
    pool_hooks = []
    for p in entry.get("pools", []):
        rp = store.resolve_pool(p)
        pool_hooks.append((rp.igroup, rp.ilevel_id))
    if not pool_hooks:
        return None
    return _cue.intensity.resolve_video_intensity(pool_hooks, speed, variants, flags=flags)
