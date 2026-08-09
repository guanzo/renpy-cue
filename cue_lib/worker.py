# CueVideoWorker -- background ffmpeg encode thread.
# Module-level function so the editor class doesn't carry the whole
# subprocess dance. All Ren'Py calls happen on the main thread via the
# caller's queue.poll; this function is pure Python + ffmpeg subprocess I/O.

import os
import subprocess
import renpy.config as _config

from cue_lib.ffmpeg import CREATIONFLAGS
from cue_lib.util import _cue_log

MYPY = False
if MYPY:
    from typing import Any, Callable
    from cue_lib.ffmpeg import CueFFmpeg


def _cue_run_encode(ffmpeg, job, dur_ms, base_dir, kill_fn):
    # type: (CueFFmpeg, Any, int, str, Callable[[], None]) -> None
    """Background thread: probe codecs, build command, run ffmpeg.
    Reads -progress pipe:1 line by line to update job.progress.
    All subprocess calls are off the main thread -- no game freeze."""
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
            _out_fps = min(60, source_fps * 2)
            total_frames = _out_fps * (dur_ms / 1000.0) / factor
        else:
            total_frames = source_fps * (dur_ms / 1000.0)
        job.total_frames = total_frames
        cmds, passlog = ffmpeg.build_ffmpeg_cmds(
            input_fs, temp_path, factor,
            vcodec, acodec, has_audio,
            target_bitrate,
            interpolate=interpolate,
            source_fps=source_fps,
            fast=(job.encode_mode == CUE_VE_MODE_FAST_PREVIEW),
        )
        job.passlog = passlog

        # --- Resume from pass2 if pass1 already completed ---
        if getattr(job, '_resume_pass2', False):
            if len(cmds) == 2:
                cmds = cmds[1:]
                job.status = "encoding"
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
                            pass

        _cue_log("Encoding {} -> {} at {:.1f}x ({})".format(
            os.path.basename(input_fs), os.path.basename(temp_path),
            factor, "2-pass" if len(cmds) == 2 else "1-pass"))

        # --- Run ffmpeg (1 or 2 passes) ---
        # Log file next to debug.log for troubleshooting
        log_path = os.path.join(_config.gamedir, base_dir, "ffmpeg.log")
        with open(log_path, "w") as _logf:
            _logf.write("cmd: {}\n".format(" ".join(cmds[0])))
        for pass_idx, cmd in enumerate(cmds):
            if job.cancelled:
                break
            if len(cmds) == 1 or pass_idx > 0:
                job.status = "encoding"
            job.progress = 0.0
            job.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATIONFLAGS,
            )
            if job.proc.stdout is None or job.proc.stderr is None:
                job.error_msg = "ffmpeg produced no pipes"
                kill_fn()
                job._done = True
                return

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
                kill_fn()
                break
            if rc != 0:
                kill_fn()
                # Capture last meaningful stderr line for the overlay
                _err_tail = ""
                if err_out:
                    if isinstance(err_out, bytes):
                        _err_tail = err_out.decode("utf-8", errors="replace")
                    else:
                        _err_tail = str(err_out)
                    _err_tail = _err_tail.strip().split("\n")[-1]
                    if len(_err_tail) > 120:
                        _err_tail = _err_tail[-120:]
                job.error_msg = "ffmpeg pass {} rc={}: {}".format(
                    pass_idx + 1, rc, _err_tail)
                _cue_log("ffmpeg FAILED pass {} rc={}: {}".format(
                    pass_idx + 1, rc, _err_tail))
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
        output_ok = os.path.exists(temp_path) and os.path.getsize(temp_path) > 0
        if not job.error_msg and output_ok:
            job._ok = True
            job.progress = 1.0
            _cue_log("Speed worker: ffmpeg succeeded")
        elif not job.error_msg:
            job.error_msg = "ffmpeg produced no output"
            _cue_log("Speed worker: FAILED -- no output file")
    except Exception as e:
        if not job.cancelled:
            job.error_msg = "ffmpeg error: {}".format(e)
            _cue_log("Speed worker: exception -- {}".format(e))
    finally:
        kill_fn()
        job._done = True
