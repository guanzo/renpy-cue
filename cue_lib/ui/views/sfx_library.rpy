###############################################################################
# SFX Library Section
# Audio file browser with presets, video presets, and folder tree.
###############################################################################

screen cue_sfx_library(_is_video):
    style_group "cue"

    $ _sidebar_mode = _cue.sfx.library.is_sidebar_mode
    $ _ov_tt = "Sidebar Mode: When enabled, this section floats to the right as a sidebar.\n\n"
    $ _ov_tt = _ov_tt + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_SIDEBAR) + " to toggle sidebar mode.\n"
    $ _ov_tt = _ov_tt + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_LIBRARY)
    if _sidebar_mode:
        $ _ov_tt = _ov_tt + " to toggle sidebar visibility."
    else:
        $ _ov_tt = _ov_tt + " to toggle expansion."

    $ _icons = [{
        "name": ("rectangle-vertical-history-flip" if _sidebar_mode else "rectangle-vertical-history"),
        "action": Function(_cue.sfx.library.toggle_sidebar_mode),
        "tt": _ov_tt
    }]

    $ sfx_tt = (
        "Add {} files to\n{}\n\n"
        "Click the + button to add files to the selected \"Target\"\n\n"
        "Prefer adding folders over single files."
    ).format(", ".join(CUE_AUDIO_EXTS), _cue.paths.audio_dir)

    use cue_section_frame(CUE_SFX_LIBRARY_HEADER, tt=sfx_tt, icons=_icons):
        if not _cue.sfx.library.tree:
            if _cue.sfx.library.scan_error:
                etext _cue.sfx.library.scan_error color _cue_color_error
            etext "No audio files found in: {}".format(_cue.paths.audio_dir)
            etext ("Add {} files there "
                "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS))
        else:
            use cue_target_context()
            if _cue.sfx.library.add_to_pool_warning:
                etext _cue.sfx.library.add_to_pool_warning color _cue_color_error size 11
            null height 1
            use cue_search_bar("_cue.sfx.library.search_query", _cue.sfx.library)
            use cue_sfx_library_content(_is_video)

# Target-context bar: the [1]..[4] chips select where [+] rows dispatch.
# Current target highlighted; unavailable targets grayed (loop never grays).
# Second line shows the resolved target's active pool.
screen cue_target_context():
    style_group "cue"

    $ _target = _cue.markers.resolve_target_context()
    # Tooltips name the rebindable hotkey for each target (Settings > Keybinds).
    $ _tgt_video_tt = "Click the + button to add files to the Video SFX pool.\n"
    $ _tgt_video_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_VIDEO) + " to select."
    $ _tgt_image_tt = "Click the + button to add files to the Image SFX pool.\n"
    $ _tgt_image_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_IMAGE) + " to select."
    $ _tgt_dialogue_tt = "Click the + button to add files to the Dialogue SFX pool.\n"
    $ _tgt_dialogue_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_DIALOGUE) + " to select."
    $ _tgt_loop_tt = "Click the + button to add files to the Loop SFX pool.\n"
    $ _tgt_loop_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_LOOP) + " to select."
    hbox:
        spacing 2
        etext "Target:"
        use cue_select_btn("Video", (_target == CueContextType.VIDEO),
            Function(_cue.markers.set_target_context, CueContextType.VIDEO),
            tt=_tgt_video_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.VIDEO))
        use cue_select_btn("Image", (_target == CueContextType.IMAGE),
            Function(_cue.markers.set_target_context, CueContextType.IMAGE),
            tt=_tgt_image_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.IMAGE))
        use cue_select_btn("Dialogue", (_target == CueContextType.DIALOGUE),
            Function(_cue.markers.set_target_context, CueContextType.DIALOGUE),
            tt=_tgt_dialogue_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.DIALOGUE))
        use cue_select_btn("Loop", (_target == CueContextType.LOOP),
            Function(_cue.markers.set_target_context, CueContextType.LOOP),
            tt=_tgt_loop_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.LOOP))
    hbox:
        spacing 2
        etext "Pool:"
        etext _cue.markers.target_active_label()


