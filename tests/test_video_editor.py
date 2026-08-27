# -*- coding: utf-8 -*-
# Tests for cue_lib.video.video_editor -- CueVideoJob, the CueVideoEditQueue
# encode state machine, _cue_swap_job, and the CueVideoEditor coordinator.
#
# The editor is constructed with fakes (FakeFFmpeg / FakeVidPathManager /
# FakePathsVideo / FakeSpeedResolver); threading.Thread is swapped for
# FakeThread so the probe/swap worker bodies never run -- tests drive the
# job flags (_launched / _done / _ok / proc.poll()) and step poll() by hand.
# subprocess.Popen is monkeypatched for the _launch_pass paths.

import os

import pytest

import renpy
import renpy.config as _config

from renpy.store import persistent

from cue_lib.state import CueContext
from cue_lib.util import _cue_escape_text
from cue_lib.video import ffmpeg as _ffmpeg_mod
from cue_lib.video import video_edit_queue as _qeditor
from cue_lib.video import video_editor as _veditor
from cue_lib.video.video_edit_queue import (
    CUE_VE_MODE_FAST_PREVIEW,
    CUE_VE_MODE_INTERPOLATE,
    CUE_VE_MODE_NORMAL,
    CueJobStatus,
    CueVideoEditQueue,
    CueVideoJob,
)
from cue_lib.video.video_editor import CueVideoEditor, CueVideoEditorState, CueVideoEditorTab

from tests.fakes import FakeFFmpeg, FakePathsVideo, FakeProc, FakeThread, FakeVidPathManager, FakeVidSpeedResolver


@pytest.fixture(autouse=True)
def _clean_persistent(monkeypatch):
    """Fresh persistent._cue / persistent._cue_jobs + initialized singleton
    for every test in this module (shared-state cleanup)."""
    from cue_lib.state import _cue

    monkeypatch.setattr(persistent, "_cue", {})
    monkeypatch.setattr(persistent, "_cue_jobs", None, raising=False)
    monkeypatch.setattr(_cue, "initialized", True, raising=False)


@pytest.fixture
def fthread(monkeypatch):
    """Swap threading.Thread for a capture-only FakeThread (no worker runs)."""
    monkeypatch.setattr(_veditor.threading, "Thread", FakeThread)
    monkeypatch.setattr(_qeditor.threading, "Thread", FakeThread)


@pytest.fixture
def ve(tmp_path, monkeypatch):
    """A real CueVideoEditor wired to fakes; gamedir points at tmp_path."""
    monkeypatch.setattr(_config, "gamedir", str(tmp_path))
    return CueVideoEditor(
        CueContext(),
        FakeFFmpeg(cache=0),
        FakeVidSpeedResolver(),
        FakeVidPathManager(vpath="movies/scene.webm"),
        FakePathsVideo(video_dir=str(tmp_path)),
    )


def make_job(ve, tmp_path, factor=2.0, status=CueJobStatus.QUEUED):
    # type: (CueVideoEditor, object, float, str) -> CueVideoJob
    job = CueVideoJob(
        ve.job_queue._next_job_id,
        vpath="movies/scene.webm",
        fspath_in=str(tmp_path / "in.webm"),
        fspath_tmp=str(tmp_path / "tmp.webm"),
        factor=factor,
        encode_mode=CUE_VE_MODE_NORMAL,
        fspath_out=str(tmp_path / "out.webm"),
        remove_audio=False,
    )
    job.status = status
    ve.job_queue._next_job_id += 1
    return job


