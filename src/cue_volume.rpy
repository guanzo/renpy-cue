###############################################################################
# CueVolumeManager — per-entry volume read/write with master × target multiplier.
# Instantiated once at _cue.volume, lives on the NoRollback _cue object.
###############################################################################

init -999 python:

    class CueVolumeManager:
        """Volume read/write for marker entries, pools, and timestamps.

        Each marker entry has an optional "volume" key (master level).
        Pools and video timestamps can also have per-target "volume" keys.
        Effective playback volume = master × target, clamped to [MIN, MAX]."""

        VOL_MIN = 0.0
        VOL_DEFAULT = 1.0
        VOL_MAX = 5.0

        def get(self, entry, trigger_key=None, pool_index=None, ts_index=None):
            """Raw stored volume for the target (pool, timestamp, or entry).
            Pool/timestamp volumes default to VOL_DEFAULT (1.0 identity) so
            they multiply correctly with the master (entry-level) volume.
            v: keys read the specified ts_index (falls back to first timestamp)."""
            if trigger_key is not None and is_vid_key(trigger_key):
                timestamps = entry.get("timestamps", [])
                if timestamps:
                    idx = ts_index if ts_index is not None else 0
                    if 0 <= idx < len(timestamps):
                        return timestamps[idx].get("volume", self.VOL_DEFAULT)
                    if timestamps:
                        return timestamps[0].get("volume", self.VOL_DEFAULT)
            if pool_index is not None:
                pools = entry.get("pools")
                if pools and 0 <= pool_index < len(pools):
                    return pools[pool_index].get("volume", self.VOL_DEFAULT)
            return entry.get("volume", self.VOL_DEFAULT)

        def write(self, trigger_key, new_vol, pool_index=None, ts_index=None):
            """Clamp and persist a volume, then save + refresh.
            v: keys with ts_index write that specific timestamp; without ts_index
            broadcast to all timestamps (backward-compatible).
            i:/d: with pool_index write that pool; otherwise entry-level."""
            entry = _cue.markers.get(trigger_key)
            if entry is None:
                return
            new_vol = max(self.VOL_MIN, min(self.VOL_MAX, round(new_vol, 1)))
            if is_vid_key(trigger_key):
                timestamps = entry.get("timestamps", [])
                if not timestamps:
                    return
                if ts_index is not None and 0 <= ts_index < len(timestamps):
                    timestamps[ts_index]["volume"] = new_vol
                else:
                    for ts_entry in timestamps:
                        ts_entry["volume"] = new_vol
            else:
                target = None
                if pool_index is not None:
                    pools = entry.get("pools")
                    if pools and 0 <= pool_index < len(pools):
                        target = pools[pool_index]
                if target is None:
                    target = entry
                target["volume"] = new_vol
            _cue_save_markers()
            renpy.restart_interaction()

        def adjust(self, trigger_key, delta, pool_index=None):
            """Adjust volume up/down by delta, clamped to [MIN, MAX].
            pool_index targets one pool for i:/d: entries; None = entry-level."""
            entry = _cue.markers.get(trigger_key)
            if entry is None:
                return
            current = self.get(entry, trigger_key, pool_index)
            self.write(trigger_key, current + delta, pool_index)

        # --- Master volume (entry-level multiplier) ---

        def get_master(self, trigger_key):
            """Entry-level master volume for a key. Returns VOL_DEFAULT if unset."""
            entry = _cue.markers.get(trigger_key)
            if entry is None:
                return self.VOL_DEFAULT
            return entry.get("volume", self.VOL_DEFAULT)

        def set_master(self, trigger_key, value):
            """Set entry-level master volume (clamped, persisted).
            Writes entry["volume"] directly so it works for all key types."""
            entry = _cue.markers.get(trigger_key)
            if entry is None:
                return
            new_vol = max(self.VOL_MIN, min(self.VOL_MAX, round(value, 1)))
            entry["volume"] = new_vol
            _cue_save_markers()
            renpy.restart_interaction()

        def adjust_master(self, trigger_key, delta):
            """Adjust master volume by delta (reads raw master, not effective)."""
            self.set_master(trigger_key,
                self.get_master(trigger_key) + delta)

        # --- Effective volume (master × target) ---

        def get_effective(self, entry, trigger_key=None, pool_index=None, ts_index=None):
            """Effective playback volume = master (entry-level) x target volume, clamped.
            Pool/timestamp volumes default to VOL_DEFAULT (1.0 identity) so master
            is never double-counted. For entry-only queries returns master alone."""
            master = entry.get("volume", self.VOL_DEFAULT) if entry is not None else self.VOL_DEFAULT
            if trigger_key is not None and is_vid_key(trigger_key):
                timestamps = entry.get("timestamps", [])
                if timestamps:
                    idx = ts_index if ts_index is not None else 0
                    if 0 <= idx < len(timestamps):
                        raw = timestamps[idx].get("volume", self.VOL_DEFAULT)
                    else:
                        raw = timestamps[0].get("volume", self.VOL_DEFAULT)
                    return max(self.VOL_MIN, min(self.VOL_MAX, master * raw))
            if pool_index is not None:
                pools = entry.get("pools")
                if pools and 0 <= pool_index < len(pools):
                    raw = pools[pool_index].get("volume", self.VOL_DEFAULT)
                    return max(self.VOL_MIN, min(self.VOL_MAX, master * raw))
            return master

        # --- Convenience: video timestamp volume ---

        def adjust_video(self, delta):
            """Adjust volume on the active video timestamp."""
            vid_key = create_vid_key(_cue.current_file)
            entry = _cue.markers.get(vid_key)
            if entry is None:
                return
            current = self.get(entry, vid_key, ts_index=_cue.markers.video.target_pool)
            self.write(vid_key, current + delta, ts_index=_cue.markers.video.target_pool)

        # --- Bar changed callback ---

        def on_bar_changed(self):
            """Called after any volume bar is dragged. Saves and refreshes the UI."""
            _cue_save_markers()
            renpy.restart_interaction()