screen cue_sfx_library_content(_is_video):
    style_group "cue"

    $ _q = _cue.sfx.library.search_query
    $ _searching = bool(_q.strip())
    # Preset/igroup names, filtered by the search query so the preset sections
    # join the file-tree search flow (same term semantics as the tree).  Pool
    # presets and intensity groups also match on their contents, so a search
    # surfaces a section when any file/folder inside it matches.  During a
    # search each section header only shows when something in it matches.
    $ _preset_names = _cue.markers.list_presets()
    $ _video_preset_names = _cue.markers.list_video_presets()
    $ _igroup_names = _cue.intensity.list_igroups()
    if _searching:
        $ _preset_names = [n for n in _preset_names if _cue_preset_search_matches(n, _q)]
        $ _video_preset_names = [n for n in _video_preset_names if _cue_query_matches(n, _q)]
        $ _igroup_names = [n for n in _igroup_names if _cue_igroup_search_matches(n, _q)]
    viewport:
        xfill True
        mousewheel True
        scrollbars "vertical"
        vscrollbar_unscrollable "hide"
        vbox:
            spacing 2
            $ _recent = _cue.sfx.library._recent
            $ _recent_entries = _recent.entries() if _recent is not None else []
            if _searching:
                $ _recent_entries = [e for e in _recent_entries if _cue_query_matches(e["ref"], _q)]
            if _recent is not None and (not _searching or _recent_entries):
                hbox:
                    spacing 2
                    use cue_txt_button("Recently Used/", Function(_recent.toggle))

                if _recent.expanded or _searching:
                    use cue_recent_list(_recent_entries)

            if not _searching or _preset_names:
                hbox:
                    spacing 2
                    use cue_txt_button("Pool Presets/", Function(_cue.sfx.library.toggle_presets_expand))

                # Rows auto-show during a search (like Recently Used) so a
                # content match is visible without expanding the section.
                if _searching or _cue.sfx.library.presets_expanded:
                    if not _preset_names:
                        etext "No pool presets yet. Save a pool as a preset to fill this." style "cue_help"
                    use cue_audio_presets_list(_preset_names, _q)

            if not _searching or _video_preset_names:
                hbox:
                    spacing 2
                    use cue_txt_button("Video Presets/", Function(_cue.sfx.library.toggle_video_presets_expand))

                if _cue.sfx.library.video_presets_expanded:
                    if not _video_preset_names:
                        etext "No video presets yet. Save video markers as a preset to fill this." style "cue_help"
                    use cue_video_presets_list(_is_video, _video_preset_names)

            use cue_intensity_group_row(_igroup_names, _searching, _q)

            $ _no_results = (_searching and not _recent_entries
                and not _preset_names
                and not _video_preset_names
                and not _igroup_names
                and not _cue.sfx.library.visible_tree)
            if _no_results:
                etext 'No files found for "{}".'.format(_q)
            else:
                use cue_file_tree()


# Recently Used rows, shown when the Recently Used folder is expanded.
# entries: filtered recent-entry dicts {type, ref}, most-recent-first.
# Rows act on the resolved target context (see cue_target_context); [+] sends
# the row there.  record=False so acting from this list doesn't re-feed it.
screen cue_recent_list(entries):
    style_group "cue"

    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _tgt_tt = _cue_target_assign_tt()

    if not entries:
        etext "Files you add to pools show up here."  style "cue_help"
    for _re in entries:
        hbox:
            spacing 2
            etext " "  # indent under Recently Used/
            if _re["type"] == "file":
                $ _re_idx = _cue.sfx.library._file_index.get(_re["ref"], -1)
                $ _re_ok = _re_idx >= 0
                use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, _re["ref"]))
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "file", _re_idx, False),
                    _tgt_tt, enabled=(_tgt_ok and _re_ok))
                null width 1
                etext _re["ref"] color _cue_color_text_accent
            elif _re["type"] == "folder":
                use cue_icon_btn(
                    "play",
                    Function(_cue.sfx.preview_folder, _re["ref"]),
                    "Play random file from folder")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "folder", _re["ref"], False),
                    _tgt_tt, enabled=_tgt_ok)
                null width 1
                etext _re["ref"] color _cue_color_text_accent
            else:  # preset
                use cue_icon_btn(
                    "play",
                    Function(_cue.sfx.preview_preset, _re["ref"]),
                    "Play random file from preset")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "preset", _re["ref"], False),
                    _tgt_tt, enabled=_tgt_ok)
                null width 1
                etext _re["ref"] color _cue_color_text_accent


