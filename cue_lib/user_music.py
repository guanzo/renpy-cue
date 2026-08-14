# -*- coding: utf-8 -*-
# CueUserMusic -- the "My Music" section on the Music page: filesystem scan,
# folder/file tree caches, and tree UI state (expand/collapse, visible rows).
# Instantiated once as _cue.music_manager.user_music; lives on the NoRollback
# _cue object.

import os
import time

from cue_lib.constants import CUE_AUDIO_EXTS
from cue_lib.state import _cue
from cue_lib.util import _cue_build_tree, _cue_log

MYPY = False
if MYPY:
    from typing import Any, Dict, List


class CueUserMusic(object):
    """Scan state and folder/file tree UI for the My Music section.

    Every _cue.music_* cache lives here instead of on _cue: music_files,
    music_tree, and music_scan_error are attributes of this manager.  A leaner
    sibling of CueSfxManager: no disabled files, presets, overlay mode,
    or pool folder refs -- just the music tree rows rendered on the Music
    page.  Section collapse reuses _cue.collapsed_sections via
    cue_section_frame."""

    def __init__(self):
        self.music_files = []        # flat sorted relative paths
        self.music_tree = []         # nested folder/file nodes from _cue_build_tree
        self.music_scan_error = ""   # non-empty only when the scan fails
        self.visible_tree = []       # flat, depth-annotated rows for the screen
        self.expanded_folders = {}   # folder_path -> bool

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        # type: () -> None
        """Scan the My Music dir and rebuild the visible tree.

        Mirrors _cue.sfx_manager.scan() but targets shared_dir/music, so
        user music never mixes with the SFX library.  An empty folder is not
        an error --
        it just means the user hasn't added music yet.  music_scan_error is
        only set when the scan itself fails.
        """
        _t0 = time.time()

        search_path = _cue.paths.music_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        results_set = set()
        _cue_log('search_path='+str(search_path))
        
        # Live filesystem scan (picks up files added after startup)
        try:
            if os.path.isdir(search_path):
                for dirpath, _dirnames, filenames in os.walk(search_path, followlinks=True):
                    rel_dir = os.path.relpath(dirpath, search_path)
                    if rel_dir == ".":
                        rel_dir = ""
                    for fname in filenames:
                        if fname.lower().endswith(CUE_AUDIO_EXTS):
                            rel_path = (rel_dir + "/" + fname) if rel_dir else fname
                            rel_path = rel_path.replace("\\", "/")
                            results_set.add(rel_path)
        except (OSError, IOError) as err:
            self.music_files = []
            self.music_tree = []
            self.music_scan_error = "Failed to scan music folder: {}".format(err)
            return

        _cue_log('results=' + str(results_set))
        
        results = sorted(results_set)
        self.music_files = results
        self.music_tree = _cue_build_tree(results)

        # Empty is fine -- the user just hasn't added music yet
        self.music_scan_error = ""

        # Rebuild visible tree for the My Music section
        self.rebuild_tree()

        _cue_log("SCAN-MUSIC: {:.3f}s {} files".format(time.time() - _t0, len(results)))

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
        """Toggle expand/collapse for a folder in the music tree."""
        if folder_path in self.expanded_folders:
            self.expanded_folders[folder_path] = not self.expanded_folders[folder_path]
        else:
            self.expanded_folders[folder_path] = True
        self.rebuild_tree()
