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
    _cue.markers = CueMarkerManager()  # Unified marker CRUD with typed accessors

    # Volume constants (clamp range + UI quick-set targets)
    _cue.VOL_DEFAULT = 1.0   # default volume; "--" reset target
    _cue.END_MARGIN = 0.05   # min distance from video end for timestamp placement

    # Key prefix constants for _cue.markers trigger keys
    _cue.IMG_KEY_PREFIX = "i:"
    _cue.LOOP_KEY_PREFIX = "l:"
    _cue.DLG_KEY_PREFIX = "d:"
    _cue.VID_KEY_PREFIX = "v:"

    # Pool state machine (multi-instance: one per active l: key)
    _cue.loop_states = {}
    _cue.loop_current = None   # {key, channels} of currently-playing loop SFX
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
    _cue.file_tree = CueFileTreeManager()
    _cue._marker_tip_text = ""     # marker timeline tooltip (rendered by _MarkerTooltipOverlay)
    _cue.scan_error = None

    class CuePresetDialog:
        """Self-contained state for the Save Preset popup."""
        def __init__(self):
            self.trigger_key = None
            self.pool_idx = 0
            self.name = ""

        def open(self, trigger_key, pool_idx):
            entry = _cue.markers.get(trigger_key)
            if entry is None:
                return
            pools = entry.get("pools", [])
            if pool_idx >= len(pools):
                return
            _cue.markers._detach_pool(trigger_key, pool_idx)
            self.trigger_key = trigger_key
            self.pool_idx = pool_idx
            self.name = ""
            renpy.show_screen("cue_save_preset_dialog", _layer="cue_layer")

        def commit(self):
            name = self.name.strip()
            if name:
                entry = _cue.markers.get(self.trigger_key)
                if entry:
                    pools = entry.get("pools", [])
                    if self.pool_idx < len(pools):
                        _cue.markers.create_preset(name, pools[self.pool_idx])
            self.trigger_key = None
            renpy.hide_screen("cue_save_preset_dialog", layer="cue_layer")

        def cancel(self):
            self.trigger_key = None
            renpy.hide_screen("cue_save_preset_dialog", layer="cue_layer")

    _cue.preset_dialog = CuePresetDialog()

    class CueVideoPresetDialog:
        """Self-contained state for the Save Video Preset popup."""
        def __init__(self):
            self.name = ""

        def open(self):
            """Open the save dialog for the current video's timestamps."""
            vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
            if not vid_key:
                return
            entry = _cue.markers.get(vid_key)
            if entry is None:
                return
            timestamps = entry.get("timestamps", [])
            if not timestamps:
                return
            self.name = ""
            renpy.show_screen("cue_save_video_preset_dialog", _layer="cue_layer")

        def commit(self):
            """Create a video preset from the current video's timestamps."""
            name = self.name.strip()
            if name:
                vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
                if vid_key:
                    entry = _cue.markers.get(vid_key)
                    if entry:
                        _cue.markers.create_video_preset(name, entry)
            renpy.hide_screen("cue_save_video_preset_dialog", layer="cue_layer")

        def cancel(self):
            renpy.hide_screen("cue_save_video_preset_dialog", layer="cue_layer")

    _cue.video_preset_dialog = CueVideoPresetDialog()

    class CueConfirmDialog:
        """Reusable confirmation popup matching the overlay UI style."""
        def __init__(self):
            self.message = ""
            self.on_confirm = None  # Function() or list of actions

        def show(self, message, confirm_action):
            self.message = message
            self.on_confirm = confirm_action
            renpy.show_screen("cue_confirm_dialog", _layer="cue_layer")

        def hide(self):
            self.message = ""
            self.on_confirm = None
            renpy.hide_screen("cue_confirm_dialog", layer="cue_layer")

    _cue.confirm_dialog = CueConfirmDialog()


    # Audio file cache
    _cue.available_files = []
    _cue.audio_tree = []

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
        _cue.markers.load_persistent()
        _cue_scan_audio()

        _cue_log("INIT: Done")
        _cue.initialized = True


###############################################################################
# SECTION 3: Core Python Functions
###############################################################################