# Audio preset rows, shown when the Presets folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
# search_query: active search term; rows are filtered to the matching files
# (content-matched presets show only what matched).
# [+] applies the preset to the resolved target context's active pool.
screen cue_audio_presets_list(name_filter=None, search_query=""):
    style_group "cue"

    $ _names = name_filter if name_filter is not None else _cue.markers.list_presets()
    $ _searching = bool(search_query.strip())
    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _tgt_tt = _cue_target_assign_tt()
    for _pname in _names:
        $ _pdata = _cue.markers.get_preset(_pname)
        $ _p_expanded = _cue.sfx.library.expanded_presets.get(_pname, False)
        $ _p_files = _cue_filter_preset_files(_pname, search_query)
        hbox:
            spacing 2
            etext " "  # indent under Presets/
            use cue_icon_btn("xmark", Function(_cue_confirm_delete_preset, _pname),
                "Delete preset" + CUE_HELP_SHIFT_SKIP_DELETE)
            use cue_icon_btn(
                "play",
                Function(_cue.sfx.preview_preset, _pname),
                "Play random file from preset")
            use cue_icon_btn(
                "plus",
                Function(_cue_markers_send, "preset", _pname),
                _tgt_tt, enabled=_tgt_ok)
            use cue_txt_button(_pname, Function(_cue.sfx.library.toggle_preset_expand, _pname))

        # File rows auto-show during a search (like the tree) so a
        # content-matched preset reveals what matched without a click.
        if _p_expanded or _searching:
            for _child in _p_files:
                hbox:
                    spacing 2
                    etext "  "
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.markers.preset_remove_file, _pname, _child),
                        "Remove file from preset")
                    use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, _child), "Preview file")
                    null width 1
                    etext _child color _cue_color_text_accent size 11


# Video preset rows, shown when the Video Presets folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
# Rows keep the dedicated apply-video-markers button -- no [+] here.
screen cue_video_presets_list(_is_video, name_filter=None):
    style_group "cue"

    $ _names = name_filter if name_filter is not None else _cue.markers.list_video_presets()
    for _vpname in _names:
        $ _vpdata = _cue.markers.get_video_preset(_vpname)
        $ _vp_expanded = _cue.sfx.library.expanded_video_presets.get(_vpname, False)
        $ _vp_pools = _vpdata.get("pools", []) if _vpdata else []
        hbox:
            spacing 2
            etext " "  # indent under Video Presets/
            use cue_icon_btn(
                "xmark",
                Function(_cue_confirm_delete_video_preset, _vpname),
                "Delete video preset" + CUE_HELP_SHIFT_SKIP_DELETE)
            use cue_icon_btn(
                "v",
                Function(_cue_maybe_apply_video_preset, _vpname),
                "Apply video markers to the current video.\nOverwrites existing markers.",
                enabled=_is_video)
            use cue_txt_button(_vpname, Function(_cue.sfx.library.toggle_video_preset_expand, _vpname))

        # Pool rows are timestamp folders; expanding one reveals its files
        # (same shape as an expanded audio preset's file rows).
        if _vp_expanded:
            $ _vp_pools_state = _cue.sfx.library.expanded_video_pools.get(_vpname, {})
            for _pool_index, _pool in enumerate(_vp_pools):
                $ _pool_label = _cue_format_time(_pool.get("time", 0))
                $ _pool_expanded = _vp_pools_state.get(_pool_index, False)
                $ _pool_files = _cue_resolve_files(_pool.get("files", []))
                hbox:
                    spacing 2
                    etext "  "
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue_confirm_remove_video_preset_pool, _vpname, _pool_index),
                        "Remove this pool from the video preset" + CUE_HELP_SHIFT_SKIP_DELETE)
                    use cue_icon_btn(
                        "play",
                        Function(_cue.sfx.preview_video_pool, _vpname, _pool_index),
                        "Play random file from this pool")
                    use cue_txt_button(
                        _pool_label,
                        Function(_cue.sfx.library.toggle_video_pool_expand, _vpname, _pool_index))

                if _pool_expanded:
                    for _child in _pool_files:
                        hbox:
                            spacing 2
                            etext "    "
                            use cue_icon_btn(
                                "xmark",
                                Function(_cue.markers.remove_video_preset_pool_file, _vpname, _pool_index, _child),
                                "Remove file from pool")
                            use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, _child), "Preview file")
                            null width 1
                            etext _child color _cue_color_text_accent size 11

