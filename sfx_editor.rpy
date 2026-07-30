###############################################################################
# SFX Video Overlay Editor v1.0.0
# Drop-in mod for Ren'Py games (7.x and 8.x compatible)
#
# Installation:
#   1. Copy this file into the game's "game/" directory
#   2. Create "game/sfx_editor/audio/" and place your .ogg/.mp3/.wav files there
#   3. Launch the game, press backtick (`) to toggle the overlay
#
# Features:
#   - Manual mode: place SFX markers at precise timestamps in looping videos
#   - Pool mode: auto-play random SFX from a pool at random intervals
#   - Frame stepping: pause video, seek forward/backward by 1 frame
#   - Elapsed / total duration display
#   - Auto-detect active movie channel
#   - Configuration persists across sessions
#   - Configurable audio directory
###############################################################################

###############################################################################
# SECTION 1: Variable Defaults (init -999 for early loading)
###############################################################################

init -999 python:
    # Version
    _sfx_editor_version = "1.0.0"

    # --- Persistent config defaults (saved to persistent._sfx_editor_config) ---
    if not hasattr(store, '_sfx_editor_config_defaults_set'):
        store._sfx_editor_config_defaults_set = True

    # --- Runtime state (not persisted; resets on game load) ---
    _sfx_editor_visible = False
    _sfx_editor_active_channel = None
    _sfx_editor_audio_dir = "sfx_editor/audio"
    _sfx_editor_mode = "manual"       # "manual" or "pool"
    _sfx_editor_markers = []          # list of {time: float, file: str}
    _sfx_editor_pool_files = []       # list of filenames
    _sfx_editor_pool_min_delay = 2.0
    _sfx_editor_pool_max_delay = 8.0
    _sfx_editor_pool_enabled = False
    _sfx_editor_next_pool_time = 0.0
    _sfx_editor_played_markers = set()
    _sfx_editor_available_files = []  # scanned from audio dir
    _sfx_editor_current_time_str = "00:00.00"
    _sfx_editor_total_time_str = "00:00.00"
    _sfx_editor_paused = False
    _sfx_editor_scan_error = None
    _sfx_editor_channel_status = "No video"
    _sfx_editor_initialized = False
    _sfx_editor_selected_file_index = 0
    _sfx_editor_manual_channel_input = ""
    _sfx_editor_pool_min_str = "2.0"
    _sfx_editor_pool_max_str = "8.0"

    # Display counts (pre-computed for screen text interpolation)
    _sfx_editor_audio_count = 0
    _sfx_editor_marker_count = 0
    _sfx_editor_pool_count = 0

    # Internal tracking
    _sfx_editor__last_pos = 0.0
    _sfx_editor__sfx_channel_idx = 0
    _sfx_editor__fallback_start = 0.0
    _sfx_editor__using_fallback = False
    _sfx_editor__frame_time = 1.0 / 30.0
    _sfx_editor__marker_tolerance = 0.08


###############################################################################
# SECTION 2: Init Block (init 999 python)
###############################################################################

init 999 python:
    # Enable dev tools for this mod (Shift+R reload, Shift+O console)
    config.developer = True
    config.console = True

    # Clear debug log for fresh session
    try:
        log_dir = os.path.join(renpy.config.gamedir, "sfx_editor")
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        log_path = os.path.join(log_dir, "debug.log")
        open(log_path, "w").close()
    except Exception:
        pass

    if not _sfx_editor_initialized:
        # Register 8 dedicated SFX channels on the "sfx" mixer
        for i in range(1, 9):
            ch_name = "_sfx_{}".format(i)
            if not renpy.music.channel_defined(ch_name):
                renpy.music.register_channel(
                    ch_name, "sfx", loop=False, stop_on_mute=True, tight=False
                )

        # Create a layer above screens for the overlay
        renpy.add_layer("sfx_editor_layer", above="screens")

        # Use config.overlay_screens for a persistent key-listener
        # (config.underlay keymaps are unreliable across Ren'Py versions)
        config.overlay_screens.append("sfx_editor_key_listener")
        _sfx_editor_log("INIT: overlay_screens key listener registered")

        # Register after_load callback (avoids label conflict with game's own after_load)
        def _sfx_editor_after_load():
            if _sfx_editor_visible:
                _sfx_editor_visible = False
                _sfx_editor_paused = False
                _sfx_editor_pool_enabled = False
        config.after_load_callbacks.append(_sfx_editor_after_load)

        _sfx_editor_initialized = True


###############################################################################
# SECTION 3: Core Python Functions
###############################################################################

