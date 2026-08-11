# -*- coding: utf-8 -*-
# CueVideoWorker -- background ffprobe probe thread.
# Module-level function so the editor class doesn't carry the whole
# subprocess dance. All Ren'Py calls happen on the main thread via the
# caller's queue.poll; this function is pure Python + ffprobe subprocess I/O.
#
# After probing, the job is staged for the main-thread poll() to launch
# ffmpeg with stdout->file. No persistent readline() thread -- no GIL fight
# during Ren'Py rollback.

import os

import renpy.config as _config

from cue_lib.constants import CUE_MAX_INTERP_FPS
from cue_lib.util import _cue_log

MYPY = False
if MYPY:
    from typing import Any
    from cue_lib.ffmpeg import CueFFmpeg


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
        # Lazy import to avoid circular dependency with video_editor
        from cue_lib.video_editor import CUE_VE_MODE_INTERPOLATE, CUE_VE_MODE_FAST_PREVIEW
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
