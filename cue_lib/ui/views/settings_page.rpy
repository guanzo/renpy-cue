###############################################################################
# Settings Page
###############################################################################

screen cue_settings_page():
    style_group "cue"

    frame:
        background _cue_color_bg_overlay
        padding (0, 0)
        viewport:
            mousewheel True
            scrollbars "vertical"
            vscrollbar_unscrollable "hide"
            vbox:
                spacing 5
                frame:
                    etext "Settings" style "cue_hdr" xoffset 4
                    yminimum 0

                use cue_data_dir()
                use cue_keybinds()
                use cue_backup_restore()
                use cue_about()

screen cue_data_dir():
    style_group "cue"

    use cue_section_frame("Data Folder"):
        vbox:
            spacing 8
            etext "Cue stores everything (markers, video, audio, backups, etc.) in this folder."
            etext ("If you change the folder, you must move all files to the new "
                "folder and restart the game.")
            use cue_text_input("_cue.settings.setup_dir_text",
                Function(_cue.settings.confirm_shared_dir),
                _cue.settings.setup_dir_text,
                xsize=430,
                commit_on_enter=False)
            if _cue.settings.shared_dir_error:
                etext _cue.settings.shared_dir_error color _cue_color_error
            elif _cue.settings.shared_dir_success:
                etext _cue.settings.shared_dir_success color _cue_color_green
            hbox:
                spacing 6
                use cue_open_in_explorer_btn(_cue.paths.original_root, "Open Data Folder")
                use cue_txt_button("Save", Function(_cue.settings.confirm_shared_dir))

            use cue_h_divider()

            etext "SFX Folders" style "cue_hdr"
            etext ("Add more folders to check for SFX.")
            for _i in range(len(_cue.settings.sfx_folders)):
                use cue_folder_row(
                    "_cue.settings.sfx_folder_drafts[{}]".format(_i),
                    Function(_cue.settings.commit_sfx_folder, _i),
                    Function(_cue.settings.remove_sfx_folder, _i))
                if _i < len(_cue.settings.sfx_folder_errors):
                    if _cue.settings.sfx_folder_errors[_i]:
                        etext _cue.settings.sfx_folder_errors[_i] color _cue_color_error
            use cue_txt_button("Add SFX Folder", Function(_cue.settings.add_sfx_folder))

            use cue_h_divider()

            etext "Music Folders" style "cue_hdr"
            etext ("Add more folders to check for music.")
            for _i in range(len(_cue.settings.music_folders)):
                use cue_folder_row(
                    "_cue.settings.music_folder_drafts[{}]".format(_i),
                    Function(_cue.settings.commit_music_folder, _i),
                    Function(_cue.settings.remove_music_folder, _i))
                if _i < len(_cue.settings.music_folder_errors):
                    if _cue.settings.music_folder_errors[_i]:
                        etext _cue.settings.music_folder_errors[_i] color _cue_color_error
            use cue_txt_button("Add Music Folder", Function(_cue.settings.add_music_folder))


# Editable folder row (Settings > Data Folder): text input bound to a
# settings.folders[i] element + remove button.  Enter commits (validates and
# rescans); the row keeps its text on failure so the user can fix it.
screen cue_folder_row(value_path, commit_action, remove_action, xsize=430):
    style_group "cue"

    $ _value = _CueFieldValue(value_path).get_text()
    $ _label = _value if _value else "Click to type a folder path..."

    hbox:
        spacing 4
        use cue_icon_btn("trash-can", remove_action, "Remove folder")
        use cue_text_input(value_path, commit_action, _label, xsize=xsize)


screen cue_keybinds():
    style_group "cue"

    use cue_section_frame("Keybinds"):
        for _kb in _cue.keybinds.visible_actions():
            $ _ks = _cue.keybinds.get_keysym(_kb["id"])
            if _ks == "":
                $ _label = "--"
                $ _is_default = False
            else:
                $ _label = _cue.keybinds.keysym_label(_ks)
                $ _is_default = (_ks == _kb["default"])

            # Have to hardcode ysize/xsize on all hbox's here, 
            # otherwise there's some weird layout shift bug with tooltips.
            hbox:
                spacing 10
                xsize 250
                ysize 12
                hbox:
                    xsize 150
                    ysize 12
                    etext _kb["label"] yalign 0.5

                hbox:
                    spacing 8
                    xsize 100
                    ysize 12
                    use cue_txt_button(
                        _label,
                        Function(_cue_keybind_start, _kb["id"]),
                        tt=_kb["desc"],
                        ysize=16,
                        xminimum=12
                    )
                    if not _is_default:
                        use cue_icon(
                            "rotate-left",
                            action=Function(_cue_keybind_reset, _kb["id"]),
                            tt="Reset to default",
                        )


