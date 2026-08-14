# -*- coding: utf-8 -*-
# CueSfxManager -- SFX library file scan, folder/file tree UI state, and
# disabled files: expand/collapse, visible tree building, and the audio
# scan that feeds them.
# Instantiated once at _cue.sfx_manager, lives on the NoRollback _cue object.

import os
import time

from cue_lib.constants import CUE_AUDIO_EXTS
from cue_lib.state import _cue
from cue_lib.util import _cue_build_tree, _cue_log, _cue_resolve_files

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional


class CueSfxManager(object):
    """SFX library audio tree state, expand/collapse, disabled files, and scan.

    Owns all UI state for the SFX Library audio tree, preset folders,
    video preset folders, section frames, and pool file-list folder refs,
    plus the audio file caches (files / audio_tree / scan_error)
    and the scan that builds them.  Provides toggle methods callable via
    Function() from screen actions."""

    def __init__(self):
        # Audio scan caches
        self.files = []     # flat sorted relative paths
        self.audio_tree = []          # nested folder/file nodes from _cue_build_tree
        self.scan_error = ""          # non-empty only when the scan fails

        # Tree state
        self.visible_tree = []
        self.expanded_folders = {}        # folder_path -> bool
        self.expanded_file_refs = {}      # folder_ref -> bool (pool file lists)

        # Presets expand/collapse
        self.presets_expanded = False
        self.expanded_presets = {}        # preset_name -> bool

        # Video presets expand/collapse
        self.video_presets_expanded = False
        self.expanded_video_presets = {}  # preset_name -> bool

        # File disable
        self.disabled_files = set()       # full_path strings

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        # type: () -> None
        """Scan the audio dir and rebuild the visible tree.

        An empty folder is not an error -- it just means no audio files have
        been added yet.  scan_error is only set when the scan itself fails.
        """
        _t0 = time.time()

        search_path = _cue.paths.audio_dir
        if not search_path.endswith("/"):
            search_path = search_path + "/"

        results_set = set()

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
            self.files = []
            self.audio_tree = []
            self.scan_error = "Failed to scan audio folder: {}".format(err)
            return

        results = sorted(results_set)
        self.files = results
        self.audio_tree = _cue_build_tree(results)

        # Empty is fine -- no audio files added yet
        self.scan_error = ""

        # Rebuild visible tree for the SFX Library section
        self.rebuild_tree()

        _cue_log("SCAN-AUDIO: {:.3f}s {} files".format(time.time() - _t0, len(results)))

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def rebuild_tree(self):
        # type: () -> None
        """Rebuild self.visible_tree from self.audio_tree.
        Only expanded folders are recursed into."""
        result = []
        self._walk_tree(self.audio_tree, "", 0, result)
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
                # Find index in flat list
                try:
                    idx = self.files.index(full)
                except ValueError:
                    idx = -1
                result.append({
                    "type": "file",
                    "name": item["name"],
                    "full_path": full,
                    "depth": depth,
                    "index": idx,
                    "enabled": full not in self.disabled_files,
                })

    # ------------------------------------------------------------------
    # Toggle: audio tree folders
    # ------------------------------------------------------------------

    def toggle_folder(self, folder_path):
        # type: (str) -> None
        """Toggle expand/collapse for a folder in the audio tree."""
        if folder_path in self.expanded_folders:
            self.expanded_folders[folder_path] = not self.expanded_folders[folder_path]
        else:
            self.expanded_folders[folder_path] = True
        self.rebuild_tree()

    # ------------------------------------------------------------------
    # Toggle: file enabled/disabled
    # ------------------------------------------------------------------

    def toggle_file_enabled(self, full_path):
        # type: (str) -> None
        """Toggle whether a file is enabled for marker addition."""
        if full_path in self.disabled_files:
            self.disabled_files.discard(full_path)
        else:
            self.disabled_files.add(full_path)
        self.rebuild_tree()
        _cue.db.update_shared_config({"disabled_files": list(self.disabled_files)})

    # ------------------------------------------------------------------
    # Pool file-list folder refs
    # ------------------------------------------------------------------

    def toggle_file_ref_expand(self, folder_ref):
        # type: (str) -> None
        """Toggle expand/collapse for a folder ref in a pool file list."""
        if folder_ref in self.expanded_file_refs:
            self.expanded_file_refs[folder_ref] = not self.expanded_file_refs[folder_ref]
        else:
            self.expanded_file_refs[folder_ref] = True

    def count_file_list_rows(self, folder_label, folder_children, files):
        # type: (Optional[str], Optional[List[str]], List[str]) -> int
        """Count rendered rows in a pool file list (for viewport sizing)."""
        rows = 0
        if folder_label is not None:
            rows += 1
            if self.expanded_file_refs.get(folder_label, False) and folder_children:
                rows += len(folder_children)
        for f in files:
            rows += 1
            if f.endswith("/"):
                if self.expanded_file_refs.get(f, False):
                    rows += len(_cue_resolve_files([f]))
        return rows

    # ------------------------------------------------------------------
    # Toggle: Presets/ folder
    # ------------------------------------------------------------------

    def toggle_presets_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Presets/ folder in the SFX Library."""
        self.presets_expanded = not self.presets_expanded

    def toggle_preset_expand(self, preset_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single preset in the SFX Library."""
        if preset_name in self.expanded_presets:
            self.expanded_presets[preset_name] = not self.expanded_presets[preset_name]
        else:
            self.expanded_presets[preset_name] = True

    # ------------------------------------------------------------------
    # Toggle: Video Presets/ folder
    # ------------------------------------------------------------------

    def toggle_video_presets_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Video Presets/ folder in the SFX Library."""
        self.video_presets_expanded = not self.video_presets_expanded

    def toggle_video_preset_expand(self, preset_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single video preset in the SFX Library."""
        if preset_name in self.expanded_video_presets:
            self.expanded_video_presets[preset_name] = not self.expanded_video_presets[preset_name]
        else:
            self.expanded_video_presets[preset_name] = True
