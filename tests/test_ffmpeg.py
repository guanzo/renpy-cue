# -*- coding: utf-8 -*-
# Tests for cue_lib.video.ffmpeg -- CueFFmpeg backend (binary detection,
# encoder discovery, media probing, filter/command building) plus the
# module-level _cue_probe_job staging function.
#
# subprocess.Popen is monkeypatched to a FakeProc factory so no real
# ffmpeg/ffprobe is ever spawned; the fake returns canned bytes that drive
# every parse path.  Command-building tests are pure argv assertions.

import os

import pytest

from cue_lib.video import ffmpeg as _ffmpeg_mod
from cue_lib.video.ffmpeg import CueFFmpeg, _cue_probe_job
from cue_lib.video.video_edit_queue import (
    CUE_VE_MODE_INTERPOLATE,
    CUE_VE_MODE_NORMAL,
    CUE_VE_MODE_FAST_PREVIEW,
    CueVideoJob,
)

from tests.fakes import FakeProc

NUL = "NUL" if os.name == "nt" else "/dev/null"


@pytest.fixture
def ff():
    return CueFFmpeg()


@pytest.fixture
def patch_popen(monkeypatch):
    """Monkeypatch subprocess.Popen with a factory returning canned FakeProcs.

    Usage: patch_popen(FakeProc(out_bytes=...), FakeProc(out_bytes=...))
    pops one FakeProc per Popen call, in order.  Every probe/load path starts
    with a `_probe_exe` availability check (ffmpeg_available / ffprobe_available),
    so a generic success FakeProc is prepended automatically."""

    def _factory(*procs):
        _queue = [FakeProc(out_bytes=b"", returncode=0)] + list(procs)
        monkeypatch.setattr(
            _ffmpeg_mod.subprocess, "Popen", lambda *a, **k: _queue.pop(0))
        return _queue
    return _factory


# ---------------------------------------------------------------------------
# binary detection
# ---------------------------------------------------------------------------

def test_init_defaults(ff):
    assert ff._ffmpeg_cache == -1
    assert ff._ffprobe_cache == -1
    assert ff._ffmpeg_path == "ffmpeg"
    assert ff._ffprobe_path == "ffprobe"
    assert ff._encoder_cache is None
    assert ff._has_rubberband is False


def test_ffmpeg_available_caches_true(ff, monkeypatch):
    calls = []
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: calls.append(exe) or True)
    assert ff.ffmpeg_available() is True
    assert ff._ffmpeg_cache == 1
    assert ff._ffmpeg_path == "ffmpeg"
    # Second call hits the cache -- no re-probe.
    assert ff.ffmpeg_available() is True
    assert len(calls) == 1


def test_ffmpeg_available_caches_false(ff, monkeypatch):
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: False)
    assert ff.ffmpeg_available() is False
    assert ff._ffmpeg_cache == 0


def test_ffmpeg_available_env_override(ff, monkeypatch):
    monkeypatch.setenv("RENPY_CUE_FFMPEG", "/opt/bin/myffmpeg")
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: exe == "/opt/bin/myffmpeg")
    assert ff.ffmpeg_available() is True
    assert ff._ffmpeg_path == "/opt/bin/myffmpeg"


def test_ffmpeg_available_uses_cache(ff, monkeypatch):
    ff._ffmpeg_cache = 0
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: True)
    assert ff.ffmpeg_available() is False  # cached "not found" wins


def test_ffprobe_available_uses_env(ff, monkeypatch):
    monkeypatch.setenv("RENPY_CUE_FFPROBE", "/opt/bin/myffprobe")
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: exe == "/opt/bin/myffprobe")
    assert ff.ffprobe_available() is True
    assert ff._ffprobe_path == "/opt/bin/myffprobe"


