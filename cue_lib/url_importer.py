# -*- coding: utf-8 -*-
# cue_lib/url_importer.py -- downloads a .zip from a user-supplied URL into
# the imports/ drop zone.
#
# CueUrlImporter owns URL policy (http/https only, no credentials, public
# hosts only -- each redirect hop re-validated), the chunked background
# download with a cancel flag, and collision-safe naming.  It writes to a
# .tmp in imports/ and renames into place so the scan worker never sees a
# partial zip.  Pure logic (URL checks, formatters, naming) lives here or in
# util and is unit-testable; the network hop is injected for headless tests.

import os
import socket
import threading
import time

try:
    import ssl as _ssl
except ImportError:
    _ssl = None   # pre-2.7.9 Python; the HTTPS handler just uses defaults

try:
    from urllib2 import (  # pyright: ignore[reportMissingImports]
        HTTPError as _HTTPError,
        HTTPRedirectHandler as _HTTPRedirectHandler,
        HTTPSHandler as _HTTPSHandler,
        URLError as _URLError,
        build_opener as _url_build_opener,
    )
    from urlparse import (  # pyright: ignore[reportMissingImports]
        urljoin as _urljoin,
        urlparse as _urlparse,
    )
    from urllib import unquote as _url_unquote  # pyright: ignore[reportAttributeAccessIssue]
except ImportError:
    from urllib.request import (
        HTTPError as _HTTPError,
        HTTPRedirectHandler as _HTTPRedirectHandler,
        HTTPSHandler as _HTTPSHandler,
        build_opener as _url_build_opener,
    )
    from urllib.error import URLError as _URLError
    from urllib.parse import urljoin as _urljoin, unquote as _url_unquote, urlparse as _urlparse

from cue_lib.importer_io import _cue_sanitize_filename
from cue_lib.util import (
    _cue_format_size,
    _cue_log,
    _cue_replace_file,
    _to_str,
)

MYPY = False
if MYPY:
    from typing import Any, List, Optional, Tuple
    # Re-assert the py3 urllib types for pyright: the runtime shim's urllib2
    # branch (py2 only) leaves these Unknown to the checker.
    from urllib.request import HTTPRedirectHandler as _HTTPRedirectHandler
    from urllib.request import HTTPSHandler as _HTTPSHandler


CUE_URL_CONNECT_TIMEOUT = 30   # per-operation socket timeout (connect + block)
CUE_URL_CHUNK_SIZE = 65536
CUE_URL_MAX_REDIRECTS = 5
_CUE_REDIRECT_CODES = (301, 302, 303, 307, 308)

# CDNs (Discord's attachments host, etc.) reject urllib's default
# "Python-urllib" user agent with a 403, so every request carries a regular
# browser UA.
CUE_URL_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36")


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


class _CueUrlError(Exception):
    """A user-facing download failure (policy, HTTP status, transport)."""
    pass


class _CueUrlCancel(Exception):
    """Internal: the cancel flag was set mid-stream."""
    pass


