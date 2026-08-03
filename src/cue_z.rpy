###############################################################################
# SECTION 1: Variable Defaults (init -999 for early loading)
###############################################################################

init -999 python:

    # --- All runtime state on a single NoRollback object ---
    # Ren'Py skips rollback for NoRollback instances — no state gets corrupted
    # by Page Up. Never reassign _cue itself; only mutate its attributes.
    _cue = renpy.python.NoRollback()

    # Context tracking
    _cue.active_channel = None
    _cue.current_file = ""
    _cue.current_dialogue = ""
    _cue.prev_dialogue = ""
    _cue.top_layer_type = None

    # Path constants
    _cue.base_dir = "renpy_cue"
    _cue.audio_dir = _cue.base_dir + "/audio"
    _cue.config_filename = "cue_config.json"
    _cue.config_path = os.path.join(renpy.config.gamedir, _cue.base_dir, _cue.config_filename)
    _cue.debug_log_filename = "debug.log"
    _cue.markers = {}          # Unified markers: trigger_key -> entry
    _cue.clipboard = None

    # Volume constants (clamp range + UI quick-set targets)
    _cue.VOL_MIN = 0.0       # clamp floor
    _cue.VOL_DEFAULT = 1.0   # default volume; "--" reset target
    _cue.VOL_MAX = 5.0       # clamp ceiling; "++" target

    # Key prefix constants for _cue.markers trigger keys
    _cue.IMG_KEY_PREFIX = "i:"
    _cue.AUTOPLAY_KEY_PREFIX = "a:"
    _cue.DLG_KEY_PREFIX = "d:"
    _cue.VID_KEY_PREFIX = "v:"

    # Pool state machine (multi-instance: one per active a: key)
    _cue.autoplay_states = {}
    _cue.autoplay_current = None   # {key, ch} of currently-playing autoplay SFX
    _cue.last_played = []

    _cue.triggers_active = True

    # Video state (per-video playback tracking)
    _cue.vid_manager = CueVideoManager()
    _cue.played_video_keys = set()  # tracks which v: markers have already fired this playback

    # Volume manager (per-entry volume read/write)
    _cue.volume = CueVolumeManager()

    # Repeat pattern dialog state
    _cue.beat = CueBeatManager()

    # UI state
    _cue.is_overlay_visible = False
    _cue.initialized = False
    _cue.visible_tree = []
    _cue.expanded_folders = {}
    _cue.scan_error = None

    # Video timestamp editing state
    _cue.edit_video_ts_text = ""   # text buffer for the editable input — always reflects active pool

    # Multi-pool UI state: which pool the file-browser I/D/V buttons target
    _cue.img_target_pool = 0
    _cue.dlg_target_pool = 0
    _cue.vid_target_pool = 0


    _cue._last_autosave_time = 0

    # Audio file cache
    _cue.available_files = []
    _cue.audio_tree = []
    _cue.disabled_files = set()  # Set of full_path strings for unchecked files

    # Internal
    _cue.__cue_channel_idx = 0
    _cue.__refreshing_channel = False
    _cue._shake_just_happened = False

    # Preview state: channel the last user preview played on (None if none)
    _cue._preview_channel = None


###############################################################################
# SECTION 2: Init Block (init 999 python)
###############################################################################