def test_ffprobe_available_derives_from_ffmpeg_path(ff, monkeypatch):
    ff._ffmpeg_path = "/opt/bin/ffmpeg"
    monkeypatch.setattr(ff, "_probe_exe",
                        lambda exe: exe == "/opt/bin/ffprobe")
    assert ff.ffprobe_available() is True
    assert ff._ffprobe_path == "/opt/bin/ffprobe"


def test_ffprobe_available_fails(ff, monkeypatch):
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: False)
    assert ff.ffprobe_available() is False


def test_ffprobe_available_caches_true(ff, monkeypatch):
    calls = []
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: calls.append(exe) or True)
    assert ff.ffprobe_available() is True
    assert ff._ffprobe_cache == 1
    assert ff._ffprobe_path == "ffprobe"
    # Second call hits the cache -- no re-probe.
    assert ff.ffprobe_available() is True
    assert calls == ["ffprobe"]


def test_ffprobe_available_caches_false(ff, monkeypatch):
    calls = []
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: calls.append(exe) or False)
    assert ff.ffprobe_available() is False
    assert ff._ffprobe_cache == 0
    # Negative result is cached too -- no re-probe.
    assert ff.ffprobe_available() is False
    assert len(calls) == 1


def test_ffprobe_available_uses_cache(ff, monkeypatch):
    ff._ffprobe_cache = 0
    monkeypatch.setattr(ff, "_probe_exe", lambda exe: True)
    assert ff.ffprobe_available() is False  # cached "not found" wins


# ---------------------------------------------------------------------------
# encoder discovery
# ---------------------------------------------------------------------------

ENCODERS_OUT = (
    b" Encoders:\n"
    b" ------\n"
    b" V..... libx264              H.264 / AVC (codec h264)\n"
    b" A..... aac                  AAC (codec aac)\n"
    b" V..... libvpx-vp9           VP9 (codec vp9)\n"
    b" V..... libvpx               VP8 (codec vp8)\n"
    b" T.. nobody                  not an encoder\n"
    b" ------\n"
)
FILTERS_OUT = (
    b" Filters:\n"
    b" ------\n"
    b" T.. atempo              Adjust audio tempo\n"
    b" T.. librubberband       Pitch correction for atempo\n"
    b" ------\n"
)


def test_load_encoders_parses_output(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=ENCODERS_OUT),
                FakeProc(out_bytes=FILTERS_OUT))
    ff.load_encoders()
    assert ff._encoder_cache == {"libx264", "aac", "libvpx-vp9", "libvpx"}
    assert ff._has_rubberband is True


def test_load_encoders_cached_noop(ff, monkeypatch):
    ff._encoder_cache = {"libx264"}
    called = []
    monkeypatch.setattr(_ffmpeg_mod.subprocess, "Popen",
                        lambda *a, **k: called.append(1))
    ff.load_encoders()
    assert called == []
    assert ff._encoder_cache == {"libx264"}


def test_load_encoders_no_ffmpeg(ff, monkeypatch):
    monkeypatch.setattr(ff, "ffmpeg_available", lambda: False)
    ff.load_encoders()
    assert ff._encoder_cache == set()


def test_load_encoders_probe_failure(ff, monkeypatch):
    monkeypatch.setattr(ff, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(_ffmpeg_mod.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    ff.load_encoders()  # must not raise
    assert ff._encoder_cache == set()


def test_pick_encoder_video(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=ENCODERS_OUT),
                FakeProc(out_bytes=FILTERS_OUT))
    assert ff.pick_encoder("vp9", "video") == "libvpx-vp9"
    assert ff.pick_encoder("vp8", "video") == "libvpx"  # libvpx first for vp8
    assert ff.pick_encoder("h264", "video") == "libx264"


def test_pick_encoder_audio(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=ENCODERS_OUT),
                FakeProc(out_bytes=FILTERS_OUT))
    assert ff.pick_encoder("aac", "audio") == "aac"
    assert ff.pick_encoder("mp3", "audio") is None  # not in available set