init python:
    import os

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
        _cue.markers.save_persistent()


    def _cue_toggle_shake_trigger():
        """Toggle trigger_on_shake for the active pool of the current image.
        When enabled, screen shake transitions play SFX from this pool."""
        if not _cue.current_file:
            return
        shake_key = create_img_key(_cue.current_file)
        pool = _cue.markers._ensure_pool(shake_key, _cue.markers._img_target)
        pool["trigger_on_shake"] = not pool.get("trigger_on_shake", False)
        _cue.markers.save_persistent()


    def _cue_show_overlay():
        _cue.is_overlay_visible = True
        # Load persisted config
        _cue.markers.load_persistent()
        # Scan audio on first open (cached thereafter)
        if not _cue.available_files:
            _cue_scan_audio()
        # Rebuild visible tree
        _cue.file_tree.rebuild_tree()
        # Auto-detect everything
        _cue_refresh_context()
        # Show the overlay screen
        renpy.show_screen("cue_overlay", _layer="cue_layer")
        renpy.restart_interaction()


    def _cue_hide_overlay():
        _cue.is_overlay_visible = False
        _cue.markers.save_persistent()
        renpy.hide_screen("cue_overlay", layer="cue_layer")


    def _cue_refresh_context():
        """Re-detect video and image, and swap context when they change."""

        old_file = _cue.current_file
        old_video = _cue.active_channel

        # 1. Re-detect video channel
        _cue_refresh_channel()
        _cue.file_tree.rebuild_tree()

        # Character callbacks don't trigger on rollback, need to clear stale dialogue here.
        if renpy.get_screen("say") is None:
            _cue.current_dialogue = ""
            _cue.prev_dialogue = ""

        # 2. Re-detect context: top displayable on master layer wins;
        #    fall back to video channel when nothing is on the master layer.
        top_name, top_type = _cue_get_top_layer()
        if top_name is None:
            return

        _cue.current_file = top_name
        _cue.top_layer_type = top_type  # cache for screen / other consumers

        # 3. Always log current context for debugging
        _cue_log_context()

        # 4. If context changed, build trigger keys and fire
        changed = ""
        img_key = None
        dlg_key = None

        if _cue.current_file != old_file:
            changed += " file:{}->{}".format(old_file, _cue.current_file)
            img_key = create_img_key(_cue.current_file) if _cue.current_file else None

            # Clean up stale data
            _cue.loop_states = {} 
            _cue.played_video_keys.clear()
        if _cue.active_channel != old_video:
            changed += " ch:{}->{}".format(old_video, _cue.active_channel)
        if _cue.current_dialogue != _cue.prev_dialogue:
            changed += " dlg:{}->{}".format(_cue.prev_dialogue[:30] if _cue.prev_dialogue else "",
                _cue.current_dialogue[:30] if _cue.current_dialogue else "")
        if _cue.current_dialogue:
            dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))

        if changed:
            _cue_log("CTX-CHANGE{}".format(changed))
            _cue_fire_context_triggers(img_key, dlg_key)

        # 5. Screenshake trigger — fires independently of context changes,
        #    but only for pools that opted in via trigger_on_shake.
        #
        #    Dedupe: when the image changed this interaction, img_key already
        #    fired above (hitting all pools for the new image), so skip the
        #    shake call for the same key to avoid double-firing.
        #    When screen shakes on existing img, img_key will be None since there
        #    was no img change, and the shake pools will trigger.
        if _cue._shake_just_happened:
            _cue._shake_just_happened = False
            if _cue.current_file:
                shake_key = create_img_key(_cue.current_file)
                if shake_key != img_key:
                    _cue_fire_context_triggers(shake_key, only_shake_pools=True)


    def _cue_log_context():
        """Log current context state for debugging — even if nothing changed."""
        vpath = _cue.vid_manager.get_video_path()
        vname = vpath.rsplit("/", 1)[-1] if vpath else "(none)"
        playing = "?"
        if _cue.active_channel:
            try:
                playing = "1" if renpy.music.is_playing(channel=_cue.active_channel) else "0"
            except Exception:
                pass
        # Determine primary context — top displayable on master layer wins;
        # fall back to video channel when nothing is on the master layer.
        top_name, top_type = _cue_get_top_layer()
        if top_type:
            ctx_type = top_type  # 'image' or 'movie'
        elif _cue.active_channel is not None and playing == "1":
            ctx_type = "video"
        else:
            ctx_type = "none"
        _cue_log("CTX-DUMP ctx={} type={} video={} ch={} playing={} dlg=\"{}\"".format(
            _cue.current_file or "(none)",
            ctx_type,
            vname,
            _cue.active_channel or "(none)",
            playing,
            _cue.current_dialogue[:60] if _cue.current_dialogue else "(none)"))


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
            vol = entry.get("volume", 1.0)
            total = sum(len(_cue.markers.resolve_pool(p).files) for p in pools)

            _cue_log("CTX-TRIGGER key={} pools={} files={} vol={:.2f}".format(
                key, len(pools), total, vol))

            picked = []
            for pi, pool in enumerate(pools):
                resolved = _cue.markers.resolve_pool(pool)
                if only_shake_pools and not resolved.trigger_on_shake:
                    continue
                files = _cue_resolve_files(resolved.files)
                if not files:
                    continue
                file = _cue_pick_file(files)
                tries = 0
                while file in picked and len(files) > 1 and tries < 3:
                    file = _cue_pick_file(files)
                    tries += 1
                if file in picked:
                    continue
                picked.append(file)
                pool_vol = _cue.volume.get_effective(entry, key, pool_index=pi)
                _cue_play_sfx(file, key, volume=pool_vol)


    # --------------------------------------------------------------------------
    # Image / Movie Detection (master layer scene list)
    # --------------------------------------------------------------------------

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
        prev_ch = _cue._preview_channel
        if prev_ch is not None and renpy.music.is_playing(channel=prev_ch):
            renpy.music.stop(channel=prev_ch, fadeout=0)
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
            warn = None
            if is_vid_key(source):
                expected_vid = get_key_file(source)
                if expected_vid and curr_file and expected_vid != curr_file:
                    warn = "expected vid={} actual vid={}".format(expected_vid, curr_file)
            elif is_img_key(source):
                expected_img = get_key_file(source)
                if expected_img and curr_file and expected_img != curr_file:
                    warn = "expected img={} actual img={}".format(expected_img, curr_file)
            elif is_dlg_key(source):
                expected_img = get_key_file(source)
                expected_dlg = get_key_dialogue(source)
                cur_dlg = (_cue.current_dialogue or "")[:40]
                if expected_img != curr_file or expected_dlg != cur_dlg:
                    warn = "expected img={}|{} actual img={}|{}".format(
                        expected_img, expected_dlg, curr_file, cur_dlg)
            if warn:
                _cue_log("WARN CTX-MISMATCH file={} src={} {}".format(
                    filename.rsplit("/", 1)[-1], source, warn))

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

        now = _time.time()
        _cue_tick_loop_triggers(now, tick)
        _cue_tick_video_triggers()

    def _cue_tick_loop_triggers(now, tick):
        """Loop state machine for l: keys — fires pooled SFX on a frequency cycle."""
        loop_key = create_loop_key(_cue.current_file or "")

        entry = _cue.markers.get(loop_key)
        if entry is None:
            return
        pools = entry.get("pools", [])
        # Collect frequencies from resolved pools with files, default 1
        freqs = []
        for p in pools:
            resolved = _cue.markers.resolve_pool(p)
            if resolved.files:
                freqs.append(resolved.frequency)
        if not freqs:
            return

        freq = int(round(sum(freqs) / float(len(freqs))))
        # Init pool state if needed
        if loop_key not in _cue.loop_states:
            _cue.loop_states[loop_key] = {
                "state": 0,
                "channels": [],
                "ready_at": 0.0,
                "play_start": 0.0,
            }
        ps = _cue.loop_states[loop_key]

        if ps["state"] == 1:
            if not _cue_loop_still_playing(ps.get("channels", [])):
                dur = now - ps["play_start"]
                breathing = _cue.markers.loop.get_delay(freq)
                ps["ready_at"] = now + breathing
                ps["channels"] = []
                ps["state"] = 0
                _cue.loop_current = None
                _cue_log("TICK#{} POOL-DONE  key={} dur={:.2f}s next_in={:.2f}s".format(
                    tick, loop_key, dur, breathing))

        if ps["state"] == 0:
            if ps["ready_at"] == 0:
                ps["ready_at"] = now + 0.5
            elif now >= ps["ready_at"]:
                # --- Cross-context overlap gate ---
                block = _cue.loop_current
                blocking = False
                if block and block.get("key") != loop_key:
                    if _cue_loop_still_playing(block.get("channels", [])):
                        blocking = True
                    else:
                        _cue.loop_current = None  # stale
                if blocking:
                    ps["ready_at"] = now + 0.1
                else:
                    channels = []
                    picked = []
                    for pi, pool in enumerate(pools):
                        resolved = _cue.markers.resolve_pool(pool)
                        files = _cue_resolve_files(resolved.files)
                        if not files:
                            continue
                        picked_file = _cue_pick_file(files)
                        tries = 0
                        while picked_file in picked and len(files) > 1 and tries < 3:
                            picked_file = _cue_pick_file(files)
                            tries += 1
                        if picked_file in picked:
                            continue
                        picked.append(picked_file)
                        pool_vol = _cue.volume.get_effective(entry, loop_key, pool_index=pi)
                        ch_used = _cue_play_sfx(picked_file, loop_key, volume=pool_vol)
                        if ch_used:
                            channels.append(ch_used)
                    if channels:
                        ps["state"] = 1
                        ps["channels"] = channels
                        ps["play_start"] = now
                        _cue.loop_current = {
                            "key": loop_key,
                            "channels": list(channels),
                        }
                        _cue_log("TICK#{} POOL-PLAY  key={} files={} chs={}".format(
                            tick, loop_key, len(channels), ",".join(channels)))
                    else:
                        ps["ready_at"] = now + 0.5


    def _cue_tick_video_triggers():
        """Video timestamp triggers for v: keys — fires SFX at marked times."""
        ch = _cue.active_channel
        if not ch or _cue.top_layer_type != 'movie':
            return

        elapsed = _cue.vid_manager.get_elapsed()
        marker_tolerance = 0.08

        # Video markers
        if _cue.current_file:
            vid_key = create_vid_key(_cue.current_file)
            timestamps = _cue.markers.video.get_markers()
            
            if timestamps:
                vid_entry = _cue.markers.get(vid_key)
                for idx, ts_entry in enumerate(timestamps):
                    ts_key = "{}@{}".format(vid_key, idx)
                    if ts_key not in _cue.played_video_keys:
                        if "time" not in ts_entry:
                            _cue_log("MISSING TIME " + vid_key + " " + str(vid_entry) + " " + str(ts_entry))
                            continue
                        mt = ts_entry["time"]
                        if mt <= elapsed < mt + marker_tolerance:
                            files = _cue_resolve_files(ts_entry.get("files", []))
                            if files:
                                f = _cue_pick_file(files, avoid_repeats=False)
                                vol = _cue.volume.get_effective(vid_entry, vid_key, ts_index=idx)
                                _cue_play_sfx(f, vid_key, volume=vol)
                                _cue.played_video_keys.add(ts_key)
                        

        # Detect video loop (markers only, pool uses wall clock)
        if _cue.vid_manager.last_elapsed > 0 and elapsed < _cue.vid_manager.last_elapsed - 0.3:
            _cue.played_video_keys.clear()
        _cue.vid_manager.last_elapsed = elapsed


    def _cue_preview_preset(preset_name):
        """Preview a random file from a preset. Resolves folder refs first."""
        preset = _cue.markers.get_preset(preset_name)
        if preset is None:
            return
        files = _cue_resolve_files(preset.get("files", []))
        if files:
            import random as _random
            f = _random.choice(files)
            _cue_preview_sfx(f)


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
    key "shift_K_1" action Function(_cue.markers.copy_context)
    key "shift_K_2" action Function(_cue.markers.paste_context)

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

    # --- Marker timeline tooltip (rendered last so it's always on top) ---
    add _MarkerTooltipOverlay()

