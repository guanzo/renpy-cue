# Type stub for cue_lib.worker
from typing import Any, Callable

from cue_lib.ffmpeg import CueFFmpeg

def _cue_run_encode(
    ffmpeg: CueFFmpeg,
    job: Any,
    dur_ms: int,
    base_dir: str,
    kill_fn: Callable[[], None],
) -> None: ...
