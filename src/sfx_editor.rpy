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

    # Context tracking
    _sfx.active_channel = None
    _sfx.current_file = ""
    _sfx.current_dialogue = ""
    _sfx.prev_dialogue = ""

    # User configuration
    _sfx.audio_dir = "sfx_editor/audio"
    _sfx.markers = {}          # Unified markers: trigger_key -> entry
    _sfx.clipboard = None

    # Volume constants (clamp range + UI quick-set targets)
    _sfx.VOL_MIN = 0.0       # clamp floor
    _sfx.VOL_DEFAULT = 1.0   # default volume; "--" reset target
    _sfx.VOL_MAX = 5.0       # clamp ceiling; "++" target

    # Key prefix constants for _sfx.markers trigger keys
    _sfx.IMG_KEY_PREFIX = "i:"
    _sfx.AUTOPLAY_KEY_PREFIX = "a:"
    _sfx.DLG_KEY_PREFIX = "d:"
    _sfx.VID_KEY_PREFIX = "v:"

    # Trigger tracking
    _sfx.played_video_keys = set()
    _sfx.__last_pos = 0.0

    # Pool state machine (multi-instance: one per active a: key)
    _sfx.pool_states = {}
    
    _sfx.triggers_active = True

    # Video seek/pause state
    _sfx.paused = False
    _sfx.fps = 30
    _sfx.__frame_time = 1.0 / 30.0
    _sfx.__time_offset = 0.0
    _sfx.__step_target = 0.0
    _sfx.__pause_target = 0.0
    _sfx.__pause_origin = 0.0
    _sfx.__total_offset = 0.0
    _sfx.__cached_dur = 0.0

    # UI state
    _sfx.visible = False
    _sfx.initialized = False
    _sfx.visible_tree = []
    _sfx.expanded_folders = {}
    _sfx.scan_error = None

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

    # Internal
    _sfx.__sfx_channel_idx = 0
    _sfx.__marker_tolerance = 0.08
    _sfx.__refreshing = False
    _sfx._shake_just_happened = False


###############################################################################
# SECTION 2: Init Block (init 999 python)
###############################################################################

