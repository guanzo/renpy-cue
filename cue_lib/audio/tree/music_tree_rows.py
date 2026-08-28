# -*- coding: utf-8 -*-
# Music Library tree row buttons.  CueMusicTreeRows builds the full music
# content stream (recent, presets, per-source empty states, combined tree)
# over CueTreeRowsBuilder.  It reaches the combined tree and its CueMusicManager
# back-ref through _tree, so it never imports the concrete managers (no import
# cycle).

import renpy

from renpy.store import Function

from cue_lib.audio.tree.tree_rows import (
    CUE_SETTINGS_FOLDER_TIP,
    CueTreeRowsBuilder,
    _cue_action_row,
    _cue_external_empty_rows,
    _cue_file_row,
    _cue_folder_rows,
    _cue_help_row,
    _cue_section_rows,
)
from cue_lib.constants import CUE_AUDIO_EXTS, CUE_HELP_SHIFT_SKIP_DELETE
from cue_lib.state import _cue
from cue_lib.ui.dialogs import _cue_confirm_delete_music_preset
from cue_lib.util import _cue_query_matches

MYPY = False
if MYPY:
    from typing import Any, Dict, List


def _cue_preview_music_preset(preset_name):
    # type: (str) -> None
    """Play a random song from a preset.

    Lazy _cue.music bind: Function() builds rows before the singleton's music
    manager is wired in unit tests, so dereferencing it here (at click time)
    instead of in the row's action keeps row construction manager-free."""
    _cue.music.preview_preset(preset_name)


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
            pdata = music._presets.music.get(pname)
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
            rows.append(_cue_help_row("user:settings_tip", CUE_SETTINGS_FOLDER_TIP, plain=True))
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
        rows.extend(_cue_external_empty_rows(self._tree, "music"))
        # -- no-results guard + tree -----------------------------------------
        if self._tree.user_tree or self._tree.game_tree or self._tree.external_sources:
            if searching and not recent_entries and not preset_names and not self._tree.visible_tree:
                rows.append(_cue_help_row("no_results", 'No files found for "{}".'.format(search_query), plain=True))
            else:
                rows.extend(self.tree_rows(current_file))
        return rows
