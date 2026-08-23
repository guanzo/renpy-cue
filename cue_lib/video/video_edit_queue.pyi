# Type stub for cue_lib.video.video_edit_queue
from typing import Any, Optional

CUE_VE_MODE_NORMAL: int
CUE_VE_MODE_INTERPOLATE: int
CUE_VE_MODE_FAST_PREVIEW: int

class CueJobStatus:
    QUEUED: str
    ANALYZING: str
    ENCODING: str
    FINALIZING: str
    DONE: str
    ERROR: str

def _cue_swap_job(job: CueVideoJob) -> None: ...

class CueVideoJob:
    job_id: int
    vpath: str
    fspath_in: str
    fspath_tmp: str
    factor: float
    encode_mode: int
    remove_audio: bool
    fspath_out: Optional[str]
    status: str
    progress: float
    error_msg: str
    start_time: float
    end_time: float
    total_frames: float
    passlog: Optional[str]
    cancelled: bool
    proc: Optional[Any]
    _done: bool
    _ok: bool
    _resume_pass2: bool
    _needs_swap: bool
    _launched: bool
    _cmds: list
    _pass_idx: int
    _num_passes: int
    _log_path: str
    _progress_path: str
    _progress_offset: int
    _swapping: bool
    _swap_done: bool
    _swap_ok: bool
    _swap_error_msg: str

    def __init__(
        self,
        job_id: int,
        vpath: str,
        fspath_in: str,
        fspath_tmp: str,
        factor: float,
        encode_mode: int,
        fspath_out: Optional[str] = None,
        remove_audio: bool = True) -> None: ...
    def elapsed(self) -> float: ...
    def status_text(self) -> str: ...
    def filename(self) -> str: ...
    @property
    def speed_label(self) -> str: ...

class CueVideoEditQueue:
    _next_job_id: int

    # editor is CueVideoEditor; typed Any to keep the stub acyclic (the
    # editor module imports this queue, so importing the editor here would
    # be a stub-level circular import).
    def __init__(self, editor: Any) -> None: ...
    @property
    def processing(self) -> bool: ...
    @property
    def has_pending(self) -> bool: ...
    @property
    def current_job(self) -> Optional[CueVideoJob]: ...
    @property
    def jobs(self) -> list[CueVideoJob]: ...
    def enqueue(self, job: CueVideoJob) -> None: ...
    def poll(self) -> None: ...
    def retry(self, job_id: int) -> None: ...
    def cancel(self, job_id: int) -> None: ...
    def remove(self, job_id: int) -> None: ...
    def save_to_persistent(self) -> None: ...
    def load_from_persistent(self) -> None: ...
    def get_elapsed(self) -> float: ...