def test_pick_encoder_unknown_codec(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=ENCODERS_OUT),
                FakeProc(out_bytes=FILTERS_OUT))
    assert ff.pick_encoder("nope", "video") is None
    assert ff.pick_encoder("vp9", "container") is None  # bad category


# ---------------------------------------------------------------------------
# media probing
# ---------------------------------------------------------------------------

def test_probe_codecs(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"h264\n"),
                FakeProc(out_bytes=b"aac\n"))
    assert ff.probe_codecs("mov.mp4") == ("h264", "aac")


def test_probe_codecs_no_ffprobe(ff, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    assert ff.probe_codecs("mov.mp4") == ("", "")


def test_probe_has_audio_true(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"0\n"))
    assert ff.probe_has_audio("mov.mp4") is True


def test_probe_has_audio_false(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b""))
    assert ff.probe_has_audio("mov.mp4") is False


def test_probe_has_audio_no_ffprobe_assumes_true(ff, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    assert ff.probe_has_audio("mov.mp4") is True


def test_probe_fps_whole(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"30/1\n"))
    assert ff.probe_fps("mov.mp4") == 30


def test_probe_fps_fractional(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"30000/1001\n"))
    assert ff.probe_fps("mov.mp4") == 30  # round(29.97)


def test_probe_fps_no_ffprobe_default(ff, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    assert ff.probe_fps("mov.mp4") == 30


def test_probe_fps_divide_by_zero_defaults(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"0/0\n"))
    assert ff.probe_fps("mov.mp4") == 30


def test_probe_bitrate_stream(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"6000000\n"))
    assert ff.probe_bitrate("mov.mp4") == "6000k"


def test_probe_bitrate_falls_back_to_format(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"N/A\n"),
                FakeProc(out_bytes=b"800000\n"))
    assert ff.probe_bitrate("mov.mp4") == "800k"


def test_probe_bitrate_none(ff, patch_popen):
    patch_popen(FakeProc(out_bytes=b"N/A\n"),
                FakeProc(out_bytes=b"N/A\n"))
    assert ff.probe_bitrate("mov.mp4") is None


def test_probe_bitrate_no_ffprobe(ff, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    assert ff.probe_bitrate("mov.mp4") is None


# ---------------------------------------------------------------------------
# audio filter builder
# ---------------------------------------------------------------------------

@pytest.fixture
def ff_ready(ff):
    # build_audio_filter calls load_encoders(); preset the cache so it returns
    # early and doesn't clobber _has_rubberband or touch subprocess.
    ff._encoder_cache = set()
    return ff


def test_audio_filter_rubberband(ff_ready):
    ff_ready._has_rubberband = True
    assert ff_ready.build_audio_filter(1.5) == "rubberband=tempo=1.5000"


def test_audio_filter_atempo_single(ff_ready):
    assert ff_ready.build_audio_filter(1.5) == "atempo=1.5000"
    assert ff_ready.build_audio_filter(0.5) == "atempo=0.5000"
    assert ff_ready.build_audio_filter(2.0) == "atempo=2.0000"


def test_audio_filter_atempo_chained_high(ff_ready):
    assert ff_ready.build_audio_filter(6.0) == \
        "atempo=2.0000,atempo=2.0000,atempo=1.5000"


def test_audio_filter_atempo_chained_low(ff_ready):
    assert ff_ready.build_audio_filter(0.25) == \
        "atempo=0.5000,atempo=0.5000"


def test_audio_filter_zero_speed_terminates(ff_ready):
    # A speed of 0.0 would divide forever in the atempo chain; the guard
    # clamps to the UI floor so the filter chain terminates.
    filt = ff_ready.build_audio_filter(0.0)
    assert isinstance(filt, str) and filt


def test_audio_filter_negative_speed_terminates(ff_ready):
    filt = ff_ready.build_audio_filter(-1.0)
    assert isinstance(filt, str) and filt


# ---------------------------------------------------------------------------
# ffmpeg command builder
# ---------------------------------------------------------------------------

def test_build_single_pass_structure(ff_ready):
    cmds, passlog = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "libx264", "aac", True, None)
    assert passlog is None
    assert len(cmds) == 1
    c = cmds[0]
    assert c[0] == "ffmpeg"
    assert "-y" in c
    assert c[c.index("-i") + 1] == "in.ogv"
    assert c[-1] == "out.ogv"
    assert "-filter_complex" in c
    fc = c[c.index("-filter_complex") + 1]
    assert "[0:v]setpts=PTS/2.0000[v]" in fc
    assert "[0:a]atempo=2.0000[a]" in fc
    # map blocks
    assert c[c.index("-map") + 1] == "[v]"
    # codec + quality (quality flags keyed by encoder name)
    assert c[c.index("-c:v") + 1] == "libx264"
    assert c[c.index("-crf") + 1] == "15"
    assert c[c.index("-preset") + 1] == "slower"
    assert c[c.index("-c:a") + 1] == "aac"
    assert c[c.index("-b:a") + 1] == "320k"
    assert "-an" not in c


