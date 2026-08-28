# -*- coding: utf-8 -*-
# Pool content rows (cue_pool_files): a marker pool's own refs -- or an
# igroup-hooked pool's resolved level files -- rendered by the shared
# cue_tree_rows renderer.  Replaces the old _cue_file_list_vbox /
# _cue_igroup_pool_files_vbox screen pair so regular, preset-backed, and
# igroup pools share one builder.  Expand state lives in the SFX library's
# expanded_file_refs (the same store the old vbox screens read).

from renpy.store import Function

from cue_lib.audio.tree.tree_rows import _cue_file_row, _cue_folder_rows
from cue_lib.constants import CUE_INTENSITY_HINT_COLOR, CUE_INTENSITY_NOTE
from cue_lib.state import _cue
from cue_lib.util import _cue_pick_file, _cue_resolve_files, create_vid_key

MYPY = False
if MYPY:
    from typing import Any, List, Optional

    from cue_lib._types import TreeButtonDict, TreeFolderRowDict, TreeRowDict


def _cue_pool_files_rows(
    files,
    preview_vol,
    detach_action,
    remove_fn,
    remove_args,
    child_remove_fn,
    marker_key,
    pool_index,
    folder_label,
    folder_children,
    igroup=None,
    ilevel_id=None,
):
    # type: (List[str], float, Any, Any, tuple, Any, Optional[str], Optional[int], Optional[str], Optional[List[str]], Optional[str], Optional[int]) -> List[TreeRowDict]
    """Row dicts for one pool's file area.

    detach_action is a pre-built action that removes the pool's hook -- the
    preset header xmark or an igroup level's detach xmark.  Per-ref /
    per-child removal stays callable (remove_fn / child_remove_fn) because
    those actions carry a per-row index the screen can't know in advance."""
    if igroup is not None:
        level_files = _cue.intensity.level_files_by_id(igroup, ilevel_id or 0) or []
        flags = _cue.intensity.flags_from_entry(
            _cue.markers.get(create_vid_key(_cue.current_file) if _cue.current_file else "", {})
        )
        hook_tt = "Attached to intensity group '{}'.".format(igroup)
        if flags.enabled and flags.sfx_levels:
            hook_tt += "\n[" + CUE_INTENSITY_NOTE + "]"
        return _cue_pool_igroup_rows(
            level_files, preview_vol, detach_action, hook_tt, bool(flags.enabled and flags.sfx_levels)
        )
    rows = []  # type: List[TreeRowDict]
    if folder_label is not None:
        rows.extend(
            _cue_pool_virtual_rows(
                folder_label, folder_children, preview_vol, detach_action, marker_key, pool_index, child_remove_fn
            )
        )
    for index, ref in enumerate(files):
        rows.extend(
            _cue_pool_ref_rows(index, ref, preview_vol, remove_fn, remove_args, marker_key, pool_index, child_remove_fn)
        )
    return rows


def _cue_pool_virtual_rows(
    folder_label, folder_children, preview_vol, detach_action, marker_key, pool_index, child_remove_fn
):
    # type: (str, Optional[List[str]], float, Any, Optional[str], Optional[int], Any) -> List[TreeRowDict]
    """Virtual-folder header + expanded children (preset-backed pools)."""
    library = _cue.sfx.library
    expanded = library.expanded_file_refs.get(folder_label, False)
    buttons = []  # type: List[TreeButtonDict]
    if detach_action is not None:
        buttons.append({"icon": "xmark", "action": detach_action, "tt": "Remove preset"})
    buttons.append(
        {
            "icon": "play",
            "action": Function(_cue.sfx.preview_sfx, _cue_pick_file(folder_children or [""], False), preview_vol),
            "tt": "Play random file from preset",
        }
    )
    children = []  # type: List[TreeRowDict]
    if folder_children:
        children = [
            _cue_file_row(
                "pf:preset:{}:{}".format(folder_label, child),
                child,
                1,
                [
                    {
                        "icon": "xmark",
                        "action": Function(child_remove_fn, marker_key, pool_index, 0, child),
                        "tt": "Remove file from pool",
                    },
                    {
                        "icon": "play",
                        "action": Function(_cue.sfx.preview_sfx, child, preview_vol),
                        "tt": "Preview audio",
                    },
                ],
                size=11,
            )
            for child in folder_children
        ]
    return _cue_folder_rows(
        "pf:preset:" + folder_label,
        folder_label,
        0,
        Function(library.toggle_file_ref_expand, folder_label),
        expanded,
        False,
        buttons,
        children,
    )