class _CueNoRedirectHandler(_HTTPRedirectHandler):  # pyright: ignore[reportGeneralTypeIssues]  # base is Unknown via the py2 urllib2 shim
    """Bypass urllib's auto-follow so the manager validates each hop itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_CUE_OPENER = _url_build_opener(_CueNoRedirectHandler(), _cue_https_context())
_CUE_OPENER.addheaders = [("User-Agent", CUE_URL_USER_AGENT)]


class _CueResponse(object):
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
    if low.startswith("fc") or low.startswith("fd"):   # fc00::/7
        return True
    if low.startswith(("fe8", "fe9", "fea", "feb")):   # fe80::/10
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


class CueUrlImporter(object):
    """Downloads a .zip from a user-supplied URL into the imports/ drop zone.

    URL policy is enforced on the click; every redirect hop is re-validated;
    the body streams to a .tmp then renames into place and kicks a scan so
    the zip shows up immediately.  The download runs on a daemon thread and
    the screen polls is_downloading / download_done / download_total."""

    def __init__(self, importer, fetcher=None):
        # type: (Any, Any) -> None
        self._importer = importer
        self._fetcher = fetcher     # injectable for tests: fetcher(url, timeout)
        self.url = u""
        self.is_downloading = False
        self.cancel_requested = False
        self.download_done = 0
        self.download_total = None   # type: Optional[int]
        self.download_started = 0.0
        self.download_label = ""
        self.download_error = ""
        self.download_status = ""
        self._thread = None   # type: Any

    # ------------------------------------------------------------------
    # screen-facing API
    # ------------------------------------------------------------------

    def clear_status(self):
        # type: () -> None
        self.download_error = ""
        self.download_status = ""

    def clear_url(self):
        # type: () -> None
        self.url = u""
        self.download_error = ""
        self.download_status = ""

    def download_duration(self):
        # type: () -> float
        """Elapsed seconds of the active download, for the progress line."""
        if not self.is_downloading:
            return 0.0
        return max(0.0, time.time() - self.download_started)

    def import_url(self):
        # type: () -> None
        """Validate the URL field and kick a background download.  Validation
        failures are synchronous (the button click's interaction restart
        renders them); only the network read happens off-thread."""
        if self.is_downloading:
            return
        self.clear_status()
        url = self.url.strip()
        if not url:
            self.download_error = "Enter a URL first."
            return
        err = self._check_url(url)
        if err:
            self.download_error = err
            return
        self.cancel_requested = False
        self.download_done = 0
        self.download_total = None
        self.download_label = self._name_from_url(url)
        self.download_started = time.time()
        self.is_downloading = True
        thread = threading.Thread(target=self._worker, args=(url,))
        thread.daemon = True
        self._thread = thread
        thread.start()

    def cancel(self):
        # type: () -> None
        """Request the worker stop at the next chunk boundary."""
        if self.is_downloading:
            self.cancel_requested = True

    # ------------------------------------------------------------------
    # URL policy
    # ------------------------------------------------------------------

    def _check_url(self, url):
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

    def _resolve(self, host):
        # type: (str) -> Any
        """Injectable for tests; the real lookup is socket.getaddrinfo."""
        return socket.getaddrinfo(host, None)

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    def _open(self, url, timeout):
        # type: (str, float) -> Any
        """Fetch url without following redirects.  Returns a response for 2xx
        and 3xx; raises _CueUrlError for transport failures.  The injected
        fetcher (tests) bypasses the network entirely."""
        if self._fetcher is not None:
            return self._fetcher(url, timeout)
        try:
            return _CueResponse(_CUE_OPENER.open(url, timeout=timeout))
        except _HTTPError as e:
            return _CueResponse(e)
        except _URLError as e:
            reason = getattr(e, "reason", e)
            raise _CueUrlError("Could not reach URL: {}.".format(reason))

    def _resolve_redirects(self, url):
        # type: (str) -> Tuple[str, Any]
        """Follow redirects manually (each hop re-validated) until a non-3xx
        response, then return (final_url, open_response)."""
        current = url
        resp = None
        for _hop in range(CUE_URL_MAX_REDIRECTS + 1):
            err = self._check_url(current)
            if err:
                if resp is not None:
                    resp.close()
                raise _CueUrlError(err)
            resp = self._open(current, CUE_URL_CONNECT_TIMEOUT)
            if resp.code in _CUE_REDIRECT_CODES:
                location = resp.headers_get("Location")
                resp.close()
                resp = None
                if not location:
                    raise _CueUrlError("Redirect response had no Location header.")
                current = _urljoin(current, location)
                continue
            if resp.code is not None and resp.code >= 400:
                resp.close()
                raise _CueUrlError("Server returned HTTP {}.".format(resp.code))
            return current, resp
        if resp is not None:
            resp.close()
        raise _CueUrlError("Too many redirects.")

    def _write_body(self, resp, tmp_path):
        # type: (Any, str) -> None
        """Stream the open response body to tmp_path in chunks, updating
        download_total/download_done and checking the cancel flag between
        chunks."""
        total = resp.headers_get("Content-Length")
        try:
            self.download_total = int(total) if total else None
        except (TypeError, ValueError):
            self.download_total = None
        self.download_done = 0
        with open(tmp_path, "wb") as f:
            while True:
                if self.cancel_requested:
                    raise _CueUrlCancel()
                chunk = resp.read(CUE_URL_CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                self.download_done += len(chunk)

    # ------------------------------------------------------------------
    # worker thread
    # ------------------------------------------------------------------

    def _worker(self, url):
        # type: (str) -> None
        """Background download: resolve redirects, stream to a .tmp in
        imports/, rename into place, then kick a scan so the zip shows up."""
        imports_dir = self._importer.imports_dir()
        if not os.path.isdir(imports_dir):
            os.makedirs(imports_dir)
        tmp_path = None
        resp = None
        try:
            final_url, resp = self._resolve_redirects(url)
            final_name = self._dedupe_name(
                imports_dir, self._name_from_url(final_url))
            tmp_path = os.path.join(imports_dir, final_name + ".tmp")
            self._write_body(resp, tmp_path)
            resp.close()
            resp = None
            _cue_replace_file(tmp_path, os.path.join(imports_dir, final_name))
            self.download_status = "Downloaded {}. ({})".format(
                final_name, _cue_format_size(self.download_done))
            self.url = u""
            self._importer.scan()
        except _CueUrlCancel:
            self.download_status = "Cancelled."
        except _CueUrlError as e:
            self.download_error = str(e)
        except Exception as e:
            _cue_log("URL: download failed: {}".format(e))
            self.download_error = "Download failed: {}.".format(e)
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            self.is_downloading = False

    # ------------------------------------------------------------------
    # naming
    # ------------------------------------------------------------------

    def _name_from_url(self, url):
        # type: (str) -> str
        """A sanitized .zip filename derived from the URL's last path segment.
        A name without a .zip extension gets one so the file is visible to the
        import scanner (a non-zip then surfaces an extraction error row rather
        than sitting invisible)."""
        parts = _urlparse(url)
        path = parts.path or ""
        base = _to_str(os.path.basename(path.rstrip("/")))
        safe = _cue_sanitize_filename(_url_unquote(base))
        if not safe.lower().endswith(".zip"):
            safe += ".zip"
        return safe

    def _dedupe_name(self, imports_dir, name):
        # type: (str, str) -> str
        """Collision-safe final name: 'pack.zip' -> 'pack (2).zip', matching
        the export side's suffix convention."""
        if not os.path.exists(os.path.join(imports_dir, name)):
            return name
        base, ext = os.path.splitext(name)
        suffix = 2
        while True:
            if ext:
                cand = "{} ({}){}".format(base, suffix, ext)
            else:
                cand = "{} ({})".format(base, suffix)
            if not os.path.exists(os.path.join(imports_dir, cand)):
                return cand
            suffix += 1
