# -*- coding: utf-8 -*-
# Tree row-building for the shared cue_tree_rows renderer.  One dedicated
# module for all folder-tree UI logic: CueTreeRowsBuilder owns the shared walk
# over a data tree's visible_tree; CueSfxTreeRows / CueMusicTreeRows own the
# per-source button and warn variations.  The data tree classes keep scan /
# search / expand / dispatch and delegate tree_rows() here via a builder they
# construct in __init__.  A builder reaches the data tree through _tree, so it
# never imports the concrete managers (no import cycle).

import renpy

from renpy.store import Function

from cue_lib.markers import _cue_markers_send

MYPY = False
if MYPY:
    from typing import Any, Dict, List


class CueTreeRowsBuilder(object):
    """Builds the flat row stream for cue_tree_rows from a data tree's
    visible_tree.

    Walks the depth-annotated visible_tree and emits one row dict per entry,
    delegating the two per-source variations to row_buttons() / warn_reason()
    and file_gap.  *state carries the non-owned values the screen computed
    (target availability/tooltip/unplayable for SFX, current_file for music)
    so subclasses never read globals."""

    # null-width px before a file row's label (music overrides to 2)
    file_gap = 1

    def __init__(self, tree):
        # type: (Any) -> None
        self._tree = tree

    def tree_rows(self, *state):
        # type: (*Any) -> List[Dict[str, Any]]
        """Flat row stream for the cue_tree_rows renderer: one row dict per
        visible_tree item, buttons from row_buttons(), warn from
        warn_reason(), file gap from file_gap."""
        rows = []
        for item in self._tree.visible_tree:
            if item["type"] == "folder":
                rows.append(
                    {
                        "key": "tree:" + item["full_path"],
                        "type": "folder",
                        "label": item["name"],
                        "depth": item["depth"],
                        "buttons": self.row_buttons(item, *state),
                        "toggle": Function(self._tree.toggle_folder, item["full_path"]),
                    }
                )
            else:
                rows.append(
                    {
                        "key": "tree:" + item["full_path"],
                        "type": "file",
                        "label": item["name"],
                        "depth": item["depth"],
                        "buttons": self.row_buttons(item, *state),
                        "warn": self.warn_reason(item, *state),
                        "gap": self.file_gap,
                    }
                )
        return rows

    def row_buttons(self, item, *state):
        # type: (Dict[str, Any], *Any) -> List[Dict[str, Any]]
        """Buttons for one tree row ([] by default; subclasses fill in)."""
        return []

    def warn_reason(self, item, *state):
        # type: (Dict[str, Any], *Any) -> str
        """Invalid-file reason for a file row's warn icon ("" = none)."""
        return ""


class CueSfxTreeRows(CueTreeRowsBuilder):
    """SFX Library tree row buttons + warn.  Reaches the library tree (and its
    CueSfxManager back-ref) through _tree."""

    def row_buttons(self, item, target_ok, target_tt, unplayable):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (Dict[str, Any], bool, str, Dict[str, str]) -> List[Dict[str, Any]]
        """SFX row buttons: [play, plus].  Plus adds to the target context, or
        in intensity add-mode appends to the active (group, level).  An empty
        folder gets no buttons (matches the current tree UI)."""
        buttons = []
        if item["type"] == "folder":
            if item.get("has_files", False):
                buttons.append(
                    {
                        "icon": "play",
                        "action": Function(self._tree._sfx.preview_folder, item["full_path"]),
                        "tt": "Play random file from folder",
                    }
                )
                buttons.append(self._add_row_button(item, "folder", target_ok, target_tt))
        else:
            buttons.append(
                {
                    "icon": "play",
                    "action": Function(self._tree._sfx.preview_sfx, item["full_path"]),
                    "tt": "Preview audio",
                }
            )
            buttons.append(self._add_row_button(item, "file", target_ok, target_tt))
        return buttons

    def _add_row_button(self, item, kind, target_ok, target_tt):
        # type: (Dict[str, Any], str, bool, str) -> Dict[str, Any]
        """The tree [+] button.  In intensity add-mode it appends item to the
        active (group, level) -- dup-checked, marked with the selected_alt bg;
        otherwise it sends item to the target context."""
        tree = self._tree
        target = tree.ilevel_add_target
        if target is not None:
            group, lv_id = target
            if kind == "folder":
                action = Function(tree.ilevel_add_folder, group, lv_id, item["full_path"])
                label = "Add this folder to Level {} of {}.".format(lv_id, group)
            else:
                action = Function(tree.ilevel_add_file, group, lv_id, item["full_path"])
                label = "Add this file to Level {} of {}.".format(lv_id, group)
            is_dup = tree.level_has_file(group, lv_id, item["full_path"])
            return {
                "icon": "plus",
                "action": action,
                "tt": label,
                "enabled": not is_dup,
                "bg": (getattr(renpy.store, "_cue_color_selected_alt", None) if not is_dup else None),
            }
        if kind == "folder":
            return {
                "icon": "plus",
                "action": Function(_cue_markers_send, "folder", item["full_path"]),
                "tt": target_tt,
                "enabled": target_ok,
            }
        return {
            "icon": "plus",
            "action": Function(_cue_markers_send, "file", item["index"]),
            "tt": target_tt,
            "enabled": target_ok,
        }

    def warn_reason(self, item, target_ok, target_tt, unplayable):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (Dict[str, Any], bool, str, Dict[str, str]) -> str
        """Unplayable-file reason for a file row's warn icon ("" = playable).
        target_ok / target_tt ride along in tree_rows' *state but are unused
        here; only unplayable feeds the icon."""
        return unplayable.get(self._tree._paths.audio_dir + item["full_path"], "")


class CueMusicTreeRows(CueTreeRowsBuilder):
    """Music Library tree row buttons.  Reaches the combined tree and its
    CueMusicManager back-ref through _tree."""

    file_gap = 2

    def row_buttons(self, item, current_file):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (Dict[str, Any], object) -> List[Dict[str, Any]]
        """Music row buttons: [plus, play] for files, [plus] for folders (only
        when the folder directly holds files).  Plus adds to the selected
        trigger or creates one for the current scene; disabled without either."""
        tree = self._tree
        sel_label = tree._music.selected_trigger_label()
        add_target = sel_label if sel_label else "a new trigger for the current scene"
        add_enabled = tree._music.selected_key is not None or bool(current_file)
        buttons = []
        if item["type"] == "folder":
            if item.get("has_files", False):
                buttons.append(
                    {
                        "icon": "plus",
                        "action": Function(tree.add_folder_to_trigger, item["full_path"]),
                        "tt": "Add folder to " + add_target,
                        "enabled": add_enabled,
                    }
                )
        else:
            buttons.append(
                {
                    "icon": "plus",
                    "action": Function(tree.add_song_to_trigger, item["full_path"]),
                    "tt": "Add song to " + add_target,
                    "enabled": add_enabled,
                }
            )
            buttons.append({"icon": "play", "action": Function(tree.preview, item["full_path"]), "tt": "Play song"})
        return buttons
