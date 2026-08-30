# -*- coding: utf-8 -*-
# cue_lib/url_importer.py -- downloads a .zip from a user-supplied URL into
# the imports/ drop zone.  The network hop, URL policy, and redirect handling
# live in cue_lib/download.py (shared with the SFX-pack download); CueUrlImporter
# only owns the import flow: state, collision-safe naming, the worker thread,
# and kicking a scan.  It writes to a .tmp in imports/ and renames into place
# so the scan worker never sees a partial zip.  Pure logic (URL checks,
# formatters, naming) lives here or in util and is unit-testable; the network
# hop is injected for headless tests.

import os
import threading
import time

try:
    from urlparse import (  # pyright: ignore[reportMissingImports]
        urlparse as _urlparse,
    )
    from urllib import unquote as _url_unquote  # pyright: ignore[reportAttributeAccessIssue]
except ImportError:
    from urllib.parse import unquote as _url_unquote, urlparse as _urlparse

import renpy.python as _renpy_python

from cue_lib.download import _CueDownloadCancel, _CueDownloadError, _cue_stream_body, CueDownloader
from cue_lib.sharing.importer_io import _cue_sanitize_filename
from cue_lib.util import _cue_format_size, _cue_log, _cue_replace_file, _to_str

MYPY = False
if MYPY:
    from typing import Any, Optional


class CueUrlImporter(_renpy_python.NoRollback):
    """Downloads a .zip from a user-supplied URL into the imports/ drop zone.

    URL policy is enforced on the click; every redirect hop is re-validated
    (see CueDownloader); the body streams to a .tmp then renames into place
    and kicks a scan so the zip shows up immediately.  The download runs on a
    daemon thread and the screen polls is_downloading / download_done /
    download_total."""

    def __init__(self, importer, fetcher=None):
        # type: (Any, Any) -> None
        self._importer = importer
        self._dl = CueDownloader(fetcher=fetcher)  # network hop, injectable for tests
        self.url = ""
        self.is_downloading = False
        self.cancel_requested = False
        self.download_done = 0
        self.download_total = None  # type: Optional[int]
        self.download_started = 0.0
        self.download_label = ""
        self.download_error = ""
        self.download_status = ""
        self._thread = None  # type: Any

    # ------------------------------------------------------------------
    # screen-facing API
    # ------------------------------------------------------------------

    def clear_status(self):
        # type: () -> None
        self.download_error = ""
        self.download_status = ""

    def clear_url(self):
        # type: () -> None
        self.url = ""
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
        err = self._dl.check_url(url)
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
    # worker thread
    # ------------------------------------------------------------------

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

        def _progress(_total, written):
            self.download_done = written

        def _cancel():
            if self.cancel_requested:
                raise _CueDownloadCancel()

        _cue_stream_body(resp, tmp_path, cancel_cb=_cancel, progress_cb=_progress)

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
            final_url, resp = self._dl.resolve_redirects(url)
            final_name = self._dedupe_name(imports_dir, self._name_from_url(final_url))
            tmp_path = os.path.join(imports_dir, final_name + ".tmp")
            self._write_body(resp, tmp_path)
            resp.close()
            resp = None
            _cue_replace_file(tmp_path, os.path.join(imports_dir, final_name))
            self.download_status = "Downloaded {}. ({})".format(final_name, _cue_format_size(self.download_done))
            self.url = ""
            self._importer.scan()
        except _CueDownloadCancel:
            self.download_status = "Cancelled."
        except _CueDownloadError as e:
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
