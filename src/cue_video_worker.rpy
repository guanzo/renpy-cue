###############################################################################
# CueVideoWorker — background ffmpeg encode thread.
# Module-level function so the editor class doesn't carry the whole
# subprocess dance. All Ren'Py calls happen on the main thread via the
# caller's queue.poll; this function is pure Python + ffmpeg subprocess I/O.
###############################################################################

init -999 python:
    import subprocess as _subprocess

    def _cue_run_encode(ffmpeg, job, dur_ms, base_dir, kill_fn):
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

            # --- Run ffmpeg (1 or 2 passes) ---
            # Log file next to debug.log for troubleshooting
            log_path = os.path.join(renpy.config.gamedir, base_dir, "ffmpeg.log")
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
                    kill_fn()
                    break
                if rc != 0:
                    kill_fn()
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
            kill_fn()
            job._done = True