init 999 python:
    # Enable dev tools for this mod (Shift+R reload, Shift+O console)
    config.developer = True
    config.console = True

    # monkeypatch renpy.with_statement
    _original_with_statement = renpy.with_statement

    def _cue_with_hook(trans, always=False, paired=None, clear=True):
        if _is_screenshake(trans):
            _cue._shake_just_happened = True
        return _original_with_statement(trans, always=always, paired=paired, clear=clear)

    renpy.with_statement = _cue_with_hook
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
        log_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        log_path = os.path.join(log_dir, _cue.debug_log_filename)
        open(log_path, "w").close()
    except Exception:
        pass

    if not _cue.initialized:
        # Detect Ren'Py version for relative_volume support (added in 7.5)
        _v = getattr(renpy, 'version_tuple', (0, 0, 0))
        _cue._has_relative_volume = (_v >= (7, 5, 0))
        _cue_log("INIT: renpy_version={} relative_volume={}".format(
            ".".join(str(x) for x in _v), _cue._has_relative_volume))

        # Register 8 dedicated SFX channels on the "sfx" mixer
        for i in range(1, 9):
            ch_name = "_cue_{}".format(i)
            if not renpy.music.channel_defined(ch_name):
                renpy.music.register_channel(
                    ch_name, "sfx", loop=False, stop_on_mute=True, tight=False
                )

        # Create a layer above screens for the overlay
        renpy.add_layer("cue_layer", above="screens")

        # Use config.overlay_screens for a persistent key-listener
        config.overlay_screens.append("cue_key_listener")
        _cue_log("INIT: overlay_screens key listener registered")

        # Register after_load callback
        def _cue_after_load():
            if _cue.is_overlay_visible:
                _cue.is_overlay_visible = False
                _cue.vid_manager.reset_pause()
        config.after_load_callbacks.append(_cue_after_load)

        # Character callback — updates dialogue text only (context change
        # detection now lives in start_interact_callbacks below).
        def _cue_char_callback(event, interact=True, **kwargs):
            if event == "show":
                _cue.prev_dialogue = _cue.current_dialogue
                _cue.current_dialogue = getattr(store, '_last_say_what', '') or ''
            elif event == "end":
                _cue.prev_dialogue = _cue.current_dialogue
                _cue.current_dialogue = ""
        config.all_character_callbacks.append(_cue_char_callback)

        # start_interact callback — detects context changes at interaction
        # boundaries (replaces the old 500ms poll in _cue_tick).
        def _cue_start_interact_callback(*args, **kwargs):
            _cue_refresh_context()
        config.start_interact_callbacks.append(_cue_start_interact_callback)

        # Load markers from persistent so SFX work immediately (before overlay is ever opened)
        _cue_load_markers()

        _cue_log("INIT: callbacks registered")
        _cue.initialized = True


###############################################################################
# SECTION 3: Core Python Functions
###############################################################################

