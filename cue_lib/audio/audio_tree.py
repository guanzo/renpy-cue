# -*- coding: utf-8 -*-
# CueAudioTreeManager -- shared folder/file tree state and scan pattern for
# the audio-library managers (SFX library, My Music, Game Music): flat sorted
# file list, nested tree, scan error, expand/collapse state, and visible-row
# building.  Subclasses supply the scan source via _discover() plus a couple
# of class attrs for the error message and log tag.  Base of CueSfxManager,
# CueUserMusic, and CueGameMusic; the concrete managers hang off _cue.

import os
import time

from cue_lib.constants import CUE_AUDIO_EXTS
from cue_lib.util import _cue_build_tree, _cue_filter_tree, _cue_log

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Set

# Broad search queries ("a" matches most files) can force-expand thousands of
# rows, which is slow to render.  Search results are capped at this many rows;
# the overflow count is left in search_truncated so the UI can ask for a
# narrower query.
CUE_SEARCH_MAX_ROWS = 100


class CueAudioTreeManager(object):
    """Folder/file tree state shared by the SFX library and music managers.

    Owns the flat sorted file list (files), the nested tree built from it
    (tree), the scan error string (scan_error), and the expand/collapse state
    that drives visible_tree.  scan() is a template: subclasses fill a set of
    relative paths via _discover(), then the base sorts, builds the tree,
    rebuilds the visible rows, and logs.  Class attrs _scan_label (error text)
    and _log_tag (log prefix) customize those two outputs.  _file_node() may
    be overridden to add per-file fields -- the SFX library adds index and
    enabled."""

    _scan_label = "audio"
    _log_tag = "AUDIO"

    def __init__(self):
        self.files = []             # flat sorted relative paths
        self.tree = []              # nested folder/file nodes from _cue_build_tree
        self.scan_error = ""        # non-empty only when the scan fails
        self.visible_tree = []      # flat, depth-annotated rows for the screen
        self.expanded_folders = {}  # folder_path -> bool
        self.search_query = ""      # non-empty -> visible_tree is a filtered view
        self.search_truncated = 0   # rows dropped by the search cap (0 when idle)
        self.search_is_editing = False  # search bar input is in edit mode
        self._search_applied = ""   # query last rebuilt for (debounce marker)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        # type: () -> None
        """Scan, sort, and rebuild the visible tree.

        An empty result is not an error -- it just means no files matched.
        scan_error is only set when the scan itself fails."""
        _t0 = time.time()

        results_set = set()

        try:
            self._discover(results_set)
        except Exception as err:
            self.files = []
            self.tree = []
            self.scan_error = "Failed to scan {}: {}".format(self._scan_label, err)
            return

        results = sorted(results_set)
        self.files = results
        self.tree = _cue_build_tree(results)

        # Empty is fine -- nothing found yet
        self.scan_error = ""

        # Rebuild visible tree
        self.rebuild_tree()

        _cue_log("SCAN-{}: {:.3f}s {} files".format(self._log_tag, time.time() - _t0, len(results)))

    def _discover(self, results_set):
        # type: (Set[str]) -> None
        """Fill results_set with relative paths to include.

        Overridden by subclasses; may raise on scan failure, which scan()
        turns into scan_error and empty caches."""
        raise NotImplementedError()

    def _discover_walk_dir(self, results_set, search_path):
        # type: (Set[str], str) -> None
        """Fill results_set with audio files under search_path (recursive).

        Shared walk for the physical-filesystem scans (SFX library and My
        Music).  A missing folder contributes nothing -- not an error."""
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

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def rebuild_tree(self):
        # type: () -> None
        """Rebuild self.visible_tree from self.tree.

        With a search query set, self.tree is filtered (see _cue_filter_tree)
        and every kept folder is force-expanded so all matches are visible;
        otherwise only expanded folders are recursed into.  self.tree and
        self.expanded_folders are never modified here, so clearing the search
        restores the exact pre-search view.  During a search the rows are
        capped at CUE_SEARCH_MAX_ROWS and the overflow count is left in
        search_truncated (0 when under the cap or not searching)."""
        query = self.search_query.strip()

        if query:
            source = _cue_filter_tree(self.tree, query)
            force_expand = True
        else:
            source = self.tree
            force_expand = False

        result = []
        self._walk_tree(source, "", 0, result, force_expand)

        if force_expand and len(result) > CUE_SEARCH_MAX_ROWS:
            self.search_truncated = len(result) - CUE_SEARCH_MAX_ROWS
            del result[CUE_SEARCH_MAX_ROWS:]
        else:
            self.search_truncated = 0

        self.visible_tree = result

    def clear_search(self):
        # type: () -> None
        """Clear the search query and rebuild the full, unexpanded tree."""
        if self.search_query:
            self.search_query = ""
            self._search_applied = ""
            self.rebuild_tree()

    def maybe_rebuild(self):
        # type: () -> None
        """Rebuild the filtered tree when the search query changed since the
        last rebuild; no-op otherwise.  Called on a timer from the search bar
        (every 0.25s), which debounces live typing into at most one rebuild
        per pause instead of one per keystroke."""
        q = self.search_query
        if q == self._search_applied:
            return
        self.rebuild_tree()
        self._search_applied = q

    def _walk_tree(self, items, prefix, depth, result, force_expand=False):
        # type: (List[Dict[str, Any]], str, int, List[Dict[str, Any]], bool) -> None
        """Recursively walk tree, only descending into expanded folders.

        force_expand (search mode) treats every folder as expanded so all
        filtered rows are produced; otherwise self.expanded_folders decides."""
        for item in items:
            full = prefix + item["name"]
            if item["type"] == "folder":
                expanded = force_expand or self.expanded_folders.get(full, False)
                result.append({
                    "type": "folder",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "expanded": expanded,
                    "has_files": item.get("has_files", False),
                })
                if expanded:
                    self._walk_tree(item.get("children", []), full, depth + 1, result, force_expand)
            else:
                result.append(self._file_node(item, full, depth))

    def _file_node(self, item, full, depth):
        # type: (Dict[str, Any], str, int) -> Dict[str, Any]
        """File row dict for a single file item.  Overridden to add fields."""
        return {
            "type": "file",
            "name": item["name"],
            "full_path": full,
            "depth": depth,
        }

    # ------------------------------------------------------------------
    # Toggle: tree folders
    # ------------------------------------------------------------------

    def toggle_folder(self, folder_path):
        # type: (str) -> None
        """Toggle expand/collapse for a folder in the tree.

        No-op while a search is active -- search results are always
        auto-expanded, and toggling must not disturb the saved expansion
        state that clear_search restores."""
        if self.search_query.strip():
            return
        if folder_path in self.expanded_folders:
            self.expanded_folders[folder_path] = not self.expanded_folders[folder_path]
        else:
            self.expanded_folders[folder_path] = True
        self.rebuild_tree()