init 999 python:
    # Enable dev tools for this mod (Shift+R reload, Shift+O console)
    config.developer = True
    config.console = True

    # Path constants
    _sfx.base_dir = "sfx_editor"
    _sfx.config_filename = "sfx_editor_config.json"
    _sfx.config_path = os.path.join(renpy.config.gamedir, _sfx.base_dir, _sfx.config_filename)
    _sfx.debug_log_filename = "debug.log"

    # monkeypatch renpy.with_statement
    _original_with_statement = renpy.with_statement

    def _sfx_editor_with_hook(trans, always=False, paired=None, clear=True):
        if _is_screenshake(trans):
            _sfx._shake_just_happened = True
        return _original_with_statement(trans, always=always, paired=paired, clear=clear)

    renpy.with_statement = _sfx_editor_with_hook
    # monkeypatch renpy.with_statement

    def _is_screenshake(trans):
        import functools
        try:
            if trans is None:
                return False

            if not isinstance(trans, functools.partial):
                return False

            func_name = getattr(trans.func, "__name__", "")
            if func_name != "Move":
                return False

            kw = trans.keywords or {}
            return (
                kw.get("bounce", False) == True
                and kw.get("repeat", False) == True
                and kw.get("delay") is not None
                and kw.get("delay") < 0.5
            )
        except Exception:
            return False

    # Clear debug log for fresh session
    try:
        log_dir = os.path.join(renpy.config.gamedir, _sfx.base_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        log_path = os.path.join(log_dir, _sfx.debug_log_filename)
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

        # Load markers from persistent so SFX work immediately (before overlay is ever opened)
        _sfx_editor_load_markers()

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
            log_dir = os.path.join(renpy.config.gamedir, _sfx.base_dir)
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir)
            log_path = os.path.join(log_dir, _sfx.debug_log_filename)
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


    def _sfx_editor_toggle_active():
        """Toggle active state — when False, no triggers fire. Persisted.
        Called from Ctrl+` key binding and the Active checkbox."""
        _sfx.triggers_active = not _sfx.triggers_active
        _sfx_editor_save_markers()


    def _sfx_editor_toggle_shake_trigger():
        """Toggle trigger_on_shake for the active pool of the current image.
        When enabled, screen shake transitions play SFX from this pool."""
        if not _sfx.current_file:
            return
        _shake_key = create_img_key(_sfx.current_file)
        _pool = _sfx_editor_ensure_pool(_shake_key, _sfx.img_target_pool)
        _pool["trigger_on_shake"] = not _pool.get("trigger_on_shake", False)
        _sfx_editor_save_markers()


    def _sfx_editor_show():
        import time
        t0 = time.time()
        _sfx.visible = True
        # Load persisted config
        _sfx_editor_load_markers()
        # Scan audio on first open (cached thereafter)
        if not _sfx.available_files:
            _sfx_editor_scan_audio()
        # Rebuild visible tree
        _sfx.visible_tree = _sfx_editor_get_visible_tree()
        # Auto-detect everything
        _sfx_editor_refresh_detections()
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
        just_shaked = _sfx._shake_just_happened

        if _sfx.current_file != old_file:
            _changed += " file:{}->{}".format(old_file, _sfx.current_file)
            _img_key = create_img_key(_sfx.current_file) if _sfx.current_file else None
        if _sfx.active_channel != old_video:
            _changed += " ch:{}->{}".format(old_video, _sfx.active_channel)
        if _sfx.current_dialogue != _sfx.prev_dialogue:
            _changed += " dlg:{}->{}".format(_sfx.prev_dialogue[:30] if _sfx.prev_dialogue else "",
                _sfx.current_dialogue[:30] if _sfx.current_dialogue else "")
        if _sfx.current_dialogue:
            _dlg_key = create_dlg_key((_sfx.current_file, _sfx.current_dialogue))

        if _changed:
            _sfx_log("CTX-CHANGE{}".format(_changed))
            if _sfx.current_file != old_file:
                _sfx.visible_tree = _sfx_editor_get_visible_tree()
            _sfx_editor_fire_context_triggers(_img_key, _dlg_key)

        # 5. Screenshake trigger — fires independently of context changes,
        #    but only for pools that opted in via trigger_on_shake.
        #    
        #    Dedupe: when the image changed this interaction, _img_key already
        #    fired above (hitting all pools for the new image), so skip the
        #    shake call for the same key to avoid double-firing.
        #    When screen shakes on existing img, _img_key will be None since there
        #    was no img change, and the shake pools will trigger.
        if _sfx._shake_just_happened:
            _sfx._shake_just_happened = False
            if _sfx.current_file:
                _shake_key = create_img_key(_sfx.current_file)
                if _shake_key != _img_key:
                    _sfx_editor_fire_context_triggers(_shake_key, only_shake_pools=True)


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


    def _sfx_editor_pick_file(files, avoid_repeats=True):
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


    def _sfx_editor_fire_context_triggers(*keys, only_shake_pools=False):
        """Fire markers for the given trigger keys.
        Multi-pool entries play one random file from EACH pool concurrently.
        Dedupe guard: same file in two pools of the same trigger is re-picked
        up to 3 times, then skipped to avoid echo artifacts.

        When only_shake_pools is True, pool without the trigger_on_shake flag
        are skipped — used by screenshake triggers so each pool independently
        opts in to firing on shake."""
        import random as _random
        if not _sfx.triggers_active:
            return
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
            for pi, pool in enumerate(pools):
                if only_shake_pools and not pool.get("trigger_on_shake", False):
                    continue
                files = pool.get("files", [])
                if not files:
                    continue
                _file = _sfx_editor_pick_file(files)
                _tries = 0
                while _file in _picked and len(files) > 1 and _tries < 3:
                    _file = _sfx_editor_pick_file(files)
                    _tries += 1
                if _file in _picked:
                    continue
                _picked.append(_file)
                _pool_vol = _sfx_editor_get_effective_volume(entry, key, pool_index=pi)
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
                        _sfx.__refreshing = False
                        return
                except Exception:
                    pass

            _sfx.active_channel = None
        finally:
            _sfx.__refreshing = False


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
        """Get total duration of the current video in seconds.
        Caches the last valid duration so transient dropouts during seek
        (stop/play restart) don't return 0 and blow up marker x-positions."""
        ch = _sfx.active_channel
        if not ch:
            return _sfx.__cached_dur
        try:
            dur = renpy.music.get_duration(channel=ch)
            if dur is not None and dur > 0:
                _sfx.__cached_dur = dur
                return dur
        except Exception:
            pass
        return _sfx.__cached_dur


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


    # --------------------------------------------------------------------------
    # SFX Playback
    # --------------------------------------------------------------------------

    def _sfx_editor_preview_sfx(filename, volume=1.0):
        """Play a preview of an SFX file. Restarts interaction to consume click.
        volume: 0.0-5.0, applied to the channel after play starts.
        """
        _sfx_editor_play_sfx(filename, "preview", volume=volume)

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
            curr_file = _sfx.current_file
            _warn = None
            if is_vid_key(source):
                _expected_vid = get_key_file(source)
                if _expected_vid and curr_file and _expected_vid != curr_file:
                    _warn = "expected vid={} actual vid={}".format(_expected_vid, curr_file)
            elif is_img_key(source):
                _expected_img = get_key_file(source)
                if _expected_img and curr_file and _expected_img != curr_file:
                    _warn = "expected img={} actual img={}".format(_expected_img, curr_file)
            elif is_dlg_key(source):
                _expected_img = get_key_file(source)
                _expected_dlg = get_key_dialogue(source)
                _cur_dlg = (_sfx.current_dialogue or "")[:40]
                if _expected_img != curr_file or _expected_dlg != _cur_dlg:
                    _warn = "expected img={}|{} actual img={}|{}".format(
                        _expected_img, _expected_dlg, curr_file, _cur_dlg)
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
    # SFX Trigger Engine (Tick)
    # --------------------------------------------------------------------------

    def _sfx_editor_tick_trigger():
        """SFX trigger engine — runs always (even when overlay is hidden)."""
        import random as _random
        import time as _time

        # Re-detect the active channel each tick so the CDD time display
        # recovers after rollback (Page Up), which resets active_channel.
        _sfx_editor_refresh_channel()

        # Keep paused state in sync (referenced by the UI for play/pause buttons)
        try:
            _sfx.paused = renpy.music.get_pause(channel=_sfx.active_channel)
        except Exception:
            pass

        if not _sfx.triggers_active:
            return

        _sfx.__tick_count = getattr(store, '_sfx.__tick_count', 0) + 1
        tick = _sfx.__tick_count

        # --- AUTOPLAY STATE MACHINE (a: keys) ---
        now = _time.time()
        autoplay_key = create_autoplay_key(_sfx.current_file or "")

        entry = _sfx.markers.get(autoplay_key)
        if entry:
            files = entry.get("files", [])
            freq = entry.get("frequency", 1)
            if files:
                # Init pool state if needed
                if autoplay_key not in _sfx.pool_states:
                    _sfx.pool_states[autoplay_key] = {
                        "state": 0,
                        "ch": None,
                        "ready_at": 0.0,
                        "play_start": 0.0,
                    }
                ps = _sfx.pool_states[autoplay_key]

                if ps["state"] == 1:
                    if not renpy.music.is_playing(channel=ps["ch"]):
                        dur = now - ps["play_start"]
                        breathing = _sfx_editor_get_autoplay_delay(freq)
                        ps["ready_at"] = now + breathing
                        ps["state"] = 0
                        _sfx_log("TICK#{} POOL-DONE  key={} dur={:.2f}s next_in={:.2f}s".format(
                            tick, autoplay_key, dur, breathing))

                if ps["state"] == 0:
                    if ps["ready_at"] == 0:
                        ps["ready_at"] = now + 0.5
                    elif now >= ps["ready_at"]:
                        f = _sfx_editor_pick_file(files)
                        _vol = entry.get("volume", 1.0)
                        ch_used = _sfx_editor_play_sfx(f, autoplay_key, volume=_vol)
                        if ch_used:
                            ps["state"] = 1
                            ps["ch"] = ch_used
                            ps["play_start"] = now
                            _sfx_log("TICK#{} POOL-PLAY  key={} file={} ch={}".format(
                                tick, autoplay_key, f, ch_used))

        # --- VIDEO MODE triggers (v: keys) ---
        ch = _sfx.active_channel
        if ch and _sfx.top_layer_type == 'movie':
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
                vid_key = create_vid_key(_sfx.current_file)
                vid_entry = _sfx.markers.get(vid_key)
                if vid_entry:
                    timestamps = vid_entry.get("timestamps", [])
                    for idx, ts_entry in enumerate(timestamps):
                        ts_key = "{}@{}".format(vid_key, idx)
                        if ts_key not in _sfx.played_video_keys:
                            if "time" not in ts_entry:
                                _sfx_log("MISSING TIME " + vid_key + " " + str(vid_entry) + " " + str(ts_entry))
                            mt = ts_entry["time"]
                            if mt <= elapsed < mt + _sfx.__marker_tolerance:
                                files = ts_entry.get("files", [])
                                if files:
                                    _vsrc = _sfx.VID_KEY_PREFIX + "{}@{:.2f}".format(_sfx.current_file, mt)
                                    f = _sfx_editor_pick_file(files, avoid_repeats=False)
                                    _vol = _sfx_editor_get_effective_volume(vid_entry, vid_key, ts_index=idx)
                                    _sfx_editor_play_sfx(f, _vsrc, volume=_vol)
                                    _sfx.played_video_keys.add(ts_key)

            # Detect video loop (markers only, pool uses wall clock)
            if _sfx.__last_pos > 0 and elapsed < _sfx.__last_pos - 0.3:
                _sfx.played_video_keys.clear()
            _sfx.__last_pos = elapsed


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

            backups_dir = os.path.join(renpy.config.gamedir, _sfx.base_dir, "backups")
            if not os.path.isdir(backups_dir):
                os.makedirs(backups_dir)

            # List existing backups sorted by mtime (oldest first)
            _files = [f for f in os.listdir(backups_dir)
                      if f.startswith("sfx_editor_backup_") and f.endswith(".json")]
            _files.sort(key=lambda f: os.path.getmtime(
                os.path.join(backups_dir, f)))

            # Rotate: delete oldest if at the max
            MAX_BACKUPS = 25
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
            "triggers_active": _sfx.triggers_active,
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
            # Strip malformed entries before persisting (empty dicts, missing "time")
            stripped = _sfx_editor_sanitize_video_timestamps()
            if stripped:
                _sfx_log("SAVE-MARKERS: sanitized {} malformed video timestamp(s)".format(stripped))
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
        _sfx.triggers_active = data.get("triggers_active", True)
        #_sfx_editor_normalize_all_markers()
        stripped = _sfx_editor_sanitize_video_timestamps()
        if stripped:
            _sfx_log("LOAD-MARKERS: sanitized {} malformed video timestamp(s)".format(stripped))
        _sfx_log("LOAD-MARKERS total_keys={} keys={}".format(
            len(_sfx.markers), list(_sfx.markers.keys())[:20]))



