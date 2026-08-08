###############################################################################
# Overlay Screen
###############################################################################


###############################################################################
# Key Listener — invisible screen that catches global hotkeys and drives the
# tick engine.
###############################################################################

screen cue_key_listener():
    zorder 10000

    key "K_BACKQUOTE" action Function(_cue_toggle_overlay)
    key "K_F3" action Function(renpy.invoke_in_new_context, renpy.pause)
    key "K_F4" action Function(_cue_toggle_active)
    key "shift_K_1" action Function(_cue.markers.copy_context)
    key "shift_K_2" action Function(_cue.markers.paste_context)
    key "K_PERIOD" action Function(_cue.speed_resolver.cycle_speed, 1)
    key "K_COMMA" action Function(_cue.speed_resolver.cycle_speed, -1)
    timer 0.02 repeat True action Function(_cue_tick_trigger, _update_screens=False)

###############################################################################
# Main Overlay — the sidebar frame.
###############################################################################

screen cue_overlay():

    zorder 9999
    modal False

    button:
        xalign 0.0
        yalign 0.0
        xsize 500
        yfill True
        action NullAction()
        background None
        hover_background None
        frame:
            style "cue_frame"
            xfill True
            yfill True
            use cue_overlay_content()

    # --- Floating tooltip near mouse (auto-sizes to fit text) ---
    $ _tt = GetTooltip()
    if _tt:
        add _Tooltip(_tt)

    # --- Marker timeline tooltip (rendered last so it's always on top) ---
    add _MarkerTooltipOverlay()