init python:
    import os

    # --------------------------------------------------------------------------
    # Debug Logging
    # --------------------------------------------------------------------------

    def _sfx_editor_log(msg):
        """Append a debug message to sfx_editor/debug.log."""
        try:
            log_dir = os.path.join(renpy.config.gamedir, "sfx_editor")
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir)
            log_path = os.path.join(log_dir, "debug.log")
            with open(log_path, "a") as f:
                f.write("{}\n".format(msg))
        except Exception:
            pass  # Never let logging break the game

    # --------------------------------------------------------------------------
    # Visibility
    # --------------------------------------------------------------------------

    def _sfx_editor_toggle():
        """Toggle the overlay on/off. Called from the key-listener screen."""
        _sfx_editor_log("TOGGLE: visible={}".format(_sfx_editor_visible))
        if _sfx_editor_visible:
            _sfx_editor_log("TOGGLE: calling hide")
            _sfx_editor_hide()
        else:
            _sfx_editor_log("TOGGLE: calling show")
            _sfx_editor_show()


    def _sfx_editor_show():
        global _sfx_editor_visible, _sfx_editor_active_channel
        global _sfx_editor_manual_channel_input
        global _sfx_editor_pool_min_str, _sfx_editor_pool_max_str
        _sfx_editor_visible = True
        # Load persisted config
        _sfx_editor_load_config()
        # Initialize string fields from current values
        _sfx_editor_manual_channel_input = (
            _sfx_editor_active_channel if _sfx_editor_active_channel else ""
        )
        _sfx_editor_pool_min_str = "{:.1f}".format(_sfx_editor_pool_min_delay)
        _sfx_editor_pool_max_str = "{:.1f}".format(_sfx_editor_pool_max_delay)
        # Scan audio files
        _sfx_editor_scan_audio()
        # Auto-detect channel
        _sfx_editor_refresh_channel()
        # Update channel input after detection
        _sfx_editor_manual_channel_input = (
            _sfx_editor_active_channel if _sfx_editor_active_channel else ""
        )
        # Show the overlay screen
        renpy.show_screen("sfx_editor_overlay", _layer="sfx_editor_layer")
        renpy.restart_interaction()


    def _sfx_editor_hide():
        global _sfx_editor_visible
        _sfx_editor_visible = False
        # Save config on close
        _sfx_editor_save_config()
        renpy.hide_screen("sfx_editor_overlay", layer="sfx_editor_layer")


    # --------------------------------------------------------------------------
    # Channel Detection
    # --------------------------------------------------------------------------

    def _sfx_editor_refresh_channel():
        """Auto-detect the active movie channel by scanning ALL channels."""
        global _sfx_editor_active_channel, _sfx_editor_channel_status

        _sfx_editor_log("refresh_channel: scanning all channels...")

        # Try to access Ren'Py's internal channel list
        try:
            import renpy.audio.audio as aaudio
            all_channels = list(aaudio.channels.keys())
            _sfx_editor_log("refresh_channel: all channels = {}".format(all_channels))
            for ch_name in all_channels:
                try:
                    is_play = renpy.music.is_playing(channel=ch_name)
                    dur = renpy.music.get_duration(channel=ch_name)
                    path = renpy.music.get_playing(channel=ch_name)
                    _sfx_editor_log("  {}: playing={}, dur={}, path={}".format(
                        ch_name, is_play, dur,
                        path[-60:] if path else None))
                    if is_play and dur > 0:
                        _sfx_editor_active_channel = ch_name
                        _sfx_editor_channel_status = ch_name
                        _sfx_editor_reset_loop_tracking()
                        _sfx_editor_log("refresh_channel: FOUND active channel: {}".format(ch_name))
                        return
                except Exception as e2:
                    _sfx_editor_log("  {}: error={}".format(ch_name, e2))
        except Exception as e:
            _sfx_editor_log("refresh_channel: failed to get channels: {}".format(e))

        # Fallback: check known channels
        for ch in ["movie", "music", "sound", "audio"]:
            try:
                if renpy.music.is_playing(channel=ch) and renpy.music.get_duration(channel=ch) > 0:
                    _sfx_editor_active_channel = ch
                    _sfx_editor_channel_status = ch
                    _sfx_editor_reset_loop_tracking()
                    _sfx_editor_log("refresh_channel: fallback found: {}".format(ch))
                    return
            except Exception:
                pass

        _sfx_editor_channel_status = "No video detected"
        _sfx_editor_log("refresh_channel: NO CHANNEL FOUND")


    def _sfx_editor_set_channel_manual(ch_name):
        """Manually set the active channel."""
        global _sfx_editor_active_channel, _sfx_editor_channel_status
        global _sfx_editor_manual_channel_input
        ch_name = ch_name.strip()
        if ch_name and renpy.music.channel_defined(ch_name):
            _sfx_editor_active_channel = ch_name
            _sfx_editor_channel_status = ch_name
            _sfx_editor_manual_channel_input = ch_name
            _sfx_editor_reset_loop_tracking()
        elif ch_name:
            _sfx_editor_channel_status = "Channel '{}' not found".format(ch_name)


    def _sfx_editor_reset_loop_tracking():
        """Reset played markers and loop detection when video changes."""
        global _sfx_editor_played_markers, _sfx_editor_next_pool_time
        global _sfx_editor__last_pos
        _sfx_editor_played_markers = set()
        _sfx_editor_next_pool_time = 0.0
        _sfx_editor__last_pos = 0.0


    # --------------------------------------------------------------------------
    # Video Metadata
    # --------------------------------------------------------------------------

    def _sfx_editor_get_elapsed():
        """Get current playback position in seconds. Falls back to timer."""
        ch = _sfx_editor_active_channel
        if not ch:
            return 0.0
        try:
            pos = renpy.music.get_pos(channel=ch)
            if pos is not None:
                return pos
        except Exception:
            pass
        return 0.0


    def _sfx_editor_get_duration():
        """Get total duration of the current video in seconds."""
        ch = _sfx_editor_active_channel
        if not ch:
            return 0.0
        try:
            dur = renpy.music.get_duration(channel=ch)
            if dur is not None and dur > 0:
                return dur
        except Exception:
            pass
        return 0.0


    def _sfx_editor_get_video_path():
        """Get the filepath of the currently playing video."""
        ch = _sfx_editor_active_channel
        if not ch:
            return None
        try:
            return renpy.music.get_playing(channel=ch)
        except Exception:
            return None


    # --------------------------------------------------------------------------
    # Video Control: Pause
    # --------------------------------------------------------------------------

    def _sfx_editor_toggle_pause():
        """Toggle pause on the active video channel."""
        global _sfx_editor_paused
        ch = _sfx_editor_active_channel
        if not ch:
            return

        try:
            currently_paused = renpy.music.get_pause(channel=ch)
            new_state = not currently_paused
            renpy.music.set_pause(new_state, channel=ch)
            _sfx_editor_paused = new_state
        except Exception:
            # Fallback: use volume as pseudo-pause
            if not _sfx_editor_paused:
                renpy.music.set_volume(0.0, delay=0, channel=ch)
                _sfx_editor_paused = True
            else:
                renpy.music.set_volume(1.0, delay=0, channel=ch)
                _sfx_editor_paused = False


    # --------------------------------------------------------------------------
    # Video Control: Frame Seeking
    # --------------------------------------------------------------------------

    def _sfx_editor_seek_frame(delta_frames):
        """Step forward or backward by N frames.

        Uses stop/restart with <from N> syntax because Ren'Py lacks
        native seek. A frame is ~1/30 second (0.0333s).
        """
        ch = _sfx_editor_active_channel
        if not ch:
            return

        # Get current state
        pos = renpy.music.get_pos(channel=ch)
        if pos is None:
            return

        filepath = renpy.music.get_playing(channel=ch)
        if filepath is None:
            return

        dur = renpy.music.get_duration(channel=ch)
        if dur is None or dur <= 0:
            return

        # Calculate new position
        new_time = pos + (delta_frames * _sfx_editor__frame_time)
        new_time = max(0.0, min(new_time, dur - 0.05))

        # Remember pause state
        was_paused = _sfx_editor_paused or renpy.music.get_pause(channel=ch)

        # Stop and restart from the new offset
        renpy.music.stop(channel=ch, fadeout=0)
        seek_path = "<from {:.3f}>{}".format(new_time, filepath)
        renpy.music.play(seek_path, channel=ch, loop=True)

        # Re-apply pause if needed
        if was_paused:
            renpy.music.set_pause(True, channel=ch)

        # Update loop tracking
        global _sfx_editor__last_pos
        _sfx_editor__last_pos = new_time


    def _sfx_editor_coarse_seek(delta_seconds):
        """Jump forward or backward by a larger time amount."""
        ch = _sfx_editor_active_channel
        if not ch:
            return

        pos = renpy.music.get_pos(channel=ch)
        if pos is None:
            return

        filepath = renpy.music.get_playing(channel=ch)
        if filepath is None:
            return

        dur = renpy.music.get_duration(channel=ch)
        if dur is None or dur <= 0:
            return

        new_time = pos + delta_seconds
        new_time = max(0.0, min(new_time, dur - 0.05))

        was_paused = _sfx_editor_paused or renpy.music.get_pause(channel=ch)

        renpy.music.stop(channel=ch, fadeout=0)
        seek_path = "<from {:.3f}>{}".format(new_time, filepath)
        renpy.music.play(seek_path, channel=ch, loop=True)

        if was_paused:
            renpy.music.set_pause(True, channel=ch)

        global _sfx_editor__last_pos
        _sfx_editor__last_pos = new_time


    # --------------------------------------------------------------------------
    # Audio File Scanning
    # --------------------------------------------------------------------------

    def _sfx_editor_scan_audio():
        """Scan the audio directory for compatible SFX files."""
        global _sfx_editor_available_files, _sfx_editor_scan_error

        search_path = _sfx_editor_audio_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        audio_exts = (".ogg", ".mp3", ".wav", ".opus", ".flac")

        try:
            all_files = renpy.list_files()
        except Exception:
            _sfx_editor_available_files = []
            _sfx_editor_scan_error = "Failed to list files"
            return

        results = []
        for f in all_files:
            if f.startswith(search_path):
                # Only top-level files in the directory
                relative = f[len(search_path):]
                if "/" not in relative and f.lower().endswith(audio_exts):
                    results.append(relative)

        results.sort()
        _sfx_editor_available_files = results
        if not results:
            _sfx_editor_scan_error = "No audio files found in: {}".format(
                _sfx_editor_audio_dir
            )
        else:
            _sfx_editor_scan_error = None


    def _sfx_editor_change_audio_dir(new_path):
        """Change the audio directory and rescan."""
        global _sfx_editor_audio_dir
        new_path = new_path.strip()
        if new_path:
            _sfx_editor_audio_dir = new_path
            _sfx_editor_scan_audio()
            _sfx_editor_save_config()


    # --------------------------------------------------------------------------
    # SFX Playback
    # --------------------------------------------------------------------------

    def _sfx_editor_play_sfx(filename):
        """Play an SFX on the next available dedicated channel.

        Uses round-robin across 8 channels to allow overlapping sounds.
        If all channels are busy, reuses the oldest channel.
        """
        global _sfx_editor__sfx_channel_idx

        base_dir = _sfx_editor_audio_dir
        if not base_dir.endswith("/"):
            base_dir = base_dir + "/"
        full_path = base_dir + filename

        # Find first idle channel
        target_ch = None
        for i in range(1, 9):
            ch_name = "_sfx_{}".format(i)
            if not renpy.music.is_playing(channel=ch_name):
                target_ch = ch_name
                break

        if target_ch is None:
            # All busy: round-robin (oldest gets cut off)
            idx = _sfx_editor__sfx_channel_idx
            target_ch = "_sfx_{}".format(idx + 1)
            _sfx_editor__sfx_channel_idx = (idx + 1) % 8
        else:
            # Update round-robin index past this channel
            ch_num = int(target_ch.split("_")[-1])
            _sfx_editor__sfx_channel_idx = ch_num % 8

        try:
            renpy.music.play(full_path, channel=target_ch, loop=False)
        except Exception:
            pass


    # --------------------------------------------------------------------------
    # Manual Marker Management
    # --------------------------------------------------------------------------

    def _sfx_editor_cycle_file(delta):
        """Cycle the selected file index for marker placement."""
        global _sfx_editor_selected_file_index
        if not _sfx_editor_available_files:
            _sfx_editor_selected_file_index = 0
            return
        count = len(_sfx_editor_available_files)
        _sfx_editor_selected_file_index = (
            _sfx_editor_selected_file_index + delta
        ) % count


    def _sfx_editor_get_selected_filename():
        """Get the currently selected audio filename."""
        if not _sfx_editor_available_files:
            return "(no files)"
        idx = _sfx_editor_selected_file_index
        if 0 <= idx < len(_sfx_editor_available_files):
            return _sfx_editor_available_files[idx]
        return "(no files)"


    def _sfx_editor_add_marker(file_index=None):
        """Add a marker at the current video time with the selected SFX file."""
        global _sfx_editor_markers

        if not _sfx_editor_available_files:
            return

        if file_index is None:
            file_index = _sfx_editor_selected_file_index

        if file_index < 0 or file_index >= len(_sfx_editor_available_files):
            file_index = 0

        elapsed = _sfx_editor_get_elapsed()
        if elapsed is None or elapsed < 0:
            return

        filename = _sfx_editor_available_files[file_index]
        marker = {"time": elapsed, "file": filename}
        _sfx_editor_markers.append(marker)
        # Keep sorted by time
        _sfx_editor_markers.sort(key=lambda m: m["time"])
        _sfx_editor_save_config()


    def _sfx_editor_remove_marker(index):
        """Remove a marker at the given list index."""
        global _sfx_editor_markers
        if 0 <= index < len(_sfx_editor_markers):
            _sfx_editor_markers.pop(index)
            global _sfx_editor_played_markers
            _sfx_editor_played_markers = set(
                i if i < index else i - 1
                for i in _sfx_editor_played_markers
                if i != index
            )
            _sfx_editor_save_config()


    def _sfx_editor_clear_all_markers():
        """Remove all markers."""
        global _sfx_editor_markers, _sfx_editor_played_markers
        _sfx_editor_markers = []
        _sfx_editor_played_markers = set()
        _sfx_editor_save_config()


    # --------------------------------------------------------------------------
    # Pool Management
    # --------------------------------------------------------------------------

    def _sfx_editor_add_to_pool(file_index):
        """Add an audio file to the SFX pool."""
        global _sfx_editor_pool_files
        if 0 <= file_index < len(_sfx_editor_available_files):
            filename = _sfx_editor_available_files[file_index]
            if filename not in _sfx_editor_pool_files:
                _sfx_editor_pool_files.append(filename)
                _sfx_editor_save_config()


    def _sfx_editor_remove_from_pool(index):
        """Remove a file from the pool by index."""
        global _sfx_editor_pool_files
        if 0 <= index < len(_sfx_editor_pool_files):
            _sfx_editor_pool_files.pop(index)
            _sfx_editor_save_config()


    def _sfx_editor_start_pool():
        """Start the random pool SFX playback."""
        global _sfx_editor_pool_enabled, _sfx_editor_next_pool_time
        if not _sfx_editor_pool_files:
            return
        import random
        _sfx_editor_pool_enabled = True
        elapsed = _sfx_editor_get_elapsed()
        if elapsed > 0:
            _sfx_editor_next_pool_time = elapsed + random.uniform(
                _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
            )
        _sfx_editor_save_config()


    def _sfx_editor_stop_pool():
        """Stop the random pool SFX playback."""
        global _sfx_editor_pool_enabled
        _sfx_editor_pool_enabled = False
        _sfx_editor_save_config()


    def _sfx_editor_set_pool_delay(field, value_str):
        """Set pool min or max delay from a string input."""
        global _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
        global _sfx_editor_pool_min_str, _sfx_editor_pool_max_str
        try:
            value = float(value_str)
            if value < 0.1:
                value = 0.1
            if field == "min":
                _sfx_editor_pool_min_delay = value
                _sfx_editor_pool_min_str = "{:.1f}".format(value)
                if _sfx_editor_pool_max_delay < value:
                    _sfx_editor_pool_max_delay = value + 0.1
                    _sfx_editor_pool_max_str = "{:.1f}".format(value + 0.1)
            elif field == "max":
                _sfx_editor_pool_max_delay = value
                _sfx_editor_pool_max_str = "{:.1f}".format(value)
                if _sfx_editor_pool_min_delay > value:
                    _sfx_editor_pool_min_delay = max(0.1, value - 0.1)
                    _sfx_editor_pool_min_str = "{:.1f}".format(
                        max(0.1, value - 0.1)
                    )
            _sfx_editor_save_config()
        except (ValueError, TypeError):
            # Restore from current values
            _sfx_editor_pool_min_str = "{:.1f}".format(_sfx_editor_pool_min_delay)
            _sfx_editor_pool_max_str = "{:.1f}".format(_sfx_editor_pool_max_delay)


    # --------------------------------------------------------------------------
    # SFX Trigger Engine (Tick)
    # --------------------------------------------------------------------------

    def _sfx_editor_tick():
        """Called ~10 times/sec by the overlay screen timer.

        Updates time display, checks markers, and drives pool mode.
        """
        global _sfx_editor_current_time_str, _sfx_editor_total_time_str
        global _sfx_editor_audio_count, _sfx_editor_marker_count, _sfx_editor_pool_count

        # Update display counts for screen text interpolation
        _sfx_editor_audio_count = len(_sfx_editor_available_files)
        _sfx_editor_marker_count = len(_sfx_editor_markers)
        _sfx_editor_pool_count = len(_sfx_editor_pool_files)

        if not _sfx_editor_visible:
            return

        ch = _sfx_editor_active_channel
        if not ch:
            return

        # Get elapsed time
        elapsed = _sfx_editor_get_elapsed()
        duration = _sfx_editor_get_duration()

        # Update time display strings
        _sfx_editor_current_time_str = _sfx_editor_format_time(elapsed)
        _sfx_editor_total_time_str = _sfx_editor_format_time(duration)

        # Update pause state from the channel
        global _sfx_editor_paused
        try:
            _sfx_editor_paused = renpy.music.get_pause(channel=ch)
        except Exception:
            pass

        # Detect video loop (position jumped backward significantly)
        if _sfx_editor__last_pos > 0 and elapsed < _sfx_editor__last_pos - 0.3:
            # Video looped — reset played markers and pool schedule
            _sfx_editor_played_markers.clear()
            if _sfx_editor_pool_enabled:
                import random
                _sfx_editor_next_pool_time = elapsed + random.uniform(
                    _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
                )
        _sfx_editor__last_pos = elapsed

        # Mode-specific logic
        if _sfx_editor_mode == "manual":
            _sfx_editor_tick_manual(elapsed)
        elif _sfx_editor_mode == "pool":
            _sfx_editor_tick_pool(elapsed)


    def _sfx_editor_tick_manual(elapsed):
        """Check manual markers and trigger SFX if elapsed time is reached."""
        for idx, marker in enumerate(_sfx_editor_markers):
            if idx in _sfx_editor_played_markers:
                continue
            marker_time = marker["time"]
            # Trigger when we pass the marker time (within tolerance)
            if marker_time <= elapsed < marker_time + _sfx_editor__marker_tolerance:
                _sfx_editor_play_sfx(marker["file"])
                _sfx_editor_played_markers.add(idx)
            elif elapsed >= marker_time + _sfx_editor__marker_tolerance:
                # We overshot (e.g., due to seeking) — trigger anyway
                _sfx_editor_play_sfx(marker["file"])
                _sfx_editor_played_markers.add(idx)


    def _sfx_editor_tick_pool(elapsed):
        """Check pool schedule and trigger random SFX."""
        if not _sfx_editor_pool_enabled:
            return
        if not _sfx_editor_pool_files:
            return

        npt = _sfx_editor_next_pool_time
        if npt > 0 and elapsed >= npt:
            import random
            choice = random.choice(_sfx_editor_pool_files)
            _sfx_editor_play_sfx(choice)

            delay = random.uniform(
                _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
            )
            global _sfx_editor_next_pool_time
            _sfx_editor_next_pool_time = elapsed + delay


    # --------------------------------------------------------------------------
    # Persistence
    # --------------------------------------------------------------------------

    def _sfx_editor_save_config():
        """Save current configuration to persistent storage."""
        video_path = _sfx_editor_get_video_path()
        video_key = video_path if video_path else "__no_video__"

        # Load existing markers dict to preserve other videos' markers
        existing = getattr(persistent, '_sfx_editor_config', None)
        if existing is None:
            existing_markers = {}
        else:
            existing_markers = existing.get("markers_per_video", {})

        # Update markers for the current video
        if _sfx_editor_markers:
            existing_markers[video_key] = list(_sfx_editor_markers)
        elif video_key in existing_markers:
            # Don't clear on empty — user might want to keep them
            existing_markers[video_key] = []

        config = {
            "audio_dir": _sfx_editor_audio_dir,
            "mode": _sfx_editor_mode,
            "pool_files": list(_sfx_editor_pool_files),
            "pool_min_delay": _sfx_editor_pool_min_delay,
            "pool_max_delay": _sfx_editor_pool_max_delay,
            "pool_enabled": _sfx_editor_pool_enabled,
            "last_channel": _sfx_editor_active_channel,
            "markers_per_video": existing_markers,
            "version": _sfx_editor_version,
        }

        persistent._sfx_editor_config = config


    def _sfx_editor_load_config():
        """Load configuration from persistent storage."""
        config = getattr(persistent, '_sfx_editor_config', None)
        if config is None:
            return

        global _sfx_editor_audio_dir, _sfx_editor_mode
        global _sfx_editor_pool_files, _sfx_editor_pool_min_delay
        global _sfx_editor_pool_max_delay, _sfx_editor_pool_enabled
        global _sfx_editor_active_channel, _sfx_editor_markers

        _sfx_editor_audio_dir = config.get("audio_dir", "sfx_editor/audio")
        _sfx_editor_mode = config.get("mode", "manual")
        _sfx_editor_pool_files = config.get("pool_files", [])
        _sfx_editor_pool_min_delay = config.get("pool_min_delay", 2.0)
        _sfx_editor_pool_max_delay = config.get("pool_max_delay", 8.0)
        _sfx_editor_pool_enabled = config.get("pool_enabled", False)
        _sfx_editor_active_channel = config.get("last_channel", None)

        # Load markers for current video
        video_path = _sfx_editor_get_video_path()
        video_key = video_path if video_path else "__no_video__"
        markers_dict = config.get("markers_per_video", {})
        if video_key in markers_dict:
            _sfx_editor_markers = list(markers_dict[video_key])
        else:
            _sfx_editor_markers = []


    # --------------------------------------------------------------------------
    # Utility: Time Formatting
    # --------------------------------------------------------------------------

    def _sfx_editor_format_time(seconds):
        """Format seconds as MM:SS.cs (centiseconds).

        For durations >= 60 min: HH:MM:SS.cs
        """
        if seconds is None or seconds < 0:
            return "00:00.00"

        total_sec = int(seconds)
        centiseconds = int((seconds - total_sec) * 100)
        minutes = total_sec // 60
        sec_remainder = total_sec % 60

        if minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
            return "{:02d}:{:02d}:{:02d}.{:02d}".format(
                hours, minutes, sec_remainder, centiseconds
            )
        else:
            return "{:02d}:{:02d}.{:02d}".format(
                minutes, sec_remainder, centiseconds
            )


