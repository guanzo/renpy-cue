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
    _sfx_editor_available_files = []  # flat list of all file paths
    _sfx_editor_audio_tree = []       # tree: [{type, name, children?, expanded?}]
    _sfx_editor_expanded_folders = {} # folder_name -> bool
    _sfx_editor_visible_tree = []     # pre-computed flat list for rendering
    _sfx_editor_current_time_str = "--:--.--"
    _sfx_editor_total_time_str = "--:--.--"
    _sfx_editor_current_frame_str = "---"
    _sfx_editor_total_frame_str = "---"
    _sfx_editor_fps = 30
    _sfx_editor_paused = False
    _sfx_editor_scan_error = None
    _sfx_editor_channel_status = "No video"
    _sfx_editor_initialized = False
    _sfx_editor_selected_file_index = 0
    _sfx_editor_manual_channel_input = ""

    # Image + dialogue mode
    _sfx_editor_current_image = ""
    _sfx_editor_current_dialogue = ""
    _sfx_editor_image_markers = []
    _sfx_editor_last_marker_key = ""
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
    _sfx_editor__time_offset = 0.0
    _sfx_editor__step_target = 0.0
    _sfx_editor__pause_target = 0.0
    _sfx_editor__pause_origin = 0.0
    _sfx_editor__total_offset = 0.0
    _sfx_editor__redetect_tick = 0
    _sfx_editor__refreshing = False


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

        # Character callback for dialogue detection
        def _sfx_editor_char_callback(event, interact=True, **kwargs):
            global _sfx_editor_current_dialogue, _sfx_editor_current_image
            if event == "show":
                text = getattr(store, '_last_say_what', '') or ''
                _sfx_editor_current_dialogue = text
                _sfx_editor_current_image = _sfx_editor_get_showing_image()
                # Dialogue started — also re-check video
                if _sfx_editor_active_channel is None or not renpy.music.is_playing(channel=_sfx_editor_active_channel):
                    _sfx_editor_refresh_channel()
            elif event == "end":
                # Dialogue ended — clear after a short delay so tick can re-check
                _sfx_editor_current_dialogue = ""
        config.all_character_callbacks.append(_sfx_editor_char_callback)

        # Lightweight channel re-check every tick when no video is active
        # (dialogue is instant via character callback; video has no on-show hook)
        _sfx_editor_log("INIT: callbacks registered")

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
        if _sfx_editor_visible:
            _sfx_editor_hide()
        else:
            _sfx_editor_show()



    def _sfx_editor_show():
        import time
        t0 = time.time()
        global _sfx_editor_visible, _sfx_editor_active_channel
        global _sfx_editor_manual_channel_input
        global _sfx_editor_pool_min_str, _sfx_editor_pool_max_str
        _sfx_editor_visible = True
        _sfx_editor_log("show: start")
        # Load persisted config
        _sfx_editor_load_config()
        _sfx_editor_log("show: load_config took {:.3f}s".format(time.time() - t0))
        # Initialize string fields from current values
        _sfx_editor_manual_channel_input = (
            _sfx_editor_active_channel if _sfx_editor_active_channel else ""
        )
        _sfx_editor_pool_min_str = "{:.1f}".format(_sfx_editor_pool_min_delay)
        _sfx_editor_pool_max_str = "{:.1f}".format(_sfx_editor_pool_max_delay)
        # Scan audio on first open (cached thereafter)
        if not _sfx_editor_available_files:
            _sfx_editor_scan_audio()
            _sfx_editor_log("show: scan_audio took {:.3f}s".format(time.time() - t0))
        # Rebuild visible tree
        global _sfx_editor_visible_tree
        _sfx_editor_visible_tree = _sfx_editor_get_visible_tree()
        # Auto-detect channel
        _sfx_editor_refresh_channel()
        _sfx_editor_log("show: refresh_channel took {:.3f}s".format(time.time() - t0))
        # Update channel input after detection
        _sfx_editor_manual_channel_input = (
            _sfx_editor_active_channel if _sfx_editor_active_channel else ""
        )
        # Show the overlay screen
        renpy.show_screen("sfx_editor_overlay", _layer="sfx_editor_layer")
        _sfx_editor_log("show: show_screen took {:.3f}s".format(time.time() - t0))
        renpy.restart_interaction()
        _sfx_editor_log("show: restart_interaction took {:.3f}s".format(time.time() - t0))


    def _sfx_editor_hide():
        global _sfx_editor_visible
        _sfx_editor_visible = False
        # Save config on close
        _sfx_editor_save_config()
        renpy.hide_screen("sfx_editor_overlay", layer="sfx_editor_layer")


    def _sfx_editor_redetect_dialogue():
        """Manually re-detect current image and dialogue."""
        global _sfx_editor_current_dialogue, _sfx_editor_current_image
        _sfx_editor_current_dialogue = getattr(store, '_last_say_what', '') or ''
        _sfx_editor_current_image = _sfx_editor_get_showing_image()


    # --------------------------------------------------------------------------
    # Image Detection
    # --------------------------------------------------------------------------

    def _sfx_editor_get_showing_image():
        """Get the currently shown image tag name."""
        try:
            tags = renpy.get_showing_tags(layer="master")
            if tags:
                return list(tags)[0]
        except Exception:
            pass
        return ""


    # --------------------------------------------------------------------------
    # Channel Detection
    # --------------------------------------------------------------------------

    def _sfx_editor_refresh_channel():
        """Auto-detect the active movie channel. Only finds video (movie) channels."""
        global _sfx_editor_active_channel, _sfx_editor_channel_status
        global _sfx_editor_fps, _sfx_editor__frame_time
        global _sfx_editor__refreshing

        if _sfx_editor__refreshing:
            return
        _sfx_editor__refreshing = True

        try:
            video_exts = (".webm", ".mp4", ".mkv", ".avi", ".ogv", ".mpeg", ".mpg")
            old_ch = _sfx_editor_active_channel

            def _apply_channel(ch_name, ch_obj=None):
                global _sfx_editor_active_channel, _sfx_editor_channel_status
                global _sfx_editor_fps, _sfx_editor__frame_time
                path = renpy.music.get_playing(channel=ch_name)
                dur = renpy.music.get_duration(channel=ch_name)
                fname = path.replace("\\", "/").rsplit("/", 1)[-1]

                fps = 30
                if ch_obj is not None:
                    for attr in ('framerate', 'fps', 'frame_rate'):
                        try:
                            val = getattr(ch_obj, attr, None)
                            if callable(val):
                                val = val()
                            if val and val > 0:
                                fps = int(round(val))
                                break
                        except Exception:
                            pass
                _sfx_editor_fps = fps
                _sfx_editor__frame_time = 1.0 / fps

                _sfx_editor_active_channel = ch_name
                _sfx_editor_channel_status = "{} | {} ({}fps)".format(ch_name, fname, fps)
                _sfx_editor_reset_loop_tracking()

            try:
                import renpy.audio.audio as aaudio
                for ch_name in aaudio.channels:
                    try:
                        ch = aaudio.channels.get(ch_name)
                        if ch is None or not getattr(ch, 'movie', False):
                            continue
                        if renpy.music.is_playing(channel=ch_name):
                            path = renpy.music.get_playing(channel=ch_name)
                            dur = renpy.music.get_duration(channel=ch_name)
                            if path and dur > 0:
                                _apply_channel(ch_name, ch)
                                if old_ch is None:
                                    renpy.restart_interaction()
                                _sfx_editor__refreshing = False
                                return
                    except Exception:
                        pass
            except Exception:
                pass

            for ch in ["movie", "_movie_1", "_movie_2"]:
                try:
                    path = renpy.music.get_playing(channel=ch)
                    if path and path.lower().endswith(video_exts):
                        _apply_channel(ch, None)
                        if old_ch is None:
                            renpy.restart_interaction()
                        _sfx_editor__refreshing = False
                        return
                except Exception:
                    pass

            _sfx_editor_active_channel = None
            _sfx_editor_channel_status = "No video detected"
        finally:
            _sfx_editor__refreshing = False


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
        """Get current playback position (real pos + virtual offset)."""
        ch = _sfx_editor_active_channel
        if not ch:
            return 0.0
        try:
            pos = renpy.music.get_pos(channel=ch)
            if pos is not None:
                return max(0.0, pos + _sfx_editor__time_offset)
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
        global _sfx_editor_paused, _sfx_editor__time_offset
        global _sfx_editor__pause_origin, _sfx_editor__total_offset
        ch = _sfx_editor_active_channel
        if not ch:
            return

        _sfx_editor__time_offset = 0.0

        try:
            currently_paused = renpy.music.get_pause(channel=ch)
            new_state = not currently_paused
            renpy.music.set_pause(new_state, channel=ch)
            _sfx_editor_paused = new_state

            if new_state:  # Just paused — save origin
                _sfx_editor__pause_origin = renpy.music.get_pos(channel=ch) or 0.0
                _sfx_editor__total_offset = 0.0
                _sfx_editor_log("pause: origin={:.3f}".format(_sfx_editor__pause_origin))
            else:  # Just unpaused
                _sfx_editor__total_offset = 0.0
                _sfx_editor_log("unpause: reset offset")
        except Exception:
            # Fallback: use volume as pseudo-pause
            if not _sfx_editor_paused:
                renpy.music.set_volume(0.0, delay=0, channel=ch)
                _sfx_editor_paused = True
            else:
                renpy.music.set_volume(1.0, delay=0, channel=ch)
                _sfx_editor_paused = False


    # --------------------------------------------------------------------------
    # Video Control: Frame Step (virtual offset — seeking doesn't work on
    # Ren'Py movie channels, so we use a time offset for display/markers)
    # --------------------------------------------------------------------------

    def _sfx_editor_seek_frame(delta_frames):
        """Step forward/backward.
        Forward: briefly unpause, auto-re-pause via tick timer.
        Backward: restart from 0, auto-pause at origin + accumulated offset."""
        global _sfx_editor__time_offset, _sfx_editor__step_target
        global _sfx_editor__pause_target, _sfx_editor__total_offset
        ch = _sfx_editor_active_channel
        if not ch:
            return

        frame_seconds = _sfx_editor__frame_time

        # Auto-pause if video is playing
        if not _sfx_editor_paused:
            renpy.music.set_pause(True, channel=ch)
            _sfx_editor_paused = True
            _sfx_editor__pause_origin = renpy.music.get_pos(channel=ch) or 0.0
            _sfx_editor__total_offset = 0.0
            _sfx_editor__time_offset = 0.0

        if delta_frames > 0:
            pos = renpy.music.get_pos(channel=ch) or 0.0
            _sfx_editor__step_target = pos + delta_frames * frame_seconds
            _sfx_editor_log("+f step_target={:.3f}".format(_sfx_editor__step_target))
            renpy.music.set_pause(False, channel=ch)

        else:  # delta_frames < 0
            _sfx_editor__total_offset += delta_frames * frame_seconds
            dur = renpy.music.get_duration(channel=ch) or 0.0
            origin = _sfx_editor__pause_origin
            target = origin + _sfx_editor__total_offset
            if target < 0:
                target = dur + target
            target = max(0.0, min(target, dur - 0.05))

            filepath = renpy.music.get_playing(channel=ch)
            _sfx_editor_log(
                "-f origin={:.3f} total_offset={:.3f} target={:.3f} dur={:.3f}"
                .format(origin, _sfx_editor__total_offset, target, dur)
            )
            if filepath and dur > 0:
                _sfx_editor__pause_target = target
                renpy.music.stop(channel=ch, fadeout=0)
                renpy.music.play(filepath, channel=ch, loop=True)


    def _sfx_editor_coarse_seek(delta_seconds):
        """Jump forward/backward. Auto-pauses if playing."""
        global _sfx_editor__time_offset, _sfx_editor__step_target
        global _sfx_editor__pause_target, _sfx_editor__total_offset
        ch = _sfx_editor_active_channel
        if not ch:
            return

        # Auto-pause if playing
        if not _sfx_editor_paused:
            renpy.music.set_pause(True, channel=ch)
            _sfx_editor_paused = True
            _sfx_editor__pause_origin = renpy.music.get_pos(channel=ch) or 0.0
            _sfx_editor__total_offset = 0.0
            _sfx_editor__time_offset = 0.0

        if delta_seconds > 0:
            pos = renpy.music.get_pos(channel=ch) or 0.0
            _sfx_editor__step_target = pos + delta_seconds
            _sfx_editor_log("+coarse step_target={:.3f}".format(_sfx_editor__step_target))
            renpy.music.set_pause(False, channel=ch)
        else:
            _sfx_editor__total_offset += delta_seconds
            dur = renpy.music.get_duration(channel=ch) or 0.0
            origin = _sfx_editor__pause_origin
            target = origin + _sfx_editor__total_offset
            if target < 0:
                target = dur + target
            target = max(0.0, min(target, dur - 0.05))

            filepath = renpy.music.get_playing(channel=ch)
            _sfx_editor_log(
                "-coarse origin={:.3f} total_offset={:.3f} target={:.3f}"
                .format(origin, _sfx_editor__total_offset, target)
            )
            if filepath and dur > 0:
                _sfx_editor__pause_target = target
                renpy.music.stop(channel=ch, fadeout=0)
                renpy.music.play(filepath, channel=ch, loop=True)


    # --------------------------------------------------------------------------
    # Audio File Scanning
    # --------------------------------------------------------------------------

    def _sfx_editor_scan_audio():
        """Scan audio dir and build folder tree."""
        global _sfx_editor_available_files, _sfx_editor_scan_error
        global _sfx_editor_audio_tree

        search_path = _sfx_editor_audio_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        audio_exts = (".ogg", ".mp3", ".wav", ".opus", ".flac")

        try:
            all_files = renpy.list_files()
        except Exception:
            _sfx_editor_available_files = []
            _sfx_editor_audio_tree = []
            _sfx_editor_scan_error = "Failed to list files"
            return

        # Build flat list of relative paths
        results = []
        for f in all_files:
            if f.startswith(search_path):
                relative = f[len(search_path):]
                if relative and f.lower().endswith(audio_exts):
                    results.append(relative)
        results.sort()
        _sfx_editor_available_files = results

        # Build tree from flat list
        root = {}
        for path in results:
            parts = path.split("/")
            node = root
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    # It's a file
                    node.setdefault("__files__", []).append(part)
                else:
                    # It's a folder
                    node = node.setdefault(part, {})

        # Convert to sorted tree list
        def _build_tree(node):
            items = []
            # Folders first
            for name in sorted(node.keys()):
                if name == "__files__":
                    continue
                items.append({
                    "type": "folder",
                    "name": name + "/",
                    "children": _build_tree(node[name]),
                    "expanded": False,
                })
            # Then files
            for name in sorted(node.get("__files__", [])):
                items.append({"type": "file", "name": name})
            return items

        _sfx_editor_audio_tree = _build_tree(root)

        if not results:
            _sfx_editor_scan_error = "No audio files found in: {}".format(
                _sfx_editor_audio_dir
            )
        else:
            _sfx_editor_scan_error = None

        # Rebuild visible tree for sidebar
        global _sfx_editor_visible_tree
        _sfx_editor_visible_tree = _sfx_editor_get_visible_tree()


    def _sfx_editor_add_folder_to_pool(folder_path):
        """Recursively add all files under a folder prefix to the pool."""
        global _sfx_editor_pool_files
        for f in _sfx_editor_available_files:
            if f.startswith(folder_path) and f not in _sfx_editor_pool_files:
                _sfx_editor_pool_files.append(f)
        _sfx_editor_save_config()


    def _sfx_editor_toggle_folder(folder_path):
        """Toggle expand/collapse for a folder in the audio tree."""
        global _sfx_editor_expanded_folders, _sfx_editor_visible_tree
        if folder_path in _sfx_editor_expanded_folders:
            _sfx_editor_expanded_folders[folder_path] = not _sfx_editor_expanded_folders[folder_path]
        else:
            _sfx_editor_expanded_folders[folder_path] = True
        _sfx_editor_visible_tree = _sfx_editor_get_visible_tree()
        renpy.restart_interaction()


    def _sfx_editor_get_visible_tree():
        """Return a flat list of visible tree items for rendering.
        Each item: {type, name, depth, full_path, index_in_flat_list}"""
        result = []
        _walk_tree(_sfx_editor_audio_tree, "", 0, result)
        return result


    def _walk_tree(items, prefix, depth, result):
        """Recursively walk tree, only descending into expanded folders."""
        for item in items:
            full = prefix + item["name"]
            if item["type"] == "folder":
                result.append({
                    "type": "folder",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "expanded": _sfx_editor_expanded_folders.get(full, False),
                })
                if _sfx_editor_expanded_folders.get(full, False):
                    _walk_tree(item.get("children", []), full, depth + 1, result)
            else:
                # Find index in flat list
                try:
                    idx = _sfx_editor_available_files.index(full)
                except ValueError:
                    idx = -1
                result.append({
                    "type": "file",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "index": idx,
                    "in_pool": full in _sfx_editor_pool_files,
                })


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

    def _sfx_editor_set_selected_file(index):
        """Set the selected file for marker placement by index."""
        global _sfx_editor_selected_file_index
        if 0 <= index < len(_sfx_editor_available_files):
            _sfx_editor_selected_file_index = index


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
        """Remove all markers (video + image)."""
        global _sfx_editor_markers, _sfx_editor_played_markers, _sfx_editor_image_markers
        _sfx_editor_markers = []
        _sfx_editor_played_markers = set()
        _sfx_editor_image_markers = []
        _sfx_editor_save_config()


    # --- Image/dialogue markers ---

    def _sfx_editor_add_image_marker(file_index=None):
        """Add a marker for the current image + dialogue + reveal step."""
        global _sfx_editor_image_markers
        if not _sfx_editor_available_files:
            return
        if file_index is None:
            file_index = _sfx_editor_selected_file_index
        if file_index < 0 or file_index >= len(_sfx_editor_available_files):
            file_index = 0
        filename = _sfx_editor_available_files[file_index]
        marker = {
            "image": _sfx_editor_current_image,
            "dialogue": _sfx_editor_current_dialogue,
            "file": filename,
        }
        _sfx_editor_image_markers.append(marker)
        _sfx_editor_save_config()


    def _sfx_editor_remove_image_marker(index):
        """Remove an image marker at the given list index."""
        global _sfx_editor_image_markers
        if 0 <= index < len(_sfx_editor_image_markers):
            _sfx_editor_image_markers.pop(index)
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
        import random as _random
        import time as _time
        global _sfx_editor_current_time_str, _sfx_editor_total_time_str
        global _sfx_editor_current_frame_str, _sfx_editor_total_frame_str
        global _sfx_editor_audio_count, _sfx_editor_marker_count, _sfx_editor_pool_count
        global _sfx_editor__step_target, _sfx_editor__pause_target

        ch = _sfx_editor_active_channel
        pos = renpy.music.get_pos(channel=ch) if ch else None

        # Auto-re-pause after backward seek (restart + play to target)
        if _sfx_editor__pause_target > 0 and pos is not None:
            if pos >= _sfx_editor__pause_target:
                renpy.music.set_pause(True, channel=ch)
                _sfx_editor__pause_target = 0.0
                _sfx_editor_paused = True
                _sfx_editor__time_offset = 0.0

        # Auto-re-pause after forward frame step
        if _sfx_editor__step_target > 0 and pos is not None:
            if pos >= _sfx_editor__step_target:
                renpy.music.set_pause(True, channel=ch)
                _sfx_editor__step_target = 0.0
                _sfx_editor_paused = True
                _sfx_editor__time_offset = 0.0

        # Update display counts for screen text interpolation
        _sfx_editor_audio_count = len(_sfx_editor_available_files)
        _sfx_editor_marker_count = len(_sfx_editor_markers)
        _sfx_editor_pool_count = len(_sfx_editor_pool_files)

        if not _sfx_editor_visible:
            return

        # Re-detect video channel every ~500ms
        global _sfx_editor__redetect_tick
        _sfx_editor__redetect_tick = (_sfx_editor__redetect_tick + 1) % 5
        if _sfx_editor__redetect_tick == 0:
            _sfx_editor_refresh_channel()

        # Detect current mode: video or image
        ch = _sfx_editor_active_channel
        is_video = ch is not None and renpy.music.is_playing(channel=ch)
        is_dialogue = bool(_sfx_editor_current_dialogue)

        if is_video:
            # --- VIDEO MODE ---
            elapsed = _sfx_editor_get_elapsed()
            duration = _sfx_editor_get_duration()

            _sfx_editor_current_time_str = _sfx_editor_format_time(elapsed)
            _sfx_editor_total_time_str = _sfx_editor_format_time(duration)
            fps = max(1, _sfx_editor_fps)
            _sfx_editor_current_frame_str = str(int(elapsed * fps))
            _sfx_editor_total_frame_str = str(int(duration * fps))

            global _sfx_editor_paused
            try:
                _sfx_editor_paused = renpy.music.get_pause(channel=ch)
            except Exception:
                pass

            # Detect video loop
            if _sfx_editor__last_pos > 0 and elapsed < _sfx_editor__last_pos - 0.3:
                _sfx_editor_played_markers.clear()
                if _sfx_editor_pool_enabled:
                    import random
                    _sfx_editor_next_pool_time = elapsed + random.uniform(
                        _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
                    )
            _sfx_editor__last_pos = elapsed

            # Video marker + pool trigger
            if _sfx_editor_mode == "manual":
                _sfx_editor_tick_manual(elapsed)
            elif _sfx_editor_mode == "pool":
                _sfx_editor_tick_pool(elapsed)

        elif is_dialogue:
            # --- IMAGE/DIALOGUE MODE ---
            _sfx_editor_current_time_str = "--:--.--"
            _sfx_editor_total_time_str = "--:--.--"
            _sfx_editor_current_frame_str = "---"
            _sfx_editor_total_frame_str = "---"

            # Trigger image markers on new dialogue key
            key = "{}|{}".format(
                _sfx_editor_current_image,
                _sfx_editor_current_dialogue
            )
            global _sfx_editor_last_marker_key
            if key != _sfx_editor_last_marker_key:
                _sfx_editor_last_marker_key = key
                for marker in _sfx_editor_image_markers:
                    if (marker["image"] == _sfx_editor_current_image
                            and marker["dialogue"] == _sfx_editor_current_dialogue):
                        _sfx_editor_play_sfx(marker["file"])

            # Pool trigger for image mode (time-based using system clock)
            if _sfx_editor_pool_enabled and _sfx_editor_pool_files:
                now = _time.time()
                global _sfx_editor_next_pool_time
                if _sfx_editor_next_pool_time == 0:
                    _sfx_editor_next_pool_time = now + _random.uniform(
                        _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
                    )
                elif now >= _sfx_editor_next_pool_time:
                    _sfx_editor_play_sfx(_random.choice(_sfx_editor_pool_files))
                    _sfx_editor_next_pool_time = now + _random.uniform(
                        _sfx_editor_pool_min_delay, _sfx_editor_pool_max_delay
                    )

        else:
            _sfx_editor_current_time_str = "--:--.--"
            _sfx_editor_total_time_str = "--:--.--"
            _sfx_editor_current_frame_str = "---"
            _sfx_editor_total_frame_str = "---"


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
            "image_markers": list(_sfx_editor_image_markers),
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
        global _sfx_editor_image_markers

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

        _sfx_editor_image_markers = config.get("image_markers", [])


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
# SECTION 4: Styles (game-agnostic — all properties explicit, no inheritance)
###############################################################################

