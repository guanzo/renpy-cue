###############################################################################
# Dialog Screens
# Repeat markers, save preset, save video preset, and confirm dialogs.
###############################################################################

screen cue_repeat_markers_dialog():
    style_group "cue"

    zorder CUE_DIALOG_ZORDER

    # _sync_tracked() runs from render/tick contexts and only flips
    # dialog_visible when the preview session must end (anchor deleted,
    # markers cleared). Hide the screen itself on the next interaction.
    if not _cue.repeater.dialog_visible:
        timer 0.01 action Function(_cue.repeater.hide)
    $ anchor = _cue.repeater.anchor
    $ offsets = _cue.repeater.offsets
    $ sel_count = _cue.repeater.sel_count

    button:
        style "cue_dialog"
        action NullAction()

        vbox:
            spacing 8
            etext "Repeat Markers" style "cue_hdr"

            hbox:
                spacing 5
                etext "Selected:"
                etext "{} marker(s)".format(sel_count) color _cue_color_text_accent

            hbox:
                spacing 5
                etext "Anchor:"
                $ _anchor_dec = Function(_cue.repeater.nudge_anchor, -0.01)
                $ _anchor_inc = Function(_cue.repeater.nudge_anchor, 0.01)
                $ _anchor_commit = Function(_cue.repeater.commit_anchor)
                $ _anchor_display = _cue.repeater.anchor_text
                use cue_float_input("_cue.repeater.anchor_text", _anchor_commit, _anchor_display,
                    dec_action=_anchor_dec, inc_action=_anchor_inc)

            hbox:
                spacing 3
                xalign 0.0
                etext "Interval:"
                $ _commit = Function(_cue.repeater.commit_interval)
                $ _display = _cue.repeater.interval_text
                use cue_float_input("_cue.repeater.interval_text", _commit, _display,
                    dec_action=Function(_cue.repeater.nudge_interval, -0.1),
                    inc_action=Function(_cue.repeater.nudge_interval, 0.1))

            hbox:
                spacing 3
                xalign 0.0
                etext "Repeat:"
                $ _dec = Function(_cue.repeater.nudge_count, -1)
                $ _inc = Function(_cue.repeater.nudge_count, 1)
                $ _commit = Function(_cue.repeater.commit_count)
                $ _display = _cue.repeater.count_text
                use cue_float_input("_cue.repeater.count_text", _commit, _display,
                    dec_action=_dec, inc_action=_inc)

            use cue_checkbox(_cue.repeater.preview_sfx_enabled, 
                "Preview markers trigger SFX",
                Function(_cue.repeater.toggle_preview_sfx))

            $ _preview_label = _cue.repeater.preview_text()
            etext _preview_label

            null height 5

            hbox:
                spacing 8
                use cue_txt_button("Cancel", Function(_cue.repeater.hide))
                use cue_txt_button("Apply", [
                    Function(_cue.repeater.apply),
                    Function(_cue.repeater.hide),
                ])


screen cue_save_preset_dialog():
    style_group "cue"

    zorder CUE_DIALOG_ZORDER

    # Shared by the SFX-pool and music-trigger save flows; the summary rows
    # branch on which target the dialog holds.
    $ _d = _cue.dialogs.preset
    $ _is_music = _d.music_key is not None
    if _is_music:
        $ _song_count = len(_cue.music.resolve_music_files(_d.songs))
    else:
        $ _entry = _cue.markers.get(_d.marker_key) if _d.marker_key else None
        $ _pools = _entry.get("pools", []) if _entry else []
        $ _pool = _pools[_d.pool_idx] if _pools and _d.pool_idx < len(_pools) else {}
        $ _r = _cue.markers.resolve_pool(_pool)
        $ _file_count = len(_cue_resolve_files(_r.files))
    key "K_RETURN" action Function(_d.commit)
    key "K_KP_ENTER" action Function(_d.commit)
    key "K_ESCAPE" action Function(_d.cancel)

    button:
        style "cue_dialog"
        action NullAction()

        vbox:
            spacing 8
            etext "Save Preset" style "cue_hdr"

            if _is_music:
                hbox:
                    spacing 5
                    etext "Songs:"
                    etext "{} file(s)".format(_song_count) color _cue_color_text_accent
            else:
                hbox:
                    spacing 5
                    etext "Files:"
                    etext "{} file(s)".format(_file_count) color _cue_color_text_accent

                hbox:
                    spacing 5
                    etext "Volume:"
                    etext "{:.1f}".format(_r.volume) color _cue_color_text_accent

            null height 5

            hbox:
                spacing 5
                etext "Name:"
                input:
                    style "cue_input"
                    value _CueFieldValue("_cue.dialogs.preset.name")
                    default True
                    xsize 200
                    copypaste True

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.cancel))
                use cue_txt_button("Save", Function(_d.commit))