screen cue_backup_restore():
    style_group "cue"

    use cue_section_frame("Backup & Restore"):
        vbox:
            spacing 8
            etext ("Backup data folder to backups/{}.".format(CUE_MANUAL_BACKUP_NAME))
            $ _auto_bk_tt = ("Auto back up your marker data once an hour for 30 days. "
                "Media files (audio, music, video) are excluded.\n"
                "Stored in: {}".format(
                    _cue.paths.auto_backups_dir.replace("\\", "/")))
            hbox:
                spacing 8
                use cue_open_in_explorer_btn(_cue.paths.backups_dir, "Open Backups Folder")
                use cue_checkbox(
                    _cue.backups.auto.enabled,
                    "Auto Backups",
                    Function(_cue.backups.set_auto_backups, (not _cue.backups.auto.enabled)),
                    tt_on=_auto_bk_tt)
            hbox:
                spacing 8
                use cue_txt_button(
                    "Back Up", Function(_cue.backups.backup),
                    sensitive=(not _cue.backups.is_busy))

                if _cue.backups.is_backing_up:
                    $ _backup_pct = int(_cue.backups.backup_fraction * 100)
                    etext ("Backing up... ({}%)".format(_backup_pct)) color _cue_color_text_muted
                if _cue.backups.backup_error:
                    etext _cue.backups.backup_error color _cue_color_error
                elif _cue.backups.backup_status:
                    etext _cue.backups.backup_status color _cue_color_green

            etext ("Restore merges the backup over current data. Anything "
                "in the data folder that's not in the backup is untouched.")
            hbox:
                spacing 8
                use cue_txt_button(
                    "Restore", Function(_cue.backups.restore),
                    sensitive=(not _cue.backups.is_busy))

                if _cue.backups.is_restore_checking:
                    etext "Preparing restore..." color _cue_color_text_muted
                if _cue.backups.is_restoring:
                    etext "Restoring..." color _cue_color_text_muted
                if _cue.backups.restore_error:
                    etext _cue.backups.restore_error color _cue_color_error
                elif _cue.backups.restore_status:
                    etext _cue.backups.restore_status color _cue_color_green


screen cue_about():
    style_group "cue"

    use cue_section_frame("About Cue"):
        vbox:
            spacing 8
            etext "Version {}".format(CUE_VERSION)
            text ("{a=" + CUE_GITHUB + "}Report bugs or request features{/a}") style "cue_about_link"
            text ("{a=" + CUE_DISCORD + "}Join the Cue Discord{/a}") style "cue_about_link"
            text ("{a=" + CUE_KOFI + "}Support me{/a}") style "cue_about_link"

# -----------------------------------------------------------------------------
# Keybind-capture modal — shown while waiting for the user to press a key
# during rebinding.  The CueKeyCaptureDisplayable (last child) intercepts
# keyboard events; the Cancel button and the modal's own blocking behavior
# ensure nothing else receives input.
# -----------------------------------------------------------------------------

screen cue_keybind_capture():
    style_group "cue"

    zorder 10002
    modal True
    frame:
        background _cue_color_bg_dialog
        xpos _cue_scale_ui(_cue_overlay_panel_width)
        ypos _cue_scale_ui(8)
        padding (_cue_scale_ui(16), _cue_scale_ui(8))
        xmaximum _cue_scale_ui(300)
        xfill False
        vbox:
            spacing _cue_scale_ui(8)
            etext "Press a key(s) for " + _cue.keybinds.current_label()
            etext "Ctrl / Alt / Shift can be combined."
            etext "Press Esc to cancel."
            if _cue.keybinds.collision_message:
                etext _cue.keybinds.collision_message color _cue_color_error
            hbox:
                spacing _cue_scale_ui(5)
                use cue_txt_button("Cancel", Function(_cue_keybind_cancel))
                if _cue.keybinds.collision_message:
                    use cue_txt_button(
                        "Override",
                        Function(_cue_keybind_override),
                        bg=_cue_color_red, hover_bg=_cue_color_red_hover)
    add CueKeyCaptureDisplayable()