style sfx_frame is empty:
    background "#000000ee"
    padding (8, 6)
    xfill True

style sfx_btn is empty:
    xysize (32, 26)
    background "#444444"
    hover_background "#666666"

style sfx_btn_text is empty:
    size 13
    color "#ffffff"
    hover_color "#ffffff"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5

style sfx_btn_sm is empty:
    xysize (20, 20)
    background "#444444"
    hover_background "#666666"

style sfx_btn_sm_text is empty:
    size 10
    color "#ffffff"
    hover_color "#ff8888"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5

style sfx_txt is empty:
    size 13
    color "#cccccc"
    font "DejaVuSans.ttf"

style sfx_hdr is empty:
    size 14
    color "#ffcc00"
    bold True
    font "DejaVuSans.ttf"

style sfx_help is empty:
    size 11
    color "#888888"
    font "DejaVuSans.ttf"

style sfx_input is empty:
    size 13
    color "#ffffff"
    font "DejaVuSans.ttf"
    xysize (100, 22)
    background "#333333"


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
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen sfx_editor_sidebar_content():
    vbox:
        spacing 4

        # --- Top bar: refresh + close (right-aligned) ---
        hbox:
            xfill True
            null xfill True
            textbutton "⟳":
                style "sfx_btn"
                text_style "sfx_btn_text"
                action [Function(_sfx_editor_refresh_channel), Function(_sfx_editor_scan_audio), Function(_sfx_editor_redetect_dialogue)]
            textbutton "✕":
                style "sfx_btn"
                text_style "sfx_btn_text"
                action Function(_sfx_editor_hide)

        # --- Mode detection ---
        $ _is_video = _sfx_editor_active_channel and renpy.music.is_playing(channel=_sfx_editor_active_channel)
        $ _is_dialogue = bool(_sfx_editor_current_dialogue)

        if not _is_video and not _is_dialogue:
            text "No video or dialogue" style "sfx_help"

        # --- Video UI ---
        if _is_video:
            frame:
                background "#222222"
                padding (2, 2)
                yminimum 0
                xfill True
                has vbox
                $ _vid_name = (_sfx_editor_channel_status or "").split(" | ")[-1] if " | " in (_sfx_editor_channel_status or "") else "?"
                text "Video: [_vid_name]" style "sfx_txt"
                text "[_sfx_editor_current_time_str] / [_sfx_editor_total_time_str]" style "sfx_txt"
                text "f: [_sfx_editor_current_frame_str]/[_sfx_editor_total_frame_str]" style "sfx_txt"
                hbox:
                    spacing 3
                    if _sfx_editor_paused:
                        textbutton "▶":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_sfx_editor_toggle_pause)
                    else:
                        textbutton "⏸":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_sfx_editor_toggle_pause)
                    textbutton "⏮":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_coarse_seek, -1.0)
                    textbutton "-1f":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_seek_frame, -1)
                    textbutton "+1f":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_seek_frame, 1)
                    textbutton "⏭":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_coarse_seek, 1.0)

        # --- Dialogue UI (can coexist with video) ---
        if _is_dialogue:
            frame:
                background "#222222"
                padding (2, 2)
                yminimum 0
                xfill True
                has vbox
                text "Image: [_sfx_editor_current_image]" style "sfx_txt"
                text "Dialogue: [_sfx_editor_current_dialogue]" style "sfx_txt"

        if _sfx_editor_scan_error:
            text "[_sfx_editor_scan_error]" style "sfx_help" color "#ff6666"

        null height 6

        # ================================================================
        # MANUAL MARKERS
        # ================================================================
        # Marker header + add button
        hbox:
            spacing 3
            if _is_video:
                text "Video Markers ([_sfx_editor_marker_count])" style "sfx_hdr"
            if _is_dialogue:
                text "Image Markers" style "sfx_hdr"
            if not _is_video and not _is_dialogue:
                text "Markers" style "sfx_hdr"
            text "File:" style "sfx_txt"
            text _sfx_editor_get_selected_filename() style "sfx_txt" color "#ffcc00"
            if _is_dialogue:
                textbutton "Add Marker":
                    style "sfx_btn"
                    text_style "sfx_btn_text"
                    action Function(_sfx_editor_add_image_marker, None)
            if _is_video:
                textbutton "Add Marker":
                    style "sfx_btn"
                    text_style "sfx_btn_text"
                    action Function(_sfx_editor_add_marker, None)

        # Video marker list
        if _sfx_editor_markers:
            viewport:
                xfill True
                ymaximum 120
                mousewheel True
                vbox:
                    spacing 2
                    for i, marker in enumerate(_sfx_editor_markers):
                        frame:
                            background "#333333"
                            padding (3, 2)
                            xfill True
                            hbox:
                                text _sfx_editor_format_time(marker["time"]) style "sfx_txt"
                                text "  " + marker["file"] style "sfx_txt" color "#ffcc00" size 11
                                null width 4
                                textbutton "✕":
                                    style "sfx_btn_sm"
                                    text_style "sfx_btn_sm_text"
                                    action Function(_sfx_editor_remove_marker, i)

        # Image marker list
        if _sfx_editor_image_markers:
            viewport:
                xfill True
                ymaximum 120
                mousewheel True
                vbox:
                    spacing 2
                    for i, marker in enumerate(_sfx_editor_image_markers):
                        frame:
                            background "#333333"
                            padding (3, 2)
                            xfill True
                            hbox:
                                text (marker["image"][:20] + " | \"" + marker["dialogue"][:30] + "\"") style "sfx_txt" size 10
                                text "  " + marker["file"] style "sfx_txt" color "#ffcc00" size 11
                                null width 4
                                textbutton "✕":
                                    style "sfx_btn_sm"
                                    text_style "sfx_btn_sm_text"
                                    action Function(_sfx_editor_remove_image_marker, i)

        if _sfx_editor_markers or _sfx_editor_image_markers:
            textbutton "Clear All":
                style "sfx_btn"
                text_style "sfx_btn_text"
                action Function(_sfx_editor_clear_all_markers)
        elif not _is_video and not _is_dialogue:
            text "No video or dialogue" style "sfx_help"

        null height 6

        # ================================================================
        # SFX POOL
        # ================================================================
        text "SFX Pool ([_sfx_editor_pool_count] / [_sfx_editor_audio_count] files)" style "sfx_hdr"

        hbox:
            spacing 2
            text "Min:" style "sfx_txt"
            input:
                style "sfx_input"
                value FieldInputValue(store, "_sfx_editor_pool_min_str", default=False)
            textbutton "Set":
                style "sfx_btn_sm"
                text_style "sfx_btn_sm_text"
                action Function(_sfx_editor_set_pool_delay, "min", _sfx_editor_pool_min_str)
            null width 6
            text "Max:" style "sfx_txt"
            input:
                style "sfx_input"
                value FieldInputValue(store, "_sfx_editor_pool_max_str", default=False)
            textbutton "Set":
                style "sfx_btn_sm"
                text_style "sfx_btn_sm_text"
                action Function(_sfx_editor_set_pool_delay, "max", _sfx_editor_pool_max_str)

        hbox:
            spacing 3
            if _sfx_editor_pool_enabled:
                textbutton "⏹ Stop Pool":
                    style "sfx_btn"
                    text_style "sfx_btn_text"
                    action Function(_sfx_editor_stop_pool)
            else:
                textbutton "▶ Start Pool":
                    style "sfx_btn"
                    text_style "sfx_btn_text"
                    action Function(_sfx_editor_start_pool)

        # Pool file list
        if _sfx_editor_pool_files:
            text "Pool files:" style "sfx_txt"
            viewport:
                xfill True
                ymaximum 130
                mousewheel True
                vbox:
                    spacing 1
                    for i, filename in enumerate(_sfx_editor_pool_files):
                        hbox:
                            spacing 1
                            textbutton "▶":
                                style "sfx_btn_sm"
                                text_style "sfx_btn_sm_text"
                                action Function(_sfx_editor_play_sfx, filename)
                            textbutton "✕":
                                style "sfx_btn_sm"
                                text_style "sfx_btn_sm_text"
                                action Function(_sfx_editor_remove_from_pool, i)
                            text filename style "sfx_txt" color "#ffcc00"

        # Audio file browser
        if _sfx_editor_audio_tree:
            text "Audio files:" style "sfx_txt"
            viewport:
                xfill True
                yfill True
                mousewheel True
                scrollbars "vertical"
                vscrollbar_xsize 6
                vscrollbar_unscrollable "hide"
                vbox:
                    spacing 1
                    for item in _sfx_editor_visible_tree:
                        hbox:
                            spacing 1
                            # Indent
                            if item["depth"] > 0:
                                text "  " * (item["depth"] * 2) style "sfx_txt"
                            if item["type"] == "folder":
                                if item["expanded"]:
                                    textbutton "▾":
                                        style "sfx_btn_sm"
                                        text_style "sfx_btn_sm_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                else:
                                    textbutton "▸":
                                        style "sfx_btn_sm"
                                        text_style "sfx_btn_sm_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                textbutton "P":
                                    style "sfx_btn_sm"
                                    text_style "sfx_btn_sm_text"
                                    action Function(_sfx_editor_add_folder_to_pool, item["full_path"])
                                textbutton item["name"]:
                                    style "sfx_btn"
                                    text_style "sfx_btn_text"
                                    action Function(_sfx_editor_toggle_folder, item["full_path"])
                                    xsize None
                            else:
                                # Play preview
                                textbutton "▶":
                                    style "sfx_btn_sm"
                                    text_style "sfx_btn_sm_text"
                                    action Function(_sfx_editor_play_sfx, item["full_path"])
                                # Set as marker file
                                textbutton "M":
                                    style "sfx_btn_sm"
                                    text_style "sfx_btn_sm_text"
                                    action Function(_sfx_editor_set_selected_file, item["index"])
                                # Add to pool or already in pool
                                if item["in_pool"]:
                                    textbutton "P":
                                        style "sfx_btn_sm"
                                        text_style "sfx_help"
                                        action NullAction()
                                    text item["name"] style "sfx_help"
                                else:
                                    textbutton "P":
                                        style "sfx_btn_sm"
                                        text_style "sfx_btn_sm_text"
                                        action Function(_sfx_editor_add_to_pool, item["index"])
                                    text item["name"] style "sfx_txt" color "#ffcc00"



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

    frame:
        style "sfx_frame"
        xalign 0.0
        yalign 0.0
        xsize 420
        yfill True
        use sfx_editor_sidebar_content()

