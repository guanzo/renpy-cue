# -*- coding: utf-8 -*-
# CueSfxManager -- SFX library file scan, folder/file tree UI state, and
# disabled files: expand/collapse, visible tree building, and the audio
# scan that feeds them.  The tree/scan/toggle core is inherited from
# CueAudioTreeManager; this class adds the SFX-specific extras (preset
# folders, video preset folders, pool file-list refs, disabled files) and
# the index/enabled fields on each file row.
# Instantiated once at _cue.sfx_manager, lives on the NoRollback _cue object.

import renpy

from cue_lib.audio.audio_tree import CueAudioTreeManager
from cue_lib.util import _cue_resolve_files

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]


class CueSfxManager(CueAudioTreeManager):
    """SFX library audio tree state, expand/collapse, disabled files, and scan.

    Owns all UI state for the SFX Library audio tree, preset folders,
    video preset folders, section frames, and pool file-list folder refs.
    The audio file caches (files / tree / scan_error) and the scan that
    builds them live in CueAudioTreeManager.  Provides toggle methods
    callable via Function() from screen actions."""

    _scan_label = "audio folder"
    _log_tag = "AUDIO"

    def __init__(self, paths, db):
        # type: (CuePaths, CueDatabase) -> None
        super(CueSfxManager, self).__init__()
        self._paths = paths
        self._db = db

        # Pool file-list folder refs
        self.expanded_file_refs = {}      # folder_ref -> bool (pool file lists)

        # Presets expand/collapse
        self.presets_expanded = False
        self.expanded_presets = {}        # preset_name -> bool

        # Video presets expand/collapse
        self.video_presets_expanded = False
        self.expanded_video_presets = {}  # preset_name -> bool

        # File disable
        self.disabled_files = set()       # full_path strings

        # Overlay mode: SFX Library section floats at 50% height
        self.overlay_mode = False

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _discover(self, results_set):
        # type: (Set[str]) -> None
        """Scan the audio dir -- files the user drops in for SFX."""
        self._discover_walk_dir(results_set, self._paths.audio_dir)

    def _file_node(self, item, full, depth):
        # type: (Dict[str, Any], str, int) -> Dict[str, Any]
        """File row with index/enabled for the SFX Library."""
        node = super(CueSfxManager, self)._file_node(item, full, depth)
        node["index"] = self._file_index.get(full, -1)
        node["enabled"] = full not in self.disabled_files
        return node

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
        self._db.update_shared_config({"disabled_files": list(self.disabled_files)})

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

    # ------------------------------------------------------------------
    # Toggle: overlay mode
    # ------------------------------------------------------------------

    def toggle_overlay_mode(self):
        # type: () -> None
        """Toggle overlay mode for the SFX Library section.
        Enabling overlay mode collapses the section if expanded.
        Exiting overlay mode expands the section if collapsed."""
        was_overlay = self.overlay_mode
        self.overlay_mode = not was_overlay

        renpy.restart_interaction()
