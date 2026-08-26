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

from cue_lib.constants import CUE_AUDIO_EXTS, CUE_HELP_SHIFT_SKIP_DELETE, CUE_INTENSITY_IDEAL_LEVELS, CueContextType
from cue_lib.markers import (
    _cue_markers_send,
    _cue_send_level_to_target,
    _cue_send_level_to_target_tt,
    _cue_target_assign_tt,
)
from cue_lib.state import _cue
from cue_lib.ui.dialogs import (
    _cue_confirm_delete_igroup,
    _cue_confirm_delete_music_preset,
    _cue_confirm_delete_preset,
    _cue_confirm_delete_video_preset,
    _cue_confirm_remove_video_preset_pool,
    _cue_maybe_apply_video_preset,
)
from cue_lib.runtime import _cue_preview_music_preset
from cue_lib.util import (
    _cue_filter_igroup_folders,
    _cue_filter_preset_files,
    _cue_format_time,
    _cue_igroup_search_matches,
    _cue_preset_search_matches,
    _cue_query_matches,
    _cue_resolve_files,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional


# Shared row helpers: every section/leaf row the content_rows builders emit is
# one of these four shapes, so the renderer's data contract has a single
# construction site.


def _cue_file_row(key, label, depth, buttons, warn=None, gap=1, size=None):
    # type: (str, str, int, List[Dict[str, Any]], Optional[str], Optional[int], Optional[int]) -> Dict[str, Any]
    """A file leaf row: indent, buttons, gap-null, then the accent label."""
    row = {
        "key": key,
        "type": "file",
        "label": label,
        "depth": depth,
        "buttons": buttons,
        "warn": warn or "",
        "gap": gap,
    }
    if size:
        row["size"] = size
    return row


def _cue_help_row(key, label, color=None, v_gap=None, depth=0, plain=False):
    # type: (str, str, Optional[str], Optional[int], int, bool) -> Dict[str, Any]
    """A muted help/empty-state line, indented to depth (0 = flush left).
    plain drops the cue_help style for text the screen renders unstyled
    (the no-results line)."""
    row = {"key": key, "type": "help", "label": label, "depth": depth}
    if color:
        row["color"] = color
    if v_gap:
        row["v_gap"] = v_gap
    if plain:
        row["plain"] = True
    return row


def _cue_action_row(key, label, action=None, tt=None, depth=0, explorer=None):
    # type: (str, str, Any, Optional[str], int, Optional[str]) -> Dict[str, Any]
    """A clickable text-button row.  explorer fills the renderer's
    open-in-explorer variant (music per-source empty states); otherwise the
    row runs action."""
    row = {"key": key, "type": "action", "label": label, "depth": depth}
    if action:
        row["action"] = action
    if tt:
        row["tt"] = tt
    if explorer:
        row["explorer"] = explorer
    return row


def _cue_section_rows(key, label, toggle_fn, expanded, searching, has_any, child_fn, auto_show=True):
    # type: (str, str, Any, bool, bool, Any, Any, bool) -> List[Dict[str, Any]]
    """Collapsible-section header + children-when-open.

    The header hides during a search unless has_any() reports a match;
    children render when the section is expanded, or during a search when
    auto_show (the tree's 'reveal matches' rule).  has_any() is a thunk so a
    search can skip an expensive child scan until the header is kept."""
    if searching and not has_any():
        return []
    rows = [{"key": key, "type": "folder", "label": label, "depth": 0, "buttons": [], "toggle": toggle_fn}]
    if expanded or (auto_show and searching):
        rows.extend(child_fn())
    return rows


def _cue_folder_rows(key, label, depth, toggle_fn, expanded, searching, buttons, children, hover_buttons=None):
    # type: (str, str, int, Any, bool, bool, List[Dict[str, Any]], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]
    """A collapsible folder row + its children while open (or during a
    search, when children auto-show like the tree).  hover_buttons (e.g. a
    level's move-up/down chevrons) render beside the label only while the
    row is hovered."""
    row = {"key": key, "type": "folder", "label": label, "depth": depth, "buttons": buttons, "toggle": toggle_fn}
    if hover_buttons:
        row["hover_buttons"] = hover_buttons
    rows = [row]
    if expanded or searching:
        rows.extend(children)
    return rows


class CueTreeRowsBuilder(object):
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
        folder gets no buttons (matches the current tree UI).

        Display paths carry the synthetic wrapper ("SFX Folder/..." for
        built-in, "ExtA/..." for external); every action that feeds a path
        uses ref_from_display to get the stored ref.  The file [+] is
        index-based and stays."""
        buttons = []
        ref = self._tree.ref_from_display(item["full_path"])
        if item["type"] == "folder":
            if item.get("has_files", False):
                buttons.append(
                    {
                        "icon": "play",
                        "action": Function(self._tree._sfx.preview_folder, ref),
                        "tt": "Play random file from folder",
                    }
                )
                buttons.append(self._add_row_button(item, "folder", target_ok, target_tt, ref))
        else:
            buttons.append(
                {"icon": "play", "action": Function(self._tree._sfx.preview_sfx, ref), "tt": "Preview audio"}
            )
            buttons.append(self._add_row_button(item, "file", target_ok, target_tt, ref))
        return buttons

    def _add_row_button(self, item, kind, target_ok, target_tt, ref):
        # type: (Dict[str, Any], str, bool, str, str) -> Dict[str, Any]
        """The tree [+] button.  In intensity add-mode it appends item to the
        active (group, level) -- dup-checked, marked with the selected_alt bg;
        otherwise it sends item to the target context."""
        tree = self._tree
        target = tree.ilevel_add_target
        if target is not None:
            group, lv_id = target
            if kind == "folder":
                action = Function(tree.ilevel_add_folder, group, lv_id, ref)
                label = "Add this folder to Level {} of {}.".format(lv_id, group)
            else:
                action = Function(tree.ilevel_add_file, group, lv_id, ref)
                label = "Add this file to Level {} of {}.".format(lv_id, group)
            is_dup = tree.level_has_file(group, lv_id, ref)
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
                "action": Function(_cue_markers_send, "folder", ref),
                "tt": target_tt,
                "enabled": target_ok,
            }
        return {
            "icon": "plus",
            "action": Function(_cue_markers_send, "file", item["index"]),
            "tt": target_tt,
            "enabled": target_ok,
        }

    def _recent_rows(self, entries, target_ok, target_tt):
        # type: (List[Dict[str, str]], bool, str) -> List[Dict[str, Any]]
        """Recently-Used rows.  Each entry is {"type", "ref"} (file / folder /
        preset).  File rows resolve a concrete _file_index so the [+] can send
        an index; all [+]s send record=False so acting from this list does not
        re-feed it.  Empty list yields the muted empty-state line."""
        if not entries:
            return [_cue_help_row("recent:empty", "Files you add to pools show up here.")]
        rows = []
        for entry in entries:
            ref = entry["ref"]
            kind = entry["type"]
            if kind == "file":
                idx = self._tree._file_index.get(ref, -1)
                buttons = [
                    {"icon": "play", "action": Function(self._tree._sfx.preview_sfx, ref)},
                    {
                        "icon": "plus",
                        "action": Function(_cue_markers_send, "file", idx, False),
                        "tt": target_tt,
                        "enabled": target_ok and idx >= 0,
                    },
                ]
            elif kind == "folder":
                buttons = [
                    {
                        "icon": "play",
                        "action": Function(self._tree._sfx.preview_folder, ref),
                        "tt": "Play random file from folder",
                    },
                    {
                        "icon": "plus",
                        "action": Function(_cue_markers_send, "folder", ref, False),
                        "tt": target_tt,
                        "enabled": target_ok,
                    },
                ]
            else:  # preset
                buttons = [
                    {
                        "icon": "play",
                        "action": Function(self._tree._sfx.preview_preset, ref),
                        "tt": "Play random file from preset",
                    },
                    {
                        "icon": "plus",
                        "action": Function(_cue_markers_send, "preset", ref, False),
                        "tt": target_tt,
                        "enabled": target_ok,
                    },
                ]
            rows.append(_cue_file_row("recent:" + ref, ref, 1, buttons))
        return rows

    def _preset_rows(self, preset_names, search_query, target_ok, target_tt):
        # type: (List[str], str, bool, str) -> List[Dict[str, Any]]
        """Pool Preset rows: one collapsible folder row per preset, then its
        filtered files while expanded or searching.  Files auto-show during a
        search so a content-matched preset reveals what matched (like the
        tree's matching-folder rule)."""
        searching = bool(search_query.strip())
        rows = []
        for pname in preset_names:
            expanded = self._tree.expanded_presets.get(pname, False)
            buttons = [
                {
                    "icon": "xmark",
                    "action": Function(_cue_confirm_delete_preset, pname),
                    "tt": "Delete preset" + CUE_HELP_SHIFT_SKIP_DELETE,
                },
                {
                    "icon": "play",
                    "action": Function(self._tree._sfx.preview_preset, pname),
                    "tt": "Play random file from preset",
                },
                {
                    "icon": "plus",
                    "action": Function(_cue_markers_send, "preset", pname),
                    "tt": target_tt,
                    "enabled": target_ok,
                },
            ]
            children = [
                _cue_file_row(
                    "preset:" + pname + "/" + child,
                    child,
                    1,
                    [
                        {
                            "icon": "xmark",
                            "action": Function(self._tree._sfx._markers.preset_remove_file, pname, child),
                            "tt": "Remove file from preset",
                        },
                        {"icon": "play", "action": Function(self._tree._sfx.preview_sfx, child), "tt": "Preview file"},
                    ],
                    size=11,
                )
                for child in _cue_filter_preset_files(pname, search_query)
            ]
            rows.extend(
                _cue_folder_rows(
                    "preset:" + pname,
                    pname,
                    1,
                    Function(self._tree.toggle_preset_expand, pname),
                    expanded,
                    searching,
                    buttons,
                    children,
                )
            )
        return rows

    def _video_preset_rows(self, video_preset_names, is_video):
        # type: (List[str], bool) -> List[Dict[str, Any]]
        """Video Preset rows: preset folder -> timestamp pools (depth 1) ->
        pool files (depth 2, size 11).  Pools reveal only on explicit expand
        (no search auto-show, matching the video preset screen); the apply-v
        button is gated on is_video."""
        rows = []
        for vpname in video_preset_names:
            data = self._tree._sfx._markers.get_video_preset(vpname)
            pools = data.get("pools", []) if data else []
            vp_expanded = self._tree.expanded_video_presets.get(vpname, False)
            buttons = [
                {
                    "icon": "xmark",
                    "action": Function(_cue_confirm_delete_video_preset, vpname),
                    "tt": "Delete video preset" + CUE_HELP_SHIFT_SKIP_DELETE,
                },
                {
                    "icon": "v",
                    "action": Function(_cue_maybe_apply_video_preset, vpname),
                    "tt": "Apply video markers to the current video.\nOverwrites existing markers.",
                    "enabled": is_video,
                },
            ]
            pool_rows = []
            pool_state = self._tree.expanded_video_pools.get(vpname, {})
            for pool_index, pool in enumerate(pools):
                pool_label = _cue_format_time(pool.get("time", 0))
                pool_expanded = pool_state.get(pool_index, False)
                pool_files = _cue_resolve_files(pool.get("files", []))
                children = [
                    _cue_file_row(
                        "vpreset:" + vpname + "/" + str(pool_index) + "/" + child,
                        child,
                        2,
                        [
                            {
                                "icon": "xmark",
                                "action": Function(
                                    self._tree._sfx._markers.remove_video_preset_pool_file, vpname, pool_index, child
                                ),
                                "tt": "Remove file from pool",
                            },
                            {
                                "icon": "play",
                                "action": Function(self._tree._sfx.preview_sfx, child),
                                "tt": "Preview file",
                            },
                        ],
                        size=11,
                    )
                    for child in pool_files
                ]
                pool_rows.extend(
                    _cue_folder_rows(
                        "vpreset:" + vpname + "/" + str(pool_index),
                        pool_label,
                        1,
                        Function(self._tree.toggle_video_pool_expand, vpname, pool_index),
                        pool_expanded,
                        False,
                        [
                            {
                                "icon": "xmark",
                                "action": Function(_cue_confirm_remove_video_preset_pool, vpname, pool_index),
                                "tt": "Remove this pool from the video preset" + CUE_HELP_SHIFT_SKIP_DELETE,
                            },
                            {
                                "icon": "play",
                                "action": Function(self._tree._sfx.preview_video_pool, vpname, pool_index),
                                "tt": "Play random file from this pool",
                            },
                        ],
                        children,
                    )
                )
            rows.extend(
                _cue_folder_rows(
                    "vpreset:" + vpname,
                    vpname,
                    1,
                    Function(self._tree.toggle_video_preset_expand, vpname),
                    vp_expanded,
                    False,
                    buttons,
                    pool_rows,
                )
            )
        return rows

    def _intensity_rows(self, igroup_names, search_query, lv_hook_ok, lv_tt):
        # type: (List[str], str, bool, str) -> List[Dict[str, Any]]
        """Intensity-group rows: the + Group action, then per group a
        collapsible folder with + Level, empty-state help, and level rows.
        Level rows carry move-up/down chevrons as hover_buttons; the level
        edit buttons (xmark, chevrons, + Level) hide while searching, like the
        screen's filter guard.  The level [+] hooks the level to a pool
        (lv_hook_ok = video/loop target only)."""
        searching = bool(search_query.strip())
        rows = [
            _cue_action_row(
                "intensity:+group", "+ Group", _cue.dialogs.intensity.open, tt="Create a new intensity group.", depth=1
            )
        ]
        if not igroup_names and not searching:
            rows.append(_cue_help_row("intensity:empty", "No intensity groups yet.", depth=1))
            rows.append(
                _cue_help_row(
                    "intensity:empty-hint",
                    "An intensity group is a soft-to-hard level list; each level is a pool of files.",
                    depth=1,
                )
            )
        for gname in igroup_names:
            group_expanded = self._tree.expanded_igroups.get(gname, False)
            g_levels = _cue_filter_igroup_folders(gname, search_query)
            children = []
            if not searching:
                children.append(
                    _cue_action_row(
                        "intensity:+level:" + gname,
                        "+ Level",
                        Function(self._tree.add_level, gname),
                        tt="Add a new level to this group.",
                        depth=2,
                    )
                )
                if not g_levels:
                    children.append(
                        _cue_help_row(
                            "intensity:nolevels:" + gname, "No levels yet. Click + Level to add one.", depth=1
                        )
                    )
                    children.append(
                        _cue_help_row(
                            "intensity:ideal:" + gname,
                            "Add up to ~{} levels for the best experience.".format(CUE_INTENSITY_IDEAL_LEVELS),
                            depth=1,
                            v_gap=2,
                        )
                    )
            for idx, lv in enumerate(g_levels):
                lv_id = lv["id"]
                lv_files = lv["files"]
                lv_expanded = lv_id in self._tree.expanded_ilevels.get(gname, set())
                in_add = self._tree.ilevel_add_target == (gname, lv_id)
                buttons = []
                if not searching:
                    buttons.append(
                        {
                            "icon": "xmark",
                            "action": Function(self._tree._intensity.remove_level, gname, idx),
                            "tt": "Remove this level",
                        }
                    )
                buttons.append(
                    {
                        "icon": "play",
                        "action": Function(self._tree._sfx.preview_level, gname, lv_id),
                        "tt": "Play a random file from this level",
                    }
                )
                buttons.append(
                    {
                        "icon": "folder-open" if in_add else "folder-plus",
                        "action": Function(self._tree.toggle_ilevel_add_mode, gname, lv_id),
                        "tt": "Click again to stop adding files" if in_add else "Add files to this level",
                        "bg": (getattr(renpy.store, "_cue_color_selected_alt", None) if in_add else None),
                    }
                )
                buttons.append(
                    {
                        "icon": "plus",
                        "action": Function(_cue_send_level_to_target, gname, lv_id),
                        "tt": lv_tt,
                        "enabled": lv_hook_ok,
                    }
                )
                hover = []
                if not searching:
                    bg_dialog = getattr(renpy.store, "_cue_color_bg_dialog", None)
                    hover = [
                        {
                            "icon": "chevron-up",
                            "action": Function(self._tree._intensity.move_level, gname, idx, -1),
                            "tt": "Move level up",
                            "bg": (bg_dialog if idx == 0 else None),
                        },
                        {
                            "icon": "chevron-down",
                            "action": Function(self._tree._intensity.move_level, gname, idx, 1),
                            "tt": "Move level down",
                            "bg": (bg_dialog if idx == len(g_levels) - 1 else None),
                        },
                    ]
                level_children = []
                if not lv_files:
                    level_children.append(
                        _cue_help_row(
                            "intensity:levelempty:" + gname + "/" + str(lv_id),
                            "Click the folder icon to add files",
                            depth=3,
                        )
                    )
                for file_ref in lv_files:
                    level_children.extend(self._ilevel_file_rows(gname, lv_id, file_ref))
                children.extend(
                    _cue_folder_rows(
                        "intensity:level:" + gname + "/" + str(lv_id),
                        "Level {}/".format(idx + 1),
                        2,
                        Function(self._tree.toggle_ilevel_expand, gname, lv_id),
                        lv_expanded,
                        searching,
                        buttons,
                        level_children,
                        hover,
                    )
                )
            rows.extend(
                _cue_folder_rows(
                    "intensity:group:" + gname,
                    gname,
                    1,
                    Function(self._tree.toggle_igroup_expand, gname),
                    group_expanded,
                    searching,
                    [
                        {
                            "icon": "xmark",
                            "action": Function(_cue_confirm_delete_igroup, gname),
                            "tt": "Delete intensity group" + CUE_HELP_SHIFT_SKIP_DELETE,
                        }
                    ],
                    children,
                )
            )
        return rows

    def _ilevel_file_rows(self, gname, lv_id, file_ref):
        # type: (str, object, str) -> List[Dict[str, Any]]
        """One level-file row (list form: a single row, or a folder ref's
        folder row + its expanded children).  Folder refs (trailing '/') are
        expandable folders whose children strip the folder prefix; plain files
        are size-11 leaves."""
        if file_ref.endswith("/"):
            expanded = self._tree.expanded_file_refs.get(file_ref, False)
            children = [
                _cue_file_row(
                    "intensity:irefchild:" + gname + "/" + str(lv_id) + "/" + child,
                    child[len(file_ref) :],
                    4,
                    [{"icon": "play", "action": Function(self._tree._sfx.preview_sfx, child), "tt": "Preview audio"}],
                    gap=0,
                    size=11,
                )
                for child in _cue_resolve_files([file_ref])
            ]
            return _cue_folder_rows(
                "intensity:iref:" + gname + "/" + str(lv_id) + "/" + file_ref,
                file_ref,
                3,
                Function(self._tree.toggle_file_ref_expand, file_ref),
                expanded,
                False,
                [
                    {
                        "icon": "xmark",
                        "action": Function(self._tree._intensity.remove_level_file, gname, lv_id, file_ref),
                        "tt": "Remove folder from level",
                    },
                    {
                        "icon": "play",
                        "action": Function(self._tree._sfx.preview_folder, file_ref),
                        "tt": "Play random file from folder",
                    },
                ],
                children,
            )
        return [
            _cue_file_row(
                "intensity:file:" + gname + "/" + str(lv_id) + "/" + file_ref,
                file_ref,
                3,
                [
                    {
                        "icon": "xmark",
                        "action": Function(self._tree._intensity.remove_level_file, gname, lv_id, file_ref),
                        "tt": "Remove file from level",
                    },
                    {"icon": "play", "action": Function(self._tree._sfx.preview_sfx, file_ref), "tt": "Preview audio"},
                ],
                size=11,
            )
        ]

    def content_rows(self, search_query, preset_names, video_preset_names, igroup_names, is_video, tgt_ok, unplayable):
        # type: (str, List[str], List[str], List[str], bool, bool, Dict[str, str]) -> List[Dict[str, Any]]
        """Full SFX Library section stream: Recently Used, Pool Presets, Video
        Presets, Intensity Groups, then the file tree.  Name lists arrive raw
        from the other managers and are search-filtered here (the current
        screen filters them the same way); recent entries are gathered from the
        tree's own CueRecentManager.  tgt_tt and the intensity hook state are
        resolved from the marker context here."""
        searching = bool(search_query.strip())
        tgt_tt = _cue_target_assign_tt()
        rows = []
        # -- Recently Used ---------------------------------------------------
        recent_entries = []
        recent = self._tree._recent
        if recent is not None:
            entries = recent.entries()
            if searching:
                entries = [e for e in entries if _cue_query_matches(e["ref"], search_query)]
            recent_entries = entries
            if not searching or entries:
                rows.extend(
                    _cue_section_rows(
                        "recent",
                        "Recently Used/",
                        Function(recent.toggle),
                        recent.expanded,
                        searching,
                        lambda: bool(entries),
                        lambda: self._recent_rows(entries, tgt_ok, tgt_tt),
                    )
                )
        # -- Pool Presets -----------------------------------------------------
        if searching:
            preset_names = [n for n in preset_names if _cue_preset_search_matches(n, search_query)]
        rows.extend(
            _cue_section_rows(
                "presets",
                "Pool Presets/",
                Function(self._tree.toggle_presets_expand),
                self._tree.presets_expanded,
                searching,
                lambda: bool(preset_names),
                lambda: self._preset_children(preset_names, search_query, tgt_ok, tgt_tt),
            )
        )
        # -- Video Presets ----------------------------------------------------
        if searching:
            video_preset_names = [n for n in video_preset_names if _cue_query_matches(n, search_query)]
        rows.extend(
            _cue_section_rows(
                "vpresets",
                "Video Presets/",
                Function(self._tree.toggle_video_presets_expand),
                self._tree.video_presets_expanded,
                searching,
                lambda: bool(video_preset_names),
                lambda: self._video_preset_children(video_preset_names, is_video),
                auto_show=False,
            )
        )
        # -- Intensity Groups -------------------------------------------------
        if searching:
            igroup_names = [n for n in igroup_names if _cue_igroup_search_matches(n, search_query)]
        ctx = _cue.markers.resolve_target_context()
        lv_hook_ok = (ctx == CueContextType.VIDEO or ctx == CueContextType.LOOP) and _cue.markers.target_is_available(
            ctx
        )
        lv_tt = _cue_send_level_to_target_tt()
        rows.extend(
            _cue_section_rows(
                "igroups",
                "Intensity Groups/",
                Function(self._tree.toggle_igroups_expand),
                self._tree.igroups_expanded,
                searching,
                lambda: bool(igroup_names),
                lambda: self._intensity_rows(igroup_names, search_query, lv_hook_ok, lv_tt),
            )
        )
        # -- Per-source empty/error states ------------------------------------
        tree = self._tree
        if not tree.builtin_tree:
            if tree.builtin_scan_error:
                rows.append(
                    _cue_help_row(
                        "builtin:scan_error",
                        tree.builtin_scan_error,
                        color=getattr(renpy.store, "_cue_color_error", None),
                        plain=True,
                    )
                )
            rows.append(
                _cue_help_row("builtin:empty", "No audio files found in: {}".format(tree._paths.audio_dir), plain=True)
            )
            rows.append(
                _cue_help_row(
                    "builtin:add",
                    "Add {} files there and click the refresh button.".format(", ".join(CUE_AUDIO_EXTS)),
                    plain=True,
                )
            )
            rows.append(_cue_action_row("builtin:open", "Open Audio folder", explorer=tree._paths.audio_dir))
            rows.append(
                _cue_help_row(
                    "builtin:settings_tip", "Add additional folder locations in Settings > Data Folder.", plain=True
                )
            )
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
                        "No audio files found in: {}".format(src["abs_root"]),
                        plain=True,
                    )
                )
                rows.append(
                    _cue_action_row("ext:{}:open".format(src["label"]), "Open folder", explorer=src["abs_root"])
                )
        # -- no-results guard + file tree ------------------------------------
        if (
            searching
            and not recent_entries
            and not preset_names
            and not video_preset_names
            and not igroup_names
            and not self._tree.visible_tree
        ):
            rows.append(_cue_help_row("no_results", 'No files found for "{}".'.format(search_query), plain=True))
        else:
            rows.extend(self.tree_rows(tgt_ok, tgt_tt, unplayable))
        return rows

    def _preset_children(self, preset_names, search_query, target_ok, target_tt):
        # type: (List[str], str, bool, str) -> List[Dict[str, Any]]
        """Pool Presets children: the empty-state line, then the preset rows."""
        rows = []
        if not preset_names:
            rows.append(_cue_help_row("presets:empty", "No pool presets yet. Save a pool as a preset to fill this."))
        rows.extend(self._preset_rows(preset_names, search_query, target_ok, target_tt))
        return rows

    def _video_preset_children(self, video_preset_names, is_video):
        # type: (List[str], bool) -> List[Dict[str, Any]]
        """Video Presets children: the empty-state line, then the preset rows."""
        rows = []
        if not video_preset_names:
            rows.append(
                _cue_help_row("vpresets:empty", "No video presets yet. Save video markers as a preset to fill this.")
            )
        rows.extend(self._video_preset_rows(video_preset_names, is_video))
        return rows

    def warn_reason(self, item, target_ok, target_tt, unplayable):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (Dict[str, Any], bool, str, Dict[str, str]) -> str
        """Unplayable-file reason for a file row's warn icon ("" = playable).
        target_ok / target_tt ride along in tree_rows' *state but are unused
        here; only unplayable feeds the icon.  The WAV index is keyed by the
        absolute path, so the display path resolves through the stored ref."""
        ref = self._tree.ref_from_display(item["full_path"])
        return unplayable.get(self._tree.resolve_path(ref), "")


