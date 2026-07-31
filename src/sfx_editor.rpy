###############################################################################
# SFX Video Overlay Editor v1.1.0
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

    _sfx.version = "1.1.0"

    # Context tracking
    _sfx.active_channel = None
    _sfx.current_file = ""
    _sfx.current_dialogue = ""
    _sfx.prev_dialogue = ""
    _sfx.channel_status = "No video"

    # User configuration
    _sfx.audio_dir = "sfx_editor/audio"
    _sfx.markers = {}          # Unified markers: trigger_key -> entry
    _sfx.clipboard = None

    # Volume constants (clamp range + UI quick-set targets)
    _sfx.VOL_MIN = 0.0       # clamp floor
    _sfx.VOL_DEFAULT = 1.0   # default volume; "--" reset target
    _sfx.VOL_MAX = 5.0       # clamp ceiling; "++" target

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

    # Video timestamp editing state
    _sfx.edit_video_ts_index = -1  # -1 = not editing; otherwise index into timestamps list
    _sfx.edit_video_ts_text = ""   # text buffer for the editable input

    # Multi-pool UI state: which pool the file-browser I/D/V buttons target
    _sfx.img_target_pool = 0
    _sfx.dlg_target_pool = 0
    _sfx.vid_target_pool = 0

    # Autosave backup throttle
    _sfx._last_autosave_time = 0

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
        # Detect Ren'Py version for relative_volume support (added in 7.5)
        _v = getattr(renpy, 'version_tuple', (0, 0, 0))
        _sfx._has_relative_volume = (_v >= (7, 5, 0))
        _sfx_log("INIT: renpy_version={} relative_volume={}".format(
            ".".join(str(x) for x in _v), _sfx._has_relative_volume))

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
        _sfx_log("INIT: overlay_screens key listener registered")

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
                _sfx.prev_dialogue = _sfx.current_dialogue
                _sfx.current_dialogue = getattr(store, '_last_say_what', '') or ''
            elif event == "end":
                _sfx.prev_dialogue = _sfx.current_dialogue
                _sfx.current_dialogue = ""
        config.all_character_callbacks.append(_sfx_editor_char_callback)

        # start_interact callback — detects context changes at interaction
        # boundaries (replaces the old 500ms poll in _sfx_editor_tick).
        def _sfx_editor_start_interact_callback(*args, **kwargs):
            _sfx_editor_refresh_detections()
        config.start_interact_callbacks.append(_sfx_editor_start_interact_callback)

        _sfx_log("INIT: callbacks registered")
        _sfx.initialized = True


###############################################################################
# SECTION 3: Core Python Functions
###############################################################################