def test_build_single_pass_no_audio(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "h264", "aac", False, None)
    c = cmds[0]
    assert "-an" in c
    assert "-c:a" not in c
    fc = c[c.index("-filter_complex") + 1]
    assert "[0:a]" not in fc


def test_build_single_pass_no_vcodec(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "", "", True, None)
    c = cmds[0]
    assert "-c:v" not in c
    assert "-c:a" not in c


def test_build_single_pass_fast(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "libx264", "aac", True, None, fast=True)
    c = cmds[0]
    assert c[c.index("-crf") + 1] == "23"
    assert c[c.index("-preset") + 1] == "veryfast"


def test_build_interpolate_adds_minterpolate(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "h264", "aac", True, None,
        interpolate=True, source_fps=30)
    fc = cmds[0][cmds[0].index("-filter_complex") + 1]
    assert "minterpolate=fps=60" in fc  # min(CUE_MAX_INTERP_FPS, 30*2)


def test_build_interpolate_caps_at_max(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "h264", "aac", True, None,
        interpolate=True, source_fps=60)
    fc = cmds[0][cmds[0].index("-filter_complex") + 1]
    assert "minterpolate=fps=60" in fc  # capped, not 120


def test_build_progress_path_normalized(ff_ready, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "h264", "aac", True, None,
        progress_path="C:\\game\\prog.txt")
    c = cmds[0]
    assert c[c.index("-progress") + 1] == "C:/game/prog.txt"


def test_build_progress_pipe_default(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "h264", "aac", True, None)
    assert cmds[0][cmds[0].index("-progress") + 1] == "pipe:1"


def test_build_two_pass_vp9(ff_ready):
    cmds, passlog = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "tmp.ogv", 2.0, "libvpx-vp9", "libopus", True, "4000k")
    assert passlog == "tmp.ogv.passlog"
    assert len(cmds) == 2
    p1, p2 = cmds
    # pass1: video-only, no audio filter, writes stats to null device
    assert p1[p1.index("-pass") + 1] == "1"
    assert "-an" in p1
    assert p1[p1.index("-passlogfile") + 1] == "tmp.ogv.passlog"
    assert p1[p1.index("-f") + 1] == "webm"
    assert p1[-1] == NUL
    p1fc = p1[p1.index("-filter_complex") + 1]
    assert "[0:a]" not in p1fc
    assert "-b:v" in p1 and p1[p1.index("-b:v") + 1] == "4000k"
    # pass2: full filters + output file
    assert p2[p2.index("-pass") + 1] == "2"
    assert p2[p2.index("-passlogfile") + 1] == "tmp.ogv.passlog"
    assert p2[-1] == "tmp.ogv"
    p2fc = p2[p2.index("-filter_complex") + 1]
    assert "[0:a]atempo=2.0000[a]" in p2fc
    assert p2[p2.index("-c:a") + 1] == "libopus"


