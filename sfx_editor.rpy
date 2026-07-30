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
    # --- Persistent config defaults (saved to persistent._sfx_editor_config) ---
    if not hasattr(store, '_sfx_editor_config_defaults_set'):
        store._sfx_editor_config_defaults_set = True

    # --- All runtime state on a single NoRollback object ---
    # Ren'Py skips rollback for NoRollback instances — no state gets corrupted
    # by Page Up. Never reassign _sfx itself; only mutate its attributes.
    _sfx = renpy.python.NoRollback()

    _sfx.version = "1.0.0"

    # Context tracking
    _sfx.active_channel = None
    _sfx.current_file = ""
    _sfx.current_dialogue = ""
    _sfx.channel_status = "No video"

    # User configuration
    _sfx.audio_dir = "sfx_editor/audio"
    _sfx.mode = "manual"
    _sfx.markers = []
    _sfx.image_markers = []
    _sfx.dialogue_markers = []
    _sfx.pool_files = []
    _sfx.pool_frequency = 1
    _sfx.clipboard = None

    # Trigger tracking
    _sfx.last_image_key = ""
    _sfx.last_dialogue_key = ""
    _sfx.played_markers = set()
    _sfx.__last_pos = 0.0

    # Pool state machine
    _sfx.pool_state = 0
    _sfx.pool_ch = None
    _sfx.pool_ready_at = 0.0
    _sfx.pool_play_start = 0.0
    _sfx.pool_last_played = []

    # Video seek/pause state
    _sfx.paused = False
    _sfx.fps = 30
    _sfx.__frame_time = 1.0 / 30.0
    _sfx.__time_offset = 0.0
    _sfx.__step_target = 0.0
    _sfx.__pause_target = 0.0
    _sfx.__pause_origin = 0.0
    _sfx.__total_offset = 0.0

    # UI state
    _sfx.visible = False
    _sfx.initialized = False
    _sfx.manual_channel_input = ""
    _sfx.visible_tree = []
    _sfx.expanded_folders = {}
    _sfx.scan_error = None
    _sfx.__active_sfx = {}

    # Audio file cache
    _sfx.available_files = []
    _sfx.audio_tree = []

    # Display
    _sfx.current_time_str = "--:--.--"
    _sfx.total_time_str = "--:--.--"
    _sfx.current_frame_str = "---"
    _sfx.total_frame_str = "---"
    _sfx.audio_count = 0
    _sfx.marker_count = 0
    _sfx.pool_count = 0

    # Internal
    _sfx.__sfx_channel_idx = 0
    _sfx.__fallback_start = 0.0
    _sfx.__using_fallback = False
    _sfx.__marker_tolerance = 0.08
    _sfx.__refreshing = False
    _sfx.__last_mismatch = ""
    _sfx.__force_redetect = 0


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

    if not _sfx.initialized:
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
        config.overlay_screens.append("sfx_editor_key_listener")
        _sfx_editor_log("INIT: overlay_screens key listener registered")

        # Register after_load callback
        def _sfx_editor_after_load():
            if _sfx.visible:
                _sfx.visible = False
                _sfx.paused = False
        config.after_load_callbacks.append(_sfx_editor_after_load)

        # Character callback — updates dialogue text only (context change
        # detection now lives in start_interact_callbacks below).
        def _sfx_editor_char_callback(event, interact=True, **kwargs):
            if event == "show":
                _sfx.current_dialogue = getattr(store, '_last_say_what', '') or ''
            elif event == "end":
                _sfx.current_dialogue = ""
        config.all_character_callbacks.append(_sfx_editor_char_callback)

        # start_interact callback — detects context changes at interaction
        # boundaries (replaces the old 500ms poll in _sfx_editor_tick).
        def _sfx_editor_start_interact_callback(*args, **kwargs):
            _sfx_editor_refresh_detections()
        config.start_interact_callbacks.append(_sfx_editor_start_interact_callback)

        _sfx_editor_log("INIT: callbacks registered")
        _sfx.initialized = True


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
            import time as _logtime
            log_dir = os.path.join(renpy.config.gamedir, "sfx_editor")
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir)
            log_path = os.path.join(log_dir, "debug.log")
            with open(log_path, "a") as f:
                _ts = _logtime.strftime("%H:%M:%S") + ".{:03d}".format(int(_logtime.time() * 1000) % 1000)
                f.write("[{}] {}\n".format(_ts, msg))
        except Exception:
            pass  # Never let logging break the game

    # --------------------------------------------------------------------------
    # Visibility
    # --------------------------------------------------------------------------

    def _sfx_editor_toggle():
        """Toggle the overlay on/off. Called from the key-listener screen."""
        if _sfx.visible:
            _sfx_editor_hide()
        else:
            _sfx_editor_show()



    def _sfx_editor_show():
        import time
        t0 = time.time()
        _sfx.visible = True
        # Load persisted config
        _sfx_editor_load_config()
        # Initialize string field from current values
        _sfx.manual_channel_input = (
            _sfx.active_channel if _sfx.active_channel else ""
        )
        # Scan audio on first open (cached thereafter)
        if not _sfx.available_files:
            _sfx_editor_scan_audio()
        # Rebuild visible tree
        _sfx.visible_tree = _sfx_editor_get_visible_tree()
        # Auto-detect everything
        _sfx_editor_refresh_detections()
        # Update channel input after detection
        _sfx.manual_channel_input = (
            _sfx.active_channel if _sfx.active_channel else ""
        )
        # Show the overlay screen
        renpy.show_screen("sfx_editor_overlay", _layer="sfx_editor_layer")
        renpy.restart_interaction()


    def _sfx_editor_hide():
        _sfx.visible = False
        # Save config on close
        _sfx_editor_save_config()
        renpy.hide_screen("sfx_editor_overlay", layer="sfx_editor_layer")


    def _sfx_editor_refresh_detections():
        """Re-detect video and image, and swap context when they change."""

        old_image = _sfx.current_file
        old_video = _sfx.active_channel
        old_dialogue = _sfx.current_dialogue

        # 1. Re-detect video channel
        _sfx_editor_refresh_channel()

        # 2. Re-detect context: if image is showing on master layer, it wins over video
        _img_on_screen = _sfx_editor_get_showing_image()
        if _img_on_screen != old_image:
            _sfx_editor_log("DETECT-IMG get_showing_tags={} old={}".format(repr(_img_on_screen), repr(old_image)))
        if _img_on_screen:
            _sfx.current_file = _img_on_screen
        else:
            is_video = _sfx.active_channel is not None and renpy.music.is_playing(channel=_sfx.active_channel)
            if is_video:
                _vpath = _sfx_editor_get_video_path()
                _sfx.current_file = _vpath.rsplit("/", 1)[-1] if _vpath else ""
            else:
                _sfx.current_file = ""

        # 3. Always log current context for debugging
        _sfx_editor_log_context()

        # 4. If context changed, load new context (old was already saved on add/remove)
        _changed = ""
        if _sfx.current_file != old_image:
            _changed += " file:{}->{}".format(old_image, _sfx.current_file)
        if _sfx.active_channel != old_video:
            _changed += " ch:{}->{}".format(old_video, _sfx.active_channel)
        if _sfx.current_dialogue != old_dialogue:
            _changed += " dlg:{}->{}".format(old_dialogue[:30] if old_dialogue else "",
                                             _sfx.current_dialogue[:30] if _sfx.current_dialogue else "")
        if _changed:
            _sfx_editor_log("CTX-CHANGE{}".format(_changed))
            _sfx_editor_load_context()
            _sfx_editor_fire_context_triggers()


    def _sfx_editor_log_context():
        """Log current context state for debugging — even if nothing changed."""
        _vpath = _sfx_editor_get_video_path()
        _vname = _vpath.rsplit("/", 1)[-1] if _vpath else "(none)"
        _sfx_editor_log("CTX-DUMP video={} ch={} img={} dlg=\"{}\"".format(
            _vname,
            _sfx.active_channel or "(none)",
            _sfx.current_file or "(none)",
            _sfx.current_dialogue[:60] if _sfx.current_dialogue else "(none)"))


    def _sfx_editor_fire_context_triggers():
        """Fire image and dialogue markers when context changes.
        Called immediately from start_interact callback — no polling delay."""
        import random as _random

        # Image markers
        if _sfx.current_file and _sfx.current_file != _sfx.last_image_key:
            _sfx.last_image_key = _sfx.current_file
            matching = [m for m in _sfx.image_markers if m["image"] == _sfx.current_file]
            _sfx_editor_log("IMG-TRIGGER file={} matching={}".format(_sfx.current_file, len(matching)))
            if matching:
                if not isinstance(_sfx.pool_last_played, list):
                    _sfx.pool_last_played = []
                _file = _random.choice(matching)["file"]
                if len(matching) > 1:
                    _tries = 0
                    while _file in _sfx.pool_last_played and _tries < 10:
                        _file = _random.choice(matching)["file"]
                        _tries += 1
                _sfx.pool_last_played.append(_file)
                if len(_sfx.pool_last_played) > 2:
                    _sfx.pool_last_played.pop(0)
                _sfx_editor_play_sfx(_file, "img:" + _sfx.current_file)

        # Dialogue markers
        dlg_key = "{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        if dlg_key != _sfx.last_dialogue_key:
            _sfx.last_dialogue_key = dlg_key
            matching = [m for m in _sfx.dialogue_markers
                        if m["image"] == _sfx.current_file
                        and m["dialogue"] == _sfx.current_dialogue]
            if matching:
                if not isinstance(_sfx.pool_last_played, list):
                    _sfx.pool_last_played = []
                _file = _random.choice(matching)["file"]
                if len(matching) > 1:
                    _tries = 0
                    while _file in _sfx.pool_last_played and _tries < 10:
                        _file = _random.choice(matching)["file"]
                        _tries += 1
                _sfx.pool_last_played.append(_file)
                if len(_sfx.pool_last_played) > 2:
                    _sfx.pool_last_played.pop(0)
                _dlg_src = _sfx.current_file + "|" + _sfx.current_dialogue[:40]
                _sfx_editor_play_sfx(_file, "dlg:" + _dlg_src)
            # else:
            #     _sfx_editor_log("TRIGGER-NO-MATCH dlg={}|{} total_dlg_markers={}".format(
            #         _sfx.current_file,
            #         _sfx.current_dialogue[:30] if _sfx.current_dialogue else "",
            #         len(_sfx.dialogue_markers)))


    def _sfx_editor_redetect_dialogue():
        """Manually re-detect current image and dialogue."""
        _sfx.current_dialogue = getattr(store, '_last_say_what', '') or ''
        _sfx.current_file = _sfx_editor_get_showing_image()


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

        if _sfx.__refreshing:
            return
        _sfx.__refreshing = True

        try:
            video_exts = (".webm", ".mp4", ".mkv", ".avi", ".ogv", ".mpeg", ".mpg")
            old_ch = _sfx.active_channel

            def _apply_channel(ch_name, ch_obj=None):
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
                _sfx.fps = fps
                _sfx.__frame_time = 1.0 / fps

                _sfx.active_channel = ch_name
                _sfx.channel_status = "{} | {} ({}fps)".format(ch_name, fname, fps)
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
                                _sfx.__refreshing = False
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
                        _sfx.__refreshing = False
                        return
                except Exception:
                    pass

            _sfx.active_channel = None
            _sfx.channel_status = "No video detected"
        finally:
            _sfx.__refreshing = False


    def _sfx_editor_set_channel_manual(ch_name):
        """Manually set the active channel."""
        ch_name = ch_name.strip()
        if ch_name and renpy.music.channel_defined(ch_name):
            _sfx.active_channel = ch_name
            _sfx.channel_status = ch_name
            _sfx.manual_channel_input = ch_name
            _sfx_editor_reset_loop_tracking()
        elif ch_name:
            _sfx.channel_status = "Channel '{}' not found".format(ch_name)


    def _sfx_editor_reset_loop_tracking():
        """Reset played markers and loop detection when video changes."""
        _sfx.played_markers = set()
        _sfx.pool_ready_at = 0.0
        _sfx.__last_pos = 0.0


    # --------------------------------------------------------------------------
    # Video Metadata
    # --------------------------------------------------------------------------

    def _sfx_editor_get_elapsed():
        """Get current playback position (real pos + virtual offset)."""
        ch = _sfx.active_channel
        if not ch:
            return 0.0
        try:
            pos = renpy.music.get_pos(channel=ch)
            if pos is not None:
                return max(0.0, pos + _sfx.__time_offset)
        except Exception:
            pass
        return 0.0


    def _sfx_editor_get_duration():
        """Get total duration of the current video in seconds."""
        ch = _sfx.active_channel
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
        ch = _sfx.active_channel
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
        ch = _sfx.active_channel
        if not ch:
            return

        _sfx.__time_offset = 0.0

        try:
            currently_paused = renpy.music.get_pause(channel=ch)
            new_state = not currently_paused
            renpy.music.set_pause(new_state, channel=ch)
            _sfx.paused = new_state

            if new_state:  # Just paused — save origin
                _sfx.__pause_origin = renpy.music.get_pos(channel=ch) or 0.0
                _sfx.__total_offset = 0.0
                _sfx_editor_log("pause: origin={:.3f}".format(_sfx.__pause_origin))
            else:  # Just unpaused
                _sfx.__total_offset = 0.0
                _sfx_editor_log("unpause: reset offset")
        except Exception:
            # Fallback: use volume as pseudo-pause
            if not _sfx.paused:
                renpy.music.set_volume(0.0, delay=0, channel=ch)
                _sfx.paused = True
            else:
                renpy.music.set_volume(1.0, delay=0, channel=ch)
                _sfx.paused = False


    # --------------------------------------------------------------------------
    # Video Control: Frame Step (virtual offset — seeking doesn't work on
    # Ren'Py movie channels, so we use a time offset for display/markers)
    # --------------------------------------------------------------------------

    def _sfx_editor_seek_frame(delta_frames):
        """Step forward/backward.
        Forward: briefly unpause, auto-re-pause via tick timer.
        Backward: restart from 0, auto-pause at origin + accumulated offset."""
        ch = _sfx.active_channel
        if not ch:
            return

        frame_seconds = _sfx.__frame_time

        # Auto-pause if video is playing
        if not _sfx.paused:
            renpy.music.set_pause(True, channel=ch)
            _sfx.paused = True
            _sfx.__pause_origin = renpy.music.get_pos(channel=ch) or 0.0
            _sfx.__total_offset = 0.0
            _sfx.__time_offset = 0.0

        if delta_frames > 0:
            pos = renpy.music.get_pos(channel=ch) or 0.0
            _sfx.__step_target = pos + delta_frames * frame_seconds
            _sfx_editor_log("+f step_target={:.3f}".format(_sfx.__step_target))
            renpy.music.set_pause(False, channel=ch)

        else:  # delta_frames < 0
            _sfx.__total_offset += delta_frames * frame_seconds
            dur = renpy.music.get_duration(channel=ch) or 0.0
            origin = _sfx.__pause_origin
            target = origin + _sfx.__total_offset
            if target < 0:
                target = dur + target
            target = max(0.0, min(target, dur - 0.05))

            filepath = renpy.music.get_playing(channel=ch)
            _sfx_editor_log(
                "-f origin={:.3f} total_offset={:.3f} target={:.3f} dur={:.3f}"
                .format(origin, _sfx.__total_offset, target, dur)
            )
            if filepath and dur > 0:
                _sfx.__pause_target = target
                renpy.music.stop(channel=ch, fadeout=0)
                renpy.music.play(filepath, channel=ch, loop=True)


    def _sfx_editor_coarse_seek(delta_seconds):
        """Jump forward/backward. Auto-pauses if playing."""
        ch = _sfx.active_channel
        if not ch:
            return

        # Auto-pause if playing
        if not _sfx.paused:
            renpy.music.set_pause(True, channel=ch)
            _sfx.paused = True
            _sfx.__pause_origin = renpy.music.get_pos(channel=ch) or 0.0
            _sfx.__total_offset = 0.0
            _sfx.__time_offset = 0.0

        if delta_seconds > 0:
            pos = renpy.music.get_pos(channel=ch) or 0.0
            _sfx.__step_target = pos + delta_seconds
            _sfx_editor_log("+coarse step_target={:.3f}".format(_sfx.__step_target))
            renpy.music.set_pause(False, channel=ch)
        else:
            _sfx.__total_offset += delta_seconds
            dur = renpy.music.get_duration(channel=ch) or 0.0
            origin = _sfx.__pause_origin
            target = origin + _sfx.__total_offset
            if target < 0:
                target = dur + target
            target = max(0.0, min(target, dur - 0.05))

            filepath = renpy.music.get_playing(channel=ch)
            _sfx_editor_log(
                "-coarse origin={:.3f} total_offset={:.3f} target={:.3f}"
                .format(origin, _sfx.__total_offset, target)
            )
            if filepath and dur > 0:
                _sfx.__pause_target = target
                renpy.music.stop(channel=ch, fadeout=0)
                renpy.music.play(filepath, channel=ch, loop=True)


    # --------------------------------------------------------------------------
    # Audio File Scanning
    # --------------------------------------------------------------------------

    def _sfx_editor_scan_audio():
        """Scan audio dir and build folder tree."""

        search_path = _sfx.audio_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        audio_exts = (".ogg", ".mp3", ".wav", ".opus", ".flac")

        try:
            all_files = renpy.list_files()
        except Exception:
            _sfx.available_files = []
            _sfx.audio_tree = []
            _sfx.scan_error = "Failed to list files"
            return

        # Build flat list of relative paths
        results = []
        for f in all_files:
            if f.startswith(search_path):
                relative = f[len(search_path):]
                if relative and f.lower().endswith(audio_exts):
                    results.append(relative)
        results.sort()
        _sfx.available_files = results

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

        _sfx.audio_tree = _build_tree(root)

        if not results:
            _sfx.scan_error = "No audio files found in: {}".format(
                _sfx.audio_dir
            )
        else:
            _sfx.scan_error = None

        # Rebuild visible tree for sidebar
        _sfx.visible_tree = _sfx_editor_get_visible_tree()


    def _sfx_editor_add_folder_to_pool(folder_path):
        """Recursively add all files under a folder prefix to the pool."""
        for f in _sfx.available_files:
            if f.startswith(folder_path) and f not in _sfx.pool_files:
                _sfx.pool_files.append(f)
        _sfx_editor_save_config()

    def _sfx_editor_add_folder_to_image_markers(folder_path):
        """Add all files under a folder as image markers for current image."""
        if not _sfx.current_file:
            return
        for f in _sfx.available_files:
            if f.startswith(folder_path):
                marker = {"image": _sfx.current_file, "file": f}
                if marker not in _sfx.image_markers:
                    _sfx.image_markers.append(marker)
        _sfx_editor_save_config()

    def _sfx_editor_add_folder_to_dialogue_markers(folder_path):
        """Add all files under a folder as dialogue markers for current image+dialogue."""
        if not _sfx.current_dialogue:
            return
        for f in _sfx.available_files:
            if f.startswith(folder_path):
                marker = {
                    "image": _sfx.current_file,
                    "dialogue": _sfx.current_dialogue,
                    "file": f,
                }
                if marker not in _sfx.dialogue_markers:
                    _sfx.dialogue_markers.append(marker)
        _sfx_editor_save_config()


    def _sfx_editor_toggle_folder(folder_path):
        """Toggle expand/collapse for a folder in the audio tree."""
        if folder_path in _sfx.expanded_folders:
            _sfx.expanded_folders[folder_path] = not _sfx.expanded_folders[folder_path]
        else:
            _sfx.expanded_folders[folder_path] = True
        _sfx.visible_tree = _sfx_editor_get_visible_tree()
        renpy.restart_interaction()


    def _sfx_editor_get_visible_tree():
        """Return a flat list of visible tree items for rendering.
        Each item: {type, name, depth, full_path, index_in_flat_list}"""
        result = []
        _walk_tree(_sfx.audio_tree, "", 0, result)
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
                    "expanded": _sfx.expanded_folders.get(full, False),
                    "has_files": item.get("has_files", False),
                })
                if _sfx.expanded_folders.get(full, False):
                    _walk_tree(item.get("children", []), full, depth + 1, result)
            else:
                # Find index in flat list
                try:
                    idx = _sfx.available_files.index(full)
                except ValueError:
                    idx = -1
                result.append({
                    "type": "file",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "index": idx,
                    "in_pool": full in _sfx.pool_files,
                })


    def _sfx_editor_change_audio_dir(new_path):
        """Change the audio directory and rescan."""
        new_path = new_path.strip()
        if new_path:
            _sfx.audio_dir = new_path
            _sfx_editor_scan_audio()
            _sfx_editor_save_config()


    # --------------------------------------------------------------------------
    # SFX Playback
    # --------------------------------------------------------------------------

    def _sfx_editor_preview_sfx(filename):
        """Play a preview of an SFX file. Restarts interaction to consume click."""
        _sfx_editor_play_sfx(filename, "preview")
        renpy.restart_interaction()

    def _sfx_editor_play_sfx(filename, source=""):
        """Play an SFX on the next available dedicated channel.
        source: descriptive key for logging (video, image, dialogue, or pool)
        Returns the channel name, or None on failure.
        """

        base_dir = _sfx.audio_dir
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
            idx = _sfx.__sfx_channel_idx
            target_ch = "_sfx_{}".format(idx + 1)
            _sfx.__sfx_channel_idx = (idx + 1) % 8
        else:
            ch_num = int(target_ch.split("_")[-1])
            _sfx.__sfx_channel_idx = ch_num % 8

        try:
            # Context mismatch warning: compare source context with current state
            _warn = None
            if source.startswith("vid:"):
                _vid_parts = source[4:].rsplit("@", 1)
                _expected_vid = _vid_parts[0]
                _cur_vpath = _sfx_editor_get_video_path()
                _cur_vname = _cur_vpath.rsplit("/", 1)[-1] if _cur_vpath else ""
                if _expected_vid and _cur_vname and _expected_vid != _cur_vname:
                    _warn = "expected vid={} actual vid={}".format(_expected_vid, _cur_vname)
            elif source.startswith("img:"):
                _expected_img = source[4:]
                if _expected_img and _sfx.current_file and _expected_img != _sfx.current_file:
                    _warn = "expected img={} actual img={}".format(_expected_img, _sfx.current_file)
            elif source.startswith("dlg:"):
                # source: "dlg:image|dialogue"
                _parts = source[4:].split("|", 1)
                _expected_img = _parts[0]
                _expected_dlg = _parts[1] if len(_parts) > 1 else ""
                _cur_img = _sfx.current_file or ""
                _cur_dlg = (_sfx.current_dialogue or "")[:40]
                if _expected_img != _cur_img or _expected_dlg != _cur_dlg:
                    _warn = "expected img={}|{} actual img={}|{}".format(
                        _expected_img, _expected_dlg, _cur_img, _cur_dlg)
            if _warn:
                _sfx_editor_log("WARN CTX-MISMATCH file={} src={} {}".format(
                    filename.rsplit("/", 1)[-1], source, _warn))

            renpy.music.play(full_path, channel=target_ch, loop=False)
            _sfx_editor_log("PLAY-SFX file={} src={} ch={}".format(filename.rsplit("/", 1)[-1], source, target_ch))
            return target_ch
        except Exception:
            return None


    # --------------------------------------------------------------------------
    # Manual Marker Management
    # --------------------------------------------------------------------------

    def _sfx_editor_add_video_marker(file_index):
        """Add a video marker at current elapsed time for the given file index."""
        if not _sfx.available_files:
            return
        if file_index < 0 or file_index >= len(_sfx.available_files):
            return
        ch = _sfx.active_channel
        if not ch or not renpy.music.is_playing(channel=ch):
            return
        elapsed = _sfx_editor_get_elapsed()
        if elapsed is None or elapsed <= 0:
            return
        filename = _sfx.available_files[file_index]
        marker = {"time": elapsed, "file": filename}
        _sfx.markers.append(marker)
        _sfx.markers.sort(key=lambda m: m["time"])
        _sfx_editor_save_config()


    def _sfx_editor_remove_marker(index):
        """Remove a marker at the given list index."""
        if 0 <= index < len(_sfx.markers):
            _sfx.markers.pop(index)
            _sfx.played_markers = set(
                i if i < index else i - 1
                for i in _sfx.played_markers
                if i != index
            )
            _sfx_editor_save_config()


    def _sfx_editor_clear_all_markers():
        """Remove all markers (video + image + dialogue)."""
        _sfx.markers = []
        _sfx.played_markers = set()
        _sfx.image_markers = []
        _sfx.dialogue_markers = []
        _sfx_editor_save_config()

    def _sfx_editor_clear_video_markers():
        _sfx.markers = []
        _sfx.played_markers = set()
        _sfx_editor_save_config()

    def _sfx_editor_clear_image_markers():
        _sfx.image_markers = []
        _sfx_editor_save_config()

    def _sfx_editor_clear_dialogue_markers():
        _sfx.dialogue_markers = []
        _sfx_editor_save_config()

    def _sfx_editor_copy_context():
        """Copy current context's markers and pool to clipboard."""
        _sfx.clipboard = {
            "markers": list(_sfx.markers),
            "image_markers": list(_sfx.image_markers),
            "dialogue_markers": list(_sfx.dialogue_markers),
            "pool_files": list(_sfx.pool_files),
            "pool_frequency": _sfx.pool_frequency,
        }

    def _sfx_editor_paste_context():
        """Paste clipboard config into current context, remapping keys."""
        if _sfx.clipboard is None:
            return
        _sfx.markers = list(_sfx.clipboard["markers"])
        # Remap image markers to current image
        _sfx.image_markers = []
        for m in _sfx.clipboard["image_markers"]:
            _sfx.image_markers.append({"image": _sfx.current_file, "file": m["file"]})
        # Remap dialogue markers to current image + dialogue
        _sfx.dialogue_markers = []
        for m in _sfx.clipboard["dialogue_markers"]:
            _sfx.dialogue_markers.append({
                "image": _sfx.current_file,
                "dialogue": _sfx.current_dialogue,
                "file": m["file"],
            })
        _sfx.pool_files = list(_sfx.clipboard["pool_files"])
        _sfx.pool_frequency = _sfx.clipboard["pool_frequency"]
        _sfx.played_markers = set()
        _sfx.pool_ready_at = 0.0
        _sfx_editor_save_config()


    # --- Image markers (keyed by image filename only) ---

    def _sfx_editor_add_image_marker(file_index):
        """Add a marker for the current image using the given file."""
        if not _sfx.available_files:
            return
        if file_index < 0 or file_index >= len(_sfx.available_files):
            return
        filename = _sfx.available_files[file_index]
        marker = {
            "image": _sfx.current_file,
            "file": filename,
        }
        _sfx.image_markers.append(marker)
        _sfx_editor_save_config()


    def _sfx_editor_remove_image_marker(index):
        """Remove an image marker at the given list index."""
        if 0 <= index < len(_sfx.image_markers):
            _sfx.image_markers.pop(index)
            _sfx_editor_save_config()


    # --- Dialogue markers (keyed by image + dialogue text) ---

    def _sfx_editor_add_dialogue_marker(file_index):
        """Add a marker for the current image + dialogue using the given file."""
        if not _sfx.available_files:
            return
        if file_index < 0 or file_index >= len(_sfx.available_files):
            return
        filename = _sfx.available_files[file_index]
        marker = {
            "image": _sfx.current_file,
            "dialogue": _sfx.current_dialogue,
            "file": filename,
        }
        _sfx.dialogue_markers.append(marker)
        _sfx_editor_save_config()


    def _sfx_editor_remove_dialogue_marker(index):
        """Remove a dialogue marker at the given list index."""
        if 0 <= index < len(_sfx.dialogue_markers):
            _sfx.dialogue_markers.pop(index)
            _sfx_editor_save_config()


    # --------------------------------------------------------------------------
    # Pool Management
    # --------------------------------------------------------------------------

    def _sfx_editor_add_to_pool(file_index):
        """Add an audio file to the SFX pool."""
        if 0 <= file_index < len(_sfx.available_files):
            filename = _sfx.available_files[file_index]
            if filename not in _sfx.pool_files:
                _sfx.pool_files.append(filename)
                _sfx_editor_save_config()


    def _sfx_editor_remove_from_pool(index):
        """Remove a file from the pool by index."""
        if 0 <= index < len(_sfx.pool_files):
            _sfx.pool_files.pop(index)
            _sfx_editor_save_config()

    def _sfx_editor_clear_pool():
        """Remove all files from the pool."""
        _sfx.pool_files = []
        _sfx.pool_ready_at = 0.0
        _sfx.pool_state = 0
        _sfx_editor_save_config()


    def _sfx_editor_get_pool_delay():
        """Return random breathing room (silence) between SFX.
        This is the gap AFTER an SFX finishes before the next one starts.

        """
        import random
        freq = _sfx.pool_frequency
        if freq == 2:
            return 0.5 + random.uniform(0.0, 0.15)
        elif freq == 1:
            return 1.7 + random.uniform(0.0, .75)
        else:
            return 3.0 + random.uniform(0.0, 1.5)

    def _sfx_editor_set_pool_frequency(freq):
        """Set pool frequency. 0 = Slow, 1 = Normal, 2 = Fast."""
        _sfx.pool_frequency = int(freq)
        _sfx_editor_save_config()
        renpy.restart_interaction()


    # --------------------------------------------------------------------------
    # SFX Trigger Engine (Tick)
    # --------------------------------------------------------------------------

    def _sfx_editor_tick_trigger():
        """SFX trigger engine — runs always (even when overlay is hidden)."""
        import random as _random
        import time as _time

        _sfx.__tick_count = getattr(store, '_sfx.__tick_count', 0) + 1
        tick = _sfx.__tick_count

        # --- POOL STATE MACHINE HELPERS ---
        # --- UNIFIED POOL state machine (one SFX at a time, any context) ---
        # Pool runs when it has files AND (video is playing OR dialogue is present)
        _pool_active = (_sfx.active_channel is not None and renpy.music.is_playing(channel=_sfx.active_channel)) or bool(_sfx.current_dialogue)
        if _sfx.pool_files and _pool_active:
            now = _time.time()

            if _sfx.pool_state == 1:
                if not renpy.music.is_playing(channel=_sfx.pool_ch):
                    dur = now - _sfx.pool_play_start
                    breathing = _sfx_editor_get_pool_delay()
                    _sfx.pool_ready_at = now + breathing
                    _sfx.pool_state = 0
                    _sfx_editor_log("TICK#{} POOL-DONE  file={} dur={:.2f}s breathing={:.2f}s".format(
                        tick, _sfx.pool_last_played[-1] if _sfx.pool_last_played else "?",
                        dur, breathing))

            if _sfx.pool_state == 0:
                if _sfx.pool_ready_at == 0:
                    _sfx.pool_ready_at = now + 0.5
                elif now >= _sfx.pool_ready_at:
                    pool_size = len(_sfx.pool_files)
                    if pool_size >= 3:
                        file = _random.choice(_sfx.pool_files)
                        tries = 0
                        while file in _sfx.pool_last_played and tries < 10:
                            file = _random.choice(_sfx.pool_files)
                            tries += 1
                    elif pool_size == 2:
                        file = _random.choice(_sfx.pool_files)
                    else:
                        file = _sfx.pool_files[0]
                    if not isinstance(_sfx.pool_last_played, list):
                        _sfx.pool_last_played = []
                    _sfx.pool_last_played.append(file)
                    if len(_sfx.pool_last_played) > 2:
                        _sfx.pool_last_played.pop(0)
                    ch_used = _sfx_editor_play_sfx(file, "pool")
                    if ch_used:
                        _sfx.pool_state = 1
                        _sfx.pool_ch = ch_used
                        _sfx.pool_play_start = now
                        _sfx_editor_log("TICK#{} POOL-PLAY  file={} ch={}".format(tick, file, ch_used))

        # --- VIDEO MODE triggers ---
        ch = _sfx.active_channel
        if ch and renpy.music.is_playing(channel=ch):
            elapsed = _sfx_editor_get_elapsed()

            # Auto-re-pause after seek
            pos = renpy.music.get_pos(channel=ch)
            if _sfx.__pause_target > 0 and pos is not None and pos >= _sfx.__pause_target:
                renpy.music.set_pause(True, channel=ch)
                _sfx.__pause_target = 0.0
                _sfx.paused = True
                _sfx.__time_offset = 0.0
            if _sfx.__step_target > 0 and pos is not None and pos >= _sfx.__step_target:
                renpy.music.set_pause(True, channel=ch)
                _sfx.__step_target = 0.0
                _sfx.paused = True
                _sfx.__time_offset = 0.0

            # Video markers
            if _sfx.mode == "manual":
                for idx, marker in enumerate(_sfx.markers):
                    if idx not in _sfx.played_markers:
                        mt = marker["time"]
                        if mt <= elapsed < mt + _sfx.__marker_tolerance:
                            _vpath = _sfx_editor_get_video_path()
                            _vname = _vpath.rsplit("/", 1)[-1] if _vpath else "?"
                            _vkey = "vid:{}@{:.2f}".format(_vname, marker["time"])
                            _sfx_editor_play_sfx(marker["file"], _vkey)
                            _sfx.played_markers.add(idx)


            # Detect video loop (markers only, pool uses wall clock)
            if _sfx.__last_pos > 0 and elapsed < _sfx.__last_pos - 0.3:
                _sfx.played_markers.clear()
            _sfx.__last_pos = elapsed


    def _sfx_editor_tick():
        """Called ~10 times/sec by the overlay screen timer.

        Updates time display, checks markers, and drives pool mode.
        """

        _sfx.audio_count = len(_sfx.available_files)
        _sfx.marker_count = len(_sfx.markers)
        _sfx.pool_count = len(_sfx.pool_files)

        if not _sfx.visible:
            return

        # Detect current mode: video or image
        ch = _sfx.active_channel
        is_video = ch is not None and renpy.music.is_playing(channel=ch)
        is_dialogue = bool(_sfx.current_dialogue)

        if is_video:
            # --- VIDEO MODE ---
            elapsed = _sfx_editor_get_elapsed()
            duration = _sfx_editor_get_duration()

            _sfx.current_time_str = _sfx_editor_format_time(elapsed)
            _sfx.total_time_str = _sfx_editor_format_time(duration)
            fps = max(1, _sfx.fps)
            _sfx.current_frame_str = str(int(elapsed * fps))
            _sfx.total_frame_str = str(int(duration * fps))

            try:
                _sfx.paused = renpy.music.get_pause(channel=ch)
            except Exception:
                pass

            # (loop detection and triggers handled by _sfx_editor_tick_trigger)

        else:
            _sfx.current_time_str = "--:--.--"
            _sfx.total_time_str = "--:--.--"
            _sfx.current_frame_str = "---"
            _sfx.total_frame_str = "---"



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
        vid_markers[video_key] = list(_sfx.markers)
        existing["markers_per_video"] = vid_markers

        # --- Image markers (keyed by image name) ---
        img_key = _sfx.current_file or "__no_image__"
        img_markers = existing.get("image_markers_per_image", {})
        img_markers[img_key] = list(_sfx.image_markers)
        existing["image_markers_per_image"] = img_markers

        # --- Dialogue markers (keyed by image + dialogue) ---
        dlg_key = (_sfx.current_file or "__") + "|" + (_sfx.current_dialogue or "")
        dlg_markers = existing.get("dialogue_markers_per_key", {})
        dlg_markers[dlg_key] = list(_sfx.dialogue_markers)
        existing["dialogue_markers_per_key"] = dlg_markers

        # --- Pool (keyed by video or image) ---
        pool_ctx = video_key if video_path else img_key
        pool_dicts = existing.get("pool_per_context", {})
        pool_dicts[pool_ctx] = {
            "files": list(_sfx.pool_files),
            "frequency": _sfx.pool_frequency,
        }
        existing["pool_per_context"] = pool_dicts

        existing["audio_dir"] = _sfx.audio_dir
        existing["mode"] = _sfx.mode
        existing["last_channel"] = _sfx.active_channel
        existing["version"] = _sfx.version

        persistent._sfx_editor_config = existing


    def _sfx_editor_load_context():
        """Load markers and pool for the current video/image/dialogue context."""
        config = getattr(persistent, '_sfx_editor_config', None)
        if config is None:
            return


        # Video markers
        video_path = _sfx_editor_get_video_path()
        video_key = video_path if video_path else "__no_video__"
        markers_dict = config.get("markers_per_video", {})
        _sfx.markers = list(markers_dict.get(video_key, []))

        # Image markers
        img_key = _sfx.current_file or "__no_image__"
        img_dict = config.get("image_markers_per_image", {})
        _sfx.image_markers = list(img_dict.get(img_key, []))

        # Dialogue markers
        dlg_key = (_sfx.current_file or "__") + "|" + (_sfx.current_dialogue or "")
        dlg_dict = config.get("dialogue_markers_per_key", {})
        _sfx.dialogue_markers = list(dlg_dict.get(dlg_key, []))

        # Pool (keyed by video if video, else image)
        pool_ctx = video_key if video_path else img_key
        pool_dicts = config.get("pool_per_context", {})
        pool_data = pool_dicts.get(pool_ctx, {})
        _sfx.pool_files = list(pool_data.get("files", []))
        _sfx.pool_frequency = pool_data.get("frequency", 1)


    def _sfx_editor_load_config():
        """Load global config (not context-specific)."""
        config = getattr(persistent, '_sfx_editor_config', None)
        if config is None:
            return


        _sfx.audio_dir = config.get("audio_dir", "sfx_editor/audio")
        _sfx.mode = config.get("mode", "manual")
        _sfx.active_channel = config.get("last_channel", None)

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
    hover_sound None
    activate_sound None

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

        # --- Top bar: copy + paste + refresh + close ---
        hbox:
            spacing 2
            textbutton "📋":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_copy_context)
                tooltip "Copy context config"
            textbutton "📄":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_paste_context)
                tooltip "Paste context config"
            textbutton "⟳":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action [Function(_sfx_editor_refresh_detections), Function(_sfx_editor_scan_audio)]
                tooltip "Refresh detections"
            textbutton "✕":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_hide)
                tooltip "Close overlay"

        # --- Mode detection ---
        $ _is_video = _sfx.active_channel and renpy.music.is_playing(channel=_sfx.active_channel)
        $ _is_dialogue = bool(_sfx.current_dialogue)

        # --- Video UI ---
        if _is_video:
            frame:
                background "#222222"
                padding (2, 2)
                xfill True
                yminimum 0
                has vbox
                $ _vid_name = (_sfx.channel_status or "").split(" | ")[-1] if " | " in (_sfx.channel_status or "") else "?"
                text "Video: [_vid_name]" style "sfx_txt"
                text "[_sfx.current_time_str] / [_sfx.total_time_str]" style "sfx_txt"
                text "f: [_sfx.current_frame_str]/[_sfx.total_frame_str]" style "sfx_txt"
                hbox:
                    spacing 5
                    if _sfx.paused:
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
                    text "Video Markers ([_sfx.marker_count])" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _sfx.markers:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_video_markers)
                null height 5
                if _sfx.markers:
                    vbox:
                        spacing 2
                        for i, marker in enumerate(_sfx.markers):
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
        $ _has_image = bool(_sfx.current_file) and not _is_video
        if _has_image:
            frame:
                background "#222222"
                padding (2, 2)
                xfill True
                yminimum 0
                has vbox
                text "Image: [_sfx.current_file]" style "sfx_txt"
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
                        if _sfx.image_markers:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_image_markers)
                null height 5
                if _sfx.image_markers:
                    vbox:
                        spacing 2
                        for i, marker in enumerate(_sfx.image_markers):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_image_marker, i)
                                text marker["file"] style "sfx_txt" color "#ffcc00" size 11

        # --- Dialogue UI ---
        if _is_dialogue:
            frame:
                background "#222222"
                padding (2, 2)
                xfill True
                yminimum 0
                has vbox
                text "Dialogue: [_sfx.current_dialogue]" style "sfx_txt"
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
                        if _sfx.dialogue_markers:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_dialogue_markers)
                null height 5
                if _sfx.dialogue_markers:
                    vbox:
                        spacing 2
                        for i, marker in enumerate(_sfx.dialogue_markers):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_dialogue_marker, i)
                                text marker["file"] style "sfx_txt" color "#ffcc00" size 11

        if _sfx.scan_error:
            text "[_sfx.scan_error]" style "sfx_help" color "#ff6666"

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

            text "SFX Pool ([_sfx.pool_count] / [_sfx.audio_count] files)" style "sfx_hdr"

            hbox:
                spacing 5
                text "SFX Frequency" style "sfx_txt"
                $ slow_selected = (_sfx.pool_frequency == 0)
                $ normal_selected = (_sfx.pool_frequency == 1)
                $ fast_selected = (_sfx.pool_frequency == 2)
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
            if _sfx.pool_files:
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
                        for i, filename in enumerate(_sfx.pool_files):
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
                                text filename style "sfx_txt" color "#ffcc00" size 11

        # Audio file browser
        if _sfx.audio_tree:
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
                    for item in _sfx.visible_tree:
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
                                        tooltip "Collapse folder"
                                else:
                                    textbutton "▸":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                        tooltip "Expand folder"
                                if item["has_files"]:
                                    textbutton "I":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_image_markers, item["full_path"])
                                        tooltip "Add folder to Image SFX"
                                    textbutton "D":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_dialogue_markers, item["full_path"])
                                        tooltip "Add folder to Dialogue SFX"
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_pool, item["full_path"])
                                        tooltip "Add folder to SFX Pool"
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
                                    tooltip "Preview audio"
                                # Video marker (file only)
                                textbutton "V":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_video_marker, item["index"])
                                    tooltip "Add video marker at current time"
                                # Image SFX
                                textbutton "I":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_image_marker, item["index"])
                                    tooltip "Add to Image SFX"
                                # Dialogue SFX
                                textbutton "D":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_dialogue_marker, item["index"])
                                    tooltip "Add to Dialogue SFX"
                                # SFX Pool
                                if item["in_pool"]:
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_help"
                                        action NullAction()
                                        tooltip "Already in SFX Pool"
                                    text item["name"] style "sfx_help"
                                else:
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_to_pool, item["index"])
                                        tooltip "Add to SFX Pool"
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