screen cue_intensity_group_row(igroup_names, searching, search_query=""):
    # The parent (cue_sfx_library_content) filters igroup names by the search
    # query and passes them here -- a `use`d screen gets its own scope, so
    # _searching/_q from the caller aren't visible.  Rows auto-show during a
    # search (like Recently Used) so a content match is visible without
    # expanding the section.
    if not searching or igroup_names:
        use cue_txt_button("Intensity Groups/", Function(_cue.sfx.library.toggle_igroups_expand))

        if searching or _cue.sfx.library.igroups_expanded:
            hbox:
                spacing 2
                etext " "  # indent
                use cue_txt_button("+ Group", Function(_cue.dialogs.intensity.open),
                    tt="Create a new intensity group.")

            use cue_intensity_groups_list(igroup_names, search_query)
# Intensity group rows, shown when the Intensity Groups/ block is expanded.
# Each igroup row expands to its ordered level rows (folder order = level
# order).  The folder-plus button toggles add-folder mode for that group (one
# group at a time); while active, a tree folder's + adds it directly.  The
# other group folders (B, C...) are never added to pools here -- usage is the
# pool-side hook, handled in the Video SFX inspector.
# search_query: active search term; level rows are filtered to the matching
# folders (content-matched groups show only what matched).
screen cue_intensity_groups_list(igroup_names, search_query=""):
    style_group "cue"

    $ _indent = " "

    if not igroup_names:
        etext _indent + "No intensity groups yet." style "cue_help"
        etext (_indent + "An intensity group is a soft-to-hard folder list; "
               "folder order is the level order.") style "cue_help"

    $ _searching = bool(search_query.strip())
    # [V] sends the level folder to the active video marker's pool, ignoring
    # the target-context selector above.  Video context must be on screen.
    $ _vid_ok = _cue.markers.target_is_available(CueContextType.VIDEO)
    $ _v_tt = _cue_send_folder_to_video_tt()
    for _gname in igroup_names:
        $ _gdata = _cue.intensity.get_igroup(_gname)
        $ _g_folders = _cue_filter_igroup_folders(_gname, search_query)
        $ _g_expanded = _cue.sfx.library.expanded_igroups.get(_gname, False)
        $ _in_add = (_cue.sfx.library.igroup_add_target == _gname)
        hbox:
            spacing 2
            etext _indent
            use cue_icon_btn("xmark", Function(_cue_confirm_delete_igroup, _gname),
                "Delete intensity group" + CUE_HELP_SHIFT_SKIP_DELETE)
            use cue_icon_btn(("folder-open" if _in_add else "folder-plus"),
                Function(_cue.sfx.library.toggle_igroup_add_mode, _gname),
                ("Click again to stop adding folders" if _in_add
                 else "Add folders to this group"),
                bg=(_cue_color_selected_alt if _in_add else None))
            use cue_txt_button(_gname, Function(_cue.sfx.library.toggle_igroup_expand, _gname))

        # Level rows auto-show during a search (like the tree) so a
        # content-matched group reveals what matched without a click.
        if _g_expanded or _searching:
            # The level buttons are index-based and must not run on the
            # filtered view -- hide them (and the level label) while searching.
            if not _searching and not _g_folders:
                etext "  No levels yet. Click the group's folder button to add files." style "cue_help"
                text "  Add up to ~[CUE_INTENSITY_IDEAL_LEVELS] levels for the best experience." style "cue_help"
                null height 2
            for _idx in range(len(_g_folders)):
                $ _folder = _g_folders[_idx]
                hbox:
                    spacing 2
                    etext _indent * 2
                    if not _searching:
                        use cue_icon_btn("xmark",
                            Function(_cue.intensity.remove_level, _gname, _idx),
                            "Remove this level")
                        use cue_icon_btn("chevron-up",
                            Function(_cue.intensity.move_level, _gname, _idx, -1),
                            "Move level up", enabled=(_idx > 0))
                        use cue_icon_btn("chevron-down",
                            Function(_cue.intensity.move_level, _gname, _idx, 1),
                            "Move level down", enabled=(_idx < len(_g_folders) - 1))
                    use cue_icon_btn("play",
                        Function(_cue.sfx.preview_folder, _folder),
                        "Play random file from folder")
                    use cue_icon_btn("v",
                        Function(_cue_send_folder_to_video, _folder),
                        _v_tt, enabled=_vid_ok)
                    etext "Level {}:".format(_idx + 1) color _cue_color_text_accent size 11
                    null width 1
                    etext _folder color _cue_color_text_accent size 11


