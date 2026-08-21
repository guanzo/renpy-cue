###############################################################################
# Video VFX Section
# Speed selection, multi-speed sequencing, auto-speed presets,
# video creation/encoding, and the edit job queue.
###############################################################################

# Inner vbox for the edit queue — extracted so the parent can conditionally
# wrap it in a viewport when there are more than 6 jobs.
screen _cue_edit_queue_vbox():
    style_group "cue"

    vbox:
        spacing 3
        text "Edit Queue" size 14 bold True
        null height 2
        for job in _cue.video_editor.job_queue.jobs:
            hbox:
                spacing 5
                if job.status in (CueJobStatus.QUEUED, CueJobStatus.ANALYZING,
                                 CueJobStatus.ENCODING, CueJobStatus.FINALIZING):
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.video_editor.job_queue.cancel, job.job_id),
                        "Cancel job",
                    )
                else:
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.video_editor.job_queue.remove, job.job_id),
                        "Remove from queue")
                text job.filename() + " " + job.speed_label size 11
                text "(" + job.status_text() + ")" size 11
                if job.status != CueJobStatus.QUEUED:
                    $ _elapsed = int(job.elapsed())
                    $ _elapsed_text = "%d:%02d" % (_elapsed // 60, _elapsed % 60)
                    text _elapsed_text size 11 color _cue_color_text_muted

            if job.status == CueJobStatus.ERROR and job.error_msg and not job.cancelled:
                hbox:
                    spacing 5
                    null width 20
                    text job.error_msg size 11 color _cue_color_error
                    use cue_txt_button("Retry",
                        Function(_cue.video_editor.job_queue.retry, job.job_id))

screen cue_video_vfx():
    style_group "cue"

    $ _vfx_tt = ("Video SFX markers on the original video (1.0x) will autoscale "
            "to all created videos.")
    use cue_section_frame("Video VFX", tt=_vfx_tt):
        # --- Pre-compute speed availability ---
        $ _vid_path = _cue.speed_resolver.base_path_for(_cue.current_file)
        $ _has_speeds = False
        if _vid_path:
            $ _avail = _cue.speed_resolver.get_available_speeds(_vid_path)
            $ _has_speeds = len(_avail) > 1

        # --- Tab buttons ---
        hbox:
            spacing 5
            use cue_tab_btn("Speed", not _cue.video_editor.active,
                Function(_cue.video_editor.close_editor))
            use cue_tab_btn("Create", _cue.video_editor.active,
                Function(_cue.video_editor.open_editor))

        # --- Speed tab ---
        if not _cue.video_editor.active:
            if _has_speeds:
                # --- Speed / Multi Speed / Auto Speed tabs ---
                $ _seq = _cue.video_sequence.speeds_for(_cue.current_file)
                $ _mode = _cue.video_sequence.get_mode()

                hbox:
                    spacing 5
                    use cue_tab_btn("Single Speed", (_mode == CueSpeedMode.SINGLE),
                        Function(_cue.video_sequence.set_mode, CueSpeedMode.SINGLE))
                    use cue_tab_btn("Multi Speed", (_mode == CueSpeedMode.MULTI),
                        Function(_cue.video_sequence.set_mode, CueSpeedMode.MULTI))
                    use cue_tab_btn("Auto Speed", (_mode == CueSpeedMode.AUTO),
                        Function(_cue.video_sequence.set_mode, CueSpeedMode.AUTO))

                # --- Single Speed tab ---
                if _mode == CueSpeedMode.SINGLE:
                    $ _cur = _cue.speed_resolver.speed_for(_cue.current_file)
                    vbox:
                        spacing 5
                        text "The video will only play at the selected speed"
                        hbox:
                            spacing 5
                            box_wrap True
                            box_wrap_spacing 3
                            for _sp in _avail:
                                $ _label = _cue_speed_label(_sp)
                                $ _tt = ("Play at " + _cue_speed_label(_sp) + " speed"
                                    if _sp != CUE_DEFAULT_VIDEO_SPEED
                                    else "Play at original video speed")
                                $ _is_pending = (_cue.speed_resolver._pending_speed is not None
                                    and _sp == _cue.speed_resolver._pending_speed)
                                $ _is_selected = _cur == _sp or _is_pending
                                $ _btn_color = (_cue_color_dark_yellow if _is_pending else _cue_color_active)
                                use cue_select_btn(_label, _is_selected,
                                    Function(_cue.speed_resolver.set_speed, _sp),
                                    tt=_tt, active_color=_btn_color)
                            if _cur != CUE_DEFAULT_VIDEO_SPEED:
                                use cue_v_divider()
                                use cue_txt_button("Delete " + _cue_speed_label(_cur),
                                    Function(_cue.speed_resolver.delete_variant, _vid_path, _cur),
                                    tt="Delete the " + _cue_speed_label(_cur) + " file.")

                        null height 3
                        use cue_checkbox(
                            _cue.speed_resolver.seamless_transition,
                            "Seamless Transition",
                            Function(_cue.speed_resolver.toggle_seamless),
                            tt_on=("When enabled, changing speeds waits for the current video "
                                "loop to finish before switching."))

                # --- Multi Speed tab ---
                elif _mode == CueSpeedMode.MULTI:
                    text "The video plays through each speed in order, then loops."
                    hbox:
                        spacing 5
                        box_wrap True
                        box_wrap_spacing 5
                        for _sp in _avail:
                            $ _a_label = _cue_speed_label(_sp)
                            use cue_txt_button(_a_label,
                                Function(_cue.video_sequence.append_speed, _sp),
                                tt="Append " + _cue_speed_label(_sp) + " to the end of the sequence")
                        if _seq:
                            use cue_v_divider()
                            use cue_txt_button("Clear",
                                Function(_cue.video_sequence.clear_sequence, None),
                                tt="Remove the entire speed sequence")

                    null height 5

                    if _seq:
                        if len(_seq) >= 2:
                            add CueAutoSpeedChart() xsize 440 ysize 80
                        else:
                            text "Click 1 more speed."
                    else:
                        text "Click the speed buttons to create a sequence. Minimum 2 speeds."

                # --- Auto Speed tab ---
                elif _mode == CueSpeedMode.AUTO:
                    $ _auto = _cue.auto_speed
                    $ _all_speeds = _cue.speed_resolver.get_available_speeds(_vid_path)
                    $ _has_auto = len(_auto.enabled_speeds) >= CUE_AUTO_SPEED_MIN_VARIANTS

                    $ _auto_help = (
                        "Procedurally generates speed rhythms with a certain theme. "
                        "Each playthrough of a rhythm is slightly different. "
                        "Minimum number of speeds is [CUE_AUTO_SPEED_MIN_VARIANTS], recommended is "
                        "[CUE_AUTO_SPEED_IDEAL_VARIANTS]. The more the better."
                    )
                    text _auto_help

                    if not _has_auto:
                        null height 3
                        text "You don't have enough speeds, generate more in the Create tab."

                    if _has_auto:
                        null height 3

                        # --- Speed toggles ---
                        hbox:
                            spacing 5
                            box_wrap True
                            box_wrap_spacing 5
                            for _sp in _all_speeds:
                                use cue_select_btn(
                                    _cue_speed_label(_sp),
                                    _auto.is_speed_enabled(_sp),
                                    Function(_auto.toggle_speed, _sp),
                                    "Click to disable" if _auto.is_speed_enabled(_sp) else "Click to enable")

                        null height 5

                        hbox:
                            spacing 5
                            box_wrap True
                            box_wrap_spacing 5

                            # Don't loop, this is a custom order that places similar themes together
                            use cue_auto_preset_btn("roller_coaster", _auto)
                            use cue_auto_preset_btn("build_up", _auto)
                            use cue_auto_preset_btn("cool_down", _auto)
                            use cue_auto_preset_btn("slow_groove", _auto)
                            use cue_auto_preset_btn("fast_frenzy", _auto)
                            use cue_auto_preset_btn("tease", _auto)
                            use cue_auto_preset_btn("plateau", _auto)
                            use cue_auto_preset_btn("edge", _auto)
                            use cue_auto_preset_btn("anchor", _auto)
                            use cue_auto_preset_btn("pulse", _auto)
                            use cue_auto_preset_btn("random_walk", _auto)
                            use cue_auto_preset_btn("shuffle", _auto)

                        null height 5

                        # --- Sequence chart ---
                        $ _seq = _cue.video_sequence.speeds_for(_cue.current_file)
                        if _seq and len(_seq) >= 2:
                            add CueAutoSpeedChart() xsize 440 ysize 80
            else:
                text "No speed variants available. Generate them in the Create tab."

        # --- Create tab ---
        if _cue.video_editor.active:
            $ _ved = _cue.video_editor
            vbox:
                spacing 5
                # --- Created speeds: select one for deletion ---
                $ _del_sel = _cue_create_delete_sel()
                hbox:
                    spacing 5
                    box_wrap True
                    box_wrap_spacing 3
                    text "Created Speeds:"
                    if _has_speeds:
                        for _sp in _avail:
                            if _sp != CUE_DEFAULT_VIDEO_SPEED:
                                use cue_select_btn(_cue_speed_label(_sp), (_del_sel == _sp),
                                    Function(_cue_create_select_speed, _sp))
                        if _del_sel is not None:
                            use cue_v_divider()
                            use cue_txt_button("Delete " + _cue_speed_label(_del_sel),
                                Function(_cue_create_delete_speed),
                                tt="Delete the " + _cue_speed_label(_del_sel) + " file.")
                    else:
                        text "None" color _cue_color_text_muted
                
                null height 5
                hbox:
                    spacing 5
                    text "New Speed:"
                    $ _commit = Function(_cue.video_editor.commit_text)
                    $ _display = _cue_speed_label(float(_ved.factor_text))
                    use cue_float_input("_cue.video_editor.factor_text", _commit, _display,
                        dec_action=Function(_cue.video_editor.nudge, -0.1),
                        inc_action=Function(_cue.video_editor.nudge, 0.1))
                    $ _ov_presets = _cue.speed_resolver.preset_speeds()
                    if _ov_presets:
                        use cue_v_divider()
                        for _sp in _ov_presets:
                            use cue_txt_button(_cue_speed_label(_sp),
                                Function(_cue.video_editor.set_quick, _sp),
                                tt="Set speed to " + _cue_speed_label(_sp))
                text "Speed multiplier is based on original video" style "cue_help" yalign 0.5

            # --- Encode mode radio buttons ---
            vbox:
                spacing 5
                hbox:
                    spacing 5
                    text "Quality:"
                    use cue_select_btn("Fast Preview", (_ved.encode_mode == _ved.MODE_FAST_PREVIEW),
                        Function(_cue.video_editor.set_encode_mode, _ved.MODE_FAST_PREVIEW),
                        tt="Fast low-quality encode to judge the edited speed.")
                    use cue_select_btn("Normal", (_ved.encode_mode == _ved.MODE_NORMAL),
                        Function(_cue.video_editor.set_encode_mode, _ved.MODE_NORMAL),
                        tt="Standard encode at the original quality, with no extra processing.")
                    use cue_select_btn("Interpolate Frames", (_ved.encode_mode == _ved.MODE_INTERPOLATE),
                        Function(_cue.video_editor.set_encode_mode, _ved.MODE_INTERPOLATE),
                        tt=("Uses ffmpeg to generate in-between frames for smoother motion. "
                            "Video takes longer to encode."))
                if _ved.encode_mode == _ved.MODE_INTERPOLATE:
                    text "Slower encode, higher quality" style "cue_help"
                elif _ved.encode_mode == _ved.MODE_FAST_PREVIEW:
                    text "Faster encode, lower quality" style "cue_help"
                else:
                    text "Match original quality" style "cue_help"
            if _ved._current_has_audio:
                use cue_checkbox(_ved.remove_audio, "Remove audio track",
                    Function(_cue.video_editor.toggle_remove_audio),
                    "Removes the video's audio track if exists.")
            null height 2
            use cue_txt_button("Create",
                Function(_cue.video_editor.prepare_create),
                sensitive=_ved._ready)
            if _ved.last_error:
                text _ved.last_error color _cue_color_error

            # --- Edit queue ---
            if _cue.video_editor.job_queue.jobs:
                use cue_h_divider()
                timer 0.2 repeat True action [
                    Function(_cue.video_editor.job_queue.poll),
                    Function(_cue.video_editor.job_queue.refresh_ui),
                ]
                frame:
                    padding (0, 0)
                    yminimum 0
                    $ _queue_len = len(_cue.video_editor.job_queue.jobs)
                    if _queue_len > 6:
                        viewport:
                            xfill True
                            ymaximum 200
                            mousewheel True
                            scrollbars "vertical"
                            vscrollbar_unscrollable "hide"
                            use _cue_edit_queue_vbox()
                    else:
                        use _cue_edit_queue_vbox()


screen cue_auto_preset_btn(preset_name, auto):
    style_group "cue"
    $ _is_active = (auto.active_preset == preset_name)
    $ _is_shuffle_mode = (preset_name == "shuffle" and auto.is_shuffle_mode)
    $ _label = _cue_auto_preset_label(preset_name)
    $ _desc = _cue_auto_preset_description(preset_name)

    if _is_shuffle_mode:
        # Shuffle is the selected "mode" -- green
        textbutton _label:
            background _cue_color_active
            action NullAction()
            tooltip _desc
    elif _is_active and auto.is_shuffle_mode:
        # Shuffle delegate -- this preset is playing, but shuffle is the mode (yellow)
        textbutton _label:
            background _cue_color_dark_yellow
            action NullAction()
            tooltip _desc
    elif _is_active:
        # Normal active preset (green)
        textbutton _label:
            background _cue_color_active
            action NullAction()
            tooltip _desc
    else:
        textbutton _label:
            action Function(auto.select_preset, preset_name)
            tooltip _desc