###############################################################################
# SECTION 4: Styles
###############################################################################

style sfx_editor_frame:
    background "#000000dd"
    padding (10, 6)
    xfill True

style sfx_editor_button:
    size_group "sfx_btn"
    xysize (36, 28)

style sfx_editor_button_text:
    size 13
    color "#cccccc"
    hover_color "#ffffff"

style sfx_editor_small_button:
    xysize (22, 22)

style sfx_editor_small_button_text:
    size 11
    color "#cccccc"
    hover_color "#ff6666"

style sfx_editor_text:
    size 13
    color "#cccccc"

style sfx_editor_header:
    size 14
    color "#ffcc00"
    bold True

style sfx_editor_help:
    size 11
    color "#888888"

style sfx_editor_input:
    size 13
    color "#ffffff"
    xysize (120, 24)


###############################################################################
# SECTION 5: Overlay Screen
###############################################################################

# =============================================================================
# KEY-LISTENER SCREEN: Always-visible invisible screen that catches backtick
# =============================================================================

screen sfx_editor_key_listener():
    zorder 10000
    key "K_BACKQUOTE" action Function(_sfx_editor_toggle)


# =============================================================================
# MAIN OVERLAY SCREEN
# =============================================================================

screen sfx_editor_overlay():

    zorder 9999
    modal False
    tag sfx_editor

    # Screen-level key bindings
    key "K_SPACE" action Function(_sfx_editor_toggle_pause)
    key "K_LEFT" action Function(_sfx_editor_seek_frame, -1)
    key "K_RIGHT" action Function(_sfx_editor_seek_frame, 1)
    key "K_UP" action Function(_sfx_editor_coarse_seek, 1.0)
    key "K_DOWN" action Function(_sfx_editor_coarse_seek, -1.0)
    # Timer to drive the SFX trigger engine
    timer 0.1 repeat True action Function(_sfx_editor_tick)

    # Main panel — docked at bottom of screen
    frame:
        style "sfx_editor_frame"
        xalign 0.5
        yalign 1.0
        xfill True
        ymaximum 280

        vbox:
            spacing 4

            # ================================================================
            # ROW 1: Controls Bar
            # ================================================================
            hbox:
                spacing 6

                # Channel status & refresh
                text "[_sfx_editor_channel_status]" style "sfx_editor_text" minwidth 120

                textbutton "⟳":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_refresh_channel)
                    tooltip "Refresh / auto-detect channel"

                null width 6

                # Pause / Play
                if _sfx_editor_paused:
                    textbutton "▶":
                        style "sfx_editor_button"
                        text_style "sfx_editor_button_text"
                        action Function(_sfx_editor_toggle_pause)
                        tooltip "Resume video"
                else:
                    textbutton "⏸":
                        style "sfx_editor_button"
                        text_style "sfx_editor_button_text"
                        action Function(_sfx_editor_toggle_pause)
                        tooltip "Pause video"

                # Frame step buttons
                textbutton "⏮":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_coarse_seek, -1.0)
                    tooltip "Jump back 1 second"

                textbutton "-1f":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_seek_frame, -1)
                    tooltip "Step back 1 frame"

                textbutton "+1f":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_seek_frame, 1)
                    tooltip "Step forward 1 frame"

                textbutton "⏭":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_coarse_seek, 1.0)
                    tooltip "Jump forward 1 second"

                null width 6

                # Time display
                text "[_sfx_editor_current_time_str] / [_sfx_editor_total_time_str]" style "sfx_editor_text"

                null width 6

                # Mode switcher
                if _sfx_editor_mode == "manual":
                    textbutton "Manual":
                        style "sfx_editor_button"
                        text_style "sfx_editor_header"
                        action NullAction()
                    textbutton "Pool":
                        style "sfx_editor_button"
                        text_style "sfx_editor_button_text"
                        action [
                            SetField(store, "_sfx_editor_mode", "pool"),
                            Function(_sfx_editor_save_config),
                        ]
                else:
                    textbutton "Manual":
                        style "sfx_editor_button"
                        text_style "sfx_editor_button_text"
                        action [
                            SetField(store, "_sfx_editor_mode", "manual"),
                            Function(_sfx_editor_stop_pool),
                            Function(_sfx_editor_save_config),
                        ]
                    textbutton "Pool":
                        style "sfx_editor_button"
                        text_style "sfx_editor_header"
                        action NullAction()

                null width 6

                # Save
                textbutton "💾":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_save_config)
                    tooltip "Save configuration"

                # Close
                textbutton "✕":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_hide)
                    tooltip "Close overlay (`)"

            # ================================================================
            # ROW 2: Mode-specific content
            # ================================================================

            if _sfx_editor_mode == "manual":
                use sfx_editor_manual_panel()
            else:
                use sfx_editor_pool_panel()

            # ================================================================
            # ROW 3: Audio directory config
            # ================================================================
            hbox:
                spacing 4
                text "Audio dir:" style "sfx_editor_text"

                input:
                    style "sfx_editor_input"
                    value FieldInputValue(store, "_sfx_editor_audio_dir", default=False)

                textbutton "↻ Scan":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action [
                        Function(_sfx_editor_change_audio_dir, _sfx_editor_audio_dir),
                    ]
                    tooltip "Rescan audio directory"

                if _sfx_editor_scan_error:
                    text "[_sfx_editor_scan_error]" style "sfx_editor_help" color "#ff6666"
                else:
                    text "([_sfx_editor_audio_count] files)" style "sfx_editor_text"

            # ================================================================
            # ROW 4: Channel manual input + help
            # ================================================================
            hbox:
                spacing 4
                text "Channel:" style "sfx_editor_text"

                input:
                    style "sfx_editor_input"
                    value FieldInputValue(store, "_sfx_editor_manual_channel_input", default=False)

                textbutton "Set":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(
                        _sfx_editor_set_channel_manual,
                        _sfx_editor_manual_channel_input
                    )

                text "` toggle | Space pause | ← → frame step | ↑↓ ±1s" style "sfx_editor_help"