# Folder/file rows for the current audio tree.
# [+] sends the row to the resolved target context's active pool (see
# cue_target_context).  Shift+Click on [+] creates a new pool first.
screen cue_file_tree():
    style_group "cue"

    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _tgt_tt = _cue_target_assign_tt()
    # An active igroup add-folder target turns the tree's + into a level
    # adder for that group (one group at a time).
    $ _igroup_target = _cue.sfx.library.igroup_add_target
    # {audio_dir-prefixed path: reason} for WAVs the converter can't make playable.
    $ _unplayable = _cue.sfx.unplayable_files()

    for item in _cue.sfx.library.visible_tree:
        hbox:
            spacing 2
            # Indent
            if item["depth"] > 0:
                etext " " * item["depth"]
            if item["type"] == "folder":
                if item["has_files"]:
                    use cue_icon_btn(
                        "play",
                        Function(_cue.sfx.preview_folder, item["full_path"]),
                        "Play random file from folder")
                    if _igroup_target is not None:
                        $ _tgt_data = _cue.intensity.get_igroup(_igroup_target)
                        $ _tgt_folders = _tgt_data.get("folders", []) if _tgt_data else []
                        $ _is_dup = item["full_path"] in _tgt_folders
                        use cue_icon_btn("plus",
                            Function(_cue.sfx.library.igroup_add_folder, _igroup_target, item["full_path"]),
                            "Add this folder to the {} intensity group.".format(_igroup_target),
                            enabled=(not _is_dup),
                            bg=(_cue_color_selected_alt if not _is_dup else None))
                    else:
                        use cue_icon_btn(
                            "plus",
                            Function(_cue_markers_send, "folder", item["full_path"]),
                            _tgt_tt, enabled=_tgt_ok)
                use cue_txt_button(item["name"], Function(_cue.sfx.library.toggle_folder, item["full_path"]))
            else:
                # Play preview
                use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, item["full_path"]), "Preview audio")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "file", item["index"]),
                    _tgt_tt, enabled=_tgt_ok)
                null width 1
                etext item["name"] color _cue_color_text_accent
                $ _bad_reason = _unplayable.get(_cue.paths.audio_dir + item["full_path"], "")
                if _bad_reason:
                    use cue_icon(
                        "triangle-exclamation",
                        tt=("Invalid file: " + _bad_reason),
                        icon_color=_cue_color_warn)
