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

    # Suppress console window flash on Windows for all ffmpeg/ffprobe calls
    if os.name == "nt":
        _CREATIONFLAGS = 0x08000000  # CREATE_NO_WINDOW
    else:
        _CREATIONFLAGS = 0

    class CueVideoEditorState:
        """Editing state for a single video file."""
        __slots__ = ("vpath", "factor_text", "has_backup", "last_error", "interpolate")

        def __init__(self, vpath):
            self.vpath = vpath
            self.factor_text = "1.00"
            self.has_backup = False
            self.last_error = ""
            self.interpolate = False


    class CueVideoEditor:
        """Change the playback speed of the currently-playing video.

        State lives on the NoRollback _cue object so it survives rollback.
        ffmpeg runs on a daemon thread; a screen timer polls for completion
        so all Ren'Py calls stay on the main thread."""

        # --- constants ---
        SPEED_MIN = 0.25
        SPEED_MAX = 4.0

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

        def __init__(self):
            # --- Per-video state ---
            self._states = {}               # vpath -> CueVideoEditorState
            self._current = None            # CueVideoEditorState for current video

            # --- UI flags (flat — not per-video) ---
            self.active = False             # True when Video Editor section is shown
            self._ready = False             # True after ffmpeg probe cache is warm
            self.processing = False         # True while ffmpeg is running
            self.progress = 0.0             # 0.0–1.0 encoding progress
            self._pass_label = ""           # "Pass 1/2 — analyzing..." etc
            self._start_time = 0            # time.time() when encode started

            # --- Job state (one ffmpeg at a time; set by main thread) ---
            self.job_done = False
            self.job_ok = False
            self.job_error = ""
            self._job_proc = None           # Popen handle for Cancel
            self._job_cancelled = False
            self._job_vpath = None          # vpath captured at apply time
            self._job_fs_in = None
            self._job_fs_tmp = None
            self._job_backup = None
            self._job_factor = 1.0

            # --- Cached probe data (shared across all states) ---
            self._ffmpeg_cache = -1         # -1=unchecked, 0=not found, 1=found
            self._ffmpeg_path = "ffmpeg"
            self._ffprobe_path = "ffprobe"
            self._encoder_cache = None      # None=not loaded, set when populated

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
        # ffmpeg / ffprobe detection
        # ==================================================================

        def _probe_exe(self, exe_name):
            """Return True if exe_name is runnable. Called from background thread."""
            try:
                p = _subprocess.Popen(
                    [exe_name, "-version"],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                p.communicate()
                return p.returncode == 0
            except Exception:
                return False

        def ffmpeg_available(self):
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
            """Check ffprobe once."""
            exe = os.environ.get("RENPY_CUE_FFPROBE", "ffprobe")
            if self._probe_exe(exe):
                self._ffprobe_path = exe
                return True
            if self._ffmpeg_path != "ffmpeg":
                alt = self._ffmpeg_path.replace("ffmpeg", "ffprobe")
                if self._probe_exe(alt):
                    self._ffprobe_path = alt
                    return True
            return False

        def _load_encoders(self):
            """Cache the set of available encoders from ffmpeg -encoders output."""
            if self._encoder_cache is not None:
                return
            if not self.ffmpeg_available():
                self._encoder_cache = set()
                return
            self._encoder_cache = set()
            try:
                p = _subprocess.Popen(
                    [self._ffmpeg_path, "-encoders"],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                out, _ = p.communicate()
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                for line in out.split("\n"):
                    line = line.strip()
                    if line and line[0] in ("V", "A") and not line.startswith(" ---"):
                        parts = line.split()
                        if len(parts) >= 2:
                            self._encoder_cache.add(parts[1])
            except Exception:
                pass

        def _pick_encoder(self, codec_name, category):
            """Pick an available encoder for the given input codec.
            category: 'video' or 'audio'. Returns the encoder name or None."""
            self._load_encoders()
            maps = self.VIDEO_ENCODERS if category == "video" else self.AUDIO_ENCODERS
            candidates = maps.get(codec_name, [])
            for enc in candidates:
                if enc in self._encoder_cache:
                    return enc
            return None

        # ==================================================================
        # Codec probing (via ffprobe)
        # ==================================================================

        def _probe_codecs(self, fspath):
            """Return (video_codec, audio_codec) from ffprobe, or ('', '') on failure."""
            vc, ac = "", ""
            if not self.ffprobe_available():
                return vc, ac
            try:
                p = _subprocess.Popen(
                    [self._ffprobe_path, "-v", "error",
                     "-select_streams", "v:0",
                     "-show_entries", "stream=codec_name",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     fspath],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                out, _ = p.communicate()
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                vc = out.strip()
            except Exception:
                pass
            try:
                p = _subprocess.Popen(
                    [self._ffprobe_path, "-v", "error",
                     "-select_streams", "a:0",
                     "-show_entries", "stream=codec_name",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     fspath],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                out, _ = p.communicate()
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                ac = out.strip()
            except Exception:
                pass
            return vc, ac

        def _probe_has_audio(self, fspath):
            """Return True if the file has at least one audio stream."""
            if not self.ffprobe_available():
                return True
            try:
                p = _subprocess.Popen(
                    [self._ffprobe_path, "-v", "error",
                     "-select_streams", "a",
                     "-show_entries", "stream=index",
                     "-of", "csv=p=0",
                     fspath],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                out, _ = p.communicate()
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                return bool(out.strip())
            except Exception:
                return True

        # Quality flags per encoder — "visually transparent" without
        # ballooning file size or encode time.
        _VIDEO_QUALITY = {
            "libx264":     ["-crf", "15", "-preset", "slower"],  # near-lossless
            "libx265":     ["-crf", "18", "-preset", "slower"],  # near-lossless
            "libvpx-vp9":  ["-crf", "12", "-b:v", "0"],  # near-lossless (0-63)
            "libvpx":      ["-crf", "4", "-b:v", "0"],    # best possible (4-63)
            "mpeg4":       ["-q:v", "2"],     # near-lossless (1-31)
            "mpeg2video":  ["-q:v", "2"],
            "libtheora":   ["-q:v", "8"],     # near-lossless (0-10, higher=better)
            "h263":        ["-q:v", "2"],
            "wmv2":        ["-q:v", "2"],
        }
        _AUDIO_QUALITY = {
            "aac":         ["-b:a", "320k"],
            "libopus":     ["-b:a", "256k"],
            "libvorbis":   ["-q:a", "8"],
            "libmp3lame":  ["-q:a", "0"],     # already max
            "mp3":         ["-q:a", "0"],     # already max
            "mp2":         ["-b:a", "320k"],
        }

        def _probe_fps(self, fspath):
            """Probe source video framerate. Returns int fps, default 30."""
            if not self.ffprobe_available():
                return 30
            try:
                p = _subprocess.Popen(
                    [self._ffprobe_path, "-v", "error",
                     "-select_streams", "v:0",
                     "-show_entries", "stream=r_frame_rate",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     fspath],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                out, _ = p.communicate()
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                rate = out.strip()  # "30/1" or "30000/1001"
                if "/" in rate:
                    num, den = rate.split("/", 1)
                    return int(round(float(num) / float(den)))
            except Exception:
                pass
            return 30

        def _probe_bitrate(self, fspath):
            """Probe the source video bitrate for quality matching.
            Returns a string like '6000k' or None if probe fails."""
            if not self.ffprobe_available():
                return None
            bps = None
            # Try stream bitrate first
            try:
                p = _subprocess.Popen(
                    [self._ffprobe_path, "-v", "error",
                     "-select_streams", "v:0",
                     "-show_entries", "stream=bit_rate",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     fspath],
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.STDOUT,
                    creationflags=_CREATIONFLAGS,
                )
                out, _ = p.communicate()
                if isinstance(out, bytes):
                    out = out.decode("utf-8", errors="replace")
                val = out.strip()
                if val and val != "N/A":
                    bps = int(val)
            except Exception:
                pass
            # Fall back to format bitrate
            if not bps:
                try:
                    p = _subprocess.Popen(
                        [self._ffprobe_path, "-v", "error",
                         "-show_entries", "format=bit_rate",
                         "-of", "default=noprint_wrappers=1:nokey=1",
                         fspath],
                        stdout=_subprocess.PIPE,
                        stderr=_subprocess.STDOUT,
                        creationflags=_CREATIONFLAGS,
                    )
                    out, _ = p.communicate()
                    if isinstance(out, bytes):
                        out = out.decode("utf-8", errors="replace")
                    val = out.strip()
                    if val and val != "N/A":
                        bps = int(val)
                except Exception:
                    pass
            if bps and bps > 0:
                return "{}k".format(int(bps / 1000))
            return None

        # ==================================================================
        # atempo chain builder
        # ==================================================================

        @staticmethod
        def _build_atempo(speed):
            """Build ffmpeg atempo filter chain for the given speed factor.
            ffmpeg atempo is limited to [0.5, 2.0] per instance, so we chain
            multiple filters for speeds outside that range."""
            f = speed
            parts = []
            while f > 2.0:
                parts.append("atempo=2.0000")
                f = f / 2.0
            while f < 0.5:
                parts.append("atempo=0.5000")
                f = f / 0.5
            parts.append("atempo={:.4f}".format(f))
            return parts

        # ==================================================================
        # ffmpeg command builder
        # ==================================================================

        def _build_ffmpeg_cmds(self, fspath, temp_path, speed, vcodec, acodec,
                               has_audio, target_bitrate, interpolate=False,
                               source_fps=30):
            """Build ffmpeg command(s). Returns python_list of arg lists.

            For VP8/VP9: 2-pass encoding with probed source bitrate.
            For other codecs: single pass.
            setpts adjusts video PTS; atempo adjusts audio tempo."""

            # Null device for pass 1
            null_dev = "NUL" if os.name == "nt" else "/dev/null"

            # Shared filter
            # Build video filter: setpts, optionally frame interpolation
            _vf = "setpts=PTS/{:.4f}".format(speed)
            if interpolate and speed > 1.0:
                _target_fps = min(60, int(source_fps * speed))
                _vf += ",minterpolate=fps={}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1".format(_target_fps)
            filters = ["[0:v]{}[v]".format(_vf)]
            if has_audio:
                atempo_chain = self._build_atempo(speed)
                filters.append("[0:a]{}[a]".format(",".join(atempo_chain)))

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
                vq = self._VIDEO_QUALITY.get(vcodec, [])
                aq = self._AUDIO_QUALITY.get(acodec, [])

                pass1 = [
                    self._ffmpeg_path, "-y",
                    "-v", "error",
                    "-i", fspath,
                    "-filter_complex", ";".join(filters),
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
                    "-progress", "pipe:1",
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
                pass2.extend([
                    "-b:v", target_bitrate,
                    "-quality", "good", "-speed", "1",
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
                    "-progress", "pipe:1",
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
                args.extend(self._VIDEO_QUALITY.get(vcodec, []))
            if has_audio and acodec:
                args.extend(["-c:a", acodec])
                args.extend(self._AUDIO_QUALITY.get(acodec, []))
            args.extend(["-vsync", "0",
                         "-avoid_negative_ts", "make_zero"])
            args.append(temp_path)
            _cue_log("1-pass encode: codec={}".format(vcodec))
            return [args], None

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

            if not self.ffmpeg_available():
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
            self.ffmpeg_available()
            self.ffprobe_available()
            self._load_encoders()

        def _warm_tools(self):
            """Background thread entry: warm the probe cache, then flag ready."""
            try:
                self._warm_cache()
            except Exception:
                pass
            self._ready = True

        def open_editor(self):
            """Show the Video Editor section, loading state for current video."""
            vp = self._get_video_vpath()
            if vp:
                self._current = self._ensure_state(vp)
                self._sync_backup_for_current()
                self._current.last_error = ""
            self.active = True
            # Warm ffmpeg/encoder probe cache in background (avoids main-thread
            # freeze when the user clicks Apply later). Only needed once.
            if self._ffmpeg_cache == -1:
                self._ready = False
                t = _threading.Thread(target=self._warm_tools)
                t.daemon = True
                t.start()
            else:
                self._ready = True
            renpy.restart_interaction()

        def get_factor(self):
            """Parse factor_text to float. Returns 1.0 on failure."""
            try:
                return float(self.factor_text)
            except (ValueError, TypeError):
                return 1.0

        def toggle_interpolate(self):
            """Toggle frame interpolation on/off (only relevant for speed > 1x)."""
            if self._current is not None:
                self._current.interpolate = not self._current.interpolate
            renpy.restart_interaction()

        def close_editor(self):
            """Return to the normal Video SFX section."""
            self.active = False
            self._current = None
            renpy.restart_interaction()

        # ==================================================================
        # Apply flow
        # ==================================================================

        def open_apply(self):
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
                vp = self._get_video_vpath()
                _cue.confirm_dialog.show(
                    "The video '{}' is inside an .rpa archive.\n"
                    "Extract it to disk so we can change its speed?\n\n"
                    "(This copies the file to the real filesystem — "
                    "you can delete it later to restore the archive version.)".format(
                        os.path.basename(vp) if vp else "?"),
                    Function(self._extract_then_apply),
                )
                return

            try:
                factor = float(self.factor_text)
            except (ValueError, TypeError):
                factor = 1.0
            factor = max(self.SPEED_MIN, min(self.SPEED_MAX, factor))

            if abs(factor - 1.0) < 0.001:
                self.last_error = "Speed is already 1.00x."
                renpy.restart_interaction()
                return

            fs = self._get_video_fspath()
            _cue.confirm_dialog.show(
                "Set speed of '{}' to {:.2f}x of original speed?\n\n"
                "The video will be re-encoded with ffmpeg "
                "(this can take a while). The original is "
                "backed up and can be restored.".format(
                    os.path.basename(fs), factor),
                Function(self.apply, factor),
            )

        def _extract_then_apply(self):
            """Callback after user confirms RPA extraction. Extract first, then apply."""
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
            _cue.confirm_dialog.show(
                "Extracted! Set speed of '{}' to {:.2f}x?".format(
                    os.path.basename(fs), factor),
                Function(self.apply, factor),
            )

        def apply(self, factor):
            """Start the ffmpeg worker thread (main thread, called from confirm)."""
            if self.processing:
                return

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
                "{}__cue_speed_tmp{}".format(base, ext),
            )

            # Always transcode from the backup (pristine original) if it
            # exists. Otherwise repeated edits would compound quality loss
            # from lossy re-encodes.
            backup_path = self._backup_path(fs)
            if os.path.exists(backup_path):
                input_fs = backup_path
            else:
                input_fs = fs

            # Capture duration for progress (fast — no subprocess)
            dur_ms = 0
            try:
                dur_ms = int(renpy.music.get_duration(channel=_cue.active_channel) * 1000)
            except Exception:
                pass

            # Store job state (captured at apply time, not read from _current later)
            self._job_type = "encode"
            self.progress = 0.0
            self._start_time = _time.time()
            self._job_cancelled = False
            self._job_vpath = vp
            self._job_fs_in = fs
            self._job_fs_tmp = temp_path
            self._job_backup = None     # backup is created after ffmpeg succeeds
            self._job_factor = factor
            self.job_ok = False
            self.job_done = False
            self.job_error = ""
            self.processing = True

            # Worker does all subprocess work (ffprobe probes + ffmpeg encode)
            # in a background thread so the main thread never freezes.
            renpy.show_screen("cue_speed_processing_dialog", _layer="cue_layer")
            t = _threading.Thread(
                target=self._worker,
                args=(input_fs, temp_path, factor, dur_ms),
            )
            t.daemon = True
            t.start()
            _cue_log("Speed worker started: factor={:.2f}, file={}".format(
                factor, os.path.basename(fs)))

        def _worker(self, input_fs, temp_path, factor, dur_ms):
            """Background thread: probe codecs, build command, run ffmpeg.
            Reads -progress pipe:1 line by line to update self.progress.
            All subprocess calls are off the main thread — no game freeze."""
            try:
                # --- Probe codecs and bitrate from input file ---
                vcodec = ""
                acodec = ""
                has_audio = True
                target_bitrate = None
                if self.ffprobe_available():
                    vc_in, ac_in = self._probe_codecs(input_fs)
                    has_audio = self._probe_has_audio(input_fs)
                    if vc_in:
                        vcodec = self._pick_encoder(vc_in, "video") or ""
                    if ac_in and has_audio:
                        acodec = self._pick_encoder(ac_in, "audio") or ""
                    # Probe source bitrate for quality matching
                    target_bitrate = self._probe_bitrate(input_fs)
                    _cue_log("probed vcodec: {} -> {}, acodec: {} -> {}, audio: {}, bitrate: {}".format(
                        vc_in, vcodec, ac_in, acodec, has_audio, target_bitrate))

                # --- Build ffmpeg command(s) ---
                interpolate = (self._current is not None and self._current.interpolate)
                source_fps = self._probe_fps(input_fs)
                cmds, passlog = self._build_ffmpeg_cmds(
                    input_fs, temp_path, factor,
                    vcodec, acodec, has_audio,
                    target_bitrate,
                    interpolate=interpolate,
                    source_fps=source_fps,
                )

                # --- Run ffmpeg (1 or 2 passes) ---
                # Log file next to debug.log for troubleshooting
                log_path = os.path.join(renpy.config.gamedir, _cue.base_dir, "ffmpeg.log")
                with open(log_path, "w") as _logf:
                    _logf.write("cmd: {}\n".format(" ".join(cmds[0])))
                for pass_idx, cmd in enumerate(cmds):
                    if self._job_cancelled:
                        break
                    if len(cmds) > 1:
                        self._pass_label = "Pass {}/2 — {}".format(
                            pass_idx + 1,
                            "analyzing..." if pass_idx == 0 else "encoding...")
                    else:
                        self._pass_label = ""
                    self._job_proc = _subprocess.Popen(
                        cmd,
                        stdout=_subprocess.PIPE,
                        stderr=_subprocess.PIPE,
                        creationflags=_CREATIONFLAGS,
                    )
                    all_out = []
                    for line in iter(self._job_proc.stdout.readline, b""):
                        if self._job_cancelled:
                            break
                        all_out.append(line)
                        if isinstance(line, bytes):
                            line_str = line.decode("utf-8", errors="replace").strip()
                        else:
                            line_str = str(line).strip()

                        if line_str.startswith("out_time_ms="):
                            try:
                                ms = int(line_str.split("=", 1)[1])
                                if dur_ms > 0:
                                    self.progress = min(0.99, float(ms) / float(dur_ms))
                            except (ValueError, IndexError):
                                pass

                    err_out = self._job_proc.stderr.read()
                    self._job_proc.stdout.close()
                    self._job_proc.stderr.close()
                    rc = self._job_proc.wait()

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

                    if self._job_cancelled:
                        self._kill_job_proc()
                        break
                    if rc != 0:
                        self._kill_job_proc()
                        self.job_error = "ffmpeg pass {} exited with code {}".format(
                            pass_idx + 1, rc)
                        break

                # --- Clean up passlog ---
                if passlog:
                    try:
                        for f in [passlog + "-0.log", passlog + "-1.log"]:
                            if os.path.exists(f):
                                os.remove(f)
                    except Exception:
                        pass

                if self._job_cancelled:
                    self.job_done = True
                    return

                # All passes completed with rc=0
                if not self.job_error and os.path.exists(self._job_fs_tmp) and os.path.getsize(self._job_fs_tmp) > 0:
                    self.job_ok = True
                    self.progress = 1.0
                    _cue_log("Speed worker: ffmpeg succeeded")
                elif not self.job_error:
                    self.job_error = "ffmpeg produced no output"
                    _cue_log("Speed worker: FAILED — no output file")
            except Exception as e:
                if not self._job_cancelled:
                    self.job_error = "ffmpeg error: {}".format(e)
                    _cue_log("Speed worker: exception — {}".format(e))
            finally:
                self._kill_job_proc()
                self.job_done = True

        def poll(self):
            """Called by screen timer on the main thread. When the worker is
            done, finalize or report error."""
            if not self.processing or not self.job_done:
                return

            self.processing = False
            renpy.hide_screen("cue_speed_processing_dialog", layer="cue_layer")

            if self._job_cancelled:
                self._cleanup_temp()
                self._set_job_state_error("Cancelled — original video untouched.")
                _cue_log("Speed: cancelled by user")
                renpy.restart_interaction()
                return

            if self.job_ok:
                self._finalize_swap()
            else:
                self._cleanup_temp()
                self._set_job_state_error("Speed change failed: " + (self.job_error or "unknown error"))
                renpy.restart_interaction()

        @staticmethod
        def _esc(text):
            """Escape square brackets so Ren'Py text interpolation doesn't
            try to resolve them as variable references."""
            if text:
                return text.replace("[", "[[").replace("]", "]]")
            return text

        def _set_job_state_error(self, msg):
            """Write an error to the state for _job_vpath (not necessarily current)."""
            state = self._state_for_vpath(self._job_vpath)
            if state is not None:
                state.last_error = self._esc(msg)
            if self._current is not None and self._current.vpath == self._job_vpath:
                pass  # last_error property already delegates to _current

        def _finalize_swap(self):
            """Backup original, swap transcoded file into place (main thread)."""
            fs = self._job_fs_in
            tmp = self._job_fs_tmp
            vp = self._job_vpath

            # Release the file by stopping playback. On Windows, Ren'Py
            # holds the file handle open while the movie channel is active,
            # which would block os.remove/rename and even open-for-read.
            try:
                if _cue.active_channel:
                    renpy.music.stop(channel=_cue.active_channel, fadeout=0)
                    _time.sleep(0.5)
            except Exception:
                pass

            # Create backup NOW (after ffmpeg success, before swap).
            # Only if a backup doesn't already exist — never overwrite the
            # original backup with an already-modified version.
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
                    self._set_job_state_error(
                        "Cannot read the original video (file is locked by "
                        "the game player). Advance past this video scene, "
                        "then click Apply again. ({})".format(e))
                    renpy.restart_interaction()
                    return

            self._job_backup = backup_path

            try:
                os.remove(fs)
                os.rename(tmp, fs)
            except Exception:
                # File may still be locked — retry with delay
                swapped = False
                for _attempt in range(3):
                    _time.sleep(1.0)
                    try:
                        os.remove(fs)
                        os.rename(tmp, fs)
                        swapped = True
                        break
                    except Exception:
                        pass
                if not swapped:
                    err = (
                        "The game still has this video file open. "
                        "Advance past this video scene, then click Apply again.\n\n"
                        "(The transcoded file and backup are already saved — "
                        "the next Apply will reuse them without re-encoding.)"
                    )
                    state = self._ensure_state(vp)
                    state.last_error = self._esc(err)
                    _cue_log("Speed: swap FAILED — file still locked")
                    renpy.restart_interaction()
                    return

            # Update state for this video
            state = self._ensure_state(vp)
            state.has_backup = True
            state.last_error = ""

            _cue_log("Speed: swap complete, backup at {}".format(
                os.path.basename(backup_path)))

            # Only show popup if overlay is visible
            if _cue.is_overlay_visible:
                elapsed = _time.time() - self._start_time if self._start_time else 0
                msg = "Speed changed to {:.2f}x in {:.0f}s. Use Restore to undo.".format(
                    self._job_factor, elapsed)
                _cue.confirm_dialog.show(msg, NullAction())
            renpy.restart_interaction()

        def _cleanup_temp(self):
            """Remove the temp transcoded file if it exists."""
            try:
                tmp = self._job_fs_tmp
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

        # ==================================================================
        # Cancel
        # ==================================================================

        def _kill_job_proc(self):
            """Kill the current ffmpeg process and wait for it. Safe to call
            from any thread, or when _job_proc is None."""
            try:
                if self._job_proc is not None:
                    p = self._job_proc
                    p.kill()
                    try:
                        p.wait()
                    except Exception:
                        pass
            except Exception:
                pass
            self._job_proc = None

        def cancel_job(self):
            """Kill the running ffmpeg process (main thread, called from dialog)."""
            self._job_cancelled = True
            self._kill_job_proc()
            _cue_log("Speed: cancel requested")

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

            _cue.confirm_dialog.show(
                "Restore '{}' to its original speed?\n\n"
                "The backup will be copied back, undoing all speed changes.".format(
                    os.path.basename(fs)),
                Function(self.restore),
            )

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

                if _cue.is_overlay_visible:
                    _cue.confirm_dialog.show("Original video restored.", NullAction())

                _cue_log("Speed: restore complete from {}".format(
                    os.path.basename(backup)))
            except Exception as e:
                self.last_error = self._esc(
                    "Cannot restore — the file may be locked. "
                    "Advance past this video scene and try again.")
                _cue_log("Speed: restore FAILED — {}".format(e))
            renpy.restart_interaction()

        # ==================================================================
        # Refresh (called when overlay is shown)
        # ==================================================================

        def refresh(self):
            """Update has_backup for the current video. Called on overlay open."""
            self._sync_backup_for_current()
            if self.processing:
                self.last_error = ""

        def get_elapsed(self):
            """Seconds since encode started. Returns 0 if not processing."""
            if self._start_time:
                return _time.time() - self._start_time
            return 0.0

        def _refresh_ui(self):
            """No-op that triggers a screen redraw for progress text updates."""
            if self.processing:
                renpy.restart_interaction()
