# CueVideoEditor -- edit the currently-playing video file.
# Currently supports: playback speed change via ffmpeg.

import os
import threading
import time as _time
import renpy
import renpy.audio.music as _music
import renpy.config as _config
import renpy.audio.audio as _aaudio

from cue_lib.state import _cue
from cue_lib.util import _cue_log, _cue_ui_refresh

MYPY = False
if MYPY:
    from typing import Optional

# Encode mode constants
CUE_VE_MODE_NORMAL = 0
CUE_VE_MODE_INTERPOLATE = 1
CUE_VE_MODE_FAST_PREVIEW = 2


def _cue_esc(text):
    # type: (str) -> str
    """Escape square brackets so Ren'Py text interpolation doesn't
    try to resolve them as variable references."""
    if text:
        return text.replace("[", "[[").replace("]", "]]")
    return text


class CueVideoEditorState(object):
    """Editing state for a single video file."""
    def __init__(self, vpath):
        self.vpath = vpath
        self.factor_text = "1.00"
        self.last_error = ""


class CueVideoJob(object):
    """One ffmpeg encode job in the queue."""
    def __init__(self, job_id, vpath, fspath_in, fspath_tmp, factor, encode_mode,
                 fspath_out=None):
        self.job_id = job_id
        self.vpath = vpath
        self.fspath_in = fspath_in
        self.fspath_tmp = fspath_tmp
        self.factor = factor
        self.encode_mode = encode_mode
        self.fspath_out = fspath_out
        self.status = "queued"
        self.progress = 0.0
        self.error_msg = ""
        self.start_time = 0.0
        self.end_time = 0.0
        self.total_frames = 0
        self.passlog = None
        self.cancelled = False
        self.proc = None
        self._done = False
        self._ok = False

    def elapsed(self):
        # type: () -> float
        if not self.start_time:
            return 0.0
        if self.status in ("done", "error") and self.end_time:
            return self.end_time - self.start_time
        return _time.time() - self.start_time

    def status_text(self):
        # type: () -> str
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

    def enqueue(self, job):
        # type: (CueVideoJob) -> None
        self._jobs.append(job)
        self._start_if_idle()

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
            if j.status == "queued":
                job = j
                break
        if job is None:
            return

        self._current = job
        job.start_time = _time.time()
        job.status = "analyzing"

        dur_ms = 0
        try:
            dur_ms = int(_music.get_duration(channel=_cue.vid_manager.channel or "") * 1000)
        except Exception:
            pass

        # Lazy import to avoid circular dependency with worker
        from cue_lib.worker import _cue_run_encode

        t = threading.Thread(
            target=_cue_run_encode,
            args=(_cue.ffmpeg, job, dur_ms, _cue.base_dir,
                  lambda _j=job: self._kill_proc(_j)),
        )
        t.daemon = True
        t.start()
        _cue_log("Speed worker started: job_id={}, factor={:.1f}, file={}".format(
            job.job_id, job.factor, os.path.basename(job.fspath_in)))
        renpy.restart_interaction()

    def poll(self):
        # type: () -> None
        job = self._current
        if job is None:
            return
        if not job._done:
            if job.cancelled:
                renpy.restart_interaction()
            return
        job.end_time = _time.time()
        if job.cancelled:
            self._cleanup_temp(job)
            job.status = "error"
            job.error_msg = "Cancelled"
            _cue_log("Speed: cancelled by user (job_id={})".format(job.job_id))
        elif not job._ok:
            self._cleanup_temp(job)
            job.status = "error"
            _cue_log("Speed: job failed (job_id={})".format(job.job_id))
        else:
            self._finish(job)
        self._current = None
        self._start_next()
        renpy.restart_interaction()

    def _finish(self, job):
        # type: (CueVideoJob) -> None
        tmp = job.fspath_tmp
        out = job.fspath_out
        speed = job.factor
        vp = job.vpath
        if not tmp or not out:
            _cue_log("Variant: FAILED -- missing tmp or out path (job_id={})".format(job.job_id))
            job.status = "error"
            job.error_msg = "Missing paths"
            return
        try:
            if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                self._cleanup_temp(job)
                _cue_log("Variant: FAILED -- empty or missing temp (job_id={})".format(job.job_id))
                job.status = "error"
                job.error_msg = "Empty output"
                return
        except Exception:
            self._cleanup_temp(job)
            job.status = "error"
            job.error_msg = "Cannot read temp"
            return
        try:
            for _ch_name in _aaudio.channels:
                _playing = _music.get_playing(channel=_ch_name)
                if _playing:
                    _playing_fs = os.path.join(_config.gamedir, _playing)
                    if os.path.normpath(_playing_fs) == os.path.normpath(out):
                        _music.stop(channel=_ch_name, fadeout=0)
        except Exception:
            pass
        _time.sleep(0.5)
        for _attempt in range(4):
            try:
                if os.path.exists(out):
                    os.remove(out)
                os.rename(tmp, out)
                job.status = "done"
                state = self._editor._ensure_state(vp)
                state.last_error = ""
                _cue_log("Variant: generated {:.1f}x at {} (job_id={})".format(
                    speed, os.path.basename(out), job.job_id))
                _cue.markers.save_persistent()
                return
            except Exception:
                if _attempt < 3:
                    _time.sleep(1.0)
        state = self._editor._ensure_state(vp)
        state.last_error = _cue_esc(
            "The game still has this video file open. "
            "Advance past this video scene, then try again.")
        job.status = "error"
        job.error_msg = "File locked -- retry later"
        _cue_log("Variant: swap FAILED -- file locked (job_id={})".format(job.job_id))

    def retry(self, job_id):
        # type: (int) -> None
        job = self._find(job_id)
        if job is None or job.status != "error":
            return
        if os.path.exists(job.fspath_tmp):
            _cue_log("Speed: retry finish (job_id={})".format(job_id))
            self._finish(job)
        else:
            _cue_log("Speed: retry encode (job_id={})".format(job_id))
            job.status = "queued"
            job._done = False
            job._ok = False
            job.progress = 0.0
            job.error_msg = ""
            self._start_if_idle()
        renpy.restart_interaction()

    def cancel(self, job_id):
        # type: (int) -> None
        job = self._find(job_id)
        if job is None:
            return
        if job.status == "queued":
            self._jobs.remove(job)
            _cue_log("Speed: de-queued job_id={}".format(job_id))
        elif job is self._current:
            job.cancelled = True
            self._kill_proc(job)
            _cue_log("Speed: cancel requested for job_id={}".format(job_id))
        elif job.status in ("done", "error"):
            self.remove(job_id)
        renpy.restart_interaction()

    def remove(self, job_id):
        # type: (int) -> None
        job = self._find(job_id)
        if job is not None and job.status in ("done", "error"):
            self._jobs.remove(job)
            _cue_log("Speed: removed job_id={} from list".format(job_id))
        renpy.restart_interaction()

    def _kill_proc(self, job):
        # type: (CueVideoJob) -> None
        try:
            if job.proc is not None:
                p = job.proc
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

    def _cleanup_temp(self, job):
        # type: (CueVideoJob) -> None
        try:
            tmp = job.fspath_tmp
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

    def get_elapsed(self):
        # type: () -> float
        if self._current is not None:
            return self._current.elapsed()
        return 0.0

    def refresh_ui(self):
        # type: () -> None
        if self._current is not None or self._jobs:
            renpy.restart_interaction()


