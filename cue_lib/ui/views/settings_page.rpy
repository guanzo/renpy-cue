###############################################################################
# Settings Page
###############################################################################

screen cue_settings_page():
    frame:
        background _cue_color_bg_overlay
        padding (0, 0)
        xfill True
        yminimum 0
        vbox:
            spacing 5
            frame:
                text "Settings" style "cue_hdr" xoffset 4
                background _cue_color_bg_panel
                padding (4, 4)
                xfill True
                yminimum 0

            use cue_data_dir()
            use cue_settings_keybinds()

screen cue_data_dir():
    use cue_section_frame("Cue Data Directory"):
        vbox:
            spacing 5
            text "Where Cue stores data for all games: markers, presets, audio, music, backups." style "cue_help"
            text "Restart the game after changing the directory." style "cue_help"
            use cue_text_input("_cue.setup_dir_text",
                Function(_cue_confirm_shared_dir),
                _cue.setup_dir_text, xsize=440)
            if _cue.shared_dir_error:
                text _cue.shared_dir_error style "cue_help" color _cue_color_error
            elif _cue.shared_dir_success:
                text _cue.shared_dir_success style "cue_help" color _cue_color_green
            use cue_txt_button("Save", Function(_cue_confirm_shared_dir))


screen cue_settings_keybinds():
    use cue_section_frame("Keybinds"):
        grid 2 len(_cue.keybinds.visible_actions()):
            spacing 10

            for _kb in _cue.keybinds.visible_actions():
                $ _ks = _cue.keybinds.get_keysym(_kb["id"])
                if _ks == "":
                    $ _label = "--"
                    $ _is_default = False
                else:
                    $ _label = _cue.keybinds.keysym_label(_ks)
                    $ _is_default = (_ks == _kb["default"])

                text _kb["label"] style "cue_txt" xsize 170 yalign 0.5

                hbox:
                    spacing 8
                    use cue_txt_button(
                        _label,
                        Function(_cue_keybind_start, _kb["id"]),
                        tt=_kb["desc"],
                        ysize=16,
                    )
                    use cue_icon_btn(
                        "rotate-left",
                        Function(_cue_keybind_reset, _kb["id"]),
                        "Reset to default",
                        None,
                        enabled=(not _is_default),
                    )


# -----------------------------------------------------------------------------
# Keybind-capture modal — shown while waiting for the user to press a key
# during rebinding.  The CueKeyCaptureDisplayable (last child) intercepts
# keyboard events; the Cancel button and the modal's own blocking behavior
# ensure nothing else receives input.
# -----------------------------------------------------------------------------

screen cue_keybind_capture():
    zorder 10002
    modal True
    frame:
        background _cue_color_bg_dialog
        xpos 500
        ypos 8
        padding (16, 8)
        xmaximum 420
        vbox:
            spacing 8
            text "Press a key(s) for " + _cue.keybinds.current_label() style "cue_txt"
            text "Ctrl / Alt / Shift can be combined." style "cue_help"
            text "Press Esc to cancel." style "cue_help"
            if _cue.keybinds.collision_message:
                text _cue.keybinds.collision_message style "cue_txt" color _cue_color_error
            hbox:
                spacing 5
                use cue_txt_button("Cancel", Function(_cue_keybind_cancel))
                if _cue.keybinds.collision_message:
                    use cue_txt_button(
                        "Override",
                        Function(_cue_keybind_override),
                        bg=_cue_color_red, hover_bg=_cue_color_red_hover)
    add CueKeyCaptureDisplayable()
