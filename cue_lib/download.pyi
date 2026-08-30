# Type stub for cue_lib.download
from typing import Any, Callable, List, Optional, Tuple

CUE_DOWNLOAD_CONNECT_TIMEOUT: int
CUE_DOWNLOAD_CHUNK_SIZE: int
CUE_DOWNLOAD_MAX_REDIRECTS: int
CUE_DOWNLOAD_USER_AGENT: str

def _cue_find_cacert() -> Optional[str]: ...
def _cue_https_context() -> Any: ...
def _cue_is_private_ip(ip: str) -> bool: ...
def _cue_stream_body(
    resp: Any,
    dest_path: str,
    cancel_cb: Optional[Callable[[], None]] = None,
    progress_cb: Optional[Callable[[Optional[int], int], None]] = None,
) -> Tuple[Optional[int], int]: ...

class _CueDownloadError(Exception):
    pass

class _CueDownloadCancel(Exception):
    pass

class CueDownloader(object):
    _fetcher: Any

    def __init__(self, fetcher: Any = None) -> None: ...
    def _resolve(self, host: str) -> Any: ...
    def _resolve_ips(self, host: str) -> List[str]: ...
    def check_url(self, url: str) -> Optional[str]: ...
    def _open(self, url: str, timeout: float, headers: Any = None) -> Any: ...
    def resolve_redirects(self, url: str, headers: Any = None) -> Tuple[str, Any]: ...
    def download_to(
        self,
        url: str,
        dest_path: str,
        progress_cb: Optional[Callable[[Optional[int], int], None]] = None,
        headers: Any = None,
    ) -> int: ...
