# Type stub for cue_lib.audio.cue_sfx_pack
from typing import Any, Optional

from cue_lib.download import CueDownloader

CUE_SFX_PACK_URL: str

class CueSfxPackDownloader(object):
    state: str
    error: str
    progress: float
    _library: Any
    _audio_dir: str
    _dl: CueDownloader
    _thread: Optional[Any]
    _scanned: bool

    def __init__(self, library: Any, audio_dir: str) -> None: ...
    def download_sfx_pack(self) -> None: ...
    def _run(self) -> None: ...
    def _progress_cb(self, total: Optional[int], written: int) -> None: ...
    def poll_sfx_pack(self) -> None: ...