# =============================================================================
# SUB-SCREEN: Manual Mode Panel
# =============================================================================

screen sfx_editor_manual_panel():
    vbox:
        spacing 3

        # Marker list header
        hbox:
            spacing 4
            text "Markers:" style "sfx_editor_header"
            text "([_sfx_editor_marker_count])" style "sfx_editor_text"

        # Marker list (scrollable if needed)
        if _sfx_editor_markers:
            viewport:
                scrollbars "horizontal"
                xfill True
                ymaximum 60
                mousewheel True

                hbox:
                    spacing 4
                    box_wrap False

                    for i, marker in enumerate(_sfx_editor_markers):
                        frame:
                            background "#333333aa"
                            padding (4, 2)
                            xysize (180, 50)

                            vbox:
                                spacing 1

                                hbox:
                                    text _sfx_editor_format_time(marker["time"]) style "sfx_editor_text" size 13
                                    null width 4
                                    textbutton "✕":
                                        style "sfx_editor_small_button"
                                        text_style "sfx_editor_small_button_text"
                                        action Function(_sfx_editor_remove_marker, i)
                                        tooltip "Remove this marker"

                                text marker["file"] style "sfx_editor_text" size 11 color "#ffcc00"
        else:
            text "(No markers yet — pause video, pick a file, and add a marker)" style "sfx_editor_help"

        # Add marker controls
        hbox:
            spacing 4
            textbutton "Add Marker":
                style "sfx_editor_button"
                text_style "sfx_editor_button_text"
                action Function(_sfx_editor_add_marker, None)
                tooltip "Add a marker at the current video time"

            if _sfx_editor_available_files:
                textbutton "◀":
                    style "sfx_editor_small_button"
                    text_style "sfx_editor_small_button_text"
                    action Function(_sfx_editor_cycle_file, -1)
                    tooltip "Previous file"

                textbutton _sfx_editor_get_selected_filename():
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action NullAction()
                    tooltip "File to use for the next marker"

                textbutton "▶":
                    style "sfx_editor_small_button"
                    text_style "sfx_editor_small_button_text"
                    action Function(_sfx_editor_cycle_file, 1)
                    tooltip "Next file"

            if _sfx_editor_markers:
                textbutton "Clear All":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_clear_all_markers)
                    tooltip "Remove all markers"


