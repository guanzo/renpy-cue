# -*- coding: utf-8 -*-
# CueAudioTreeManager -- shared folder/file tree state and scan pattern for
# the audio-library managers (SFX library, Music Library): flat sorted file
# list, nested tree, scan error, expand/collapse state, and visible-row
# building.  Subclasses supply the scan source via _discover() plus a couple
# of class attrs for the error message and log tag.  Base of CueSfxManager and
# CueMusicTree; the concrete managers hang off _cue.

import os
import time

from renpy.store import persistent

from cue_lib.constants import CUE_AUDIO_EXTS
from cue_lib.util import _cue_build_tree, _cue_filter_tree, _cue_log, _cue_unwrap_persistent

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple

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
    # Expand every depth-0 folder on the first non-empty scan (opt-in via
    # _auto_expand_roots) so a tree's root level is open by default.  After
    # that one-time default the user's toggle state is left untouched.
    _auto_expand_roots = False
    # persistent._cue key for expanded_folders; None = this tree does not
    # persist folder expansion.  Subclasses that persist set the CUE_PERSIST_*
    # key (SFX tree, Music Library tree).
    _persist_key = None
    # Basenames that must never become an external source's display label
    # (the synthetic built-in roots).  Subclasses reserve their own.
    _reserved_labels = ()  # type: Tuple[str, ...]

    def __init__(self):
        self._recent = None  # CueRecentManager, wired after construction
        self.external_folders = []  # configured external abs paths
        self.external_files = []  # absolute payloads from _scan_external
        self.external_sources = []  # per-root scan dicts from _scan_external
        self.files = []  # flat sorted relative paths
        self._file_index = {}  # path -> position in files (rebuilt in scan)
        self.tree = []  # nested folder/file nodes from _cue_build_tree
        self.scan_error = ""  # non-empty only when the scan fails
        self.visible_tree = []  # flat, depth-annotated rows for the screen
        self.expanded_folders = {}  # folder_path -> bool
        self.search_query = ""  # non-empty -> visible_tree is a filtered view
        self.search_truncated = 0  # rows dropped by the search cap (0 when idle)
        self._search_applied = ""  # query last rebuilt for (debounce marker)
        self._has_expanded_roots = False  # one-time root expansion done

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
            self._file_index = {}
            self.tree = []
            self.scan_error = "Failed to scan {}: {}".format(self._scan_label, err)
            return

        results = sorted(results_set)
        self.files = results
        self.tree = _cue_build_tree(results)

        # Empty is fine -- nothing found yet
        self.scan_error = ""

        self._file_index = {path: i for i, path in enumerate(results)}

        # One-time default: open the tree at its root folders (opt-in), so
        # the top level is visible without a click.  Only the first non-empty
        # scan does this -- every later scan leaves the user's toggles alone.
        if self._auto_expand_roots and not self._has_expanded_roots and self.tree:
            self._expand_roots()
            self._has_expanded_roots = True

        # Overlay persisted toggles: saved keys win, untouched folders keep
        # their default (the one-time root view above).
        self._restore_expansion()

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

    def _scan_external(self):
        # type: () -> None
        """Scan configured external folders into per-source trees.

        Each configured abs_root becomes an external source dict (label,
        files, tree, scan_error).  A missing folder keeps its entry with a
        warning and an empty tree so the warning row stays reachable."""
        self.external_files = []
        self.external_sources = []
        used_labels = []  # type: List[str]
        for abs_root in self.external_folders:
            source = self._scan_external_root(abs_root, used_labels)
            used_labels.append(source["label"])
            self.external_sources.append(source)
            self.external_files += source["files"]
        # Global sort: the per-source lists are sorted individually but splicing
        # them in config order is not; _cue_expand_folder_ref bisects this list,
        # so it must be sorted for a stored folder ref to expand correctly.
        self.external_files.sort()

    def _scan_external_root(self, abs_root, used_labels):
        # type: (str, List[str]) -> Dict[str, Any]
        """Scan one configured external folder into an external source dict.

        files hold the absolute payloads (the untagged form); the display
        tree is built from the relative paths so it renders under the source
        label."""
        abs_root = abs_root.replace("\\", "/").rstrip("/")
        rel_files = []  # type: List[str]
        scan_error = ""  # type: str
        if os.path.isdir(abs_root):
            try:
                sub = set()
                self._discover_walk_dir(sub, abs_root)
                rel_files = sorted(sub)
            except Exception as err:
                rel_files = []
                scan_error = "Failed to scan external folder: {}".format(err)
        else:
            scan_error = "Folder not found: {}".format(abs_root)
        return {
            "abs_root": abs_root,
            "label": self._external_label(abs_root, used_labels),
            "files": [abs_root + "/" + rel for rel in rel_files],
            "tree": _cue_build_tree(rel_files),
            "scan_error": scan_error,
        }

    def _external_label(self, abs_root, used_labels):
        # type: (str, List[str]) -> str
        """Display label for an external folder: its basename, disambiguated
        against the reserved built-in roots and other external labels."""
        base = abs_root.rstrip("/").rsplit("/", 1)[-1] or "External"
        reserved = tuple(x.rstrip("/") for x in self._reserved_labels)
        label = base
        n = 2
        while label in reserved or label in used_labels:
            label = "{} ({})".format(base, n)
            n += 1
        return label

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

    def _expand_roots(self):
        # type: () -> None
        """Mark every depth-0 folder expanded (one-time default view).

        Keys match _walk_tree's folder keys (item["name"] at depth 0, e.g.
        "music/" for My Music).  Subfolders stay collapsed."""
        for item in self.tree:
            if item["type"] == "folder":
                self.expanded_folders[item["name"]] = True

    def clear_search(self):
        # type: () -> None
        """Clear the search query and rebuild the full, unexpanded tree.

        The Recently Used list is not owned here and is never touched by a
        search or clear: it force-expands read-time during a search (the UI
        shows it whenever `_searching`), so clearing restores the user's own
        expand state just like every tree folder."""
        if self.search_query:
            self.search_query = ""
            self._search_applied = ""
            self.rebuild_tree()

    def maybe_rebuild(self):
        # type: () -> None
        q = self.search_query
        if q == self._search_applied:
            return
        self.rebuild_tree()
        self._search_applied = q

    def _walk_tree(self, items, prefix, depth, result, force_expand=False, abs_root=None):
        # type: (List[Dict[str, Any]], str, int, List[Dict[str, Any]], bool, Optional[str]) -> None
        """Recursively walk tree, only descending into expanded folders.

        force_expand (search mode) treats every folder as expanded so all
        filtered rows are produced; otherwise self.expanded_folders decides.
        abs_root threads an external source's absolute path down its subtree
        so folder rows under one can show it as their tooltip."""
        for item in items:
            full = prefix + item["name"]
            if item["type"] == "folder":
                node_abs = item.get("abs_root")
                if node_abs is None and abs_root is not None:
                    node_abs = abs_root + "/" + item["name"].rstrip("/")
                expanded = force_expand or self.expanded_folders.get(full, False)
                node = {
                    "type": "folder",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "has_files": item.get("has_files", False),
                }
                if node_abs is not None:
                    node["abs_root"] = node_abs
                result.append(node)
                if expanded:
                    self._walk_tree(item.get("children", []), full, depth + 1, result, force_expand, node_abs)
            else:
                result.append(self._file_node(item, full, depth))

    def _file_node(self, item, full, depth):
        # type: (Dict[str, Any], str, int) -> Dict[str, Any]
        """File row dict for a single file item.  Overridden to add fields."""
        return {"type": "file", "name": item["name"], "full_path": full, "depth": depth}

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
        self._save_expansion()

    def _save_expansion(self):
        # type: () -> None
        """Write expanded_folders to persistent._cue (no-op if not persisted)."""
        if self._persist_key is None:
            return
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[self._persist_key] = dict(self.expanded_folders)

    def _restore_expansion(self):
        # type: () -> None
        """Overlay persisted folder-expansion state onto expanded_folders.

        Keys the saved dict holds override the current values; keys it omits
        keep their defaults, so an untouched tree keeps its first-run view
        while explicitly-toggled folders restore."""
        if self._persist_key is None:
            return
        raw = (persistent._cue or {}).get(self._persist_key)
        if raw is None:
            return
        self.expanded_folders.update(_cue_unwrap_persistent(raw))
