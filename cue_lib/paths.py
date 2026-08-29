# -*- coding: utf-8 -*-
# cue_lib/paths.py -- single owner of every directory path in the shared
# data tree.  Instances are built from an explicit root + game_id so the live
# path set (_cue.paths) and the throwaway Settings-page probe db (arbitrary
# root) share the same layout rules.
#
# Nothing else in cue_lib derives these paths -- audio_dir/music_dir no longer
# live on Cue, and CueDatabase no longer computes its own dirs.  Ask _cue.paths
# (or the db's own CuePaths) for "where does X live".

import os
import sys

import renpy.config as _config

from cue_lib.constants import CUE_MANUAL_BACKUP_NAME, CUE_SHARED_CONFIG_FILENAME

MYPY = False
if MYPY:
    from typing import Any, List  # pyright: ignore[reportUnusedImport]

# The mod's folder name -- both the in-game base dir under gamedir (debug
# logs, ffmpeg progress/log, icons) and the platform default dir under
# APPDATA/etc.  One identity, one name.
CUE_MOD_DIRNAME = "renpy_cue"

# Pointer file inside the platform-default shared dir that redirects to the
# user-chosen shared dir.  The default dir is the one anchor every game on
# the same OS user computes identically, so the choice applies to all games.
# In-game choice wins over the RENPY_CUE_DIR env var.
CUE_DIR_OVERRIDE_FILENAME = "dir.txt"

# Backup tree under the shared root.  Automatic backups live in
# {shared}/backups/auto/auto_backup_<ts>.zip; the single manual backup is
# {shared}/backups/renpy_cue_backup.zip.
CUE_BACKUP_DIR = "backups"
CUE_BACKUP_AUTO_DIR = "auto"


