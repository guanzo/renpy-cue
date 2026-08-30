# -*- coding: utf-8 -*-
# Shared row-building core for the cue_tree_rows renderer.  Every section/leaf
# row the content_rows builders emit is one of the row shapes below, so the
# renderer's data contract has a single construction site.  CueTreeRowsBuilder
# walks a data tree's visible_tree and emits the flat row stream, delegating
# the per-source variations to subclasses.  A builder reaches its data tree
# through _tree, so it never imports the concrete managers (no import cycle).

import renpy
import renpy.python as _renpy_python

from renpy.store import Function

from cue_lib.util import _cue_escape_text

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional

    from cue_lib._types import (
        TreeActionRowDict,
        TreeActionsRowDict,
        TreeButtonDict,
        TreeFileRowDict,
        TreeFolderRowDict,
        TreeHelpRowDict,
        TreeRowDict,
    )

# Empty-library tip shared by the SFX and music empty states.
CUE_SETTINGS_FOLDER_TIP = "Add additional folder locations in Settings > Data Folder."


def _cue_file_row(key, label, depth, buttons, warn=None, gap=1, size=None):
    # type: (str, str, int, List[TreeButtonDict], Optional[str], int, Optional[int]) -> TreeFileRowDict
    """A file leaf row: indent, buttons, gap-null, then the accent label."""
    row = {
        "key": key,
        "type": "file",
        "label": label,
        "depth": depth,
        "buttons": buttons,
        "warn": warn or "",
        "gap": gap,
    }  # type: TreeFileRowDict
    if size:
        row["size"] = size
    return row


def _cue_help_row(key, label, color=None, v_gap=None, depth=0, plain=False):
    # type: (str, str, Optional[str], Optional[int], int, bool) -> TreeHelpRowDict
    """A muted help/empty-state line, indented to depth (0 = flush left).
    plain drops the cue_help style for text the screen renders unstyled
    (the no-results line)."""
    row = {"key": key, "type": "help", "label": label, "depth": depth}  # type: TreeHelpRowDict
    if color:
        row["color"] = color
    if v_gap:
        row["v_gap"] = v_gap
    if plain:
        row["plain"] = True
    return row


def _cue_action_row(key, label, action=None, tt=None, depth=0, explorer=None, sensitive=True, icon=None):
    # type: (str, str, Any, Optional[str], int, Optional[str], bool, Optional[str]) -> TreeActionRowDict
    """A clickable text-button row.  explorer fills the renderer's
    open-in-explorer variant (music per-source empty states); otherwise the
    row runs action.  icon names an icon-manager PNG to render beside the
    label (e.g. the SFX-pack download button)."""
    row = {"key": key, "type": "action", "label": label, "depth": depth}  # type: TreeActionRowDict
    if action:
        row["action"] = action
    if tt:
        row["tt"] = tt
    if explorer:
        row["explorer"] = explorer
    if icon:
        row["icon"] = icon
    if not sensitive:
        row["sensitive"] = False
    return row


def _cue_actions_row(key, actions, depth=0):
    # type: (str, List[TreeActionRowDict], int) -> TreeActionsRowDict
    """A row that lays its action buttons out horizontally (same line)."""
    return {"key": key, "type": "actions", "actions": actions, "depth": depth}


def _cue_folder_row(key, label, depth, buttons, toggle):
    # type: (str, str, int, List[TreeButtonDict], Any) -> TreeFolderRowDict
    """A collapsible folder row (the header; children are separate rows)."""
    return {"key": key, "type": "folder", "label": label, "depth": depth, "buttons": buttons, "toggle": toggle}


def _cue_external_empty_rows(tree, kind_word):
    # type: (Any, str) -> List[TreeRowDict]
    """Per-source empty/error rows for external folders with no files.

    A source appears even when its folder is missing or errored so its
    warning/empty row stays reachable.  kind_word is the folder description
    used in the empty text ("audio files" for SFX, "music" for music)."""
    rows = []  # type: List[TreeRowDict]
    for src in tree.external_sources:
        if src["tree"]:
            continue
        if src["scan_error"]:
            rows.append(
                _cue_help_row(
                    "ext:{}:scan_error".format(src["label"]),
                    src["scan_error"],
                    color=getattr(renpy.store, "_cue_color_error", None),
                    plain=True,
                )
            )
        else:
            rows.append(
                _cue_help_row(
                    "ext:{}:empty".format(src["label"]),
                    "No {} found in: {}".format(kind_word, src["abs_root"]),
                    plain=True,
                )
            )
            rows.append(_cue_action_row("ext:{}:open".format(src["label"]), "Open folder", explorer=src["abs_root"]))
    return rows


