# -*- coding: utf-8 -*-
# CueFFmpeg -- low-level ffmpeg/ffprobe backend.
# Binary detection, encoder discovery, media probing, filter/command building,
# plus the background probe job (_cue_probe_job) that stages encodes for the
# video editor.
#
# Instantiated once at _cue.ffmpeg, lives on the NoRollback _cue object.
# No Ren'Py API calls -- safe to use from any thread.

import os
import subprocess
import threading
import time as _time

import renpy.config as _config

from cue_lib.util import _cue_log

MYPY = False
if MYPY:
    from typing import Any, List, Optional, Tuple

# Suppress console window flash on Windows for all ffmpeg/ffprobe calls
if os.name == "nt":
    CREATIONFLAGS = 0x08000000  # CREATE_NO_WINDOW
else:
    CREATIONFLAGS = 0

# Subprocess hang guards: a hung binary can't block a thread forever --
# _cue_run_proc joins a communicate() thread with CUE_SUBPROC_TIMEOUT and
# _cue_wait_proc polls with CUE_KILL_WAIT_TIMEOUT.  The thread/poll
# implementations work on both Python 2.7 (Ren'Py 7.x) and Python 3 (8.x).
CUE_SUBPROC_TIMEOUT = 10.0   # probe / encoder discovery communicate()
CUE_KILL_WAIT_TIMEOUT = 5.0  # post-kill reap in _kill_proc

# Maximum FPS cap for frame interpolation (minterpolate filter).
# Doubled source framerate is clamped to this ceiling.
CUE_MAX_INTERP_FPS = 60


class CueSubprocessTimeout(Exception):
    """Raised when an ffmpeg/ffprobe subprocess exceeds CUE_SUBPROC_TIMEOUT.

    Distinguishes a hung binary from ordinary probe failure: the encode-path
    probe methods re-raise it so _cue_probe_job errors the job, while
    binary/encoder discovery treats it as "unavailable" and degrades."""


# communicate(timeout=) only exists on Python 3.3+; Ren'Py 7.x runs Python 2.7,
# which lacks it.  So the hang guard is a join-with-deadline on a daemon thread
# (cross-engine, cross-platform -- select()-on-pipes fails on Windows Py2.7)
# and a poll-loop for waits.  The thread lives only for one communicate() call,
# not a persistent reader, so there's no GIL fight during rollback.
def _cue_run_proc(p, timeout=None):
    # type: (Any, Optional[float]) -> Tuple[bytes, bytes]
    """Run p.communicate() with a hang guard; works on Py2.7 and Py3.

    On timeout the process is killed and reaped, then CueSubprocessTimeout
    raised so callers can tell "hung" from ordinary failure.  Returns
    (out, err) on success.  Any exception from communicate() is re-raised
    in the caller's thread."""
    if timeout is None:
        timeout = CUE_SUBPROC_TIMEOUT
    result = {}

    def _run():
        try:
            result["data"] = p.communicate()
        except Exception as exc:
            result["error"] = exc

    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()
    t.join(timeout)
    if "error" in result:
        raise result["error"]
    if not t.is_alive():
        return result["data"]
    # Timed out -- kill and reap so no process is left behind.
    try:
        p.kill()
    except Exception:
        pass
    t.join(CUE_KILL_WAIT_TIMEOUT)
    _cue_log("SUBPROC: timed out after {:.0f}s".format(timeout))
    raise CueSubprocessTimeout(timeout)


def _cue_wait_proc(p, timeout=None):
    # type: (Any, Optional[float]) -> Optional[int]
    """Wait for p to exit with a hang guard; poll-loop, works on both engines.

    Returns the returncode, or None if the reap timed out (the process was
    already killed, so a stuck wait is logged, not fatal)."""
    if timeout is None:
        timeout = CUE_KILL_WAIT_TIMEOUT
    deadline = _time.time() + timeout
    while True:
        rc = p.poll()
        if rc is not None:
            return rc
        if _time.time() >= deadline:
            _cue_log("SUBPROC: wait timed out after {:.0f}s".format(timeout))
            return None
        _time.sleep(0.05)


