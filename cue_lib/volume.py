# -*- coding: utf-8 -*-
# CueVolumeManager -- per-entry volume read/write with master x target multiplier.
# Instantiated once at _cue.volume, lives on the NoRollback _cue object.

import renpy

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.state import _cue
from cue_lib.util import create_vid_key

MYPY = False
if MYPY:
    from typing import Optional
    from cue_lib._types import MarkerEntry


class CueVolumeManager(object):
    """Volume read/write for marker entries and pools.

    Each marker entry has an optional "volume" key (master level).
    Pools (including video pools) can also have per-target "volume" keys.
    Effective playback volume = master x target, clamped to [MIN, MAX]."""

    VOL_MIN = 0.0
    VOL_DEFAULT = CUE_VOLUME_DEFAULT  # legacy alias; new code uses CUE_VOLUME_DEFAULT
    VOL_MAX = 5.0

    def get(self, entry, trigger_key=None, pool_index=None):
        # type: (Optional[MarkerEntry], Optional[str], Optional[int]) -> float
        """Raw stored volume for the target (pool or entry).
        Pool volumes default to VOL_DEFAULT (1.0 identity) so
        they multiply correctly with the master (entry-level) volume.
        Falls back to first pool when pool_index is out of range."""
        if entry is None:
            return self.VOL_DEFAULT
        if pool_index is not None:
            pools = entry.get("pools")
            if pools:
                idx = pool_index
                if 0 <= idx < len(pools):
                    resolved = _cue.markers.resolve_pool(pools[idx])
                    return resolved.volume
                if pools:
                    resolved = _cue.markers.resolve_pool(pools[0])
                    return resolved.volume
        return entry.get("volume", self.VOL_DEFAULT)

    def write(self, trigger_key, new_vol, pool_index=None):
        # type: (str, float, Optional[int]) -> None
        """Clamp and persist a volume, then save + refresh.
        With pool_index writes that specific pool; otherwise entry-level."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            return
        new_vol = max(self.VOL_MIN, min(self.VOL_MAX, round(new_vol, 1)))
        if pool_index is not None:
            pools = entry.get("pools")
            if pools and 0 <= pool_index < len(pools):
                pools[pool_index]["volume"] = new_vol
        else:
            entry["volume"] = new_vol
        _cue.markers.save_marker(trigger_key)
        renpy.restart_interaction()

    def adjust(self, trigger_key, delta, pool_index=None):
        # type: (str, float, Optional[int]) -> None
        """Adjust volume up/down by delta, clamped to [MIN, MAX].
        pool_index targets one pool; None = entry-level."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            return
        current = self.get(entry, trigger_key, pool_index)
        self.write(trigger_key, current + delta, pool_index)

    # --- Master volume (entry-level multiplier) ---

    def get_master(self, trigger_key):
        # type: (str) -> float
        """Entry-level master volume for a key. Returns VOL_DEFAULT if unset."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            return self.VOL_DEFAULT
        return entry.get("volume", self.VOL_DEFAULT)

    def set_master(self, trigger_key, value):
        # type: (str, float) -> None
        """Set entry-level master volume (clamped, persisted).
        Writes entry["volume"] directly so it works for all key types."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            return
        new_vol = max(self.VOL_MIN, min(self.VOL_MAX, round(value, 1)))
        entry["volume"] = new_vol
        _cue.markers.save_marker(trigger_key)
        renpy.restart_interaction()

    def adjust_master(self, trigger_key, delta):
        # type: (str, float) -> None
        """Adjust master volume by delta (reads raw master, not effective)."""
        self.set_master(trigger_key,
            self.get_master(trigger_key) + delta)

    # --- Effective volume (master x target) ---

    def get_effective(self, entry, trigger_key=None, pool_index=None):
        # type: (Optional[MarkerEntry], Optional[str], Optional[int]) -> float
        """Effective playback volume = master (entry-level) x target volume, clamped.
        Pool volumes default to VOL_DEFAULT (1.0 identity) so master
        is never double-counted. For entry-only queries returns master alone."""
        master = entry.get("volume", self.VOL_DEFAULT) if entry is not None else self.VOL_DEFAULT

        if pool_index is None:
            return master

        pools = entry.get("pools") if entry is not None else None
        if pools:
            idx = pool_index
            if 0 <= idx < len(pools):
                resolved = _cue.markers.resolve_pool(pools[idx])
                return max(self.VOL_MIN, min(self.VOL_MAX, master * resolved.volume))
            if pools:
                resolved = _cue.markers.resolve_pool(pools[0])
                return max(self.VOL_MIN, min(self.VOL_MAX, master * resolved.volume))
        return master

    # --- Convenience: video pool volume ---

    def adjust_video(self, delta):
        # type: (float) -> None
        """Adjust volume on the active video pool."""
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key)
        if entry is None:
            return
        pi = _cue.markers.video.target_pool
        current = self.get(entry, vid_key, pool_index=pi)
        self.write(vid_key, current + delta, pool_index=pi)
