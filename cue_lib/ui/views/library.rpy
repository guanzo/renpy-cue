###############################################################################
# SFX Library Section
# Audio file browser with presets, video presets, and folder tree.
###############################################################################

screen cue_sfx_library(_is_video, _has_image, _is_dialogue):
    $ _overlay_mode = _cue.sfx_manager.overlay_mode
    $ _ov_tt = "Overlay Mode\nWhen enabled, this section will float on top when expanded.\n"
    $ _ov_tt = _ov_tt + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX) + " to toggle expansion."

    $ _icons = [{
        "name": "square-plus" if _overlay_mode else "square-minus", 
        "action": Function(_cue.sfx_manager.toggle_overlay_mode), 
        "tt": _ov_tt
    }]

    $ sfx_tt = "Add SFX files to\n{}".format(_cue.paths.audio_dir)
    use cue_section_frame(CUE_SFX_LIBRARY_HEADER, tt=sfx_tt, icons=_icons):
        if not _cue.sfx_manager.tree:
            if _cue.sfx_manager.scan_error:
                text "[_cue.sfx_manager.scan_error]" style "cue_txt" color _cue_color_error
            text ("Place {} files there "
                "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS)) style "cue_txt"
        else:
            use cue_search_bar("_cue.sfx_manager.search_query", _cue.sfx_manager)
            null height 5
            use cue_sfx_library_content(_is_video, _has_image, _is_dialogue)

screen cue_sfx_library_content(_is_video, _has_image, _is_dialogue):
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
        style_group "cue"
        vscrollbar_unscrollable "hide"
        vbox:
            spacing 2
            if not _searching or _preset_names:
                hbox:
                    spacing 2
                    use cue_txt_button("Presets/", Function(_cue.sfx_manager.toggle_presets_expand))

                if _cue.sfx_manager.presets_expanded:
                    use cue_audio_presets_list(_is_video, _has_image, _is_dialogue, _preset_names)

            if not _searching or _video_preset_names:
                hbox:
                    spacing 2
                    use cue_txt_button("Video Presets/", Function(_cue.sfx_manager.toggle_video_presets_expand))

                if _cue.sfx_manager.video_presets_expanded:
                    use cue_video_presets_list(_is_video, _has_image, _is_dialogue, _video_preset_names)

            if _searching and not _preset_names and not _video_preset_names and not _cue.sfx_manager.visible_tree:
                text 'No files found for "{}".'.format(_q) style "cue_txt"
            else:
                use cue_file_tree(_is_video, _has_image, _is_dialogue)


# Audio preset rows, shown when the Presets folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
screen cue_audio_presets_list(_is_video, _has_image, _is_dialogue, name_filter=None):
    $ _names = name_filter if name_filter is not None else _cue.markers.list_presets()
    # Tooltip strings per marker type (screen-local).  The _*_tt_has variant
    # is shown once a pool exists; _*_tt_create until the first pool.
    $ _vid_tt_create = "Create pool at current timestamp and apply preset"
    $ _vid_tt_has = "Click: Apply preset to active Video SFX pool\nShift+Click: " + _vid_tt_create
    $ _img_tt_create = "Create Image SFX pool and apply preset"
    $ _img_tt_has = "Click: Apply preset to active Image SFX pool\nShift+Click: " + _img_tt_create
    $ _dlg_tt_create = "Create Dialogue SFX pool and apply preset"
    $ _dlg_tt_has = "Click: Apply preset to active Dialogue SFX pool\nShift+Click: " + _dlg_tt_create
    $ _loop_tt_create = "Create Loop SFX pool and apply preset"
    $ _loop_tt_has = "Click: Apply preset to active Loop SFX pool\nShift+Click: " + _loop_tt_create
    $ _vid_tt = _vid_tt_has if _cue.markers.video.has_pools() else _vid_tt_create
    $ _img_tt = _img_tt_has if _cue.markers.image.has_pools() else _img_tt_create
    $ _dlg_tt = _dlg_tt_has if _cue.markers.dialogue.has_pools() else _dlg_tt_create
    $ _loop_tt = _loop_tt_has if _cue.markers.loop.has_pools() else _loop_tt_create
    for _pname in _names:
        $ _pdata = _cue.markers.get_preset(_pname)
        $ _p_expanded = _cue.sfx_manager.expanded_presets.get(_pname, False)
        $ _p_files = _cue_resolve_files(_pdata.get("files", [])) if _pdata else []
        hbox:
            spacing 2
            text "  " style "cue_txt"  # indent under Presets/
            use cue_icon_btn("xmark", Function(_cue_confirm_delete_preset, _pname), "Delete preset", None)
            use cue_icon_btn(
                "play",
                Function(_cue_preview_preset, _pname),
                "Play random file from preset", None)
            use cue_icon_btn(
                "V",
                Function(_cue.markers.video.send_preset, _pname),
                _vid_tt, None, enabled=_is_video)
            use cue_icon_btn(
                "I",
                Function(_cue.markers.image.send_preset, _pname),
                _img_tt, None, enabled=_has_image)
            use cue_icon_btn(
                "D",
                Function(_cue.markers.dialogue.send_preset, _pname),
                _dlg_tt, None, enabled=_is_dialogue)
            use cue_icon_btn(
                "L",
                Function(_cue.markers.loop.send_preset, _pname),
                _loop_tt, None)
            use cue_txt_button(_pname, Function(_cue.sfx_manager.toggle_preset_expand, _pname))

        if _p_expanded:
            for _child in _p_files:
                hbox:
                    spacing 2
                    text "    " style "cue_txt"  # double indent
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.markers.preset_remove_file, _pname, _child),
                        "Remove file from preset", None)
                    use cue_icon_btn("play", Function(_cue_preview_sfx, _child), "Preview file", None)
                    text _child style "cue_txt" color _cue_color_text_accent size 11


