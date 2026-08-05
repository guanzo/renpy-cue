###############################################################################
# CueVideoEditor — edit the currently-playing video file.
# Currently supports: playback speed change via ffmpeg.
# Backs up the original, replaces the file in place, and can restore.
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

    class CueVideoEditorState:
        """Editing state for a single video file."""

        def __init__(self, vpath):
            self.vpath = vpath
            self.factor_text = "1.00"
            self.has_backup = False
            self.last_error = ""
            self.last_factor = None    # float set on edit completion, None = never edited
            self.last_interpolate = False
            self.last_fast_preview = False


    class CueVideoJob:
        """One ffmpeg encode job in the queue."""

        def __init__(self, job_id, vpath, fspath_in, fspath_tmp, factor, interpolate, fast_preview):
            self.job_id = job_id
            self.vpath = vpath
            self.fspath_in = fspath_in
            self.fspath_tmp = fspath_tmp
            self.factor = factor
            self.interpolate = interpolate
            self.fast_preview = fast_preview
            self.status = "queued"      # queued | analyzing | encoding | swapping | done | error
            self._swap_attempts = 0     # retry counter for the swap phase
            self.progress = 0.0
            self.error_msg = ""
            self.start_time = 0.0
            self.end_time = 0.0
            self.total_frames = 0
            self.passlog = None
            self.cancelled = False
            self.proc = None            # Popen handle (set by worker thread)
            self.backup_path = None     # set after successful finalize
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
            if self.status == "swapping":
                return "Swapping..."
            if self.status == "done":
                return "Done"
            if self.status == "error":
                msg = self.error_msg or "Unknown error"
                if msg == "Cancelled":
                    return "Cancelled"
                if len(msg) > 40:
                    msg = msg[:40] + "..."
                return "Error: {}".format(msg)
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
        SPEED_MIN = 0.25
        SPEED_MAX = 4.0

        TMP_SUFFIX = "__cue_speed_tmp"

        def __init__(self):
            # --- Per-video state ---
            self._states = {}               # vpath -> CueVideoEditorState
            self._current = None            # CueVideoEditorState for current video

            # --- UI flags (flat — not per-video) ---
            self.active = False             # True when Video Editor section is shown
            self._ready = False             # True after ffmpeg probe cache is warm
            self.interpolate = True         # Global frame interpolation toggle
            self.fast_preview = False    # Fast low-quality encode for judging speed

            # --- Job queue ---
            self._jobs = []                 # list of CueVideoJob
            self._current_job = None        # CueVideoJob currently processing, or None
            self._next_job_id = 1           # incrementing counter for job_id

            # --- Cached probe data ---
            self._probed_fps = 30           # probed source fps, refreshed in open_editor

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
        def has_backup(self):
            return self._get_state_or_dummy().has_backup

        @has_backup.setter
        def has_backup(self, value):
            s = self._get_state()
            if s is not None:
                s.has_backup = value

        @property
        def last_error(self):
            return self._get_state_or_dummy().last_error

        @last_error.setter
        def last_error(self, value):
            s = self._get_state()
            if s is not None:
                s.last_error = value

        @property
        def config_label(self):
            """Human-readable summary of the last edit config for the current
            video, e.g. '1.5x interpolated' or '2.0x'. Returns '' if the
            current video has never been edited."""
            s = self._get_state()
            if s is None or s.last_factor is None:
                return ""
            label = "{:.1f}x".format(s.last_factor)
            if s.last_fast_preview:
                label += " fast preview"
            elif s.last_interpolate:
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

        def _find_existing_backup(self, fspath):
            """Return the backup path if it exists, or None."""
            bp = self._backup_path(fspath)
            if os.path.exists(bp):
                return bp
            return None

        def _sync_backup_for_current(self):
            """Update current state's has_backup from the filesystem."""
            if self._current is None:
                return
            fs = self._get_video_fspath()
            if not fs:
                self._current.has_backup = False
                return
            self._current.has_backup = self._find_existing_backup(fs) is not None

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
                        if isinstance(chunk, str):
                            fh_out.write(chunk)
                        else:
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

        def _save_interpolate(self):
            """Persist interpolate setting via the shared markers key."""
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
            self.factor_text = "{:.2f}".format(mult)
            self.last_error = ""
            renpy.restart_interaction()

        def commit_text(self):
            """Parse and clamp the text input."""
            try:
                v = float(self.factor_text)
            except (ValueError, TypeError):
                v = 1.0
            v = max(self.SPEED_MIN, min(self.SPEED_MAX, v))
            self.factor_text = "{:.2f}".format(v)
            self.last_error = ""
            renpy.restart_interaction()

        def nudge(self, delta):
            """Adjust speed factor by delta (e.g., +0.1 or -0.1)."""
            try:
                v = float(self.factor_text)
            except (ValueError, TypeError):
                v = 1.0
            v = max(self.SPEED_MIN, min(self.SPEED_MAX, v + delta))
            self.factor_text = "{:.2f}".format(v)
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
            except Exception:
                pass
            self._ready = True

        @property
        def source_fps(self):
            return self._probed_fps

        def _probe_fps_bg(self, fspath):
            """Background thread: probe fps and flag done."""
            try:
                self._probed_fps = _cue.ffmpeg.probe_fps(fspath)
            except Exception:
                self._probed_fps = 30
            renpy.restart_interaction()

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

        def toggle_interpolate(self):
            """Toggle frame interpolation on/off (only relevant for speed > 1x)."""
            self.interpolate = not self.interpolate
            self._save_interpolate()
            renpy.restart_interaction()

        def toggle_fast_preview(self):
            """Toggle fast preview — fast low-quality encode for judging speed."""
            self.fast_preview = not self.fast_preview
            if self.fast_preview:
                self.interpolate = False
            renpy.restart_interaction()

        def close_editor(self):
            """Return to the normal Video SFX section."""
            self.active = False
            self._current = None
            renpy.restart_interaction()

        # ==================================================================
        # Apply flow
        # ==================================================================

        def prepare_create(self):
            """Pre-flight check then show confirmation dialog (main thread)."""
            if not self._ready:
                self.last_error = "Checking ffmpeg — try again in a moment."
                renpy.restart_interaction()
                return
            self._sync_backup_for_current()

            status, msg = self.check_prerequisites()
            if status == "error":
                self.last_error = msg
                renpy.restart_interaction()
                return

            if status == "rpa":
                self._extract_then_create()
                return

            try:
                factor = float(self.factor_text)
            except (ValueError, TypeError):
                factor = 1.0
            factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))

            if abs(factor - 1.0) < 0.001 and not self.interpolate:
                self.last_error = "Speed is already 1.00x."
                renpy.restart_interaction()
                return

            fs = self._get_video_fspath()
            self.create(factor)

        def _extract_then_create(self):
            """Callback after user confirms RPA extraction. Extract first, then create."""
            self.last_error = ""
            ok, msg = self.extract_from_rpa()
            if ok == "error":
                self.last_error = msg
                renpy.restart_interaction()
                return

            status, msg2 = self.check_prerequisites()
            if status == "error":
                self.last_error = msg2
                renpy.restart_interaction()
                return

            try:
                factor = float(self.factor_text)
            except (ValueError, TypeError):
                factor = 1.0
            factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))

            fs = self._get_video_fspath()
            self.create(factor)

        def create(self, factor):
            """Enqueue a speed-change job (main thread)."""
            vp = self._get_video_vpath()
            fs = self._get_video_fspath()
            if not fs:
                self.last_error = "Video file disappeared."
                renpy.restart_interaction()
                return

            # Build temp path in same directory (same fs = atomic rename)
            base, ext = os.path.splitext(os.path.basename(fs))
            if not ext:
                ext = ".webm"
            temp_path = os.path.join(
                os.path.dirname(fs),
                "{}{}{}".format(base, self.TMP_SUFFIX, ext),
            )

            # Always transcode from the backup (pristine original) if it
            # exists. Otherwise repeated edits would compound quality loss
            # from lossy re-encodes.
            backup_path = self._backup_path(fs)
            if os.path.exists(backup_path):
                input_fs = backup_path
            else:
                input_fs = fs

            # Create job and add to queue
            job_id = self._next_job_id
            self._next_job_id += 1
            job = CueVideoJob(job_id, vp, input_fs, temp_path, factor, self.interpolate, self.fast_preview)
            self._jobs.append(job)

            _cue_log("Speed job queued: id={}, factor={:.2f}, file={}".format(
                job_id, factor, os.path.basename(fs)))
            self._start_if_idle()
            renpy.restart_interaction()

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
            _cue_log("Speed worker started: job_id={}, factor={:.2f}, file={}".format(
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

                # --- Build ffmpeg command(s) ---
                interpolate = job.interpolate
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
                    fast=job.fast_preview,
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

        def poll(self):
            """Called by screen timer on the main thread. When the worker is
            done, finalize or report error. Swap retries on subsequent ticks
            if the file is still locked."""
            job = self._current_job
            if job is None:
                return

            if not job._done:
                return

            # Worker just finished — first poll tick after completion
            if job.status != "swapping":
                job.end_time = _time.time()

                if job.cancelled:
                    self._cleanup_temp_for(job)
                    job.status = "error"
                    job.error_msg = "Cancelled"
                    _cue_log("Speed: cancelled by user (job_id={})".format(job.job_id))
                    self._current_job = None
                    self._start_next_job()
                    renpy.restart_interaction()
                    return

                if not job._ok:
                    self._cleanup_temp_for(job)
                    job.status = "error"
                    _cue_log("Speed: job failed (job_id={})".format(job.job_id))
                    self._current_job = None
                    self._start_next_job()
                    renpy.restart_interaction()
                    return

                # --- Job succeeded, prepare for swap ---
                tmp = job.fspath_tmp
                fs = tmp.replace(self.TMP_SUFFIX, "")

                # Stop playback to release the file handle — only if the
                # current channel is playing this job's video.
                try:
                    if _cue.active_channel:
                        playing = renpy.music.get_playing(channel=_cue.active_channel)
                        if playing:
                            playing_fs = os.path.join(renpy.config.gamedir, playing)
                            if os.path.normpath(playing_fs) == os.path.normpath(fs):
                                renpy.music.stop(channel=_cue.active_channel, fadeout=0)
                except Exception:
                    pass

                # Create backup NOW (after ffmpeg success, before swap).
                # Only if a backup doesn't already exist — never overwrite
                # the original backup with an already-modified version.
                backup_path = self._backup_path(fs)
                if not os.path.exists(backup_path):
                    try:
                        with open(fs, "rb") as src:
                            with open(backup_path, "wb") as dst:
                                while True:
                                    chunk = src.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    dst.write(chunk)
                    except Exception as e:
                        self._cleanup_temp_for(job)
                        job.status = "error"
                        self._set_job_state_error_for(job,
                            "Cannot read the original video (file is locked by "
                            "the game player). Advance past this video scene, "
                            "then try again. ({})".format(e))
                        self._current_job = None
                        self._start_next_job()
                        _cue_log("Speed: backup FAILED (job_id={})".format(job.job_id))
                        renpy.restart_interaction()
                        return

                job.backup_path = backup_path
                job.status = "swapping"
                job._swap_attempts = 0
                # Don't clear _current_job — keep retrying on future ticks
                renpy.restart_interaction()
                return

            # --- Swapping phase — retry each poll tick ---
            if job.cancelled:
                job.status = "error"
                job.error_msg = "Cancelled"
                _cue_log("Speed: cancelled during swap (job_id={})".format(job.job_id))
                self._current_job = None
                self._start_next_job()
                renpy.restart_interaction()
                return

            job._swap_attempts += 1
            if self._try_swap(job):
                # Success — update state and move on
                vp = job.vpath
                fs = job.fspath_tmp.replace(self.TMP_SUFFIX, "")
                state = self._ensure_state(vp)
                state.has_backup = True
                state.last_error = ""
                state.last_factor = job.factor
                state.last_interpolate = job.interpolate
                state.last_fast_preview = job.fast_preview
                job.status = "done"
                _cue_log("Speed: swap complete, backup at {} (job_id={})".format(
                    os.path.basename(job.backup_path or ""), job.job_id))
                self._current_job = None
                self._start_next_job()
                renpy.restart_interaction()
                return

            # Swap still failing — give up after ~6 seconds (30 ticks × 0.2s)
            if job._swap_attempts >= 30:
                vp = job.vpath
                err = (
                    "The game still has this video file open. "
                    "Advance past this video scene, then try again.\n\n"
                    "(The transcoded file and backup are already saved — "
                    "advance one scene and click Create again.)"
                )
                state = self._ensure_state(vp)
                state.last_error = self._esc(err)
                job.status = "error"
                job.error_msg = "File locked — retry later"
                _cue_log("Speed: swap FAILED after {} attempts (job_id={})".format(
                    job._swap_attempts, job.job_id))
                self._current_job = None
                self._start_next_job()
                renpy.restart_interaction()
                return

            # Still retrying — trigger redraw for elapsed display
            renpy.restart_interaction()

        @staticmethod
        def _esc(text):
            """Escape square brackets so Ren'Py text interpolation doesn't
            try to resolve them as variable references."""
            if text:
                return text.replace("[", "[[").replace("]", "]]")
            return text

        def _set_job_state_error_for(self, job, msg):
            """Write an error to the state for the job's vpath."""
            vp = job.vpath
            state = self._state_for_vpath(vp)
            if state is not None:
                state.last_error = self._esc(msg)
            if self._current is not None and self._current.vpath == vp:
                pass  # last_error property already delegates to _current

        def _try_swap(self, job):
            """Try to replace the original file with the transcoded temp.
            Returns True on success, False if the file is still locked.
            Called from poll() on the main thread — gives Ren'Py one full
            interaction cycle between attempts to release the file handle."""
            tmp = job.fspath_tmp
            fs = tmp.replace(self.TMP_SUFFIX, "")
            try:
                os.remove(fs)
                os.rename(tmp, fs)
                return True
            except Exception:
                return False

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
                    # Close pipes first — if ffmpeg is blocked on a full
                    # stdout/stderr pipe buffer, kill() won't take effect
                    # until the buffer is drained.
                    for _pipe in (p.stdout, p.stderr):
                        if _pipe is not None:
                            try:
                                _pipe.close()
                            except Exception:
                                pass
                    p.kill()
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
                if job is self._current_job:
                    self._current_job = None
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

        def open_restore(self):
            """Confirm then restore (main thread)."""
            self._sync_backup_for_current()
            if not self.has_backup:
                self.last_error = "No backup exists for the current video."
                renpy.restart_interaction()
                return

            fs = self._get_video_fspath()
            if not fs:
                self.last_error = "Video file not found."
                renpy.restart_interaction()
                return

            backup = self._find_existing_backup(fs)
            if not backup:
                self.has_backup = False
                self.last_error = "Backup file not found."
                renpy.restart_interaction()
                return
            
            self.restore()

        def restore(self):
            """Restore the original video from backup (main thread, from confirm)."""
            vp = self._get_video_vpath()
            fs = self._get_video_fspath()
            if not fs:
                self.last_error = "Video file not found."
                renpy.restart_interaction()
                return

            backup = self._find_existing_backup(fs)
            if not backup:
                self.has_backup = False
                self.last_error = "Backup file not found."
                renpy.restart_interaction()
                return

            try:
                # Release file lock before swapping
                try:
                    if _cue.active_channel:
                        renpy.music.stop(channel=_cue.active_channel, fadeout=0)
                        _time.sleep(0.5)
                except Exception:
                    pass

                swap_ok = False
                for _attempt in range(4):
                    try:
                        if os.path.exists(fs):
                            os.remove(fs)
                        os.rename(backup, fs)
                        swap_ok = True
                        break
                    except Exception:
                        if _attempt < 3:
                            _time.sleep(1.0)
                if not swap_ok:
                    self.last_error = self._esc(
                        "Cannot restore — the file is still locked. "
                        "Advance past this video scene and try again.")
                    renpy.restart_interaction()
                    return

                state = self._ensure_state(vp) if vp else None
                if state:
                    state.has_backup = False
                    state.last_error = ""
                    state.last_factor = None
                    state.last_interpolate = False
                    state.last_fast_preview = False

                _cue_log("Speed: restore complete from {}".format(
                    os.path.basename(backup)))

                # Re-probe fps — the restored original may differ from the
                # replaced file (e.g. user slowed it down then restored).
                self._probed_fps = -1
                if fs:
                    t = _threading.Thread(target=self._probe_fps_bg, args=(fs,))
                    t.daemon = True
                    t.start()
            except Exception as e:
                self.last_error = self._esc(
                    "Cannot restore — the file may be locked. "
                    "Advance past this video scene and try again.")
                _cue_log("Speed: restore FAILED — {}".format(e))
            renpy.restart_interaction()

        @staticmethod
        def cleanup_orphans():
            """Remove leftover tmp and passlog files from interrupted encodes.
            Called once on init. Never touches *.bak* backups."""
            import glob as _glob
            removed = 0
            try:
                gamedir = renpy.config.gamedir
                for dirpath, _dirnames, _filenames in os.walk(gamedir):
                    for pattern in ("*" + CueVideoEditor.TMP_SUFFIX + "*",):
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
            """Update has_backup for the current video.
            Called on overlay open and when context changes."""

            vp = self._get_video_vpath()
            
            if vp:
                self._current = self._ensure_state(vp)
                self._sync_backup_for_current()
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
            # Probe source fps in background (avoids main-thread ffprobe call)
            self._probed_fps = -1
            fs = self._get_video_fspath()
            if fs:
                t = _threading.Thread(target=self._probe_fps_bg, args=(fs,))
                t.daemon = True
                t.start()
            else:
                self._probed_fps = 30
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
