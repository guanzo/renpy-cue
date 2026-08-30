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
        use cue_section_frame("Edited Scenes"):
            use cue_select_input(_filter, "Filter by character...")
            null height _cue_scale_ui(4)
            if not _entries:
                etext "No scenes yet.  Markers edited inside a replay show up here."
            elif not _filtered:
                etext "No scenes match the selected characters."
            else:
                # Header and filter stay pinned; only the rows scroll.
                viewport:
                    xfill True
                    yfill True
                    mousewheel True
                    scrollbars "vertical"
                    vscrollbar_unscrollable "hide"
                    $pass  # https://github.com/renpy/renpy/issues/3474
                    vbox:
                        spacing 2
                        for _r in _filtered:
                            use cue_scene_row(_r, _in_replay)


screen cue_scene_row(entry, in_replay, play_action=None, play_sensitive=None):
    style_group "cue"

    # Transient per-row hover state: which row/thumbnail the pointer is over.
    default _hovered_label = None
    default _thumb_hovered = False
    $ _label = entry["replay"]
    $ _exists = renpy.has_label(_label)
    $ _thumb = _cue.replays.thumbs.thumb_for(_label)
    $ _th_w = _cue_scale_ui(96)
    $ _th_h = _cue_scale_ui(54)
    $ _chips = _cue.replays.cast_filter.chips_for(_label)
    $ _mc = entry["marker_count"]
    $ _mc_text = "{} marker".format(_mc) if _mc == 1 else "{} markers".format(_mc)
    # Import rows override the play action (enter preview first) and gate it
    # separately; the Scenes page keeps the defaults.
    $ _play_act = play_action if play_action is not None else Function(_cue.replays.play, _label)
    $ _play_sens = play_sensitive if play_sensitive is not None else _exists

    button:
        style "empty"
        xfill True
        background _cue_color_bg_panel
        hover_background _cue_color_bg_input
        action NullAction()
        hovered SetLocalVariable("_hovered_label", _label)
        unhovered SetLocalVariable("_hovered_label", None)
        padding (4, 4)
        hbox:
            spacing 6
            button:
                style "cue_scene_thumb"
                xysize (_th_w, _th_h)
                action _play_act
                sensitive _play_sens
                hovered [SetLocalVariable("_hovered_label", _label), SetLocalVariable("_thumb_hovered", True)]
                unhovered [SetLocalVariable("_hovered_label", None), SetLocalVariable("_thumb_hovered", False)]
                if _thumb is not None:
                    # fit (aspect-preserving scale) exists only on 7.4.2+; older
                    # versions stretch the slot instead of dropping the thumbnail.
                    # size= not xysize=: 7.2.x registers size but not the individual
                    # props, and 7.4+ aliases size to xysize.
                    if getattr(renpy, "version_tuple", (0, 0, 0)) >= (7, 4, 2):
                        add Transform(_thumb, size=(_th_w, _th_h), fit="contain")
                    else:
                        add Transform(_thumb, size=(_th_w, _th_h))
                if _exists and _hovered_label == _label:
                    add (_cue.icons.displayable_for("play", None, 18)):
                        align (0.5, 0.5)
                        alpha (1.0 if _thumb_hovered else 0.7)
            if not _exists:
                use cue_icon(
                    "triangle-exclamation",
                    tt="Scene doesn't exist",
                    icon_color=_cue_color_warn,
                    size=12)
            vbox:
                spacing 4
                hbox:
                    spacing 5
                    etext _label color _cue_color_text_accent
                    if in_replay == _label:
                        etext "(now playing)" color _cue_color_text_muted
                if _chips:
                    hbox:
                        spacing 5
                        for _chip in _chips:
                            frame:
                                style "cue_select_chip"
                                etext _chip style "cue_select_chip_text"
                etext _mc_text color _cue_color_text_muted yalign 0.5