def _cue_section_rows(key, label, toggle_fn, expanded, searching, has_any, child_fn, auto_show=True):
    # type: (str, str, Any, bool, bool, Any, Any, bool) -> List[TreeRowDict]
    """Collapsible-section header + children-when-open.

    The header hides during a search unless has_any() reports a match;
    children render when the section is expanded, or during a search when
    auto_show (the tree's 'reveal matches' rule).  has_any() is a thunk so a
    search can skip an expensive child scan until the header is kept."""
    if searching and not has_any():
        return []
    rows = _cue_folder_rows(key, label, 0, toggle_fn, False, False, [], [])
    if expanded or (auto_show and searching):
        rows.extend(child_fn())
    return rows


def _cue_folder_rows(key, label, depth, toggle_fn, expanded, searching, buttons, children, hover_buttons=None):
    # type: (str, str, int, Any, bool, bool, List[TreeButtonDict], List[TreeRowDict], Optional[List[TreeButtonDict]]) -> List[TreeRowDict]
    """A collapsible folder row + its children while open (or during a
    search, when children auto-show like the tree).  hover_buttons (e.g. a
    level's move-up/down chevrons) render beside the label only while the
    row is hovered."""
    row = _cue_folder_row(key, label, depth, buttons, toggle_fn)
    if hover_buttons:
        row["hover_buttons"] = hover_buttons
    rows = [row]  # type: List[TreeRowDict]
    if expanded or searching:
        rows.extend(children)
    return rows


class CueTreeRowsBuilder(_renpy_python.NoRollback):
    """Builds the flat row stream for cue_tree_rows from a data tree's
    visible_tree.

    Walks the depth-annotated visible_tree and emits one row dict per entry,
    delegating the two per-source variations to row_buttons() / warn_reason()
    and file_gap.  *state carries the non-owned values the screen computed
    (target availability/tooltip/unplayable for SFX, current_file for music)
    so subclasses never read globals."""

    # null-width px before a file row's label (all sources match SFX)
    file_gap = 1

    def __init__(self, tree):
        # type: (Any) -> None
        self._tree = tree
        self._rows_cache_key = None  # fingerprint of the last built content_rows
        self._rows_cache = None  # List[TreeRowDict] served on unchanged keys
        # Hit/build counters for verifying the memo at runtime: hover a while
        # in-game, then read them via the dev console (Shift+O).
        self._rows_cache_hits = 0
        self._rows_cache_builds = 0

    def _memo_rows(self, key, build):
        # type: (tuple, Any) -> List[TreeRowDict]
        """Serve the cached row list when ``key`` is unchanged, else rebuild.

        The SFX/music screens call content_rows on every interaction restart
        (each hover, tooltip focus change, and scroll re-evaluates the screen
        body), so without this a pure hover rebuilds every row.  Subclasses
        fingerprint exactly the state content_rows reads; any input they miss
        would serve stale rows, so _rows_key must stay exhaustive."""
        if key == self._rows_cache_key and self._rows_cache is not None:
            self._rows_cache_hits += 1
            return self._rows_cache
        rows = build()
        self._rows_cache_key = key
        self._rows_cache = rows
        self._rows_cache_builds += 1
        return rows

    def tree_rows(self, *state):
        # type: (*Any) -> List[TreeRowDict]
        """Flat row stream for the cue_tree_rows renderer: one row dict per
        visible_tree item, buttons from row_buttons(), warn from
        warn_reason(), file gap from file_gap."""
        rows = []  # type: List[TreeRowDict]
        for item in self._tree.visible_tree:
            if item["type"] == "folder":
                row = {
                    "key": "tree:" + item["full_path"],
                    "type": "folder",
                    "label": item["name"],
                    "depth": item["depth"],
                    "buttons": self.row_buttons(item, *state),
                    "toggle": Function(self._tree.toggle_folder, item["full_path"]),
                }  # type: TreeFolderRowDict
                # Abs-path tooltip only on source roots: threading it onto every
                # nested folder gives a big tree thousands of per-hover tooltips.
                if item.get("abs_root") and item["depth"] == 0:
                    row["tt"] = _cue_escape_text(item["abs_root"]) or ""
                rows.append(row)
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
        # type: (Dict[str, Any], *Any) -> List[TreeButtonDict]
        """Buttons for one tree row ([] by default; subclasses fill in)."""
        return []

    def warn_reason(self, item, *state):
        # type: (Dict[str, Any], *Any) -> str
        """Invalid-file reason for a file row's warn icon ("" = none)."""
        return ""
