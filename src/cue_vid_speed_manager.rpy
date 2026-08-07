###############################################################################
# CueVidSpeedResolver — per-tag speed preferences and variant Movie resolution.
# Wraps every Movie image in a DynamicDisplayable that swaps in speed variants
# (or the active sequence playlist) without touching the registry entry.
#
# CueVidSpeedSequence — user-defined per-video speed sequences stored in the
# marker config. When active, overrides normal speed resolution: the resolver
# builds a Movie with play=[paths...] and Ren'Py's audio queue re-loops the
# whole list.
#
# Instantiated at _cue.speed_resolver and _cue.video_sequence.
###############################################################################

init -999 python:
    import os as _os
    import time as _time

    class SpeedMode:
        """Playback mode for video speed control."""
        SINGLE = "single"       # play at one fixed speed (from marker entry speed_pref)
        SEQUENCE = "sequence"   # loop through the user-defined speed sequence

    class CueVidSpeedResolver:
        """Per-tag speed preferences and memoized variant/queue Movies.

        All state lives on this instance (reachable through the NoRollback
        _cue singleton) so it survives rollback.  Methods are callable from
        screen actions via Function(_cue.speed_resolver.method, ...)."""

        def __init__(self):
            self.paths = {}          # tag -> original base video path
            self.children = {}       # (tag, speed) -> memoized variant Movie
            self.sequence = None                # CueVidSpeedSequence back-ref

        # ==================================================================
        # Lookup helpers
        # ==================================================================

        def _get_speed_pref(self, tag):
            """Read the speed_pref from the tag's marker entry. Fuzzy: if the
            exact tag has no pref, tries the longest prefix match so attribute
            shows share the same speed. Returns DEFAULT_VIDEO_SPEED if unset."""
            if not tag:
                return _cue.DEFAULT_VIDEO_SPEED

            def _read(entry):
                return entry.get("speed_pref", _cue.DEFAULT_VIDEO_SPEED)

            entry = _cue.markers.get(create_vid_key(tag))
            if entry is not None and "speed_pref" in entry:
                return _read(entry)

            # Prefix-match fallback (longest match wins)
            best = _cue.DEFAULT_VIDEO_SPEED
            best_len = -1
            for key in self.paths:
                if key.startswith(tag + " ") and len(key) > best_len:
                    e = _cue.markers.get(create_vid_key(key))
                    if e is not None and "speed_pref" in e:
                        best = _read(e)
                        best_len = len(key)
            return best

        def _set_speed_pref(self, tag, speed):
            """Write speed_pref into the tag's marker entry and persist."""
            if not tag:
                return
            entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
            entry["speed_pref"] = speed
            _cue.markers.save_persistent()

        def speed_for(self, tag):
            """Current speed for a scene-list name (_cue.DEFAULT_VIDEO_SPEED if unknown)."""
            return self._get_speed_pref(tag)

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
                self.sequence.set_mode(SpeedMode.SINGLE)
            if _cue.top_layer_type != 'movie':
                return
            tag = _cue.current_file
            if not tag:
                return
            base_path = self.base_path_for(tag)
            if not base_path:
                return
            available = self.get_available_speeds(base_path)
            if len(available) <= 1:
                return
            current = self._get_speed_pref(tag)
            try:
                idx = available.index(current)
            except ValueError:
                idx = 0
            new_idx = max(0, min(idx + delta, len(available) - 1))
            self._set_speed_pref(tag, available[new_idx])
            renpy.restart_interaction()

        def set_speed(self, speed):
            """Set playback speed to a specific value."""
            if self.sequence is not None:
                self.sequence.set_mode(SpeedMode.SINGLE)
            if _cue.top_layer_type != 'movie':
                return
            tag = _cue.current_file
            if not tag:
                return
            self._set_speed_pref(tag, speed)
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
                speed = self._get_speed_pref(tag)
            except Exception:
                speed = _cue.DEFAULT_VIDEO_SPEED

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
                        return _build_or_cache((tag, "__queue__"), queue_paths), None

            # --- Normal speed resolution ---
            if speed == _cue.DEFAULT_VIDEO_SPEED:
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

        # ------------------------------------------------------------------
        # Variant path helpers — all variant file I/O goes through these.
        # Format: {base}_cue{speed:.1f}x{ext}  (e.g. ep1_cue1.5x.webm)
        # ------------------------------------------------------------------

        _VARIANT_PREFIX = "_cue"

        @staticmethod
        def _suffix_variant(speed, ext):
            """Return the variant suffix for a given speed and extension.
            Example: 1.5, '.webm' -> '_cue1.5x.webm'"""
            return "{cue}{speed:.1f}x{ext}".format(
                cue=CueVidSpeedResolver._VARIANT_PREFIX, speed=speed, ext=ext)

        @staticmethod
        def _parse_variant_speed(filename, base_no_ext, ext):
            """If filename is a variant of base_no_ext+ext, return the speed
            as a float. Otherwise return None.
            Example: 'ep1_cue1.5x.webm', 'ep1', '.webm' -> 1.5"""
            prefix = base_no_ext + CueVidSpeedResolver._VARIANT_PREFIX
            suffix = "x" + ext
            if not (filename.startswith(prefix) and filename.endswith(suffix)):
                return None
            middle = filename[len(prefix):-len(suffix)]
            try:
                return float(middle)
            except ValueError:
                return None

        @staticmethod
        def _split_ext(path):
            """Return (base_no_ext, ext). Defaults ext to '.webm' if missing."""
            base, ext = _os.path.splitext(path)
            if not ext:
                ext = ".webm"
            return base, ext

        @classmethod
        def variant_path(cls, base_path, speed):
            """Build the virtual path for a speed variant.
            Example: 'movies/ep1.webm' + 1.5 -> 'movies/ep1_cue1.5x.webm'"""
            base, ext = cls._split_ext(base_path)
            return base + cls._suffix_variant(speed, ext)

        @classmethod
        def is_variant_of(cls, path, base_path):
            """True if path is base_path itself or a speed variant of it."""
            if not path or not base_path:
                return False
            if path == base_path:
                return True
            base, ext = cls._split_ext(base_path)
            sp = cls._parse_variant_speed(path, base, ext)
            
            return sp is not None

        def get_available_speeds(self, base_path):
            """Return sorted list of speeds that have variant files on disk.
            Always includes the default speed (the original)."""
            speeds = [_cue.DEFAULT_VIDEO_SPEED]
            base_dir = _os.path.dirname(_os.path.join(renpy.config.gamedir, base_path))
            base_name = _os.path.basename(base_path)
            base_no_ext, ext = self._split_ext(base_name)
            try:
                for f in _os.listdir(base_dir):
                    sp = self._parse_variant_speed(f, base_no_ext, ext)
                    if sp is not None and abs(sp - 1.0) > 0.05:
                        if _os.path.isfile(_os.path.join(base_dir, f)):
                            speeds.append(sp)
            except Exception:
                pass
            speeds.sort()
            return speeds

        @staticmethod
        def preset_speeds():
            """Return hardcoded speed presets for the video editor UI (no default speed)."""
            return [0.5, 1.5, 2.0]

        def _prune_deleted_speed_from_sequence(self, speed):
            """Remove every occurrence of `speed` from the current video's
            sequence. Restarts the sequence if it was active."""
            if self.sequence is None:
                return
            tag = _cue.current_file
            if not tag:
                return
            entry = _cue.markers.get(create_vid_key(tag))
            if entry is None:
                return
            seq = entry.get("speed_sequence")
            if not seq:
                return
            new_seq = [s for s in seq if abs(s - speed) >= 0.05]
            if len(new_seq) == len(seq):
                return
            if new_seq:
                entry["speed_sequence"] = new_seq
            else:
                entry.pop("speed_sequence", None)
            if self.sequence.active_tag:
                self.sequence.start(self.sequence.active_tag)

        def delete_variant(self, base_path, speed):
            """Delete a speed variant file from disk. If the variant is currently
            playing, switches to the 1.0x original first so the file handle is
            released before deletion."""
            if speed == _cue.DEFAULT_VIDEO_SPEED:
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
            # to default speed on the next interaction.
            for tag, base in self.paths.items():
                if base == base_path:
                    cur = self._get_speed_pref(tag)
                    if abs(cur - speed) < 0.05:
                        self._set_speed_pref(tag, _cue.DEFAULT_VIDEO_SPEED)

            tag = _cue.current_file
            if tag:
                cur = self._get_speed_pref(tag)
                if abs(cur - speed) < 0.05:
                    self._set_speed_pref(tag, _cue.DEFAULT_VIDEO_SPEED)

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
            for tag, base in self.paths.items():
                if base == base_path:
                    self.children.pop((tag, speed), None)

            # Remove the deleted speed from the current video's sequence.
            self._prune_deleted_speed_from_sequence(speed)

            _cue_log("DELETE-VARIANT: removed {} (speed={:.1f}x)".format(vpath, speed))
            _cue.markers.save_persistent()
            renpy.restart_interaction()


    class CueVidSpeedSequence:
        """User-defined per-video speed sequences stored in the marker config.
        When active, overrides normal speed resolution: the resolver builds a
        Movie with play=[paths...] and Ren'Py's audio queue re-loops the WHOLE
        list, cycling the sequence forever. Owns the play-count tracker used
        for VQ-PLAY log lines."""

        def __init__(self, resolver):
            self.resolver = resolver
            self.active_tag = None
            self.last_playing = None
            self.last_elapsed = 0.0
            self.play_count = 0
            self._step_index = -1

        # ==================================================================
        # Lookup
        # ==================================================================

        def speeds_for(self, tag):
            """User-defined speed sequence for a video, from its marker entry.
            Exact file match. Returns None when absent or empty."""
            if not tag:
                return None
            entry = _cue.markers.get(create_vid_key(tag))
            if entry is None:
                return None
            seq = entry.get("speed_sequence")
            if not seq:
                return None
            return seq

        # ==================================================================
        # UI helpers
        # ==================================================================

        def current_step_index(self):
            """Index of the currently playing step in the active sequence,
            or -1 if the sequence isn't active."""
            return self._step_index

        def contains(self, speed):
            """True if speed (within 0.05) appears in the current video's sequence."""
            seq = self.speeds_for(_cue.current_file)
            if not seq:
                return False
            for s in seq:
                if abs(s - speed) < 0.05:
                    return True
            return False

        def _get_entry(self, tag):
            """Get or create the video marker entry for tag. Returns entry or None."""
            if not tag:
                return None
            return _cue.markers._get_or_create_entry(create_vid_key(tag))

        # ==================================================================
        # Mutation (persist on every change)
        # ==================================================================

        def append_speed(self, speed):
            """Append a speed to the current video's sequence. Persists immediately."""
            tag = _cue.current_file
            if not tag:
                return
            entry = self._get_entry(tag)
            if entry is None:
                return
            seq = entry.setdefault("speed_sequence", [])
            seq.append(speed)
            _cue_log("VQ-APPEND tag={} speed={} seq={}".format(tag, speed, seq))
            if len(seq) >= 1:
                self.start(tag)

            _cue.markers.save_persistent()
            renpy.restart_interaction()

        def remove_at(self, index):
            """Remove the speed at index from the current video's sequence."""
            tag = _cue.current_file
            if not tag:
                return
            entry = _cue.markers.get(create_vid_key(tag))
            if entry is None:
                return
            seq = entry.get("speed_sequence")
            if not seq or not (0 <= index < len(seq)):
                return
            seq.pop(index)
            if not seq:
                entry.pop("speed_sequence", None)

            _cue.markers.save_persistent()
            if self.active_tag == tag:
                self.start(tag)
            else:
                renpy.restart_interaction()

        def move(self, index, delta):
            """Swap the speed at index with its neighbor (delta = -1 or 1)."""
            tag = _cue.current_file
            if not tag:
                return
            entry = _cue.markers.get(create_vid_key(tag))
            if entry is None:
                return
            seq = entry.get("speed_sequence")
            if not seq:
                return
            new_index = index + delta
            if new_index < 0 or new_index >= len(seq):
                return
            seq[index], seq[new_index] = seq[new_index], seq[index]

            _cue.markers.save_persistent()
            if self.active_tag == tag:
                self.start(tag)
            else:
                renpy.restart_interaction()

        def clear_sequence(self, tag=None):
            """Remove the entire speed sequence for the current video."""
            if tag is None:
                tag = _cue.current_file
            if not tag:
                return
            entry = _cue.markers.get(create_vid_key(tag))
            if entry is not None and "speed_sequence" in entry:
                del entry["speed_sequence"]
                _cue.markers.save_persistent()

            self.cancel()
            renpy.restart_interaction()

        # ==================================================================
        # Mode (speed vs sequence)
        # ==================================================================

        def get_mode(self, tag=None):
            """Return 'speed' or 'sequence' for the current or given tag."""
            if tag is None:
                tag = _cue.current_file
            if not tag:
                return SpeedMode.SINGLE
            entry = _cue.markers.get(create_vid_key(tag))
            if entry is None:
                return SpeedMode.SINGLE
            return entry.get("speed_mode", SpeedMode.SINGLE)

        def set_mode(self, mode, tag=None):
            """Set playback mode. Persists immediately."""
            if tag is None:
                tag = _cue.current_file
            if not tag or mode not in (SpeedMode.SINGLE, SpeedMode.SEQUENCE):
                return
            entry = self._get_entry(tag)
            if entry is None:
                return
            entry["speed_mode"] = mode
            
            _cue.markers.save_persistent()
            if mode == SpeedMode.SEQUENCE:
                self.start(tag)
            else:
                self.cancel()
                renpy.restart_interaction()

        # ==================================================================
        # Playback
        # ==================================================================

        def paths_for(self, tag):
            """Resolved file list for the tag's sequence, or None if unusable.
            Default speed entries use the base path; others use generated variants.
            Missing variant files are skipped (renpy.loadable handles .rpa)."""
            speeds = self.speeds_for(tag)
            base_path = self.resolver.base_path_for(tag)
            if not speeds or len(speeds) < 1 or not base_path:
                return None
            paths = []
            for sp in speeds:
                if sp == _cue.DEFAULT_VIDEO_SPEED:
                    paths.append(base_path)
                else:
                    vpath = self.resolver.variant_path(base_path, sp)
                    if renpy.loadable(vpath):
                        paths.append(vpath)
            if len(paths) < 1:
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
            self.play_count = 0
            self._step_index = 0
            self.last_playing = None
            self.last_elapsed = 0.0
            _cue_log("VQ-START tag={} paths={}".format(tag, ",".join(paths)))
            renpy.restart_interaction()

        def handle(self, tag):
            """Context-change hook. Starts the sequence when mode is 'sequence'
            and a sequence exists for the tag."""
            old_tag = self.active_tag
            speeds = self.speeds_for(tag)
            if speeds and self.get_mode(tag) == SpeedMode.SEQUENCE:
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

            is_wrap_around = now_playing and now_elapsed < 0.2 and self.last_elapsed - now_elapsed > 0.2
            is_new_play = (now_playing != self.last_playing or is_wrap_around)
            
            if is_new_play:
                # On the very first detection (last_playing was None),
                # _step_index is already 0 from start() — don't advance.
                if self.play_count > 0:
                    seq = self.speeds_for(self.active_tag)
                    if seq:
                        self._step_index = (self._step_index + 1) % len(seq)
                self.play_count += 1

                _cue_log("VQ-PLAY #{} step={} file={}".format(
                    self.play_count, self._step_index,
                    now_playing.rsplit("/", 1)[-1] if now_playing else now_playing))
                renpy.restart_interaction()

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
