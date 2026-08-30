# -*- coding: utf-8 -*-
# cue_lib/download.py -- the generic http(s) download layer: URL policy
# (http/https only, no credentials, public hosts only -- each redirect hop
# re-validated), manual redirect handling, and chunked streaming to a local
# path.  Owned by neither the url importer nor the SFX-pack download -- both
# delegate to CueDownloader.  The network hop and resolver are injectable for
# headless tests.

import socket

import renpy.python as _renpy_python

try:
    import ssl as _ssl
except ImportError:
    _ssl = None  # pre-2.7.9 Python; the HTTPS handler just uses defaults

try:
    from urllib2 import (  # pyright: ignore[reportMissingImports]
        HTTPError as _HTTPError,
        HTTPRedirectHandler as _HTTPRedirectHandler,
        HTTPSHandler as _HTTPSHandler,
        Request as _url_Request,
        URLError as _URLError,
        build_opener as _url_build_opener,
    )
    from urlparse import (  # pyright: ignore[reportMissingImports]
        urljoin as _urljoin,
        urlparse as _urlparse,
    )
except ImportError:
    from urllib.request import (
        HTTPError as _HTTPError,
        HTTPRedirectHandler as _HTTPRedirectHandler,
        HTTPSHandler as _HTTPSHandler,
        Request as _url_Request,
        build_opener as _url_build_opener,
    )
    from urllib.error import URLError as _URLError
    from urllib.parse import urljoin as _urljoin, urlparse as _urlparse

MYPY = False
if MYPY:
    from typing import Any, Callable, List, Optional, Tuple

    # Re-assert the py3 urllib types for pyright: the runtime shim's urllib2
    # branch (py2 only) leaves these Unknown to the checker.
    from urllib.request import HTTPRedirectHandler as _HTTPRedirectHandler
    from urllib.request import HTTPSHandler as _HTTPSHandler


CUE_DOWNLOAD_CONNECT_TIMEOUT = 30  # per-operation socket timeout (connect + block)
CUE_DOWNLOAD_CHUNK_SIZE = 65536
CUE_DOWNLOAD_MAX_REDIRECTS = 5
_CUE_REDIRECT_CODES = (301, 302, 303, 307, 308)

# CDNs (Discord's attachments host, etc.) reject urllib's default
# "Python-urllib" user agent with a 403, so every request carries a regular
# browser UA.
CUE_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _cue_find_cacert():
    # type: () -> Optional[str]
    """Path to a usable CA bundle (certifi's), or None when unavailable."""
    try:
        import certifi as _certifi  # pyright: ignore[reportMissingImports]  # optional runtime dep, not in the lint venv

        return _certifi.where()
    except ImportError:
        return None


def _cue_https_context():
    # type: () -> Any
    """An HTTPSHandler for _CUE_OPENER.  Ren'Py 8.x's bundled python has no
    default CA paths, so ssl.create_default_context() verifies nothing and
    every https download fails with CERTIFICATE_VERIFY_FAILED.  Prefer
    certifi's bundled CA store when present; fall back to unverified SSL so
    downloads still work (7.x's urllib2 never verified certs)."""
    if _ssl is None:
        return _HTTPSHandler()
    cacert = _cue_find_cacert()
    if cacert:
        try:
            return _HTTPSHandler(context=_ssl.create_default_context(cafile=cacert))
        except Exception:
            pass
    return _HTTPSHandler(context=_ssl._create_unverified_context())


class _CueDownloadError(Exception):
    """A user-facing download failure (policy, HTTP status, transport)."""

    pass


class _CueDownloadCancel(Exception):
    """Internal: the cancel flag was set mid-stream."""

    pass


