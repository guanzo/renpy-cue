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
    _sfx_editor_pool_frequency = 1  # 0 = Slow, 1 = Normal, 2 = Fast
    _sfx_editor_pool_state_video = 0   # 0=waiting for next play, 1=playing (waiting for finish)
    _sfx_editor_pool_state_dlg = 0
    _sfx_editor_pool_ch_video = None   # channel currently playing SFX
    _sfx_editor_pool_ch_dlg = None
    _sfx_editor_pool_ready_at_video = 0.0  # wall clock when next SFX can start
    _sfx_editor_pool_ready_at_dlg = 0.0
    _sfx_editor_pool_play_start_video = 0.0
    _sfx_editor_pool_play_start_dlg = 0.0
    _sfx_editor_pool_last_played = []  # last 2 played files (no-repeat window)
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
    _sfx_editor_manual_channel_input = ""

    # Image + dialogue mode
    _sfx_editor_current_image = ""
    _sfx_editor_current_dialogue = ""
    _sfx_editor_image_markers = []
    _sfx_editor_dialogue_markers = []
    _sfx_editor_last_image_key = ""
    _sfx_editor_last_dialogue_key = ""

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
            global _sfx_editor_visible, _sfx_editor_paused
            if _sfx_editor_visible:
                _sfx_editor_visible = False
                _sfx_editor_paused = False
        config.after_load_callbacks.append(_sfx_editor_after_load)

        # Character callback for dialogue detection
        def _sfx_editor_char_callback(event, interact=True, **kwargs):
            global _sfx_editor_current_dialogue
            if event == "show":
                old_dlg = _sfx_editor_current_dialogue
                _sfx_editor_current_dialogue = getattr(store, '_last_say_what', '') or ''
                _sfx_editor_refresh_detections()
                if _sfx_editor_current_dialogue != old_dlg:
                    _sfx_editor_load_context()
            elif event == "end":
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
        _sfx_editor_visible = True
        # Load persisted config
        _sfx_editor_load_config()
        # Initialize string field from current values
        _sfx_editor_manual_channel_input = (
            _sfx_editor_active_channel if _sfx_editor_active_channel else ""
        )
        # Scan audio on first open (cached thereafter)
        if not _sfx_editor_available_files:
            _sfx_editor_scan_audio()
        # Rebuild visible tree
        global _sfx_editor_visible_tree
        _sfx_editor_visible_tree = _sfx_editor_get_visible_tree()
        # Auto-detect everything
        _sfx_editor_refresh_detections()
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


    def _sfx_editor_refresh_detections():
        """Re-detect video and image, and swap context when they change."""
        global _sfx_editor_current_image
        global _sfx_editor_current_dialogue

        old_image = _sfx_editor_current_image
        old_video = _sfx_editor_active_channel
        old_dialogue = _sfx_editor_current_dialogue

        # 1. Re-detect video channel
        _sfx_editor_refresh_channel()

        # 2. Re-detect image (only if no video is playing)
        is_video = _sfx_editor_active_channel is not None and renpy.music.is_playing(channel=_sfx_editor_active_channel)
        if is_video:
            _sfx_editor_current_image = ""
            _sfx_editor_current_dialogue = ""
        else:
            _sfx_editor_current_image = _sfx_editor_get_showing_image()

        # 3. If context changed, load new context (old was already saved on add/remove)
        if (_sfx_editor_current_image != old_image
                or _sfx_editor_active_channel != old_video
                or _sfx_editor_current_dialogue != old_dialogue):
            _sfx_editor_load_context()


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
                if old_ch != ch_name:
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
        global _sfx_editor_played_markers, _sfx_editor_pool_ready_at_video
        global _sfx_editor__last_pos
        _sfx_editor_played_markers = set()
        _sfx_editor_pool_ready_at_video = 0.0
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
                children = _build_tree(node[name])
                has_direct_files = len(node[name].get("__files__", [])) > 0
                items.append({
                    "type": "folder",
                    "name": name + "/",
                    "children": children,
                    "expanded": False,
                    "has_files": has_direct_files,
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

    def _sfx_editor_add_folder_to_image_markers(folder_path):
        """Add all files under a folder as image markers for current image."""
        global _sfx_editor_image_markers
        if not _sfx_editor_current_image:
            return
        for f in _sfx_editor_available_files:
            if f.startswith(folder_path):
                marker = {"image": _sfx_editor_current_image, "file": f}
                if marker not in _sfx_editor_image_markers:
                    _sfx_editor_image_markers.append(marker)
        _sfx_editor_save_config()

    def _sfx_editor_add_folder_to_dialogue_markers(folder_path):
        """Add all files under a folder as dialogue markers for current image+dialogue."""
        global _sfx_editor_dialogue_markers
        if not _sfx_editor_current_dialogue:
            return
        for f in _sfx_editor_available_files:
            if f.startswith(folder_path):
                marker = {
                    "image": _sfx_editor_current_image,
                    "dialogue": _sfx_editor_current_dialogue,
                    "file": f,
                }
                if marker not in _sfx_editor_dialogue_markers:
                    _sfx_editor_dialogue_markers.append(marker)
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
                    "has_files": item.get("has_files", False),
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

    def _sfx_editor_preview_sfx(filename):
        """Play a preview of an SFX file. Restarts interaction to consume click."""
        _sfx_editor_play_sfx(filename)
        renpy.restart_interaction()

    def _sfx_editor_play_sfx(filename):
        """Play an SFX on the next available dedicated channel.
        Returns the channel name, or None on failure.
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
            idx = _sfx_editor__sfx_channel_idx
            target_ch = "_sfx_{}".format(idx + 1)
            _sfx_editor__sfx_channel_idx = (idx + 1) % 8
        else:
            ch_num = int(target_ch.split("_")[-1])
            _sfx_editor__sfx_channel_idx = ch_num % 8

        try:
            renpy.music.play(full_path, channel=target_ch, loop=False)
            return target_ch
        except Exception:
            return None


    # --------------------------------------------------------------------------
    # Manual Marker Management
    # --------------------------------------------------------------------------

    def _sfx_editor_add_video_marker(file_index):
        """Add a video marker at current elapsed time for the given file index."""
        global _sfx_editor_markers
        if not _sfx_editor_available_files:
            return
        if file_index < 0 or file_index >= len(_sfx_editor_available_files):
            return
        elapsed = _sfx_editor_get_elapsed()
        if elapsed is None or elapsed < 0:
            return
        filename = _sfx_editor_available_files[file_index]
        marker = {"time": elapsed, "file": filename}
        _sfx_editor_markers.append(marker)
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
        """Remove all markers (video + image + dialogue)."""
        global _sfx_editor_markers, _sfx_editor_played_markers
        global _sfx_editor_image_markers, _sfx_editor_dialogue_markers
        _sfx_editor_markers = []
        _sfx_editor_played_markers = set()
        _sfx_editor_image_markers = []
        _sfx_editor_dialogue_markers = []
        _sfx_editor_save_config()


    # --- Image markers (keyed by image filename only) ---

    def _sfx_editor_add_image_marker(file_index):
        """Add a marker for the current image using the given file."""
        global _sfx_editor_image_markers
        if not _sfx_editor_available_files:
            return
        if file_index < 0 or file_index >= len(_sfx_editor_available_files):
            return
        filename = _sfx_editor_available_files[file_index]
        marker = {
            "image": _sfx_editor_current_image,
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


    # --- Dialogue markers (keyed by image + dialogue text) ---

    def _sfx_editor_add_dialogue_marker(file_index):
        """Add a marker for the current image + dialogue using the given file."""
        global _sfx_editor_dialogue_markers
        if not _sfx_editor_available_files:
            return
        if file_index < 0 or file_index >= len(_sfx_editor_available_files):
            return
        filename = _sfx_editor_available_files[file_index]
        marker = {
            "image": _sfx_editor_current_image,
            "dialogue": _sfx_editor_current_dialogue,
            "file": filename,
        }
        _sfx_editor_dialogue_markers.append(marker)
        _sfx_editor_save_config()


    def _sfx_editor_remove_dialogue_marker(index):
        """Remove a dialogue marker at the given list index."""
        global _sfx_editor_dialogue_markers
        if 0 <= index < len(_sfx_editor_dialogue_markers):
            _sfx_editor_dialogue_markers.pop(index)
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

    def _sfx_editor_clear_pool():
        """Remove all files from the pool."""
        global _sfx_editor_pool_files, _sfx_editor_pool_ready_at_video
        global _sfx_editor_pool_ready_at_dlg, _sfx_editor_pool_state_video
        global _sfx_editor_pool_state_dlg
        _sfx_editor_pool_files = []
        _sfx_editor_pool_ready_at_video = 0.0
        _sfx_editor_pool_ready_at_dlg = 0.0
        _sfx_editor_pool_state_video = 0
        _sfx_editor_pool_state_dlg = 0
        _sfx_editor_save_config()


    def _sfx_editor_get_pool_delay():
        """Return random breathing room (silence) between SFX.
        This is the gap AFTER an SFX finishes before the next one starts.

        """
        import random
        freq = _sfx_editor_pool_frequency
        if freq == 2:
            return 0.5 + random.uniform(0.0, 0.15)
        elif freq == 1:
            return 1.7 + random.uniform(0.0, .75)
        else:
            return 3.0 + random.uniform(0.0, 1.5)

    def _sfx_editor_set_pool_frequency(freq):
        """Set pool frequency. 0 = Slow, 1 = Normal, 2 = Fast."""
        global _sfx_editor_pool_frequency
        _sfx_editor_pool_frequency = int(freq)
        _sfx_editor_save_config()
        renpy.restart_interaction()


    # --------------------------------------------------------------------------
    # SFX Trigger Engine (Tick)
    # --------------------------------------------------------------------------

    def _sfx_editor_tick_trigger():
        """SFX trigger engine — runs always (even when overlay is hidden)."""
        import random as _random
        import time as _time

        global _sfx_editor__tick_count
        _sfx_editor__tick_count = getattr(store, '_sfx_editor__tick_count', 0) + 1
        tick = _sfx_editor__tick_count

        # --- POOL STATE MACHINE HELPERS ---
        # State 0: waiting for ready_at to arrive
        # State 1: SFX playing, waiting for channel to go silent

        # --- VIDEO MODE triggers ---
        ch = _sfx_editor_active_channel
        if ch and renpy.music.is_playing(channel=ch):
            elapsed = _sfx_editor_get_elapsed()

            # Auto-re-pause after seek
            global _sfx_editor__pause_target, _sfx_editor__step_target
            global _sfx_editor_paused, _sfx_editor__time_offset
            pos = renpy.music.get_pos(channel=ch)
            if _sfx_editor__pause_target > 0 and pos is not None and pos >= _sfx_editor__pause_target:
                renpy.music.set_pause(True, channel=ch)
                _sfx_editor__pause_target = 0.0
                _sfx_editor_paused = True
                _sfx_editor__time_offset = 0.0
            if _sfx_editor__step_target > 0 and pos is not None and pos >= _sfx_editor__step_target:
                renpy.music.set_pause(True, channel=ch)
                _sfx_editor__step_target = 0.0
                _sfx_editor_paused = True
                _sfx_editor__time_offset = 0.0

            # Video markers
            if _sfx_editor_mode == "manual":
                for idx, marker in enumerate(_sfx_editor_markers):
                    if idx not in _sfx_editor_played_markers:
                        mt = marker["time"]
                        if mt <= elapsed < mt + _sfx_editor__marker_tolerance:
                            _sfx_editor_play_sfx(marker["file"])
                            _sfx_editor_played_markers.add(idx)

            # Video pool state machine
            # State 0: waiting — check if ready to play
            # State 1: playing — check if SFX finished
            if _sfx_editor_pool_files:
                now = _time.time()
                global _sfx_editor_pool_state_video, _sfx_editor_pool_ch_video
                global _sfx_editor_pool_ready_at_video, _sfx_editor_pool_play_start_video

                if _sfx_editor_pool_state_video == 1:
                    # Waiting for SFX to finish
                    if not renpy.music.is_playing(channel=_sfx_editor_pool_ch_video):
                        dur = now - _sfx_editor_pool_play_start_video
                        breathing = _sfx_editor_get_pool_delay()
                        _sfx_editor_pool_ready_at_video = now + breathing
                        _sfx_editor_pool_state_video = 0
                        _sfx_editor_log("TICK#{} POOL-DONE  file={} dur={:.2f}s breathing={:.2f}s next_in={:.2f}s".format(
                            tick, _sfx_editor_pool_last_played[-1] if _sfx_editor_pool_last_played else "?",
                            dur, breathing, breathing))

                if _sfx_editor_pool_state_video == 0:
                    # Waiting for next play time
                    if _sfx_editor_pool_ready_at_video == 0:
                        # First init: 500ms delay
                        _sfx_editor_pool_ready_at_video = now + 0.5
                    elif now >= _sfx_editor_pool_ready_at_video:
                        # Pick file with no-repeat protection
                        global _sfx_editor_pool_last_played
                        pool_size = len(_sfx_editor_pool_files)
                        if pool_size >= 3:
                            file = _random.choice(_sfx_editor_pool_files)
                            tries = 0
                            while file in _sfx_editor_pool_last_played and tries < 10:
                                file = _random.choice(_sfx_editor_pool_files)
                                tries += 1
                        elif pool_size == 2:
                            file = _random.choice(_sfx_editor_pool_files)
                        else:
                            file = _sfx_editor_pool_files[0]
                        if not isinstance(_sfx_editor_pool_last_played, list):
                            _sfx_editor_pool_last_played = []
                        _sfx_editor_pool_last_played.append(file)
                        if len(_sfx_editor_pool_last_played) > 2:
                            _sfx_editor_pool_last_played.pop(0)
                        ch = _sfx_editor_play_sfx(file)
                        if ch:
                            _sfx_editor_pool_state_video = 1
                            _sfx_editor_pool_ch_video = ch
                            _sfx_editor_pool_play_start_video = now
                            _sfx_editor_log("TICK#{} POOL-PLAY  file={} ch={}".format(tick, file, ch))

            # Detect video loop (markers only, pool uses wall clock)
            if _sfx_editor__last_pos > 0 and elapsed < _sfx_editor__last_pos - 0.3:
                _sfx_editor_played_markers.clear()
            global _sfx_editor__last_pos
            _sfx_editor__last_pos = elapsed

        # --- DIALOGUE MODE triggers ---
        if _sfx_editor_current_dialogue:
            global _sfx_editor_last_image_key, _sfx_editor_last_dialogue_key

            # Image markers — pick one randomly
            img_key = _sfx_editor_current_image
            if img_key != _sfx_editor_last_image_key:
                _sfx_editor_last_image_key = img_key
                matching = [m for m in _sfx_editor_image_markers if m["image"] == _sfx_editor_current_image]
                if matching:
                    _sfx_editor_play_sfx(_random.choice(matching)["file"])

            # Dialogue markers — pick one randomly
            dlg_key = "{}|{}".format(_sfx_editor_current_image, _sfx_editor_current_dialogue)
            if dlg_key != _sfx_editor_last_dialogue_key:
                _sfx_editor_last_dialogue_key = dlg_key
                matching = [m for m in _sfx_editor_dialogue_markers
                            if m["image"] == _sfx_editor_current_image
                            and m["dialogue"] == _sfx_editor_current_dialogue]
                if matching:
                    _sfx_editor_play_sfx(_random.choice(matching)["file"])

            # Dialogue pool state machine
            if _sfx_editor_pool_files:
                now = _time.time()
                global _sfx_editor_pool_state_dlg, _sfx_editor_pool_ch_dlg
                global _sfx_editor_pool_ready_at_dlg, _sfx_editor_pool_play_start_dlg

                if _sfx_editor_pool_state_dlg == 1:
                    if not renpy.music.is_playing(channel=_sfx_editor_pool_ch_dlg):
                        dur = now - _sfx_editor_pool_play_start_dlg
                        breathing = _sfx_editor_get_pool_delay()
                        _sfx_editor_pool_ready_at_dlg = now + breathing
                        _sfx_editor_pool_state_dlg = 0
                        _sfx_editor_log("TICK#{} POOL-DONE  file={} dur={:.2f}s breathing={:.2f}s".format(
                            tick, _sfx_editor_pool_last_played[-1] if _sfx_editor_pool_last_played else "?",
                            dur, breathing))

                if _sfx_editor_pool_state_dlg == 0:
                    if _sfx_editor_pool_ready_at_dlg == 0:
                        _sfx_editor_pool_ready_at_dlg = now + 0.5
                    elif now >= _sfx_editor_pool_ready_at_dlg:
                        global _sfx_editor_pool_last_played
                        pool_size = len(_sfx_editor_pool_files)
                        if pool_size >= 3:
                            file = _random.choice(_sfx_editor_pool_files)
                            tries = 0
                            while file in _sfx_editor_pool_last_played and tries < 10:
                                file = _random.choice(_sfx_editor_pool_files)
                                tries += 1
                        elif pool_size == 2:
                            file = _random.choice(_sfx_editor_pool_files)
                        else:
                            file = _sfx_editor_pool_files[0]
                        if not isinstance(_sfx_editor_pool_last_played, list):
                            _sfx_editor_pool_last_played = []
                        _sfx_editor_pool_last_played.append(file)
                        if len(_sfx_editor_pool_last_played) > 2:
                            _sfx_editor_pool_last_played.pop(0)
                        ch = _sfx_editor_play_sfx(file)
                        if ch:
                            _sfx_editor_pool_state_dlg = 1
                            _sfx_editor_pool_ch_dlg = ch
                            _sfx_editor_pool_play_start_dlg = now
                            _sfx_editor_log("TICK#{} POOL-PLAY  file={} ch={}".format(tick, file, ch))


    def _sfx_editor_tick():
        """Called ~10 times/sec by the overlay screen timer.

        Updates time display, checks markers, and drives pool mode.
        """
        global _sfx_editor_current_time_str, _sfx_editor_total_time_str
        global _sfx_editor_current_frame_str, _sfx_editor_total_frame_str
        global _sfx_editor_audio_count, _sfx_editor_marker_count, _sfx_editor_pool_count

        _sfx_editor_audio_count = len(_sfx_editor_available_files)
        _sfx_editor_marker_count = len(_sfx_editor_markers)
        _sfx_editor_pool_count = len(_sfx_editor_pool_files)

        if not _sfx_editor_visible:
            return

        # Re-detect video channel every ~500ms
        global _sfx_editor__redetect_tick
        _sfx_editor__redetect_tick = (_sfx_editor__redetect_tick + 1) % 5
        if _sfx_editor__redetect_tick == 0:
            _sfx_editor_refresh_detections()

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

            # (loop detection and triggers handled by _sfx_editor_tick_trigger)

        else:
            _sfx_editor_current_time_str = "--:--.--"
            _sfx_editor_total_time_str = "--:--.--"
            _sfx_editor_current_frame_str = "---"
            _sfx_editor_total_frame_str = "---"



    # --------------------------------------------------------------------------
    # Persistence
    # --------------------------------------------------------------------------

    def _sfx_editor_save_config():
        """Save current configuration to persistent storage, scoped by context."""
        existing = getattr(persistent, '_sfx_editor_config', {})
        if existing is None:
            existing = {}

        # --- Video markers (keyed by video path) ---
        video_path = _sfx_editor_get_video_path()
        video_key = video_path if video_path else "__no_video__"
        vid_markers = existing.get("markers_per_video", {})
        vid_markers[video_key] = list(_sfx_editor_markers)
        existing["markers_per_video"] = vid_markers

        # --- Image markers (keyed by image name) ---
        img_key = _sfx_editor_current_image or "__no_image__"
        img_markers = existing.get("image_markers_per_image", {})
        img_markers[img_key] = list(_sfx_editor_image_markers)
        existing["image_markers_per_image"] = img_markers

        # --- Dialogue markers (keyed by image + dialogue) ---
        dlg_key = (_sfx_editor_current_image or "__") + "|" + (_sfx_editor_current_dialogue or "")
        dlg_markers = existing.get("dialogue_markers_per_key", {})
        dlg_markers[dlg_key] = list(_sfx_editor_dialogue_markers)
        existing["dialogue_markers_per_key"] = dlg_markers

        # --- Pool (keyed by video or image) ---
        pool_ctx = video_key if video_path else img_key
        pool_dicts = existing.get("pool_per_context", {})
        pool_dicts[pool_ctx] = {
            "files": list(_sfx_editor_pool_files),
            "frequency": _sfx_editor_pool_frequency,
        }
        existing["pool_per_context"] = pool_dicts

        existing["audio_dir"] = _sfx_editor_audio_dir
        existing["mode"] = _sfx_editor_mode
        existing["last_channel"] = _sfx_editor_active_channel
        existing["version"] = _sfx_editor_version

        persistent._sfx_editor_config = existing


    def _sfx_editor_load_context():
        """Load markers and pool for the current video/image/dialogue context."""
        config = getattr(persistent, '_sfx_editor_config', None)
        if config is None:
            return

        global _sfx_editor_markers, _sfx_editor_image_markers
        global _sfx_editor_dialogue_markers

        # Video markers
        video_path = _sfx_editor_get_video_path()
        video_key = video_path if video_path else "__no_video__"
        markers_dict = config.get("markers_per_video", {})
        _sfx_editor_markers = list(markers_dict.get(video_key, []))

        # Image markers
        img_key = _sfx_editor_current_image or "__no_image__"
        img_dict = config.get("image_markers_per_image", {})
        _sfx_editor_image_markers = list(img_dict.get(img_key, []))

        # Dialogue markers
        dlg_key = (_sfx_editor_current_image or "__") + "|" + (_sfx_editor_current_dialogue or "")
        dlg_dict = config.get("dialogue_markers_per_key", {})
        _sfx_editor_dialogue_markers = list(dlg_dict.get(dlg_key, []))

        # Pool (keyed by video if video, else image)
        global _sfx_editor_pool_frequency
        pool_ctx = video_key if video_path else img_key
        pool_dicts = config.get("pool_per_context", {})
        pool_data = pool_dicts.get(pool_ctx, {})
        global _sfx_editor_pool_files
        _sfx_editor_pool_files = list(pool_data.get("files", []))
        _sfx_editor_pool_frequency = pool_data.get("frequency", 1)


    def _sfx_editor_load_config():
        """Load global config (not context-specific)."""
        config = getattr(persistent, '_sfx_editor_config', None)
        if config is None:
            return

        global _sfx_editor_audio_dir, _sfx_editor_mode, _sfx_editor_active_channel

        _sfx_editor_audio_dir = config.get("audio_dir", "sfx_editor/audio")
        _sfx_editor_mode = config.get("mode", "manual")
        _sfx_editor_active_channel = config.get("last_channel", None)

        # Load context-specific data
        _sfx_editor_load_context()


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
    background "#444444"
    hover_background "#666666"

style sfx_btn_text is empty:
    size 13
    color "#ffffff"
    hover_color "#ffffff"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5

style sfx_btn_icon is empty:
    xysize (18, 18)
    padding (0, 0)
    background "#444444"
    hover_background "#666666"

style sfx_btn_icon_text is empty:
    size 10
    color "#ffffff"
    hover_color "#ffffff"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5
    padding (0, 0)

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
    background "#333333"
    xsize 80


###############################################################################
# SECTION 5: Overlay Screen
###############################################################################

# =============================================================================
# KEY-LISTENER SCREEN: Always-visible invisible screen that catches backtick
# =============================================================================

screen sfx_editor_key_listener():
    zorder 10000
    key "K_BACKQUOTE" action Function(_sfx_editor_toggle)
    timer 0.05 repeat True action Function(_sfx_editor_tick_trigger)


# =============================================================================
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen sfx_editor_sidebar_content():
    vbox:
        spacing 4

        # --- Top bar: refresh + close ---
        hbox:
            spacing 2
            textbutton "⟳":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action [Function(_sfx_editor_refresh_detections), Function(_sfx_editor_scan_audio)]
            textbutton "✕":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
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
                xfill True
                yminimum 0
                has vbox
                $ _vid_name = (_sfx_editor_channel_status or "").split(" | ")[-1] if " | " in (_sfx_editor_channel_status or "") else "?"
                text "Video: [_vid_name]" style "sfx_txt"
                text "[_sfx_editor_current_time_str] / [_sfx_editor_total_time_str]" style "sfx_txt"
                text "f: [_sfx_editor_current_frame_str]/[_sfx_editor_total_frame_str]" style "sfx_txt"
                hbox:
                    spacing 5
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
                # Video marker add + list
                null height 5
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                null height 5
                vbox:
                    spacing 5
                    text "Video Markers ([_sfx_editor_marker_count])" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _sfx_editor_markers:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_all_markers)
                null height 5
                if _sfx_editor_markers:
                    vbox:
                        spacing 2
                        for i, marker in enumerate(_sfx_editor_markers):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_remove_marker, i)
                                vbox:
                                    text _sfx_editor_format_time(marker["time"]) style "sfx_txt"
                                    text " " + marker["file"] style "sfx_txt" color "#ffcc00" size 11
                                

        # --- Image UI ---
        $ _has_image = bool(_sfx_editor_current_image)
        if _has_image:
            frame:
                background "#222222"
                padding (2, 2)
                xfill True
                yminimum 0
                has vbox
                text "Image: [_sfx_editor_current_image]" style "sfx_txt"
                # Image marker add + list
                null height 5
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                null height 5
                vbox:
                    spacing 5
                    text "Image SFX" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _sfx_editor_image_markers:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_all_markers)
                null height 5
                if _sfx_editor_image_markers:
                    vbox:
                        spacing 2
                        for i, marker in enumerate(_sfx_editor_image_markers):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_image_marker, i)
                                vbox:
                                    text marker["image"][:25] style "sfx_txt" size 10
                                    text " " + marker["file"] style "sfx_txt" color "#ffcc00" size 11

        # --- Dialogue UI ---
        if _is_dialogue:
            frame:
                background "#222222"
                padding (2, 2)
                xfill True
                yminimum 0
                has vbox
                text "Dialogue: [_sfx_editor_current_dialogue]" style "sfx_txt"
                # Dialogue marker add + list
                null height 5
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                null height 5
                vbox:
                    spacing 5
                    text "Dialogue SFX" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _sfx_editor_dialogue_markers:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_all_markers)
                null height 5
                if _sfx_editor_dialogue_markers:
                    vbox:
                        spacing 2
                        for i, marker in enumerate(_sfx_editor_dialogue_markers):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_dialogue_marker, i)
                                vbox:
                                    text (marker["image"][:20] + " | " + marker["dialogue"][:20]) style "sfx_txt" size 10
                                    text " " + marker["file"] style "sfx_txt" color "#ffcc00" size 11

        if _sfx_editor_scan_error:
            text "[_sfx_editor_scan_error]" style "sfx_help" color "#ff6666"

        if not _is_video and not _is_dialogue:
            text "No video or dialogue" style "sfx_help"

        null height 6

        # ================================================================
        # SFX POOL
        # ================================================================
        frame:
            background "#222222"
            padding (3, 3)
            xfill True
            yminimum 0
            has vbox

            text "SFX Pool ([_sfx_editor_pool_count] / [_sfx_editor_audio_count] files)" style "sfx_hdr"

            hbox:
                spacing 5
                text "SFX Frequency" style "sfx_txt"
                $ slow_selected = (_sfx_editor_pool_frequency == 0)
                $ normal_selected = (_sfx_editor_pool_frequency == 1)
                $ fast_selected = (_sfx_editor_pool_frequency == 2)
                textbutton "Slow":
                    style "sfx_btn_icon"
                    text_style "sfx_btn_icon_text"
                    xsize 38
                    if slow_selected:
                        background "#666699"
                    else:
                        background "#444444"
                    action Function(_sfx_editor_set_pool_frequency, 0)
                textbutton "Normal":
                    style "sfx_btn_icon"
                    text_style "sfx_btn_icon_text"
                    xsize 50
                    if normal_selected:
                        background "#669966"
                    else:
                        background "#444444"
                    action Function(_sfx_editor_set_pool_frequency, 1)
                textbutton "Fast":
                    style "sfx_btn_icon"
                    text_style "sfx_btn_icon_text"
                    xsize 38
                    if fast_selected:
                        background "#996666"
                    else:
                        background "#444444"
                    action Function(_sfx_editor_set_pool_frequency, 2)

            # Pool file list
            if _sfx_editor_pool_files:
                text "Pool files:" style "sfx_txt"
                textbutton "Clear":
                    style "sfx_btn"
                    text_style "sfx_btn_text"
                    xsize 50
                    action Function(_sfx_editor_clear_pool)
                viewport:
                    xfill True
                    ymaximum 130
                    mousewheel True
                    vbox:
                        spacing 2
                        for i, filename in enumerate(_sfx_editor_pool_files):
                            hbox:
                                spacing 2
                                textbutton "▶":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_preview_sfx, filename)
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
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
                    spacing 2
                    for item in _sfx_editor_visible_tree:
                        hbox:
                            spacing 2
                            # Indent
                            if item["depth"] > 0:
                                text " " * item["depth"] style "sfx_txt"
                            if item["type"] == "folder":
                                if item["expanded"]:
                                    textbutton "▾":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                else:
                                    textbutton "▸":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                if item["has_files"]:
                                    textbutton "I":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_image_markers, item["full_path"])
                                    textbutton "D":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_dialogue_markers, item["full_path"])
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_pool, item["full_path"])
                                textbutton item["name"]:
                                    style "sfx_btn"
                                    text_style "sfx_btn_text"
                                    action Function(_sfx_editor_toggle_folder, item["full_path"])
                                    xsize None
                            else:
                                # Play preview
                                textbutton "▶":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_preview_sfx, item["full_path"])
                                # Video marker (file only)
                                textbutton "V":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_video_marker, item["index"])
                                # Image SFX
                                textbutton "I":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_image_marker, item["index"])
                                # Dialogue SFX
                                textbutton "D":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_dialogue_marker, item["index"])
                                # SFX Pool
                                if item["in_pool"]:
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_help"
                                        action NullAction()
                                    text item["name"] style "sfx_help"
                                else:
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
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
    key "K_BACKQUOTE" action Function(_sfx_editor_hide)
    # Timer to drive the SFX trigger engine
    timer 0.05 repeat True action Function(_sfx_editor_tick)

    button:
        xalign 0.0
        yalign 0.0
        xsize 420
        yfill True
        action NullAction()
        background None
        hover_background None
        frame:
            style "sfx_frame"
            xfill True
            yfill True
            use sfx_editor_sidebar_content()

