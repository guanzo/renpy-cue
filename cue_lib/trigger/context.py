# -*- coding: utf-8 -*-
# CueContextTrigger -- i_, d_, and shake one-shot fires on context change.
# One domain of CueTriggerEngine; the engine owns tick cadence, this owns the
# per-key one-shot fire path.

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.markers import CueExclusiveStart
from cue_lib.state import _cue
from cue_lib.trigger.exclusive import CUE_EXCL_KIND_ONESHOT, CUE_EXCL_KIND_VIDEO
from cue_lib.trigger.helpers import _cue_pick_deduped, _cue_vid_intensity_resolution
from cue_lib.util import _cue_log, get_key_file, is_dlg_key

MYPY = False
if MYPY:
    from typing import Optional
    from cue_lib.trigger.engine import CueTriggerEngine  # pyright: ignore[reportUnusedImport]


class CueContextTrigger(object):
    """One-shot SFX fired on scene/dialogue/shake context changes."""

    def __init__(self, engine):
        # type: (CueTriggerEngine) -> None
        self._engine = engine

    def fire(self, key, only_shake_pools=False):
        # type: (Optional[str], bool) -> None
        """Fire an i_, d_, or shake trigger for one key.

        Multi-pool entries play one random file from EACH pool concurrently.
        Dedupe guard: same file in two pools of the same trigger is re-picked
        up to 3 times, then skipped to avoid echo artifacts.

        An empty key is a no-op.  When only_shake_pools is True, pools without
        the trigger_on_shake flag are skipped -- used by screenshake triggers
        so each pool independently opts in to firing on shake."""
        if not self._engine.active:
            return
        if not key:
            return

        # Global intensity volume scale: context one-shots (image/dialogue/
        # shake) firing during a video with intensity play at the video's
        # active level volume.  Computed on demand -- fire_context runs before
        # tick in the same frame, so a per-tick cache would be one frame stale.
        vid_scale = 1.0
        if _cue.ctx.current_file:
            vres = _cue_vid_intensity_resolution(
                self._engine._store,
                _cue.ctx.current_file,
                self._engine._speed_resolver.get_current_speed(),
                self._engine._speed_resolver.banding_speeds(_cue.ctx.current_file),
            )
            if vres is not None:
                vid_scale = vres.volume_mult

        entry = self._engine._store.get(key)
        if not entry:
            return
        pools = entry.get("pools", [])
        if not pools:
            return
        vol = entry.get("volume", CUE_VOLUME_DEFAULT)
        # Resolve each pool once; the log's file count and the fire pass
        # below share the same resolutions.
        resolved_pools = [self._engine._store.resolve_pool(p, expand=True) for p in pools]
        total = sum(len(r.files or []) for r in resolved_pools)

        _cue_log("CTX-TRIGGER key={} pools={} files={} vol={:.2f}".format(key, len(pools), total, vol))

        # Group identity: scene (file) + line (dialogue key, or None for
        # image/shake). Same scene AND (either is non-dialogue OR same
        # line) share a group -- image/dialogue coexist, a new line cuts
        # the previous one.
        scene = get_key_file(key)
        line = key if is_dlg_key(key) else None

        picked = []
        for pi, (pool, resolved) in enumerate(zip(pools, resolved_pools)):
            if only_shake_pools and not resolved.trigger_on_shake:
                continue
            files = resolved.files
            if not files:
                continue
            excl = resolved.exclusive
            # Hold gate: a holding out-group SFX owns the air -- drop this pool.
            if self._engine.excl.is_hold_blocked(CUE_EXCL_KIND_ONESHOT, scene, line):
                _cue_log("CTX-DROPPED key={} pool={} (held)".format(key, pi))
                continue
            # One-shot pools can't defer: "wait" only plays into open air.
            if excl.start == CueExclusiveStart.WAIT and self._engine.excl.is_outgroup_busy(
                CUE_EXCL_KIND_ONESHOT, scene, line
            ):
                _cue_log("CTX-DROPPED key={} pool={} (air busy)".format(key, pi))
                continue
            file = _cue_pick_deduped(files, picked)
            if file is None:
                continue
            picked.append(file)

            if excl.start == CueExclusiveStart.FADE:
                # Cut-in: fade out one-shots outside this group, plus any
                # playing loops (one-shots cut loops).  Video-marker SFX
                # are spared -- they're tracked as their own kind.
                faded = _cue.sfx.fade_out(
                    exclude_channels=(
                        self._engine.excl.group_channels(CUE_EXCL_KIND_ONESHOT, scene, line)
                        + self._engine.excl.kind_channels(CUE_EXCL_KIND_VIDEO)
                    )
                )
                _cue_log("CTX-FADE key={} pool={} faded={}".format(key, pi, faded))
            ch_used = _cue.sfx.play_pool(entry, key, pool, pi, file=file, volume_mult=vid_scale)
            self._engine.excl.track_channel(ch_used, CUE_EXCL_KIND_ONESHOT, scene, line, excl.hold)