init python:
    import os


    # --------------------------------------------------------------------------
    # Debug Logging
    # --------------------------------------------------------------------------

    def _cue_log(msg):
        """Append a debug message to cue_editor/debug.log."""
        try:
            import time as _logtime
            log_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir)
            log_path = os.path.join(log_dir, _cue.debug_log_filename)
            with open(log_path, "a") as f:
                _ts = _logtime.strftime("%H:%M:%S") + ".{:03d}".format(int(_logtime.time() * 1000) % 1000)
                f.write("[{}] {}\n".format(_ts, msg))
        except Exception:
            pass  # Never let logging break the game

    # --------------------------------------------------------------------------
    # Visibility
    # --------------------------------------------------------------------------

    def _cue_toggle_overlay():
        """Toggle the overlay on/off. Called from the key-listener screen."""
        if _cue.is_overlay_visible:
            _cue_hide_overlay()
        else:
            _cue_show_overlay()


    def _cue_toggle_active():
        """Toggle active state — when False, no triggers fire. Persisted.
        Called from Ctrl+` key binding and the Active checkbox."""
        _cue.triggers_active = not _cue.triggers_active
        _cue_save_markers()


    def _cue_toggle_shake_trigger():
        """Toggle trigger_on_shake for the active pool of the current image.
        When enabled, screen shake transitions play SFX from this pool."""
        if not _cue.current_file:
            return
        _shake_key = create_img_key(_cue.current_file)
        _pool = _cue_ensure_pool(_shake_key, _cue.img_target_pool)
        _pool["trigger_on_shake"] = not _pool.get("trigger_on_shake", False)
        _cue_save_markers()


    def _cue_show_overlay():
        _cue.is_overlay_visible = True
        # Load persisted config
        _cue_load_markers()
        # Scan audio on first open (cached thereafter)
        if not _cue.available_files:
            _cue_scan_audio()
        # Rebuild visible tree
        _cue.visible_tree = _cue_get_visible_tree()
        # Auto-detect everything
        _cue_refresh_context()
        # Show the overlay screen
        renpy.show_screen("cue_overlay", _layer="cue_layer")
        renpy.restart_interaction()


    def _cue_hide_overlay():
        _cue.is_overlay_visible = False
        _cue_save_markers()
        renpy.hide_screen("cue_overlay", layer="cue_layer")


    def _cue_refresh_context():
        """Re-detect video and image, and swap context when they change."""

        old_file = _cue.current_file
        old_video = _cue.active_channel

        # 1. Re-detect video channel
        _cue_refresh_channel()
        _cue.visible_tree = _cue_get_visible_tree()

        # 2. Re-detect context: top displayable on master layer wins;
        #    fall back to video channel when nothing is on the master layer.
        _top_name, _top_type = _cue_get_top_layer()
        if _top_name is None:
            return
        
        _cue.current_file = _top_name
        _cue.top_layer_type = _top_type  # cache for screen / other consumers

        # 3. Always log current context for debugging
        _cue_log_context()

        # 4. If context changed, build trigger keys and fire
        _changed = ""
        _img_key = None
        _dlg_key = None

        if _cue.current_file != old_file:
            _changed += " file:{}->{}".format(old_file, _cue.current_file)
            _img_key = create_img_key(_cue.current_file) if _cue.current_file else None
            _cue.autoplay_states = {} # clean up stale data
        if _cue.active_channel != old_video:
            _changed += " ch:{}->{}".format(old_video, _cue.active_channel)
        if _cue.current_dialogue != _cue.prev_dialogue:
            _changed += " dlg:{}->{}".format(_cue.prev_dialogue[:30] if _cue.prev_dialogue else "",
                _cue.current_dialogue[:30] if _cue.current_dialogue else "")
        if _cue.current_dialogue:
            _dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))

        if _changed:
            _cue_log("CTX-CHANGE{}".format(_changed))
            _cue_fire_context_triggers(_img_key, _dlg_key)

        # 5. Screenshake trigger — fires independently of context changes,
        #    but only for pools that opted in via trigger_on_shake.
        #    
        #    Dedupe: when the image changed this interaction, _img_key already
        #    fired above (hitting all pools for the new image), so skip the
        #    shake call for the same key to avoid double-firing.
        #    When screen shakes on existing img, _img_key will be None since there
        #    was no img change, and the shake pools will trigger.
        if _cue._shake_just_happened:
            _cue._shake_just_happened = False
            if _cue.current_file:
                _shake_key = create_img_key(_cue.current_file)
                if _shake_key != _img_key:
                    _cue_fire_context_triggers(_shake_key, only_shake_pools=True)


    def _cue_log_context():
        """Log current context state for debugging — even if nothing changed."""
        _vpath = _cue.vid_manager.get_video_path()
        _vname = _vpath.rsplit("/", 1)[-1] if _vpath else "(none)"
        _playing = "?"
        if _cue.active_channel:
            try:
                _playing = "1" if renpy.music.is_playing(channel=_cue.active_channel) else "0"
            except Exception:
                pass
        # Determine primary context — top displayable on master layer wins;
        # fall back to video channel when nothing is on the master layer.
        _top_name, _top_type = _cue_get_top_layer()
        if _top_type:
            _ctx_type = _top_type  # 'image' or 'movie'
        elif _cue.active_channel is not None and _playing == "1":
            _ctx_type = "video"
        else:
            _ctx_type = "none"
        _cue_log("CTX-DUMP ctx={} type={} video={} ch={} playing={} dlg=\"{}\"".format(
            _cue.current_file or "(none)",
            _ctx_type,
            _vname,
            _cue.active_channel or "(none)",
            _playing,
            _cue.current_dialogue[:60] if _cue.current_dialogue else "(none)"))


    def _cue_pick_file(files, avoid_repeats=True):
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
            last = _cue.last_played
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


    def _cue_fire_context_triggers(*keys, only_shake_pools=False):
        """Fire markers for the given trigger keys.
        Multi-pool entries play one random file from EACH pool concurrently.
        Dedupe guard: same file in two pools of the same trigger is re-picked
        up to 3 times, then skipped to avoid echo artifacts.

        When only_shake_pools is True, pool without the trigger_on_shake flag
        are skipped — used by screenshake triggers so each pool independently
        opts in to firing on shake."""
        if not _cue.triggers_active:
            return
        for key in keys:
            if not key:
                continue
            entry = _cue.markers.get(key)
            if not entry:
                continue
            pools = entry.get("pools", [])
            if not pools:
                continue
            _vol = entry.get("volume", 1.0)
            _total = sum(len(p.get("files", [])) for p in pools)
            
            _cue_log("CTX-TRIGGER key={} pools={} files={} vol={:.2f}".format(
                key, len(pools), _total, _vol))

            _picked = []
            for pi, pool in enumerate(pools):
                if only_shake_pools and not pool.get("trigger_on_shake", False):
                    continue
                files = pool.get("files", [])
                if not files:
                    continue
                _file = _cue_pick_file(files)
                _tries = 0
                while _file in _picked and len(files) > 1 and _tries < 3:
                    _file = _cue_pick_file(files)
                    _tries += 1
                if _file in _picked:
                    continue
                _picked.append(_file)
                _pool_vol = _cue.volume.get_effective(entry, key, pool_index=pi)
                _cue_play_sfx(_file, key, volume=_pool_vol)


    # --------------------------------------------------------------------------
    # Image / Movie Detection (master layer scene list)
    # --------------------------------------------------------------------------

    def _cue_top_layer_name(name):
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


    def _cue_top_movie_name(movie):
        """Context name for a Movie on the master layer.
        Movie has no 'name' in Ren'Py 7/8 — fall back to the file basename
        from its 'play' attribute (which may be a list of paths)."""
        name = _cue_top_layer_name(getattr(movie, "name", None))
        if name:
            return name
        play = getattr(movie, "play", None)
        if isinstance(play, list):
            play = play[0] if play else None
        if play:
            return str(play).replace("\\", "/").rsplit("/", 1)[-1]
        return None


    def _cue_get_top_layer():
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
            name = _cue_top_layer_name(getattr(d, "name", None))

            # Movie: check d first ('show expression Movie(...)'), then
            # d.target ('image foo = Movie(...)' + 'show foo').
            movie = d if isinstance(d, renpy.display.video.Movie) else getattr(d, "target", None)
            if isinstance(movie, renpy.display.video.Movie):
                if name is None:
                    name = _cue_top_movie_name(movie)
                return name, "movie"

            # Image: check d first, then d.target (ImageReference wrapper).
            img = d if isinstance(d, renpy.display.im.Image) else getattr(d, "target", None)
            if isinstance(img, renpy.display.im.Image):
                if name is None:
                    name = _cue_top_layer_name(getattr(img, "filename", None))
                return name, "image"

            # Unknown but named — treat as image context (matches old behavior).
            if name:
                return name, "image"
            return None, None
        except Exception as exc:
            _cue_log("TOP-LAYER-ERR {}".format(repr(exc)))
            return None, None

    # --------------------------------------------------------------------------
    # Channel Detection
    # --------------------------------------------------------------------------

    def _cue_refresh_channel():
        """Auto-detect the active movie channel. Only finds video (movie) channels."""

        if _cue.__refreshing_channel:
            return
        _cue.__refreshing_channel = True

        try:
            video_exts = (".webm", ".mp4", ".mkv", ".avi", ".ogv", ".mpeg", ".mpg")
            old_ch = _cue.active_channel

            def _apply_channel(ch_name, ch_obj=None):

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
                _cue.active_channel = ch_name
                _cue.vid_manager.channel = ch_name
                if old_ch != ch_name:
                    _cue.vid_manager.reset(ch_name)
                _cue.vid_manager.set_fps(fps)

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
                        return
                except Exception:
                    pass

            _cue.active_channel = None
            _cue.vid_manager.channel = None
        finally:
            _cue.__refreshing_channel = False




    # --------------------------------------------------------------------------
    # SFX Playback
    # --------------------------------------------------------------------------

    def _cue_preview_sfx(filename, volume=1.0):
        """Play a preview of an SFX file. Restarts interaction to consume click.
        volume: 0.0-5.0, applied to the channel after play starts.
        """
        # Stop the previous user preview before starting a new one
        _prev_ch = _cue._preview_channel
        if _prev_ch is not None and renpy.music.is_playing(channel=_prev_ch):
            renpy.music.stop(channel=_prev_ch, fadeout=0)
        _cue._preview_channel = _cue_play_sfx(filename, "preview", volume=volume)

    def _cue_play_sfx(filename, source="", volume=1.0):
        """Play an SFX on the next available dedicated channel.
        source: descriptive key for logging (video, image, dialogue, or pool)
        volume: 0.0-1.0, applied to the channel after play starts
        Returns the channel name, or None on failure.
        """

        base_dir = _cue.audio_dir
        if not base_dir.endswith("/"):
            base_dir = base_dir + "/"
        full_path = base_dir + filename

        # Find first idle channel
        target_ch = None
        for i in range(1, 9):
            ch_name = "_cue_{}".format(i)
            if not renpy.music.is_playing(channel=ch_name):
                target_ch = ch_name
                break

        if target_ch is None:
            idx = _cue.__cue_channel_idx
            target_ch = "_cue_{}".format(idx + 1)
            _cue.__cue_channel_idx = (idx + 1) % 8
        else:
            ch_num = int(target_ch.split("_")[-1])
            _cue.__cue_channel_idx = ch_num % 8

        try:
            # Context mismatch warning: compare source context with current state
            curr_file = _cue.current_file
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
                _cur_dlg = (_cue.current_dialogue or "")[:40]
                if _expected_img != curr_file or _expected_dlg != _cur_dlg:
                    _warn = "expected img={}|{} actual img={}|{}".format(
                        _expected_img, _expected_dlg, curr_file, _cur_dlg)
            if _warn:
                _cue_log("WARN CTX-MISMATCH file={} src={} {}".format(
                    filename.rsplit("/", 1)[-1], source, _warn))

            if _cue._has_relative_volume:
                renpy.music.play(full_path, channel=target_ch, loop=False, relative_volume=volume)
            else:
                renpy.music.play(full_path, channel=target_ch, loop=False)
                renpy.music.set_volume(volume, delay=0, channel=target_ch)

            _cue_log("PLAY-SFX file={} src={} ch={} vol={:.2f}".format(
                filename.rsplit("/", 1)[-1], source, target_ch, volume))

            return target_ch
        except Exception:
            return None



    # --------------------------------------------------------------------------
    # SFX Trigger Engine (Tick)
    # --------------------------------------------------------------------------

    def _cue_tick_trigger():
        """SFX trigger engine — runs always (even when overlay is hidden)."""
        import time as _time

        # Re-detect the active channel each tick so the CDD time display
        # recovers after rollback (Page Up), which resets active_channel.
        _cue_refresh_channel()

        # Keep paused state in sync (referenced by the UI for play/pause buttons)
        _cue.vid_manager.sync_paused()

        # --- Auto-re-pause after seek (runs regardless of SFX Active) ---
        _cue.vid_manager.poll_autopause()

        if not _cue.triggers_active:
            return

        _cue.__tick_count = getattr(_cue, '__tick_count', 0) + 1
        tick = _cue.__tick_count

        # --- AUTOPLAY STATE MACHINE (a: keys) ---
        now = _time.time()
        autoplay_key = create_autoplay_key(_cue.current_file or "")
        
        entry = _cue.markers.get(autoplay_key)
        if entry:
            files = entry.get("files", [])
            freq = entry.get("frequency", 1)
            if files:
                # Init pool state if needed
                if autoplay_key not in _cue.autoplay_states:
                    _cue.autoplay_states[autoplay_key] = {
                        "state": 0,
                        "ch": None,
                        "ready_at": 0.0,
                        "play_start": 0.0,
                    }
                ps = _cue.autoplay_states[autoplay_key]
                
                if ps["state"] == 1:
                    if not renpy.music.is_playing(channel=ps["ch"]):
                        dur = now - ps["play_start"]
                        breathing = _cue_get_autoplay_delay(freq)
                        ps["ready_at"] = now + breathing
                        ps["state"] = 0
                        _cue.autoplay_current = None
                        _cue_log("TICK#{} POOL-DONE  key={} dur={:.2f}s next_in={:.2f}s".format(
                            tick, autoplay_key, dur, breathing))

                if ps["state"] == 0:
                    if ps["ready_at"] == 0:
                        ps["ready_at"] = now + 0.5
                    elif now >= ps["ready_at"]:
                        # --- Cross-context overlap gate ---
                        _block = _cue.autoplay_current
                        if _block and _block["key"] != autoplay_key and renpy.music.is_playing(channel=_block["ch"]):
                            # Another autoplay SFX is still playing -- defer
                            ps["ready_at"] = now + 0.1
                        else:
                            f = _cue_pick_file(files)
                            _vol = entry.get("volume", 1.0)
                            ch_used = _cue_play_sfx(f, autoplay_key, volume=_vol)
                            if ch_used:
                                ps["state"] = 1
                                ps["ch"] = ch_used
                                ps["play_start"] = now
                                _cue.autoplay_current = {"key": autoplay_key, "ch": ch_used}
                                _cue_log("TICK#{} POOL-PLAY  key={} file={} ch={}".format(
                                    tick, autoplay_key, f, ch_used))

        # --- VIDEO MODE triggers (v: keys) ---
        ch = _cue.active_channel
        marker_tolerance = 0.08

        if ch and _cue.top_layer_type == 'movie':
            elapsed = _cue.vid_manager.get_elapsed()

            # Video markers
            if _cue.current_file:
                vid_key = create_vid_key(_cue.current_file)
                vid_entry = _cue.markers.get(vid_key)
                if vid_entry:
                    timestamps = vid_entry.get("timestamps", [])
                    for idx, ts_entry in enumerate(timestamps):
                        ts_key = "{}@{}".format(vid_key, idx)
                        if ts_key not in _cue.played_video_keys:
                            if "time" not in ts_entry:
                                _cue_log("MISSING TIME " + vid_key + " " + str(vid_entry) + " " + str(ts_entry))
                                continue
                            mt = ts_entry["time"]
                            if mt <= elapsed < mt + marker_tolerance:
                                files = ts_entry.get("files", [])
                                if files:
                                    f = _cue_pick_file(files, avoid_repeats=False)
                                    _vol = _cue.volume.get_effective(vid_entry, vid_key, ts_index=idx)
                                    _cue_play_sfx(f, vid_key, volume=_vol)
                                    _cue.played_video_keys.add(ts_key)

            # Detect video loop (markers only, pool uses wall clock)
            if _cue.vid_manager.last_elapsed > 0 and elapsed < _cue.vid_manager.last_elapsed - 0.3:
                _cue.played_video_keys.clear()
            _cue.vid_manager.last_elapsed = elapsed


    # --------------------------------------------------------------------------
    # Persistence
    # --------------------------------------------------------------------------

    def _cue_autosave_backup():
        """Create a timestamped backup of markers in cue_editor/backups/.

        Throttled to once every 5 minutes. Maintains a max of 10 backups,
        deleting the oldest when the limit is reached.

        Called from _cue_save_markers() after every successful save.
        All exceptions are swallowed — autosave must never break the editor."""
        try:
            import time as _time
            import json as _json

            # Throttle: skip if last autosave was within 5 minutes
            _now = _time.time()
            if _now - _cue._last_autosave_time < 300:
                return

            backups_dir = os.path.join(renpy.config.gamedir, _cue.base_dir, "backups")
            if not os.path.isdir(backups_dir):
                os.makedirs(backups_dir)

            # List existing backups sorted by mtime (oldest first)
            _files = [f for f in os.listdir(backups_dir)
                      if f.startswith("cue_backup_") and f.endswith(".json")]
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
            _name = "cue_backup_{}.json".format(_ts)
            _path = os.path.join(backups_dir, _name)
            with open(_path, "w") as f:
                _json.dump(persistent._cue_markers, f,
                           indent=2, sort_keys=True)

            _cue._last_autosave_time = _now
            _cue_log("AUTOSAVE-BACKUP path={} marker_keys={}".format(
                _name, len(_cue.markers)))
        except Exception:
            pass  # Never let autosave break the editor

    def _cue_save_markers():
        """Save unified markers and disabled_files to persistent storage.

        Refuses to overwrite existing persistent marker data with an empty dict.
        This guards against auto-reload wiping markers: init -999 clears
        _cue.markers in RAM, and if load fails for any reason (syntax error,
        split-file ordering, etc.), a subsequent save would otherwise persist
        the empty state and destroy all marker data.

        disabled_files is always written regardless of the marker guard."""
        data = {
            "version": "2.2.0",
            "disabled_files": sorted(_cue.disabled_files),
            "triggers_active": _cue.triggers_active,
        }

        if not _cue.markers:
            existing = getattr(persistent, '_cue_markers', None)
            if existing is not None and existing.get("markers"):
                _cue_log("SAVE-MARKERS: refusing to clobber {} existing keys with empty dict".format(
                    len(existing["markers"])))
                data["markers"] = existing["markers"]
            else:
                data["markers"] = {}
        else:
            # Strip malformed entries before persisting (empty dicts, missing "time")
            stripped = _cue_sanitize_video_timestamps()
            if stripped:
                _cue_log("SAVE-MARKERS: sanitized {} malformed video timestamp(s)".format(stripped))
            data["markers"] = python_dict(_cue.markers)

        persistent._cue_markers = data

        # Autosave backup to disk (throttled to once per 5 min)
        _cue_autosave_backup()


    def _cue_load_markers():
        """Load markers and disabled_files from persistent storage.
        Unwraps Ren'Py RevertableDict/RevertableList via JSON round-trip
        so that isinstance checks work on the loaded data."""
        data = getattr(persistent, '_cue_markers', None)
        if data is None:
            _cue.markers = {}
            return
        _cue.markers = _cue_unwrap_persistent(data.get("markers", {}))
        _cue.disabled_files = set(data.get("disabled_files", []))
        _cue.triggers_active = data.get("triggers_active", True)
        stripped = _cue_sanitize_video_timestamps()
        if stripped:
            _cue_log("LOAD-MARKERS: sanitized {} malformed video timestamp(s)".format(stripped))
        _cue_log("LOAD-MARKERS total_keys={}".format(len(_cue.markers)))



