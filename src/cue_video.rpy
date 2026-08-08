###############################################################################
# CueVideoManager — per-video playback state and control.
# Instantiated once at _cue.vid_manager, lives on the NoRollback _cue object.
###############################################################################

init -999 python:

    class CueVideoManager:
        """Per-video playback state and control.
        Methods act on self.channel (the movie channel this state tracks);
        _cue.vid_manager.channel is kept in sync by _cue_refresh_channel."""

        def __init__(self, channel=None):
            self.reset(channel)

        # --- Playback control ---

        def reset(self, channel=None):
            """Reinitialize playback state (video changed).
            Keeps the current channel unless a new one is given."""
            self.channel = channel
            self.paused = False
            self.refreshing = False
            self.fps = 30
            self.last_elapsed = 0.0
            self.frame_time = 1.0 / 30.0
            self.time_offset = 0.0
            self.step_target = 0.0
            self.pause_target = 0.0
            self.pause_origin = 0.0
            self.total_offset = 0.0  # deprecated, kept for attribute compatibility

        def set_fps(self, fps):
            """Apply the detected video framerate."""
            self.fps = fps
            self.frame_time = 1.0 / fps

        def reset_pause(self):
            """Clear the paused flag without touching playback (after load)."""
            self.paused = False

        def get_elapsed(self):
            """Get current playback position (real pos + virtual offset)."""
            if not self.channel:
                return 0.0
            try:
                pos = renpy.music.get_pos(channel=self.channel)
                if pos is not None:
                    return max(0.0, pos + self.time_offset)
            except Exception:
                pass
            return 0.0

        def get_duration(self):
            """Get total duration of the current video in seconds.
            Returns 0.0 when the channel is unavailable or duration cannot
            be queried."""
            if not self.channel:
                return 0.0
            try:
                dur = renpy.music.get_duration(channel=self.channel)
                if dur is not None and dur > 0:
                    return dur
            except Exception:
                pass
            return 0.0

        def get_video_path(self):
            """Get the filepath of the currently playing video."""
            if not self.channel:
                return None
            try:
                return renpy.music.get_playing(channel=self.channel)
            except Exception:
                return None

        def toggle_pause(self):
            """Toggle pause on the active video channel."""
            if not self.channel:
                return
            self.time_offset = 0.0
            try:
                currently_paused = renpy.music.get_pause(channel=self.channel)
                new_state = not currently_paused
                renpy.music.set_pause(new_state, channel=self.channel)
                self.paused = new_state
                if new_state:  # Just paused — save origin
                    self.pause_origin = renpy.music.get_pos(channel=self.channel) or 0.0
                    self.total_offset = 0.0
                    _cue_log("pause: origin={:.3f}".format(self.pause_origin))
                else:  # Just unpaused
                    self.total_offset = 0.0
                    _cue_log("unpause: reset offset")
            except Exception:
                # Fallback: use volume as pseudo-pause
                if not self.paused:
                    renpy.music.set_volume(0.0, delay=0, channel=self.channel)
                    self.paused = True
                else:
                    renpy.music.set_volume(1.0, delay=0, channel=self.channel)
                    self.paused = False

        def seek_frame(self, delta_frames):
            """Step forward/backward.
            Forward: briefly unpause, auto-re-pause via tick timer.
            Backward: restart from 0, auto-pause at origin + accumulated offset.
            Does not wrap around — clamps at 0 and duration."""
            if not self.channel:
                return
            frame_seconds = self.frame_time
            # Auto-pause if video is playing
            if not self.paused:
                renpy.music.set_pause(True, channel=self.channel)
                self.paused = True
                self.pause_origin = renpy.music.get_pos(channel=self.channel) or 0.0
                self.total_offset = 0.0
                self.time_offset = 0.0
            dur = renpy.music.get_duration(channel=self.channel) or 0.0
            if delta_frames > 0:
                pos = renpy.music.get_pos(channel=self.channel) or 0.0
                target = pos + delta_frames * frame_seconds
                if dur > 0:
                    target = _cue_clamp_time(target, dur)
                self.step_target = max(0.001, target)
                _cue_log("+f step_target={:.3f}".format(self.step_target))
                renpy.music.set_pause(False, channel=self.channel)
            else:  # delta_frames < 0
                self.total_offset += delta_frames * frame_seconds
                origin = self.pause_origin
                target = origin + self.total_offset
                if dur > 0:
                    target = _cue_clamp_time(target, dur)
                else:
                    target = max(0.0, target)
                filepath = renpy.music.get_playing(channel=self.channel)
                _cue_log(
                    "-f origin={:.3f} total_offset={:.3f} target={:.3f} dur={:.3f}"
                    .format(origin, self.total_offset, target, dur)
                )
                if filepath and dur > 0:
                    self.pause_target = max(0.001, target)
                    renpy.music.stop(channel=self.channel, fadeout=0)
                    renpy.music.play(filepath, channel=self.channel, loop=True)

        def seek_to(self, target_time):
            """Seek to an absolute timestamp and pause there.
            Forward (target >= current pos): pause, set step_target, unpause.
            The tick auto-pauses when pos reaches the target — no restart.
            Backward (target < current pos): restart from 0 with pause_target."""
            if not self.channel:
                return
            dur = renpy.music.get_duration(channel=self.channel) or 0.0
            if dur <= 0:
                return
            target = _cue_clamp_time(target_time, dur)
            current_pos = renpy.music.get_pos(channel=self.channel) or 0.0
            # Reset offset tracking for the absolute target
            self.pause_origin = target
            self.total_offset = 0.0
            self.time_offset = 0.0
            self.pause_target = 0.0
            if target >= current_pos:
                # Forward seek: pause, set step target, unpause (same as +1f)
                if not self.paused:
                    renpy.music.set_pause(True, channel=self.channel)
                    self.paused = True
                self.step_target = max(0.001, target)
                renpy.music.set_pause(False, channel=self.channel)
            else:
                # Backward seek: restart from 0 (same as -1f)
                filepath = renpy.music.get_playing(channel=self.channel)
                if not filepath:
                    return
                self.step_target = 0.0
                self.pause_target = max(0.001, target)
                renpy.music.stop(channel=self.channel, fadeout=0)
                renpy.music.play(filepath, channel=self.channel, loop=True)

        # --- Tick hooks ---

        def poll_autopause(self):
            """Tick hook: auto-re-pause when a seek target is reached."""
            if not self.channel or _cue.top_layer_type != 'movie':
                return
            try:
                pos = renpy.music.get_pos(channel=self.channel)
            except Exception:
                return
            has_pos = pos is not None
            if has_pos and self.pause_target > 0 and pos >= self.pause_target:
                renpy.music.set_pause(True, channel=self.channel)
                self.pause_target = 0.0
                self.paused = True
                self.time_offset = 0.0
            if has_pos and self.step_target > 0 and pos >= self.step_target:
                renpy.music.set_pause(True, channel=self.channel)
                self.step_target = 0.0
                self.paused = True
                self.time_offset = 0.0

        def sync_paused(self):
            """Mirror the channel's real pause state (UI play/pause buttons)."""
            if not self.channel:
                return
            try:
                self.paused = renpy.music.get_pause(channel=self.channel)
            except Exception:
                pass

        # --- Label getters (zero-arg callables for SelfUpdatingLabel) ---

        def time_label(self):
            """Return 'elapsed / duration' formatted for the live time display."""
            if _cue.top_layer_type != 'movie':
                return "--:--.-- / --:--.--"
            e = self.get_elapsed()
            d = self.get_duration()
            return "{} / {}".format(
                _cue_format_time(e),
                _cue_format_time(d),
            )

        def frame_label(self):
            """Return 'frame / total' formatted for the live frame display."""
            if _cue.top_layer_type != 'movie':
                return "---/---"
            e = self.get_elapsed()
            d = self.get_duration()
            fps = max(1, self.fps)
            return "{}/{}".format(int(e * fps), int(d * fps))
