###############################################################################
# Keybinds Settings Section
###############################################################################

screen cue_settings_keybinds():
    use cue_section_frame(CUE_KEYBINDS_SECTION_HEADER):
        use cue_h_divider()
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
                        "↺",
                        Function(_cue_keybind_reset, _kb["id"]),
                        "Reset to default",
                        None,
                        enabled=(not _is_default),
                    )