class _CueNoRedirectHandler(_HTTPRedirectHandler):  # pyright: ignore[reportGeneralTypeIssues]  # base is Unknown via the py2 urllib2 shim
    """Bypass urllib's auto-follow so the downloader validates each hop itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_CUE_OPENER = _url_build_opener(_CueNoRedirectHandler(), _cue_https_context())
_CUE_OPENER.addheaders = [("User-Agent", CUE_DOWNLOAD_USER_AGENT)]


class _CueResponse(_renpy_python.NoRollback):
    """Normalizes a urllib response or HTTPError to a small contract:
    .code / .headers_get(name) / .read(size) / .close()."""

    def __init__(self, resp):
        self._resp = resp
        self.code = getattr(resp, "code", None)
        if self.code is None and hasattr(resp, "getcode"):
            try:
                self.code = resp.getcode()
            except Exception:
                pass

    def headers_get(self, name):
        return self._resp.headers.get(name)

    def read(self, size):
        return self._resp.read(size)

    def close(self):
        try:
            self._resp.close()
        except Exception:
            pass


def _cue_is_private_ip(ip):
    # type: (str) -> bool
    """True for loopback, private, link-local, and CGNAT ranges (v4 + common v6)."""
    low = str(ip).lower()
    if low == "::1" or low == "0:0:0:0:0:0:0:1":
        return True
    if low.startswith("fc") or low.startswith("fd"):  # fc00::/7
        return True
    if low.startswith(("fe8", "fe9", "fea", "feb")):  # fe80::/10
        return True
    parts = low.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    a = nums[0]
    b = nums[1]
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 169 and b == 254:
        return True
    if a == 100 and 64 <= b <= 127:
        return True
    if a == 127 or a == 0:
        return True
    return False


def _cue_stream_body(resp, dest_path, cancel_cb=None, progress_cb=None):
    # type: (Any, str, Optional[Callable[[], None]], Optional[Callable[[Optional[int], int], None]]) -> Tuple[Optional[int], int]
    """Stream an open response body to dest_path in chunks.

    Shared by the url-import download and the SFX-pack download.  cancel_cb
    runs before each chunk and may raise to abort; progress_cb(total, written)
    runs after each chunk with the maybe-unknown Content-Length so callers can
    count bytes even without a total.  Returns (total, written); total is None
    when the length is unknown."""
    total = None
    try:
        raw = resp.headers_get("Content-Length")
        total = int(raw) if raw else None
    except (TypeError, ValueError):
        total = None
    written = 0
    with open(dest_path, "wb") as f:
        while True:
            if cancel_cb is not None:
                cancel_cb()
            chunk = resp.read(CUE_DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
            if progress_cb is not None:
                progress_cb(total, written)
    return total, written


class CueDownloader(_renpy_python.NoRollback):
    """Fetch a URL to a local path: http/https policy, per-hop redirect
    validation, chunked stream.  Shared by CueUrlImporter (user-supplied
    import URLs) and the SFX-pack download.  The network hop and resolver are
    injectable for headless tests."""

    def __init__(self, fetcher=None):
        # type: (Any) -> None
        self._fetcher = fetcher  # tests: fetcher(url, timeout)

    # ------------------------------------------------------------------
    # URL policy
    # ------------------------------------------------------------------

    def _resolve(self, host):
        # type: (str) -> Any
        """Injectable for tests; the real lookup is socket.getaddrinfo."""
        return socket.getaddrinfo(host, None)

    def _resolve_ips(self, host):
        # type: (str) -> List[str]
        """Resolved address strings for a host; [] if it can't be resolved
        (the open then fails with a friendly message)."""
        ips = []
        try:
            for info in self._resolve(host):
                sockaddr = info[4]
                if sockaddr and sockaddr[0]:
                    ips.append(sockaddr[0])
        except Exception:
            pass
        return ips

    def check_url(self, url):
        # type: (str) -> Optional[str]
        """Return an error string for a URL that violates URL policy, else
        None.  Cheap syntax checks first; the host is then resolved and each
        address checked against private ranges."""
        parts = _urlparse(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            return "Only http/https URLs are supported."
        if parts.username is not None or parts.password is not None:
            return "URLs with embedded credentials are not allowed."
        host = parts.hostname
        if not host:
            return "URL has no host."
        if _cue_is_private_ip(host):
            return "That address is not reachable from the internet."
        for ip in self._resolve_ips(host):
            if _cue_is_private_ip(ip):
                return "That address is not reachable from the internet."
        return None

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    def _open(self, url, timeout, headers=None):
        # type: (str, float, Any) -> Any
        """Fetch url without following redirects.  Returns a response for 2xx
        and 3xx; raises _CueDownloadError for transport failures.  The injected
        fetcher (tests) bypasses the network entirely.  headers (dict) is sent
        on the request -- callers use it for conditional GETs (If-Modified-Since)."""
        if self._fetcher is not None:
            if headers is None:
                return self._fetcher(url, timeout)
            return self._fetcher(url, timeout, headers)
        try:
            if headers is None:
                return _CueResponse(_CUE_OPENER.open(url, timeout=timeout))
            req = _url_Request(url, headers=headers)
            return _CueResponse(_CUE_OPENER.open(req, timeout=timeout))
        except _HTTPError as e:
            return _CueResponse(e)
        except _URLError as e:
            reason = getattr(e, "reason", e)
            raise _CueDownloadError("Could not reach URL: {}.".format(reason))

    def resolve_redirects(self, url, headers=None):
        # type: (str, Any) -> Tuple[str, Any]
        """Follow redirects manually (each hop re-validated) until a non-3xx
        response, then return (final_url, open_response).  headers (dict) is
        re-sent on every hop so a conditional GET survives to the final CDN."""
        current = url
        resp = None
        for _hop in range(CUE_DOWNLOAD_MAX_REDIRECTS + 1):
            err = self.check_url(current)
            if err:
                if resp is not None:
                    resp.close()
                raise _CueDownloadError(err)
            resp = self._open(current, CUE_DOWNLOAD_CONNECT_TIMEOUT, headers)
            if resp.code in _CUE_REDIRECT_CODES:
                location = resp.headers_get("Location")
                resp.close()
                resp = None
                if not location:
                    raise _CueDownloadError("Redirect response had no Location header.")
                current = _urljoin(current, location)
                continue
            if resp.code is not None and resp.code >= 400:
                resp.close()
                raise _CueDownloadError("Server returned HTTP {}.".format(resp.code))
            return current, resp
        if resp is not None:
            resp.close()
        raise _CueDownloadError("Too many redirects.")

    def download_to(self, url, dest_path, progress_cb=None, headers=None):
        # type: (str, str, Optional[Callable[[Optional[int], int], None]], Any) -> int
        """Synchronous download of url to dest_path: policy check, per-hop
        redirect validation, chunked stream.  progress_cb(total, written)
        fires after each chunk when Content-Length is known.  headers (dict)
        is sent on the request; when the server answers 304 (conditional GET:
        content unchanged), nothing is written and 0 is returned.  Returns
        bytes written; raises _CueDownloadError on policy/HTTP/transport failure."""
        resp = None
        try:
            _final_url, resp = self.resolve_redirects(url, headers)
            if resp.code == 304:
                return 0
            _total, written = _cue_stream_body(resp, dest_path, progress_cb=progress_cb)
            return written
        finally:
            if resp is not None:
                resp.close()