class CueFFmpeg(object):
    """Stateless ffmpeg/ffprobe backend -- detection, probing, command building.

    All subprocess calls are blocking (called from background threads by
    the video editor). No Ren'Py API calls -- safe to use from any thread."""

    # Codec maps: input codec name -> list of encoders to try in order.
    # The first encoder that ffmpeg supports will be used.
    VIDEO_ENCODERS = {
        "h264": ["libx264"],
        "vp9": ["libvpx-vp9", "libvpx"],
        "vp8": ["libvpx", "libvpx-vp9"],
        "mpeg4": ["mpeg4", "libx264"],
        "theora": ["libtheora"],
        "mpeg2video": ["mpeg2video", "mpeg4", "libx264"],
        "hevc": ["libx265"],
        "h263": ["h263", "mpeg4"],
        "wmv2": ["wmv2", "mpeg4"],
        "wmv3": ["wmv3", "mpeg4"],
        "vc1": ["vc1", "mpeg4"],
    }

    AUDIO_ENCODERS = {
        "aac": ["aac"],
        "opus": ["libopus"],
        "vorbis": ["libvorbis"],
        "mp3": ["libmp3lame", "mp3"],
        "mp2": ["mp2", "libmp3lame"],
        "pcm_s16le": ["pcm_s16le"],
        "pcm_s24le": ["pcm_s24le"],
        "flac": ["flac"],
    }

    # Quality flags per encoder -- "visually transparent" without
    # ballooning file size or encode time.
    _VIDEO_QUALITY = {
        "libx264":     ["-crf", "15", "-preset", "slower"],
        "libx265":     ["-crf", "18", "-preset", "slower"],
        "libvpx-vp9":  ["-crf", "12", "-b:v", "0"],
        "libvpx":      ["-crf", "4", "-b:v", "0"],
        "mpeg4":       ["-q:v", "2"],
        "mpeg2video":  ["-q:v", "2"],
        "libtheora":   ["-q:v", "8"],
        "h263":        ["-q:v", "2"],
        "wmv2":        ["-q:v", "2"],
    }
    # Lower quality for fast preview -- decent enough to judge
    # speed changes, much faster to encode.
    _VIDEO_QUALITY_FAST = {
        "libx264":     ["-crf", "23", "-preset", "veryfast"],
        "libx265":     ["-crf", "26", "-preset", "veryfast"],
        "libvpx-vp9":  ["-crf", "24", "-b:v", "0"],
        "libvpx":      ["-crf", "10", "-b:v", "0"],
        "mpeg4":       ["-q:v", "5"],
        "mpeg2video":  ["-q:v", "5"],
        "libtheora":   ["-q:v", "6"],
        "h263":        ["-q:v", "5"],
        "wmv2":        ["-q:v", "5"],
    }
    _AUDIO_QUALITY = {
        "aac":         ["-b:a", "320k"],
        "libopus":     ["-b:a", "256k"],
        "libvorbis":   ["-q:a", "8"],
        "libmp3lame":  ["-q:a", "0"],
        "mp3":         ["-q:a", "0"],
        "mp2":         ["-b:a", "320k"],
    }

    def __init__(self):
        self._ffmpeg_cache = -1         # -1=unchecked, 0=not found, 1=found
        self._ffprobe_cache = -1        # -1=unchecked, 0=not found, 1=found
        self._ffmpeg_path = "ffmpeg"
        self._ffprobe_path = "ffprobe"
        self._encoder_cache = None      # None=not loaded, set when populated
        self._has_rubberband = False    # proven True after probe in load_encoders

    # ==================================================================
    # Binary detection
    # ==================================================================

    def _probe_exe(self, exe_name):
        # type: (str) -> bool
        """Return True if exe_name is runnable. Called from background thread."""
        try:
            p = subprocess.Popen(
                [exe_name, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            _cue_run_proc(p)
            return p.returncode == 0
        except Exception:
            _cue_log("FFMPEG-PROBE: exe check failed for {}".format(exe_name))
            return False

    def ffmpeg_available(self):
        # type: () -> bool
        """Check ffmpeg once and cache the result."""
        if self._ffmpeg_cache != -1:
            return self._ffmpeg_cache == 1
        exe = os.environ.get("RENPY_CUE_FFMPEG", "ffmpeg")
        ok = self._probe_exe(exe)
        if ok:
            self._ffmpeg_path = exe
            self._ffmpeg_cache = 1
        else:
            self._ffmpeg_cache = 0
        return ok

    def ffprobe_available(self):
        # type: () -> bool
        """Check ffprobe once and cache the result."""
        if self._ffprobe_cache != -1:
            return self._ffprobe_cache == 1
        exe = os.environ.get("RENPY_CUE_FFPROBE", "ffprobe")
        if self._probe_exe(exe):
            self._ffprobe_path = exe
            self._ffprobe_cache = 1
            return True
        if self._ffmpeg_path != "ffmpeg":
            alt = self._ffmpeg_path.replace("ffmpeg", "ffprobe")
            if self._probe_exe(alt):
                self._ffprobe_path = alt
                self._ffprobe_cache = 1
                return True
        self._ffprobe_cache = 0
        return False

    # ==================================================================
    # Encoder discovery
    # ==================================================================

    def load_encoders(self):
        # type: () -> None
        """Cache the set of available encoders from ffmpeg -encoders output."""
        if self._encoder_cache is not None:
            return
        if not self.ffmpeg_available():
            self._encoder_cache = set()
            return
        self._encoder_cache = set()
        try:
            p = subprocess.Popen(
                [self._ffmpeg_path, "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            for line in out.split("\n"):
                line = line.strip()
                if line and line[0] in ("V", "A") and not line.startswith(" ---"):
                    parts = line.split()
                    if len(parts) >= 2:
                        self._encoder_cache.add(parts[1])
        except Exception:
            _cue_log("FFMPEG-ENCODERS: load failed")

        # Probe for librubberband filter (pitch-corrected time-stretch)
        try:
            p = subprocess.Popen(
                [self._ffmpeg_path, "-filters"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            for line in out.split("\n"):
                if "rubberband" in line:
                    self._has_rubberband = True
                    break
        except Exception:
            _cue_log("FFMPEG-RUBBERBAND: probe failed")

    def pick_encoder(self, codec_name, category):
        # type: (str, str) -> Optional[str]
        """Pick an available encoder for the given input codec.
        category: 'video' or 'audio'. Returns the encoder name or None."""
        self.load_encoders()
        maps = self.VIDEO_ENCODERS if category == "video" else self.AUDIO_ENCODERS
        candidates = maps.get(codec_name, [])
        for enc in candidates:
            if self._encoder_cache is not None and enc in self._encoder_cache:
                return enc
        return None

    # ==================================================================
    # Codec probing (via ffprobe)
    # ==================================================================

    def probe_codecs(self, fspath):
        # type: (str) -> Tuple[str, str]
        """Return (video_codec, audio_codec) from ffprobe, or ('', '') on failure."""
        vc, ac = "", ""
        if not self.ffprobe_available():
            return vc, ac
        try:
            p = subprocess.Popen(
                [self._ffprobe_path, "-v", "error",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 fspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            vc = out.strip()
        except CueSubprocessTimeout:
            raise
        except Exception:
            _cue_log("FFMPEG-CODECS: video probe failed for {}".format(fspath))
        try:
            p = subprocess.Popen(
                [self._ffprobe_path, "-v", "error",
                 "-select_streams", "a:0",
                 "-show_entries", "stream=codec_name",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 fspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            ac = out.strip()
        except CueSubprocessTimeout:
            raise
        except Exception:
            _cue_log("FFMPEG-CODECS: audio probe failed for {}".format(fspath))
        return vc, ac

    def probe_has_audio(self, fspath):
        # type: (str) -> bool
        """Return True if the file has at least one audio stream."""
        if not self.ffprobe_available():
            return True
        try:
            p = subprocess.Popen(
                [self._ffprobe_path, "-v", "error",
                 "-select_streams", "a",
                 "-show_entries", "stream=index",
                 "-of", "csv=p=0",
                 fspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            return bool(out.strip())
        except CueSubprocessTimeout:
            raise
        except Exception:
            _cue_log("FFMPEG-AUDIO: probe failed for {}, assuming has audio".format(fspath))
            return True

    def probe_fps(self, fspath):
        # type: (str) -> int
        """Probe source video framerate. Returns int fps, default 30."""
        if not self.ffprobe_available():
            return 30
        try:
            p = subprocess.Popen(
                [self._ffprobe_path, "-v", "error",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=r_frame_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 fspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            rate = out.strip()  # "30/1" or "30000/1001"
            if "/" in rate:
                num, den = rate.split("/", 1)
                return int(round(float(num) / float(den)))
        except CueSubprocessTimeout:
            raise
        except Exception:
            _cue_log("FFMPEG-FPS: probe failed for {}, defaulting to 30".format(fspath))
        return 30

    def probe_duration(self, fspath):
        # type: (str) -> float
        """Probe a media file's duration in seconds. Returns 0.0 on failure
        so validation callers fail loudly instead of guessing."""
        if not self.ffprobe_available():
            return 0.0
        try:
            p = subprocess.Popen(
                [self._ffprobe_path, "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 fspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            return float(out.strip())
        except CueSubprocessTimeout:
            raise
        except Exception:
            _cue_log("FFMPEG-DURATION: probe failed for {}, assuming 0".format(fspath))
        return 0.0

    def probe_bitrate(self, fspath):
        # type: (str) -> Optional[str]
        """Probe the source video bitrate for quality matching.
        Returns a string like '6000k' or None if probe fails."""
        if not self.ffprobe_available():
            return None
        bps = None
        # Try stream bitrate first
        try:
            p = subprocess.Popen(
                [self._ffprobe_path, "-v", "error",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=bit_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 fspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATIONFLAGS,
            )
            out, _ = _cue_run_proc(p)
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            val = out.strip()
            if val and val != "N/A":
                bps = int(val)
        except CueSubprocessTimeout:
            raise
        except Exception:
            _cue_log("FFMPEG-BITRATE: stream probe failed for {}".format(fspath))
        # Fall back to format bitrate
        if not bps:
            try:
                p = subprocess.Popen(
                    [self._ffprobe_path, "-v", "error",
                     "-show_entries", "format=bit_rate",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     fspath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATIONFLAGS,
                )
                out, _ = _cue_run_proc(p)
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                val = out.strip()
                if val and val != "N/A":
                    bps = int(val)
            except CueSubprocessTimeout:
                raise
            except Exception:
                _cue_log("FFMPEG-BITRATE: format probe failed for {}".format(fspath))
        if bps and bps > 0:
            return "{}k".format(int(bps / 1000))
        return None

    # ==================================================================
    # atempo chain builder
    # ==================================================================

    def build_audio_filter(self, speed):
        # type: (float) -> str
        """Build the audio tempo filter string for the given speed factor.
        Uses librubberband (pitch-corrected) when available; falls back to
        atempo (pitch changes with speed)."""
        if speed <= 0:
            speed = 0.1  # the atempo chain divides by 0.5; 0.0 hangs forever
        self.load_encoders()  # ensures _has_rubberband is probed
        if self._has_rubberband:
            return "rubberband=tempo={:.4f}".format(speed)
        # atempo fallback -- chained for speeds outside [0.5, 2.0]
        f = speed
        parts = []
        while f > 2.0:
            parts.append("atempo=2.0000")
            f = f / 2.0
        while f < 0.5:
            parts.append("atempo=0.5000")
            f = f / 0.5
        parts.append("atempo={:.4f}".format(f))
        return ",".join(parts)

    # ==================================================================
    # ffmpeg command builder
    # ==================================================================

    def build_ffmpeg_cmds(self, fspath, temp_path, speed, vcodec, acodec,
                           has_audio, target_bitrate, interpolate=False,
                           source_fps=30, fast=False, progress_path=None):
        # type: (str, str, float, str, str, bool, Optional[str], bool, int, bool, Optional[str]) -> Tuple[List[List[str]], Optional[str]]
        """Build ffmpeg command(s). Returns list of arg lists.

        For VP8/VP9: 2-pass encoding with probed source bitrate.
        For other codecs: single pass.
        setpts adjusts video PTS; atempo adjusts audio tempo to match.
        progress_path: if provided, use '-progress <path>' instead of '-progress pipe:1'."""

        # Normalize Windows paths for ffmpeg (it parses the value as a URL)
        if progress_path:
            progress_path = progress_path.replace("\\", "/")

        # Null device for pass 1
        null_dev = "NUL" if os.name == "nt" else "/dev/null"

        # Progress argument
        _prog = ["-progress", progress_path] if progress_path else ["-progress", "pipe:1"]

        # Build video filter: setpts, optionally frame interpolation
        _vf = "setpts=PTS/{:.4f}".format(speed)
        if interpolate:
            _target_fps = min(CUE_MAX_INTERP_FPS, source_fps * 2)
            _vf += ",minterpolate=fps={}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1".format(_target_fps)
        filters = ["[0:v]{}[v]".format(_vf)]
        if has_audio:
            _af = self.build_audio_filter(speed)
            filters.append("[0:a]{}[a]".format(_af))

        # Shared output args (except pass-specific ones)
        shared = [
            self._ffmpeg_path, "-y",
            "-i", fspath,
            "-filter_complex", ";".join(filters),
            "-map", "[v]",
        ]
        if has_audio:
            shared.extend(["-map", "[a]"])
        else:
            shared.extend(["-an"])

        if vcodec:
            shared.extend(["-c:v", vcodec])
        if has_audio and acodec:
            shared.extend(["-c:a", acodec])

        shared.extend(["-vsync", "0",
                       "-avoid_negative_ts", "make_zero"])

        # Determine if 2-pass (VP8/VP9 with bitrate available)
        is_vp = vcodec in ("libvpx-vp9", "libvpx")
        if is_vp and target_bitrate:
            passlog = temp_path + ".passlog"

            # Pass 1: video only. Don't include the audio filter since
            # -an discards audio and unconnected [a] output is an error.
            _video_filter = filters[0] if filters else ""
            pass1 = [
                self._ffmpeg_path, "-y",
                "-v", "error",
                "-i", fspath,
                "-filter_complex", _video_filter,
                "-map", "[v]",
                "-c:v", vcodec,
                "-b:v", target_bitrate,
                "-quality", "good", "-speed", "4",
                "-pass", "1",
                "-passlogfile", passlog,
                "-an", "-f", "webm", null_dev,
            ]

            pass2 = [
                self._ffmpeg_path, "-y",
            ] + _prog + [
                "-nostats",
                "-loglevel", "error",
                "-i", fspath,
                "-filter_complex", ";".join(filters),
                "-map", "[v]",
            ]
            if has_audio:
                pass2.extend(["-map", "[a]"])
            else:
                pass2.extend(["-an"])
            pass2.extend(["-c:v", vcodec])
            if has_audio and acodec:
                pass2.extend(["-c:a", acodec])
            _pass2_speed = "2" if fast else "1"
            pass2.extend([
                "-b:v", target_bitrate,
                "-quality", "good", "-speed", _pass2_speed,
                "-pass", "2",
                "-passlogfile", passlog,
                "-vsync", "0",
                "-avoid_negative_ts", "make_zero",
                temp_path,
            ])

            _cue_log("2-pass encode: bitrate={}, passlog={}".format(
                target_bitrate, passlog))
            return [pass1, pass2], passlog

        # Single-pass
        args = [self._ffmpeg_path, "-y",
                ] + _prog + [
                "-nostats",
                "-loglevel", "error",
                "-i", fspath,
                "-filter_complex", ";".join(filters)]
        if has_audio:
            args.extend(["-map", "[v]", "-map", "[a]"])
        else:
            args.extend(["-map", "[v]", "-an"])
        if vcodec:
            args.extend(["-c:v", vcodec])
            _vq = self._VIDEO_QUALITY_FAST if fast else self._VIDEO_QUALITY
            args.extend(_vq.get(vcodec, []))
        if has_audio and acodec:
            args.extend(["-c:a", acodec])
            args.extend(self._AUDIO_QUALITY.get(acodec, []))
        args.extend(["-vsync", "0",
                     "-avoid_negative_ts", "make_zero"])
        args.append(temp_path)

        _cue_log("1-pass encode: codec={}".format(vcodec))
        return [args], None


# ==================================================================
# Background probe job
# ==================================================================
# Module-level function so the editor class doesn't carry the whole
# subprocess dance. All Ren'Py calls happen on the main thread via the
# caller's queue.poll; this function is pure Python + ffprobe subprocess I/O.
#
# After probing, the job is staged for the main-thread poll() to launch
# ffmpeg with stdout->file. No persistent readline() thread -- no GIL fight
# during Ren'Py rollback.

def _cue_probe_job(ffmpeg, job, dur_ms, base_dir):
    # type: (CueFFmpeg, Any, int, str) -> None
    """One-shot background probe: probe codecs, build ffmpeg commands,
    and stage the job for the main-thread poll() to launch.

    Runs 1-2s and is blocked in ffprobe communicate() (GIL released)
    almost the entire time. Never touches job.proc.
    Always sets job._launched before exiting."""
    input_fs = job.fspath_in
    temp_path = job.fspath_tmp
    factor = job.factor
    try:
        # --- Probe codecs and bitrate from input file ---
        vcodec = ""
        acodec = ""
        has_audio = True
        target_bitrate = None
        if ffmpeg.ffprobe_available():
            vc_in, ac_in = ffmpeg.probe_codecs(input_fs)
            has_audio = ffmpeg.probe_has_audio(input_fs)
            if vc_in:
                vcodec = ffmpeg.pick_encoder(vc_in, "video") or ""
            if ac_in and has_audio:
                acodec = ffmpeg.pick_encoder(ac_in, "audio") or ""
            # Probe source bitrate for quality matching
            target_bitrate = ffmpeg.probe_bitrate(input_fs)
            _cue_log("probed vcodec: {} -> {}, acodec: {} -> {}, audio: {}, bitrate: {}".format(
                vc_in, vcodec, ac_in, acodec, has_audio, target_bitrate))

        # Audio track removal override
        if job.remove_audio:
            has_audio = False

        if job.cancelled:
            return

        # --- Build ffmpeg command(s) ---
        # Lazy import to avoid circular dependency with video_edit_queue
        from cue_lib.video.video_edit_queue import CUE_VE_MODE_INTERPOLATE, CUE_VE_MODE_FAST_PREVIEW
        interpolate = (job.encode_mode == CUE_VE_MODE_INTERPOLATE)
        source_fps = ffmpeg.probe_fps(input_fs)
        # Total output frames for progress. -vsync 0 preserves frame count
        # unless minterpolate generates new frames at a different rate.
        if interpolate:
            _out_fps = min(CUE_MAX_INTERP_FPS, source_fps * 2)
            total_frames = _out_fps * (dur_ms / 1000.0) / factor
        else:
            total_frames = source_fps * (dur_ms / 1000.0)
        job.total_frames = total_frames

        job._progress_path = os.path.join(_config.gamedir, base_dir, "ffmpeg_progress.txt")
        cmds, passlog = ffmpeg.build_ffmpeg_cmds(
            input_fs, temp_path, factor,
            vcodec, acodec, has_audio,
            target_bitrate,
            interpolate=interpolate,
            source_fps=source_fps,
            fast=(job.encode_mode == CUE_VE_MODE_FAST_PREVIEW),
            progress_path=job._progress_path,
        )
        job.passlog = passlog

        # --- Resume from pass2 if pass1 already completed ---
        if getattr(job, '_resume_pass2', False):
            if len(cmds) == 2:
                cmds = cmds[1:]
                _cue_log("Resuming from pass2 for job_id={}".format(getattr(job, 'job_id', '?')))
            else:
                # Was 2-pass originally but codec choice changed.
                # Clean up stale passlog files from the previous run.
                _cue_log("Pass2 resume requested but cmds are single-pass; cleaning up")
                if passlog:
                    for _suffix in ("-0.log", "-1.log"):
                        try:
                            _pf = passlog + _suffix
                            if os.path.exists(_pf):
                                os.remove(_pf)
                        except Exception:
                            _cue_log("PROBE-JOB: passlog cleanup failed for {}{}".format(passlog, _suffix))

        job._cmds = cmds
        job._num_passes = len(cmds)
        job._log_path = os.path.join(_config.gamedir, base_dir, "ffmpeg.log")

        _cue_log("Encoding {} -> {} at {:.1f}x ({})".format(
            os.path.basename(input_fs), os.path.basename(temp_path),
            factor, "2-pass" if len(cmds) == 2 else "1-pass"))

    except Exception as e:
        if not job.cancelled:
            job.error_msg = "ffmpeg error: {}".format(e)
            _cue_log("Speed worker: exception -- {}".format(e))
            job._done = True
    finally:
        job._launched = True