def test_build_two_pass_no_audio(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "tmp.ogv", 2.0, "libvpx", "libopus", False, "4000k")
    assert len(cmds) == 2
    p2 = cmds[1]
    assert "-an" in p2
    assert "-c:a" not in p2


def test_build_two_pass_fast_speed_2(ff_ready):
    cmds, _ = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "tmp.ogv", 2.0, "libvpx-vp9", "libopus", True, "4000k",
        fast=True)
    p2 = cmds[1]
    assert p2[p2.index("-speed") + 1] == "2"


def test_build_vp_without_bitrate_single_pass(ff_ready):
    cmds, passlog = ff_ready.build_ffmpeg_cmds(
        "in.ogv", "out.ogv", 2.0, "libvpx-vp9", "libopus", True, None)
    assert len(cmds) == 1
    assert passlog is None


# ---------------------------------------------------------------------------
# _cue_probe_job
# ---------------------------------------------------------------------------

@pytest.fixture
def job(tmp_path):
    return CueVideoJob(
        1, "movies/scene.webm",
        fspath_in=str(tmp_path / "in.webm"),
        fspath_tmp=str(tmp_path / "tmp.webm"),
        factor=2.0, encode_mode=CUE_VE_MODE_NORMAL,
        fspath_out=str(tmp_path / "out.webm"), remove_audio=False)


