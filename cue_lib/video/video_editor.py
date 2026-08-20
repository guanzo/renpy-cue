# -*- coding: utf-8 -*-
# CueVideoEditor -- edit the currently-playing video file.
# Currently supports: playback speed change via ffmpeg.
# The encode job queue lives in cue_lib.video.video_edit_queue.

import os
import threading
import renpy
import renpy.config as _config

from renpy.store import persistent

from cue_lib.video.ffmpeg import CueSubprocessTimeout
from cue_lib.video.video_edit_queue import (
    CUE_VE_MODE_NORMAL,
    CUE_VE_MODE_INTERPOLATE,
    CUE_VE_MODE_FAST_PREVIEW,
    CueVideoEditQueue,
    CueVideoJob,
    _cue_esc,
)
from cue_lib.util import _cue_log, _cue_ui_refresh

MYPY = False
if MYPY:
    from typing import Optional
    from cue_lib.video.ffmpeg import CueFFmpeg  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.speed import CueVidSpeedResolver  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video import CueVideoManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]
    from cue_lib.state import CueContext  # pyright: ignore[reportUnusedImport]


class CueVideoEditorState(object):
    """Editing state for a single video file."""
    def __init__(self, vpath):
        self.vpath = vpath
        self.factor_text = "1.00"
        self.last_error = ""


class CueRpaExtractState(object):
    """Background .rpa extraction state.  The worker thread writes the
    ok/msg/done fields; poll_extract() (main thread) finalizes them into
    check_prerequisites + create."""
    def __init__(self):
        self.in_progress = False
        self.done = False
        self.ok = False
        self.msg = ""
        self.vpath = None  # type: Optional[str]


