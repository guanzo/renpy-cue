###############################################################################
# SFX Library Section
# Audio file browser with presets, video presets, and folder tree.
###############################################################################

screen cue_sfx_library(_is_video, _has_image, _is_dialogue):
    $ _collapsed = _cue.file_tree.collapsed_sections.get(CUE_SFX_LIBRARY_HEADER, False)
    $ _overlay_mode = _cue.file_tree.sfx_library_overlay_mode
    $ _arrow = "▸" if _collapsed else "▾"
    $ _ov_icon = "⊞" if _overlay_mode else "⊟"
    $ _ov_tt = (
        "Overlay Mode\n" 
        "When enabled, this section will float on top when expanded.\n"
        "Shift + S to toggle expansion.")
    frame:
        background _cue_color_bg_panel
        padding (4, 4)
        xfill True
        yminimum 0
        vbox:
            spacing 8
            xfill True
            hbox:
                xfill True
                button:
                    style "cue_section_hdr_btn"
                    action Function(_cue.file_tree.toggle_section, CUE_SFX_LIBRARY_HEADER)
                    hbox:
                        xfill True
                        text CUE_SFX_LIBRARY_HEADER style "cue_hdr"
                        null width 8
                        hbox:
                            xalign 1.0
                            spacing 10
                            yalign 0.5

                            use cue_icon_btn(
                                _ov_icon,
                                Function(_cue.file_tree.toggle_sfx_library_overlay_mode),
                                _ov_tt,
                                None
                            )
                            text _arrow style "cue_help" size 14
            if not _collapsed:
                if not _cue.audio_tree:
                    text "[_cue.scan_error]" style "cue_help" color _cue_color_error
                    text "Place .ogg, .mp3, .wav, .opus, or .flac files there and click ⟳ to refresh." style "cue_help"
                else:
                    use cue_sfx_library_content(_is_video, _has_image, _is_dialogue)

screen cue_sfx_library_content(_is_video, _has_image, _is_dialogue):
    viewport:
        xfill True
        yfill True
        mousewheel True
        scrollbars "vertical"
        style_group "cue"
        vscrollbar_unscrollable "hide"
        vbox:
            spacing 2
            # --- Presets folder (matches audio tree folder UI) ---
            hbox:
                spacing 2
                use cue_icon_btn(
                    ("▾" if _cue.file_tree.presets_expanded else "▸"),
                    Function(_cue.file_tree.toggle_presets_expand), None, None)
                use cue_txt_button("Presets/", Function(_cue.file_tree.toggle_presets_expand))

            if _cue.file_tree.presets_expanded:
                use cue_audio_presets_list(_is_video, _has_image, _is_dialogue)

            # --- Video Presets folder ---
            hbox:
                spacing 2
                use cue_icon_btn(
                    ("▾" if _cue.file_tree.video_presets_expanded else "▸"),
                    Function(_cue.file_tree.toggle_video_presets_expand), None, None)
                use cue_txt_button("Video Presets/", Function(_cue.file_tree.toggle_video_presets_expand))

            if _cue.file_tree.video_presets_expanded:
                use cue_video_presets_list(_is_video, _has_image, _is_dialogue)

            # --- Folder/file tree ---
            use cue_file_tree(_is_video, _has_image, _is_dialogue)


# Audio preset rows, shown when the Presets folder is expanded.
screen cue_audio_presets_list(_is_video, _has_image, _is_dialogue):
    for _pname in _cue.markers.list_presets():
        $ _pdata = _cue.markers.get_preset(_pname)
        $ _p_expanded = _cue.file_tree.expanded_presets.get(_pname, False)
        $ _p_files = _cue_resolve_files(_pdata.get("files", [])) if _pdata else []
        hbox:
            spacing 2
            text "  " style "cue_txt"  # indent under Presets/
            use cue_icon_btn(
                ("▾" if _p_expanded else "▸"),
                Function(_cue.file_tree.toggle_preset_expand, _pname), None, None)
            use cue_icon_btn("✕", Function(_cue_confirm_delete_preset, _pname), "Delete preset", None)
            use cue_icon_btn(
                "▶",
                Function(_cue_preview_preset, _pname),
                "Preview random file from preset", None)
            use cue_icon_btn(
                "V",
                Function(_cue.markers.video.apply_preset, _pname),
                "Apply preset to current video at playhead position",
                None, enabled=_is_video)
            use cue_icon_btn(
                "I",
                Function(_cue.markers.image.apply_preset, _pname),
                "Apply preset to active Image SFX pool", None, enabled=_has_image)
            use cue_icon_btn(
                "D",
                Function(_cue.markers.dialogue.apply_preset, _pname),
                "Apply preset to active Dialogue SFX pool", None, enabled=_is_dialogue)
            use cue_icon_btn(
                "L",
                Function(_cue.markers.loop.apply_preset, _pname),
                "Apply preset to active Loop SFX pool", None)
            use cue_txt_button(_pname, Function(_cue.file_tree.toggle_preset_expand, _pname))

        if _p_expanded:
            for _child in _p_files:
                hbox:
                    spacing 2
                    text "    " style "cue_txt"  # double indent
                    use cue_icon_btn(
                        "✕",
                        Function(_cue.markers.preset_remove_file, _pname, _child),
                        "Remove file from preset", None)
                    use cue_icon_btn("▶", Function(_cue_preview_sfx, _child), "Preview file", None)
                    text _child style "cue_txt" color _cue_color_text_accent size 11


