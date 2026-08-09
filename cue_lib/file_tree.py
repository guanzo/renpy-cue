# CueFileTreeManager -- folder/file tree UI state: expand/collapse, disabled
# files, and visible tree building for the SFX Library sidebar.
# Instantiated once at _cue.file_tree, lives on the NoRollback _cue object.

import renpy

from cue_lib.state import _cue

MYPY = False
if MYPY:
    from typing import List
    from cue_lib._types import AudioTreeNode


class CueFileTreeManager:
    """Folder/file tree visibility, expand/collapse state, and disabled files.

    Owns all UI state for the SFX Library audio tree, preset folders,
    video preset folders, section frames, and pool file-list folder refs.
    Provides toggle methods callable via Function() from screen actions."""

    def __init__(self):
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

        # Section collapse
        self.collapsed_sections = {}      # section_name -> bool

        # File disable
        self.disabled_files = set()       # full_path strings

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def rebuild_tree(self):
        # type: () -> None
        """Rebuild self.visible_tree from _cue.audio_tree.
        Only expanded folders are recursed into."""
        result = []
        self._walk_tree(_cue.audio_tree, "", 0, result)
        self.visible_tree = result

    def _walk_tree(self, items, prefix, depth, result):
        # type: (List[AudioTreeNode], str, int, List[AudioTreeNode]) -> None
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
                    idx = _cue.available_files.index(full)
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
        _cue.markers.save_persistent()

    # ------------------------------------------------------------------
    # Toggle: pool file-list folder refs
    # ------------------------------------------------------------------

    def toggle_file_ref_expand(self, folder_ref):
        # type: (str) -> None
        """Toggle expand/collapse for a folder ref in a pool file list."""
        if folder_ref in self.expanded_file_refs:
            self.expanded_file_refs[folder_ref] = not self.expanded_file_refs[folder_ref]
        else:
            self.expanded_file_refs[folder_ref] = True

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
    # Toggle: section frames
    # ------------------------------------------------------------------

    def toggle_section(self, section_name):
        # type: (str) -> None
        """Toggle expand/collapse for a cue_section_frame."""
        self.collapsed_sections[section_name] = not self.collapsed_sections.get(section_name, False)
        renpy.restart_interaction()