# =============================================================================
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen cue_overlay_content():
    vbox:
        spacing 4

        # --- Top bar: active checkbox + copy + paste + dump + restore + refresh + close ---
        hbox:
            spacing 2
            use cue_toggle_btn(_cue.triggers_active, "SFX Active",
                Function(_cue_toggle_active),
                "SFX triggers are ON (F4 to toggle)",
                "SFX triggers are OFF (F4 to toggle)",
                _cue_color_active, _cue_color_green_hover, _cue_color_red, _cue_color_red_hover)
            null width 5
            use cue_icon_btn("📋", Function(_cue.markers.copy_context), "Copy current context config (Shift + 1)", None)
            use cue_icon_btn("📄", Function(_cue.markers.paste_context), "Paste context config (Shift + 2)", None)
            null width 5
            $ _backup_tooltip = "Backup config to " + _cue.config_filename
            use cue_icon_btn("💾", Function(_cue.markers.backup_to_file), _backup_tooltip, None)
            $ _restore_tooltip = "Restore config from " + _cue.config_filename
            use cue_icon_btn("📂", Function(_cue.markers.restore_from_file), _restore_tooltip, None)
            null width 5
            use cue_icon_btn("⏸", Function(renpy.invoke_in_new_context, renpy.pause), "Pause game (F3)", None)
            use cue_icon_btn("⟳", [Function(_cue_refresh_context), Function(_cue_scan_audio)], "Refresh overlay", None)
            use cue_icon_btn("✕", Function(_cue_hide_overlay), "Close overlay", None)

        # --- Mode detection ---
        $ _is_video = _cue.top_layer_type == 'movie'
        $ _is_dialogue = bool(_cue.current_dialogue)

        # --- Video UI ---
        if _is_video:
            use cue_section_frame("Video"):
                # --- Tab buttons ---
                hbox:
                    spacing 5
                    use cue_tab_btn("SFX", not _cue.video_editor.active,
                        Function(_cue.video_editor.close_editor))
                    use cue_tab_btn("VFX", _cue.video_editor.active,
                        Function(_cue.video_editor.open_editor))
                $ _vid_name = _cue.current_file if _cue.current_file else "?"
                text "Video: [_vid_name]" style "cue_txt"

                # --- Speed / Multi Speed tabs ---
                $ _vid_path = _cue.speed_resolver.base_path_for(_cue.current_file)
                if _vid_path:
                    $ _avail = _cue.speed_resolver.get_available_speeds(_vid_path)
                    $ _seq = _cue.video_sequence.speeds_for(_cue.current_file)
                    $ _mode = _cue.video_sequence.get_mode()

                    if len(_avail) > 1:
                        hbox:
                            spacing 5
                            use cue_tab_btn("Single Speed", _mode == SpeedMode.SINGLE,
                                Function(_cue.video_sequence.set_mode, SpeedMode.SINGLE))
                            use cue_tab_btn("Multi Speed", _mode == SpeedMode.MULTI,
                                Function(_cue.video_sequence.set_mode, SpeedMode.MULTI))

                    # --- Speeds tab ---
                    if _mode == SpeedMode.SINGLE and len(_avail) > 1:
                        $ _cur = _cue.speed_resolver.speed_for(_cue.current_file)
                        vbox:
                            spacing 5
                            hbox:
                                spacing 3
                                for _sp in _avail:
                                    $ _label = _cue_speed_label(_sp)
                                    $ _tt = ("Play at " + _cue_speed_label(_sp) + " speed"
                                        if _sp != _cue.DEFAULT_VIDEO_SPEED
                                        else "Play at original video speed")
                                    use cue_select_btn(_label, abs(_cur - _sp) < 0.05,
                                        Function(_cue.speed_resolver.set_speed, _sp),
                                        tt=_tt, active_color=_cue_color_active)
                                if _cur != _cue.DEFAULT_VIDEO_SPEED:
                                    use cue_v_divider()
                                    use cue_txt_button("Delete " + _cue_speed_label(_cur),
                                        Function(_cue.speed_resolver.delete_variant, _vid_path, _cur),
                                        tt="Delete the " + _cue_speed_label(_cur) + " file.")
                            text "The video will only play at the selected speed" style "cue_help"

                    # --- Multi Speed tab ---
                    if _mode == SpeedMode.MULTI:
                        if len(_avail) > 1:
                            hbox:
                                spacing 3
                                text "Add:" style "cue_txt" size 11
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
                        if _seq:
                            null height 3
                            viewport:
                                xalign 0.5
                                xsize 425
                                ysize 30
                                mousewheel True
                                scrollbars "horizontal"
                                scrollbar_unscrollable "hide"
                                style_group "cue"

                                hbox:
                                    spacing 5
                                    for _si in range(len(_seq)):
                                        $ _sp = _seq[_si]
                                        $ _s_label = _cue_speed_label(_sp)
                                        $ _is_current = (_cue.video_sequence.current_step_index() == _si)
                                        $ _bg = _cue_color_active if _is_current else None
                                        use cue_txt_button(_s_label, NullAction(),
                                            bg=_bg, sensitive=False,
                                            tt="Multi speed position {}. Cycles in order.".format(_si + 1))

                        text "The video plays through each speed in order, then loops." style "cue_help"


                use cue_h_divider()

                # --- SFX Tab ---
                if not _cue.video_editor.active:
                    hbox:
                        spacing 5
                        hbox:
                            spacing 0
                            text "Time: " style "cue_txt"
                            add SelfUpdatingLabel(_cue.vid_manager.time_label, style="cue_txt")
                        hbox:
                            spacing 0
                            text "Frames: " style "cue_txt"
                            add SelfUpdatingLabel(_cue.vid_manager.frame_label, style="cue_txt")
                    hbox:
                        spacing 5
                        use cue_txt_button(("▶" if _cue.vid_manager.paused else "⏸"),
                            Function(_cue.vid_manager.toggle_pause))
                        use cue_txt_button("-1f",
                            Function(_cue.vid_manager.seek_frame, -1),
                            tt="Seek backwards 1 frame (inaccurate and requires restarting video)")
                        use cue_txt_button("+1f",
                            Function(_cue.vid_manager.seek_frame, 1),
                            tt="Seek forward 1 frame (inaccurate)")

                        use cue_v_divider()
                        use cue_txt_button("Repeat", Function(_cue.beat.open),
                            tt="Repeat selected markers at regular intervals across the video")
                        $ _has_markers = _cue.markers.video.has_markers()
                        use cue_icon_btn("💾", Function(_cue.video_preset_dialog.open), "Save all video markers as a preset", None)
                        use cue_icon_btn("✕",
                            Function(_cue.markers.video.remove_selected) if _has_markers else NullAction(),
                            "Delete selected markers" if _has_markers else "No markers to delete", None)
                        use cue_icon_btn("?",
                            NullAction(),
                            ("• Markers and marker groups are draggable.\n"
                            + "• (Alt + Click) or (Shift + Click) to create a marker group.\n"
                            + "• Use Repeat to copy selected markers at an interval.\n"
                            + "• Get your markers timed to the first 'beat', find the interval to the next 'beat', then use Repeat to finish."),
                            None)
                    # --- Timeline visualizer ---
                    frame:
                        background None
                        xfill True
                        yminimum 0
                        padding (10, 0)
                        fixed:
                            xfill True
                            ysize 18
                            add VideoTimeline()
                    # Video marker tabs + active pool
                    $ _vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
                    $ _vid_entry = _cue.markers.get(_vid_key, {})
                    $ _vid_entries = _cue.markers._resolve_video_pools(_vid_entry) if _vid_entry else []
                    $ _vid_count = len(_vid_entries)
                    $ _vid_target = _cue.markers.video.target_pool
                    $ _vid_target = max(0, min(_vid_target, _vid_count - 1)) if _vid_entries else 0
                    # --- Draggable video marker timeline ---
                    if _vid_entries:
                        add CueVideoMarkerTimeline(
                            get_markers=_cue.markers.video.get_markers,
                            get_active=_cue.markers.video.get_active,
                            set_active=_cue.markers.video.set_active,
                            set_time=_cue.markers.video.set_time,
                            get_dur=_cue.markers.video.get_duration,
                        ) yoffset -8
                    if _vid_entry:
                        $ _vid_entry.setdefault("volume", 1.0)
                        $ _master_vol = _vid_entry.get("volume", 1.0)
                        $ _dec = Function(_cue.volume.adjust_master, _vid_key, -0.1)
                        $ _inc = Function(_cue.volume.adjust_master, _vid_key, 0.1)
                        use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _dec, _vid_entry, _inc)
                    use cue_pool_tabs(_vid_count, _vid_target, bool(_vid_entries),
                        "Delete all video markers for the current video?",
                        Function(_cue.markers.video.clear), "Delete all video SFX for the current video",
                        Function(_cue.markers.video.add_pool), "Create a new empty marker at current time",
                        _cue.markers.video.select_tab, (), "Select pool — V button adds files here")

                    # Active pool display
                    if _vid_entries and 0 <= _vid_target < _vid_count:
                        $ _active_pool = _vid_entries[_vid_target]
                        $ _raw_files = _active_pool.get("files", [])
                        $ _active_files = _cue_resolve_files(_raw_files)
                        $ _active_vol = _active_pool.get("volume", _cue.VOL_DEFAULT)
                        $ _active_eff = _cue.volume.get_effective(_vid_entry, _vid_key, pool_index=_vid_target)
                        # Detect preset-backed pool
                        $ _raw_pool_list = _vid_entry.get("pools", [])
                        $ _raw_pool = _raw_pool_list[_vid_target] if 0 <= _vid_target < len(_raw_pool_list) else {}
                        $ _is_preset_ts = "preset" in _raw_pool
                        $ _preset_name = _raw_pool.get("preset", "")
                        # Volume dict target: raw pool for preset-backed (so overrides
                        # persist on the real dict), resolved pool for concrete.
                        $ _vol_target = _raw_pool if _is_preset_ts else _active_pool
                        if _is_preset_ts:
                            $ _active_label = "Pool " + str(_vid_target + 1) + " (Preset: " + _preset_name + ")"
                        else:
                            $ _active_label = "Pool " + str(_vid_target + 1) + " (" + str(len(_active_files)) + " files)"
                        hbox:
                            spacing 5
                            text _active_label style "cue_txt"

                            null width 5

                            use cue_icon_btn("♻", Function(_cue.markers.video.duplicate_pool, _vid_target), "Duplicate pool", None)
                            use cue_icon_btn("✕", Function(_cue.markers.video.remove_pool, _vid_target), "Delete pool", None)

                            # Volume controls
                            $ _vol_target.setdefault("volume", 1.0)
                            $ _dec = Function(_cue.volume.adjust_video, -0.1)
                            $ _inc = Function(_cue.volume.adjust_video, 0.1)
                            null width 5
                            if abs(_active_vol - _active_eff) > 0.01:
                                $ _vol_label = "Volume: {:.1f} ({:.1f} total)".format(_active_vol, _active_eff)
                            else:
                                $ _vol_label = "Volume: {:.1f}".format(_active_vol)
                            use cue_vol_row(_vol_label, _dec, _vol_target, _inc)

                        # Editable time + nudge buttons
                        hbox:
                            spacing 3
                            text "Time:" style "cue_txt" size 11
                            $ _dec10 = Function(_cue.markers.video.nudge, -0.01)
                            $ _dec100 = Function(_cue.markers.video.nudge, -0.1)
                            $ _inc10 = Function(_cue.markers.video.nudge, 0.01)
                            $ _inc100 = Function(_cue.markers.video.nudge, 0.1)
                            $ _commit = Function(_cue.markers.video.commit_text)
                            $ _display = _cue_format_time(_active_pool.get("time", 0))
                            use cue_time_input("_cue.markers.video.edit_text", _commit, _dec100, _dec10,
                                               _inc10, _inc100, _display)
                        # File list
                        if _is_preset_ts:
                            # Preset-backed: render as expandable folder via cue_file_list
                            use cue_file_list([], _cue_detach_active_video_ts, (), _active_eff, 5,
                                folder_label=_preset_name, folder_children=_active_files,
                                trigger_key=_vid_key, pool_index=_vid_target,
                                folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                        elif _raw_files:
                            use cue_file_list(_raw_files, _cue.markers.video.remove_file, (_vid_target,), _active_eff, 5,
                                trigger_key=_vid_key, pool_index=_vid_target,
                                folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
                        else:
                            text "SFX plays when this video reaches the marked time(s)." style "cue_help"
                            text "Click the V button in the SFX Library to add files to this pool." style "cue_help"
                    else:
                        text "SFX plays when this video reaches the marked time(s)." style "cue_help"
                        text "Click the V button in the SFX Library to create a new pool or add to the active pool." style "cue_help"

                # --- Video Editor Tab ---
                if _cue.video_editor.active:
                    $ _ved = _cue.video_editor
                    vbox:
                        spacing 2
                        hbox:
                            spacing 5
                            text "New Speed:" style "cue_txt"
                            $ _commit = Function(_cue.video_editor.commit_text)
                            $ _display = _cue_speed_label(float(_ved.factor_text))
                            use cue_icon_btn("-", Function(_cue.video_editor.nudge, -0.1))
                            use cue_float_input("_cue.video_editor.factor_text", _commit, _display)
                            use cue_icon_btn("+", Function(_cue.video_editor.nudge, 0.1))
                            $ _ov_presets = _cue.speed_resolver.preset_speeds()
                            if _ov_presets:
                                use cue_v_divider()
                                for _sp in _ov_presets:
                                    use cue_txt_button(_cue_speed_label(_sp),
                                        Function(_cue.video_editor.set_quick, _sp),
                                        tt="Set speed to " + _cue_speed_label(_sp))
                        text "Speed multiplier is based on original video" style "cue_help" size 10 yalign 0.5

                    # --- Encode mode radio buttons ---
                    vbox:
                        spacing 2
                        hbox:
                            spacing 4
                            text "Quality:" style "cue_txt"
                            use cue_radio_btn(_ved.encode_mode == _ved.MODE_FAST_PREVIEW, "Fast Preview",
                                Function(_cue.video_editor.set_encode_mode, _ved.MODE_FAST_PREVIEW),
                                tt="Fast low-quality encode to judge the edited speed.")
                            use cue_radio_btn(_ved.encode_mode == _ved.MODE_NORMAL, "Normal",
                                Function(_cue.video_editor.set_encode_mode, _ved.MODE_NORMAL),
                                tt="Standard encode at the original quality — no extra processing.")
                            use cue_radio_btn(_ved.encode_mode == _ved.MODE_INTERPOLATE, "Interpolate Frames",
                                Function(_cue.video_editor.set_encode_mode, _ved.MODE_INTERPOLATE),
                                tt="Uses ffmpeg to generate in-between frames for smoother motion. Video takes longer to encode.")
                        if _ved.encode_mode == _ved.MODE_INTERPOLATE:
                            text "Slower encode, higher quality" style "cue_help"
                        elif _ved.encode_mode == _ved.MODE_FAST_PREVIEW:
                            text "Faster encode, lower quality" style "cue_help"
                        else:
                            text "Match original quality" style "cue_help"
                    null height 2
                    use cue_txt_button("Create",
                        Function(_cue.video_editor.prepare_create),
                        sensitive=_ved._ready)
                    if _ved.last_error:
                        text _ved.last_error style "cue_txt" color _cue_color_error

                    # --- Edit queue ---
                    if _ved.job_queue.jobs:
                        use cue_h_divider()
                        timer 0.2 repeat True action [
                            Function(_cue.video_editor.job_queue.poll),
                            Function(_cue.video_editor.job_queue.refresh_ui),
                        ]
                        frame:
                            background _cue_color_bg_panel
                            padding (4, 0)
                            yminimum 0
                            xfill True
                            vbox:
                                spacing 3
                                text "Edit Queue" style "cue_txt" size 14 bold True
                                null height 2
                                for _job in _ved.job_queue.jobs:
                                    hbox:
                                        spacing 4
                                        if _job.status in ("queued", "analyzing", "encoding"):
                                            use cue_icon_btn("✕", Function(_cue.video_editor.job_queue.cancel, _job.job_id), "Cancel job", None)
                                        else:
                                            use cue_icon_btn("✕", Function(_cue.video_editor.job_queue.remove, _job.job_id), "Remove from queue", None)
                                        text _job.filename() + " " + _job.speed_label style "cue_txt" size 11
                                        text "(" + _job.status_text() + ")" style "cue_txt" size 11
                                        if _job.status != "queued":
                                            $ _elapsed = int(_job.elapsed())
                                            text ("%d:%02d" % (_elapsed // 60, _elapsed % 60)) style "cue_txt" size 11 color _cue_color_text_muted
                                    if _job.status == "error" and _job.error_msg and not _job.cancelled:
                                        hbox:
                                            spacing 4
                                            null width 20
                                            text _job.error_msg style "cue_txt" size 10 color _cue_color_error
                                            use cue_txt_button("Retry",
                                                Function(_cue.video_editor.job_queue.retry, _job.job_id))

        # --- Image UI ---
        $ _has_image = bool(_cue.current_file) and not _is_video
        if _has_image:
            $ _img_key = create_img_key(_cue.current_file)
            use cue_context_section("Image SFX", _cue.markers.image, _img_key,
                "Image: " + _cue.current_file, "image", "I",
                "SFX plays when this image is displayed."):
                $ _p = _cue._pool_ui["pool"]
                use cue_toggle_btn(_p.get("trigger_on_shake", False),
                    "Trigger on screen shake",
                    Function(_cue_toggle_shake_trigger),
                    "Play SFX when a screen shake occurs")

        # --- Dialogue UI ---
        if _is_dialogue:
            $ _dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))
            use cue_context_section("Dialogue SFX", _cue.markers.dialogue, _dlg_key,
                "Dialogue: " + _cue.current_dialogue, "dialogue", "D",
                "SFX plays when this line of dialogue is displayed.")

        # Loop SFX
        $ _loop_key = create_loop_key(_cue.current_file or "")
        use cue_context_section("Loop SFX", _cue.markers.loop, _loop_key,
            None, "file", "L",
            "SFX plays on a loop when this image/video is displayed."):
            $ _freq = _cue._pool_ui.get("freq", 1)
            hbox:
                spacing 5
                text "Interval:" style "cue_txt" size 11
                use cue_select_btn("Slowest", _freq == 4, Function(_cue.markers.loop.set_frequency, 4), tt="~6.3s between plays")
                use cue_select_btn("Slow", _freq == 0, Function(_cue.markers.loop.set_frequency, 0), tt="~3.8s between plays")
                use cue_select_btn("Normal", _freq == 1, Function(_cue.markers.loop.set_frequency, 1), tt="~2.1s between plays")
                use cue_select_btn("Fast", _freq == 2, Function(_cue.markers.loop.set_frequency, 2), tt="~0.6s between plays")
                use cue_select_btn("Fastest", _freq == 3, Function(_cue.markers.loop.set_frequency, 3), tt="~0.2s between plays")
                use cue_v_divider()
                $ _no_overlap = _cue._pool_ui.get("no_overlap", False)
                use cue_toggle_btn(_no_overlap, "Don't overlap",
                    Function(_cue.markers.loop.set_no_overlap, not _no_overlap),
                    "Waits for other loop SFX to finish before playing.")

        # Audio file browser
        use cue_section_frame("SFX Library"):
            if not _cue.audio_tree:
                text "[_cue.scan_error]" style "cue_help" color _cue_color_error
                text "Place .ogg, .mp3, .wav, .opus, or .flac files there and click ⟳ to refresh." style "cue_help"
            else:
                viewport:
                    xfill True
                    yfill True
                    mousewheel True
                    scrollbars "vertical"
                    style_group "cue"
                    vscrollbar_unscrollable "hide"
                    vbox:
                        spacing 2
                        # --- Presets folder (matches audio tree folder UI) ---
                        hbox:
                            spacing 2
                            use cue_icon_btn(
                                ("▾" if _cue.file_tree.presets_expanded else "▸"),
                                Function(_cue.file_tree.toggle_presets_expand), None, None)
                            $ _preset_names = _cue.markers.list_presets()
                            use cue_txt_button("Presets/", Function(_cue.file_tree.toggle_presets_expand))
                        if _cue.file_tree.presets_expanded:
                            for _pname in _preset_names:
                                $ _pdata = _cue.markers.get_preset(_pname)
                                $ _p_expanded = _cue.file_tree.expanded_presets.get(_pname, False)
                                $ _p_files = _cue_resolve_files(_pdata.get("files", [])) if _pdata else []
                                $ _pfile_count = len(_p_files)
                                hbox:
                                    spacing 2
                                    text "  " style "cue_txt"  # indent under Presets/
                                    use cue_icon_btn(
                                        ("▾" if _p_expanded else "▸"),
                                        Function(_cue.file_tree.toggle_preset_expand, _pname), None, None)
                                    use cue_icon_btn("✕", Function(_cue_confirm_delete_preset, _pname), "Delete preset", None)
                                    use cue_icon_btn("▶", Function(_cue_preview_preset, _pname), "Preview random file from preset", None)
                                    use cue_icon_btn("V", Function(_cue.markers.video.apply_preset, _pname), "Apply preset to current video at playhead position", None, enabled=_is_video)
                                    use cue_icon_btn("I", Function(_cue.markers.image.apply_preset, _pname), "Apply preset to active Image SFX pool", None, enabled=_has_image)
                                    use cue_icon_btn("D", Function(_cue.markers.dialogue.apply_preset, _pname), "Apply preset to active Dialogue SFX pool", None, enabled=_is_dialogue)
                                    use cue_icon_btn("L", Function(_cue.markers.loop.apply_preset, _pname), "Apply preset to active Loop SFX pool", None)
                                    use cue_txt_button(_pname, Function(_cue.file_tree.toggle_preset_expand, _pname))
                                if _p_expanded:
                                    for _child in _p_files:
                                        hbox:
                                            spacing 2
                                            text "    " style "cue_txt"  # double indent
                                            use cue_icon_btn("✕", Function(_cue.markers.preset_remove_file, _pname, _child), "Remove file from preset", None)
                                            use cue_icon_btn("▶", Function(_cue_preview_sfx, _child), "Preview file", None)
                                            text _child style "cue_txt" color _cue_color_text_accent size 11
                        # --- Video Presets folder ---
                        hbox:
                            spacing 2
                            use cue_icon_btn(
                                ("▾" if _cue.file_tree.video_presets_expanded else "▸"),
                                Function(_cue.file_tree.toggle_video_presets_expand), None, None)
                            $ _vp_names = _cue.markers.list_video_presets()
                            use cue_txt_button("Video Presets/", Function(_cue.file_tree.toggle_video_presets_expand))
                        if _cue.file_tree.video_presets_expanded:
                            for _vpname in _vp_names:
                                $ _vpdata = _cue.markers.get_video_preset(_vpname)
                                $ _vp_expanded = _cue.file_tree.expanded_video_presets.get(_vpname, False)
                                $ _vp_pools = _vpdata.get("pools", []) if _vpdata else []
                                $ _vp_total_files = 0
                                for _pool in _vp_pools:
                                    $ _vp_total_files += len(_pool.get("files", []))
                                hbox:
                                    spacing 2
                                    text "  " style "cue_txt"  # indent under Video Presets/
                                    use cue_icon_btn(
                                        ("▾" if _vp_expanded else "▸"),
                                        Function(_cue.file_tree.toggle_video_preset_expand, _vpname), None, None)
                                    use cue_icon_btn("✕", Function(_cue_confirm_delete_video_preset, _vpname), "Delete video preset", None)
                                    use cue_icon_btn("▶", Function(_cue_preview_video_preset, _vpname), "Preview random file from video preset", None)
                                    use cue_icon_btn("V", Function(_cue_maybe_apply_video_preset, _vpname), "Apply video markers to the current video", None, enabled=_is_video)
                                    use cue_txt_button(_vpname, Function(_cue.file_tree.toggle_video_preset_expand, _vpname))
                                if _vp_expanded:
                                    for _pool in _vp_pools:
                                        $ _pool_time = _pool.get("time", 0)
                                        $ _pool_files = len(_cue_resolve_files(_pool.get("files", [])))
                                        hbox:
                                            spacing 2
                                            text "    " style "cue_txt"  # double indent
                                            text "{} ({} files)".format(_cue_format_time(_pool_time), _pool_files) style "cue_txt" color _cue_color_text_accent size 11
                        # --- Folder/file tree ---
                        for item in _cue.file_tree.visible_tree:
                            hbox:
                                spacing 2
                                # Indent
                                if item["depth"] > 0:
                                    text " " * item["depth"] style "cue_txt"
                                if item["type"] == "folder":
                                    if item["expanded"]:
                                        use cue_icon_btn("▾", Function(_cue.file_tree.toggle_folder, item["full_path"]), None, None)
                                    else:
                                        use cue_icon_btn("▸", Function(_cue.file_tree.toggle_folder, item["full_path"]), None, None)
                                    if item["has_files"]:
                                        use cue_icon_btn("V", Function(_cue.markers.video.add_folder, item["full_path"]), "Add folder to active video pool", None, enabled=_is_video)
                                        use cue_icon_btn("I", Function(_cue.markers.image.add_folder, item["full_path"]), "Add folder to Image SFX pool", None, enabled=_has_image)
                                        use cue_icon_btn("D", Function(_cue.markers.dialogue.add_folder, item["full_path"]), "Add folder to Dialogue SFX pool", None, enabled=_is_dialogue)
                                        use cue_icon_btn("L", Function(_cue.markers.loop.add_folder, item["full_path"]), "Add folder to Loop SFX Pool", None)
                                    use cue_txt_button(item["name"], Function(_cue.file_tree.toggle_folder, item["full_path"]))
                                else:
                                    # Play preview
                                    use cue_icon_btn("▶", Function(_cue_preview_sfx, item["full_path"]), "Preview audio", None)
                                    # Video marker (adds to active pool)
                                    use cue_icon_btn("V", Function(_cue.markers.video.add_file, item["index"]), "Add file to active video pool", None, enabled=_is_video)
                                    # Image SFX
                                    use cue_icon_btn("I", Function(_cue.markers.image.add_file, item["index"]), "Add to Image SFX pool", None, enabled=_has_image)
                                    # Dialogue SFX
                                    use cue_icon_btn("D", Function(_cue.markers.dialogue.add_file, item["index"]), "Add to Dialogue SFX pool", None, enabled=_is_dialogue)
                                    # Loop SFX
                                    use cue_icon_btn("L", Function(_cue.markers.loop.add_file, item["index"]), "Add to Loop SFX pool", None)
                                    use cue_icon_btn(
                                        ("☑" if item.get("enabled", True) else "☐"),
                                        Function(_cue.file_tree.toggle_file_enabled, item["full_path"]),
                                        "Click to {} globally".format("disable" if item.get("enabled", True) else "enable"),
                                        None)
                                    text item["name"] style "cue_txt" color _cue_color_text_accent


###############################################################################
# Repeat Pattern Dialog
###############################################################################

screen cue_repeat_pattern_dialog():
    $ anchor = _cue.beat.anchor
    $ offsets = _cue.beat.offsets
    $ sel_count = _cue.beat.sel_count

    button:
        xpos 500
        ypos 8
        padding (16, 8)
        background _cue_color_bg_dialog
        hover_background _cue_color_bg_dialog
        xmaximum 400
        action NullAction()

        vbox:
                spacing 8
                text "Repeat Pattern" style "cue_hdr"

                hbox:
                    spacing 5
                    text "Selected:" style "cue_txt"
                    text "{} marker(s)".format(sel_count) style "cue_txt" color _cue_color_text_accent

                hbox:
                    spacing 5
                    text "Anchor:" style "cue_txt"
                    text _cue_format_time(anchor) style "cue_txt" color _cue_color_text_accent

                null height 5

                hbox:
                    spacing 3
                    xalign 0.0
                    text "Interval:" style "cue_txt" size 12
                    $ _commit = Function(_cue.beat.commit_interval)
                    $ _display = _cue.beat.interval_text
                    use cue_icon_btn("-", Function(_cue.beat.nudge_interval, -0.1))
                    use cue_float_input("_cue.beat.interval_text", _commit, _display)
                    use cue_icon_btn("+", Function(_cue.beat.nudge_interval, 0.1))

                hbox:
                    spacing 3
                    xalign 0.0
                    text "Repeat:" style "cue_txt" size 12
                    $ _dec = Function(_cue.beat.nudge_count, -1)
                    $ _inc = Function(_cue.beat.nudge_count, 1)
                    $ _commit = Function(_cue.beat.commit_count)
                    $ _display = _cue.beat.count_text
                    use cue_icon_btn("-", _dec)
                    use cue_float_input("_cue.beat.count_text", _commit, _display)
                    use cue_icon_btn("+", _inc)

                use cue_toggle_btn(_cue.beat.preview_sfx_enabled, "Preview markers trigger SFX",
                    Function(_cue.beat.toggle_preview_sfx))

                $ _preview_label = _cue.beat.preview_text()
                text _preview_label style "cue_help"

                null height 5

                hbox:
                    spacing 8
                    use cue_txt_button("Cancel", Function(_cue.beat.hide))
                    use cue_txt_button("Apply", [
                        Function(_cue.beat.apply),
                        Function(_cue.beat.hide),
                    ])


###############################################################################
# Save Preset Dialog
###############################################################################

screen cue_save_preset_dialog():
    $ _d = _cue.preset_dialog
    $ _entry = _cue.markers.get(_d.trigger_key) if _d.trigger_key else None
    $ _pools = _entry.get("pools", []) if _entry else []
    $ _pool = _pools[_d.pool_idx] if _pools and _d.pool_idx < len(_pools) else {}
    $ _r = _cue.markers.resolve_pool(_pool)
    $ _file_count = len(_cue_resolve_files(_r.files))
    key "K_RETURN" action Function(_d.commit)
    key "K_KP_ENTER" action Function(_d.commit)
    key "K_ESCAPE" action Function(_d.cancel)

    button:
        xpos 500
        ypos 8
        padding (16, 8)
        background _cue_color_bg_dialog
        hover_background _cue_color_bg_dialog
        xmaximum 400
        action NullAction()

        vbox:
            spacing 8
            text "Save Preset" style "cue_hdr"

            hbox:
                spacing 5
                text "Files:" style "cue_txt"
                text "{} file(s)".format(_file_count) style "cue_txt" color _cue_color_text_accent

            hbox:
                spacing 5
                text "Volume:" style "cue_txt"
                text "{:.1f}".format(_r.volume) style "cue_txt" color _cue_color_text_accent

            null height 5

            hbox:
                spacing 5
                text "Name:" style "cue_txt" size 12
                input:
                    style "cue_input"
                    value VariableInputValue("_cue.preset_dialog.name")
                    default True
                    xsize 200
                    copypaste True

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.cancel))
                use cue_txt_button("Save", Function(_d.commit))