class CueVideoEditor(object):
    """Change the playback speed of the currently-playing video."""

    SPEED_MIN = 0.1
    SPEED_MAX = 10.0
    MODE_NORMAL = CUE_VE_MODE_NORMAL
    MODE_INTERPOLATE = CUE_VE_MODE_INTERPOLATE
    MODE_FAST_PREVIEW = CUE_VE_MODE_FAST_PREVIEW

    def __init__(self):
        self._states = {}
        self._current = None
        self.active = False
        self._ready = False
        self._warm_cache_error = ""
        self.encode_mode = CUE_VE_MODE_INTERPOLATE
        self.job_queue = CueVideoEditQueue(self)

    @property
    def processing(self):
        # type: () -> bool
        return self.job_queue.processing

    def _get_state(self):
        # type: () -> Optional[CueVideoEditorState]
        return self._current

    def _get_state_or_dummy(self):
        # type: () -> CueVideoEditorState
        if self._current is not None:
            return self._current
        return CueVideoEditorState("")

    @property
    def factor_text(self):
        # type: () -> str
        return self._get_state_or_dummy().factor_text

    @factor_text.setter
    def factor_text(self, value):
        # type: (str) -> None
        s = self._get_state()
        if s is not None:
            s.factor_text = value

    @property
    def last_error(self):
        # type: () -> str
        return self._get_state_or_dummy().last_error

    @last_error.setter
    def last_error(self, value):
        # type: (str) -> None
        s = self._get_state()
        if s is not None:
            s.last_error = _cue_esc(value)

    def _get_video_vpath(self):
        # type: () -> Optional[str]
        return _cue.vid_manager.get_video_path()

    def _get_video_fspath(self):
        # type: () -> Optional[str]
        vp = self._get_video_vpath()
        if not vp:
            return None
        vp = vp.replace("\\", "/")
        fs = os.path.normpath(os.path.join(_config.gamedir, vp))
        if os.path.exists(fs):
            return fs
        return None

    def _is_in_rpa(self):
        # type: () -> bool
        vp = self._get_video_vpath()
        if not vp:
            return False
        return self._get_video_fspath() is None

    def extract_from_rpa(self):
        # type: () -> tuple[str, str]
        vp = self._get_video_vpath()
        if not vp:
            return ("error", "No video is currently playing.")
        vp = vp.replace("\\", "/")
        out_dir = os.path.dirname(os.path.join(_config.gamedir, vp))
        try:
            if not os.path.isdir(out_dir):
                os.makedirs(out_dir)
        except Exception as e:
            return ("error", "Cannot create directory: {}".format(e))
        fspath = os.path.join(_config.gamedir, vp)
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

    def check_prerequisites(self):
        # type: () -> tuple[str, str]
        if not self._get_video_vpath():
            return ("error", "No video is currently playing.")
        fs = self._get_video_fspath()
        if fs is None:
            if self._is_in_rpa():
                return ("rpa", "Video is inside an .rpa archive -- extract it first.")
            return ("error", "Video file not found on disk.")
        if not os.access(fs, os.W_OK):
            return ("error", "Video file is read-only.")
        d = os.path.dirname(fs)
        if not os.access(d, os.W_OK):
            return ("error", "Video directory is read-only.")
        if not _cue.ffmpeg.ffmpeg_available():
            return ("error", "ffmpeg not found. Install ffmpeg and restart the game, or set RENPY_CUE_FFMPEG environment variable.")
        return ("ok", "")

    def _ensure_state(self, vpath):
        # type: (str) -> CueVideoEditorState
        if vpath not in self._states:
            self._states[vpath] = CueVideoEditorState(vpath)
        return self._states[vpath]

    def _state_for_vpath(self, vpath):
        # type: (str) -> Optional[CueVideoEditorState]
        return self._states.get(vpath)

    def set_quick(self, mult):
        # type: (float) -> None
        mult = max(self.SPEED_MIN, min(self.SPEED_MAX, float(mult)))
        self.factor_text = "{:.1f}".format(mult)
        self.last_error = ""
        renpy.restart_interaction()

    def commit_text(self):
        # type: () -> None
        try:
            v = float(self.factor_text)
        except (ValueError, TypeError):
            v = 1.0
        v = max(self.SPEED_MIN, min(self.SPEED_MAX, v))
        self.factor_text = "{:.1f}".format(v)
        self.last_error = ""
        renpy.restart_interaction()

    def nudge(self, delta):
        # type: (float) -> None
        try:
            v = float(self.factor_text)
        except (ValueError, TypeError):
            v = 1.0
        v = max(self.SPEED_MIN, min(self.SPEED_MAX, v + delta))
        self.factor_text = "{:.1f}".format(v)
        self.last_error = ""
        renpy.restart_interaction()

    def _warm_cache(self):
        # type: () -> None
        _cue.ffmpeg.ffmpeg_available()
        _cue.ffmpeg.ffprobe_available()
        _cue.ffmpeg.load_encoders()

    def _warm_tools(self):
        # type: () -> None
        try:
            self._warm_cache()
        except Exception as e:
            self._warm_cache_error = str(e)
        self._ready = True

    def open_editor(self):
        # type: () -> None
        self.active = True
        self.refresh()

    def get_factor(self):
        # type: () -> float
        try:
            return float(self.factor_text)
        except (ValueError, TypeError):
            return 1.0

    def set_encode_mode(self, mode):
        # type: (int) -> None
        mode = int(mode)
        if mode not in (self.MODE_NORMAL, self.MODE_INTERPOLATE, self.MODE_FAST_PREVIEW):
            return
        self.encode_mode = mode
        _cue.markers.save_persistent()
        renpy.restart_interaction()

    def close_editor(self):
        # type: () -> None
        self.active = False
        self._current = None
        renpy.restart_interaction()

    @_cue_ui_refresh
    def prepare_create(self):
        # type: () -> None
        if not self._ready:
            self.last_error = "Checking ffmpeg -- try again in a moment."
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
        # type: () -> None
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
        # type: (float) -> None
        fs = self._get_video_fspath()
        if not fs:
            self.last_error = "Video file disappeared."
            return
        vp = _cue.speed_resolver.base_path_for(_cue.current_file) or self._get_video_vpath()
        if not vp:
            return
        orig_vpath = vp.replace("\\", "/")
        orig_fs = os.path.normpath(os.path.join(_config.gamedir, orig_vpath))
        out_fspath = _cue.speed_resolver.variant_path(orig_fs, factor)
        _base, _ext = _cue.speed_resolver._split_ext(os.path.basename(orig_fs))
        temp_path = os.path.join(
            os.path.dirname(orig_fs),
            "{}__cue_tmp_{:.1f}x{}".format(_base, factor, _ext),
        )
        input_fs = orig_fs
        job_id = self.job_queue._next_job_id
        self.job_queue._next_job_id += 1
        job = CueVideoJob(job_id, vp, input_fs, temp_path, factor,
                          self.encode_mode, fspath_out=out_fspath)
        self.job_queue.enqueue(job)
        _cue_log("Speed variant job queued: id={}, factor={:.1f}, out={}".format(
            job_id, factor, os.path.basename(out_fspath)))

    def apply_variant(self, speed, out_fspath):
        # type: (float, str) -> None
        if self.job_queue.processing:
            return
        vp = self._get_video_vpath()
        fs = self._get_video_fspath()
        if not fs:
            _cue_log("SPEED-VARIANT: apply_variant failed -- no filesystem path")
            renpy.restart_interaction()
            return
        orig_vpath = _cue.speed_resolver.base_path_for(_cue.current_file) or vp
        if not orig_vpath:
            return
        orig_vpath = orig_vpath.replace("\\", "/")
        orig_fs = os.path.normpath(os.path.join(_config.gamedir, orig_vpath))
        base, ext = os.path.splitext(os.path.basename(orig_fs))
        if not ext:
            ext = ".webm"
        temp_path = os.path.join(
            os.path.dirname(out_fspath),
            "{}__cue_tmp_{:.1f}x{}".format(base, speed, ext),
        )
        input_fs = orig_fs
        job_id = self.job_queue._next_job_id
        self.job_queue._next_job_id += 1
        _enc_mode = self.encode_mode
        if _enc_mode == self.MODE_FAST_PREVIEW:
            _enc_mode = self.MODE_NORMAL
        job = CueVideoJob(job_id, vp, input_fs, temp_path, speed,
                          _enc_mode, fspath_out=out_fspath)
        self.job_queue.enqueue(job)
        _cue_log("Variant job queued: id={}, speed={:.1f}, out={}".format(
            job_id, speed, os.path.basename(out_fspath)))

    def refresh(self):
        # type: () -> None
        vp = self._get_video_vpath()
        if vp:
            self._current = self._ensure_state(vp)
            self._current.last_error = ""
        if _cue.ffmpeg._ffmpeg_cache == -1:
            self._ready = False
            t = threading.Thread(target=self._warm_tools)
            t.daemon = True
            t.start()
        else:
            self._ready = True
        if self.processing:
            self.last_error = ""
        renpy.restart_interaction()
