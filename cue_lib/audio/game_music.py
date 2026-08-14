# -*- coding: utf-8 -*-
# CueGameMusic -- the "Game Music" section on the Music page: scan of the
# game's own audio files via the Ren'Py virtual filesystem, folder/file tree
# caches, and tree UI state (expand/collapse, visible rows).  The tree/scan/
# toggle core is inherited from CueAudioTreeManager; this class only supplies
# the virtual-filesystem scan source.
# Instantiated once as _cue.music.game_music; lives on the NoRollback _cue
# object.

import renpy

from cue_lib.audio.audio_tree import CueAudioTreeManager
from cue_lib.constants import CUE_AUDIO_EXTS, CUE_GAME_MUSIC_DIRS

MYPY = False
if MYPY:
    from typing import Set


class CueGameMusic(CueAudioTreeManager):
    """Scan state and folder/file tree UI for the Game Music section.

    Same shape as CueUserMusic -- the files / tree / scan_error /
    visible_tree / expanded_folders caches are inherited.  The difference is
    the scan source: instead of os.walk over a shared dir, _discover()
    enumerates renpy.list_files() (the game's virtual filesystem, archives
    included) and keeps audio files whose path passes the directory-name
    heuristic.  No disabled files, presets, or pool refs -- just the tree
    rows rendered on the Music page."""

    _scan_label = "game music"
    _log_tag = "GAME-MUSIC"

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _discover(self, results_set):
        # type: (Set[str]) -> None
        """Scan the game's virtual filesystem for music.

        A file counts as music when its path has a directory segment matching
        CUE_GAME_MUSIC_DIRS and it ends with an audio extension.  Paths are
        kept game-relative so they play directly on the music channel.  An
        empty result is not an error -- the game may just have no music in
        standard dirs."""
        for f in renpy.list_files():
            path = f.replace("\\", "/")
            if not path.lower().endswith(CUE_AUDIO_EXTS):
                continue
            parts = path.split("/")
            dirs = [p.lower() for p in parts[:-1]]
            if any(d in CUE_GAME_MUSIC_DIRS for d in dirs):
                results_set.add(path)