# =============================================================================
# CDD: Self-updating label — redraws itself on a timer without restarting
# interaction, so the time display stays live without jitter or input focus loss.
# =============================================================================

init python:
    class SelfUpdatingLabel(renpy.Displayable):
        """A text label that calls renpy.redraw() to update itself periodically.

        `getter` is a zero-argument function that returns a string.
        `style` is the Ren'Py text style to apply.
        `interval` is the redraw interval in seconds (default 0.05 = 20 Hz)."""

        def __init__(self, getter, style="default", interval=0.05, **properties):
            # Let the base class resolve the string to a proper style object
            # (so per_interact doesn't crash on self.style.prefix).
            super(SelfUpdatingLabel, self).__init__(style=style, **properties)
            self._text_style = style  # raw string for child Text creation
            self.getter = getter
            self.interval = interval

        def render(self, width, height, st, at):
            from renpy.text.text import Text as Txt
            text = self.getter()
            t = Txt(text, style=self._text_style)
            cr = renpy.render(t, width, height, st, at)
            cw, ch = cr.get_size()
            r = renpy.Render(cw, ch)
            r.blit(cr, (0, 0))
            renpy.redraw(self, self.interval)
            return r


    class VideoTimeline(renpy.Displayable):
        """Video-editor-style timeline bar with a playhead line.
        Redraws at ~60 Hz (16 ms) for smooth playhead movement."""

        BAR_H = 16  # bar height in pixels

        def __init__(self, interval=0.016, **properties):
            super(VideoTimeline, self).__init__(**properties)
            self.interval = interval

        def render(self, width, height, st, at):
            r = renpy.Render(width, height)

            dur = _sfx_editor_get_duration()
            elapsed = _sfx_editor_get_elapsed()
            paused = _sfx.paused

            # Determine hover state for subtle brightness change
            hovered = False
            try:
                hovered = self in renpy.get_hovered()
            except Exception:
                pass

            bar_y = max(0, (height - self.BAR_H) // 2)

            # Bar background (slightly brighter on hover)
            bg = "#3a3a3a" if hovered else "#333333"
            canvas = r.canvas()
            canvas.rect(bg, (0, bar_y, width, self.BAR_H))

            # Playhead line (inside the bar)
            if dur > 0 and width > 0:
                frac = max(0.0, min(1.0, elapsed / float(dur)))
                px = int(frac * width)
                px = max(0, min(px, width - 1))

                ph_color = "#ffaa00" if paused else "#ffffff"
                canvas.rect(ph_color, (px, bar_y, 2, self.BAR_H))

            renpy.redraw(self, self.interval)
            return r


    class _VideoMarkerTimeline(renpy.Displayable):
        """Timeline with draggable marker tabs. Click to select, drag to adjust.
        Renders its own tooltip inline — no separate tooltip CDD needed."""

        TRACK_H = 10
        TAB_H = 16
        LINE_H = 8
        TAB_W = 14
        DRAG_THRESH = 4
        TIP_H = 22  # height of the floating tooltip

        def __init__(self, get_markers, get_active, set_active, set_time, get_dur, **kw):
            super(_VideoMarkerTimeline, self).__init__(**kw)
            self.get_markers = get_markers
            self.get_active = get_active
            self.set_active = set_active
            self.set_time = set_time
            self.get_dur = get_dur
            self._drag_idx = getattr(_sfx, '_mtl_drag_idx', -1)
            self._drag_on = getattr(_sfx, '_mtl_drag_on', False)
            self._drag_start_x = getattr(_sfx, '_mtl_drag_start_x', 0)
            self._tip_text = ""
            self._tip_x = 0
            self._tip_y = 0
            self._hover_idx = -1

        def _total_h(self):
            return self.TAB_H + self.TRACK_H + 4

        def render(self, width, height, st, at):
            self._w = width
            r = renpy.Render(width, self._total_h())
            c = r.canvas()
            dur = max(0.001, self.get_dur())
            markers = self.get_markers()
            active = self.get_active()

            # Draw marker lines and tabs (hover state managed by event())
            for i, m in enumerate(markers):
                t = m.get("time", 0.0)
                frac = max(0.0, min(1.0, t / dur))
                px = int(frac * width)

                # Vertical line
                lc = "#669966" if i == active else "#666666"
                c.rect(lc, (px - 1, 0, 2, self.TRACK_H + self.LINE_H))

                # Tab button geometry
                bx_pos = px - self.TAB_W // 2
                by_pos = self.TRACK_H - 2

                # Tab background
                if i == self._drag_idx and self._drag_on:
                    bg = "#7777cc"
                elif i == active:
                    bg = "#669966"
                elif self._hover_idx == i:
                    bg = "#666666"
                else:
                    bg = "#444444"
                c.rect(bg, (bx_pos, by_pos, self.TAB_W, self.TAB_H))

                # Tab number
                txt = Text(str(i + 1), style="sfx_btn_text", size=12, color="#ffffff")
                tr = renpy.render(txt, self.TAB_W, self.TAB_H, st, at)
                tw, _ = tr.get_size()
                r.blit(tr, (bx_pos + (self.TAB_W - tw) // 2, by_pos))

            # Render tooltip if there's text (set by event())
            if self._tip_text:
                tip_widget = Text(self._tip_text, style="sfx_txt", size=11,
                                  color="#cccccc", italic=True, substitute=False)
                tip_render = renpy.render(tip_widget, 300, self.TIP_H, st, at)
                tw, _ = tip_render.get_size()
                fw = min(tw + 8, 300)
                fh = self.TIP_H - 2

                tip = renpy.Render(fw, fh)
                tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
                tip.blit(tip_render, (4, 1))

                # Position tooltip to right of the cursor
                tx = self._tip_x + 10
                ty = self._tip_y
                r.blit(tip, (tx, ty))

            renpy.redraw(self, 0.05)
            return r

        def event(self, ev, x, y, st):
            dur = max(0.001, self.get_dur())
            markers = self.get_markers()
            w = getattr(self, '_w', 1)

            import pygame
            if ev.type == pygame.MOUSEMOTION:
                if self._drag_idx >= 0:
                    if not self._drag_on and abs(x - self._drag_start_x) > self.DRAG_THRESH:
                        self._drag_on = True
                        _sfx._mtl_drag_on = True
                    if self._drag_on:
                        f = max(0.0, min(1.0, x / float(max(1, w))))
                        self.set_time(self._drag_idx, f * dur)
                        self._tip_text = "Pool {} ({})".format(
                            self._drag_idx + 1, _sfx_editor_format_time(f * dur))
                        self._tip_x = x
                        self._tip_y = y
                    renpy.redraw(self, 0)
                    raise renpy.display.core.IgnoreEvent()
                # Hover tooltip
                self._hover_idx = -1
                for i, m in enumerate(markers):
                    t = m.get("time", 0.0)
                    px = int((t / dur) * w)
                    bx = px - self.TAB_W // 2
                    by = self.TRACK_H - 2
                    if bx <= x <= bx + self.TAB_W and by <= y <= by + self.TAB_H:
                        self._tip_text = "Pool {} ({})".format(
                            i + 1, _sfx_editor_format_time(t))
                        self._tip_x = x
                        self._tip_y = y
                        self._hover_idx = i
                        return None
                self._tip_text = ""
                return None

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i, m in enumerate(markers):
                    t = m.get("time", 0.0)
                    px = int((t / dur) * w)
                    bx = px - self.TAB_W // 2
                    by = self.TRACK_H - 2
                    if bx <= x <= bx + self.TAB_W and by <= y <= by + self.TAB_H:
                        self._drag_idx = i
                        self._drag_start_x = x
                        self._drag_on = False
                        _sfx._mtl_drag_idx = i
                        _sfx._mtl_drag_on = False
                        _sfx._mtl_drag_start_x = x
                        self.set_active(i)
                        renpy.redraw(self, 0)
                        raise renpy.display.core.IgnoreEvent()
                return None

            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self._drag_idx >= 0:
                    was_drag = self._drag_on
                    self._drag_idx = -1
                    self._drag_on = False
                    _sfx._mtl_drag_idx = -1
                    _sfx._mtl_drag_on = False
                    if was_drag:
                        _sfx_editor_mtl_finalize()
                    renpy.redraw(self, 0)
                    renpy.restart_interaction()
                    raise renpy.display.core.IgnoreEvent()
                return None

            return None

    class _MouseFollowerTooltip(renpy.Displayable):
        """Tooltip that continuously re-positions itself at the mouse cursor."""

        def __init__(self, **properties):
            super(_MouseFollowerTooltip, self).__init__(**properties)

        def render(self, width, height, st, at):
            tt = getattr(_sfx, '_tooltip_text', None) or ""
            if not tt:
                return renpy.Render(1, 1)

            mx, my = renpy.get_mouse_pos()

            text_widget = Text(
                tt, style="sfx_txt", size=11, color="#cccccc",
                italic=True, substitute=False,
            )
            text_render = renpy.render(text_widget, 300, 22, st, at)
            tw, th = text_render.get_size()

            pad_x, pad_y = 4, 2
            fw = min(tw + pad_x * 2, 300)
            fh = 22

            tip = renpy.Render(fw, fh)
            tip.canvas().rect("#2a2a2a", (0, 0, fw, fh))
            tip.blit(text_render, (pad_x, pad_y))

            r = renpy.Render(1, 1)
            r.blit(tip, (mx + 12, my - 8))

            renpy.redraw(self, 0.05)
            return r


    def _sfx_editor_time_label_getter():
        """Return 'elapsed / duration' formatted for the live time display."""
        if _sfx.top_layer_type != 'movie':
            _sfx_log("not movie? " + _sfx.top_layer_type + " " + _sfx.current_file)
            return "--:--.-- / --:--.--"
        e = _sfx_editor_get_elapsed()
        d = _sfx_editor_get_duration()
        return "{} / {}".format(
            _sfx_editor_format_time(e),
            _sfx_editor_format_time(d),
        )

    def _sfx_editor_frame_label_getter():
        """Return 'frame / total' formatted for the live frame display."""
        if _sfx.top_layer_type != 'movie':
            _sfx_log("not movie? " + _sfx.top_layer_type + " " + _sfx.current_file)
            return "---/---"
        e = _sfx_editor_get_elapsed()
        d = _sfx_editor_get_duration()
        fps = max(1, _sfx.fps)
        return "{}/{}".format(int(e * fps), int(d * fps))


# =============================================================================
# KEY-LISTENER SCREEN: Always-visible invisible screen that catches backtick
# =============================================================================

screen sfx_editor_key_listener():
    zorder 10000
    key "K_BACKQUOTE" action Function(_sfx_editor_toggle)
    key "K_F3" action Function(renpy.invoke_in_new_context, renpy.pause)
    key "K_F4" action Function(_sfx_editor_toggle_active)
    timer 0.025 repeat True action Function(_sfx_editor_tick_trigger, _update_screens=False)

# =============================================================================
# MAIN OVERLAY SCREEN
# =============================================================================

screen sfx_editor_overlay():

    zorder 9999
    modal False
    tag sfx_editor

    # Screen-level key bindings
    key "K_BACKQUOTE" action Function(_sfx_editor_hide)
    key "shift_K_1" action Function(_sfx_editor_copy_context)
    key "shift_K_2" action Function(_sfx_editor_paste_context)

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

