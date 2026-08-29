###############################################################################
# Scenes Page
###############################################################################

screen cue_replays_page():
    style_group "cue"

    $ _in_replay = renpy.store._in_replay
    $ _entries = _cue.replays.entries

    frame:
        background _cue_color_bg_overlay
        padding (0, 0)
        viewport:
            mousewheel True
            scrollbars "vertical"
            vscrollbar_unscrollable "hide"
            use cue_section_frame("Scenes"):
                if not _entries:
                    etext "No scenes yet.  Markers edited inside a replay show up here."
                else:
                    vbox:
                        spacing 5
                        for _r in _entries:
                            use cue_scene_row(_r, _in_replay)


screen cue_scene_row(entry, in_replay):
    style_group "cue"

    $ _label = entry["replay"]
    $ _exists = renpy.has_label(_label)

    hbox:
        spacing 6
        use cue_icon_btn(
            "play",
            Function(_cue.replays.play, _label),
            "Play this scene",
            enabled=_exists)
        if not _exists:
            use cue_icon(
                "triangle-exclamation",
                tt="Scene doesn't exist",
                icon_color=_cue_color_warn,
                size=12)
        etext _label color _cue_color_text_accent size 11
        etext "{} marker(s)".format(entry["marker_count"]) color _cue_color_text_muted size 11
        if in_replay == _label:
            etext "(now playing)" color _cue_color_text_muted size 11