# Video preset rows, shown when the Video Presets folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
screen cue_video_presets_list(_is_video, _has_image, _is_dialogue, name_filter=None):
    $ _names = name_filter if name_filter is not None else _cue.markers.list_video_presets()
    for _vpname in _names:
        $ _vpdata = _cue.markers.get_video_preset(_vpname)
        $ _vp_expanded = _cue.sfx_manager.expanded_video_presets.get(_vpname, False)
        $ _vp_pools = _vpdata.get("pools", []) if _vpdata else []
        hbox:
            spacing 2
            text "  " style "cue_txt"  # indent under Video Presets/
            use cue_icon_btn(
                "xmark",
                Function(_cue_confirm_delete_video_preset, _vpname),
                "Delete video preset", None)
            use cue_icon_btn(
                "play",
                Function(_cue_preview_video_preset, _vpname),
                "Play random file from video preset", None)
            use cue_icon_btn(
                "V",
                Function(_cue_maybe_apply_video_preset, _vpname),
                "Apply video markers to the current video.\nOverwrites existing markers.",
                None, enabled=_is_video)
            use cue_txt_button(_vpname, Function(_cue.sfx_manager.toggle_video_preset_expand, _vpname))

        if _vp_expanded:
            for _pool in _vp_pools:
                $ _pool_time = _pool.get("time", 0)
                $ _pool_files = len(_cue_resolve_files(_pool.get("files", [])))
                $ _pool_label = "{} ({} files)".format(_cue_format_time(_pool_time), _pool_files)
                hbox:
                    spacing 2
                    text "    " style "cue_txt"  # double indent
                    text _pool_label style "cue_txt" color _cue_color_text_accent size 11


# Folder/file rows for the current audio tree.
screen cue_file_tree(_is_video, _has_image, _is_dialogue):
    # Tooltip strings per marker type (screen-local).  The _*_tt_has variant
    # is shown once a pool exists; _*_tt_create until the first pool.
    $ _vid_tt_create = "Create Video SFX pool at current timestamp and add files"
    $ _vid_tt_has = "Click: Add files to active Video SFX pool\nShift+Click: " + _vid_tt_create
    $ _img_tt_create = "Create Image SFX pool and add files"
    $ _img_tt_has = "Click: Add files to active Image SFX pool\nShift+Click: " + _img_tt_create
    $ _dlg_tt_create = "Create Dialogue SFX pool and add files"
    $ _dlg_tt_has = "Click: Add files to active Dialogue SFX pool\nShift+Click: " + _dlg_tt_create
    $ _loop_tt_create = "Create Loop SFX pool and add files"
    $ _loop_tt_has = "Click: Add files to active Loop SFX pool\nShift+Click: " + _loop_tt_create
    $ _vid_tt = _vid_tt_has if _cue.markers.video.has_pools() else _vid_tt_create
    $ _img_tt = _img_tt_has if _cue.markers.image.has_pools() else _img_tt_create
    $ _dlg_tt = _dlg_tt_has if _cue.markers.dialogue.has_pools() else _dlg_tt_create
    $ _loop_tt = _loop_tt_has if _cue.markers.loop.has_pools() else _loop_tt_create

    for item in _cue.sfx_manager.visible_tree:
        hbox:
            spacing 2
            # Indent
            if item["depth"] > 0:
                text " " * item["depth"] style "cue_txt"
            if item["type"] == "folder":
                if item["has_files"]:
                    use cue_icon_btn(
                        "play",
                        Function(_cue_preview_folder, item["full_path"]),
                        "Play random file from folder", None)
                    use cue_icon_btn(
                        "V",
                        Function(_cue.markers.video.send_folder, item["full_path"]),
                        _vid_tt, None, enabled=_is_video)
                    use cue_icon_btn(
                        "I",
                        Function(_cue.markers.image.send_folder, item["full_path"]),
                        _img_tt, None, enabled=_has_image)
                    use cue_icon_btn(
                        "D",
                        Function(_cue.markers.dialogue.send_folder, item["full_path"]),
                        _dlg_tt, None, enabled=_is_dialogue)
                    use cue_icon_btn(
                        "L",
                        Function(_cue.markers.loop.send_folder, item["full_path"]),
                        _loop_tt, None)
                use cue_txt_button(item["name"], Function(_cue.sfx_manager.toggle_folder, item["full_path"]))
            else:
                # Play preview
                use cue_icon_btn("play", Function(_cue_preview_sfx, item["full_path"]), "Preview audio", None)
                # Video marker (adds to active pool)
                use cue_icon_btn(
                    "V",
                    Function(_cue.markers.video.send_file, item["index"]),
                    _vid_tt, None, enabled=_is_video)
                # Image SFX
                use cue_icon_btn(
                    "I",
                    Function(_cue.markers.image.send_file, item["index"]),
                    _img_tt, None, enabled=_has_image)
                # Dialogue SFX
                use cue_icon_btn(
                    "D",
                    Function(_cue.markers.dialogue.send_file, item["index"]),
                    _dlg_tt, None, enabled=_is_dialogue)
                # Loop SFX
                use cue_icon_btn(
                    "L",
                    Function(_cue.markers.loop.send_file, item["index"]),
                    _loop_tt, None)
                # use cue_icon_btn(
                #     ("square-check" if item.get("enabled", True) else "square"),
                #     Function(_cue.sfx_manager.toggle_file_enabled, item["full_path"]),
                #     "Click to {} globally".format("disable" if item.get("enabled", True) else "enable"),
                #     None)
                text item["name"] style "cue_txt" color _cue_color_text_accent
