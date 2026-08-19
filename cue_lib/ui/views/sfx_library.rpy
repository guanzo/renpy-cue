###############################################################################
# SFX Library Section
# Audio file browser with presets, video presets, and folder tree.
###############################################################################

screen cue_sfx_library(_is_video):
    style_group "cue"

    $ _overlay_mode = _cue.sfx_manager.overlay_mode
    $ _ov_tt = "Overlay Mode: When enabled, this section will float on top when expanded.\n\n"
    $ _ov_tt = _ov_tt + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_LIBRARY) + " to toggle expansion."

    $ _icons = [{
        "name": "window-maximize" if _overlay_mode else "window-restore",
        "action": Function(_cue.sfx_manager.toggle_overlay_mode),
        "tt": _ov_tt
    }]

    $ sfx_tt = (
        "Add {} files to\n{}\n\n"
        "Click the + button to send files to the selected \"Target\""
    ).format(", ".join(CUE_AUDIO_EXTS), _cue.paths.audio_dir)

    use cue_section_frame(CUE_SFX_LIBRARY_HEADER, tt=sfx_tt, icons=_icons):
        if not _cue.sfx_manager.tree:
            if _cue.sfx_manager.scan_error:
                text "[_cue.sfx_manager.scan_error]" color _cue_color_error
            text "No audio files found in: [_cue.paths.audio_dir]"
            text ("Add {} files there "
                "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS))
        else:
            use cue_target_context()
            null height 2
            use cue_search_bar("_cue.sfx_manager.search_query", _cue.sfx_manager)
            use cue_sfx_library_content(_is_video)

# Target-context bar: the [1]..[4] chips select where [+] rows dispatch.
# Current target highlighted; unavailable targets grayed (loop never grays).
# Second line shows the resolved target's active pool.
screen cue_target_context():
    style_group "cue"

    $ _target = _cue.markers.resolve_target_context()
    # Tooltips name the rebindable hotkey for each target (Settings > Keybinds).
    $ _tgt_video_tt = "Click the + button to send files to the Video SFX pool.\n"
    $ _tgt_video_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_VIDEO) + " to select."
    $ _tgt_image_tt = "Click the + button to send files to the Image SFX pool.\n"
    $ _tgt_image_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_IMAGE) + " to select."
    $ _tgt_dialogue_tt = "Click the + button to send files to the Dialogue SFX pool.\n"
    $ _tgt_dialogue_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_DIALOGUE) + " to select."
    $ _tgt_loop_tt = "Click the + button to send files to the Loop SFX pool.\n"
    $ _tgt_loop_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_LOOP) + " to select."
    hbox:
        spacing 2
        text "Target:"
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
        text "Pool:"
        text _cue.markers.target_active_label()


screen cue_sfx_library_content(_is_video):
    style_group "cue"

    $ _q = _cue.sfx_manager.search_query
    $ _searching = bool(_q.strip())
    # Preset names, filtered by the search query so the preset sections join
    # the file-tree search flow (same term semantics as the tree).  During a
    # search each section header only shows when something in it matches.
    $ _preset_names = _cue.markers.list_presets()
    $ _video_preset_names = _cue.markers.list_video_presets()
    if _searching:
        $ _preset_names = [n for n in _preset_names if _cue_query_matches(n, _q)]
        $ _video_preset_names = [n for n in _video_preset_names if _cue_query_matches(n, _q)]
    viewport:
        xfill True
        yfill True
        mousewheel True
        scrollbars "vertical"
        vscrollbar_unscrollable "hide"
        vbox:
            spacing 2
            $ _recent = _cue.sfx_manager._recent
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
                    use cue_txt_button("Pool Presets/", Function(_cue.sfx_manager.toggle_presets_expand))

                if _cue.sfx_manager.presets_expanded:
                    if not _preset_names:
                        text "No pool presets yet. Save a pool as a preset to fill this." style "cue_help"
                    use cue_audio_presets_list(_preset_names)

            if not _searching or _video_preset_names:
                hbox:
                    spacing 2
                    use cue_txt_button("Video Presets/", Function(_cue.sfx_manager.toggle_video_presets_expand))

                if _cue.sfx_manager.video_presets_expanded:
                    if not _video_preset_names:
                        text "No video presets yet. Save video markers as a preset to fill this." style "cue_help"
                    use cue_video_presets_list(_is_video, _video_preset_names)

            $ _no_results = (_searching and not _recent_entries
                and not _preset_names
                and not _video_preset_names
                and not _cue.sfx_manager.visible_tree)
            if _no_results:
                text 'No files found for "{}".'.format(_q)
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
        text "Files you add to pools show up here."  style "cue_help"
    for _re in entries:
        hbox:
            spacing 2
            text " "  # indent under Recently Used/
            if _re["type"] == "file":
                $ _re_idx = _cue.sfx_manager._file_index.get(_re["ref"], -1)
                $ _re_ok = _re_idx >= 0
                use cue_icon_btn("play", Function(_cue_preview_sfx, _re["ref"]), "Preview audio")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "file", _re_idx, False),
                    _tgt_tt, enabled=(_tgt_ok and _re_ok))
                null width 1
                text _re["ref"] color _cue_color_text_accent
            elif _re["type"] == "folder":
                use cue_icon_btn(
                    "play",
                    Function(_cue_preview_folder, _re["ref"]),
                    "Play random file from folder")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "folder", _re["ref"], False),
                    _tgt_tt, enabled=_tgt_ok)
                null width 1
                text _re["ref"] color _cue_color_text_accent
            else:  # preset
                use cue_icon_btn(
                    "play",
                    Function(_cue_preview_preset, _re["ref"]),
                    "Play random file from preset")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "preset", _re["ref"], False),
                    _tgt_tt, enabled=_tgt_ok)
                null width 1
                text _re["ref"] color _cue_color_text_accent


