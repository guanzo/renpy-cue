###############################################################################
# CueVidSpeedResolver — per-tag speed preferences and variant Movie resolution.
# Wraps every Movie image in a DynamicDisplayable that swaps in speed variants
# (or the active sequence playlist) without touching the registry entry.
#
# CueVidSpeedSequence — hardcoded speed-variant playlist experiment.
# When active, overrides normal speed resolution: the resolver builds a Movie
# with play=[paths...] and Ren'Py's audio queue re-loops the whole list.
#
# Instantiated at _cue.speed_resolver and _cue.video_sequence.
###############################################################################

init -999 python:
    import os as _os
    import time as _time

    class CueVidSpeedResolver:
        """Per-tag speed preferences and memoized variant/queue Movies.

        All state lives on this instance (reachable through the NoRollback
        _cue singleton) so it survives rollback.  Methods are callable from
        screen actions via Function(_cue.speed_resolver.method, ...)."""

        def __init__(self):
            self.speed_prefs = {}    # tag -> float speed
            self.paths = {}          # tag -> original base video path
            self.children = {}       # (tag, speed) -> memoized variant Movie
            self.sequence = None                # CueVidSpeedSequence back-ref

        # ==================================================================
        # Lookup helpers
        # ==================================================================

        def key_for(self, tag):
            """Map a scene-list name to the speed_prefs key.
            Exact match first, then longest-prefix match."""
            if not tag:
                return tag
            if tag in self.speed_prefs:
                return tag
            best_key = tag
            best_len = -1
            for key in self.speed_prefs:
                if key.startswith(tag + " ") and len(key) > best_len:
                    best_key = key
                    best_len = len(key)
            return best_key

        def speed_for(self, tag):
            """Current speed for a scene-list name (1.0 if unknown)."""
            return self.speed_prefs.get(self.key_for(tag), 1.0)

        def base_path_for(self, tag):
            """Original base video path for a scene-list name."""
            if not tag:
                return None
            if tag in self.paths:
                return self.paths[tag]
            for key, base in self.paths.items():
                if key.startswith(tag + " ") or tag.startswith(key + " "):
                    return base
            return _cue.vid_manager.get_video_path()

        # ==================================================================
        # Speed control (called from screen actions)
        # ==================================================================

        def cycle_speed(self, delta):
            """Cycle through available speed variants. delta = 1/-1."""
            if self.sequence is not None:
                self.sequence.cancel()
            if _cue.top_layer_type != 'movie':
                return
            tag = _cue.current_file
            if not tag:
                return
            key = self.key_for(tag)
            base_path = self.base_path_for(tag)
            if not base_path:
                return
            available = self.get_available_speeds(base_path)
            if len(available) <= 1:
                return
            current = self.speed_prefs.get(key, 1.0)
            try:
                idx = available.index(current)
            except ValueError:
                idx = 0
            new_idx = max(0, min(idx + delta, len(available) - 1))
            new_speed = available[new_idx]
            self.speed_prefs[key] = new_speed
            renpy.restart_interaction()

        def set_speed(self, speed):
            """Set playback speed to a specific value."""
            if self.sequence is not None:
                self.sequence.cancel()
            if _cue.top_layer_type != 'movie':
                return
            tag = _cue.current_file
            if not tag:
                return
            key = self.key_for(tag)
            self.speed_prefs[key] = speed
            renpy.restart_interaction()

        # ==================================================================
        # Cache management
        # ==================================================================

        def invalidate(self, tag):
            """Drop cached child Movies whose key starts with tag.
            Called by CueVidSpeedSequence when (de)activating."""
            keys_to_pop = [k for k in self.children
                           if (isinstance(k, tuple) and k[0] == tag)]
            for k in keys_to_pop:
                self.children.pop(k, None)

        # ==================================================================
        # DynamicDisplayable callback delegate
        # ==================================================================

        def resolve(self, st, at, tag, base_path, orig_movie):
            """Core resolution logic — returns (displayable, redraw_delay).

            Called by the module-level _cue_resolver wrapper so the DD
            callback stays picklable by name reference."""
            try:
                speed = self.speed_prefs.get(tag, 1.0)
            except Exception:
                speed = 1.0

            def _build_or_cache(cache_key, play_value):
                """Return cached Movie for cache_key, or build and cache one."""
                cached = self.children.get(cache_key, None)
                if cached is not None:
                    return cached
                kwargs = _cue_capture_kwargs(orig_movie)
                kwargs["play"] = play_value
                child = renpy.display.video.Movie(**kwargs)
                self.children[cache_key] = child
                _cue_log("VQ-BUILD cache_key={}".format(cache_key))
                return child

            # --- Active speed sequence overrides normal speed resolution ---
            seq = self.sequence
            if seq is not None:
                active = seq.active_tag
                if active and (tag == active or
                               active.startswith(tag + " ") or
                               tag.startswith(active + " ")):
                    queue_paths = seq.paths_for(active)
                    if queue_paths:
                        return _build_or_cache(("__queue__", active), queue_paths), None

            # --- Normal speed resolution ---
            if abs(speed - 1.0) < 0.05:
                return orig_movie, None

            variant = self.variant_path(base_path, speed)
            if not renpy.loadable(variant):
                return orig_movie, None

            return _build_or_cache((tag, speed), variant), None

        # ==================================================================
        # Init-time wrapping
        # ==================================================================

        def wrap_all_movies(self):
            """Wrap every Movie image in the registry with a DynamicDisplayable
            so speed changes take effect without touching the registry entry."""
            _start = _time.time()
            _count = 0
            for name_tuple, d in list(renpy.display.image.images.items()):
                if isinstance(d, DynamicDisplayable):
                    continue  # already wrapped — safe against hot-reload

                unwrapped = _cue_unwrap_displayable(d)
                if not isinstance(unwrapped, renpy.display.video.Movie):
                    continue

                tag = " ".join(name_tuple)
                base_path = _cue_get_movie_play(unwrapped)
                if not base_path:
                    continue

                self.paths[tag] = base_path
                renpy.image(name_tuple, DynamicDisplayable(_cue_resolver, tag, base_path, unwrapped))
                _count += 1

            _elapsed = _time.time() - _start
            _cue_log("DynamicDisplayable resolver wrapping done: {} movies in {:.3f}s".format(_count, _elapsed))

        # ==================================================================
        # Variant path utilities
        # ==================================================================

        @staticmethod
        def variant_path(base_path, speed):
            """Build the virtual path for a speed variant.
            Example: 'movies/ep1.webm' + 1.5 -> 'movies/ep1.1.5x.webm'"""
            base, ext = _os.path.splitext(base_path)
            if not ext:
                ext = ".webm"
            return "{}.{:.1f}x{}".format(base, speed, ext)

        @staticmethod
        def is_variant_of(path, base_path):
            """True if path is base_path itself or a speed variant of it
            (movies/ep1.webm -> movies/ep1.2.0x.webm)."""
            if not path or not base_path:
                return False
            if path == base_path:
                return True
            base, ext = _os.path.splitext(base_path)
            if not ext:
                ext = ".webm"
            if not (path.startswith(base + ".") and path.endswith("x" + ext)):
                return False
            middle = path[len(base) + 1:-len("x" + ext)]
            try:
                sp = float(middle)
            except ValueError:
                return False
            return 0.25 <= sp <= 4.0

        def get_available_speeds(self, base_path):
            """Return sorted list of speeds that have variant files on disk.
            Always includes 1.0 (the original)."""
            speeds = [1.0]
            base_dir = _os.path.dirname(_os.path.join(renpy.config.gamedir, base_path))
            base_name = _os.path.basename(base_path)
            base_no_ext, ext = _os.path.splitext(base_name)
            if not ext:
                ext = ".webm"
            try:
                for f in _os.listdir(base_dir):
                    if f.startswith(base_no_ext + ".") and f.endswith("x" + ext):
                        middle = f[len(base_no_ext) + 1:-len("x" + ext)]
                        try:
                            sp = float(middle)
                            if 0.25 <= sp <= 4.0 and abs(sp - 1.0) > 0.05:
                                if _os.path.isfile(_os.path.join(base_dir, f)):
                                    speeds.append(sp)
                        except ValueError:
                            pass
            except Exception:
                pass
            speeds.sort()
            return speeds

        @staticmethod
        def preset_speeds():
            """Return hardcoded speed presets for the video editor UI (no 1.0)."""
            return python_list([0.5, 1.5, 2.0])

        def delete_variant(self, base_path, speed):
            """Delete a speed variant file from disk. If the variant is currently
            playing, switches to the 1.0x original first so the file handle is
            released before deletion."""
            if abs(speed - 1.0) < 0.05:
                return  # cannot delete the original

            vpath = self.variant_path(base_path, speed)

            # If this variant is currently playing, switch to the 1.0x
            # original first.  This releases the file handle so the delete
            # won't fail with a lock error on Windows.
            try:
                import renpy.audio.audio as _aaudio
                for _ch_name in _aaudio.channels:
                    _playing = renpy.music.get_playing(channel=_ch_name)
                    if _playing:
                        _playing_fs = _os.path.join(renpy.config.gamedir, _playing)
                        _target_fs = _os.path.join(renpy.config.gamedir, vpath)
                        if _os.path.normpath(_playing_fs) == _os.path.normpath(_target_fs):
                            renpy.music.play(
                                base_path,
                                channel=_ch_name,
                                loop=True,
                                fadeout=0,
                                synchro_start=True,
                            )
            except Exception:
                pass

            # Update speed prefs before deleting so the resolver falls back
            # to 1.0x on the next interaction.
            for tag, bp in self.paths.items():
                if bp == base_path:
                    key = self.key_for(tag)
                    cur = self.speed_prefs.get(key, 1.0)
                    if abs(cur - speed) < 0.05:
                        self.speed_prefs[key] = 1.0

            tag = _cue.current_file
            if tag:
                key = self.key_for(tag)
                cur = self.speed_prefs.get(key, 1.0)
                if abs(cur - speed) < 0.05:
                    self.speed_prefs[key] = 1.0

            # Now delete the variant file with a few retries in case the
            # file handle takes a moment to release (Windows especially).
            fspath = _os.path.join(renpy.config.gamedir, vpath)
            deleted = False
            for _attempt in range(4):
                try:
                    if _os.path.exists(fspath):
                        _os.remove(fspath)
                    deleted = True
                    break
                except Exception:
                    if _attempt < 3:
                        _time.sleep(0.5)

            if not deleted:
                _cue_log("DELETE-VARIANT: all attempts failed to remove {}".format(fspath))
                return

            # Clear resolver cache entries for tags that use this base_path
            # so stale variant Movies aren't reused.
            for tag, bp in self.paths.items():
                if bp == base_path:
                    self.children.pop((tag, speed), None)

            _cue_log("DELETE-VARIANT: removed {} (speed={:.1f}x)".format(vpath, speed))
            renpy.restart_interaction()


    class CueVidSpeedSequence:
        """Hardcoded per-video speed sequences. When active, overrides normal
        speed resolution: the resolver builds a Movie with play=[paths...] and
        Ren'Py's audio queue re-loops the WHOLE list, cycling the sequence
        forever. Owns the play-count tracker used for VQ-PLAY log lines."""

        def __init__(self, resolver):
            self.resolver = resolver
            self.map = {
                "v1s3_veronica_tits": python_list([1.0, 2.0, 3.0, 2.0]),
                "anim_lily_rev1_ep8": python_list([1.0, 1.5, 2.0, 2.5, 2.5, 2.5, 2.0, 1.5]),
            }
            self.active_tag = None
            self.last_playing = None
            self.last_elapsed = 0.0
            self.play_count = 0

        # ==================================================================
        # Lookup
        # ==================================================================

        def speeds_for(self, tag):
            """Speed sequence for a tag from the map, or None.
            Exact match first, then prefix match in both directions."""
            if not tag:
                return None
            if tag in self.map:
                return self.map[tag]
            for key, speeds in self.map.items():
                if key.startswith(tag + " ") or tag.startswith(key + " "):
                    return speeds
            return None

        def paths_for(self, tag):
            """Resolved file list for the tag's sequence, or None if unusable.
            1.0 entries use the base path; other speeds use generated variants.
            Missing variant files are skipped (renpy.loadable handles .rpa)."""
            speeds = self.speeds_for(tag)
            base_path = self.resolver.base_path_for(tag)
            if not speeds or len(speeds) < 2 or not base_path:
                return None
            paths = python_list([])
            for sp in speeds:
                if abs(sp - 1.0) < 0.05:
                    paths.append(base_path)
                else:
                    vpath = self.resolver.variant_path(base_path, sp)
                    if renpy.loadable(vpath):
                        paths.append(vpath)
            if len(paths) < 2 or len(python_set(paths)) < 2:
                return None
            return paths

        # ==================================================================
        # Lifecycle
        # ==================================================================

        def start(self, tag):
            """Set the active tag and trigger a resolver rebuild.
            The resolver builds a Movie with play=[paths...], and the
            DynamicDisplayable swap causes Movie.play() -> music.play(paths)
            which sets up the full sequence atomically."""
            paths = self.paths_for(tag)
            if not paths:
                _cue_log("VQ-NOSTART tag={} paths={}".format(tag, paths is not None))
                self.active_tag = None
                return
            # Clear resolver cache for this tag so a fresh queue Movie is built
            self.resolver.invalidate(tag)
            self.active_tag = tag
            _cue_log("VQ-START tag={} paths={}".format(tag, ",".join(paths)))
            renpy.restart_interaction()

        def handle(self, tag):
            """Context-change hook. Starts the sequence for a mapped tag;
            clears the active tag when leaving a queued scene."""
            old_tag = self.active_tag
            speeds = self.speeds_for(tag)
            if speeds:
                if not old_tag or old_tag != tag:
                    self.start(tag)
            elif old_tag:
                self.active_tag = None
                if _cue.top_layer_type != 'movie':
                    ch = _cue.vid_manager.channel
                    if ch:
                        try:
                            renpy.music.stop(channel=ch, fadeout=0)
                        except Exception:
                            pass

        def cancel(self):
            """Release the sequence so normal speed control takes over.
            The subsequent restart_interaction() in cycle/set triggers the
            resolver to swap the Movie, which replaces the channel."""
            self.active_tag = None

        def tick(self):
            """Play-count tracker — logs each new play via elapsed wrap-around.
            No-op when no sequence is active. Runs regardless of triggers_active."""
            if not self.active_tag or not _cue.vid_manager.channel:
                return
            try:
                ch = _cue.vid_manager.channel
                now_playing = renpy.music.get_playing(channel=ch)
                now_elapsed = renpy.music.get_pos(channel=ch) or 0.0
            except Exception:
                now_playing = None
                now_elapsed = 0.0
            is_new_play = (now_playing != self.last_playing or
                           (now_playing and now_elapsed < 1.0 and
                            self.last_elapsed - now_elapsed > 1.0))
            if is_new_play:
                self.play_count += 1
                _cue_log("VQ-PLAY #{} file={}".format(
                    self.play_count,
                    now_playing.rsplit("/", 1)[-1] if now_playing else now_playing))
            self.last_playing = now_playing
            self.last_elapsed = now_elapsed


    # ==========================================================================
    # Module-level wrappers (must be module-level for DynamicDisplayable pickling)
    # ==========================================================================

    def _cue_resolver(st, at, tag, base_path, orig_movie):
        """DynamicDisplayable callback — delegates to the resolver instance
        so the callback pickles by module+name reference instead of through
        the instance (which holds live Movie displayables in children)."""
        return _cue.speed_resolver.resolve(st, at, tag, base_path, orig_movie)

    def _cue_capture_kwargs(movie):
        """Capture constructor kwargs from a Movie object so we can reconstruct
        an equivalent Movie with a different play path."""
        kwargs = {
            "channel": movie.channel,
            "loop": movie.loop,
            "size": movie.size,
            "side_mask": getattr(movie, "side_mask", False),
            "mask": getattr(movie, "mask", None),
            "mask_channel": getattr(movie, "mask_channel", None),
            "image": getattr(movie, "image", None),
            "start_image": getattr(movie, "start_image", None),
            "play_callback": getattr(movie, "play_callback", None),
        }
        # group param only exists in Ren'Py 8.x — would TypeError on 7.x
        if hasattr(movie, "group"):
            kwargs["group"] = movie.group
        return kwargs