def test_probe_job_builds_cmds(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    assert job._launched is True
    assert len(job._cmds) == 1
    assert job._num_passes == 1
    assert job.passlog is None
    assert job.total_frames == 30  # 30fps * (1000ms / 1000)
    assert job._log_path.endswith("ffmpeg.log")
    assert job._progress_path.endswith("ffmpeg_progress.txt")
    assert job.error_msg == ""


def test_probe_job_remove_audio(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    job.remove_audio = True
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    c = job._cmds[0]
    assert "-an" in c
    fc = c[c.index("-filter_complex") + 1]
    assert "[0:a]" not in fc


def test_probe_job_cancelled_skips_build(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    job.cancelled = True
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    assert job._launched is True
    assert job._cmds == []


def test_probe_job_probes_and_picks_encoders(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: True)
    monkeypatch.setattr(ff, "probe_codecs", lambda fs: ("vp9", "opus"))
    monkeypatch.setattr(ff, "probe_has_audio", lambda fs: True)
    monkeypatch.setattr(ff, "probe_bitrate", lambda fs: "4000k")
    monkeypatch.setattr(ff, "probe_fps", lambda fs: 30)
    monkeypatch.setattr(
        ff, "pick_encoder",
        lambda c, cat: {"vp9": "libvpx-vp9", "opus": "libopus"}.get(c))
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    assert len(job._cmds) == 2  # vp9 + bitrate -> 2-pass
    assert job.passlog is not None
    assert job.total_frames == 30


def test_probe_job_interpolate_frames(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    job.encode_mode = CUE_VE_MODE_INTERPOLATE
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    # 30fps -> 60 interp, /factor 2.0 = 30 frames
    assert job.total_frames == 30
    fc = job._cmds[0][job._cmds[0].index("-filter_complex") + 1]
    assert "minterpolate=fps=60" in fc


def test_probe_job_resume_pass2(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: True)
    monkeypatch.setattr(ff, "probe_codecs", lambda fs: ("vp9", "opus"))
    monkeypatch.setattr(ff, "probe_has_audio", lambda fs: True)
    monkeypatch.setattr(ff, "probe_bitrate", lambda fs: "4000k")
    monkeypatch.setattr(ff, "probe_fps", lambda fs: 30)
    monkeypatch.setattr(
        ff, "pick_encoder",
        lambda c, cat: {"vp9": "libvpx-vp9", "opus": "libopus"}.get(c))
    job._resume_pass2 = True
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    # pass1 dropped; only pass2 remains
    assert len(job._cmds) == 1
    assert job._cmds[0][job._cmds[0].index("-pass") + 1] == "2"


def test_probe_job_resume_pass2_single_pass_cleans_stale(ff, job, monkeypatch,
                                                         tmp_path):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)
    passlog = str(tmp_path / "stale.passlog")
    for suffix in ("-0.log", "-1.log"):
        p = passlog + suffix
        with open(p, "w") as f:
            f.write("x")
    # Force a single-pass build that still reports a passlog -- the case where
    # the codec choice changed between sessions.
    monkeypatch.setattr(
        ff, "build_ffmpeg_cmds",
        lambda *a, **k: ([["ffmpeg", "-y", "out"]], passlog))
    job._resume_pass2 = True
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    assert not os.path.exists(passlog + "-0.log")
    assert not os.path.exists(passlog + "-1.log")
    assert len(job._cmds) == 1


def test_probe_job_exception_sets_error(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: False)

    def _boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(ff, "build_ffmpeg_cmds", _boom)
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    assert job._done is True
    assert "boom" in job.error_msg
    assert job._launched is True


def test_probe_job_fast_preview_mode(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: True)
    monkeypatch.setattr(ff, "probe_codecs", lambda fs: ("h264", "aac"))
    monkeypatch.setattr(ff, "probe_has_audio", lambda fs: True)
    monkeypatch.setattr(ff, "probe_bitrate", lambda fs: None)
    monkeypatch.setattr(ff, "probe_fps", lambda fs: 30)
    monkeypatch.setattr(
        ff, "pick_encoder",
        lambda c, cat: {"h264": "libx264", "aac": "aac"}.get(c))
    job.encode_mode = CUE_VE_MODE_FAST_PREVIEW
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    c = job._cmds[0]
    assert c[c.index("-preset") + 1] == "veryfast"  # quality fast map


# ---------------------------------------------------------------------------
# subprocess timeout guard
# ---------------------------------------------------------------------------

def test_run_proc_returns_communicate():
    out, _ = _ffmpeg_mod._cue_run_proc(FakeProc(out_bytes=b"x"))
    assert out == b"x"


def test_run_proc_timeout_kills_and_raises():
    p = FakeProc(timeout_error=True)
    with pytest.raises(_ffmpeg_mod.CueSubprocessTimeout):
        _ffmpeg_mod._cue_run_proc(p, timeout=0.05)
    assert p.killed is True  # hung process is killed and reaped


def test_probe_exe_timeout_degrades_to_false(monkeypatch):
    # Binary detection: a hung ffmpeg -version is "unavailable", not an error.
    monkeypatch.setattr(_ffmpeg_mod, "CUE_SUBPROC_TIMEOUT", 0.05)
    monkeypatch.setattr(_ffmpeg_mod.subprocess, "Popen",
                        lambda *a, **k: FakeProc(timeout_error=True))
    assert CueFFmpeg()._probe_exe("ffmpeg") is False


def test_probe_fps_timeout_raises(ff, patch_popen, monkeypatch):
    # Media probes on the encode path surface the timeout so the job errors.
    monkeypatch.setattr(_ffmpeg_mod, "CUE_SUBPROC_TIMEOUT", 0.05)
    patch_popen(FakeProc(timeout_error=True))
    with pytest.raises(_ffmpeg_mod.CueSubprocessTimeout):
        ff.probe_fps("mov.mp4")


def test_probe_job_probe_timeout_errors_job(ff, job, monkeypatch):
    monkeypatch.setattr(ff, "ffprobe_available", lambda: True)
    monkeypatch.setattr(
        ff, "probe_codecs",
        lambda fs: (_ for _ in ()).throw(_ffmpeg_mod.CueSubprocessTimeout(10)))
    _cue_probe_job(ff, job, 1000, "renpy_cue")
    assert job._done is True
    assert "ffmpeg error" in job.error_msg
    assert job._launched is True  # never left unset, so poll() advances
