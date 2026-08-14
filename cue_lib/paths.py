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

from cue_lib.constants import CUE_DIR_OVERRIDE_FILENAME, CUE_SHARED_CONFIG_FILENAME

MYPY = False
if MYPY:
    from typing import Any  # pyright: ignore[reportUnusedImport]

# The mod's folder name -- both the in-game base dir under gamedir (debug
# logs, ffmpeg progress/log, icons) and the platform default dir under
# APPDATA/etc.  One identity, one name.
CUE_MOD_DIRNAME = "renpy_cue"


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
        self._root = root
        self._game_id = game_id

    @property
    def root(self):
        # type: () -> str
        return self._root

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
            base = os.environ.get(
                "XDG_DATA_HOME",
                os.path.expanduser("~/.local/share"),
            )
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
        return self._root + "/audio/"

    @property
    def music_dir(self):
        # type: () -> str
        return self._root + "/music/"

    # ------------------------------------------------------------------
    # Internal data tree
    # ------------------------------------------------------------------

    @property
    def marker_dir(self):
        # type: () -> str
        return os.path.join(self._root, "data", "markers", self._game_id) + "/"

    @property
    def music_triggers_dir(self):
        # type: () -> str
        return os.path.join(self.marker_dir, "music") + "/"

    @property
    def presets_dir(self):
        # type: () -> str
        return os.path.join(self._root, "data", "presets") + "/"

    @property
    def audio_preset_dir(self):
        # type: () -> str
        return os.path.join(self.presets_dir, "audio") + "/"

    @property
    def video_preset_dir(self):
        # type: () -> str
        return os.path.join(self.presets_dir, "video") + "/"

    @property
    def video_dir(self):
        # type: () -> str
        return os.path.join(self._root, "video", self._game_id).replace("\\", "/") + "/"

    @property
    def shared_config_path(self):
        # type: () -> str
        return os.path.join(self._root, "data", CUE_SHARED_CONFIG_FILENAME)