###############################################################################
# Save Video Preset Dialog
###############################################################################

screen cue_save_video_preset_dialog():
    $ _d = _cue.video_preset_dialog
    $ _vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
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
        xpos 500
        ypos 8
        padding (16, 8)
        background _cue_color_bg_dialog
        hover_background _cue_color_bg_dialog
        xmaximum 400
        action NullAction()

        vbox:
            spacing 8
            text "Save Video Preset" style "cue_hdr"

            hbox:
                spacing 5
                text "Markers:" style "cue_txt"
                text "{} marker(s)".format(_marker_count) style "cue_txt" color _cue_color_text_accent

            hbox:
                spacing 5
                text "Span:" style "cue_txt"
                text _span_text style "cue_txt" color _cue_color_text_accent

            hbox:
                spacing 5
                text "Files:" style "cue_txt"
                text "{} file(s)".format(_total_files) style "cue_txt" color _cue_color_text_accent

            null height 5

            hbox:
                spacing 5
                text "Name:" style "cue_txt" size 12
                input:
                    style "cue_input"
                    value VariableInputValue("_cue.video_preset_dialog.name")
                    default True
                    xsize 200
                    copypaste True

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.cancel))
                use cue_txt_button("Save", Function(_d.commit))


###############################################################################
# Confirm Dialog
###############################################################################

screen cue_confirm_dialog():
    $ _d = _cue.confirm_dialog
    key "K_RETURN" action [Function(_d.hide)] + ([_d.on_confirm] if _d.on_confirm else [])
    key "K_KP_ENTER" action [Function(_d.hide)] + ([_d.on_confirm] if _d.on_confirm else [])
    key "K_ESCAPE" action Function(_d.hide)

    button:
        xpos 500
        ypos 8
        padding (16, 8)
        background _cue_color_bg_dialog
        hover_background _cue_color_bg_dialog
        xmaximum 400
        action NullAction()

        vbox:
            spacing 8
            text _d.message style "cue_txt"

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                use cue_txt_button("Cancel", Function(_d.hide))
                use cue_txt_button("OK", [Function(_d.hide), _d.on_confirm])