init python:
    import os

    # --------------------------------------------------------------------------
    # Debug Logging
    # --------------------------------------------------------------------------

    def _sfx_log(msg):
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
        _sfx_editor_load_markers()
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
        _sfx_editor_save_markers()
        renpy.hide_screen("sfx_editor_overlay", layer="sfx_editor_layer")


    def _sfx_editor_refresh_detections():
        """Re-detect video and image, and swap context when they change."""

        old_file = _sfx.current_file
        old_video = _sfx.active_channel

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
        _sfx_log_context()

        # 4. If context changed, build trigger keys and fire
        _changed = ""
        _img_key = None
        _dlg_key = None
        if _sfx.current_file != old_file:
            _changed += " file:{}->{}".format(old_file, _sfx.current_file)
            _img_key = "i:" + _sfx.current_file if _sfx.current_file else None
        if _sfx.active_channel != old_video:
            _changed += " ch:{}->{}".format(old_video, _sfx.active_channel)
        if _sfx.current_dialogue != _sfx.prev_dialogue:
            _changed += " dlg:{}->{}".format(_sfx.prev_dialogue[:30] if _sfx.prev_dialogue else "",
                _sfx.current_dialogue[:30] if _sfx.current_dialogue else "")
        if _sfx.current_dialogue:
            _dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)

        if _changed:
            _sfx_log("CTX-CHANGE{}".format(_changed))
            # Rebuild visible tree so in_pool flags reflect new context
            if _sfx.current_file != old_file:
                _sfx.visible_tree = _sfx_editor_get_visible_tree()
            _sfx_editor_fire_context_triggers(_img_key, _dlg_key)


    def _sfx_log_context():
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
        _sfx_log("CTX-DUMP ctx={} type={} video={} ch={} playing={} dlg=\"{}\"".format(
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
        Multi-pool entries play one random file from EACH pool concurrently.
        Dedupe guard: same file in two pools of the same trigger is re-picked
        up to 3 times, then skipped to avoid echo artifacts."""
        import random as _random
        for key in keys:
            if not key:
                continue
            entry = _sfx.markers.get(key)
            if not entry:
                continue
            pools = _sfx_editor_get_pools(entry)
            if not pools:
                continue
            _vol = entry.get("volume", 1.0)
            _total = sum(len(p.get("files", [])) for p in pools)
            _sfx_log("CTX-TRIGGER key={} pools={} files={} vol={:.2f}".format(
                key, len(pools), _total, _vol))
            _picked = []
            for pool in pools:
                files = pool.get("files", [])
                if not files:
                    continue
                _file = _sfx_editor_pick_file(files, key)
                _tries = 0
                while _file in _picked and len(files) > 1 and _tries < 3:
                    _file = _sfx_editor_pick_file(files, key)
                    _tries += 1
                if _file in _picked:
                    continue
                _picked.append(_file)
                _pool_vol = pool.get("volume", entry.get("volume", 1.0))
                _sfx_editor_play_sfx(_file, key, volume=_pool_vol)


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
            _sfx_log("TOP-LAYER-ERR {}".format(repr(exc)))
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
                _sfx_log("pause: origin={:.3f}".format(_sfx.__pause_origin))
            else:  # Just unpaused
                _sfx.__total_offset = 0.0
                _sfx_log("unpause: reset offset")
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
            _sfx_log("+f step_target={:.3f}".format(_sfx.__step_target))
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
            _sfx_log(
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
            _sfx_log("+coarse step_target={:.3f}".format(_sfx.__step_target))
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
            _sfx_log(
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
        """Check if a file is in the current context's p: entry."""
        if not _sfx.current_file:
            return False
        pool_key = "p:" + _sfx.current_file
        entry = _sfx.markers.get(pool_key)
        if entry and full_path in entry.get("files", []):
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
        """Add all files under a folder as image markers for current image.
        Adds to the currently targeted image pool."""
        if not _sfx.current_file:
            return
        img_key = "i:" + _sfx.current_file
        pool = _sfx_editor_ensure_pool(img_key, _sfx.img_target_pool)
        files = pool.setdefault("files", [])
        for f in _sfx.available_files:
            if f.startswith(folder_path) and f not in files and f not in _sfx.disabled_files:
                files.append(f)
        _sfx_editor_save_markers()

    def _sfx_editor_add_folder_to_dialogue_markers(folder_path):
        """Add all files under a folder as dialogue markers for current image+dialogue.
        Adds to the currently targeted dialogue pool."""
        if not _sfx.current_dialogue:
            return
        dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        pool = _sfx_editor_ensure_pool(dlg_key, _sfx.dlg_target_pool)
        files = pool.setdefault("files", [])
        for f in _sfx.available_files:
            if f.startswith(folder_path) and f not in files and f not in _sfx.disabled_files:
                files.append(f)
        _sfx_editor_save_markers()

    def _sfx_editor_add_folder_to_video_markers(folder_path):
        """Add all files under a folder to the active video timestamp pool.
        Creates a new timestamp pool when none exist (requires playing video)."""
        if not _sfx.current_file:
            return
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.setdefault(vid_key, {"timestamps": []})
        timestamps = entry.setdefault("timestamps", [])
        target = _sfx.vid_target_pool
        if timestamps and 0 <= target < len(timestamps):
            # Add to existing active timestamp pool
            pool_files = timestamps[target].setdefault("files", [])
            for f in _sfx.available_files:
                if f.startswith(folder_path) and f not in pool_files and f not in _sfx.disabled_files:
                    pool_files.append(f)
        else:
            # Create new timestamp at current time (requires playing video)
            ch = _sfx.active_channel
            if not ch or not renpy.music.is_playing(channel=ch):
                return
            elapsed = _sfx_editor_get_elapsed()
            if elapsed is None or elapsed <= 0:
                return
            new_files = []
            for f in _sfx.available_files:
                if f.startswith(folder_path) and f not in _sfx.disabled_files:
                    new_files.append(f)
            if new_files:
                timestamps.append({"time": elapsed, "files": new_files})
                timestamps.sort(key=lambda e: e["time"])
                _sfx.vid_target_pool = len(timestamps) - 1
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

    def _sfx_editor_preview_sfx(filename, volume=1.0):
        """Play a preview of an SFX file. Restarts interaction to consume click.
        volume: 0.0-5.0, applied to the channel after play starts.
        """
        _sfx_editor_play_sfx(filename, "preview", volume=volume)
        renpy.restart_interaction()

    def _sfx_editor_play_sfx(filename, source="", volume=1.0):
        """Play an SFX on the next available dedicated channel.
        source: descriptive key for logging (video, image, dialogue, or pool)
        volume: 0.0-1.0, applied to the channel after play starts
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
                _sfx_log("WARN CTX-MISMATCH file={} src={} {}".format(
                    filename.rsplit("/", 1)[-1], source, _warn))

            if _sfx._has_relative_volume:
                renpy.music.play(full_path, channel=target_ch, loop=False, relative_volume=volume)
            else:
                renpy.music.play(full_path, channel=target_ch, loop=False)
                renpy.music.set_volume(volume, delay=0, channel=target_ch)
                _sfx_log("PLAY-SFX file={} src={} ch={} vol={:.2f}".format(
                    filename.rsplit("/", 1)[-1], source, target_ch, volume))
            return target_ch
        except Exception:
            return None


    # --------------------------------------------------------------------------
    # Multi-Pool Helpers (normalize, access, create, prune)
    # --------------------------------------------------------------------------

    def _sfx_editor_normalize_entry(entry):
        """Migrate legacy {'files': [...]} to {'pools': [{'files': [...]}]} in place.
        Preserves entry-level keys (volume, frequency, etc.)."""
        if not isinstance(entry, dict):
            return entry
        if "pools" not in entry:
            entry["pools"] = [{"files": entry.pop("files", [])}]
        return entry

    def _sfx_editor_unwrap_persistent(data):
        """Recursively convert Ren'Py RevertableDict/RevertableList wrappers
        to plain Python dict/list. Duck-typing avoids isinstance which fails
        on wrapped types; json.dumps also fails for the same reason.
        Strings/basestrings must be guarded — they are iterable."""
        if isinstance(data, (str, bytes)):
            return data
        try:
            if isinstance(data, unicode):  # Python 2 only
                return data
        except NameError:
            pass
        if hasattr(data, "items") and hasattr(data, "keys"):
            return {k: _sfx_editor_unwrap_persistent(v) for k, v in data.items()}
        if hasattr(data, "__iter__"):
            return [_sfx_editor_unwrap_persistent(v) for v in data]
        return data

    def _sfx_editor_normalize_all_markers():
        """Migrate all legacy i: and d: entries to pools format and persist."""
        changed = False
        for key, entry in list(_sfx.markers.items()):
            if key.startswith(("i:", "d:")):
                _sfx_editor_normalize_entry(entry)
                changed = True
        return changed

    def _sfx_editor_get_pools(entry):
        """Return the list of pool dicts for an entry.
        New format: entry['pools'] is a list of {'files': [...]} dicts.
        Legacy format: entry['files'] is wrapped as one pool by reference.
        Returns [] for non-dict entries and empty dicts."""
        if not isinstance(entry, dict):
            return []
        pools = entry.get("pools")
        if isinstance(pools, list):
            return [p for p in pools if isinstance(p, dict)]
        files = entry.get("files")
        if isinstance(files, list):
            return [{"files": files}]
        return []

    def _sfx_editor_get_or_create_entry(trigger_key):
        """Get the entry dict for trigger_key, creating it in pools format if
        needed. Migrates legacy {'files': [...]} entries in place."""
        entry = _sfx.markers.get(trigger_key)
        if entry is None:
            entry = {"pools": []}
            _sfx.markers[trigger_key] = entry
        return _sfx_editor_normalize_entry(entry)

    def _sfx_editor_ensure_pool(trigger_key, pool_index):
        """Return the pool dict at pool_index for trigger_key, creating the
        entry/pools as needed. Clamps an out-of-range pool_index to the last
        existing pool; creates pool 0 when no pools exist yet."""
        entry = _sfx_editor_get_or_create_entry(trigger_key)
        pools = entry["pools"]
        if not pools:
            pools.append({
                "files": [],
                "volume": entry.get("volume", _sfx.VOL_DEFAULT),
            })
        if pool_index < 0:
            pool_index = 0
        if pool_index >= len(pools):
            pool_index = len(pools) - 1
        return pools[pool_index]

    def _sfx_editor_add_pool(trigger_key, kind="img"):
        """Append a new empty pool and auto-switch target to it."""
        entry = _sfx_editor_get_or_create_entry(trigger_key)
        entry["pools"].append({
            "files": [],
            "volume": entry.get("volume", _sfx.VOL_DEFAULT),
        })
        new_idx = len(entry["pools"]) - 1
        if kind == "dlg":
            _sfx.dlg_target_pool = new_idx
        else:
            _sfx.img_target_pool = new_idx
        _sfx_editor_save_markers()
        renpy.restart_interaction()

    def _sfx_editor_remove_pool(trigger_key, pool_index, kind="img"):
        """Delete a pool; delete the entry when no pools remain.
        Clamps target-pool index so the highlight stays valid."""
        entry = _sfx.markers.get(trigger_key)
        if not isinstance(entry, dict):
            return
        pools = entry.get("pools")
        if not isinstance(pools, list) or not (0 <= pool_index < len(pools)):
            return
        pools.pop(pool_index)
        if not pools:
            del _sfx.markers[trigger_key]
        # Keep target-pool valid
        remaining = len(pools)
        if kind == "dlg":
            if remaining:
                _sfx.dlg_target_pool = min(_sfx.dlg_target_pool, remaining - 1)
            else:
                _sfx.dlg_target_pool = 0
        else:
            if remaining:
                _sfx.img_target_pool = min(_sfx.img_target_pool, remaining - 1)
            else:
                _sfx.img_target_pool = 0
        _sfx_editor_save_markers()
        renpy.restart_interaction()

    def _sfx_editor_set_target_pool(kind, pool_index):
        """Set which pool the file-browser I/D buttons add to."""
        if kind == "dlg":
            _sfx.dlg_target_pool = int(pool_index)
        else:
            _sfx.img_target_pool = int(pool_index)
        renpy.restart_interaction()

    # --------------------------------------------------------------------------
    # Unified Marker CRUD
    # --------------------------------------------------------------------------

    def _sfx_editor_marker_add_file(trigger_key, filename, pool_index=0):
        """Append a file to a specific pool. Creates the entry/pool if needed."""
        pool = _sfx_editor_ensure_pool(trigger_key, pool_index)
        files = pool.setdefault("files", [])
        if filename not in files:
            files.append(filename)
        _sfx_editor_save_markers()

    def _sfx_editor_marker_remove_file(trigger_key, file_index, pool_index=0):
        """Remove a file from a pool. Prunes pool when empty and entry when
        last pool is gone. Legacy entries (p: callers) use the files branch."""
        entry = _sfx.markers.get(trigger_key)
        if not isinstance(entry, dict):
            return
        pools = entry.get("pools")
        if isinstance(pools, list):
            if not (0 <= pool_index < len(pools)):
                return
            pool = pools[pool_index]
            files = pool.get("files", [])
            if 0 <= file_index < len(files):
                files.pop(file_index)
            if not files:
                pools.pop(pool_index)
            if not pools:
                del _sfx.markers[trigger_key]
            _sfx_editor_save_markers()
        elif "files" in entry:
            # Legacy path — p: entries and any un-migrated entries
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
        """Add a file to the active timestamp pool. Creates a new timestamp
        if no timestamps exist yet or the active target is out of range."""
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
        entry = _sfx.markers.setdefault(vid_key, {"timestamps": []})
        timestamps = entry.setdefault("timestamps", [])
        target = _sfx.vid_target_pool
        if timestamps and 0 <= target < len(timestamps):
            # Add to existing active timestamp
            files = timestamps[target].setdefault("files", [])
            if filename not in files:
                files.append(filename)
        else:
            # Create new timestamp at current time
            timestamps.append({"time": elapsed, "files": [filename]})
            timestamps.sort(key=lambda e: e["time"])
            _sfx.vid_target_pool = len(timestamps) - 1
        _sfx_editor_save_markers()

    def _sfx_editor_clear_video_markers():
        """Remove video markers for the current context."""
        vid_key = "v:" + _sfx.current_file
        _sfx.markers.pop(vid_key, None)
        _sfx.played_video_keys = set()
        _sfx.vid_target_pool = 0
        _sfx_editor_save_markers()

    def _sfx_editor_start_edit_video_ts():
        """Begin editing the active video timestamp."""
        index = _sfx.vid_target_pool
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if 0 <= index < len(timestamps):
            _sfx.edit_video_ts_index = index
            _sfx.edit_video_ts_text = _sfx_editor_format_time(timestamps[index]["time"])
            renpy.restart_interaction()

    def _sfx_editor_commit_video_ts():
        """Parse the edit text and update the active video timestamp.
        Tracks the active tab after re-sort."""
        index = _sfx.edit_video_ts_index
        if index < 0:
            return
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if index >= len(timestamps):
            _sfx.edit_video_ts_index = -1
            return
        new_time = _sfx_editor_parse_time(_sfx.edit_video_ts_text)
        if new_time is not None and new_time >= 0:
            edited_entry = timestamps[index]
            edited_entry["time"] = new_time
            timestamps.sort(key=lambda e: e["time"])
            # Track the edited entry to its new position
            try:
                _sfx.vid_target_pool = timestamps.index(edited_entry)
            except ValueError:
                _sfx.vid_target_pool = min(index, len(timestamps) - 1)
            _sfx.played_video_keys = set()
            _sfx_editor_save_markers()
        # Clear editing state regardless of success/failure
        _sfx.edit_video_ts_index = -1
        _sfx.edit_video_ts_text = ""
        renpy.restart_interaction()

    def _sfx_editor_cancel_edit_video_ts():
        """Cancel editing the video timestamp."""
        _sfx.edit_video_ts_index = -1
        _sfx.edit_video_ts_text = ""
        renpy.restart_interaction()

    def _sfx_editor_start_edit_video_ts_by_index(index):
        """Begin editing the video timestamp at the given index (for non-active tabs)."""
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if 0 <= index < len(timestamps):
            _sfx.edit_video_ts_index = index
            _sfx.edit_video_ts_text = _sfx_editor_format_time(timestamps[index]["time"])
            renpy.restart_interaction()

    def _sfx_editor_set_vid_target_pool(pool_index):
        """Set which timestamp pool tab is active."""
        _sfx.vid_target_pool = int(pool_index)
        renpy.restart_interaction()

    def _sfx_editor_add_video_pool():
        """Create a new empty timestamp at current elapsed time.
        Auto-switches vid_target_pool to the new timestamp."""
        ch = _sfx.active_channel
        if not ch or not renpy.music.is_playing(channel=ch):
            return
        elapsed = _sfx_editor_get_elapsed()
        if elapsed is None or elapsed <= 0:
            return
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.setdefault(vid_key, {"timestamps": []})
        timestamps = entry.setdefault("timestamps", [])
        timestamps.append({"time": elapsed, "files": []})
        timestamps.sort(key=lambda e: e["time"])
        _sfx.vid_target_pool = len(timestamps) - 1
        _sfx_editor_save_markers()
        renpy.restart_interaction()

    def _sfx_editor_remove_video_pool(ts_index):
        """Delete a timestamp pool by index. Clamps vid_target_pool."""
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if not (0 <= ts_index < len(timestamps)):
            return
        timestamps.pop(ts_index)
        if not timestamps:
            del _sfx.markers[vid_key]
            _sfx.vid_target_pool = 0
        else:
            _sfx.vid_target_pool = min(_sfx.vid_target_pool, len(timestamps) - 1)
        _sfx.played_video_keys = set()
        _sfx_editor_save_markers()
        renpy.restart_interaction()

    def _sfx_editor_remove_video_file(ts_index, file_index):
        """Remove a single file from a timestamp's files list.
        Keeps the timestamp even if files becomes empty."""
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        if not (0 <= ts_index < len(timestamps)):
            return
        files = timestamps[ts_index].get("files", [])
        if 0 <= file_index < len(files):
            files.pop(file_index)
            _sfx.played_video_keys = set()
            _sfx_editor_save_markers()
            renpy.restart_interaction()

    def _sfx_editor_set_video_volume(value):
        """Set volume on the active timestamp."""
        vid_key = "v:" + _sfx.current_file
        _sfx_editor_write_volume(vid_key, value, ts_index=_sfx.vid_target_pool)

    def _sfx_editor_adjust_video_volume(delta):
        """Adjust volume on the active timestamp."""
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key)
        if entry is None:
            return
        current = _sfx_editor_get_volume(entry, vid_key, ts_index=_sfx.vid_target_pool)
        _sfx_editor_write_volume(vid_key, current + delta, ts_index=_sfx.vid_target_pool)

    def _sfx_editor_nudge_video_ts(delta):
        """Nudge the active timestamp's time by delta seconds.
        If currently editing, updates both the text buffer and the entry."""
        vid_key = "v:" + _sfx.current_file
        entry = _sfx.markers.get(vid_key, {})
        timestamps = entry.get("timestamps", [])
        index = _sfx.vid_target_pool
        if not (0 <= index < len(timestamps)):
            return
        ts_entry = timestamps[index]
        new_time = max(0.0, ts_entry["time"] + delta)
        ts_entry["time"] = new_time
        timestamps.sort(key=lambda e: e["time"])
        # Track the entry to its new position after sort
        try:
            _sfx.vid_target_pool = timestamps.index(ts_entry)
        except ValueError:
            pass
        # Keep edit buffer in sync if currently editing this timestamp
        if _sfx.edit_video_ts_index == index:
            _sfx.edit_video_ts_text = _sfx_editor_format_time(new_time)
        _sfx.played_video_keys = set()
        _sfx_editor_save_markers()
        renpy.restart_interaction()

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
        _sfx_editor_marker_add_file(img_key, filename, _sfx.img_target_pool)

    def _sfx_editor_remove_image_marker(pool_index, file_index):
        """Remove a file from a specific pool in the i: entry."""
        img_key = "i:" + _sfx.current_file
        _sfx_editor_marker_remove_file(img_key, file_index, pool_index)

    def _sfx_editor_clear_image_markers():
        """Remove image markers for the current context."""
        img_key = "i:" + _sfx.current_file
        _sfx.markers.pop(img_key, None)
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
        _sfx_editor_marker_add_file(dlg_key, filename, _sfx.dlg_target_pool)

    def _sfx_editor_remove_dialogue_marker(pool_index, file_index):
        """Remove a file from a specific pool in the d: entry."""
        dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        _sfx_editor_marker_remove_file(dlg_key, file_index, pool_index)

    def _sfx_editor_clear_dialogue_markers():
        """Remove dialogue markers for the current context."""
        dlg_key = "d:{}|{}".format(_sfx.current_file, _sfx.current_dialogue)
        _sfx.markers.pop(dlg_key, None)
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
        """Remove pool markers for the current context."""
        pool_key = "p:" + _sfx.current_file
        _sfx.markers.pop(pool_key, None)
        _sfx.pool_states.pop(pool_key, None)
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
        import copy as _copy
        ctx_file = _sfx.current_file or ""
        ctx_dlg = _sfx.current_dialogue or ""
        copied = {}
        for key, entry in _sfx.markers.items():
            if key.startswith("i:") and key[2:] == ctx_file:
                copied[key] = _copy.deepcopy(entry)
            elif key.startswith("d:") and key[2:].startswith(ctx_file + "|"):
                copied[key] = _copy.deepcopy(entry)
            elif key.startswith(("p:", "v:")) and key[2:] == ctx_file:
                copied[key] = _copy.deepcopy(entry)
        _sfx.clipboard = {
            "markers": copied,
            "source_file": ctx_file,
            "source_dialogue": ctx_dlg,
        }

    def _sfx_editor_paste_context():
        """Paste clipboard markers into current context, remapping keys."""
        import copy as _copy
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
                _sfx.markers[new_key] = _copy.deepcopy(entry)
        _sfx.played_video_keys = set()
        _sfx.pool_states = {}
        _sfx_editor_save_markers()

    def _sfx_editor_dump_markers():
        """Dump entire persistent._sfx_editor_markers to sfx_editor/sfx_editor_config.json."""
        try:
            import json as _json
            dump_dir = os.path.join(renpy.config.gamedir, "sfx_editor")
            if not os.path.isdir(dump_dir):
                os.makedirs(dump_dir)
            dump_path = os.path.join(dump_dir, "sfx_editor_config.json")
            data = getattr(persistent, '_sfx_editor_markers', None)
            if data is None:
                # Ensure current state is saved before dumping
                _sfx_editor_save_markers()
                data = getattr(persistent, '_sfx_editor_markers', {})
            with open(dump_path, "w") as f:
                _json.dump(data, f, indent=2, sort_keys=True)
            _sfx_log("DUMP-MARKERS total_keys={} path=sfx_editor_config.json".format(
                len(_sfx.markers)))
        except Exception as e:
            _sfx_log("DUMP-MARKERS-ERROR {}".format(str(e)))

    def _sfx_editor_restore_markers_from_file():
        """Restore persistent._sfx_editor_markers from sfx_editor/sfx_editor_config.json."""
        try:
            import json as _json
            dump_path = os.path.join(renpy.config.gamedir, "sfx_editor", "sfx_editor_config.json")
            if not os.path.isfile(dump_path):
                _sfx_log("RESTORE-MARKERS-NO-FILE path=sfx_editor_config.json")
                return
            with open(dump_path, "r") as f:
                data = _json.load(f)
            persistent._sfx_editor_markers = data
            _sfx.markers = dict(data.get("markers", {}))
            _sfx.played_video_keys = set()
            _sfx.pool_states = {}
            #_sfx_editor_normalize_all_markers()
            _sfx_editor_save_markers()
            _sfx_log("RESTORE-MARKERS total_keys={} path=sfx_editor_config.json".format(
                len(_sfx.markers)))
        except Exception as e:
            _sfx_log("RESTORE-MARKERS-ERROR {}".format(str(e)))


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


    def _sfx_editor_get_volume(entry, trigger_key=None, pool_index=None, ts_index=None):
        """Current volume for the target: pool-level with entry-level fallback.
        v: keys read the specified ts_index (falls back to first timestamp).
        Returns _sfx.VOL_DEFAULT if unset."""
        if trigger_key is not None and trigger_key.startswith("v:"):
            timestamps = entry.get("timestamps", [])
            if timestamps:
                idx = ts_index if ts_index is not None else 0
                if 0 <= idx < len(timestamps):
                    return timestamps[idx].get("volume", _sfx.VOL_DEFAULT)
                if timestamps:
                    return timestamps[0].get("volume", _sfx.VOL_DEFAULT)
        if pool_index is not None:
            pools = entry.get("pools")
            if isinstance(pools, list) and 0 <= pool_index < len(pools):
                return pools[pool_index].get("volume",
                    entry.get("volume", _sfx.VOL_DEFAULT))
        return entry.get("volume", _sfx.VOL_DEFAULT)

    def _sfx_editor_write_volume(trigger_key, new_vol, pool_index=None, ts_index=None):
        """Clamp and persist a volume, then save + refresh.
        v: keys with ts_index write that specific timestamp; without ts_index
        broadcast to all timestamps (backward-compatible).
        i:/d: with pool_index write that pool; otherwise entry-level."""
        entry = _sfx.markers.get(trigger_key)
        if entry is None:
            return
        new_vol = max(_sfx.VOL_MIN, min(_sfx.VOL_MAX, round(new_vol, 1)))
        if trigger_key.startswith("v:"):
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
                if isinstance(pools, list) and 0 <= pool_index < len(pools):
                    target = pools[pool_index]
            if target is None:
                target = entry
            target["volume"] = new_vol
        _sfx_editor_save_markers()
        renpy.restart_interaction()

    def _sfx_editor_adjust_volume(trigger_key, delta, pool_index=None):
        """Adjust volume up/down by delta, clamped to [VOL_MIN, VOL_MAX].
        pool_index targets one pool for i:/d: entries; None = entry-level."""
        entry = _sfx.markers.get(trigger_key)
        if entry is None:
            return
        current = _sfx_editor_get_volume(entry, trigger_key, pool_index)
        _sfx_editor_write_volume(trigger_key, current + delta, pool_index)

    def _sfx_editor_set_volume(trigger_key, value, pool_index=None):
        """Set volume to an absolute value, clamped.
        -- = VOL_DEFAULT, ++ = VOL_MAX. pool_index same as adjust."""
        _sfx_editor_write_volume(trigger_key, value, pool_index)


    # --------------------------------------------------------------------------
    # SFX Trigger Engine (Tick)
    # --------------------------------------------------------------------------

    def _sfx_editor_tick_trigger():
        """SFX trigger engine — runs always (even when overlay is hidden)."""
        import random as _random
        import time as _time

        _sfx_editor_tick()

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
                        _sfx_log("TICK#{} POOL-DONE  key={} dur={:.2f}s next_in={:.2f}s".format(
                            tick, pool_key, dur, breathing))

                if ps["state"] == 0:
                    if ps["ready_at"] == 0:
                        ps["ready_at"] = now + 0.5
                    elif now >= ps["ready_at"]:
                        f = _sfx_editor_pick_file(files, pool_key)
                        _vol = entry.get("volume", 1.0)
                        ch_used = _sfx_editor_play_sfx(f, pool_key, volume=_vol)
                        if ch_used:
                            ps["state"] = 1
                            ps["ch"] = ch_used
                            ps["play_start"] = now
                            _sfx_log("TICK#{} POOL-PLAY  key={} file={} ch={}".format(
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
                vid_entry = _sfx.markers.get(vid_key)
                if vid_entry:
                    timestamps = vid_entry.get("timestamps", [])
                    for idx, ts_entry in enumerate(timestamps):
                        ts_key = "{}@{}".format(vid_key, idx)
                        if ts_key not in _sfx.played_video_keys:
                            mt = ts_entry["time"]
                            if mt <= elapsed < mt + _sfx.__marker_tolerance:
                                files = ts_entry.get("files", [])
                                if files:
                                    _vsrc = "vid:{}@{:.2f}".format(_sfx.current_file, mt)
                                    f = _sfx_editor_pick_file(files, vid_key, avoid_repeats=False)
                                    _vol = ts_entry.get("volume", 1.0)
                                    _sfx_editor_play_sfx(f, _vsrc, volume=_vol)
                                    _sfx.played_video_keys.add(ts_key)

            # Detect video loop (markers only, pool uses wall clock)
            if _sfx.__last_pos > 0 and elapsed < _sfx.__last_pos - 0.3:
                _sfx.played_video_keys.clear()
            _sfx.__last_pos = elapsed


    def _sfx_editor_tick():
        """Updates time display, checks markers, and drives pool mode.
        """

        if not _sfx.visible:
            return

        _sfx.audio_count = len(_sfx.available_files)
        _sfx.marker_count = len(_sfx.markers)

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

    def _sfx_editor_autosave_backup():
        """Create a timestamped backup of markers in sfx_editor/backups/.

        Throttled to once every 5 minutes. Maintains a max of 10 backups,
        deleting the oldest when the limit is reached.

        Called from _sfx_editor_save_markers() after every successful save.
        All exceptions are swallowed — autosave must never break the editor."""
        try:
            import time as _time
            import json as _json

            # Throttle: skip if last autosave was within 5 minutes
            _now = _time.time()
            if _now - _sfx._last_autosave_time < 300:
                return

            backups_dir = os.path.join(renpy.config.gamedir, "sfx_editor", "backups")
            if not os.path.isdir(backups_dir):
                os.makedirs(backups_dir)

            # List existing backups sorted by mtime (oldest first)
            _files = [f for f in os.listdir(backups_dir)
                      if f.startswith("sfx_editor_backup_") and f.endswith(".json")]
            _files.sort(key=lambda f: os.path.getmtime(
                os.path.join(backups_dir, f)))

            # Rotate: delete oldest if at the max
            MAX_BACKUPS = 10
            while len(_files) >= MAX_BACKUPS:
                _oldest = _files.pop(0)
                try:
                    os.remove(os.path.join(backups_dir, _oldest))
                except Exception:
                    pass

            # Write backup with unix timestamp suffix
            _ts = int(_now)
            _name = "sfx_editor_backup_{}.json".format(_ts)
            _path = os.path.join(backups_dir, _name)
            with open(_path, "w") as f:
                _json.dump(persistent._sfx_editor_markers, f,
                           indent=2, sort_keys=True)

            _sfx._last_autosave_time = _now
            _sfx_log("AUTOSAVE-BACKUP path={} marker_keys={}".format(
                _name, len(_sfx.markers)))
        except Exception:
            pass  # Never let autosave break the editor

    def _sfx_editor_save_markers():
        """Save unified markers and disabled_files to persistent storage.

        Refuses to overwrite existing persistent marker data with an empty dict.
        This guards against auto-reload wiping markers: init -999 clears
        _sfx.markers in RAM, and if load fails for any reason (syntax error,
        split-file ordering, etc.), a subsequent save would otherwise persist
        the empty state and destroy all marker data.

        disabled_files is always written regardless of the marker guard."""
        data = {
            "version": "2.2.0",
            "disabled_files": sorted(_sfx.disabled_files),
        }

        if not _sfx.markers:
            existing = getattr(persistent, '_sfx_editor_markers', None)
            if existing is not None and existing.get("markers"):
                _sfx_log("SAVE-MARKERS: refusing to clobber {} existing keys with empty dict".format(
                    len(existing["markers"])))
                data["markers"] = existing["markers"]
            else:
                data["markers"] = {}
        else:
            data["markers"] = dict(_sfx.markers)

        persistent._sfx_editor_markers = data

        # Autosave backup to disk (throttled to once per 5 min)
        _sfx_editor_autosave_backup()


    def _sfx_editor_load_markers():
        """Load markers and disabled_files from persistent storage.
        Unwraps Ren'Py RevertableDict/RevertableList via JSON round-trip
        so that isinstance checks work on the loaded data."""
        data = getattr(persistent, '_sfx_editor_markers', None)
        if data is None:
            _sfx.markers = {}
            return
        _sfx.markers = _sfx_editor_unwrap_persistent(data.get("markers", {}))
        _sfx.disabled_files = set(data.get("disabled_files", []))
        #_sfx_editor_normalize_all_markers()
        _sfx_log("LOAD-MARKERS total_keys={} keys={}".format(
            len(_sfx.markers), list(_sfx.markers.keys())[:20]))



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


    def _sfx_editor_parse_time(time_str):
        """Parse a time string back to float seconds.

        Accepts:
          - "MM:SS.cs"   (e.g. "01:23.45" -> 83.45)
          - "HH:MM:SS.cs" (e.g. "01:02:03.45" -> 3723.45)
          - Raw number as string (e.g. "90.5" -> 90.5)

        Returns None if the string cannot be parsed.
        """
        if time_str is None:
            return None
        # Accept both str and unicode (Py2) / str (Py3)
        try:
            time_str = time_str.strip()
        except AttributeError:
            return None
        if not time_str:
            return None

        # Try raw float
        try:
            val = float(time_str)
            if val >= 0:
                return val
        except ValueError:
            pass

        # Try MM:SS.cs or HH:MM:SS.cs
        parts = time_str.split(":")
        if len(parts) < 2 or len(parts) > 3:
            return None

        try:
            if len(parts) == 2:
                # MM:SS.cs
                minutes = int(parts[0])
                sec_part = parts[1].replace(",", ".")  # accept both . and , as decimal
                seconds = float(sec_part)
                return minutes * 60.0 + seconds
            else:
                # HH:MM:SS.cs
                hours = int(parts[0])
                minutes = int(parts[1])
                sec_part = parts[2].replace(",", ".")
                seconds = float(sec_part)
                return hours * 3600.0 + minutes * 60.0 + seconds
        except (ValueError, IndexError):
            return None


# =============================================================================
# KEY-LISTENER SCREEN: Always-visible invisible screen that catches backtick
# =============================================================================

screen sfx_editor_key_listener():
    zorder 10000
    key "K_BACKQUOTE" action Function(_sfx_editor_toggle)
    timer 0.05 repeat True action Function(_sfx_editor_tick_trigger)

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
    key "K_1" action Function(_sfx_editor_copy_context)
    key "K_2" action Function(_sfx_editor_paste_context)
    # Timer to drive the SFX trigger engine
    #timer 0.05 repeat True action Function(_sfx_editor_tick_trigger)

    button:
        xalign 0.0
        yalign 0.0
        xsize 500
        yfill True
        action NullAction()
        background None
        hover_background None
        frame:
            style "sfx_frame"
            xfill True
            yfill True
            use sfx_editor_sidebar_content()

    # --- Floating tooltip near mouse ---
    $ _tt = GetTooltip()
    if _tt:
        $ _mx, _my = renpy.get_mouse_pos()
        frame:
            background "#2a2a2a"
            padding (4, 2)
            xpos (_mx + 12)
            ypos (_my - 8)
            xmaximum 300
            ysize 22
            text _tt substitute False:
                style "sfx_txt"
                size 11
                color "#cccccc"
                italic True

