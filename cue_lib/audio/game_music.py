# -*- coding: utf-8 -*-
# CueGameMusic -- the "Game Music" section on the Music page: scan of the
# game's own audio files via the Ren'Py virtual filesystem, folder/file tree
# caches, and tree UI state (expand/collapse, visible rows).
# Instantiated once as _cue.music.game_music; lives on the NoRollback _cue
# object.

import renpy
import time

from cue_lib.constants import CUE_AUDIO_EXTS, CUE_GAME_MUSIC_DIRS
from cue_lib.util import _cue_build_tree, _cue_log

MYPY = False
if MYPY:
    from typing import Any, Dict, List


class CueGameMusic(object):
    """Scan state and folder/file tree UI for the Game Music section.

    Same shape as CueUserMusic -- music_files, music_tree, music_scan_error,
    visible_tree, and expanded_folders are attributes of this manager.  The
    difference is the scan source: instead of os.walk over a shared dir, it
    enumerates renpy.list_files() (the game's virtual filesystem, archives
    included) and keeps audio files whose path passes the directory-name
    heuristic.  No disabled files, presets, or pool refs -- just the tree
    rows rendered on the Music page."""

    def __init__(self):
        self.music_files = []        # flat sorted game-relative paths
        self.music_tree = []         # nested folder/file nodes from _cue_build_tree
        self.music_scan_error = ""   # non-empty only when the scan fails
        self.visible_tree = []       # flat, depth-annotated rows for the screen
        self.expanded_folders = {}   # folder_path -> bool

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        # type: () -> None
        """Scan the game's virtual filesystem for music and rebuild the tree.

        Mirrors CueUserMusic.scan() but targets renpy.list_files() -- the
        game's bundled audio, not the user's shared music dir.  A file counts
        as music when its path has a directory segment matching
        CUE_GAME_MUSIC_DIRS and it ends with an audio extension.  Paths are
        kept game-relative so they play directly on the music channel.  An
        empty result is not an error -- the game may just have no music in
        standard dirs.  music_scan_error is only set when the scan fails."""
        _t0 = time.time()

        results_set = set()

        # Ren'Py's virtual filesystem (covers .rpa archives and the live
        # game dir) -- the source of truth for what the game actually has.
        try:
            for f in renpy.list_files():
                path = f.replace("\\", "/")
                if not path.lower().endswith(CUE_AUDIO_EXTS):
                    continue
                parts = path.split("/")
                dirs = [p.lower() for p in parts[:-1]]
                if any(d in CUE_GAME_MUSIC_DIRS for d in dirs):
                    results_set.add(path)
        except Exception as err:
            self.music_files = []
            self.music_tree = []
            self.music_scan_error = "Failed to scan game music: {}".format(err)
            return

        results = sorted(results_set)
        self.music_files = results
        self.music_tree = _cue_build_tree(results)

        # Empty is fine -- no music found in standard dirs
        self.music_scan_error = ""

        # Rebuild visible tree for the Game Music section
        self.rebuild_tree()

        _cue_log("SCAN-GAME-MUSIC: {:.3f}s {} files".format(time.time() - _t0, len(results)))

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def rebuild_tree(self):
        # type: () -> None
        """Rebuild self.visible_tree from self.music_tree.
        Only expanded folders are recursed into."""
        result = []
        self._walk_tree(self.music_tree, "", 0, result)
        self.visible_tree = result

    def _walk_tree(self, items, prefix, depth, result):
        # type: (List[Dict[str, Any]], str, int, List[Dict[str, Any]]) -> None
        """Recursively walk tree, only descending into expanded folders."""
        for item in items:
            full = prefix + item["name"]
            if item["type"] == "folder":
                result.append({
                    "type": "folder",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "expanded": self.expanded_folders.get(full, False),
                    "has_files": item.get("has_files", False),
                })
                if self.expanded_folders.get(full, False):
                    self._walk_tree(item.get("children", []), full, depth + 1, result)
            else:
                result.append({
                    "type": "file",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                })

    # ------------------------------------------------------------------
    # Toggle: tree folders
    # ------------------------------------------------------------------

    def toggle_folder(self, folder_path):
        # type: (str) -> None
        """Toggle expand/collapse for a folder in the game music tree."""
        if folder_path in self.expanded_folders:
            self.expanded_folders[folder_path] = not self.expanded_folders[folder_path]
        else:
            self.expanded_folders[folder_path] = True
        self.rebuild_tree()
