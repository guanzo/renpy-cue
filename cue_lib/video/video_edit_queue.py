# -*- coding: utf-8 -*-
# CueVideoEditQueue -- ffmpeg encode job queue for the video editor.
# Split out of video_editor.py so the queue (the threaded encode state
# machine) is testable independently of the CueVideoEditor coordinator.

import os
import subprocess
import threading
import time as _time
import renpy
import renpy.audio.music as _music
import renpy.config as _config
import renpy.audio.audio as _aaudio

from renpy.store import persistent

from cue_lib.video.ffmpeg import CREATIONFLAGS, _cue_probe_job
from cue_lib.state import _cue
from cue_lib.util import _cue_log, _cue_replace_file, _cue_unwrap_persistent

MYPY = False
if MYPY:
    from typing import Any, Optional

# Encode mode constants
CUE_VE_MODE_NORMAL = 0
CUE_VE_MODE_INTERPOLATE = 1
CUE_VE_MODE_FAST_PREVIEW = 2


class CueJobStatus(object):
    """String-valued job lifecycle states. Values are title-cased so they
    can be returned directly from CueVideoJob.status_text()."""

    QUEUED = "Queued"
    ANALYZING = "Analyzing"
    ENCODING = "Encoding"
    FINALIZING = "Finalizing"
    DONE = "Done"
    ERROR = "Error"


class CueVideoJob(object):
    """One ffmpeg encode job in the queue."""

    def __init__(self, job_id, vpath, fspath_in, fspath_tmp, factor, encode_mode, fspath_out=None, remove_audio=True):
        self.job_id = job_id
        self.vpath = vpath
        self.fspath_in = fspath_in
        self.fspath_tmp = fspath_tmp
        self.factor = factor
        self.encode_mode = encode_mode
        self.fspath_out = fspath_out
        self.remove_audio = remove_audio
        self.status = CueJobStatus.QUEUED
        self.progress = 0.0
        self.error_msg = ""
        self.start_time = 0.0
        self.end_time = 0.0
        self.total_frames = 0
        self.passlog = None
        self.cancelled = False
        self.proc = None  # type: Optional[Any]
        self._done = False
        self._ok = False
        self._resume_pass2 = False
        # Retry of a finished encode: skip encoding, go straight to the swap.
        self._needs_swap = False
        # Staging fields: set by probe thread, consumed by main-thread poll()
        self._launched = False
        self._cmds = []  # type: list
        self._pass_idx = 0
        self._num_passes = 0
        self._log_path = ""
        self._progress_path = ""
        self._progress_offset = 0
        # Swap state: written by the background swap thread, consumed by
        # main-thread poll(). job.status is CueJobStatus.FINALIZING while
        # _swapping is True.
        self._swapping = False
        self._swap_done = False
        self._swap_ok = False
        self._swap_error_msg = ""

    def elapsed(self):
        # type: () -> float
        if not self.start_time:
            return 0.0
        if self.status in (CueJobStatus.DONE, CueJobStatus.ERROR) and self.end_time:
            return self.end_time - self.start_time
        return _time.time() - self.start_time

    def status_text(self):
        # type: () -> str
        if self.status == CueJobStatus.ENCODING:
            _pct = int(self.progress * 100)
            return "{} {}%".format(self.status, _pct)
        if self.status == CueJobStatus.ERROR:
            if self.error_msg == "Cancelled":
                return "Cancelled"
            return CueJobStatus.ERROR
        return self.status

    def filename(self):
        # type: () -> str
        if self.vpath:
            return os.path.basename(self.vpath)
        return "?"

    @property
    def speed_label(self):
        # type: () -> str
        return "{:.1f}x".format(self.factor)


