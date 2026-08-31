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

from cue_lib.ui.displayables import _cue_scale_ui
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
CUE_SETTINGS_FOLDER_TIP = "Add folders in Settings > Data Folder."

# Px reserved past measured chrome when computing a row label's elide bound:
# a nominal right shoulder plus headroom so glyph-width estimates cannot
# under-reserve and push the label onto a second line.
CUE_ELIDE_SAFETY_PX = 30

# Persistent scroll adjustments for the windowed cue_tree_rows screen: one per
# tree instance (keyed by the call site).  Module state is not tracked by
# rollback, so the scroll position survives a rollback without a revert.
_cue_tree_adjs = {}

# Throttle state per tree key: the (pitch, first row, buffer) of the last
# window the screen built.  The screen records it on every eval; the scroll
# callback only restarts the interaction once the scroll has moved past it.
_cue_tree_win = {}


def _cue_tree_window(key, pitch, first, buf):
    # type: (str, int, int, int) -> None
    """Record the window the screen just built, for the scroll throttle.

    The screen calls this on every eval.  _cue_tree_restart compares the new
    scroll position against this build and restarts only when it has moved
    `buf` rows past it."""
    _cue_tree_win[key] = (pitch, first, buf)


def _cue_tree_restart(key, value):
    # type: (str, float) -> None
    """Re-evaluate the screen when a windowed tree scrolls past its buffer.

    A viewport scroll only redraws its displayables; it does not re-run the
    screen function (per_interact runs once per interact_core, before its event
    loop).  Without a restart the window slice goes stale and empty space shows
    until some other event restarts the interaction.  Restarting on *every*
    scroll would rebuild the window at mouse-motion rate during a scrollbar
    drag, so this restarts only once the scroll has moved `buf` rows past the
    last build -- the built slice always still covers the visible rows, and a
    drag rebuilds at most once per buffer's worth of scroll.  Returns None so
    the scroll event is not consumed."""
    st = _cue_tree_win.get(key)
    if st is None:
        return None
    pitch, first0, buf = st
    first = int(value) // pitch
    if abs(first - first0) < buf:
        return None
    _cue_tree_win[key] = (pitch, first, buf)
    renpy.exports.restart_interaction()
    return None


def _cue_tree_adjustment(key):
    # type: (str) -> Any
    """Return the persistent scroll adjustment for a windowed tree instance.

    cue_tree_rows builds only the visible slice of rows (plus a buffer on each
    side) instead of every row, so it needs one Adjustment per tree to carry
    the scroll position across re-evals.  The viewport writes the adjustment
    as the user scrolls; the throttled `changed` callback re-evaluates the
    screen so the window tracks the new position.  The range/page are filled
    in by the viewport on its first render."""
    import renpy.display.behavior as _renpy_behavior

    def _changed(value):
        _cue_tree_restart(key, value)

    return _cue_tree_adjs.setdefault(key, _renpy_behavior.Adjustment(1, 0, changed=_changed))


def _cue_elide_label(label, max_chars):
    # type: (str, int) -> str
    """Trim a row label to max_chars with a trailing "...".

    Tree rows render in a vpgrid with a uniform cell height, so every label
    must be single-line; paths, scan errors, and search queries are unbounded,
    so the renderer elides labels here rather than letting them wrap."""
    if len(label) > max_chars:
        return label[: max_chars - 3] + "..."
    return label


def _cue_row_label_max(row, container_w):
    # type: (TreeRowDict, int) -> int
    """Max label chars for one tree row given the scaled container width.

    The elide bound must keep the label on its own line, so the row's own
    chrome is subtracted from the container's width (the overlay panel, or the
    SFX sidebar, which is drag-resizable): per-depth indent, leading icon
    buttons, file gap + warn icon, and the side padding of button labels.
    container_w is scaled px; the per-char budget is the scaled width of a
    12px glyph."""
    indent_px = _cue_scale_ui(7)  # one indent level (the 2-space _cue_indent)
    char_w = _cue_scale_ui(7)  # per-glyph width of a 12px label
    button_w = _cue_scale_ui(getattr(renpy.store, "_cue_btn_height", 16))
    btn_pad = _cue_scale_ui(4)  # cue_button side padding (2px each side)
    btn_gap = 4  # null gap between action buttons
    icon_space = _cue_scale_ui(4)  # hbox spacing between an icon and its label
    min_chars = 16  # never elide below this many characters

    chrome = indent_px * row.get("depth", 0)
    chrome += button_w * len(row.get("buttons", []))
    if row["type"] == "file":
        chrome += row.get("gap", 1)
        if row.get("warn"):
            chrome += button_w
    elif row["type"] == "actions":
        for index, act in enumerate(row["actions"]):
            chrome += btn_pad
            if index > 0:
                chrome += btn_gap
            if act.get("icon"):
                chrome += icon_space + button_w
    else:
        # folder/action/help labels sit in a cue_button (side padding) or a
        # bare text line; both leave a small shoulder.
        chrome += btn_pad
        if row["type"] == "folder":
            chrome += button_w + icon_space  # the leading caret icon
    avail = container_w - chrome - _cue_scale_ui(CUE_ELIDE_SAFETY_PX)
    return max(min_chars, avail // char_w)


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


def _cue_folder_row(key, label, depth, buttons, toggle, expanded=False):
    # type: (str, str, int, List[TreeButtonDict], Any, bool) -> TreeFolderRowDict
    """A collapsible folder row (the header; children are separate rows)."""
    return {
        "key": key,
        "type": "folder",
        "label": label,
        "depth": depth,
        "buttons": buttons,
        "toggle": toggle,
        "expanded": expanded,
    }


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
    rows = _cue_folder_rows(key, label, 0, toggle_fn, expanded, searching, [], [])
    if expanded or (auto_show and searching):
        rows.extend(child_fn())
    return rows


def _cue_folder_rows(key, label, depth, toggle_fn, expanded, searching, buttons, children, hover_buttons=None):
    # type: (str, str, int, Any, bool, bool, List[TreeButtonDict], List[TreeRowDict], Optional[List[TreeButtonDict]]) -> List[TreeRowDict]
    """A collapsible folder row + its children while open (or during a
    search, when children auto-show like the tree).  hover_buttons (e.g. a
    level's move-up/down chevrons) render beside the label only while the
    row is hovered."""
    row = _cue_folder_row(key, label, depth, buttons, toggle_fn, expanded=expanded)
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
                    "expanded": item.get("expanded", False),
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