class CueMusicTreeRows(CueTreeRowsBuilder):
    """Music Library tree row buttons.  Reaches the combined tree and its
    CueMusicManager back-ref through _tree."""

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

    def _recent_rows(self, entries, current_file):
        # type: (List[Dict[str, str]], object) -> List[Dict[str, Any]]
        """Recently-Used rows (music).  Folder rows carry only a [+], file rows
        [+] + [play]; all rows share SFX's 1px label gap.  + adds to the
        selected trigger (or a new one for the current scene) with record=False
        so acting here does not re-feed the list.  Empty list yields the muted
        empty-state line."""
        if not entries:
            return [_cue_help_row("recent:empty", "Songs you add to a trigger show up here.")]
        tree = self._tree
        music = tree._music
        sel_label = music.selected_trigger_label()
        add_target = sel_label if sel_label else "a new trigger for the current scene"
        add_enabled = music.selected_key is not None or bool(current_file)
        rows = []
        for entry in entries:
            ref = entry["ref"]
            path = tree.ref_display_path(ref)
            if entry["type"] == "folder":
                buttons = [
                    {
                        "icon": "plus",
                        "action": Function(tree.add_folder_to_trigger, path, False),
                        "tt": "Add folder to " + add_target,
                        "enabled": add_enabled,
                    }
                ]
            else:
                buttons = [
                    {
                        "icon": "plus",
                        "action": Function(tree.add_song_to_trigger, path, False),
                        "tt": "Add song to " + add_target,
                        "enabled": add_enabled,
                    },
                    {"icon": "play", "action": Function(tree.preview, path), "tt": "Play song"},
                ]
            rows.append(_cue_file_row("recent:" + ref, path, 1, buttons))
        return rows

    def _preset_rows(self, preset_names):
        # type: (List[str]) -> List[Dict[str, Any]]
        """Music Preset rows: one collapsible folder per preset (delete /
        apply / play + label), its files listed while the preset is expanded.
        Unlike SFX, music preset files do not auto-show during a search."""
        music = self._tree._music
        apply_tt = "Click: Replace selected trigger's songs\nShift+Click: Apply to current scene (new trigger if none)"
        apply_enabled = music.selected_key is not None
        rows = []
        for pname in preset_names:
            expanded = music.expanded_presets.get(pname, False)
            buttons = [
                {
                    "icon": "xmark",
                    "action": Function(_cue_confirm_delete_music_preset, pname),
                    "tt": "Delete preset" + CUE_HELP_SHIFT_SKIP_DELETE,
                },
                {
                    "icon": "plus",
                    "action": Function(music.apply_preset, pname),
                    "tt": apply_tt,
                    "enabled": apply_enabled,
                },
                {
                    "icon": "play",
                    "action": Function(_cue_preview_music_preset, pname),
                    "tt": "Play random song from preset",
                },
            ]
            pdata = music.get_preset(pname)
            children = [
                _cue_file_row(
                    "preset:" + pname + "/" + child,
                    child,
                    1,
                    [
                        {
                            "icon": "xmark",
                            "action": Function(music.preset_remove_file, pname, child),
                            "tt": "Remove file from preset",
                        },
                        {"icon": "play", "action": Function(self._tree.preview, child), "tt": "Preview song"},
                    ],
                    size=11,
                )
                for child in (music.preset_display_files(pdata) if pdata else [])
            ]
            rows.extend(
                _cue_folder_rows(
                    "preset:" + pname,
                    pname,
                    1,
                    Function(music.toggle_preset_expand, pname),
                    expanded,
                    False,
                    buttons,
                    children,
                )
            )
        return rows

    def _preset_children(self, preset_names):
        # type: (List[str]) -> List[Dict[str, Any]]
        """Music Presets children: the empty-state line, then the preset rows."""
        rows = []
        if not preset_names:
            rows.append(
                _cue_help_row("presets:empty", "No music presets yet. Save a trigger's song list to fill this.")
            )
        rows.extend(self._preset_rows(preset_names))
        return rows

    def content_rows(self, search_query, preset_names, current_file):
        # type: (str, List[str], object) -> List[Dict[str, Any]]
        """Full Music Library section stream: Recently Used, Music Presets,
        the per-source empty/error states, then the combined tree (or the
        no-results line during a search).  preset_names arrive raw from the
        manager and are search-filtered here; recent entries are gathered from
        the manager's own CueRecentManager.  Row layout (depth-based indent,
        1px file gap, uniform 2px spacing) matches the SFX library."""
        searching = bool(search_query.strip())
        music = self._tree._music
        rows = []
        # -- Recently Used ---------------------------------------------------
        recent_entries = []
        recent = music._recent
        if recent is not None:
            entries = recent.entries()
            if searching:
                entries = [
                    e for e in entries if _cue_query_matches(self._tree.ref_display_path(e["ref"]), search_query)
                ]
            recent_entries = entries
            if not searching or entries:
                rows.extend(
                    _cue_section_rows(
                        "recent",
                        "Recently Used/",
                        Function(recent.toggle),
                        recent.expanded,
                        searching,
                        lambda: bool(entries),
                        lambda: self._recent_rows(entries, current_file),
                    )
                )
        # -- Music Presets ----------------------------------------------------
        if searching:
            preset_names = [n for n in preset_names if _cue_query_matches(n, search_query)]
        rows.extend(
            _cue_section_rows(
                "presets",
                "Music Presets/",
                Function(music.toggle_presets_expand),
                music.presets_expanded,
                searching,
                lambda: bool(preset_names),
                lambda: self._preset_children(preset_names),
                auto_show=False,  # music preset files only render when expanded
            )
        )
        # -- Per-source empty/error states ------------------------------------
        user = self._tree.user_tree
        if not user:
            if self._tree.user_scan_error:
                rows.append(
                    _cue_help_row(
                        "user:scan_error",
                        self._tree.user_scan_error,
                        color=getattr(renpy.store, "_cue_color_error", None),
                        plain=True,
                    )
                )
            rows.append(_cue_help_row("user:empty", "No music found in: {}".format(music._paths.music_dir), plain=True))
            rows.append(
                _cue_help_row(
                    "user:add",
                    "Add {} files there and click the refresh button.".format(", ".join(CUE_AUDIO_EXTS)),
                    plain=True,
                )
            )
            rows.append(_cue_action_row("user:open", "Open Music folder", explorer=music._paths.music_dir))
        game = self._tree.game_tree
        if not game:
            if self._tree.game_scan_error:
                rows.append(
                    _cue_help_row(
                        "game:scan_error",
                        self._tree.game_scan_error,
                        color=getattr(renpy.store, "_cue_color_error", None),
                        plain=True,
                    )
                )
            rows.append(_cue_help_row("game:empty", "No music found in game directory.", plain=True))
        for src in self._tree.external_sources:
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
                        "ext:{}:empty".format(src["label"]), "No music found in: {}".format(src["abs_root"]), plain=True
                    )
                )
                rows.append(
                    _cue_action_row("ext:{}:open".format(src["label"]), "Open folder", explorer=src["abs_root"])
                )
        # -- no-results guard + tree -----------------------------------------
        if self._tree.user_tree or self._tree.game_tree or self._tree.external_sources:
            if searching and not recent_entries and not preset_names and not self._tree.visible_tree:
                rows.append(_cue_help_row("no_results", 'No files found for "{}".'.format(search_query), plain=True))
            else:
                rows.extend(self.tree_rows(current_file))
        return rows