# =============================================================================
# SUB-SCREEN: Pool Mode Panel
# =============================================================================

screen sfx_editor_pool_panel():
    vbox:
        spacing 3

        # Pool file list
        hbox:
            spacing 4
            text "Pool files:" style "sfx_editor_header"
            text "([_sfx_editor_pool_count])" style "sfx_editor_text"

        if _sfx_editor_pool_files:
            viewport:
                scrollbars "horizontal"
                xfill True
                ymaximum 50
                mousewheel True

                hbox:
                    spacing 4
                    box_wrap False

                    for i, filename in enumerate(_sfx_editor_pool_files):
                        frame:
                            background "#333333aa"
                            padding (6, 3)

                            hbox:
                                spacing 3
                                text filename style "sfx_editor_text" size 13 color "#ffcc00"
                                textbutton "✕":
                                    style "sfx_editor_small_button"
                                    text_style "sfx_editor_small_button_text"
                                    action Function(_sfx_editor_remove_from_pool, i)
                                    tooltip "Remove from pool"
        else:
            text "(No files in pool — add files below)" style "sfx_editor_help"

        # Pool delay settings
        hbox:
            spacing 4
            text "Min delay (s):" style "sfx_editor_text"
            input:
                style "sfx_editor_input"
                value FieldInputValue(store, "_sfx_editor_pool_min_str", default=False)
            textbutton "Set":
                style "sfx_editor_small_button"
                text_style "sfx_editor_small_button_text"
                action Function(_sfx_editor_set_pool_delay, "min", _sfx_editor_pool_min_str)

            null width 10

            text "Max delay (s):" style "sfx_editor_text"
            input:
                style "sfx_editor_input"
                value FieldInputValue(store, "_sfx_editor_pool_max_str", default=False)
            textbutton "Set":
                style "sfx_editor_small_button"
                text_style "sfx_editor_small_button_text"
                action Function(_sfx_editor_set_pool_delay, "max", _sfx_editor_pool_max_str)

        # Pool controls
        hbox:
            spacing 4

            # Add file to pool
            if _sfx_editor_available_files:
                text "Add file:" style "sfx_editor_text"
                # Show first 10 available files as buttons
                for j, afile in enumerate(_sfx_editor_available_files):
                    if j >= 8:
                        textbutton "...":
                            style "sfx_editor_small_button"
                            text_style "sfx_editor_small_button_text"
                            action NullAction()
                        break
                    if afile not in _sfx_editor_pool_files:
                        textbutton afile:
                            style "sfx_editor_small_button"
                            text_style "sfx_editor_small_button_text"
                            action Function(_sfx_editor_add_to_pool, j)
                            tooltip "Add [afile] to pool"

            null width 10

            # Start / Stop pool
            if _sfx_editor_pool_enabled:
                textbutton "⏹ Stop Pool":
                    style "sfx_editor_button"
                    text_style "sfx_editor_button_text"
                    action Function(_sfx_editor_stop_pool)
                    tooltip "Stop the random SFX pool"
            else:
                if _sfx_editor_pool_files:
                    textbutton "▶ Start Pool":
                        style "sfx_editor_button"
                        text_style "sfx_editor_button_text"
                        action Function(_sfx_editor_start_pool)
                        tooltip "Start playing random SFX from the pool"
                else:
                    textbutton "▶ Start Pool":
                        style "sfx_editor_button"
                        text_style "sfx_editor_button_text"
                        action NullAction()
                        tooltip "Add files to the pool first"
