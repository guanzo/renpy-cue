###############################################################################
# Scenes Page
###############################################################################

screen cue_replays_page():
    style_group "cue"

    $ _in_replay = renpy.store._in_replay
    $ _entries = _cue.replays.entries
    $ _filter = _cue.replays.cast_filter
    $ _filtered = [e for e in _entries if _filter.matches(e["replay"])]

    frame:
        background _cue_color_bg_overlay
        padding (0, 0)
        viewport:
            mousewheel True
            scrollbars "vertical"
            vscrollbar_unscrollable "hide"
            use cue_section_frame("Scenes"):
                text ""
                use cue_select_input(_filter, "Filter by character...")
                null height _cue_scale_ui(4)
                if not _entries:
                    etext "No scenes yet.  Markers edited inside a replay show up here."
                elif not _filtered:
                    etext "No scenes match the selected characters."
                else:
                    vbox:
                        spacing 5
                        for _r in _filtered:
                            use cue_scene_row(_r, _in_replay)


screen cue_scene_row(entry, in_replay):
    style_group "cue"

    $ _label = entry["replay"]
    $ _exists = renpy.has_label(_label)
    $ _thumb = _cue.replays.thumbs.thumb_for(_label)
    $ _th_w = _cue_scale_ui(64)
    $ _th_h = _cue_scale_ui(36)

    hbox:
        spacing 6
        if _thumb is not None:
            # fit (aspect-preserving scale) exists only on 7.4.2+; older
            # versions stretch the slot instead of dropping the thumbnail.
            # size= not xysize=: 7.2.x registers size but not the individual
            # props, and 7.4+ aliases size to xysize.
            if getattr(renpy, "version_tuple", (0, 0, 0)) >= (7, 4, 2):
                add Transform(_thumb, size=(_th_w, _th_h), fit="contain")
            else:
                add Transform(_thumb, size=(_th_w, _th_h))
        else:
            frame:
                xysize (_th_w, _th_h)
                background _cue_color_bg_overlay
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