# Audio preset rows, shown when the Presets folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
# [+] applies the preset to the resolved target context's active pool.
screen cue_audio_presets_list(name_filter=None):
    style_group "cue"

    $ _names = name_filter if name_filter is not None else _cue.markers.list_presets()
    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _tgt_tt = _cue_target_assign_tt()
    for _pname in _names:
        $ _pdata = _cue.markers.get_preset(_pname)
        $ _p_expanded = _cue.sfx_manager.expanded_presets.get(_pname, False)
        $ _p_files = _cue_resolve_files(_pdata.get("files", [])) if _pdata else []
        hbox:
            spacing 2
            text " "  # indent under Presets/
            use cue_icon_btn("xmark", Function(_cue_confirm_delete_preset, _pname), "Delete preset")
            use cue_icon_btn(
                "play",
                Function(_cue_preview_preset, _pname),
                "Play random file from preset")
            use cue_icon_btn(
                "plus",
                Function(_cue_markers_send, "preset", _pname),
                _tgt_tt, enabled=_tgt_ok)
            use cue_txt_button(_pname, Function(_cue.sfx_manager.toggle_preset_expand, _pname))

        if _p_expanded:
            for _child in _p_files:
                hbox:
                    spacing 2
                    text "  "
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.markers.preset_remove_file, _pname, _child),
                        "Remove file from preset")
                    use cue_icon_btn("play", Function(_cue_preview_sfx, _child), "Preview file")
                    null width 1
                    text _child color _cue_color_text_accent size 11


# Video preset rows, shown when the Video Presets folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
# Rows keep the dedicated apply-video-markers button -- no [+] here.
screen cue_video_presets_list(_is_video, name_filter=None):
    style_group "cue"

    $ _names = name_filter if name_filter is not None else _cue.markers.list_video_presets()
    for _vpname in _names:
        $ _vpdata = _cue.markers.get_video_preset(_vpname)
        $ _vp_expanded = _cue.sfx_manager.expanded_video_presets.get(_vpname, False)
        $ _vp_pools = _vpdata.get("pools", []) if _vpdata else []
        hbox:
            spacing 2
            text " "  # indent under Video Presets/
            use cue_icon_btn(
                "xmark",
                Function(_cue_confirm_delete_video_preset, _vpname),
                "Delete video preset")
            use cue_icon_btn(
                "play",
                Function(_cue_preview_video_preset, _vpname),
                "Play random file from video preset")
            use cue_icon_btn(
                "V",
                Function(_cue_maybe_apply_video_preset, _vpname),
                "Apply video markers to the current video.\nOverwrites existing markers.",
                enabled=_is_video)
            use cue_txt_button(_vpname, Function(_cue.sfx_manager.toggle_video_preset_expand, _vpname))

        if _vp_expanded:
            for _pool in _vp_pools:
                $ _pool_time = _pool.get("time", 0)
                $ _pool_files = len(_cue_resolve_files(_pool.get("files", [])))
                $ _pool_label = "{} ({} files)".format(_cue_format_time(_pool_time), _pool_files)
                hbox:
                    spacing 2
                    text "  "
                    text _pool_label color _cue_color_text_accent size 11


# Folder/file rows for the current audio tree.
# [+] sends the row to the resolved target context's active pool (see
# cue_target_context).  Shift+Click on [+] creates a new pool first.
screen cue_file_tree():
    style_group "cue"

    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _tgt_tt = _cue_target_assign_tt()

    for item in _cue.sfx_manager.visible_tree:
        hbox:
            spacing 2
            # Indent
            if item["depth"] > 0:
                text " " * item["depth"]
            if item["type"] == "folder":
                if item["has_files"]:
                    use cue_icon_btn(
                        "play",
                        Function(_cue_preview_folder, item["full_path"]),
                        "Play random file from folder")
                    use cue_icon_btn(
                        "plus",
                        Function(_cue_markers_send, "folder", item["full_path"]),
                        _tgt_tt, enabled=_tgt_ok)
                use cue_txt_button(item["name"], Function(_cue.sfx_manager.toggle_folder, item["full_path"]))
            else:
                # Play preview
                use cue_icon_btn("play", Function(_cue_preview_sfx, item["full_path"]), "Preview audio")
                use cue_icon_btn(
                    "plus",
                    Function(_cue_markers_send, "file", item["index"]),
                    _tgt_tt, enabled=_tgt_ok)
                null width 1
                text item["name"] color _cue_color_text_accent
