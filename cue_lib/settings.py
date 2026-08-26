# -*- coding: utf-8 -*-
# CueSettings -- Settings-page state and actions: the Shared Dir input
# (text + error/success lines).
# Instantiated once at _cue.settings, lives on the NoRollback _cue object.

import os as _os
import renpy

from cue_lib.constants import CUE_SHARED_KEY_MUSIC_FOLDERS, CUE_SHARED_KEY_SFX_FOLDERS
from cue_lib.db import CueDatabase
from cue_lib.paths import CuePaths
from cue_lib.state import _cue
from cue_lib.util import _cue_log, _cue_ui_refresh

MYPY = False
if MYPY:
    from typing import Any, List, Tuple  # pyright: ignore[reportUnusedImport]


class CueSettings(object):
    """Settings-page state and actions.

    Owns the Shared Dir input and the external Music/SFX folder lists.
    Methods are callable via Function() from the settings screens."""

    def __init__(self):
        self.setup_dir_text = ""  # text bound to the Shared Dir input
        self.shared_dir_error = ""  # error line under the Shared Dir input
        self.shared_dir_success = ""  # success line under the Shared Dir input

        # External folder lists (Settings > Data Folder).  The *_folders lists
        # hold committed absolute paths (mirror of the shared-config lists the
        # trees consume); *_folder_drafts hold the live row text the inputs
        # bind to (components._CueFieldValue), so an uncommitted draft never
        # reaches config or the loader roots; *_folder_errors parallel the
        # drafts by index.
        self.music_folders = []  # type: List[str]
        self.sfx_folders = []  # type: List[str]
        self.music_folder_drafts = []  # type: List[str]
        self.sfx_folder_drafts = []  # type: List[str]
        self.music_folder_errors = []  # type: List[str]
        self.sfx_folder_errors = []  # type: List[str]

    def prepare_for_page(self):
        # type: () -> None
        """Reset the Settings-page fields when it opens.

        The Shared Dir field names the real data root -- never an import path
        the active overlay happens to serve.  Folder lists hydrate from the
        shared config; uncommitted row text is dropped (config is truth).
        """
        self.setup_dir_text = _cue.paths.original_root
        self.shared_dir_error = ""
        self.shared_dir_success = ""

        _config = _cue.db.load_shared_config()
        self.music_folders = list(_config.get(CUE_SHARED_KEY_MUSIC_FOLDERS, []) or [])
        self.sfx_folders = list(_config.get(CUE_SHARED_KEY_SFX_FOLDERS, []) or [])
        # Drafts start as a copy of the committed list so committed rows show
        # their canonical path; a row is re-validated on Enter.
        self.music_folder_drafts = list(self.music_folders)
        self.sfx_folder_drafts = list(self.sfx_folders)
        self.music_folder_errors = ["" for _ in self.music_folders]
        self.sfx_folder_errors = ["" for _ in self.sfx_folders]

    # ------------------------------------------------------------------
    # External folder lists -- add / commit / remove
    # ------------------------------------------------------------------

    @_cue_ui_refresh
    def _add_folder(self, kind):
        # type: (str) -> None
        """Append an empty folder row for a kind (committed by Enter)."""
        folders, drafts, errors = self._folder_lists(kind)
        folders.append("")
        drafts.append("")
        errors.append("")

    @_cue_ui_refresh
    def _commit_folder(self, kind, index):
        # type: (str, int) -> None
        """Validate + persist the kind's folders[index], then apply + rescan.

        On failure only the row's error line is set -- the raw text stays in
        the draft so the user can fix it without retyping.  Only rows the user
        validated are folded into `folders`, so a sibling's partial text never
        reaches config or the loader roots."""
        folders, drafts, errors = self._folder_lists(kind)
        key = CUE_SHARED_KEY_MUSIC_FOLDERS if kind == "music" else CUE_SHARED_KEY_SFX_FOLDERS
        builtin = self._builtin_dir(kind)

        text = (drafts[index] or "").strip()
        if not text:
            errors[index] = "Path cannot be empty."
            return
        path = _os.path.abspath(_os.path.normpath(_os.path.expanduser(text))).replace("\\", "/")
        if path == builtin:
            errors[index] = "That folder is already built in."
            return
        if not _os.path.isdir(path):
            errors[index] = "Folder not found."
            return
        # Dup check excludes the committing row itself (its current value is
        # the text being validated).
        _others = list(folders)
        _others[index] = ""
        if path in _others:
            errors[index] = "Folder already in the list."
            return
        folders[index] = path
        drafts[index] = path
        errors[index] = ""
        self._persist_folders(key, folders)
        self._apply(kind, folders)

    @_cue_ui_refresh
    def _remove_folder(self, kind, index):
        # type: (str, int) -> None
        """Remove the kind's folders[index], persist, then apply + rescan."""
        folders, drafts, errors = self._folder_lists(kind)
        folders.pop(index)
        drafts.pop(index)
        errors.pop(index)
        key = CUE_SHARED_KEY_MUSIC_FOLDERS if kind == "music" else CUE_SHARED_KEY_SFX_FOLDERS
        self._persist_folders(key, folders)
        self._apply(kind, folders)

    def _folder_lists(self, kind):
        # type: (str) -> Tuple[List[str], List[str], List[str]]
        """The three parallel folder lists for a kind (folders, drafts, errors)."""
        if kind == "music":
            return self.music_folders, self.music_folder_drafts, self.music_folder_errors
        return self.sfx_folders, self.sfx_folder_drafts, self.sfx_folder_errors

    # Public names bound by settings_page.rpy screen actions; thin dispatch to
    # the kind-parameterised helpers above.
    def add_music_folder(self):
        # type: () -> None
        self._add_folder("music")

    def add_sfx_folder(self):
        # type: () -> None
        self._add_folder("sfx")

    def commit_music_folder(self, index):
        # type: (int) -> None
        self._commit_folder("music", index)

    def commit_sfx_folder(self, index):
        # type: (int) -> None
        self._commit_folder("sfx", index)

    def remove_music_folder(self, index):
        # type: (int) -> None
        self._remove_folder("music", index)

    def remove_sfx_folder(self, index):
        # type: (int) -> None
        self._remove_folder("sfx", index)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _builtin_dir(self, kind):
        # type: (str) -> str
        """The always-on folder for a library kind, normalized like user input
        ("" if the paths graph lacks it -- unit-test graphs)."""
        _dir = getattr(_cue.paths, "music_dir" if kind == "music" else "audio_dir", "")
        if not _dir:
            return ""
        return _os.path.abspath(_os.path.normpath(_os.path.expanduser(_dir))).replace("\\", "/")

    def _persist_folders(self, key, folders):
        # type: (str, List[str]) -> None
        """Write the committed rows (drop empty placeholders) to shared config."""
        _cue.db.update_shared_config({key: [f for f in folders if f]})

    def _apply(self, kind, folders):
        # type: (str, List[str]) -> None
        """Fan out the committed rows (drop empty placeholders) to the runtime
        apply helper (rescan)."""
        from cue_lib import runtime

        _committed = [f for f in folders if f]
        if kind == "music":
            runtime._cue_apply_music_folders(_committed)
        else:
            runtime._cue_apply_sfx_folders(_committed)

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
