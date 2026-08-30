# -*- coding: utf-8 -*-
# CueTriggerEngine -- trigger dispatch for i_, d_, l_, v_ keys and shake.
# Instantiated once at _cue.trigger, lives on the NoRollback _cue object.
# Owns tick cadence and shared context; per-domain logic lives in the
# CueContextTrigger / CueLoopTrigger / CueVideoTrigger sub-objects.

import time as _time

from renpy.store import persistent

from cue_lib.state import _cue
from cue_lib.trigger.context import CueContextTrigger
from cue_lib.trigger.exclusive import CueExclusiveRegistry
from cue_lib.trigger.helpers import _cue_vid_intensity_resolution
from cue_lib.trigger.loop import CueLoopTrigger
from cue_lib.trigger.trigger_debug import CueTriggerDebug
from cue_lib.trigger.video import CueVideoTrigger

MYPY = False
if MYPY:
    from typing import Any, Optional
    from cue_lib.marker_store import CueMarkerStore  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.repeater import CueMarkerRepeater  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.speed import CueVidSpeedResolver  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video import CueVideoManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.markers import CueMarkerManager  # pyright: ignore[reportUnusedImport]


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
        self.last_played = []
        self._tick_count = 0
        # Last tick's video-level intensity resolution.  Observational only:
        # the domains take vid_scale as an argument and fire_context recomputes
        # on demand (it runs before tick, so a per-tick value would be stale).
        self._vid_intensity = None  # type: Optional[Any]
        # Wall-clock time of the last active tick; measures the frame cadence
        # the marker lead is sized from.  0 = no baseline yet (first tick).
        self._last_tick_wall = 0.0
        # Shared exclusive-tracking backbone (channel -> {"kind", "scene",
        # "line", "hold"}) consulted by all three domains.
        self.excl = CueExclusiveRegistry()
        # Anomaly detection (stall / stuck-gate / late-fire / missed markers).
        self._debug = CueTriggerDebug()
        # Per-domain trigger logic.  Context one-shots fire on context change;
        # loop + video run per-tick off the engine's cadence.  The domain
        # constructors are typed against the engine stub, which pyright won't
        # unify with the live class during its own analysis.
        self.context = CueContextTrigger(self)  # pyright: ignore[reportArgumentType]
        self.loop = CueLoopTrigger(self)  # pyright: ignore[reportArgumentType]
        self.video = CueVideoTrigger(self)  # pyright: ignore[reportArgumentType]

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

    def reset(self):
        # type: () -> None
        """Drop per-file trigger state (loop + video) on a file change."""
        self.loop.reset()
        self.video.reset()

    # -- tick entry point --

    def tick(self, current_file, top_layer_type):
        # type: (str, str) -> None
        """Called every frame. Handles loop (l_) and video (v_) triggers."""
        self._tick_count += 1
        tick = self._tick_count
        now = _time.time()
        # Frame cadence for the marker lead: the real wall-clock interval since
        # the last tick.  Zero on the first tick (no baseline yet).
        interval = now - self._last_tick_wall if self._last_tick_wall else 0.0
        self._last_tick_wall = now

        if self.active:
            self._debug.tick(now, current_file, top_layer_type, self._vid_manager.channel)

        # Speed + variant set, computed once per tick for intensity banding.
        # variants is None for videos with fewer than 2 speed variants (no
        # intensity).  The video level resolution doubles as the global
        # volume scale applied to SFX that fire during the video but aren't
        # themselves hooked to a group.
        speed = self._speed_resolver.get_current_speed()
        variants = self._speed_resolver.banding_speeds(current_file)
        vres = _cue_vid_intensity_resolution(self._store, current_file, speed, variants)
        self._vid_intensity = vres
        vid_scale = vres.volume_mult if vres is not None else 1.0

        self.loop.tick(now, tick, current_file, speed, variants, vid_scale)
        self.video.tick(current_file, top_layer_type, speed, variants, interval, vid_scale)

    # -- context triggers (i_, d_, shake) --

    def fire_context(self, key, only_shake_pools=False):
        # type: (Optional[str], bool) -> None
        """Fire an i_, d_, or shake trigger for one key."""
        self.context.fire(key, only_shake_pools)
