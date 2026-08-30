# -*- coding: utf-8 -*-
# cue_lib/audio/cue_sfx_pack.py -- the curated-pack bootstrap for an empty SFX
# library.  CueSfxPackDownloader fetches+extracts the pack on a background
# thread and exposes a coarse UI state (idle/downloading/done/error); the
# empty-state screen polls poll_sfx_pack to finish -- "done" means the
# download AND extract succeeded, and the poll triggers a rescan (via the
# owning library) then returns to idle.  The network hop is the shared
# CueDownloader.

import os
import tempfile
import threading

import renpy.python as _renpy_python

from cue_lib.constants import CUE_SFX_FOLDER
from cue_lib.download import CueDownloader
from cue_lib.sharing.importer_io import _cue_extract_zip_to

MYPY = False
if MYPY:
    from typing import Any, Optional

# Curated SFX pack published with each release (README links the same URL).
# Deliberately versionless: releases/latest/download resolves to the latest
# published asset, never a draft (the release workflow uploads the pack before
# publishing).  Downloaded through the shared CueDownloader, which owns URL
# policy, redirects, and the connect timeout.
CUE_SFX_PACK_URL = "https://github.com/guanzo/renpy-cue/releases/latest/download/cue_sfx.zip"


class CueSfxPackDownloader(_renpy_python.NoRollback):
    """Downloads the curated SFX pack into the audio dir and reports the
    bootstrap state.  Holds the owning library so poll_sfx_pack can rescan
    after a successful extract; audio_dir is the extraction target."""

    def __init__(self, library, audio_dir):
        # type: (Any, str) -> None
        self._library = library
        self._audio_dir = audio_dir
        self._dl = CueDownloader()  # shared network layer for the pack fetch
        self.state = "idle"  # "idle" | "downloading" | "done" | "error"
        self.error = ""  # non-empty only when state == "error"
        self.progress = 0.0  # 0..1 while downloading
        self._thread = None  # type: Any
        self._scanned = False  # poll already finished a "done" state

    def download_sfx_pack(self):
        # type: () -> None
        """Start a background fetch+extract of the curated pack into the
        audio dir.  No-op while a download is already running."""
        if self.state == "downloading":
            return
        self.state = "downloading"
        self.error = ""
        self.progress = 0.0
        self._scanned = False
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()

    def _run(self):
        # type: () -> None
        """Background worker: download the pack to a temp file via the shared
        CueDownloader, extract it into the audio dir, then report the terminal
        state.  Makes no Ren'Py API calls; the UI thread finishes the work via
        poll_sfx_pack."""
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="cue_sfx_", suffix=".zip")
            os.close(fd)
            try:
                self._dl.download_to(CUE_SFX_PACK_URL, tmp_path, progress_cb=self._progress_cb)
                # The pack's categories sit at the top level; unwrap_root is a
                # no-op on the flat zip (and unwraps any legacy wrapped pack).
                _cue_extract_zip_to(tmp_path, self._audio_dir, unwrap_root=True)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            self.state = "done"
        except Exception as err:
            self.state = "error"
            self.error = str(err)

    def _progress_cb(self, total, written):
        # type: (Optional[int], int) -> None
        if total:
            self.progress = float(written) / float(total)

    def poll_sfx_pack(self):
        # type: () -> None
        """Finish a "done" fetch on the UI thread: rescan the library once,
        then return to idle.  A rescan failure surfaces as the error state."""
        if self.state != "done":
            return
        if self._scanned:
            return
        self._scanned = True
        try:
            self._library.scan()
            # Show the fetched content immediately: open the SFX root (its
            # subfolders stay collapsed).
            self._library.expand_folder(CUE_SFX_FOLDER)
        except Exception as err:
            self.state = "error"
            self.error = str(err)
            return
        self.state = "idle"