# Video preset rows, shown when the Video Presets folder is expanded.
screen cue_video_presets_list(_is_video, _has_image, _is_dialogue):
    for _vpname in _cue.markers.list_video_presets():
        $ _vpdata = _cue.markers.get_video_preset(_vpname)
        $ _vp_expanded = _cue.file_tree.expanded_video_presets.get(_vpname, False)
        $ _vp_pools = _vpdata.get("pools", []) if _vpdata else []
        hbox:
            spacing 2
            text "  " style "cue_txt"  # indent under Video Presets/
            use cue_icon_btn(
                ("▾" if _vp_expanded else "▸"),
                Function(_cue.file_tree.toggle_video_preset_expand, _vpname), None, None)
            use cue_icon_btn(
                "✕",
                Function(_cue_confirm_delete_video_preset, _vpname),
                "Delete video preset", None)
            use cue_icon_btn(
                "▶",
                Function(_cue_preview_video_preset, _vpname),
                "Preview random file from video preset", None)
            use cue_icon_btn(
                "V",
                Function(_cue_maybe_apply_video_preset, _vpname),
                "Apply video markers to the current video.\nOverwrites existing markers.",
                None, enabled=_is_video)
            use cue_txt_button(_vpname, Function(_cue.file_tree.toggle_video_preset_expand, _vpname))

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
    for item in _cue.file_tree.visible_tree:
        hbox:
            spacing 2
            # Indent
            if item["depth"] > 0:
                text " " * item["depth"] style "cue_txt"
            if item["type"] == "folder":
                if item["expanded"]:
                    use cue_icon_btn("▾", Function(_cue.file_tree.toggle_folder, item["full_path"]), None, None)
                else:
                    use cue_icon_btn("▸", Function(_cue.file_tree.toggle_folder, item["full_path"]), None, None)
                if item["has_files"]:
                    use cue_icon_btn(
                        "V",
                        Function(_cue.markers.video.add_folder, item["full_path"]),
                        "Add folder to active video pool", None, enabled=_is_video)
                    use cue_icon_btn(
                        "I",
                        Function(_cue.markers.image.add_folder, item["full_path"]),
                        "Add folder to Image SFX pool", None, enabled=_has_image)
                    use cue_icon_btn(
                        "D",
                        Function(_cue.markers.dialogue.add_folder, item["full_path"]),
                        "Add folder to Dialogue SFX pool", None, enabled=_is_dialogue)
                    use cue_icon_btn(
                        "L",
                        Function(_cue.markers.loop.add_folder, item["full_path"]),
                        "Add folder to Loop SFX Pool", None)
                use cue_txt_button(item["name"], Function(_cue.file_tree.toggle_folder, item["full_path"]))
            else:
                # Play preview
                use cue_icon_btn("▶", Function(_cue_preview_sfx, item["full_path"]), "Preview audio", None)
                # Video marker (adds to active pool)
                use cue_icon_btn(
                    "V",
                    Function(_cue.markers.video.add_file, item["index"]),
                    "Add file to active video pool", None, enabled=_is_video)
                # Image SFX
                use cue_icon_btn(
                    "I",
                    Function(_cue.markers.image.add_file, item["index"]),
                    "Add to Image SFX pool", None, enabled=_has_image)
                # Dialogue SFX
                use cue_icon_btn(
                    "D",
                    Function(_cue.markers.dialogue.add_file, item["index"]),
                    "Add to Dialogue SFX pool", None, enabled=_is_dialogue)
                # Loop SFX
                use cue_icon_btn(
                    "L",
                    Function(_cue.markers.loop.add_file, item["index"]),
                    "Add to Loop SFX pool", None)
                use cue_icon_btn(
                    ("☑" if item.get("enabled", True) else "☐"),
                    Function(_cue.file_tree.toggle_file_enabled, item["full_path"]),
                    "Click to {} globally".format("disable" if item.get("enabled", True) else "enable"),
                    None)
                text item["name"] style "cue_txt" color _cue_color_text_accent
