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
                use cue_settings_keybinds()
                use cue_settings_backup()

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
                _cue.settings.setup_dir_text)
            if _cue.settings.shared_dir_error:
                etext _cue.settings.shared_dir_error color _cue_color_error
            elif _cue.settings.shared_dir_success:
                etext _cue.settings.shared_dir_success color _cue_color_green
            use cue_txt_button("Save", Function(_cue.settings.confirm_shared_dir))


screen cue_settings_keybinds():
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
                ysize 16
                hbox:
                    xsize 150
                    etext _kb["label"] yalign 0.5

                hbox:
                    spacing 8
                    xsize 150
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


screen cue_settings_backup():
    style_group "cue"

    $ _backup_busy = _cue.backups.is_backing_up or _cue.backups.is_restoring

    if _backup_busy:
        timer 0.1 repeat True action Function(renpy.restart_interaction, _update_screens=False)

    use cue_section_frame("Backup & Restore"):
        vbox:
            spacing 8
            etext ("Backup data folder to backups/{}, or restore that "
                "backup's data over the current game.".format(CUE_MANUAL_BACKUP_NAME))
            $ _auto_bk_tt = ("Auto back up your marker data once an hour for 30 days. "
                "Media files (audio, music, video) are excluded.\n"
                "Stored in: {}".format(
                    _cue.paths.auto_backups_dir.replace("\\", "/")))
            hbox:
                spacing 8
                use cue_checkbox(
                    _cue.backups.auto.enabled,
                    "Auto Backups",
                    Function(_cue.backups.set_auto_backups, (not _cue.backups.auto.enabled)),
                    tt_on=_auto_bk_tt)
            hbox:
                spacing 8
                use cue_txt_button(
                    "Back Up", Function(_cue.backups.backup),
                    sensitive=(not _backup_busy))

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
                    sensitive=(not _backup_busy))

                if _cue.backups.is_restoring:
                    etext "Restoring..." color _cue_color_text_muted
                if _cue.backups.restore_error:
                    etext _cue.backups.restore_error color _cue_color_error
                elif _cue.backups.restore_status:
                    etext _cue.backups.restore_status color _cue_color_green


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
        xpos _cue_overlay_panel_width
        ypos 8
        padding (16, 8)
        xmaximum 300
        xfill False
        vbox:
            spacing 8
            etext "Press a key(s) for " + _cue.keybinds.current_label()
            etext "Ctrl / Alt / Shift can be combined."
            etext "Press Esc to cancel."
            if _cue.keybinds.collision_message:
                etext _cue.keybinds.collision_message color _cue_color_error
            hbox:
                spacing 5
                use cue_txt_button("Cancel", Function(_cue_keybind_cancel))
                if _cue.keybinds.collision_message:
                    use cue_txt_button(
                        "Override",
                        Function(_cue_keybind_override),
                        bg=_cue_color_red, hover_bg=_cue_color_red_hover)
    add CueKeyCaptureDisplayable()