class CuePaths(object):
    """Directory layout for the shared data tree.

    Everything the mod persists or browses lives under one root (the shared
    dir) in two families:

      - user media:  audio/ and music/ -- where users drop SFX and music files
      - internal data: data/... and video/{game_id}/... -- markers, presets,
        shared config, and speed-variant videos (namespaced by game_id)

    Locating the root is also class's job: resolve_root() figures out where
    the shared dir is (pointer file, then RENPY_CUE_DIR, then the platform
    default), and save_root() persists the user's choice.  Instances are
    built from an explicit root so the throwaway Settings-page probe can
    construct CuePaths for an arbitrary candidate path without touching
    root resolution.
    """

    def __init__(self, root, game_id):
        # type: (str, str) -> None
        self._original_root = root
        self._game_id = game_id
        # Set while an import is active; every serving dir then resolves
        # against the import instead of the live data tree.
        self._active_root = None
        # User's external Music/SFX folder lists (Settings > Data Folder).
        # Fed by runtime._cue_apply_* / boot hydration; the loader patch must
        # serve them or external playback fails.
        self._extra_loader_roots = []  # type: List[str]

    @property
    def root(self):
        # type: () -> str
        """Effective root: the active import if one is active, else
        the original data root."""
        return self._active_root if self._active_root is not None else self._original_root

    @property
    def original_root(self):
        # type: () -> str
        """The original data root, never the active import.  Used for
        imports/exports dirs, the Settings shared-dir field, and anywhere a
        path must stay on the user's real data."""
        return self._original_root

    @property
    def game_id(self):
        # type: () -> str
        return self._game_id

    # ------------------------------------------------------------------
    # In-game base dir -- the mod's folder inside the game directory
    # (gamedir).  Debug logs, ffmpeg progress/log, and icon images live
    # under this name.  Not part of the shared data tree.
    # ------------------------------------------------------------------

    @property
    def in_game_base_dir(self):
        # type: () -> str
        return CUE_MOD_DIRNAME

    def icon(self, filename):
        # type: (str) -> str
        return self.in_game_base_dir + "/cue_lib/images/icons/" + filename

    # ------------------------------------------------------------------
    # Loader ownership -- which absolute paths the loader patch may claim.
    # Only files under the shared tree or the in-game base dir belong to
    # the mod; every other path is left to Ren'Py.
    # ------------------------------------------------------------------

    def _loader_roots(self):
        # type: () -> list
        roots = [self.root, self.original_root, os.path.join(_config.gamedir, CUE_MOD_DIRNAME)]
        roots += self._extra_loader_roots
        return list({os.path.abspath(r).replace("\\", "/") for r in roots})

    def set_extra_loader_roots(self, folders):
        # type: (List[str]) -> None
        """Replace the external Music/SFX folder roots the loader may serve.

        Called by runtime on settings changes and at boot hydration."""
        self._extra_loader_roots = [r.replace("\\", "/") for r in (folders or [])]

    def _loader_owns(self, name):
        # type: (str) -> bool
        """True if an absolute path lives under one of the mod's data
        roots.  Relative or foreign paths are never the mod's."""
        if not os.path.isabs(name):
            return False
        n = os.path.normpath(name).replace("\\", "/")
        for root in self._loader_roots():
            if n == root or n.startswith(root + "/"):
                return True
        return False

    # ------------------------------------------------------------------
    # Root resolution -- "where IS the shared dir?" (class-level: no game
    # instance needed).  The pointer file lives in the platform-default dir
    # so every game on the machine finds the same user-chosen root.
    # ------------------------------------------------------------------

    @classmethod
    def platform_shared_dir(cls):
        # type: () -> str
        """Platform-standard default for the shared data directory.

        Windows : %APPDATA%/renpy_cue
        macOS   : ~/Library/Application Support/renpy_cue
        Linux   : $XDG_DATA_HOME/renpy_cue or ~/.local/share/renpy_cue
        """
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", "")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return os.path.normpath(os.path.join(base, CUE_MOD_DIRNAME)).replace("\\", "/")

    @classmethod
    def resolve_root(cls):
        # type: () -> str
        """Resolved shared directory root for cue data.

        Priority:
          1. Pointer file {platform_shared_dir()}/dir.txt -- the user's
             in-game choice, written by the Settings page.  Lives in the
             platform-default dir so every game finds the same choice.
          2. RENPY_CUE_DIR environment override.
          3. Platform default (see platform_shared_dir).
        """
        ptr_path = os.path.join(cls.platform_shared_dir(), CUE_DIR_OVERRIDE_FILENAME)
        try:
            if os.path.isfile(ptr_path):
                with open(ptr_path, "r") as _f:
                    _ptr = _f.read().strip()
                if _ptr:
                    return os.path.normpath(_ptr).replace("\\", "/")
        except Exception:
            pass  # Unreadable pointer -- fall through to env / default.

        env = os.environ.get("RENPY_CUE_DIR", "")
        if env:
            return os.path.normpath(env)
        return cls.platform_shared_dir()

    @classmethod
    def save_root(cls, path):
        # type: (str) -> None
        """Persist the user-chosen shared dir as a pointer file in the
        platform-default dir (the well-known anchor all games can find).
        Saving the platform default removes the pointer (clean reset).
        Raises OSError on failure -- the caller shows the error.
        """
        default_dir = cls.platform_shared_dir()
        ptr_path = os.path.join(default_dir, CUE_DIR_OVERRIDE_FILENAME)
        if path == default_dir:
            if os.path.isfile(ptr_path):
                os.remove(ptr_path)
            return
        if not os.path.isdir(default_dir):
            os.makedirs(default_dir)
        with open(ptr_path, "w") as _f:
            _f.write(path)

    # ------------------------------------------------------------------
    # User media folders -- files the user drops in
    # ------------------------------------------------------------------

    @property
    def audio_dir(self):
        # type: () -> str
        return self.root + "/audio/"

    @property
    def music_dir(self):
        # type: () -> str
        return self.root + "/music/"

    # ------------------------------------------------------------------
    # Internal data tree
    # ------------------------------------------------------------------

    @property
    def marker_dir(self):
        # type: () -> str
        return os.path.join(self.root, "data", "markers", self._game_id) + "/"

    @property
    def music_trigger_dir(self):
        # type: () -> str
        return os.path.join(self.marker_dir, "music_triggers") + "/"

    def music_trigger_path(self, replay_id):
        # type: (str) -> str
        return os.path.join(self.music_trigger_dir, replay_id + ".json")

    @property
    def replay_dir(self):
        # type: (str) -> str
        return os.path.join(self.marker_dir, "replays") + "/"

    def replay_path(self, replay_id):
        # type: (str) -> str
        return os.path.join(self.replay_dir, replay_id + ".json")

    @property
    def presets_dir(self):
        # type: () -> str
        return os.path.join(self.root, "data", "presets") + "/"

    @property
    def audio_preset_dir(self):
        # type: () -> str
        return os.path.join(self.presets_dir, "audio") + "/"

    @property
    def video_preset_dir(self):
        # type: () -> str
        return os.path.join(self.presets_dir, "video") + "/"

    @property
    def music_preset_dir(self):
        # type: () -> str
        return os.path.join(self.presets_dir, "music") + "/"

    @property
    def intensity_preset_dir(self):
        # type: () -> str
        return os.path.join(self.presets_dir, "intensity") + "/"

    @property
    def video_dir(self):
        # type: () -> str
        return os.path.join(self.root, "video", self._game_id).replace("\\", "/") + "/"

    @property
    def shared_config_path(self):
        # type: () -> str
        return os.path.join(self._original_root, "data", CUE_SHARED_CONFIG_FILENAME)

    # ------------------------------------------------------------------
    # Exchange tree -- {root}/exports/ and {root}/imports/.  Sharing zips are
    # written to and dropped into these.  Use _original_root (never the active
    # import) -- exports/imports are user-visible files on the live shared
    # tree, like backups.
    # ------------------------------------------------------------------

    @property
    def exports_dir(self):
        # type: () -> str
        return os.path.join(self._original_root, "exports")

    @property
    def imports_dir(self):
        # type: () -> str
        return os.path.join(self._original_root, "imports")

    # ------------------------------------------------------------------
    # Backup tree -- {root}/backups/.  Automatic backups live under
    # auto/; the manual backup is a single named zip at the root.  These
    # use _original_root (never the active import) -- backups are real user data
    # and must stay on the live shared tree, like shared_config_path.
    # ------------------------------------------------------------------

    @property
    def backups_dir(self):
        # type: () -> str
        return os.path.join(self._original_root, CUE_BACKUP_DIR)

    @property
    def auto_backups_dir(self):
        # type: () -> str
        return os.path.join(self.backups_dir, CUE_BACKUP_AUTO_DIR)

    @property
    def manual_backup_path(self):
        # type: () -> str
        return os.path.join(self.backups_dir, CUE_MANUAL_BACKUP_NAME)
