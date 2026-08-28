# -*- coding: utf-8 -*-
# SFX Library tree row buttons + warn.  CueSfxTreeRows builds the full SFX
# content stream (recent, presets, video presets, intensity groups, file tree)
# and the tree row buttons/warn variants over CueTreeRowsBuilder.  It reaches
# the library tree (and its CueSfxManager back-ref) through _tree, so it never
# imports the concrete managers (no import cycle).

import renpy

from renpy.store import Function

from cue_lib.audio.tree.tree_rows import (
    CUE_SETTINGS_FOLDER_TIP,
    CueTreeRowsBuilder,
    _cue_action_row,
    _cue_actions_row,
    _cue_external_empty_rows,
    _cue_file_row,
    _cue_folder_rows,
    _cue_help_row,
    _cue_section_rows,
)
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
    _cue_confirm_delete_preset,
    _cue_confirm_delete_video_preset,
    _cue_confirm_remove_video_preset_pool,
    _cue_maybe_apply_video_preset,
)
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
    from typing import Any, Dict, List

    from cue_lib._types import TreeActionRowDict, TreeButtonDict, TreeRowDict


class CueSfxTreeRows(CueTreeRowsBuilder):
    """SFX Library tree row buttons + warn.  Reaches the library tree (and its
    CueSfxManager back-ref) through _tree."""

    def row_buttons(self, item, target_ok, target_tt, unplayable):  # pyright: ignore[reportIncompatibleMethodOverride]
        # type: (Dict[str, Any], bool, str, Dict[str, str]) -> List[TreeButtonDict]
        """SFX row buttons: [play, plus].  Plus adds to the target context, or
        in intensity add-mode appends to the active (group, level).  An empty
        folder gets no buttons (matches the current tree UI).

        Display paths carry the synthetic wrapper ("SFX/..." for
        built-in, "ExtA/..." for external); every action that feeds a path
        uses ref_from_display to get the stored ref.  The file [+] is
        index-based and stays."""
        buttons = []  # type: List[TreeButtonDict]
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
        # type: (Dict[str, Any], str, bool, str, str) -> TreeButtonDict
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
        # type: (List[Dict[str, str]], bool, str) -> List[TreeRowDict]
        """Recently-Used rows.  Each entry is {"type", "ref"} (file / folder /
        preset).  File rows resolve a concrete _file_index so the [+] can send
        an index; all [+]s send record=False so acting from this list does not
        re-feed it.  Empty list yields the muted empty-state line."""
        if not entries:
            return [_cue_help_row("recent:empty", "Files you add to pools show up here.")]
        rows = []  # type: List[TreeRowDict]
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
                ]  # type: List[TreeButtonDict]
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
                ]  # type: List[TreeButtonDict]
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
                ]  # type: List[TreeButtonDict]
            rows.append(_cue_file_row("recent:" + ref, ref, 1, buttons))
        return rows

    def _preset_rows(self, preset_names, search_query, target_ok, target_tt):
        # type: (List[str], str, bool, str) -> List[TreeRowDict]
        """Pool Preset rows: one collapsible folder row per preset, then its
        filtered files while expanded or searching.  Files auto-show during a
        search so a content-matched preset reveals what matched (like the
        tree's matching-folder rule)."""
        searching = bool(search_query.strip())
        rows = []  # type: List[TreeRowDict]
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
            ]  # type: List[TreeButtonDict]
            children = [
                _cue_file_row(
                    "preset:" + pname + "/" + child,
                    child,
                    2,
                    [
                        {
                            "icon": "xmark",
                            "action": Function(_cue.presets.audio.preset_remove_file, pname, child),
                            "tt": "Remove file from preset",
                        },
                        {"icon": "play", "action": Function(self._tree._sfx.preview_sfx, child), "tt": "Preview file"},
                    ],
                    size=11,
                )
                for child in _cue_filter_preset_files(pname, search_query)
            ]  # type: List[TreeRowDict]
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
        # type: (List[str], bool) -> List[TreeRowDict]
        """Video Preset rows: preset folder -> timestamp pools (depth 2) ->
        pool files (depth 3, size 11).  Pools reveal only on explicit expand
        (no search auto-show, matching the video preset screen); the apply-v
        button is gated on is_video."""
        rows = []  # type: List[TreeRowDict]
        for vpname in video_preset_names:
            data = _cue.presets.video.get(vpname)
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
            ]  # type: List[TreeButtonDict]
            pool_rows = []  # type: List[TreeRowDict]
            pool_state = self._tree.expanded_video_pools.get(vpname, {})
            for pool_index, pool in enumerate(pools):
                pool_label = _cue_format_time(pool.get("time", 0))
                pool_expanded = pool_state.get(pool_index, False)
                pool_files = _cue_resolve_files(pool.get("files", []))
                children = [
                    _cue_file_row(
                        "vpreset:" + vpname + "/" + str(pool_index) + "/" + child,
                        child,
                        3,
                        [
                            {
                                "icon": "xmark",
                                "action": Function(
                                    _cue.presets.video.remove_video_preset_pool_file, vpname, pool_index, child
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
                ]  # type: List[TreeRowDict]
                pool_rows.extend(
                    _cue_folder_rows(
                        "vpreset:" + vpname + "/" + str(pool_index),
                        pool_label,
                        2,
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
        # type: (List[str], str, bool, str) -> List[TreeRowDict]
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
        ]  # type: List[TreeRowDict]
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
            children = []  # type: List[TreeRowDict]
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
                buttons = []  # type: List[TreeButtonDict]
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
                hover = []  # type: List[TreeButtonDict]
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
                level_children = []  # type: List[TreeRowDict]
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
        # type: (str, object, str) -> List[TreeRowDict]
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
            ]  # type: List[TreeRowDict]
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
        # type: (str, List[str], List[str], List[str], bool, bool, Dict[str, str]) -> List[TreeRowDict]
        """Full SFX Library section stream: Recently Used, Pool Presets, Video
        Presets, Intensity Groups, then the file tree.  Name lists arrive raw
        from the other managers and are search-filtered here (the current
        screen filters them the same way); recent entries are gathered from the
        tree's own CueRecentManager.  tgt_tt and the intensity hook state are
        resolved from the marker context here."""
        searching = bool(search_query.strip())
        tree = self._tree
        # Truly-empty library (no built-in files, no external folders): only the
        # built-in empty state -- message, open-folder, curated-pack download.
        # The screen hides the section chrome (target/search) in this case too.
        if not tree.builtin_tree and not tree.external_sources:
            return self._builtin_empty_rows(tree)
        tgt_tt = _cue_target_assign_tt()
        rows = []  # type: List[TreeRowDict]
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
        if not tree.builtin_tree:
            rows.extend(self._builtin_empty_rows(tree))
        rows.extend(_cue_external_empty_rows(tree, "audio files"))
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

    def _builtin_empty_rows(self, tree):
        # type: (Any) -> List[TreeRowDict]
        """Built-in source empty rows: scan error, no-files message, add hint,
        an Open-folder + curated-pack download action row, and the settings
        tip.  Shared by the truly-empty early return and the per-source empty
        block so the SFX empty state has a single construction site."""
        rows = []  # type: List[TreeRowDict]
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
        rows.append(_cue_help_row("builtin:settings_tip", CUE_SETTINGS_FOLDER_TIP, plain=True))
        rows.append(
            _cue_actions_row(
                "builtin:open_dl",
                [
                    _cue_action_row("builtin:open", "Open Audio folder", explorer=tree._paths.audio_dir),
                    self._download_pack_button(tree),
                ],
            )
        )

        rows.extend(self._download_pack_status_rows(tree))
        return rows

    def _download_pack_button(self, tree):
        # type: (Any) -> TreeActionRowDict
        """The curated-pack download button (icon + label).  Label and
        sensitivity follow the pack state; purely presentational -- the state
        poll timer lives in cue_runtime_timers, gated on the pack state."""
        pack = tree.sfx_pack
        st = pack.state
        if st == "downloading":
            label, sensitive = "Downloading...", False
        elif st == "done":
            label, sensitive = "Loading pack...", False
        else:
            label = "Retry download" if st == "error" else "Download Cue SFX Pack"
            sensitive = True
        return _cue_action_row(
            "builtin:download_pack", label, Function(pack.download_sfx_pack), sensitive=sensitive, icon="download"
        )

    def _download_pack_status_rows(self, tree):
        # type: (Any) -> List[TreeRowDict]
        """Progress / loading / error lines under the pack download button."""
        pack = tree.sfx_pack
        st = pack.state
        if st == "downloading":
            rows = [  # type: List[TreeRowDict]
                _cue_help_row(
                    "builtin:download_progress", "Downloading Cue SFX Pack... {:.0%}".format(pack.progress), plain=True
                )
            ]
        elif st == "done":
            row = _cue_help_row("builtin:download_loading", "Pack downloaded - loading sounds...", plain=True)
            rows = [row]  # type: List[TreeRowDict]
        elif st == "error":
            rows = [  # type: List[TreeRowDict]
                _cue_help_row(
                    "builtin:download_error",
                    pack.error,
                    color=getattr(renpy.store, "_cue_color_error", None),
                    plain=True,
                )
            ]
        else:
            rows = []
        return rows

    def _preset_children(self, preset_names, search_query, target_ok, target_tt):
        # type: (List[str], str, bool, str) -> List[TreeRowDict]
        """Pool Presets children: the empty-state line, then the preset rows."""
        rows = []  # type: List[TreeRowDict]
        if not preset_names:
            rows.append(
                _cue_help_row("presets:empty", "No pool presets yet. Save a pool as a preset to fill this.")
            )
        rows.extend(self._preset_rows(preset_names, search_query, target_ok, target_tt))
        return rows

    def _video_preset_children(self, video_preset_names, is_video):
        # type: (List[str], bool) -> List[TreeRowDict]
        """Video Presets children: the empty-state line, then the preset rows."""
        rows = []  # type: List[TreeRowDict]
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
