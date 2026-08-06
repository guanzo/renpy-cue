###############################################################################
# CueVideoEditor — edit the currently-playing video file.
# Currently supports: playback speed change via ffmpeg.
# No preview, no marker rescaling.
#
# Per-video state: one CueVideoEditorState per virtual path, held in _states
# dict. Switching videos switches which state the UI reads/writes.
# Instantiated once at _cue.video_editor, lives on the NoRollback _cue object.
###############################################################################

init -999 python:
    import subprocess as _subprocess
    import threading as _threading
    import time as _time

    # Encode mode constants (global — shared with cue_marker.rpy)
    CUE_VE_MODE_NORMAL = 0
    CUE_VE_MODE_INTERPOLATE = 1
    CUE_VE_MODE_FAST_PREVIEW = 2

    class CueVideoEditorState:
        """Editing state for a single video file."""

        def __init__(self, vpath):
            self.vpath = vpath
            self.factor_text = "1.00"
            self.last_error = ""
            self.last_factor = None    # float set on edit completion, None = never edited
            self.last_encode_mode = CUE_VE_MODE_NORMAL  # 0 normal, 1 interpolate, 2 fast preview


    class CueVideoJob:
        """One ffmpeg encode job in the queue."""

        def __init__(self, job_id, vpath, fspath_in, fspath_tmp, factor, encode_mode,
                     fspath_out=None):
            self.job_id = job_id
            self.vpath = vpath
            self.fspath_in = fspath_in
            self.fspath_tmp = fspath_tmp
            self.factor = factor
            self.encode_mode = encode_mode
            self.fspath_out = fspath_out  # variant output path
            self.status = "queued"      # queued | analyzing | encoding | done | error
            self.progress = 0.0
            self.error_msg = ""
            self.start_time = 0.0
            self.end_time = 0.0
            self.total_frames = 0
            self.passlog = None
            self.cancelled = False
            self.proc = None            # Popen handle (set by worker thread)
            self._done = False          # worker sets True when finished
            self._ok = False            # True if ffmpeg exited 0 and output exists

        def elapsed(self):
            if not self.start_time:
                return 0.0
            if self.status in ("done", "error") and self.end_time:
                return self.end_time - self.start_time
            return _time.time() - self.start_time

        def status_text(self):
            if self.status == "queued":
                return "Queued"
            if self.status == "analyzing":
                return "Analyzing"
            if self.status == "encoding":
                _pct = int(self.progress * 100)
                return "Encoding {}%".format(_pct)
            if self.status == "done":
                return "Done"
            if self.status == "error":
                if self.error_msg == "Cancelled":
                    return "Cancelled"
                return "Error"
            return self.status

        def filename(self):
            """Basename of the target video for display (never the .bak source)."""
            if self.vpath:
                return os.path.basename(self.vpath)
            return "?"

        @property
        def speed_label(self):
            """Speed factor for queue display, e.g. '1.5x'."""
            return "{:.1f}x".format(self.factor)


    class CueVideoEditor:
        """Change the playback speed of the currently-playing video.

        State lives on the NoRollback _cue object so it survives rollback.
        ffmpeg runs on a daemon thread; a screen timer polls for completion
        so all Ren'Py calls stay on the main thread."""

        # --- constants ---
        SPEED_MIN = 0.1
        SPEED_MAX = 10.0

        MODE_NORMAL = CUE_VE_MODE_NORMAL
        MODE_INTERPOLATE = CUE_VE_MODE_INTERPOLATE
        MODE_FAST_PREVIEW = CUE_VE_MODE_FAST_PREVIEW

        def __init__(self):
            # --- Per-video state ---
            self._states = {}               # vpath -> CueVideoEditorState
            self._current = None            # CueVideoEditorState for current video

            # --- UI flags (flat — not per-video) ---
            self.active = False             # True when Video Editor section is shown
            self._ready = False             # True after ffmpeg probe cache is warm
            self._warm_cache_error = ""      # "" = ok, else the exception string from warmup
            self.encode_mode = CUE_VE_MODE_INTERPOLATE  # Global encode mode: 0 normal, 1 interpolate, 2 fast preview

            # --- Job queue ---
            self._jobs = []                 # list of CueVideoJob
            self._current_job = None        # CueVideoJob currently processing, or None
            self._next_job_id = 1           # incrementing counter for job_id

        @property
        def processing(self):
            return self._current_job is not None

        # ==================================================================
        # Properties — delegate to _current state so UI code Just Works
        # ==================================================================

        def _get_state(self):
            return self._current
        def _get_state_or_dummy(self):
            """Return _current or a throwaway state so reads don't crash."""
            if self._current is not None:
                return self._current
            return CueVideoEditorState("")

        @property
        def factor_text(self):
            return self._get_state_or_dummy().factor_text

        @factor_text.setter
        def factor_text(self, value):
            s = self._get_state()
            if s is not None:
                s.factor_text = value

        @property
        def last_error(self):
            return self._get_state_or_dummy().last_error

        @last_error.setter
        def last_error(self, value):
            s = self._get_state()
            if s is not None:
                s.last_error = self._esc(value)

        @property
        def config_label(self):
            """Human-readable summary of the last edit config for the current
            video, e.g. '1.5x interpolated' or '2.0x'. Returns '' if the
            current video has never been edited."""
            s = self._get_state()
            if s is None or s.last_factor is None:
                return ""
            label = "{:.1f}x".format(s.last_factor)
            if s.last_encode_mode == self.MODE_FAST_PREVIEW:
                label += " fast preview"
            elif s.last_encode_mode == self.MODE_INTERPOLATE:
                label += " interpolated"
            return label

        # ==================================================================
        # Helpers
        # ==================================================================

        def _get_video_vpath(self):
            """Virtual path (relative to gamedir) of the currently-playing video."""
            return _cue.vid_manager.get_video_path()

        def _get_video_fspath(self):
            """Real filesystem path of the current video, or None."""
            vp = self._get_video_vpath()
            if not vp:
                return None
            vp = vp.replace("\\", "/")
            fs = os.path.normpath(os.path.join(renpy.config.gamedir, vp))
            if os.path.exists(fs):
                return fs
            return None

        def _is_in_rpa(self):
            """True if video is playing but not on the real filesystem.
            If Ren'Py can play it, renpy.file() can read it — no need to
            search renpy.list_files() (which may not include video files)."""
            vp = self._get_video_vpath()
            if not vp:
                return False
            return self._get_video_fspath() is None

        def _backup_path(self, fspath):
            """Backup lives next to the original: movie.bak.webm"""
            base, ext = os.path.splitext(fspath)
            return "{}.bak{}".format(base, ext)

        # ==================================================================
        # RPA extraction
        # ==================================================================

        def extract_from_rpa(self):
            """Extract the current video from .rpa to the real filesystem.

            Uses Ren'Py's virtual file system (renpy.file) which can read
            from archives transparently. Writes in chunks to avoid memory
            pressure on large files. Returns ('ok', fspath) or ('error', msg)."""
            vp = self._get_video_vpath()
            if not vp:
                return ("error", "No video is currently playing.")
            vp = vp.replace("\\", "/")

            out_dir = os.path.dirname(os.path.join(renpy.config.gamedir, vp))
            try:
                if not os.path.isdir(out_dir):
                    os.makedirs(out_dir)
            except Exception as e:
                return ("error", "Cannot create directory: {}".format(e))

            fspath = os.path.join(renpy.config.gamedir, vp)

            try:
                fh = renpy.file(vp)
            except Exception as e:
                return ("error", "Cannot open '{}' in game archives: {}".format(vp, e))

            try:
                fh_out = open(fspath, "wb")
                try:
                    while True:
                        chunk = fh.read(1024 * 1024)
                        if not chunk:
                            break
                        fh_out.write(chunk)
                finally:
                    fh_out.close()
            except Exception as e:
                try:
                    os.remove(fspath)
                except Exception:
                    pass
                return ("error", "Failed to write extracted file: {}".format(e))
            finally:
                fh.close()

            return ("ok", fspath)

        # ==================================================================
        # Pre-flight checks
        # ==================================================================

        def check_prerequisites(self):
            """Return ('ok', '') or ('error', message) describing what's missing."""
            if not self._get_video_vpath():
                return ("error", "No video is currently playing.")

            fs = self._get_video_fspath()
            if fs is None:
                if self._is_in_rpa():
                    return ("rpa", "Video is inside an .rpa archive — extract it first.")
                return ("error", "Video file not found on disk.")

            if not os.access(fs, os.W_OK):
                return ("error", "Video file is read-only.")

            d = os.path.dirname(fs)
            if not os.access(d, os.W_OK):
                return ("error", "Video directory is read-only.")

            if not _cue.ffmpeg.ffmpeg_available():
                return ("error", "ffmpeg not found. Install ffmpeg and restart the game, or set RENPY_CUE_FFMPEG environment variable.")

            return ("ok", "")

        # ==================================================================
        # State helpers
        # ==================================================================

        def _ensure_state(self, vpath):
            """Get or create the CueVideoEditorState for vpath."""
            if vpath not in self._states:
                self._states[vpath] = CueVideoEditorState(vpath)
            return self._states[vpath]

        def _save_encode_settings(self):
            """Persist encode mode via the shared markers key."""
            _cue.markers.save_persistent()

        def _state_for_vpath(self, vpath):
            """Return the state for vpath, or None if it doesn't exist."""
            return self._states.get(vpath)

        # ==================================================================
        # Speed input UI methods (called from screens via Function())
        # ==================================================================

        def set_quick(self, mult):
            """Set speed factor from a quick-select button (0.5, 1.0, 1.5, 2.0)."""
            mult = max(self.SPEED_MIN, min(self.SPEED_MAX, float(mult)))
            self.factor_text = "{:.1f}".format(mult)
            self.last_error = ""
            renpy.restart_interaction()

        def commit_text(self):
            """Parse and clamp the text input."""
            try:
                v = float(self.factor_text)
            except (ValueError, TypeError):
                v = 1.0
            v = max(self.SPEED_MIN, min(self.SPEED_MAX, v))
            self.factor_text = "{:.1f}".format(v)
            self.last_error = ""
            renpy.restart_interaction()

        def nudge(self, delta):
            """Adjust speed factor by delta (e.g., +0.1 or -0.1)."""
            try:
                v = float(self.factor_text)
            except (ValueError, TypeError):
                v = 1.0
            v = max(self.SPEED_MIN, min(self.SPEED_MAX, v + delta))
            self.factor_text = "{:.1f}".format(v)
            self.last_error = ""
            renpy.restart_interaction()

        # ==================================================================
        # Probe cache warming (background thread so main thread never blocks)
        # ==================================================================

        def _warm_cache(self):
            """Run ffmpeg/ffprobe probes and load encoder list. Blocking —
            must be called from a background thread, never main."""
            _cue.ffmpeg.ffmpeg_available()
            _cue.ffmpeg.ffprobe_available()
            _cue.ffmpeg.load_encoders()

        def _warm_tools(self):
            """Background thread entry: warm the probe cache, then flag ready."""
            try:
                self._warm_cache()
            except Exception as e:
                self._warm_cache_error = str(e)
            self._ready = True

        def open_editor(self):
            """Show the Video Editor section, loading state for current video."""
            self.active = True
            self.refresh()
            

        def get_factor(self):
            """Parse factor_text to float. Returns 1.0 on failure."""
            try:
                return float(self.factor_text)
            except (ValueError, TypeError):
                return 1.0

        def set_encode_mode(self, mode, save=True, restart=True):
            """Select the encode mode for new jobs: 0=normal, 1=interpolate,
            2=fast preview. Invalid modes are ignored (mode unchanged)."""
            mode = int(mode)
            if mode not in (self.MODE_NORMAL, self.MODE_INTERPOLATE, self.MODE_FAST_PREVIEW):
                return
            self.encode_mode = mode
            if save:
                self._save_encode_settings()
            if restart:
                renpy.restart_interaction()

        def close_editor(self):
            """Return to the normal Video SFX section."""
            self.active = False
            self._current = None
            renpy.restart_interaction()

        # ==================================================================
        # Apply flow
        # ==================================================================

        @_cue_ui_refresh
        def prepare_create(self):
            """Pre-flight check then show confirmation dialog (main thread)."""
            if not self._ready:
                self.last_error = "Checking ffmpeg — try again in a moment."
                return
            if self._warm_cache_error:
                self.last_error = "ffmpeg check failed: {}".format(self._warm_cache_error)
                return

            status, msg = self.check_prerequisites()
            if status == "error":
                self.last_error = msg
                return

            if status == "rpa":
                self._extract_then_create()
                return

            try:
                factor = float(self.factor_text)
            except (ValueError, TypeError):
                factor = 1.0
            factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))

            if abs(factor - 1.0) < 0.05 and self.encode_mode != self.MODE_INTERPOLATE:
                self.last_error = "Speed is already 1.00x."
                return

            fs = self._get_video_fspath()
            self.create(factor)

        @_cue_ui_refresh
        def _extract_then_create(self):
            """Callback after user confirms RPA extraction. Extract first, then create."""
            self.last_error = ""
            ok, msg = self.extract_from_rpa()
            if ok == "error":
                self.last_error = msg
                return

            status, msg2 = self.check_prerequisites()
            if status == "error":
                self.last_error = msg2
                return

            try:
                factor = float(self.factor_text)
            except (ValueError, TypeError):
                factor = 1.0
            factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))

            fs = self._get_video_fspath()
            self.create(factor)

        @_cue_ui_refresh
        def create(self, factor):
            """Enqueue a speed-change job (main thread).
            Generates a variant file alongside the original instead of
            replacing it. The variant appears in the Speed: toggle row."""
            fs = self._get_video_fspath()
            if not fs:
                self.last_error = "Video file disappeared."
                return

            # Use the resolver's original base path for display and output
            # naming, not the currently-playing file (which may be a variant).
            vp = _cue_resolver_base_path_for(_cue.current_file) or self._get_video_vpath()
            orig_vpath = vp
            orig_vpath = orig_vpath.replace("\\", "/")
            orig_fs = os.path.normpath(os.path.join(renpy.config.gamedir, orig_vpath))

            # Build variant output path: movie.2.0x.webm
            base, ext = os.path.splitext(orig_fs)
            if not ext:
                ext = ".webm"
            out_fspath = "{}.{:.1f}x{}".format(base, factor, ext)

            # Build temp path in same directory (atomic rename after success)
            temp_path = os.path.join(
                os.path.dirname(orig_fs),
                "{}__cue_tmp_{:.1f}x{}".format(os.path.basename(base), factor, ext),
            )

            # Always transcode from the backup (pristine original) if it
            # exists. Otherwise repeated edits would compound quality loss.
            backup_path = self._backup_path(orig_fs)
            if os.path.exists(backup_path):
                input_fs = backup_path
            else:
                input_fs = orig_fs

            # Create job — writes a variant alongside the original
            job_id = self._next_job_id
            self._next_job_id += 1
            job = CueVideoJob(job_id, vp, input_fs, temp_path, factor,
                              self.encode_mode,
                              fspath_out=out_fspath)
            self._jobs.append(job)

            _cue_log("Speed variant job queued: id={}, factor={:.1f}, out={}".format(
                job_id, factor, os.path.basename(out_fspath)))
            self._start_if_idle()

        def _find_job(self, job_id):
            """Return the CueVideoJob with job_id, or None."""
            for j in self._jobs:
                if j.job_id == job_id:
                    return j
            return None

        def _start_if_idle(self):
            """If no job is currently processing, start the next queued one."""
            if self._current_job is None:
                self._start_next_job()

        def apply_variant(self, speed, out_fspath):
            """Start ffmpeg to generate a speed variant file alongside the original."""
            if self.processing:
                return

            vp = self._get_video_vpath()
            fs = self._get_video_fspath()
            if not fs:
                _cue_log("SPEED-VARIANT: apply_variant failed — no filesystem path")
                renpy.restart_interaction()
                return

            # Use the resolver's original base path, not the
            # currently-playing file (which may be a variant).
            orig_vpath = _cue_resolver_base_path_for(_cue.current_file) or vp
            orig_vpath = orig_vpath.replace("\\", "/")
            orig_fs = os.path.normpath(os.path.join(renpy.config.gamedir, orig_vpath))

            # Build temp path in same directory (atomic rename after success)
            base, ext = os.path.splitext(os.path.basename(orig_fs))
            if not ext:
                ext = ".webm"
            temp_path = os.path.join(
                os.path.dirname(out_fspath),
                "{}__cue_tmp_{:.1f}x{}".format(base, speed, ext),
            )

            # Always transcode from the backup (pristine original) if it
            # exists. Otherwise repeated edits would compound quality loss.
            backup_path = self._backup_path(orig_fs)
            if os.path.exists(backup_path):
                input_fs = backup_path
            else:
                input_fs = orig_fs

            # Create job and add to queue
            job_id = self._next_job_id
            self._next_job_id += 1
            # Variants never use fast preview — downgrade to normal
            _enc_mode = self.encode_mode
            if _enc_mode == self.MODE_FAST_PREVIEW:
                _enc_mode = self.MODE_NORMAL
            job = CueVideoJob(job_id, vp, input_fs, temp_path, speed,
                              _enc_mode, fspath_out=out_fspath)
            self._jobs.append(job)

            _cue_log("Variant job queued: id={}, speed={:.1f}, out={}".format(
                job_id, speed, os.path.basename(out_fspath)))
            self._start_if_idle()

        def _start_next_job(self):
            """Pick the first queued job and start its worker thread."""
            job = None
            for j in self._jobs:
                if j.status == "queued":
                    job = j
                    break
            if job is None:
                return

            self._current_job = job
            job.start_time = _time.time()
            job.status = "analyzing"

            # Capture duration for progress (fast — no subprocess)
            dur_ms = 0
            try:
                dur_ms = int(renpy.music.get_duration(channel=_cue.active_channel) * 1000)
            except Exception:
                pass

            t = _threading.Thread(
                target=self._worker,
                args=(job, dur_ms),
            )
            t.daemon = True
            t.start()
            _cue_log("Speed worker started: job_id={}, factor={:.1f}, file={}".format(
                job.job_id, job.factor, os.path.basename(job.fspath_in)))
            renpy.restart_interaction()

        def _worker(self, job, dur_ms):
            """Background thread: probe codecs, build command, run ffmpeg.
            Reads -progress pipe:1 line by line to update job.progress.
            All subprocess calls are off the main thread — no game freeze."""
            input_fs = job.fspath_in
            temp_path = job.fspath_tmp
            factor = job.factor
            try:
                # --- Probe codecs and bitrate from input file ---
                vcodec = ""
                acodec = ""
                has_audio = True
                target_bitrate = None
                if _cue.ffmpeg.ffprobe_available():
                    vc_in, ac_in = _cue.ffmpeg.probe_codecs(input_fs)
                    has_audio = _cue.ffmpeg.probe_has_audio(input_fs)
                    if vc_in:
                        vcodec = _cue.ffmpeg.pick_encoder(vc_in, "video") or ""
                    if ac_in and has_audio:
                        acodec = _cue.ffmpeg.pick_encoder(ac_in, "audio") or ""
                    # Probe source bitrate for quality matching
                    target_bitrate = _cue.ffmpeg.probe_bitrate(input_fs)
                    _cue_log("probed vcodec: {} -> {}, acodec: {} -> {}, audio: {}, bitrate: {}".format(
                        vc_in, vcodec, ac_in, acodec, has_audio, target_bitrate))

                if job.cancelled:
                    return

                # --- Build ffmpeg command(s) ---
                interpolate = (job.encode_mode == CUE_VE_MODE_INTERPOLATE)
                source_fps = _cue.ffmpeg.probe_fps(input_fs)
                # Total output frames for progress. -vsync 0 preserves frame count
                # unless minterpolate generates new frames at a different rate.
                if interpolate:
                    _out_fps = min(60, source_fps * 2)
                    total_frames = _out_fps * (dur_ms / 1000.0) / factor
                else:
                    total_frames = source_fps * (dur_ms / 1000.0)
                job.total_frames = total_frames
                cmds, passlog = _cue.ffmpeg.build_ffmpeg_cmds(
                    input_fs, temp_path, factor,
                    vcodec, acodec, has_audio,
                    target_bitrate,
                    interpolate=interpolate,
                    source_fps=source_fps,
                    fast=(job.encode_mode == CUE_VE_MODE_FAST_PREVIEW),
                )
                job.passlog = passlog

                # --- Run ffmpeg (1 or 2 passes) ---
                # Log file next to debug.log for troubleshooting
                log_path = os.path.join(renpy.config.gamedir, _cue.base_dir, "ffmpeg.log")
                with open(log_path, "w") as _logf:
                    _logf.write("cmd: {}\n".format(" ".join(cmds[0])))
                for pass_idx, cmd in enumerate(cmds):
                    if job.cancelled:
                        break
                    if len(cmds) == 1 or pass_idx > 0:
                        job.status = "encoding"
                    job.progress = 0.0
                    job.proc = _subprocess.Popen(
                        cmd,
                        stdout=_subprocess.PIPE,
                        stderr=_subprocess.PIPE,
                        creationflags=_CREATIONFLAGS,
                    )
                    all_out = []
                    for line in iter(job.proc.stdout.readline, b""):
                        if job.cancelled:
                            break
                        all_out.append(line)
                        if isinstance(line, bytes):
                            line_str = line.decode("utf-8", errors="replace").strip()
                        else:
                            line_str = str(line).strip()

                        if line_str.startswith("frame="):
                            try:
                                _frame = int(line_str.split("=", 1)[1])
                                if total_frames > 0:
                                    job.progress = min(1.0, float(_frame) / total_frames)
                            except (ValueError, IndexError):
                                pass

                    err_out = job.proc.stderr.read()
                    job.proc.stdout.close()
                    job.proc.stderr.close()
                    rc = job.proc.wait()
                    job.proc = None  # child reaped; prevent finally from kill()ing stale pid

                    # Append pass output to log
                    with open(log_path, "a") as _logf:
                        _logf.write("--- pass {} (rc={}) ---\n".format(pass_idx + 1, rc))
                        for line in all_out:
                            if isinstance(line, bytes):
                                _logf.write(line.decode("utf-8", errors="replace"))
                            else:
                                _logf.write(str(line))
                        if err_out:
                            _logf.write("\n[stderr]\n")
                            if isinstance(err_out, bytes):
                                _logf.write(err_out.decode("utf-8", errors="replace"))
                            else:
                                _logf.write(str(err_out))
                            _logf.write("\n")

                    if job.cancelled:
                        self._kill_job_proc_for(job)
                        break
                    if rc != 0:
                        self._kill_job_proc_for(job)
                        job.error_msg = "ffmpeg pass {} exited with code {}".format(
                            pass_idx + 1, rc)
                        break

                # --- Clean up 2-pass artifacts ---
                if passlog:
                    try:
                        for f in [passlog + "-0.log", passlog + "-1.log"]:
                            if os.path.exists(f):
                                os.remove(f)
                    except Exception:
                        pass

                if job.cancelled:
                    job._done = True
                    return

                # All passes completed with rc=0
                if not job.error_msg and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    job._ok = True
                    job.progress = 1.0
                    _cue_log("Speed worker: ffmpeg succeeded")
                elif not job.error_msg:
                    job.error_msg = "ffmpeg produced no output"
                    _cue_log("Speed worker: FAILED — no output file")
            except Exception as e:
                if not job.cancelled:
                    job.error_msg = "ffmpeg error: {}".format(e)
                    _cue_log("Speed worker: exception — {}".format(e))
            finally:
                self._kill_job_proc_for(job)
                job._done = True

        def poll_jobs(self):
            """Called by screen timer and tick_trigger on the main thread.
            When the worker is done, finalize or report error."""
            job = self._current_job
            if job is None:
                return

            if not job._done:
                if job.cancelled:
                    renpy.restart_interaction()
                return

            job.end_time = _time.time()

            if job.cancelled:
                self._cleanup_temp_for(job)
                job.status = "error"
                job.error_msg = "Cancelled"
                _cue_log("Speed: cancelled by user (job_id={})".format(job.job_id))
            elif not job._ok:
                self._cleanup_temp_for(job)
                job.status = "error"
                _cue_log("Speed: job failed (job_id={})".format(job.job_id))
            else:
                self._finish_variant(job)

            self._current_job = None
            self._start_next_job()
            renpy.restart_interaction()

        def _finish_variant(self, job):
            """Move the temp file to the final variant path, replacing any
            existing variant. Stops channels playing the target, then retries
            the swap up to 4 times with backoff to handle file locks."""
            tmp = job.fspath_tmp
            out = job.fspath_out
            speed = job.factor
            vp = job.vpath

            if not tmp or not out:
                _cue_log("Variant: FAILED — missing tmp or out path (job_id={})".format(job.job_id))
                job.status = "error"
                job.error_msg = "Missing paths"
                return

            # Validate temp file
            try:
                if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                    self._cleanup_temp_for(job)
                    _cue_log("Variant: FAILED — empty or missing temp (job_id={})".format(job.job_id))
                    job.status = "error"
                    job.error_msg = "Empty output"
                    return
            except Exception:
                self._cleanup_temp_for(job)
                job.status = "error"
                job.error_msg = "Cannot read temp"
                return

            # Stop channels playing the variant we're about to replace
            try:
                import renpy.audio.audio as _aaudio
                for _ch_name in _aaudio.channels:
                    _playing = renpy.music.get_playing(channel=_ch_name)
                    if _playing:
                        _playing_fs = os.path.join(renpy.config.gamedir, _playing)
                        if os.path.normpath(_playing_fs) == os.path.normpath(out):
                            renpy.music.stop(channel=_ch_name, fadeout=0)
            except Exception:
                pass
            _time.sleep(0.5)

            # Swap with retries
            for _attempt in range(4):
                try:
                    if os.path.exists(out):
                        os.remove(out)
                    os.rename(tmp, out)
                    job.status = "done"
                    state = self._ensure_state(vp)
                    state.last_error = ""
                    state.last_factor = job.factor
                    state.last_encode_mode = job.encode_mode
                    _cue_log("Variant: generated {:.1f}x at {} (job_id={})".format(
                        speed, os.path.basename(out), job.job_id))
                    _cue.markers.save_persistent()
                    return
                except Exception:
                    if _attempt < 3:
                        _time.sleep(1.0)

            # All attempts failed — leave temp for retry
            state = self._ensure_state(vp)
            state.last_error = self._esc(
                "The game still has this video file open. "
                "Advance past this video scene, then try again.")
            job.status = "error"
            job.error_msg = "File locked — retry later"
            _cue_log("Variant: swap FAILED — file locked (job_id={})".format(job.job_id))

        def retry_job(self, job_id):
            """Retry a failed job from where it left off. If the temp file
            exists, skip straight to swap. Otherwise re-encode from scratch."""
            job = self._find_job(job_id)
            if job is None or job.status != "error":
                return

            if os.path.exists(job.fspath_tmp):
                # Temp still exists — finish the swap
                _cue_log("Speed: retry finish (job_id={})".format(job_id))
                self._finish_variant(job)
            else:
                # Need to re-encode
                _cue_log("Speed: retry encode (job_id={})".format(job_id))
                job.status = "queued"
                job._done = False
                job._ok = False
                job.progress = 0.0
                job.error_msg = ""
                self._start_if_idle()

            renpy.restart_interaction()

        @staticmethod
        def _esc(text):
            """Escape square brackets so Ren'Py text interpolation doesn't
            try to resolve them as variable references."""
            if text:
                return text.replace("[", "[[").replace("]", "]]")
            return text


        def _cleanup_temp_for(self, job):
            """Remove the temp transcoded file if it exists."""
            try:
                tmp = job.fspath_tmp
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

        # ==================================================================
        # Cancel / Remove
        # ==================================================================

        def _kill_job_proc_for(self, job):
            """Kill a job's ffmpeg process and wait for it. Safe to call
            from any thread, or when job.proc is None."""
            try:
                if job.proc is not None:
                    p = job.proc
                    # Kill first — unblocks any readline() immediately
                    # so the main thread never freezes waiting on a pipe
                    # close (especially VP8/VP9 pass-1 which has no
                    # -progress pipe:1 output).
                    p.kill()
                    for _pipe in (p.stdout, p.stderr):
                        if _pipe is not None:
                            try:
                                _pipe.close()
                            except Exception:
                                pass
                    try:
                        p.wait()
                    except Exception:
                        pass
            except Exception:
                pass
            job.proc = None

        def cancel_job(self, job_id):
            """Cancel a job by job_id (main thread, called from screen action)."""
            job = self._find_job(job_id)
            if job is None:
                return
            if job.status == "queued":
                self._jobs.remove(job)
                _cue_log("Speed: de-queued job_id={}".format(job_id))
            elif job is self._current_job:
                job.cancelled = True
                self._kill_job_proc_for(job)
                _cue_log("Speed: cancel requested for job_id={}".format(job_id))
            elif job.status in ("done", "error"):
                self.remove_job(job_id)
            renpy.restart_interaction()

        def remove_job(self, job_id):
            """Remove a completed job from the list (main thread, screen action)."""
            job = self._find_job(job_id)
            if job is not None and job.status in ("done", "error"):
                self._jobs.remove(job)
                _cue_log("Speed: removed job_id={} from list".format(job_id))
            renpy.restart_interaction()

        # ==================================================================
        # Restore
        # ==================================================================

        @_cue_ui_refresh
        @staticmethod
        def cleanup_orphans():
            """Remove leftover tmp and passlog files from interrupted encodes.
            Called once on init. Never touches *.bak* backups."""
            import glob as _glob
            removed = 0
            try:
                gamedir = renpy.config.gamedir
                for dirpath, _dirnames, _filenames in os.walk(gamedir):
                    for pattern in ("*__cue_tmp_*",):
                        for f in _glob.glob(os.path.join(dirpath, pattern)):
                            try:
                                os.remove(f)
                                removed += 1
                            except Exception:
                                pass
            except Exception:
                pass
            if removed:
                _cue_log("CLEANUP-ORPHANS: removed {} leftover temp file(s)".format(removed))

        # ==================================================================
        # Refresh (called when overlay is shown)
        # ==================================================================

        def refresh(self):
            """Load state for the current video.
            Called on overlay open and when context changes."""

            vp = self._get_video_vpath()

            if vp:
                self._current = self._ensure_state(vp)
                self._current.last_error = ""
            # Warm ffmpeg/encoder probe cache in background (avoids main-thread
            # freeze when the user clicks Apply later). Only needed once.
            if _cue.ffmpeg._ffmpeg_cache == -1:
                self._ready = False
                t = _threading.Thread(target=self._warm_tools)
                t.daemon = True
                t.start()
            else:
                self._ready = True
            if self.processing:
                self.last_error = ""

            renpy.restart_interaction()

        def get_elapsed(self):
            """Seconds since current job started. Returns 0 if idle."""
            if self._current_job is not None:
                return self._current_job.elapsed()
            return 0.0

        def _refresh_ui(self):
            """Trigger a screen redraw while jobs are active."""
            if self._current_job is not None or self._jobs:
                renpy.restart_interaction()
