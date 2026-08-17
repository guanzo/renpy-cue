# Type stub for cue_lib.video.ffmpeg
from typing import Any, Dict, List, Optional, Tuple

CREATIONFLAGS: int


class CueSubprocessTimeout(Exception): ...


def _cue_run_proc(p: Any, timeout: Optional[float] = ...) -> Tuple[bytes, bytes]: ...
def _cue_wait_proc(p: Any, timeout: Optional[float] = ...) -> Optional[int]: ...


def _cue_probe_job(
    ffmpeg: CueFFmpeg,
    job: Any,
    dur_ms: int,
    base_dir: str,
) -> None: ...

class CueFFmpeg:
    VIDEO_ENCODERS: Dict[str, List[str]]
    AUDIO_ENCODERS: Dict[str, List[str]]
    _ffmpeg_cache: int

    def __init__(self) -> None: ...
    def ffmpeg_available(self) -> bool: ...
    def ffprobe_available(self) -> bool: ...
    def load_encoders(self) -> None: ...
    def pick_encoder(self, codec_name: str, category: str) -> Optional[str]: ...
    def probe_codecs(self, fspath: str) -> Tuple[str, str]: ...
    def probe_has_audio(self, fspath: str) -> bool: ...
    def probe_fps(self, fspath: str) -> int: ...
    def probe_bitrate(self, fspath: str) -> Optional[str]: ...

    @staticmethod
    def build_atempo(speed: float) -> List[str]: ...

    def build_ffmpeg_cmds(
        self,
        fspath: str,
        temp_path: str,
        speed: float,
        vcodec: str,
        acodec: str,
        has_audio: bool,
        target_bitrate: Optional[str],
        interpolate: bool = False,
        source_fps: int = 30,
        fast: bool = False,
        progress_path: Optional[str] = None,
    ) -> Tuple[List[List[str]], Optional[str]]: ...