# =============================================================================



# =============================================================================
# KEY-LISTENER SCREEN: Always-visible invisible screen that catches backtick
# =============================================================================

screen cue_key_listener():
    zorder 10000
    key "K_BACKQUOTE" action Function(_cue_toggle_overlay)
    key "K_F3" action Function(renpy.invoke_in_new_context, renpy.pause)
    key "K_F4" action Function(_cue_toggle_active)
    timer 0.025 repeat True action Function(_cue_tick_trigger, _update_screens=False)

# =============================================================================
# MAIN OVERLAY SCREEN
# =============================================================================

screen cue_overlay():

    zorder 9999
    modal False
    tag cue_editor

    # Screen-level key bindings
    key "K_BACKQUOTE" action Function(_cue_hide_overlay)
    key "shift_K_1" action Function(_cue_copy_context)
    key "shift_K_2" action Function(_cue_paste_context)

    button:
        xalign 0.0
        yalign 0.0
        xsize 500
        yfill True
        action NullAction()
        background None
        hover_background None
        frame:
            style "cue_frame"
            xfill True
            yfill True
            use cue_overlay_content()

    # --- Floating tooltip near mouse (auto-sizes to fit text) ---
    $ _tt = GetTooltip()
    if _tt:
        add _Tooltip(_tt)