def _cue_pool_ref_rows(index, ref, preview_vol, remove_fn, remove_args, marker_key, pool_index, child_remove_fn):
    # type: (int, str, float, Any, tuple, Optional[str], Optional[int], Any) -> List[TreeRowDict]
    """Rows for one pool ref: an expandable folder (children strip the folder
    prefix) or a plain file, both with an xmark wired through remove_fn."""
    library = _cue.sfx.library
    if ref.endswith("/"):
        expanded = library.expanded_file_refs.get(ref, False)
        children = [
            _cue_file_row(
                "pf:child:{}:{}".format(ref, child),
                child[len(ref) :],
                1,
                [
                    {
                        "icon": "xmark",
                        "action": Function(child_remove_fn, marker_key, pool_index, index, child),
                        "tt": "Remove file from the folder",
                    },
                    {
                        "icon": "play",
                        "action": Function(_cue.sfx.preview_sfx, child, preview_vol),
                        "tt": "Preview audio",
                    },
                ],
                size=11,
            )
            for child in _cue_resolve_files([ref])
        ]  # type: List[TreeRowDict]
        return _cue_folder_rows(
            "pf:folder:" + ref,
            ref,
            0,
            Function(library.toggle_file_ref_expand, ref),
            expanded,
            False,
            [
                {"icon": "xmark", "action": Function(remove_fn, *(remove_args + (index,))), "tt": "Remove folder"},
                {
                    "icon": "play",
                    "action": Function(_cue.sfx.preview_folder, ref, preview_vol),
                    "tt": "Play random file from folder",
                },
            ],
            children,
        )
    return [
        _cue_file_row(
            "pf:file:" + ref,
            ref,
            0,
            [
                {"icon": "xmark", "action": Function(remove_fn, *(remove_args + (index,))), "tt": "Remove file"},
                {"icon": "play", "action": Function(_cue.sfx.preview_sfx, ref, preview_vol), "tt": "Preview audio"},
            ],
            size=11,
        )
    ]


def _cue_pool_igroup_rows(level_files, preview_vol, detach_action, hook_tt, hint):
    # type: (List[str], float, Any, str, bool) -> List[TreeRowDict]
    """Read-only rows for an igroup-hooked pool: the level's files/folders
    with preview only, an optional detach xmark on each folder row, and the
    level-folder hint bar."""
    library = _cue.sfx.library
    rows = []  # type: List[TreeRowDict]
    for f in level_files:
        if f.endswith("/"):
            expanded = library.expanded_file_refs.get(f, False)
            buttons = []
            if detach_action is not None:
                buttons.append({"icon": "xmark", "action": detach_action, "tt": "Remove intensity level from pool"})
            buttons.append(
                {
                    "icon": "play",
                    "action": Function(_cue.sfx.preview_folder, f, preview_vol),
                    "tt": "Play random file from folder",
                }
            )
            row = {
                "key": "pf:ig:" + f,
                "type": "folder",
                "label": f,
                "depth": 0,
                "buttons": buttons,
                "toggle": Function(library.toggle_file_ref_expand, f),
                "tt": hook_tt,
            }  # type: TreeFolderRowDict
            if hint:
                row["bar_color"] = CUE_INTENSITY_HINT_COLOR
            rows.append(row)
            if expanded:
                for child in _cue_resolve_files([f]):
                    rows.append(
                        _cue_file_row(
                            "pf:ig:child:{}:{}".format(f, child),
                            child[len(f) :],
                            1,
                            [
                                {
                                    "icon": "play",
                                    "action": Function(_cue.sfx.preview_sfx, child, preview_vol),
                                    "tt": "Preview audio",
                                }
                            ],
                            gap=0,
                            size=11,
                        )
                    )
        else:
            rows.append(
                _cue_file_row(
                    "pf:ig:file:" + f,
                    f,
                    0,
                    [{"icon": "play", "action": Function(_cue.sfx.preview_sfx, f, preview_vol), "tt": "Preview audio"}],
                    size=11,
                )
            )
    return rows
