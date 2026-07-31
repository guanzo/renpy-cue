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
    _sfx.markers = {}          # Unified markers: trigger_key -> entry
    _sfx.clipboard = None

    # Trigger tracking
    _sfx.played_video_keys = set()
    _sfx.__last_pos = 0.0

    # Pool state machine (multi-instance: one per active p: key)
    _sfx.pool_states = {}

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
    _sfx.disabled_files = set()  # Set of full_path strings for unchecked files

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
        _sfx_editor_save_markers()
        renpy.hide_screen("sfx_editor_overlay", layer="sfx_editor_layer")


    def _sfx_editor_refresh_detections():
        """Re-detect video and image, and swap context when they change."""

        old_file = _sfx.current_file
        old_video = _sfx.active_channel
        old_dialogue = _sfx.current_dialogue

        # 1. Re-detect video channel
        _sfx_editor_refresh_channel()

        # 2. Re-detect context: top displayable on master layer wins;
        #    fall back to video channel when nothing is on the master layer.
        _top_name, _top_type = _sfx_editor_get_top_layer()
        if _top_name is None:
            return
        
        _sfx.current_file = _top_name
        _sfx.top_layer_type = _top_type  # cache for screen / other consumers

        # 3. Always log current context for debugging
        _sfx_editor_log_context()

        # 4. If context changed, build trigger keys and fire
        _changed = ""
        _img_key = None
        _dlg_key = None
        if _sfx.current_file != old_file:
            _changed += " file:{}->{}".format(old_file, _sfx.current_file)
            _img_key = "i:" + _sfx.current_file if _sfx.current_file else None
        if _sfx.active_channel != old_video:
            _changed += " ch:{}->{}".format(old_video, _sfx.active_channel)
        if _sfx.current_dialogue != old_dialogue:
            _changed += " dlg:{}->{}".format(old_dialogue[:30] if old_dialogue else "",
                                             _sfx.current_dialogue[:30] if _sfx.current_dialogue else "")
            if _sfx.current_dialogue:
                _dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        if _changed:
            _sfx_editor_log("CTX-CHANGE{}".format(_changed))
            _sfx_editor_fire_context_triggers(_img_key, _dlg_key)


    def _sfx_editor_log_context():
        """Log current context state for debugging — even if nothing changed."""
        _vpath = _sfx_editor_get_video_path()
        _vname = _vpath.rsplit("/", 1)[-1] if _vpath else "(none)"
        _playing = "?"
        if _sfx.active_channel:
            try:
                _playing = "1" if renpy.music.is_playing(channel=_sfx.active_channel) else "0"
            except Exception:
                pass
        # Determine primary context — top displayable on master layer wins;
        # fall back to video channel when nothing is on the master layer.
        _top_name, _top_type = _sfx_editor_get_top_layer()
        if _top_type:
            _ctx_type = _top_type  # 'image' or 'movie'
        elif _sfx.active_channel is not None and _playing == "1":
            _ctx_type = "video"
        else:
            _ctx_type = "none"
        _sfx_editor_log("CTX-DUMP ctx={} type={} video={} ch={} playing={} dlg=\"{}\"".format(
            _sfx.current_file or "(none)",
            _ctx_type,
            _vname,
            _sfx.active_channel or "(none)",
            _playing,
            _sfx.current_dialogue[:60] if _sfx.current_dialogue else "(none)"))


    def _sfx_editor_pick_file(files, pool_key, avoid_repeats=True):
        """Pick a random file from a list.
        If avoid_repeats is True, avoids files in the global last_played list.
        Repeat avoidance is shared across all non-video contexts.
        Video timestamps should pass avoid_repeats=False — they always fire.
        """
        import random as _random
        if not files:
            return None
        if len(files) == 1:
            f = files[0]
        elif avoid_repeats:
            last = _sfx.pool_states.setdefault("__last_played__", [])
            if not isinstance(last, list):
                last = []
                _sfx.pool_states["__last_played__"] = last
            f = _random.choice(files)
            tries = 0
            while f in last and tries < 10:
                f = _random.choice(files)
                tries += 1
            last.append(f)
            if len(last) > 2:
                last.pop(0)
        else:
            f = _random.choice(files)
        return f


    def _sfx_editor_fire_context_triggers(*keys):
        """Fire markers for the given trigger keys.
        refresh_detections passes the exact keys — this just does lookups.
        """
        import random as _random
        for key in keys:
            if not key:
                continue
            entry = _sfx.markers.get(key)
            if entry:
                files = entry.get("files", [])
                if files:
                    _sfx_editor_log("CTX-TRIGGER key={} files={}".format(key, len(files)))
                    _file = _sfx_editor_pick_file(files, key)
                    _sfx_editor_play_sfx(_file, key)


    # --------------------------------------------------------------------------
    # Image / Movie Detection (master layer scene list)
    # --------------------------------------------------------------------------

    def _sfx_editor_top_name(name):
        """Normalize a displayable name to a single string.
        Image names are tuples like ('bg', 'forest') — use the tag ('bg')."""
        if name is None:
            return None
        if isinstance(name, tuple) and name:
            name = name[0]
        name = str(name)
        if not name:
            return None
        return name


    def _sfx_editor_top_movie_name(movie):
        """Context name for a Movie on the master layer.
        Movie has no 'name' in Ren'Py 7/8 — fall back to the file basename
        from its 'play' attribute (which may be a list of paths)."""
        name = _sfx_editor_top_name(getattr(movie, "name", None))
        if name:
            return name
        play = getattr(movie, "play", None)
        if isinstance(play, list):
            play = play[0] if play else None
        if play:
            return str(play).replace("\\", "/").rsplit("/", 1)[-1]
        return None


    def _sfx_editor_get_top_layer():
        """Return (name, kind) for the topmost displayable on the master
        layer — what the player actually sees (scene list order is z-order).

        kind is 'image', 'movie', or None (nothing/unknown on the layer).
        name is the image tag (e.g. 'bg') or movie basename (e.g.
        'intro.webm'), or None. Callers fall back to the video channel
        when name is None (channel movies are not on the master layer).
        """
        try:
            layers = renpy.game.context().scene_lists.layers.get("master", [])
            if not layers:
                return None, None

            d = layers[-1].displayable
            unwrap = lambda f, x: (f(f, x.child) if x is not None and hasattr(x, "child") else x)
            d = unwrap(unwrap, d)
            if d is None:
                return None, None

            # The wrapper (ImageReference) always has .name; the underlying
            # displayable (Image / Movie) may be d itself or d.target.
            name = _sfx_editor_top_name(getattr(d, "name", None))

            # Movie: check d first ('show expression Movie(...)'), then
            # d.target ('image foo = Movie(...)' + 'show foo').
            movie = d if isinstance(d, renpy.display.video.Movie) else getattr(d, "target", None)
            if isinstance(movie, renpy.display.video.Movie):
                if name is None:
                    name = _sfx_editor_top_movie_name(movie)
                return name, "movie"

            # Image: check d first, then d.target (ImageReference wrapper).
            img = d if isinstance(d, renpy.display.im.Image) else getattr(d, "target", None)
            if isinstance(img, renpy.display.im.Image):
                if name is None:
                    name = _sfx_editor_top_name(getattr(img, "filename", None))
                return name, "image"

            # Unknown but named — treat as image context (matches old behavior).
            if name:
                return name, "image"
            return None, None
        except Exception as exc:
            _sfx_editor_log("TOP-LAYER-ERR {}".format(repr(exc)))
            return None, None

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
                    if path and path.lower().endswith(video_exts) and renpy.music.is_playing(channel=ch):
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
        _sfx.played_video_keys = set()
        _sfx.pool_states = {}
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


    def _sfx_editor_is_file_in_pool(full_path):
        """Check if a file is in any p: entry."""
        for key, entry in _sfx.markers.items():
            if key.startswith("p:") and full_path in entry.get("files", []):
                return True
        return False


    def _sfx_editor_add_folder_to_pool(folder_path):
        """Recursively add all files under a folder prefix to the p: pool."""
        if not _sfx.current_file:
            return
        pool_key = "p:" + _sfx.current_file
        entry = _sfx.markers.setdefault(pool_key, {"files": [], "frequency": 1})
        files = entry.setdefault("files", [])
        for f in _sfx.available_files:
            if f.startswith(folder_path) and f not in files and f not in _sfx.disabled_files:
                files.append(f)
        _sfx_editor_save_markers()

    def _sfx_editor_add_folder_to_image_markers(folder_path):
        """Add all files under a folder as image markers for current image."""
        if not _sfx.current_file:
            return
        img_key = "i:" + _sfx.current_file
        entry = _sfx.markers.setdefault(img_key, {"files": []})
        files = entry.setdefault("files", [])
        for f in _sfx.available_files:
            if f.startswith(folder_path) and f not in files and f not in _sfx.disabled_files:
                files.append(f)
        _sfx_editor_save_markers()

    def _sfx_editor_add_folder_to_dialogue_markers(folder_path):
        """Add all files under a folder as dialogue markers for current image+dialogue."""
        if not _sfx.current_dialogue:
            return
        dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        entry = _sfx.markers.setdefault(dlg_key, {"files": []})
        files = entry.setdefault("files", [])
        for f in _sfx.available_files:
            if f.startswith(folder_path) and f not in files and f not in _sfx.disabled_files:
                files.append(f)
        _sfx_editor_save_markers()


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
                    "in_pool": _sfx_editor_is_file_in_pool(full),
                    "enabled": full not in _sfx.disabled_files,
                })


    def _sfx_editor_change_audio_dir(new_path):
        """Change the audio directory and rescan."""
        new_path = new_path.strip()
        if new_path:
            _sfx.audio_dir = new_path
            _sfx_editor_scan_audio()
            _sfx_editor_save_config()


    def _sfx_editor_toggle_file_enabled(full_path):
        """Toggle whether a file is enabled for marker addition."""
        if full_path in _sfx.disabled_files:
            _sfx.disabled_files.discard(full_path)
        else:
            _sfx.disabled_files.add(full_path)
        _sfx.visible_tree = _sfx_editor_get_visible_tree()
        renpy.restart_interaction()


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
                _cur_vname = _sfx.current_file or ""
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
    # Unified Marker CRUD
    # --------------------------------------------------------------------------

    def _sfx_editor_marker_add_file(trigger_key, filename):
        """Append a file to an entry's files list. Creates the entry if needed."""
        entry = _sfx.markers.get(trigger_key)
        if entry is None:
            _sfx.markers[trigger_key] = {"files": [filename]}
        else:
            files = entry.setdefault("files", [])
            if filename not in files:
                files.append(filename)
        _sfx_editor_save_markers()

    def _sfx_editor_marker_remove_file(trigger_key, file_index):
        """Remove a file from an entry's files list by index."""
        entry = _sfx.markers.get(trigger_key)
        if entry and "files" in entry:
            files = entry["files"]
            if 0 <= file_index < len(files):
                files.pop(file_index)
                if not files:
                    del _sfx.markers[trigger_key]
                _sfx_editor_save_markers()

    def _sfx_editor_marker_remove_key(trigger_key):
        """Remove an entire trigger key entry."""
        if trigger_key in _sfx.markers:
            del _sfx.markers[trigger_key]
            _sfx_editor_save_markers()

    # --- Video markers (v: prefix) ---

    def _sfx_editor_add_video_marker(file_index):
        """Add a video timestamp entry at current elapsed time."""
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
        if filename in _sfx.disabled_files:
            return
        vid_key = "v:" + _sfx.current_file
        timestamps = _sfx.markers.setdefault(vid_key, [])
        timestamps.append({"time": elapsed, "files": [filename]})
        timestamps.sort(key=lambda e: e["time"])
        _sfx_editor_save_markers()

    def _sfx_editor_remove_video_marker(ts_index):
        """Remove a video timestamp entry at the given index in the v: list."""
        vid_key = "v:" + _sfx.current_file
        timestamps = _sfx.markers.get(vid_key, [])
        if 0 <= ts_index < len(timestamps):
            timestamps.pop(ts_index)
            if not timestamps:
                del _sfx.markers[vid_key]
            _sfx.played_video_keys = set()  # reset on any removal
            _sfx_editor_save_markers()

    def _sfx_editor_clear_video_markers():
        """Remove all v: keys."""
        for key in list(_sfx.markers.keys()):
            if key.startswith("v:"):
                del _sfx.markers[key]
        _sfx.played_video_keys = set()
        _sfx_editor_save_markers()

    # --- Image markers (i: prefix) ---

    def _sfx_editor_add_image_marker(file_index):
        """Add a file to the i: entry for the current image."""
        if not _sfx.available_files:
            return
        if file_index < 0 or file_index >= len(_sfx.available_files):
            return
        if not _sfx.current_file:
            return
        filename = _sfx.available_files[file_index]
        if filename in _sfx.disabled_files:
            return
        img_key = "i:" + _sfx.current_file
        _sfx_editor_marker_add_file(img_key, filename)

    def _sfx_editor_remove_image_marker(file_index):
        """Remove a file from the i: entry for the current image."""
        img_key = "i:" + _sfx.current_file
        _sfx_editor_marker_remove_file(img_key, file_index)

    def _sfx_editor_clear_image_markers():
        """Remove all i: keys."""
        for key in list(_sfx.markers.keys()):
            if key.startswith("i:"):
                del _sfx.markers[key]
        _sfx_editor_save_markers()

    # --- Dialogue markers (d: prefix) ---

    def _sfx_editor_add_dialogue_marker(file_index):
        """Add a file to the d: entry for the current image + dialogue."""
        if not _sfx.available_files:
            return
        if file_index < 0 or file_index >= len(_sfx.available_files):
            return
        if not _sfx.current_dialogue:
            return
        filename = _sfx.available_files[file_index]
        if filename in _sfx.disabled_files:
            return
        dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        _sfx_editor_marker_add_file(dlg_key, filename)

    def _sfx_editor_remove_dialogue_marker(file_index):
        """Remove a file from the d: entry for the current dialogue."""
        dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        _sfx_editor_marker_remove_file(dlg_key, file_index)

    def _sfx_editor_clear_dialogue_markers():
        """Remove all d: keys."""
        for key in list(_sfx.markers.keys()):
            if key.startswith("d:"):
                del _sfx.markers[key]
        _sfx_editor_save_markers()

    # --- Pool (p: prefix) ---

    def _sfx_editor_add_to_pool(file_index):
        """Add an audio file to the p: pool for the current context."""
        if 0 <= file_index < len(_sfx.available_files):
            if not _sfx.current_file:
                return
            filename = _sfx.available_files[file_index]
            if filename in _sfx.disabled_files:
                return
            pool_key = "p:" + _sfx.current_file
            entry = _sfx.markers.setdefault(pool_key, {"files": [], "frequency": 1})
            files = entry.setdefault("files", [])
            if filename not in files:
                files.append(filename)
            _sfx_editor_save_markers()

    def _sfx_editor_remove_from_pool(file_index):
        """Remove a file from the p: pool for the current context."""
        pool_key = "p:" + _sfx.current_file
        _sfx_editor_marker_remove_file(pool_key, file_index)

    def _sfx_editor_clear_pool():
        """Remove all p: keys."""
        for key in list(_sfx.markers.keys()):
            if key.startswith("p:"):
                del _sfx.markers[key]
        _sfx.pool_states = {}
        _sfx_editor_save_markers()

    # --- Bulk clear ---

    def _sfx_editor_clear_all_markers():
        """Remove all markers (all prefixes)."""
        _sfx.markers = {}
        _sfx.played_video_keys = set()
        _sfx.pool_states = {}
        _sfx_editor_save_markers()

    def _sfx_editor_get_context_files():
        """Return a set of filenames that identify the current context.
        Used for p: pool lookups."""
        result = set()
        if _sfx.current_file:
            result.add(_sfx.current_file)
        return result

    def _sfx_editor_get_pool_entry():
        """Return the pool entry dict for the current context, or None.
        Checks both image tag and video basename for a matching p: key.
        Injects __key__ into the returned dict so the UI knows the key.
        """
        ctx_files = _sfx_editor_get_context_files()
        for f in ctx_files:
            key = "p:" + f
            entry = _sfx.markers.get(key)
            if entry:
                result = dict(entry)
                result["__key__"] = key
                return result
        return None

    # --- Clipboard ---

    def _sfx_editor_copy_context():
        """Copy markers for the current context to clipboard."""
        ctx_file = _sfx.current_file or ""
        ctx_dlg = _sfx.current_dialogue or ""
        copied = {}
        for key, entry in _sfx.markers.items():
            if key.startswith("i:") and key[2:] == ctx_file:
                copied[key] = dict(entry)
            elif key.startswith("d:") and key[2:].startswith(ctx_file + "|"):
                copied[key] = dict(entry)
            elif key.startswith(("p:", "v:")) and key[2:] == ctx_file:
                copied[key] = dict(entry)
        _sfx.clipboard = {
            "markers": copied,
            "source_file": ctx_file,
            "source_dialogue": ctx_dlg,
        }

    def _sfx_editor_paste_context():
        """Paste clipboard markers into current context, remapping keys."""
        if _sfx.clipboard is None:
            return
        ctx_file = _sfx.current_file or ""
        ctx_dlg = _sfx.current_dialogue or ""
        old_file = _sfx.clipboard.get("source_file", "")
        old_dlg = _sfx.clipboard.get("source_dialogue", "")
        for old_key, entry in _sfx.clipboard.get("markers", {}).items():
            new_key = old_key
            if old_key.startswith("i:") and old_key[2:] == old_file:
                new_key = "i:" + ctx_file
            elif old_key.startswith("d:") and old_key[2:].startswith(old_file + "|"):
                new_key = "d:" + ctx_file + "|" + ctx_dlg
            elif old_key.startswith(("p:", "v:")) and old_key[2:] == old_file:
                new_key = old_key[:2] + ctx_file
            if new_key not in _sfx.markers:
                if isinstance(entry, list):
                    _sfx.markers[new_key] = list(entry)
                else:
                    _sfx.markers[new_key] = dict(entry)
        _sfx.played_video_keys = set()
        _sfx.pool_states = {}
        _sfx_editor_save_markers()

    def _sfx_editor_dump_markers():
        """Dump full markers data to sfx_editor/markers_dump.json (next to debug.log)."""
        try:
            import json as _json
            dump_dir = os.path.join(renpy.config.gamedir, "sfx_editor")
            if not os.path.isdir(dump_dir):
                os.makedirs(dump_dir)
            dump_path = os.path.join(dump_dir, "markers_dump_old.json")
            with open(dump_path, "w") as f:
                _json.dump({
                    "version": "2.0.2",
                    "markers": dict(_sfx.markers),
                }, f, indent=2, sort_keys=True)
            _sfx_editor_log("DUMP-MARKERS total_keys={} path=markers.json".format(
                len(_sfx.markers)))
        except Exception as e:
            _sfx_editor_log("DUMP-MARKERS-ERROR {}".format(str(e)))

    def _sfx_editor_restore_markers_from_file():
        """Restore markers from sfx_editor/markers_dump.json, replacing all current markers."""
        try:
            import json as _json
            dump_path = os.path.join(renpy.config.gamedir, "sfx_editor", "markers_dump.json")
            if not os.path.isfile(dump_path):
                _sfx_editor_log("RESTORE-MARKERS-NO-FILE path=markers_dump.json")
                return
            with open(dump_path, "r") as f:
                data = _json.load(f)
            _sfx.markers = dict(data.get("markers", {}))
            _sfx.played_video_keys = set()
            _sfx.pool_states = {}
            _sfx_editor_save_markers()
            _sfx_editor_log("RESTORE-MARKERS total_keys={} path=markers_dump.json".format(
                len(_sfx.markers)))
        except Exception as e:
            _sfx_editor_log("RESTORE-MARKERS-ERROR {}".format(str(e)))


    def _sfx_editor_get_pool_delay(frequency=1):
        """Return random breathing room (silence) between SFX.
        This is the gap AFTER an SFX finishes before the next one starts.
        frequency: 0=Slow, 1=Normal, 2=Fast
        """
        import random
        freq = frequency
        if freq == 2:
            return 0.5 + random.uniform(0.0, 0.15)
        elif freq == 1:
            return 1.7 + random.uniform(0.0, .75)
        else:
            return 3.0 + random.uniform(0.0, 1.5)

    def _sfx_editor_set_pool_frequency(trigger_key, freq):
        """Set pool frequency for a p: entry. 0 = Slow, 1 = Normal, 2 = Fast."""
        entry = _sfx.markers.get(trigger_key)
        if entry:
            entry["frequency"] = int(freq)
            _sfx_editor_save_markers()
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

        # --- POOL STATE MACHINE (p: keys) ---
        now = _time.time()
        pool_key = "p:" + (_sfx.current_file or "")

        entry = _sfx.markers.get(pool_key)
        if entry:
            files = entry.get("files", [])
            freq = entry.get("frequency", 1)
            if files:
                # Init pool state if needed
                if pool_key not in _sfx.pool_states:
                    _sfx.pool_states[pool_key] = {
                        "state": 0,
                        "ch": None,
                        "ready_at": 0.0,
                        "play_start": 0.0,
                    }
                ps = _sfx.pool_states[pool_key]

                if ps["state"] == 1:
                    if not renpy.music.is_playing(channel=ps["ch"]):
                        dur = now - ps["play_start"]
                        breathing = _sfx_editor_get_pool_delay(freq)
                        ps["ready_at"] = now + breathing
                        ps["state"] = 0
                        _sfx_editor_log("TICK#{} POOL-DONE  key={} dur={:.2f}s breathing={:.2f}s".format(
                            tick, pool_key, dur, breathing))

                if ps["state"] == 0:
                    if ps["ready_at"] == 0:
                        ps["ready_at"] = now + 0.5
                    elif now >= ps["ready_at"]:
                        f = _sfx_editor_pick_file(files, pool_key)
                        ch_used = _sfx_editor_play_sfx(f, pool_key)
                        if ch_used:
                            ps["state"] = 1
                            ps["ch"] = ch_used
                            ps["play_start"] = now
                            _sfx_editor_log("TICK#{} POOL-PLAY  key={} file={} ch={}".format(
                                tick, pool_key, f, ch_used))

        # --- VIDEO MODE triggers (v: keys) ---
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
            if _sfx.current_file:
                vid_key = "v:" + _sfx.current_file
                timestamps = _sfx.markers.get(vid_key, [])
                for idx, entry in enumerate(timestamps):
                    ts_key = "{}@{}".format(vid_key, idx)
                    if ts_key not in _sfx.played_video_keys:
                        mt = entry["time"]
                        if mt <= elapsed < mt + _sfx.__marker_tolerance:
                            files = entry.get("files", [])
                            if files:
                                _vsrc = "vid:{}@{:.2f}".format(_sfx.current_file, mt)
                                f = _sfx_editor_pick_file(files, vid_key, avoid_repeats=False)
                                _sfx_editor_play_sfx(f, _vsrc)
                                _sfx.played_video_keys.add(ts_key)

            # Detect video loop (markers only, pool uses wall clock)
            if _sfx.__last_pos > 0 and elapsed < _sfx.__last_pos - 0.3:
                _sfx.played_video_keys.clear()
            _sfx.__last_pos = elapsed


    def _sfx_editor_tick():
        """Called ~10 times/sec by the overlay screen timer.

        Updates time display, checks markers, and drives pool mode.
        """

        _sfx.audio_count = len(_sfx.available_files)
        _sfx.marker_count = len(_sfx.markers)
        # Count pool files across all p: entries
        _pool_total = 0
        for key, entry in _sfx.markers.items():
            if key.startswith("p:"):
                _pool_total += len(entry.get("files", []))
        _sfx.pool_count = _pool_total

        if not _sfx.visible:
            return

        # Detect current mode: video or image
        ch = _sfx.active_channel

        if _sfx.top_layer_type == 'movie':
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

    def _sfx_editor_save_markers():
        """Save unified markers to persistent storage."""
        persistent._sfx_editor_markers = {
            "version": "2.0.2",
            "markers": dict(_sfx.markers),
        }


    def _sfx_editor_load_markers():
        """Load all markers from persistent storage."""
        data = getattr(persistent, '_sfx_editor_markers', None)
        if data is None:
            _sfx.markers = {}
            return
        _sfx.markers = dict(data.get("markers", {}))
        _sfx_editor_log("LOAD-MARKERS total_keys={} keys={}".format(
            len(_sfx.markers), list(_sfx.markers.keys())[:20]))


    def _sfx_editor_save_config():
        """Save global settings (not markers) to old config key."""
        existing = getattr(persistent, '_sfx_editor_config', {})
        if existing is None:
            existing = {}
        existing["audio_dir"] = _sfx.audio_dir
        existing["last_channel"] = _sfx.active_channel
        existing["version"] = _sfx.version
        existing["disabled_files"] = sorted(_sfx.disabled_files)
        persistent._sfx_editor_config = existing


    def _sfx_editor_load_config():
        """Load global settings from old config key."""
        config = getattr(persistent, '_sfx_editor_config', None)
        if config is None:
            return
        _sfx.audio_dir = config.get("audio_dir", "sfx_editor/audio")
        _sfx.active_channel = config.get("last_channel", None)
        _sfx.disabled_files = set(config.get("disabled_files", []))

        # Load unified markers from new key
        _sfx_editor_load_markers()


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

        # --- Top bar: copy + paste + dump + restore + refresh + close ---
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
            null width 5
            textbutton "💾":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_dump_markers)
                tooltip "Dump markers to file"
            textbutton "📂":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_restore_markers_from_file)
                tooltip "Restore markers from file"
            null width 5
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
        $ _is_video = _sfx.top_layer_type == 'movie'
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
                $ _vid_key = "v:" + _sfx.current_file if _sfx.current_file else ""
                $ _vid_entries = _sfx.markers.get(_vid_key, [])
                $ _vid_count = len(_vid_entries)
                null height 5
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                null height 5
                vbox:
                    spacing 5
                    text "Video Markers ([_vid_count])" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _vid_entries:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_video_markers)
                null height 5
                if _vid_entries:
                    vbox:
                        spacing 2
                        for i, entry in enumerate(_vid_entries):
                            for j, f in enumerate(entry["files"]):
                                hbox:
                                    spacing 5
                                    if j == 0:
                                        textbutton "✕":
                                            style "sfx_btn_icon"
                                            text_style "sfx_btn_icon_text"
                                            action Function(_sfx_editor_remove_video_marker, i)
                                        text _sfx_editor_format_time(entry["time"]) style "sfx_txt"
                                    else:
                                        text "      " style "sfx_txt" size 1
                                    text " " + f style "sfx_txt" color "#ffcc00" size 11
                                

        # --- Image UI ---
        $ _has_image = bool(_sfx.current_file) and not _is_video
        if _has_image:
            $ _img_key = "i:" + _sfx.current_file
            $ _img_entry = _sfx.markers.get(_img_key, {})
            $ _img_files = _img_entry.get("files", [])
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
                        if _img_files:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_image_markers)
                null height 5
                if _img_files:
                    vbox:
                        spacing 2
                        for i, f in enumerate(_img_files):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_image_marker, i)
                                text f style "sfx_txt" color "#ffcc00" size 11

        # --- Dialogue UI ---
        if _is_dialogue:
            $ _dlg_key = "d:" + _sfx.current_file + "|" + _sfx.current_dialogue
            $ _dlg_entry = _sfx.markers.get(_dlg_key, {})
            $ _dlg_files = _dlg_entry.get("files", [])
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
                        if _dlg_files:
                            textbutton "Clear":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_clear_dialogue_markers)
                null height 5
                if _dlg_files:
                    vbox:
                        spacing 2
                        for i, f in enumerate(_dlg_files):
                            hbox:
                                spacing 5
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_dialogue_marker, i)
                                text f style "sfx_txt" color "#ffcc00" size 11

        if _sfx.scan_error:
            text "[_sfx.scan_error]" style "sfx_help" color "#ff6666"

        null height 6

        # ================================================================
        # SFX POOL
        # ================================================================
        $ _pool_key = "p:" + (_sfx.current_file or "")
        $ _pool_entry = _sfx.markers.get(_pool_key, {})
        $ _pool_files = _pool_entry.get("files", [])
        $ _pool_freq = _pool_entry.get("frequency", 1)
        $ _pool_count = len(_pool_files)
        frame:
            background "#222222"
            padding (3, 3)
            xfill True
            yminimum 0
            has vbox

            text "SFX Pool ([_pool_count] / [_sfx.audio_count] files)" style "sfx_hdr"

            hbox:
                spacing 5
                text "SFX Frequency" style "sfx_txt"
                $ slow_selected = (_pool_freq == 0)
                $ normal_selected = (_pool_freq == 1)
                $ fast_selected = (_pool_freq == 2)
                textbutton "Slow":
                    style "sfx_btn_icon"
                    text_style "sfx_btn_icon_text"
                    xsize 38
                    if slow_selected:
                        background "#666699"
                    else:
                        background "#444444"
                    action Function(_sfx_editor_set_pool_frequency, _pool_key, 0)
                textbutton "Normal":
                    style "sfx_btn_icon"
                    text_style "sfx_btn_icon_text"
                    xsize 50
                    if normal_selected:
                        background "#669966"
                    else:
                        background "#444444"
                    action Function(_sfx_editor_set_pool_frequency, _pool_key, 1)
                textbutton "Fast":
                    style "sfx_btn_icon"
                    text_style "sfx_btn_icon_text"
                    xsize 38
                    if fast_selected:
                        background "#996666"
                    else:
                        background "#444444"
                    action Function(_sfx_editor_set_pool_frequency, _pool_key, 2)

            # Pool file list
            if _pool_files:
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
                        for i, filename in enumerate(_pool_files):
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
                                    if item.get("enabled", True):
                                        textbutton "☑":
                                            style "sfx_btn_icon"
                                            text_style "sfx_btn_icon_text"
                                            action Function(_sfx_editor_toggle_file_enabled, item["full_path"])
                                            tooltip "Click to exclude from markers"
                                    else:
                                        textbutton "☐":
                                            style "sfx_btn_icon"
                                            text_style "sfx_btn_icon_text"
                                            action Function(_sfx_editor_toggle_file_enabled, item["full_path"])
                                            tooltip "Click to include in markers"
                                    text item["name"] style "sfx_help"
                                else:
                                    textbutton "P":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_to_pool, item["index"])
                                        tooltip "Add to SFX Pool"
                                    if item.get("enabled", True):
                                        textbutton "☑":
                                            style "sfx_btn_icon"
                                            text_style "sfx_btn_icon_text"
                                            action Function(_sfx_editor_toggle_file_enabled, item["full_path"])
                                            tooltip "Click to exclude from markers"
                                    else:
                                        textbutton "☐":
                                            style "sfx_btn_icon"
                                            text_style "sfx_btn_icon_text"
                                            action Function(_sfx_editor_toggle_file_enabled, item["full_path"])
                                            tooltip "Click to include in markers"
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

