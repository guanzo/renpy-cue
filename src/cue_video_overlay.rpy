###############################################################################
# CueVideoOverlay — non-destructive video speed overlay.
# Plays speed-edited variants ON TOP of the original game video instead of
# replacing the original file on disk. Variants are generated on demand as
# "{basename}.{speed:.2f}x{ext}" next to the original and persist.
#
# Instantiated once at _cue.video_overlay (cue_z.rpy init -999).
###############################################################################

init -999 python:
    import os as _os
    import time as _time

    class CueVideoOverlay:
        """Non-destructive video speed overlay.

        When active, the original game video is paused and a speed-edited
        variant plays on a separate movie channel above the master layer.
        The original file is never modified; variants live alongside it."""

        # Hardcoded default speeds (1.0 = original, no overlay).
        DEFAULT_SPEEDS = python_list([1.0, 1.5, 2.0, 2.5])

        def __init__(self):
            # Speed presets (combined from hardcoded + user)
            self.speeds = python_list(self.DEFAULT_SPEEDS)
            self.user_speeds = python_list([])
            self._load_user_speeds()

            # Active state
            self.active = False
            self.speed = 1.0          # active variant speed
            self.speed_index = 0      # index into _all_speeds
            self.vpath = None         # original video virtual path
            self.variant_vpath = None # currently playing variant file path
            self.orig_channel = None  # game's movie channel (paused)
            self.overlay_ch = "_movie_2"
            self.orig_was_playing = False
            self.was_paused = False   # user paused during overlay
            self.logical_pos = 0.0    # position on the ORIGINAL timeline
            self.variant_dur = 0.0
            self.last_overlay_pos = 0.0
            self.pause_target = 0.0
            self.step_target = 0.0

            # Generation state
            self.generating = False
            self.gen_speed = 0.0
            self.gen_error = ""

        # ------------------------------------------------------------------
        # Persistence
        # ------------------------------------------------------------------

        def _load_user_speeds(self):
            """Load user-added speed presets from persistent storage."""
            try:
                data = getattr(_cue.markers, '_data', None)
                if data is not None:
                    stored = data.get("video_overlay_user_speeds", None)
                    if stored is not None:
                        self.user_speeds = python_list([float(s) for s in stored])
            except Exception:
                self.user_speeds = python_list([])

        def _save_user_speeds(self):
            """Save user-added speed presets to persistent storage."""
            try:
                _cue.markers._data["video_overlay_user_speeds"] = list(self.user_speeds)
                _cue.markers.save_persistent()
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Speed list
        # ------------------------------------------------------------------

        @property
        def _all_speeds(self):
            """Combined and sorted list of all available speeds."""
            combined = list(self.speeds)
            for s in self.user_speeds:
                if s not in combined:
                    combined.append(s)
            combined.sort()
            return python_list(combined)

        def get_preset_speeds(self):
            """Return all speeds except 1.0 (for preset UI buttons)."""
            return python_list([s for s in self._all_speeds if abs(s - 1.0) > 0.001])

        def _index_of(self, speed):
            """Find the index of a speed in _all_speeds. Returns -1 if not found."""
            all_s = self._all_speeds
            for i, s in enumerate(all_s):
                if abs(s - speed) < 0.001:
                    return i
            return -1

        # ------------------------------------------------------------------
        # User speed management
        # ------------------------------------------------------------------

        def add_user_speed(self, speed):
            """Add a custom speed to the user presets list."""
            speed = round(max(0.25, min(4.0, speed)), 2)
            if speed not in self.user_speeds and abs(speed - 1.0) > 0.001:
                self.user_speeds.append(speed)
                self.user_speeds.sort()
                self._save_user_speeds()
                renpy.restart_interaction()

        def remove_user_speed(self, speed):
            """Remove a custom speed from the user presets list."""
            self.user_speeds = python_list([s for s in self.user_speeds if abs(s - speed) > 0.001])
            self._save_user_speeds()
            renpy.restart_interaction()

        # ------------------------------------------------------------------
        # Naming helpers
        # ------------------------------------------------------------------

        def variant_vpath_for(self, speed):
            """Build the virtual path for a speed variant.
            Example: 'movies/ep1.webm' + 1.5 -> 'movies/ep1.1.50x.webm'"""
            vp = _cue.vid_manager.get_video_path()
            if not vp:
                return None
            base, ext = _os.path.splitext(vp)
            if not ext:
                ext = ".webm"
            return "{}.{:.2f}x{}".format(base, speed, ext)

        def variant_fspath_for(self, speed):
            """Build the real filesystem path for a speed variant."""
            vp = self.variant_vpath_for(speed)
            if not vp:
                return None
            return _os.path.normpath(_os.path.join(renpy.config.gamedir, vp))

        def variant_exists(self, speed):
            """Check whether a speed variant file already exists on disk."""
            fspath = self.variant_fspath_for(speed)
            if not fspath:
                return False
            return _os.path.exists(fspath)

        # ------------------------------------------------------------------
        # Channel selection
        # ------------------------------------------------------------------

        def _pick_overlay_channel(self):
            """Return a free movie channel for the overlay.
            Prefers _movie_2, falls back to _movie_1, returns None if both busy."""
            for ch in ("_movie_2", "_movie_1"):
                if ch != _cue.active_channel:
                    try:
                        if not renpy.music.is_playing(channel=ch):
                            return ch
                    except Exception:
                        pass
            # Both busy — try them anyway (last resort)
            if "_movie_2" != _cue.active_channel:
                return "_movie_2"
            if "_movie_1" != _cue.active_channel:
                return "_movie_1"
            return None

        # ------------------------------------------------------------------
        # Activation / deactivation
        # ------------------------------------------------------------------

        def cycle_speed(self, delta):
            """Cycle to the next or previous speed in the list (wrapping).
            Called from key bindings (Period/Comma). delta = 1 or -1."""
            if _cue.top_layer_type != 'movie':
                return
            if self.generating:
                return
            all_s = self._all_speeds
            if not all_s:
                return
            if not self.active:
                # Not active yet — activate at current index (1.0)
                idx = self._index_of(1.0)
                if idx < 0:
                    idx = 0
            else:
                idx = self.speed_index
            new_idx = (idx + delta) % len(all_s)
            self.activate_speed(all_s[new_idx])

        def activate_speed(self, speed):
            """Activate a speed variant. 1.0 means deactivate (back to original)."""
            if self.generating:
                return
            if _cue.top_layer_type != 'movie':
                return
            if not _cue.active_channel:
                return

            # 1.0 = back to original
            if abs(speed - 1.0) < 0.001:
                if self.active:
                    self.deactivate()
                return

            # Same speed = no-op
            if self.active and abs(self.speed - speed) < 0.001:
                return

            # Check channel availability
            ov_ch = self._pick_overlay_channel()
            if ov_ch is None:
                self.gen_error = "No free movie channel available for overlay."
                renpy.restart_interaction()
                return

            # If a different overlay is already active, deactivate it first
            if self.active:
                _prev_logical = self.logical_pos
                _prev_was_paused = self.was_paused
                self._teardown_overlay()
            else:
                _prev_logical = _cue.vid_manager.get_elapsed()
                _prev_was_paused = False

            # Check if variant exists — generate if not
            if not self.variant_exists(speed):
                self._start_generation(speed, _prev_logical, _prev_was_paused, ov_ch)
                return

            self._start_activation(speed, _prev_logical, _prev_was_paused, ov_ch)

        def _start_activation(self, speed, logical_pos, was_paused, ov_ch):
            """Internal: activate the overlay with an existing variant file."""
            vid = _cue.vid_manager

            # Capture original state
            self.orig_channel = _cue.active_channel
            self.orig_was_playing = not vid.paused
            self.was_paused = was_paused

            # Pause the original video
            try:
                renpy.music.set_pause(True, channel=self.orig_channel)
            except Exception:
                pass
            vid.paused = True

            # Set up overlay state
            self.vpath = vid.get_video_path()
            self.variant_vpath = self.variant_vpath_for(speed)
            self.overlay_ch = ov_ch
            self.speed = speed
            self.speed_index = self._index_of(speed)
            self.logical_pos = logical_pos
            self.active = True
            self.pause_target = 0.0
            self.step_target = 0.0

            # Play the variant on the overlay channel
            if self.variant_vpath:
                try:
                    renpy.music.play(
                        self.variant_vpath,
                        channel=self.overlay_ch,
                        loop=True,
                    )
                except Exception:
                    self.deactivate()
                    self.gen_error = "Failed to play variant on overlay channel."
                    renpy.restart_interaction()
                    return

            # Get variant duration
            try:
                self.variant_dur = renpy.music.get_duration(channel=self.overlay_ch) or 10.0
            except Exception:
                self.variant_dur = 10.0

            # Seek the variant to the equivalent position
            if self.variant_dur > 0 and logical_pos > 0:
                variant_target = logical_pos / speed
                self._seek_overlay(variant_target)
            else:
                self.last_overlay_pos = 0.0

            # Show the overlay screen
            renpy.show_screen("cue_overlay_video", _layer="cue_video_layer")
            renpy.restart_interaction()

            _cue_log("OVERLAY: activated {:.2f}x logical={:.3f} ch={}".format(
                speed, logical_pos, self.overlay_ch))

        def deactivate(self):
            """Deactivate the overlay and restore the original video."""
            if not self.active:
                return

            logical = self.logical_pos
            orig_ch = self.orig_channel
            orig_playing = self.orig_was_playing
            user_paused = self.was_paused

            self._teardown_overlay()

            # Restore original video position
            if orig_ch:
                vid = _cue.vid_manager
                try:
                    vid.seek_to(logical)
                except Exception:
                    pass

                # Restore pause state
                try:
                    if user_paused:
                        renpy.music.set_pause(True, channel=orig_ch)
                        vid.paused = True
                    elif orig_playing:
                        renpy.music.set_pause(False, channel=orig_ch)
                        vid.paused = False
                    else:
                        # Original was paused — keep it paused
                        renpy.music.set_pause(True, channel=orig_ch)
                        vid.paused = True
                except Exception:
                    pass

            renpy.restart_interaction()
            _cue_log("OVERLAY: deactivated logical={:.3f}".format(logical))

        def _teardown_overlay(self):
            """Internal: hide overlay screen, stop channel, reset state.
            Does NOT restore the original video (caller handles that)."""
            # Capture logical position before teardown
            try:
                if self.overlay_ch and self.active:
                    pos = renpy.music.get_pos(channel=self.overlay_ch)
                    if pos is not None:
                        self.logical_pos = pos * self.speed
            except Exception:
                pass

            # Hide the overlay screen
            try:
                renpy.hide_screen("cue_overlay_video", layer="cue_video_layer")
            except Exception:
                pass

            # Stop the overlay channel
            if self.overlay_ch:
                try:
                    renpy.music.stop(channel=self.overlay_ch, fadeout=0)
                except Exception:
                    pass

            # Reset state
            self.active = False
            self.speed = 1.0
            self.speed_index = 0
            self.vpath = None
            self.variant_vpath = None
            self.orig_channel = None
            self.overlay_ch = "_movie_2"
            self.orig_was_playing = False
            self.was_paused = False
            self.logical_pos = 0.0
            self.variant_dur = 0.0
            self.last_overlay_pos = 0.0
            self.pause_target = 0.0
            self.step_target = 0.0

        # ------------------------------------------------------------------
        # Seek
        # ------------------------------------------------------------------

        def seek_logical(self, target):
            """Seek to a position on the original (logical) timeline."""
            if not self.active:
                return
            target = max(0.0, target)
            self.logical_pos = target
            variant_target = target / max(self.speed, 0.01)
            self._seek_overlay(variant_target)

        def seek_frame(self, delta_frames):
            """Step forward/backward by frames on the logical timeline."""
            if not self.active:
                return
            fps = max(1, _cue.vid_manager.fps)
            frame_seconds = 1.0 / fps
            self.seek_logical(self.logical_pos + delta_frames * frame_seconds)

        def _seek_overlay(self, target):
            """Seek the overlay channel to a position on the VARIANT timeline.
            Uses stop+play+auto-pause pattern (movie channels ignore <from N>)."""
            if not self.overlay_ch:
                return
            dur = self.variant_dur
            if dur <= 0:
                return

            target = _cue_clamp_time(target, dur)

            # For very small targets, just restart from 0
            if target <= 0.05:
                try:
                    renpy.music.stop(channel=self.overlay_ch, fadeout=0)
                    if self.variant_vpath:
                        renpy.music.play(self.variant_vpath, channel=self.overlay_ch, loop=True)
                    self.pause_target = 0.0
                    self.step_target = 0.0
                    self.last_overlay_pos = 0.0
                except Exception:
                    pass
                return

            # Forward seek: restart from 0 with pause_target
            try:
                renpy.music.stop(channel=self.overlay_ch, fadeout=0)
                if self.variant_vpath:
                    self.pause_target = max(0.001, target)
                    self.step_target = 0.0
                    renpy.music.play(self.variant_vpath, channel=self.overlay_ch, loop=True)
                    renpy.music.set_pause(False, channel=self.overlay_ch)
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Playback control
        # ------------------------------------------------------------------

        def toggle_pause(self):
            """Toggle pause on the overlay channel."""
            if not self.active or not self.overlay_ch:
                return
            try:
                currently_paused = renpy.music.get_pause(channel=self.overlay_ch)
                new_state = not currently_paused
                renpy.music.set_pause(new_state, channel=self.overlay_ch)
                _cue.vid_manager.paused = new_state
                self.was_paused = new_state
                renpy.restart_interaction()
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Tick hook
        # ------------------------------------------------------------------

        def poll_tick(self):
            """Called from _cue_tick_trigger every 25ms while overlay is active.
            Updates logical_pos, detects variant wrap/end, and auto-deactivates
            if the game changes video or the channel vanishes."""
            if not self.active:
                return

            # Guard: original channel changed or vanished
            if self.orig_channel != _cue.active_channel:
                _cue_log("OVERLAY: channel changed, deactivating")
                self.deactivate()
                return

            # Guard: video path changed
            cur_vpath = _cue.vid_manager.get_video_path()
            if cur_vpath and self.vpath and cur_vpath != self.vpath:
                _cue_log("OVERLAY: video changed, deactivating")
                self.deactivate()
                return

            # Get current overlay position
            try:
                pos = renpy.music.get_pos(channel=self.overlay_ch)
            except Exception:
                return

            if pos is None:
                return

            # Auto-re-pause at seek targets
            if self.pause_target > 0 and pos >= self.pause_target:
                renpy.music.set_pause(True, channel=self.overlay_ch)
                self.pause_target = 0.0
                _cue.vid_manager.paused = True
                self.was_paused = True

            if self.step_target > 0 and pos >= self.step_target:
                renpy.music.set_pause(True, channel=self.overlay_ch)
                self.step_target = 0.0
                _cue.vid_manager.paused = True
                self.was_paused = True

            # Detect loop wrap (variant ended and restarted)
            if pos < self.last_overlay_pos - 0.3 and self.pause_target <= 0 and self.step_target <= 0:
                # Variant looped — deactivate and let original continue
                _cue_log("OVERLAY: variant looped, deactivating")
                self.deactivate()
                return

            self.last_overlay_pos = pos

            # Update logical position
            self.logical_pos = pos * self.speed

        # ------------------------------------------------------------------
        # Generation (delegates to CueVideoEditor)
        # ------------------------------------------------------------------

        def _start_generation(self, speed, logical_pos, was_paused, ov_ch):
            """Start ffmpeg generation of a speed variant.
            When generation completes, _start_activation is called automatically."""
            if not _cue.video_editor.ffmpeg_available():
                self.gen_error = "ffmpeg not found. Set RENPY_CUE_FFMPEG env var."
                renpy.restart_interaction()
                return

            out_fspath = self.variant_fspath_for(speed)
            if not out_fspath:
                self.gen_error = "Cannot determine output path for variant."
                renpy.restart_interaction()
                return

            # Store context for when generation completes
            self._gen_logical_pos = logical_pos
            self._gen_was_paused = was_paused
            self._gen_ov_ch = ov_ch

            self.generating = True
            self.gen_speed = speed
            self.gen_error = ""

            _cue.video_editor.apply_variant(speed, out_fspath)
            renpy.restart_interaction()

        def _on_generation_done(self, success, speed):
            """Called by CueVideoEditor.poll() when variant generation finishes."""
            self.generating = False
            if success:
                self.gen_error = ""
                # Now activate the freshly-generated variant
                logical_pos = getattr(self, '_gen_logical_pos', 0.0)
                was_paused = getattr(self, '_gen_was_paused', False)
                ov_ch = getattr(self, '_gen_ov_ch', "_movie_2")
                self._start_activation(speed, logical_pos, was_paused, ov_ch)
            else:
                self.gen_error = "Failed to generate {:.2f}x variant.".format(speed)
                renpy.restart_interaction()

        # ------------------------------------------------------------------
        # Lifecycle hooks
        # ------------------------------------------------------------------

        def after_load(self):
            """Called after rollback / game load. Drops overlay without seeking
            (the game restarted its video anyway)."""
            if self.active:
                try:
                    renpy.hide_screen("cue_overlay_video", layer="cue_video_layer")
                except Exception:
                    pass
                if self.overlay_ch:
                    try:
                        renpy.music.stop(channel=self.overlay_ch, fadeout=0)
                    except Exception:
                        pass
            self.active = False
            self.speed = 1.0
            self.speed_index = 0
            self.vpath = None
            self.variant_vpath = None
            self.orig_channel = None
            self.overlay_ch = "_movie_2"
            self.orig_was_playing = False
            self.was_paused = False
            self.logical_pos = 0.0
            self.variant_dur = 0.0
            self.last_overlay_pos = 0.0
            self.pause_target = 0.0
            self.step_target = 0.0
            self.generating = False
            self.gen_speed = 0.0
            self.gen_error = ""

        def refresh(self):
            """Called when the overlay is opened. Sync state with current video."""
            self.gen_error = ""
            if self.active:
                cur_vpath = _cue.vid_manager.get_video_path()
                if cur_vpath != self.vpath:
                    self.deactivate()
            # Re-check user speeds from persistent
            self._load_user_speeds()
