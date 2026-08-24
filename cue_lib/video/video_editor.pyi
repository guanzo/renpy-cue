# Type stub for cue_lib.video.video_editor
from typing import Optional

from cue_lib.video.ffmpeg import CueFFmpeg
from cue_lib.video.speed import CueVidSpeedResolver
from cue_lib.video.video import CueVideoManager
from cue_lib.paths import CuePaths
from cue_lib.state import CueContext
from cue_lib.video.video_edit_queue import CueVideoEditQueue

def _cue_extract_rpa(editor: "CueVideoEditor", vp: str) -> None: ...

class CueVideoEditorState:
    vpath: str
    factor_text: str
    last_error: str
    def __init__(self, vpath: str) -> None: ...

class CueRpaExtractState:
    in_progress: bool
    done: bool
    ok: bool
    msg: str
    vpath: Optional[str]
    def __init__(self) -> None: ...

class CueVideoEditorTab:
    SPEED: str
    INTENSITY: str
    CREATE: str

class CueVideoEditor:
    SPEED_MIN: float
    SPEED_MAX: float
    MODE_NORMAL: int
    MODE_INTERPOLATE: int
    MODE_FAST_PREVIEW: int

    active: bool
    tab: str
    encode_mode: int
    remove_audio: bool
    _current_has_audio: Optional[bool]
    rpa_extract: CueRpaExtractState
    job_queue: CueVideoEditQueue
    _ffmpeg: CueFFmpeg
    _speed_resolver: CueVidSpeedResolver
    _vid_manager: CueVideoManager
    _paths: CuePaths
    _ctx: CueContext

    def __init__(
        self,
        ctx: CueContext,
        ffmpeg: CueFFmpeg,
        speed_resolver: CueVidSpeedResolver,
        vid_manager: CueVideoManager,
        paths: CuePaths,
    ) -> None: ...
    @property
    def processing(self) -> bool: ...
    @property
    def factor_text(self) -> str: ...
    @factor_text.setter
    def factor_text(self, value: str) -> None: ...
    @property
    def last_error(self) -> str: ...
    @last_error.setter
    def last_error(self, value: str) -> None: ...
    def check_prerequisites(self) -> tuple[str, str]: ...
    def extract_from_rpa(self, vp: Optional[str] = None) -> tuple[str, str]: ...
    def _extract_then_create(self) -> None: ...
    def poll_extract(self) -> None: ...
    def set_quick(self, mult: float) -> None: ...
    def commit_text(self) -> None: ...
    def nudge(self, delta: float) -> None: ...
    def show_tab(self, tab: str) -> None: ...
    def toggle_remove_audio(self) -> None: ...
    def get_factor(self) -> float: ...
    def set_encode_mode(self, mode: int) -> None: ...
    def prepare_create(self) -> None: ...
    def create(self, factor: float) -> None: ...
    def refresh(self) -> None: ...