class CueVideoEditQueue(object):
    """Job queue for ffmpeg encode jobs."""

    def __init__(self, editor):
        self._editor = editor
        self._jobs = []
        self._current = None
        self._next_job_id = 1

    @property
    def processing(self):
        # type: () -> bool
        return self._current is not None

    @property
    def current_job(self):
        # type: () -> Optional[CueVideoJob]
        return self._current

    @property
    def jobs(self):
        # type: () -> list[CueVideoJob]
        return self._jobs

    @property
    def has_pending(self):
        # type: () -> bool
        """True when poll() has work: a running job or queued jobs to start.
        The runtime driver gates poll() on this, so a restored-from-persistent
        queue (QUEUED job, no current) still gets kick-started."""
        if self._current is not None:
            return True
        for j in self._jobs:
            if j.status == CueJobStatus.QUEUED:
                return True
        return False

    def enqueue(self, job):
        # type: (CueVideoJob) -> None
        self._jobs.append(job)
        self._start_if_idle()
        self.save_to_persistent()

    def _find(self, job_id):
        # type: (int) -> Optional[CueVideoJob]
        for j in self._jobs:
            if j.job_id == job_id:
                return j
        return None

    def _start_if_idle(self):
        # type: () -> None
        if self._current is None:
            self._start_next()

    def _start_next(self):
        # type: () -> None
        job = None
        for j in self._jobs:
            if j.status == CueJobStatus.QUEUED:
                job = j
                break
        if job is None:
            return

        self._current = job
        job.start_time = _time.time()

        if job._needs_swap:
            # Retry of a finished encode whose file swap failed.  Skip the
            # probe/encode path and go straight to the file swap.
            job._needs_swap = False
            self._start_swap(job)
            renpy.restart_interaction()
            return

        job.status = CueJobStatus.ANALYZING

        dur_ms = 0
        try:
            dur_ms = int(_music.get_duration(channel=self._editor._vid_manager.channel or "") * 1000)
        except Exception:
            _cue_log("EDITOR-START: get_duration failed")

        t = threading.Thread(
            target=_cue_probe_job, args=(self._editor._ffmpeg, job, dur_ms, self._editor._paths.in_game_base_dir)
        )
        t.daemon = True
        t.start()
        _cue_log(
            "Speed worker probing: job_id={}, factor={:.1f}, file={}".format(
                job.job_id, job.factor, os.path.basename(job.fspath_in)
            )
        )
        renpy.restart_interaction()

    # ==================================================================
    # Encode state machine helpers (called from poll() on main thread)
    # ==================================================================

    def _launch_pass(self, job):
        # type: (CueVideoJob) -> None
        """Launch the next ffmpeg pass from job._cmds. Pops the command,
        spawns subprocess with stdout->log file. Only writer of job.proc."""
        if job.cancelled or not job._cmds:
            return
        cmd = job._cmds.pop(0)
        job._pass_idx += 1
        job.status = CueJobStatus.ENCODING
        job.progress = 0.0
        job._progress_offset = 0  # ffmpeg truncates progress file per pass
        job.proc = None
        logf = None
        try:
            # Truncate on first pass, append on subsequent passes
            _mode = "wb" if job._pass_idx == 1 else "ab"
            logf = open(job._log_path, _mode)
            _header = "--- pass {} ---\ncmd: {}\n".format(job._pass_idx, " ".join(cmd))
            if not isinstance(_header, bytes):
                _header = _header.encode("utf-8")
            logf.write(_header)
            logf.flush()
            job.proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, creationflags=CREATIONFLAGS)
        except Exception as e:
            if job.cancelled:
                job._done = True
            else:
                job.error_msg = "ffmpeg error: {}".format(e)
                _cue_log("Speed worker: launch failed -- {}".format(e))
                job._done = True
        finally:
            if logf is not None:
                try:
                    logf.close()  # child holds its own dup
                except Exception:
                    _cue_log("EDITOR-LAUNCH: logf.close failed")
        if job.cancelled and job.proc is not None:
            self._kill_proc(job)
            job._done = True

    def _read_progress(self, job):
        # type: (CueVideoJob) -> None
        """Read frame= value from ffmpeg -progress file (main thread)."""
        pp = job._progress_path
        if not pp or not os.path.exists(pp):
            return
        try:
            with open(pp, "rb") as f:
                f.seek(job._progress_offset)
                data = f.read(65536)
            job._progress_offset += len(data)
        except Exception:
            _cue_log("READ-PROGRESS: file read failed for {}".format(pp))
            return
        last_frame = None
        for raw in data.split(b"\n"):
            if raw.startswith(b"frame="):
                try:
                    last_frame = int(raw.split(b"=", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
        if last_frame is not None and job.total_frames > 0:
            job.progress = min(1.0, float(last_frame) / job.total_frames)

    def _append_pass_footer(self, job, rc):
        # type: (CueVideoJob, int) -> None
        """Write the pass completion footer to the log file."""
        try:
            _footer = "--- pass {} rc={} ---\n".format(job._pass_idx, rc)
            with open(job._log_path, "ab") as f:
                if not isinstance(_footer, bytes):
                    _footer = _footer.encode("utf-8")
                f.write(_footer)
        except Exception:
            _cue_log("EDITOR-FOOTER: write failed")

    def _error_tail(self, job, rc):
        # type: (CueVideoJob, int) -> str
        """Extract last meaningful error line from the log file."""
        tail = ""
        try:
            with open(job._log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096))
                data = f.read()
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            for line in reversed(data.split("\n")):
                line = line.strip()
                if line:
                    tail = line
                    break
            if len(tail) > 120:
                tail = tail[-120:]
        except Exception:
            _cue_log("ERROR-TAIL: read failed for {}".format(job._log_path))
        return "ffmpeg pass {} rc={}: {}".format(job._pass_idx, rc, tail)

    def _finalize_encode(self, job):
        # type: (CueVideoJob) -> None
        """Check output and set _ok/_done after all passes succeed."""
        # Clean up 2-pass artifacts
        if job.passlog:
            try:
                for _suffix in ("-0.log", "-1.log"):
                    _pf = job.passlog + _suffix
                    if os.path.exists(_pf):
                        os.remove(_pf)
            except Exception:
                _cue_log("FINALIZE: passlog cleanup failed")
        # Clean up progress file
        if job._progress_path and os.path.exists(job._progress_path):
            try:
                os.remove(job._progress_path)
            except Exception:
                _cue_log("FINALIZE: progress cleanup failed")
        output_ok = os.path.exists(job.fspath_tmp) and os.path.getsize(job.fspath_tmp) > 0
        if not job.error_msg and output_ok:
            job._ok = True
            job.progress = 1.0
            _cue_log("Speed worker: ffmpeg succeeded")
        elif not job.error_msg:
            job.error_msg = "ffmpeg produced no output"
            _cue_log("Speed worker: FAILED -- no output file")
        job._done = True

    def poll(self):
        # type: () -> None
        """Main-thread encode state machine. Called at ~50Hz by the tick timer.
        Handles: probe completion, ffmpeg launch, progress reading,
        pass transitions, and finalization."""
        job = self._current
        if job is None:
            self._start_if_idle()
            return

        # ---- 0. Swap running on the background thread ----
        if job._swapping:
            if job._swap_done:
                self._finish_swap(job)
                self._advance_queue()
            return

        # ---- 1. Encode fully finished (all passes done / error / cancelled) ----
        if job._done:
            job.end_time = _time.time()
            if job.cancelled:
                self._cleanup_temp(job)
                job.status = CueJobStatus.ERROR
                job.error_msg = "Cancelled"
                _cue_log("Speed: cancelled by user (job_id={})".format(job.job_id))
            elif not job._ok:
                self._cleanup_temp(job)
                job.status = CueJobStatus.ERROR
                _cue_log("Speed: job failed (job_id={})".format(job.job_id))
            else:
                if self._start_swap(job):
                    renpy.restart_interaction()
                    return
            self._advance_queue()
            return

        # ---- 2. Probe thread still staging (status CueJobStatus.ANALYZING) ----
        if not job._launched:
            if job.cancelled:
                renpy.restart_interaction()
            return

        # ---- 3. Cancellation requested while encoding ----
        if job.cancelled:
            self._kill_proc(job)  # no-op if proc is None (between passes)
            job._done = True
            renpy.restart_interaction()
            return

        # ---- 4. Current pass running: refresh progress ----
        proc = job.proc
        if proc is not None and proc.poll() is None:
            self._read_progress(job)
            return

        # ---- 5. Current pass exited ----
        if proc is not None:
            rc = proc.returncode
            job.proc = None  # reaped; _kill_proc must not see it
            self._append_pass_footer(job, rc)
            if rc != 0:
                job.error_msg = self._error_tail(job, rc)
                _cue_log("ffmpeg FAILED pass {} rc={}: {}".format(job._pass_idx, rc, job.error_msg))
                job._done = True
                renpy.restart_interaction()
                return
            if job._cmds:  # 2-pass: launch the next pass
                self._launch_pass(job)
                renpy.restart_interaction()
                return
            self._finalize_encode(job)  # last pass ok: output check + cleanup
            renpy.restart_interaction()
            return

        # ---- 6. Not yet launched (first pass) ----
        if job._cmds:
            self._launch_pass(job)
            renpy.restart_interaction()
            return

    def _advance_queue(self):
        # type: () -> None
        """Clear the finished current job and start the next queued job."""
        self._current = None
        self._start_next()
        self.save_to_persistent()
        renpy.restart_interaction()

    def _start_swap(self, job):
        # type: (CueVideoJob) -> bool
        """Validate the encoded temp file and kick off the file swap on a
        background thread.  Main-thread only: _music.stop() is a Ren'Py API
        call.  Returns False (and marks the job error) if the temp is bad."""
        tmp = job.fspath_tmp
        out = job.fspath_out
        if not tmp or not out:
            _cue_log("Variant: FAILED -- missing tmp or out path (job_id={})".format(job.job_id))
            job.status = CueJobStatus.ERROR
            job.error_msg = "Missing paths"
            return False
        try:
            if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                self._cleanup_temp(job)
                _cue_log("Variant: FAILED -- empty or missing temp (job_id={})".format(job.job_id))
                job.status = CueJobStatus.ERROR
                job.error_msg = "Empty output"
                return False
        except Exception:
            self._cleanup_temp(job)
            job.status = CueJobStatus.ERROR
            job.error_msg = "Cannot read temp"
            return False
        # Stop any channel playing the target file so the swap below can
        # replace it on disk.
        try:
            for _ch_name in _aaudio.channels:
                _playing = _music.get_playing(channel=_ch_name)
                if _playing:
                    _playing_fs = os.path.join(_config.gamedir, _playing)
                    if os.path.normpath(_playing_fs) == os.path.normpath(out):
                        _music.stop(channel=_ch_name, fadeout=0)
        except Exception:
            _cue_log("EDITOR-FINISH: channel stop failed")
        job.status = CueJobStatus.FINALIZING
        job._swapping = True
        job._swap_done = False
        job._swap_ok = False
        job._swap_error_msg = ""
        t = threading.Thread(target=_cue_swap_job, args=(job,))
        t.daemon = True
        t.start()
        return True

    def _finish_swap(self, job):
        # type: (CueVideoJob) -> None
        """Complete the job on the main thread after the background swap
        thread reports done.  Runs all Ren'Py/DB side effects here."""
        vp = job.vpath
        out = job.fspath_out
        state = self._editor._ensure_state(vp)
        if not out:
            job.status = CueJobStatus.ERROR
            job.error_msg = "Missing paths"
            return
        if job.cancelled:
            state.last_error = ""
            job.status = CueJobStatus.ERROR
            job.error_msg = "Cancelled"
            _cue_log("Speed: swap cancelled (job_id={})".format(job.job_id))
        elif job._swap_ok:
            job.status = CueJobStatus.DONE
            state.last_error = ""
            # The new variant file now exists; drop the cached available-speed
            # list so intensity bands pick it up on the next resolve.
            self._editor._speed_resolver.invalidate_speed_cache()
            _cue_log(
                "Variant: generated {:.1f}x at {} (job_id={})".format(job.factor, os.path.basename(out), job.job_id)
            )
        else:
            state.last_error = "The game still has this video file open. Advance past this video scene, then try again."
            job.status = CueJobStatus.ERROR
            job.error_msg = job._swap_error_msg or "File locked.  Retry later"
            _cue_log("Variant: swap FAILED -- {} (job_id={})".format(job._swap_error_msg or "file locked", job.job_id))

    def retry(self, job_id):
        # type: (int) -> None
        job = self._find(job_id)
        if job is None or job.status != CueJobStatus.ERROR:
            return
        if os.path.exists(job.fspath_tmp):
            _cue_log("Speed: retry finish (job_id={})".format(job_id))
            job.status = CueJobStatus.QUEUED
            job._needs_swap = True
            job._done = True
            job._ok = True
            self._start_if_idle()
        else:
            _cue_log("Speed: retry encode (job_id={})".format(job_id))
            job.status = CueJobStatus.QUEUED
            job._needs_swap = False
            job._done = False
            job._ok = False
            job._launched = False
            job._cmds = []
            job._pass_idx = 0
            job._num_passes = 0
            job._progress_offset = 0
            job.progress = 0.0
            job.error_msg = ""
            self._start_if_idle()
        self.save_to_persistent()
        renpy.restart_interaction()

    def cancel(self, job_id):
        # type: (int) -> None
        job = self._find(job_id)
        if job is None:
            return
        if job.status == CueJobStatus.QUEUED:
            self._jobs.remove(job)
            _cue_log("Speed: de-queued job_id={}".format(job_id))
        elif job is self._current:
            job.cancelled = True
            self._kill_proc(job)
            _cue_log("Speed: cancel requested for job_id={}".format(job_id))
        elif job.status in (CueJobStatus.DONE, CueJobStatus.ERROR):
            self.remove(job_id)
        self.save_to_persistent()
        renpy.restart_interaction()

    def remove(self, job_id):
        # type: (int) -> None
        job = self._find(job_id)
        if job is not None and job.status in (CueJobStatus.DONE, CueJobStatus.ERROR):
            self._jobs.remove(job)
            _cue_log("Speed: removed job_id={} from list".format(job_id))
        self.save_to_persistent()
        renpy.restart_interaction()

    def _kill_proc(self, job):
        # type: (CueVideoJob) -> None
        try:
            if job.proc is not None:
                p = job.proc
                p.kill()
                # stdout/stderr are file handles (not pipes), so p.stdout
                # and p.stderr are None. Just wait for the process to exit.
                try:
                    p.wait()
                except Exception:
                    _cue_log("KILL-PROC: wait failed for pid {}".format(p.pid))
        except Exception:
            _cue_log("KILL-PROC: kill failed")
        job.proc = None

    def _cleanup_temp(self, job):
        # type: (CueVideoJob) -> None
        try:
            tmp = job.fspath_tmp
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            _cue_log("CLEANUP: remove failed for {}".format(job.fspath_tmp))
        # Clean up 2-pass artifacts (same as old worker's unconditional
        # post-loop cleanup on cancel/error)
        try:
            if job.passlog:
                for _suffix in ("-0.log", "-1.log"):
                    _pf = job.passlog + _suffix
                    if os.path.exists(_pf):
                        os.remove(_pf)
        except Exception:
            _cue_log("CLEANUP: passlog remove failed")
        # Clean up progress file
        try:
            if job._progress_path and os.path.exists(job._progress_path):
                os.remove(job._progress_path)
        except Exception:
            _cue_log("CLEANUP: progress remove failed")

    def save_to_persistent(self):
        # type: () -> None
        """Persist actionable jobs (queued + current) to persistent._cue_jobs."""
        if not _cue.initialized:
            return
        try:
            serialized = []
            # Collect queued jobs
            for j in self._jobs:
                if j.status in (CueJobStatus.QUEUED,):
                    serialized.append(
                        {
                            "job_id": j.job_id,
                            "vpath": j.vpath,
                            "fspath_in": j.fspath_in,
                            "fspath_tmp": j.fspath_tmp,
                            "factor": j.factor,
                            "encode_mode": j.encode_mode,
                            "fspath_out": j.fspath_out,
                            "passlog": j.passlog,
                            "remove_audio": j.remove_audio,
                        }
                    )
            # Include current (in-progress) job
            cur = self._current
            if cur is not None and cur.status in (CueJobStatus.ANALYZING, CueJobStatus.ENCODING):
                serialized.append(
                    {
                        "job_id": cur.job_id,
                        "vpath": cur.vpath,
                        "fspath_in": cur.fspath_in,
                        "fspath_tmp": cur.fspath_tmp,
                        "factor": cur.factor,
                        "encode_mode": cur.encode_mode,
                        "fspath_out": cur.fspath_out,
                        "passlog": cur.passlog,
                        "remove_audio": cur.remove_audio,
                    }
                )
            if serialized:
                persistent._cue_jobs = serialized
            else:
                persistent._cue_jobs = None
        except Exception:
            _cue_log("SAVE-JOBS: failed to persist queue")
            persistent._cue_jobs = None

    def load_from_persistent(self):
        # type: () -> None
        """Restore persisted jobs from persistent._cue_jobs.
        Called once at init 999 after bootstrap."""
        raw = getattr(persistent, '_cue_jobs', None)
        if raw is None:
            return
        try:
            data = _cue_unwrap_persistent(raw)
            if not hasattr(data, "__iter__") or isinstance(data, (str, bytes)):
                _cue_log("LOAD-JOBS: unexpected type, clearing")
                persistent._cue_jobs = None
                return
            max_id = 0
            count = 0
            for d in data:
                try:
                    job_id = int(d.get("job_id", 0))
                    fspath_out = d.get("fspath_out", "")
                    fspath_in = d.get("fspath_in", "")
                    fspath_tmp = d.get("fspath_tmp", "")
                    vpath = d.get("vpath", "")
                    factor = float(d.get("factor", 1.0))
                    encode_mode = int(d.get("encode_mode", 0))
                    remove_audio = bool(d.get("remove_audio", True))
                except (ValueError, TypeError):
                    _cue_log("LOAD-JOBS: skipping malformed entry")
                    continue

                # Already completed?
                if fspath_out and os.path.exists(fspath_out) and os.path.getsize(fspath_out) > 0:
                    _cue_log("LOAD-JOBS: skipping job_id={} -- output already exists".format(job_id))
                    continue

                # Input file gone?
                if not os.path.exists(fspath_in):
                    _cue_log(
                        "LOAD-JOBS: skipping job_id={} -- input file missing: {}".format(
                            job_id, os.path.basename(fspath_in)
                        )
                    )
                    if fspath_tmp and os.path.exists(fspath_tmp):
                        try:
                            os.remove(fspath_tmp)
                        except Exception:
                            _cue_log("LOAD-JOBS: stale tmp remove failed for {}".format(fspath_tmp))
                    _logbase = fspath_tmp + ".passlog" if fspath_tmp else None
                    if _logbase:
                        for _suffix in ("-0.log", "-1.log"):
                            _pf = _logbase + _suffix
                            if os.path.exists(_pf):
                                try:
                                    os.remove(_pf)
                                except Exception:
                                    _cue_log("LOAD-JOBS: stale passlog remove failed for {}".format(_pf))
                    continue

                # Detect if pass1 already completed by checking for the
                # passlog file on disk. Path is deterministic:
                # fspath_tmp + ".passlog" + "-0.log".
                # We derive instead of reading persisted passlog because
                # save_to_persistent() runs before the worker thread
                # finishes probing -- the persisted value races.
                _passlog = fspath_tmp + ".passlog" if fspath_tmp else None
                _passlog0 = _passlog + "-0.log" if _passlog else None
                resume_pass2 = False
                if _passlog0 and os.path.exists(_passlog0) and os.path.getsize(_passlog0) > 0:
                    resume_pass2 = True

                job = CueVideoJob(
                    job_id=job_id,
                    vpath=vpath,
                    fspath_in=fspath_in,
                    fspath_tmp=fspath_tmp,
                    factor=factor,
                    encode_mode=encode_mode,
                    fspath_out=fspath_out,
                    remove_audio=remove_audio,
                )
                job._resume_pass2 = resume_pass2
                if resume_pass2:
                    _cue_log("LOAD-JOBS: job_id={} resuming from pass2".format(job_id))
                else:
                    _cue_log("LOAD-JOBS: job_id={} restarting full encode".format(job_id))
                # Append directly -- don't call enqueue() during init,
                # since _start_if_idle() would call renpy.restart_interaction()
                # before the game loop is ready. poll() will kick-start.
                self._jobs.append(job)
                count += 1
                if job_id > max_id:
                    max_id = job_id
            if max_id >= self._next_job_id:
                self._next_job_id = max_id + 1
            if count:
                _cue_log("LOAD-JOBS: restored {} job(s)".format(count))
        except Exception as e:
            _cue_log("LOAD-JOBS: error restoring queue: {}".format(e))

    def get_elapsed(self):
        # type: () -> float
        if self._current is not None:
            return self._current.elapsed()
        return 0.0


# ==================================================================
# Background file swap
# ==================================================================
# Module-level so threading.Thread can reference it by name.  Only writes
# job._swap_* fields; poll() finalizes status and runs side effects on the
# main thread.  Pure Python + OS calls -- never blocks the main thread.


def _cue_swap_job(job):
    # type: (CueVideoJob) -> None
    """Wait for the stopped channel to release the output handle, then
    replace the output file with the encoded temp file.

    The 0.5s initial delay and the retry sleeps are the reason this must
    run off the main thread -- they'd otherwise freeze the render loop
    (the old stutter).  A failed swap leaves tmp on disk so retry() can
    re-attempt it."""
    tmp = job.fspath_tmp
    out = job.fspath_out
    if not tmp or not out:
        job._swap_ok = False
        job._swap_error_msg = "Missing paths"
        job._swap_done = True
        return
    _time.sleep(0.5)
    for _attempt in range(4):
        try:
            _cue_replace_file(tmp, out)
            job._swap_ok = True
            job._swap_error_msg = ""
            break
        except Exception:
            if _attempt < 3:
                _time.sleep(1.0)
    else:
        job._swap_ok = False
        job._swap_error_msg = "File locked.  Retry later"
    job._swap_done = True