def write_file(path, data=b"content"):
    _d = os.path.dirname(path)
    if _d:
        os.makedirs(_d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class FakeRenPyFile(object):
    """renpy.file() stand-in: returns one chunk then EOF."""

    def __init__(self, data=b"video-bytes"):
        self._data = data
        self._done = False

    def read(self, n):
        if self._done:
            return b""
        self._done = True
        return self._data

    def close(self):
        pass


# ---------------------------------------------------------------------------
# CueVideoJob
# ---------------------------------------------------------------------------


def test_job_init_defaults(ve, tmp_path):
    job = make_job(ve, tmp_path)
    assert job.status == CueJobStatus.QUEUED
    assert job.progress == 0.0
    assert job.error_msg == ""
    assert job.passlog is None
    assert job.cancelled is False
    assert job.proc is None
    assert job._done is False
    assert job._ok is False
    assert job._launched is False
    assert job._needs_swap is False


def test_job_elapsed_no_start(ve, tmp_path):
    assert make_job(ve, tmp_path).elapsed() == 0.0


def test_job_elapsed_running(ve, tmp_path, monkeypatch):
    job = make_job(ve, tmp_path)
    job.start_time = 100.0
    monkeypatch.setattr(_qeditor._time, "time", lambda: 105.0)
    assert job.elapsed() == 5.0


def test_job_elapsed_done(ve, tmp_path):
    job = make_job(ve, tmp_path)
    job.start_time = 100.0
    job.end_time = 110.0
    job.status = CueJobStatus.DONE
    assert job.elapsed() == 10.0


def test_job_status_text(ve, tmp_path):
    job = make_job(ve, tmp_path)
    assert job.status_text() == "Queued"
    job.status = CueJobStatus.ANALYZING
    assert job.status_text() == "Analyzing"
    job.status = CueJobStatus.ENCODING
    job.progress = 0.42
    assert job.status_text() == "Encoding 42%"
    job.status = CueJobStatus.FINALIZING
    assert job.status_text() == "Finalizing"
    job.status = CueJobStatus.DONE
    assert job.status_text() == "Done"
    job.status = CueJobStatus.ERROR
    assert job.status_text() == "Error"
    job.error_msg = "Cancelled"
    assert job.status_text() == "Cancelled"
    job.status = "weird"
    assert job.status_text() == "weird"


def test_job_filename(ve, tmp_path):
    assert make_job(ve, tmp_path).filename() == "scene.webm"
    job = CueVideoJob(99, vpath="", fspath_in="x", fspath_tmp="y", factor=1.0, encode_mode=0)
    assert job.filename() == "?"


def test_job_speed_label(ve, tmp_path):
    job = make_job(ve, tmp_path, factor=2.5)
    assert job.speed_label == "2.5x"


# ---------------------------------------------------------------------------
# queue: enqueue / find / start
# ---------------------------------------------------------------------------


def test_queue_init(ve):
    q = ve.job_queue
    assert q.processing is False
    assert q.current_job is None
    assert q.jobs == []


def test_enqueue_appends_and_starts(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q.enqueue(job)
    assert job in q.jobs
    assert q.current_job is job
    assert job.status == CueJobStatus.ANALYZING
    assert job.start_time > 0
    # current job is persisted
    assert [d["job_id"] for d in persistent._cue_jobs] == [job.job_id]


def test_enqueue_no_start_when_busy(ve, tmp_path):
    q = ve.job_queue
    blocker = make_job(ve, tmp_path, status=CueJobStatus.ENCODING)
    q._current = blocker
    job2 = make_job(ve, tmp_path)
    q.enqueue(job2)
    assert q.current_job is blocker
    assert job2.status == CueJobStatus.QUEUED


def test_find(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q.enqueue(job)
    assert q._find(job.job_id) is job
    assert q._find(9999) is None


def test_start_next_no_queued(ve):
    ve.job_queue._start_next()
    assert ve.job_queue.current_job is None


def test_start_next_needs_swap_skips_probe(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    job._needs_swap = True
    job._done = True
    job._ok = True
    q._jobs.append(job)
    q._start_next()
    assert q.current_job is job
    assert job._needs_swap is False
    assert job.status == CueJobStatus.FINALIZING
    assert job._swapping is True


def test_start_next_needs_swap_empty_tmp(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)  # no tmp file on disk
    job._needs_swap = True
    job._done = True
    job._ok = True
    q._jobs.append(job)
    q._start_next()
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Empty output"


def test_start_next_probe_thread(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._jobs.append(job)
    q._start_next()
    assert job.status == CueJobStatus.ANALYZING
    assert job.start_time > 0


# ---------------------------------------------------------------------------
# queue: poll state machine
# ---------------------------------------------------------------------------


def test_poll_no_current_starts_if_idle(ve):
    ve.job_queue.poll()  # empty queue: no crash
    assert ve.job_queue.current_job is None


def test_poll_swap_done_finishes(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._swapping = True
    job._swap_done = True
    job._swap_ok = True
    q.poll()
    assert job.status == CueJobStatus.DONE
    assert q.current_job is None


def test_poll_swap_done_cancelled(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._swapping = True
    job._swap_done = True
    job.cancelled = True
    q.poll()
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Cancelled"


def test_poll_done_cancelled_cleans_tmp(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    q._current = job
    job._done = True
    job.cancelled = True
    q.poll()
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Cancelled"
    assert not os.path.exists(job.fspath_tmp)
    assert q.current_job is None


def test_poll_done_not_ok_errors(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._done = True
    job._ok = False
    q.poll()
    assert job.status == CueJobStatus.ERROR
    assert q.current_job is None


def test_poll_done_ok_starts_swap(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    q._current = job
    job._done = True
    job._ok = True
    q.poll()
    assert job.status == CueJobStatus.FINALIZING
    assert job._swapping is True
    assert q.current_job is job  # not advanced yet


def test_poll_done_ok_missing_tmp_errors(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._done = True
    job._ok = True
    q.poll()
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Empty output"
    assert q.current_job is None


def test_poll_not_launched_waits(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    q.poll()  # probe thread still staging: status untouched
    assert job.status == CueJobStatus.QUEUED


def test_poll_not_launched_cancelled(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job.cancelled = True
    q.poll()
    assert job.status == CueJobStatus.QUEUED  # restart_interaction is the only effect


def test_poll_cancelled_kills_proc(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    proc = FakeProc(poll_result=0)  # exited after kill, so the reap poll returns
    job.proc = proc
    job.cancelled = True
    q.poll()
    assert job._done is True
    assert proc.killed is True
    assert job.proc is None


def test_poll_cancelled_wait_timeout_still_reaps(ve, tmp_path, monkeypatch):
    # Post-kill reap bound: a wait that times out must not wedge poll() or
    # raise -- the job is already cancelled, proc just can't be reaped.
    monkeypatch.setattr(_ffmpeg_mod, "CUE_KILL_WAIT_TIMEOUT", 0.05)
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    proc = FakeProc(poll_result=None)
    job.proc = proc
    job.cancelled = True
    q.poll()
    assert job._done is True
    assert proc.killed is True
    assert job.proc is None


def test_poll_proc_running_reads_progress(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    job.total_frames = 40
    job._progress_path = str(tmp_path / "prog.txt")
    write_file(job._progress_path, b"frame=10\nframe=20\n")
    job.proc = FakeProc(poll_result=None)
    q.poll()
    assert job.progress == 0.5
    # offset advanced: second read picks up only the new tail (append,
    # since ffmpeg grows the progress file in place)
    with open(job._progress_path, "ab") as f:
        f.write(b"frame=30\n")
    q.poll()
    assert job.progress == 0.75


def test_poll_proc_failed_sets_error(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    job._pass_idx = 1
    job._log_path = str(tmp_path / "enc.log")
    write_file(job._log_path, b"boom\n")
    job.proc = FakeProc(poll_result=1, returncode=1)
    q.poll()
    # the pass footer is written before the tail is read, so it is the
    # last non-empty line captured by _error_tail
    assert job.error_msg == "ffmpeg pass 1 rc=1: --- pass 1 rc=1 ---"
    assert job._done is True


def test_poll_proc_ok_launches_next_pass(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    job._pass_idx = 1
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg", "-y", "pass2"]]
    monkeypatch.setattr(_qeditor.subprocess, "Popen", lambda *a, **k: FakeProc())
    job.proc = FakeProc(poll_result=0, returncode=0)
    q.poll()
    assert job._pass_idx == 2
    assert job.status == CueJobStatus.ENCODING
    assert job.proc is not None


def test_poll_proc_ok_last_pass_finalizes(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    job._pass_idx = 1
    job._log_path = str(tmp_path / "enc.log")
    write_file(job.fspath_tmp)  # valid output
    job.proc = FakeProc(poll_result=0, returncode=0)
    q.poll()
    assert job._done is True
    assert job._ok is True
    assert job.progress == 1.0


def test_poll_launches_first_pass(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._current = job
    job._launched = True
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg", "-y"]]
    monkeypatch.setattr(_qeditor.subprocess, "Popen", lambda *a, **k: FakeProc())
    q.poll()
    assert job.status == CueJobStatus.ENCODING
    assert job._pass_idx == 1
    assert job.proc is not None


# ---------------------------------------------------------------------------
# queue: pass launch / progress / finalize helpers
# ---------------------------------------------------------------------------


def test_launch_pass_cancelled_noop(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job.cancelled = True
    job._cmds = [["ffmpeg"]]
    calls = []
    monkeypatch.setattr(_qeditor.subprocess, "Popen", lambda *a, **k: calls.append(1))
    q._launch_pass(job)
    assert calls == []


def test_launch_pass_writes_header(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg", "-y", "-i", "in"]]
    monkeypatch.setattr(_qeditor.subprocess, "Popen", lambda *a, **k: FakeProc())
    q._launch_pass(job)
    assert job._pass_idx == 1
    assert job.proc is not None
    with open(job._log_path, "rb") as f:
        data = f.read()
    assert b"--- pass 1 ---" in data
    assert b"ffmpeg -y -i in" in data


def test_launch_pass_popen_error(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg"]]

    def _boom(*a, **k):
        raise OSError("spawn failed")

    monkeypatch.setattr(_qeditor.subprocess, "Popen", _boom)
    q._launch_pass(job)
    assert job.error_msg == "ffmpeg error: spawn failed"
    assert job._done is True


def test_read_progress_missing_file(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._progress_path = str(tmp_path / "nope.txt")
    job.total_frames = 100
    q._read_progress(job)  # must not raise
    assert job.progress == 0.0


def test_read_progress_no_total_frames(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._progress_path = str(tmp_path / "prog.txt")
    write_file(job._progress_path, b"frame=50\n")
    job.total_frames = 0
    q._read_progress(job)
    assert job.progress == 0.0


def test_read_progress_bad_frame_line(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._progress_path = str(tmp_path / "prog.txt")
    write_file(job._progress_path, b"frame=notanumber\n")
    job.total_frames = 10
    q._read_progress(job)  # parse failure ignored
    assert job.progress == 0.0


def test_append_pass_footer(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._pass_idx = 2
    job._log_path = str(tmp_path / "enc.log")
    write_file(job._log_path, b"")
    q._append_pass_footer(job, 0)
    with open(job._log_path, "rb") as f:
        assert b"--- pass 2 rc=0 ---" in f.read()


def test_error_tail_truncates(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._pass_idx = 1
    job._log_path = str(tmp_path / "enc.log")
    long_line = "x" * 300
    write_file(job._log_path, ("pad\n" + long_line).encode())
    tail = q._error_tail(job, 2)
    assert tail == "ffmpeg pass 1 rc=2: " + "x" * 120


def test_finalize_encode_success_cleans_artifacts(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job.passlog = str(tmp_path / "p.passlog")
    for suffix in ("-0.log", "-1.log"):
        write_file(job.passlog + suffix)
    job._progress_path = str(tmp_path / "prog.txt")
    write_file(job._progress_path, b"frame=1\n")
    write_file(job.fspath_tmp)
    q._finalize_encode(job)
    assert job._ok is True
    assert not os.path.exists(job.passlog + "-0.log")
    assert not os.path.exists(job.passlog + "-1.log")
    assert not os.path.exists(job._progress_path)


def test_finalize_encode_no_output(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)  # tmp never created
    q._finalize_encode(job)
    assert job._ok is False
    assert job.error_msg == "ffmpeg produced no output"
    assert job._done is True


# ---------------------------------------------------------------------------
# queue: swap
# ---------------------------------------------------------------------------


def test_start_swap_missing_paths(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job.fspath_tmp = None
    assert q._start_swap(job) is False
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Missing paths"


def test_start_swap_empty_tmp(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp, b"")  # zero bytes
    assert q._start_swap(job) is False
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Empty output"


def test_start_swap_success(ve, tmp_path, fthread):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    assert q._start_swap(job) is True
    assert job.status == CueJobStatus.FINALIZING
    assert job._swapping is True
    assert job._swap_done is False


def test_finish_swap_success(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._swap_ok = True
    q._finish_swap(job)
    assert job.status == CueJobStatus.DONE
    assert ve._states["movies/scene.webm"].last_error == ""


def test_finish_swap_fail_locked(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._swap_ok = False
    job._swap_error_msg = "File locked.  Retry later"
    q._finish_swap(job)
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "File locked.  Retry later"
    assert "still has this video file open" in ve._states[job.vpath].last_error


def test_finish_swap_missing_out(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job.fspath_out = None
    job._swap_ok = True
    q._finish_swap(job)
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Missing paths"


# ---------------------------------------------------------------------------
# queue: retry / cancel / remove / kill / cleanup
# ---------------------------------------------------------------------------


def test_retry_not_found(ve, tmp_path):
    ve.job_queue.retry(9999)  # must not raise


def test_retry_only_errors(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._jobs.append(job)
    q._current = job  # block _start_if_idle
    q.retry(job.job_id)  # status "queued" -> no-op
    assert job.status == CueJobStatus.QUEUED


def test_retry_tmp_exists_needs_swap(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path, status=CueJobStatus.ERROR)
    write_file(job.fspath_tmp)
    q._jobs.append(job)
    q._current = make_job(ve, tmp_path, status=CueJobStatus.ENCODING)  # block start
    q.retry(job.job_id)
    assert job.status == CueJobStatus.QUEUED
    assert job._needs_swap is True
    assert job._done is True
    assert job._ok is True


def test_retry_tmp_missing_reencode(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path, status=CueJobStatus.ERROR)
    q._jobs.append(job)
    q._current = make_job(ve, tmp_path, status=CueJobStatus.ENCODING)  # block start
    q.retry(job.job_id)
    assert job.status == CueJobStatus.QUEUED
    assert job._needs_swap is False
    assert job._done is False
    assert job._ok is False
    assert job._launched is False
    assert job._cmds == []
    assert job._pass_idx == 0
    assert job.progress == 0.0
    assert job.error_msg == ""


def test_cancel_queued_removes(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._jobs.append(job)
    q.cancel(job.job_id)
    assert job not in q._jobs


def test_cancel_current_kills(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path, status=CueJobStatus.ENCODING)
    proc = FakeProc(poll_result=None)
    job.proc = proc
    q._jobs.append(job)
    q._current = job
    q.cancel(job.job_id)
    assert job.cancelled is True
    assert proc.killed is True


def test_cancel_done_removes(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path, status=CueJobStatus.DONE)
    q._jobs.append(job)
    q.cancel(job.job_id)
    assert job not in q._jobs


def test_cancel_not_found(ve):
    ve.job_queue.cancel(9999)  # must not raise


def test_remove_only_terminal(ve, tmp_path):
    q = ve.job_queue
    done = make_job(ve, tmp_path, status=CueJobStatus.DONE)
    queued = make_job(ve, tmp_path, status=CueJobStatus.QUEUED)
    q._jobs.extend([done, queued])
    q.remove(done.job_id)
    assert done not in q._jobs
    q.remove(queued.job_id)  # queued: not removed
    assert queued in q._jobs


def test_kill_proc(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    proc = FakeProc(poll_result=0)  # exits immediately on the reap poll
    job.proc = proc
    q._kill_proc(job)
    assert proc.killed is True
    assert job.proc is None


def test_cleanup_temp_removes_all(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    job.passlog = str(tmp_path / "p.passlog")
    for suffix in ("-0.log", "-1.log"):
        write_file(job.passlog + suffix)
    job._progress_path = str(tmp_path / "prog.txt")
    write_file(job._progress_path)
    q._cleanup_temp(job)
    assert not os.path.exists(job.fspath_tmp)
    assert not os.path.exists(job.passlog + "-0.log")
    assert not os.path.exists(job.passlog + "-1.log")
    assert not os.path.exists(job._progress_path)


# ---------------------------------------------------------------------------
# queue: persistence
# ---------------------------------------------------------------------------


def test_save_serializes_queued_and_current(ve, tmp_path):
    q = ve.job_queue
    q._current = None
    queued = make_job(ve, tmp_path)
    q._jobs.append(queued)
    cur = make_job(ve, tmp_path, status=CueJobStatus.ENCODING)
    q._current = cur
    q.save_to_persistent()
    ids = [d["job_id"] for d in persistent._cue_jobs]
    assert queued.job_id in ids
    assert cur.job_id in ids
    d = persistent._cue_jobs[0]
    assert d["factor"] == 2.0
    assert d["remove_audio"] is False


def test_save_skips_done_jobs(ve, tmp_path):
    q = ve.job_queue
    done = make_job(ve, tmp_path, status=CueJobStatus.DONE)
    q._jobs.append(done)
    q.save_to_persistent()
    assert persistent._cue_jobs is None


def test_load_from_persistent_restores(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "in.webm")
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 5,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "in.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
                "remove_audio": False,
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert len(ve.job_queue._jobs) == 1
    job = ve.job_queue._jobs[0]
    assert job.job_id == 5
    assert job.factor == 3.0
    assert job._resume_pass2 is False
    assert ve.job_queue._next_job_id == 6


def test_loaded_job_reports_pending(ve, tmp_path, monkeypatch):
    """A job restored from persistent sits QUEUED with no current job.  The
    runtime driver polls the queue only when it reports pending work, so a
    restored queue must report pending or the job never starts."""
    write_file(tmp_path / "in.webm")
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 5,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "in.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
                "remove_audio": False,
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert ve.job_queue.has_pending is True


def test_load_skips_existing_output(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "in.webm")
    write_file(tmp_path / "out.webm")
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 1,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "in.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert ve.job_queue._jobs == []


def test_load_skips_missing_input(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 1,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "gone.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert ve.job_queue._jobs == []


def test_load_detects_pass2_resume(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "in.webm")
    write_file(tmp_path / "tmp.webm.passlog-0.log")
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 2,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "in.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert len(ve.job_queue._jobs) == 1
    assert ve.job_queue._jobs[0]._resume_pass2 is True


def test_load_skips_malformed(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "in.webm")
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": "not-an-int",
                "vpath": "x",
                "fspath_in": "x",
                "fspath_tmp": "x",
                "factor": "z",
                "encode_mode": 0,
            },
            {
                "job_id": 9,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "in.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 1.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
            },
        ],
    )
    ve.job_queue.load_from_persistent()
    assert len(ve.job_queue._jobs) == 1  # malformed skipped
    assert ve.job_queue._jobs[0].job_id == 9


def test_load_wrong_type_clears(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(persistent, "_cue_jobs", "not a list")
    ve.job_queue.load_from_persistent()
    assert persistent._cue_jobs is None


def test_load_none_is_noop(ve, tmp_path):
    ve.job_queue.load_from_persistent()  # persistent._cue_jobs is None
    assert ve.job_queue._jobs == []


def test_get_elapsed(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    assert q.get_elapsed() == 0.0
    job = make_job(ve, tmp_path)
    job.start_time = 100.0
    q._current = job
    monkeypatch.setattr(_qeditor._time, "time", lambda: 102.0)
    assert q.get_elapsed() == 2.0


# ---------------------------------------------------------------------------
# _cue_swap_job (background swap)
# ---------------------------------------------------------------------------


def test_swap_job_missing_paths(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(_qeditor._time, "sleep", lambda s: None)
    job = make_job(ve, tmp_path)
    job.fspath_tmp = None
    _qeditor._cue_swap_job(job)
    assert job._swap_ok is False
    assert job._swap_error_msg == "Missing paths"
    assert job._swap_done is True


def test_swap_job_success(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(_qeditor._time, "sleep", lambda s: None)
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp, b"encoded")
    _qeditor._cue_swap_job(job)
    assert job._swap_ok is True
    assert job._swap_error_msg == ""
    assert os.path.exists(job.fspath_out)
    with open(job.fspath_out, "rb") as f:
        assert f.read() == b"encoded"


def test_swap_job_failure_retries(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(_qeditor._time, "sleep", lambda s: None)

    def _blocked(src, dst):
        raise OSError("file locked")

    monkeypatch.setattr(_qeditor, "_cue_replace_file", _blocked)
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    _qeditor._cue_swap_job(job)
    assert job._swap_ok is False
    assert job._swap_error_msg == "File locked.  Retry later"
    assert job._swap_done is True


# ---------------------------------------------------------------------------
# CueVideoEditor coordinator
# ---------------------------------------------------------------------------


def test_editor_factor_text_dummy(ve):
    assert ve.factor_text == "1.1"  # no current -> dummy state, default 1.1x


def test_editor_factor_text_roundtrip(ve):
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "2.50"
    assert ve.factor_text == "2.50"


def test_editor_last_error_stores_raw(ve):
    # Escaping happens at display (etext), not in the setter -- the raw value
    # is kept so a later render escapes it exactly once.
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.last_error = "Bad [x]"
    assert ve.last_error == "Bad [x]"
    assert _cue_escape_text(ve.last_error) == "Bad [[x]"


def test_editor_last_error_no_current_is_noop(ve):
    ve.last_error = "nope"  # setter guarded when no state
    assert ve.last_error == ""


def test_editor_set_quick(ve):
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.set_quick(2.3)
    assert ve.factor_text == "2.3"
    ve.set_quick(50)
    assert ve.factor_text == "10.0"
    ve.set_quick(0.01)
    assert ve.factor_text == "0.1"


def test_editor_commit_text(ve):
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "2.5"
    ve.commit_text()
    assert ve.factor_text == "2.5"
    ve.factor_text = "abc"
    ve.commit_text()
    assert ve.factor_text == "1.0"
    ve.factor_text = "999"
    ve.commit_text()
    assert ve.factor_text == "10.0"


def test_editor_nudge(ve):
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "1.5"
    ve.nudge(0.3)
    assert ve.factor_text == "1.8"
    ve.factor_text = "abc"
    ve.nudge(0.1)
    assert ve.factor_text == "1.1"
    ve.factor_text = "10.0"
    ve.nudge(0.5)
    assert ve.factor_text == "10.0"


def test_editor_get_factor(ve):
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "2.5"
    assert ve.get_factor() == 2.5
    ve.factor_text = "abc"
    assert ve.get_factor() == 1.0


def test_editor_set_encode_mode_valid(ve):
    ve.set_encode_mode(CUE_VE_MODE_FAST_PREVIEW)
    assert ve.encode_mode == CUE_VE_MODE_FAST_PREVIEW
    assert persistent._cue["encode_mode"] == CUE_VE_MODE_FAST_PREVIEW


def test_editor_set_encode_mode_invalid(ve):
    ve.encode_mode = CUE_VE_MODE_NORMAL
    ve.set_encode_mode(9)
    assert ve.encode_mode == CUE_VE_MODE_NORMAL


def test_editor_toggle_remove_audio(ve):
    assert ve.remove_audio is True
    ve.toggle_remove_audio()
    assert ve.remove_audio is False
    assert persistent._cue["remove_audio"] is False


def test_editor_check_prerequisites_no_video(ve, tmp_path):
    ve._vid_manager._vpath = ""
    assert ve.check_prerequisites() == ("error", "No video is currently playing.")


def test_editor_check_prerequisites_rpa(ve, tmp_path):
    # vpath set but file not on disk -> inside an archive
    status, msg = ve.check_prerequisites()
    assert status == "rpa"
    assert "archive" in msg


def test_editor_check_prerequisites_ffmpeg_missing(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ffmpeg = FakeFFmpeg(available=False, cache=0)
    status, msg = ve.check_prerequisites()
    assert status == "error"
    assert "ffmpeg not found" in msg


def test_editor_check_prerequisites_ok(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    assert ve.check_prerequisites() == ("ok", "")


def test_editor_check_prerequisites_readonly(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    monkeypatch.setattr(os, "access", lambda p, m: False)
    status, msg = ve.check_prerequisites()
    assert status == "error"
    assert "read-only" in msg


def test_editor_extract_no_video(ve):
    ve._vid_manager._vpath = ""
    assert ve.extract_from_rpa() == ("error", "No video is currently playing.")


def test_editor_extract_success(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(renpy, "file", lambda vp: FakeRenPyFile())
    ok, fspath = ve.extract_from_rpa()
    assert ok == "ok"
    with open(fspath, "rb") as f:
        assert f.read() == b"video-bytes"


def test_editor_extract_cannot_open(ve, tmp_path, monkeypatch):
    def _raise(vp):
        raise OSError("no such archive")

    monkeypatch.setattr(renpy, "file", _raise)
    ok, msg = ve.extract_from_rpa()
    assert ok == "error"
    assert "Cannot open" in msg


def test_editor_extract_write_failure(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(renpy, "file", lambda vp: FakeRenPyFile())
    real_open = open

    def _flaky_open(path, mode, *a, **k):
        if mode == "wb":
            raise OSError("disk full")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", _flaky_open)
    ok, msg = ve.extract_from_rpa()
    assert ok == "error"
    assert "Failed to write extracted file" in msg


def test_editor_show_create_tab_warm_thread(ve, fthread):
    ve._ffmpeg = FakeFFmpeg(cache=-1)
    ve.show_tab(CueVideoEditorTab.CREATE)
    assert ve.active is True
    assert ve._current is not None
    assert ve._ready is False  # warm check still running


def test_editor_show_create_tab_ready(ve):
    ve._ffmpeg = FakeFFmpeg(cache=0)
    ve.show_tab(CueVideoEditorTab.CREATE)
    assert ve.active is True
    assert ve._ready is True


def test_editor_refresh_has_audio(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve.tab = CueVideoEditorTab.CREATE
    ve.refresh()
    assert ve._current_has_audio is True


def test_editor_refresh_no_ffprobe(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ffmpeg = FakeFFmpeg(ffprobe_ok=False, cache=0)
    ve.tab = CueVideoEditorTab.CREATE
    ve.refresh()
    assert ve._current_has_audio is None


def test_editor_refresh_no_video(ve):
    ve._vid_manager._vpath = ""
    ve.tab = CueVideoEditorTab.CREATE
    ve.refresh()
    assert ve._current_has_audio is None


def test_editor_refresh_skips_probe_outside_create(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve.tab = CueVideoEditorTab.SPEED
    calls = []
    orig = ve._ffmpeg.probe_has_audio
    ve._ffmpeg.probe_has_audio = lambda fspath: calls.append(fspath) or orig(fspath)
    ve.refresh()
    assert ve._current_has_audio is None
    assert calls == []


def test_editor_refresh_probes_once_per_video(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve.tab = CueVideoEditorTab.CREATE
    calls = []
    orig = ve._ffmpeg.probe_has_audio
    ve._ffmpeg.probe_has_audio = lambda fspath: calls.append(fspath) or orig(fspath)
    ve.refresh()
    ve.refresh()
    ve.show_tab(CueVideoEditorTab.SPEED)
    ve.show_tab(CueVideoEditorTab.CREATE)
    assert ve._current_has_audio is True
    assert len(calls) == 1


def test_editor_show_speed_tab(ve):
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.active = True
    ve.show_tab(CueVideoEditorTab.SPEED)
    assert ve.active is False
    assert ve._current is None


def test_editor_prepare_create_not_ready(ve):
    ve._ready = False
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.prepare_create()
    assert "Checking ffmpeg" in ve.last_error


def test_editor_prepare_create_warm_cache_error(ve):
    ve._ready = True
    ve._warm_cache_error = "boom"
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.prepare_create()
    assert "ffmpeg check failed: boom" in ve.last_error


def test_editor_prepare_create_prereq_error(ve):
    ve._ready = True
    ve._vid_manager._vpath = ""
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.prepare_create()
    assert ve.last_error == "No video is currently playing."


def test_editor_prepare_create_rpa_extract_error(ve, monkeypatch):
    ve._ready = True
    ve._current = ve._ensure_state("movies/scene.webm")

    def _fake_extract(vp):
        return ("error", "Cannot open '{}' in game archives: no archive".format(vp))

    monkeypatch.setattr(ve, "extract_from_rpa", _fake_extract)
    ve.prepare_create()
    # Extraction is deferred: prepare_create only arms it; poll_extract
    # surfaces the error once the background thread reports done.
    assert ve.rpa_extract.in_progress is True
    ve.rpa_extract.done = True
    ve.poll_extract()
    assert "Cannot open" in ve.last_error


def test_editor_prepare_create_speed_one(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ready = True
    ve.encode_mode = CUE_VE_MODE_NORMAL
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "1.00"
    ve.prepare_create()
    assert ve.last_error == "Speed is already 1.00x."


def test_editor_prepare_create_success(ve, tmp_path, fthread):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ready = True
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "2.00"
    ve.prepare_create()
    assert len(ve.job_queue.jobs) == 1
    job = ve.job_queue.jobs[0]
    assert job.factor == 2.0
    assert job.encode_mode == CUE_VE_MODE_INTERPOLATE  # editor default


def test_editor_prepare_create_normalizes_factor(ve, tmp_path, fthread):
    # A typed sub-decimal factor rounds to tenths so the encoded speed
    # matches the {:.1f}x filename label (1.08 -> 1.1x, not a 1.08x encode
    # stored as "1.1x").
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ready = True
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "1.08"
    ve.prepare_create()
    assert len(ve.job_queue.jobs) == 1
    assert ve.job_queue.jobs[0].factor == 1.1
    assert ve.factor_text == "1.1"


def test_editor_prepare_create_subdecimal_rounds_to_one(ve, tmp_path):
    # 1.04 rounds to 1.0, which the Create guard rejects.
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ready = True
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "1.04"
    ve.prepare_create()
    assert ve.last_error == "Speed is already 1.00x."
    assert len(ve.job_queue.jobs) == 0


def test_editor_create_no_fs(ve):
    ve._vid_manager._vpath = ""
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.create(2.0)
    assert ve.last_error == "Video file disappeared."


def test_editor_create_enqueues_job(ve, tmp_path, fthread):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.create(2.0)
    assert len(ve.job_queue.jobs) == 1
    job = ve.job_queue.jobs[0]
    assert job.factor == 2.0
    assert job.fspath_out.endswith("__cue_2.0x.webm")


def test_editor_create_temp_name_unique_per_job(ve, tmp_path, fthread):
    """The encode temp (and its derived passlog) must be job-scoped, not
    keyed only by (base, speed) -- a stale temp/passlog from one job must
    never be reused by another job for the same video+speed."""
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.create(2.0)
    ve.create(2.0)  # same video, same speed -- a second job
    jobs = ve.job_queue.jobs
    assert len(jobs) == 2
    t1, t2 = jobs[0].fspath_tmp, jobs[1].fspath_tmp
    assert t1 != t2
    # Each temp embeds its own job id.
    assert str(jobs[0].job_id) in os.path.basename(t1)
    assert str(jobs[1].job_id) in os.path.basename(t2)
    # Passlogs derive from the temp path, so they are unique too.
    assert t1 + ".passlog" != t2 + ".passlog"


def test_editor_queue_properties(ve, tmp_path):
    assert ve.processing is False
    assert ve._get_state() is None
    assert isinstance(ve._get_state_or_dummy(), CueVideoEditorState)
    ve._current = ve._ensure_state("movies/scene.webm")
    assert ve._get_state() is ve._states["movies/scene.webm"]
    assert ve._state_for_vpath("movies/scene.webm") is ve._states["movies/scene.webm"]
    assert ve._state_for_vpath("nope") is None


# ---------------------------------------------------------------------------
# coverage push: editor + queue exception branches
# ---------------------------------------------------------------------------


def test_editor_check_prerequisites_not_found_disk(ve, monkeypatch):
    # _get_video_fspath() misses and _is_in_rpa() sees no vpath on its own
    # re-read -> "not found on disk" (also covers _is_in_rpa's no-vp False)
    calls = [0]

    def _stateful():
        calls[0] += 1
        return "movies/scene.webm" if calls[0] == 1 else None

    monkeypatch.setattr(ve, "_get_video_vpath", _stateful)
    status, msg = ve.check_prerequisites()
    assert status == "error"
    assert msg == "Video file not found on disk."


def test_editor_check_prerequisites_dir_readonly(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    fs = os.path.normpath(os.path.join(str(tmp_path), "movies/scene.webm"))
    real_access = os.access

    def _access(path, mode):
        if path == os.path.dirname(fs) and mode == os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", _access)
    status, msg = ve.check_prerequisites()
    assert status == "error"
    assert "read-only" in msg


def test_editor_extract_makedirs_fails(ve, monkeypatch):
    def _boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(os, "makedirs", _boom)
    ok, msg = ve.extract_from_rpa()
    assert ok == "error"
    assert "Cannot create directory" in msg


def test_editor_warm_cache(ve):
    ve._warm_cache()
    assert ve._ffmpeg._ffmpeg_cache == 1


def test_editor_warm_tools(ve):
    ve._warm_tools()
    assert ve._ready is True
    assert ve._warm_cache_error == ""


def test_editor_warm_tools_error(ve, monkeypatch):
    def _boom():
        raise OSError("encoders unavailable")

    monkeypatch.setattr(ve._ffmpeg, "load_encoders", _boom)
    ve._warm_tools()
    assert ve._ready is True
    assert ve._warm_cache_error == "encoders unavailable"


def test_editor_prepare_create_bad_factor(ve, tmp_path):
    # A non-numeric factor falls back to 1.0, which the Create guard rejects.
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._ready = True
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.factor_text = "abc"
    ve.prepare_create()
    assert ve.last_error == "Speed is already 1.00x."
    assert len(ve.job_queue.jobs) == 0


def test_poll_extract_prereq_error_after_extract(ve, tmp_path, monkeypatch):
    # Background extract succeeded, but check_prerequisites fails on the
    # main thread -> poll_extract surfaces that error instead of creating.
    ve._current = ve._ensure_state("movies/scene.webm")
    monkeypatch.setattr(ve, "check_prerequisites", lambda: ("error", "nope"))
    ve.rpa_extract.in_progress = True
    ve.rpa_extract.done = True
    ve.rpa_extract.ok = True
    ve.rpa_extract.msg = str(tmp_path / "movies" / "scene.webm")
    ve.rpa_extract.vpath = "movies/scene.webm"
    ve.poll_extract()
    assert ve.last_error == "nope"
    assert ve.rpa_extract.in_progress is False


def test_editor_create_no_vp(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve._current = ve._ensure_state("movies/scene.webm")
    calls = [0]

    def _stateful():
        calls[0] += 1
        return "movies/scene.webm" if calls[0] == 1 else None

    monkeypatch.setattr(ve, "_get_video_vpath", _stateful)
    ve.create(2.0)
    assert len(ve.job_queue.jobs) == 0


def test_editor_refresh_processing(ve, tmp_path):
    write_file(tmp_path / "movies" / "scene.webm", b"v")
    ve.refresh()
    job = make_job(ve, tmp_path, status=CueJobStatus.ENCODING)
    ve.job_queue._current = job
    ve.refresh()
    assert ve.last_error == ""


def test_start_next_get_duration_raises(ve, tmp_path, fthread, monkeypatch):
    def _boom(channel=None):
        raise RuntimeError("no channel")

    monkeypatch.setattr(_qeditor._music, "get_duration", _boom)
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._jobs.append(job)
    q._start_next()
    assert job.status == CueJobStatus.ANALYZING


def test_launch_pass_popen_error_cancelled(ve, tmp_path, monkeypatch):
    # Main-thread cancel() can't run mid-launch, so the cancelled branch of
    # the launch except is defensive dead code; fake the Popen to set it.
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg"]]

    def _boom(*a, **k):
        job.cancelled = True
        raise OSError("spawn failed")

    monkeypatch.setattr(_qeditor.subprocess, "Popen", _boom)
    q._launch_pass(job)
    assert job._done is True
    assert job.proc is None


def test_launch_pass_close_raises(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg"]]
    monkeypatch.setattr(_qeditor.subprocess, "Popen", lambda *a, **k: FakeProc())

    class _FlakyLogFile(object):
        def write(self, data):
            pass

        def flush(self):
            pass

        def close(self):
            raise OSError("flush failed")

    monkeypatch.setattr(_qeditor, "open", lambda path, mode: _FlakyLogFile(), raising=False)
    q._launch_pass(job)
    assert job.proc is not None


def test_launch_pass_cancelled_kills_after_popen(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._log_path = str(tmp_path / "enc.log")
    job._cmds = [["ffmpeg"]]
    proc = FakeProc()

    def _popen(*a, **k):
        job.cancelled = True
        return proc

    monkeypatch.setattr(_qeditor.subprocess, "Popen", _popen)
    q._launch_pass(job)
    assert proc.killed is True
    assert job._done is True


def test_read_progress_open_fails(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    d = tmp_path / "progdir"
    d.mkdir()
    job._progress_path = str(d)
    job.total_frames = 100
    q._read_progress(job)
    assert job.progress == 0.0


def test_append_pass_footer_write_fails(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._pass_idx = 2
    d = tmp_path / "logdir"
    d.mkdir()
    job._log_path = str(d)
    q._append_pass_footer(job, 0)  # must not raise


def test_error_tail_read_fails(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._pass_idx = 1
    d = tmp_path / "logdir"
    d.mkdir()
    job._log_path = str(d)
    assert q._error_tail(job, 1) == "ffmpeg pass 1 rc=1: "


def test_finalize_encode_passlog_cleanup_fails(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job.passlog = str(tmp_path / "p.passlog")
    (tmp_path / "p.passlog-0.log").mkdir()
    q._finalize_encode(job)
    assert job._done is True


def test_finalize_encode_progress_cleanup_fails(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    job._progress_path = str(tmp_path / "progdir")
    (tmp_path / "progdir").mkdir()
    q._finalize_encode(job)
    assert job._done is True


def test_start_swap_getsize_raises(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)

    def _boom(path):
        raise OSError("io error")

    monkeypatch.setattr(os.path, "getsize", _boom)
    assert q._start_swap(job) is False
    assert job.status == CueJobStatus.ERROR
    assert job.error_msg == "Cannot read temp"


def test_start_swap_stops_playing_channel(ve, tmp_path, fthread, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    monkeypatch.setattr(_qeditor._aaudio, "channels", {"movie": {}})
    _qeditor._music._registry.setdefault("movie", {})["playing"] = "out.webm"
    assert q._start_swap(job) is True
    assert _qeditor._music._registry["movie"].get("playing") is None
    assert job._swapping is True


def test_start_swap_other_channel_playing(ve, tmp_path, fthread, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    monkeypatch.setattr(_qeditor._aaudio, "channels", {"movie": {}})
    _qeditor._music._registry.setdefault("movie", {})["playing"] = "other.webm"
    assert q._start_swap(job) is True
    assert _qeditor._music._registry["movie"].get("playing") == "other.webm"


def test_start_swap_channel_stop_error(ve, tmp_path, fthread, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    write_file(job.fspath_tmp)
    monkeypatch.setattr(_qeditor._aaudio, "channels", {"movie": {}})

    def _boom(channel=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(_qeditor._music, "get_playing", _boom)
    assert q._start_swap(job) is True
    assert job.status == CueJobStatus.FINALIZING


def test_kill_proc_wait_raises(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)

    class _Proc(object):
        pid = 777

        def kill(self):
            pass

        def wait(self):
            raise OSError("wait failed")

    job.proc = _Proc()
    q._kill_proc(job)
    assert job.proc is None


def test_kill_proc_kill_raises(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)

    class _Proc(object):
        pid = 777

        def kill(self):
            raise OSError("kill failed")

        def wait(self):
            return 0

    job.proc = _Proc()
    q._kill_proc(job)
    assert job.proc is None


def test_cleanup_temp_remove_fails(ve, tmp_path):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    (tmp_path / "tmpdir").mkdir()
    job.fspath_tmp = str(tmp_path / "tmpdir")
    job.passlog = str(tmp_path / "p.passlog")
    (tmp_path / "p.passlog-0.log").mkdir()
    (tmp_path / "p.passlog-1.log").mkdir()
    job._progress_path = str(tmp_path / "progdir")
    (tmp_path / "progdir").mkdir()
    q._cleanup_temp(job)  # all three removes fail on directories


def test_save_not_initialized_noop(ve, tmp_path, monkeypatch):
    from cue_lib.state import _cue as _state_cue

    monkeypatch.setattr(_state_cue, "initialized", False, raising=False)
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._jobs.append(job)
    q.save_to_persistent()
    assert persistent._cue_jobs is None


def test_save_to_persistent_fails(ve, tmp_path, monkeypatch):
    q = ve.job_queue
    job = make_job(ve, tmp_path)
    q._jobs.append(job)

    class _FlakyPersistent(object):
        def __init__(self):
            self._stored = None

        @property
        def _cue_jobs(self):
            return self._stored

        @_cue_jobs.setter
        def _cue_jobs(self, value):
            if value is not None:
                raise OSError("disk full")
            self._stored = value

    monkeypatch.setattr(_qeditor, "persistent", _FlakyPersistent())
    q.save_to_persistent()  # must not raise


def test_load_removes_stale_tmp_with_error(ve, tmp_path, monkeypatch):
    (tmp_path / "tmpdir").mkdir()
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 1,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "gone.webm"),
                "fspath_tmp": str(tmp_path / "tmpdir"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert ve.job_queue._jobs == []


def test_load_removes_stale_passlog_with_error(ve, tmp_path, monkeypatch):
    write_file(tmp_path / "tmp.webm")
    (tmp_path / "tmp.webm.passlog-0.log").mkdir()
    monkeypatch.setattr(
        persistent,
        "_cue_jobs",
        [
            {
                "job_id": 1,
                "vpath": "movies/scene.webm",
                "fspath_in": str(tmp_path / "gone.webm"),
                "fspath_tmp": str(tmp_path / "tmp.webm"),
                "factor": 3.0,
                "encode_mode": 0,
                "fspath_out": str(tmp_path / "out.webm"),
            }
        ],
    )
    ve.job_queue.load_from_persistent()
    assert ve.job_queue._jobs == []


def test_load_persistent_unwrap_error(ve, tmp_path, monkeypatch):
    monkeypatch.setattr(persistent, "_cue_jobs", [{"job_id": 1}])

    def _boom(raw):
        raise RuntimeError("unpack failed")

    monkeypatch.setattr(_qeditor, "_cue_unwrap_persistent", _boom)
    ve.job_queue.load_from_persistent()  # must not raise
    assert ve.job_queue._jobs == []


# ---------------------------------------------------------------------------
# .rpa extraction deferral (finding 11 Part B)
# ---------------------------------------------------------------------------


def test_extract_then_create_spawns_background_thread(ve, monkeypatch):
    threads = []

    class CaptureThread(object):
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon
            threads.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(_veditor.threading, "Thread", CaptureThread)
    ve._extract_then_create()
    assert ve.rpa_extract.in_progress is True
    assert ve.rpa_extract.done is False
    assert len(threads) == 1
    t = threads[0]
    assert t.target is _veditor._cue_extract_rpa
    assert t.args[0] is ve
    assert t.args[1] == "movies/scene.webm"
    assert t.daemon is True  # set after construction, like _warm_tools
    assert t.started is True


def test_extract_then_create_ignores_second_call_while_extracting(ve, monkeypatch):
    calls = []

    class DummyThread(object):
        def start(self):
            pass

    monkeypatch.setattr(_veditor.threading, "Thread", lambda **kw: calls.append(1) or DummyThread())
    ve.rpa_extract.in_progress = True  # simulate in-flight extraction
    ve.rpa_extract.vpath = "movies/old.webm"
    ve._extract_then_create()
    assert calls == []  # no new thread
    assert ve.rpa_extract.vpath == "movies/old.webm"  # state untouched


def test_extract_then_create_no_video_sets_error(ve, monkeypatch):
    monkeypatch.setattr(ve, "_get_video_vpath", lambda: None)
    ve._current = ve._ensure_state("movies/scene.webm")
    ve._extract_then_create()
    assert ve.rpa_extract.in_progress is False
    assert ve.last_error == "No video is currently playing."


def test_poll_extract_noop_when_idle(ve, monkeypatch):
    restarts = []
    monkeypatch.setattr(_veditor.renpy, "restart_interaction", lambda: restarts.append(1))
    ve.rpa_extract.in_progress = False
    ve.rpa_extract.done = True  # even with done set, not extracting => noop
    ve.poll_extract()
    assert ve.rpa_extract.in_progress is False
    assert restarts == []


def test_poll_extract_error_sets_last_error(ve, monkeypatch):
    restarts = []
    monkeypatch.setattr(_veditor.renpy, "restart_interaction", lambda: restarts.append(1))
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.rpa_extract.in_progress = True
    ve.rpa_extract.done = True
    ve.rpa_extract.ok = False
    ve.rpa_extract.msg = "boom"
    ve.rpa_extract.vpath = "movies/scene.webm"
    ve.poll_extract()
    assert ve.rpa_extract.in_progress is False
    assert ve.last_error == "boom"
    assert restarts == [1]


def test_poll_extract_vpath_changed_bails(ve, monkeypatch):
    restarts = []
    monkeypatch.setattr(_veditor.renpy, "restart_interaction", lambda: restarts.append(1))
    ve._current = ve._ensure_state("movies/scene.webm")
    ve.rpa_extract.in_progress = True
    ve.rpa_extract.done = True
    ve.rpa_extract.ok = True
    ve.rpa_extract.msg = "/tmp/scene.webm"
    ve.rpa_extract.vpath = "movies/old.webm"  # no longer the current video
    ve.poll_extract()
    assert ve.rpa_extract.in_progress is False
    assert "changed" in ve.last_error
    assert restarts == [1]


def test_poll_extract_happy_path_creates(ve, monkeypatch):
    restarts = []
    monkeypatch.setattr(_veditor.renpy, "restart_interaction", lambda: restarts.append(1))
    monkeypatch.setattr(ve, "check_prerequisites", lambda: ("ok", ""))
    created = []
    monkeypatch.setattr(ve, "create", lambda factor: created.append(factor))
    ve._current = ve._ensure_state("movies/scene.webm")
    ve._current.factor_text = "2.00"
    ve.rpa_extract.in_progress = True
    ve.rpa_extract.done = True
    ve.rpa_extract.ok = True
    ve.rpa_extract.msg = "/tmp/scene.webm"
    ve.rpa_extract.vpath = "movies/scene.webm"
    ve.poll_extract()
    assert ve.rpa_extract.in_progress is False
    assert created == [2.0]
    assert restarts == []


def test_extract_from_rpa_copies_vp(ve, monkeypatch):
    class FakeReader(object):
        def __init__(self):
            self._chunks = [b"abc", b"def"]

        def read(self, size):
            return self._chunks.pop(0) if self._chunks else b""

        def close(self):
            pass

    monkeypatch.setattr(_veditor.renpy, "file", lambda vp: FakeReader())
    ve._current = ve._ensure_state("movies/scene.webm")
    status, msg = ve.extract_from_rpa("movies/scene.webm")
    assert status == "ok"
    fpath = os.path.join(_config.gamedir, "movies", "scene.webm")
    assert os.path.isfile(fpath)
    with open(fpath, "rb") as f:
        assert f.read() == b"abcdef"


def test_extract_from_rpa_write_error_cleans_partial(ve, monkeypatch):
    real_open = open

    class FakeReader(object):
        def read(self, size):
            return b"partial"

        def close(self):
            pass

    def failing_open(path, mode):
        f = real_open(path, mode)  # create/truncate like the real open
        f.close()
        raise IOError("disk full")

    monkeypatch.setattr(_veditor.renpy, "file", lambda vp: FakeReader())
    monkeypatch.setattr("builtins.open", failing_open)
    ve._current = ve._ensure_state("movies/scene.webm")
    status, msg = ve.extract_from_rpa("movies/scene.webm")
    assert status == "error"
    fpath = os.path.join(_config.gamedir, "movies", "scene.webm")
    assert not os.path.exists(fpath)


# ==========================================================================
# Video VFX tab view -- tri-state tab selector (Speed / Intensity / Create).
# `active` stays derived: only the Create editor is "active".
# ==========================================================================


def test_editor_tab_defaults_to_speed(ve):
    assert ve.tab == "speed"
    assert ve.active is False


def test_editor_show_create_tab_activates(ve):
    ve.show_tab(CueVideoEditorTab.CREATE)
    assert ve.tab == "create"
    assert ve.active is True


def test_editor_show_intensity_selects_tab(ve):
    ve.show_tab(CueVideoEditorTab.INTENSITY)
    assert ve.tab == "intensity"
    assert ve.active is False


def test_editor_active_setter_sets_tab(ve):
    ve.active = True
    assert ve.tab == "create"
    ve.active = False
    assert ve.tab == "speed"


def test_editor_show_speed_tab_from_intensity(ve):
    ve.show_tab(CueVideoEditorTab.INTENSITY)
    ve.show_tab(CueVideoEditorTab.SPEED)
    assert ve.tab == "speed"
    assert ve.active is False
