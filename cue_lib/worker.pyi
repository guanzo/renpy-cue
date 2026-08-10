# Type stub for cue_lib.worker
from typing import Any

from cue_lib.ffmpeg import CueFFmpeg

def _cue_probe_job(
    ffmpeg: CueFFmpeg,
    job: Any,
    dur_ms: int,
    base_dir: str,
) -> None: ...
