# -*- coding: utf-8 -*-
# CueSettings -- Settings-page state and actions: the Shared Dir input
# (text + error/success lines).
# Instantiated once at _cue.settings, lives on the NoRollback _cue object.

import os as _os
import renpy

from cue_lib.db import CueDatabase
from cue_lib.paths import CuePaths
from cue_lib.state import _cue
from cue_lib.util import _cue_log, _cue_ui_refresh

MYPY = False
if MYPY:
    from typing import Any  # pyright: ignore[reportUnusedImport]


class CueSettings(object):
    """Settings-page state and actions.

    Owns the Shared Dir input.  Methods are callable via Function() from the
    settings screens."""

    def __init__(self):
        self.setup_dir_text = ""  # text bound to the Shared Dir input
        self.shared_dir_error = ""  # error line under the Shared Dir input
        self.shared_dir_success = ""  # success line under the Shared Dir input

    def prepare_for_page(self):
        # type: () -> None
        """Reset the Shared Dir fields when the Settings page opens.

        The field names the real data root -- never an import path the
        active overlay happens to serve.
        """
        self.setup_dir_text = _cue.paths.original_root
        self.shared_dir_error = ""
        self.shared_dir_success = ""

    @_cue_ui_refresh
    def confirm_shared_dir(self):
        # type: () -> None
        """Validate and persist the Shared Dir input.

        The dir is created up front (throwaway CueDatabase) so uncreatable
        paths fail here instead of at next launch; the live db is untouched --
        the new dir takes effect after restart.  The choice is written as a
        pointer file in the platform-default dir, so all games on this machine
        pick it up.
        """
        self.shared_dir_success = ""

        text = (self.setup_dir_text or "").strip()
        if not text:
            self.shared_dir_error = "Path cannot be empty."
            return
        path = _os.path.abspath(_os.path.normpath(_os.path.expanduser(text))).replace("\\", "/")

        try:
            probe_db = CueDatabase(CuePaths(path, getattr(renpy.config, "save_directory")))
            probe_db.open()
        except Exception as exc:
            self.shared_dir_error = "Could not create that directory."
            _cue_log("SHARED-DIR: open failed for {}: {}".format(path, exc))
            return

        try:
            CuePaths.save_root(path)
        except Exception as exc:
            self.shared_dir_error = "Could not save the directory setting."
            _cue_log("SHARED-DIR: pointer write failed for {}: {}".format(path, exc))
            return

        self.shared_dir_error = ""
        self.setup_dir_text = path
        self.shared_dir_success = "Success. If you have any data in the old dir, move it to the new dir and relaunch."