class CueVideoEditor(object):
    """Change the playback speed of the currently-playing video."""

    SPEED_MIN = 0.1
    SPEED_MAX = 10.0
    MODE_NORMAL = CUE_VE_MODE_NORMAL
    MODE_INTERPOLATE = CUE_VE_MODE_INTERPOLATE
    MODE_FAST_PREVIEW = CUE_VE_MODE_FAST_PREVIEW

    def __init__(self, ctx, ffmpeg, speed_resolver, vid_manager, paths):
        # type: (CueContext, CueFFmpeg, CueVidSpeedResolver, CueVideoManager, CuePaths) -> None
        self._ffmpeg = ffmpeg
        self._speed_resolver = speed_resolver
        self._vid_manager = vid_manager
        self._paths = paths
        self._ctx = ctx
        self._states = {}
        self._current = None
        self.active = False
        self._ready = False
        self._warm_cache_error = ""
        self.encode_mode = CUE_VE_MODE_INTERPOLATE
        self.remove_audio = True
        self._current_has_audio = None  # type: Optional[bool]
        self.job_queue = CueVideoEditQueue(self)
        # Background .rpa extraction state.  The worker thread only writes the
        # ok/msg/done fields; poll_extract() finalizes them on the main thread.
        self.rpa_extract = CueRpaExtractState()

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
        return self._vid_manager.get_video_path()

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

    def extract_from_rpa(self, vp=None):
        # type: (Optional[str]) -> tuple[str, str]
        if vp is None:
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
                _cue_log("EXTRACT: cleanup remove failed for {}".format(fspath))
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
                return ("rpa", "Video is inside an .rpa archive.  Extract it first.")
            return ("error", "Video file not found on disk.")
        if not os.access(fs, os.W_OK):
            return ("error", "Video file is read-only.")
        d = os.path.dirname(fs)
        if not os.access(d, os.W_OK):
            return ("error", "Video directory is read-only.")
        if not self._ffmpeg.ffmpeg_available():
            return ("error", "ffmpeg not found. Install ffmpeg and restart the game, "
                    "or set RENPY_CUE_FFMPEG environment variable.")
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
            _cue_log("EDITOR-FACTOR: parse failed for '{}'".format(self.factor_text))
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
            _cue_log("EDITOR-FACTOR: parse failed for '{}'".format(self.factor_text))
            v = 1.0
        v = max(self.SPEED_MIN, min(self.SPEED_MAX, v + delta))
        self.factor_text = "{:.1f}".format(v)
        self.last_error = ""
        renpy.restart_interaction()

    def _warm_cache(self):
        # type: () -> None
        self._ffmpeg.ffmpeg_available()
        self._ffmpeg.ffprobe_available()
        self._ffmpeg.load_encoders()

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
            _cue_log("EDITOR-FACTOR: parse failed for '{}'".format(self.factor_text))
            return 1.0

    def set_encode_mode(self, mode):
        # type: (int) -> None
        mode = int(mode)
        if mode not in (self.MODE_NORMAL, self.MODE_INTERPOLATE, self.MODE_FAST_PREVIEW):
            return
        self.encode_mode = mode
        persistent._cue["encode_mode"] = mode
        renpy.restart_interaction()

    def toggle_remove_audio(self):
        # type: () -> None
        self.remove_audio = not self.remove_audio
        persistent._cue["remove_audio"] = self.remove_audio
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
            self.last_error = "Checking ffmpeg.  Try again in a moment."
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
            _cue_log("EDITOR-FACTOR: parse failed for '{}'".format(self.factor_text))
            factor = 1.0
        factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))
        if abs(factor - 1.0) < 0.05 and self.encode_mode != self.MODE_INTERPOLATE:
            self.last_error = "Speed is already 1.00x."
            return
        self.create(factor)

    @_cue_ui_refresh
    def _extract_then_create(self):
        # type: () -> None
        if self.rpa_extract.in_progress:
            return  # already extracting; poll_extract continues it
        vp = self._get_video_vpath()
        if not vp:
            self.last_error = "No video is currently playing."
            return
        self.last_error = ""
        self.rpa_extract.vpath = vp
        self.rpa_extract.done = False
        self.rpa_extract.ok = False
        self.rpa_extract.msg = ""
        self.rpa_extract.in_progress = True
        t = threading.Thread(target=_cue_extract_rpa, args=(self, vp))
        t.daemon = True
        t.start()

    def poll_extract(self):
        # type: () -> None
        """Main-thread pickup for the background .rpa extraction.

        Runs from the slow tick; once the thread sets rpa_extract.done,
        completes the deferred extract by continuing to check_prerequisites +
        create."""
        if not self.rpa_extract.in_progress or not self.rpa_extract.done:
            return
        self.rpa_extract.in_progress = False
        if not self.rpa_extract.ok:
            self.last_error = self.rpa_extract.msg
            renpy.restart_interaction()
            return
        # The video may have changed while extracting; only continue if the
        # extracted file still matches the video that was being extracted.
        if self._get_video_vpath() != self.rpa_extract.vpath:
            self.last_error = "Video changed during extraction."
            renpy.restart_interaction()
            return
        status, msg = self.check_prerequisites()
        if status == "error":
            self.last_error = msg
            renpy.restart_interaction()
            return
        try:
            factor = float(self.factor_text)
        except (ValueError, TypeError):
            _cue_log("EDITOR-FACTOR: parse failed for '{}'".format(self.factor_text))
            factor = 1.0
        factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))
        self.create(factor)

    @_cue_ui_refresh
    def create(self, factor):
        # type: (float) -> None
        fs = self._get_video_fspath()
        if not fs:
            self.last_error = "Video file disappeared."
            return
        vp = self._speed_resolver.base_path_for(self._ctx.current_file) or self._get_video_vpath()
        if not vp:
            return
        orig_vpath = vp.replace("\\", "/")
        orig_fs = os.path.normpath(os.path.join(_config.gamedir, orig_vpath))
        out_fspath = self._speed_resolver.variant_path(orig_fs, factor)
        _base, _ext = self._speed_resolver._split_ext(os.path.basename(orig_fs))
        job_id = self.job_queue._next_job_id
        self.job_queue._next_job_id += 1
        # The temp name is job-scoped so a stale temp/passlog from a prior
        # job for the same video+speed can never be misread as this job's.
        temp_path = os.path.join(
            self._paths.video_dir,
            "{}__cue_tmp_{:.1f}x_{}{}".format(_base, factor, job_id, _ext),
        )
        input_fs = orig_fs
        job = CueVideoJob(job_id, vp, input_fs, temp_path, factor,
                          self.encode_mode, fspath_out=out_fspath,
                          remove_audio=self.remove_audio)
        self.job_queue.enqueue(job)
        _cue_log("Speed variant job queued: id={}, factor={:.1f}, out={}".format(
            job_id, factor, os.path.basename(out_fspath)))

    def refresh(self):
        # type: () -> None
        vp = self._get_video_vpath()
        if vp:
            self._current = self._ensure_state(vp)
            self._current.last_error = ""
            fs = self._get_video_fspath()
            if fs and self._ffmpeg.ffprobe_available():
                # A probe hang must not escape to the main thread; degrade to
                # "has audio" (today's ffprobe-missing default) on timeout.
                try:
                    self._current_has_audio = self._ffmpeg.probe_has_audio(fs)
                except CueSubprocessTimeout:
                    _cue_log("REFRESH: audio probe timed out, assuming has audio")
                    self._current_has_audio = True
            else:
                self._current_has_audio = None
        else:
            self._current_has_audio = None
        if self._ffmpeg._ffmpeg_cache == -1:
            self._ready = False
            t = threading.Thread(target=self._warm_tools)
            t.daemon = True
            t.start()
        else:
            self._ready = True
        if self.processing:
            self.last_error = ""
        renpy.restart_interaction()


# ==================================================================
# Background .rpa extraction
# ==================================================================
# Module-level so threading.Thread can reference it by name.  Only writes
# editor.rpa_extract fields; poll_extract() finalizes on the main thread.
# The chunked copy of a potentially multi-hundred-MB archive read is why
# this must not run on the main thread.

def _cue_extract_rpa(editor, vp):
    # type: (CueVideoEditor, str) -> None
    """Copy `vp` out of the game archives onto the editor's result fields."""
    try:
        status, msg = editor.extract_from_rpa(vp)
        editor.rpa_extract.ok = (status == "ok")
        editor.rpa_extract.msg = msg
    except Exception as e:
        editor.rpa_extract.ok = False
        editor.rpa_extract.msg = "Extraction failed: {}".format(e)
    editor.rpa_extract.done = True
