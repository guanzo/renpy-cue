###############################################################################
# Music Page
###############################################################################

screen cue_music_page():
    use cue_section_frame("Music"):
        vbox:
            spacing 5
            if not _cue.current_replay:
                text "Enter a replay to see its default music triggers." style "cue_help"
            else:
                $ _triggers = _cue.music_manager.triggers_for(_cue.current_replay)
                if not _triggers:
                    text "No music triggers recorded for this replay yet." style "cue_help"
                else:
                    for _t in _triggers:
                        hbox:
                            spacing 8
                            text (_t.get("key_after") or _t["key_before"]) style "cue_txt"
                            text _t["filepath"] style "cue_help"