screen cue_save_video_preset_dialog():
    style_group "cue"

    zorder CUE_DIALOG_ZORDER

    $ _d = _cue.dialogs.video_preset
    $ _vid_key = _cue_create_vid_key(_cue.current_file) if _cue.current_file else ""
    $ _entry = _cue.markers.get(_vid_key, {}) if _vid_key else {}
    $ _pools = _entry.get("pools", [])
    $ _marker_count = len(_pools)
    $ _total_files = 0
    $ _span_text = "0:00.00"
    if _pools:
        $ _first_t = _pools[0].get("time", 0)
        $ _last_t = _pools[-1].get("time", 0)
        $ _span_text = _cue_format_time(_last_t - _first_t)
        for _pool in _pools:
            $ _total_files += len(_cue_resolve_files(_pool.get("files", [])))
    key "K_RETURN" action Function(_d.commit)
    key "K_KP_ENTER" action Function(_d.commit)
    key "K_ESCAPE" action Function(_d.cancel)

    button:
        style "cue_dialog"
        action NullAction()

        vbox:
            spacing 8
            etext "Save Video Preset" style "cue_hdr"

            hbox:
                spacing 5
                etext "Markers:"
                etext "{} marker(s)".format(_marker_count) color _cue_color_text_accent

            hbox:
                spacing 5
                etext "Span:"
                etext _span_text color _cue_color_text_accent

            hbox:
                spacing 5
                etext "Files:"
                etext "{} file(s)".format(_total_files) color _cue_color_text_accent

            null height 5

            hbox:
                spacing 5
                etext "Name:"
                input:
                    style "cue_input"
                    value _CueFieldValue("_cue.dialogs.video_preset.name")
                    default True
                    xsize 200
                    copypaste True

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.cancel))
                use cue_txt_button("Save", Function(_d.commit))


screen cue_new_igroup_dialog():
    style_group "cue"

    zorder CUE_DIALOG_ZORDER

    $ _d = _cue.dialogs.intensity
    key "K_RETURN" action Function(_d.commit)
    key "K_KP_ENTER" action Function(_d.commit)
    key "K_ESCAPE" action Function(_d.cancel)

    button:
        style "cue_dialog"
        action NullAction()

        vbox:
            spacing 8
            etext ("Rename Intensity Group" if _d.renaming is not None else "New Intensity Group") style "cue_hdr"

            hbox:
                spacing 5
                etext "Name:"
                input:
                    style "cue_input"
                    value _CueFieldValue("_cue.dialogs.intensity.name")
                    default True
                    xsize 200
                    copypaste True

            if _d.error:
                etext _d.error color _cue_color_error

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.cancel))
                use cue_txt_button("Save", Function(_d.commit))


screen cue_confirm_dialog():
    style_group "cue"

    zorder CUE_DIALOG_ZORDER

    $ _d = _cue.dialogs.confirm
    key "K_RETURN" action [Function(_d.hide)] + ([_d.on_confirm] if _d.on_confirm else [])
    key "K_KP_ENTER" action [Function(_d.hide)] + ([_d.on_confirm] if _d.on_confirm else [])
    key "K_ESCAPE" action Function(_d.hide)

    button:
        style "cue_dialog"
        action NullAction()

        vbox:
            spacing 8
            etext _d.message

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.hide))
                use cue_txt_button("OK", [Function(_d.hide), _d.on_confirm])


screen cue_merge_dialog():
    style_group "cue"

    zorder CUE_DIALOG_ZORDER

    $ _d = _cue.dialogs.merge
    $ _summary = _d.summary()
    # Category order is canonical; counts only holds present categories.
    $ _merge_cats = [c for c in CUE_IMPORT_CATEGORY_ORDER if c in _d.counts]
    key "K_RETURN" action Function(_d.confirm)
    key "K_KP_ENTER" action Function(_d.confirm)
    key "K_ESCAPE" action Function(_d.cancel)

    button:
        style "cue_dialog"
        action NullAction()

        vbox:
            spacing 8
            etext "Merge Import" style "cue_hdr"

            for _cat in _merge_cats:
                $ _label = CUE_IMPORT_CATEGORY_LABELS.get(_cat, "?")
                $ _n = _d.counts[_cat]
                hbox:
                    spacing 8
                    use cue_checkbox(
                        _d.is_checked(_cat),
                        _label,
                        Function(_d.toggle, _cat),
                        enabled=_d.is_category_enabled(_cat))
                    etext "{} file(s)".format(_n) color _cue_color_text_accent

            null height 5

            etext _summary

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.cancel))
                use cue_txt_button("Merge", Function(_d.confirm))
