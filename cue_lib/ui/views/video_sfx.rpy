###############################################################################
# Video SFX Section
# Video timeline, marker pools, time editing, and SFX volume.
###############################################################################

screen cue_video_sfx():
    use cue_section_frame("Video SFX"):
        $ _vid_name = _cue.current_file if _cue.current_file else "?"
        text "Video: [_vid_name]" style "cue_txt"

        # --- SFX content ---
        hbox:
            spacing 5
            hbox:
                spacing 0
                text "Time: " style "cue_txt"
                add CueSelfUpdatingLabel(_cue.vid_manager.time_label, style="cue_txt")
            hbox:
                spacing 0
                text "Frames: " style "cue_txt"
                add CueSelfUpdatingLabel(_cue.vid_manager.frame_label, style="cue_txt")
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
            use cue_txt_button("Repeat", Function(_cue.repeater.open),
                tt="Repeat selected markers at regular intervals across the video")
            $ _has_markers = _cue.markers.video.has_markers()
            use cue_icon_btn("💾", Function(_cue.video_preset_dialog.open), "Save all video markers as a preset", None)
            use cue_icon_btn("✕",
                (Function(_cue.markers.video.remove_selected) if _has_markers else NullAction()),
                "Delete selected markers" if _has_markers else "No markers to delete", None)
            use cue_icon_btn("?",
                NullAction(),
                ("• Markers and marker groups are draggable.\n"
                + "• (Alt + Click) or (Shift + Click) to create a marker group.\n"
                + "• Use Repeat to copy selected markers at an interval.\n"
                + "• Get your markers timed to the first position, then use Repeat to find to right interval."),
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
                add CueVideoTimeline()
        # Video marker tabs + active pool
        $ _vid_key = _cue_create_vid_key(_cue.current_file) if _cue.current_file else ""
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
            $ _vid_entry.setdefault("volume", _cue.volume.VOL_DEFAULT)
            $ _master_vol = _vid_entry.get("volume", _cue.volume.VOL_DEFAULT)
            $ _dec = Function(_cue.volume.adjust_master, _vid_key, -0.1)
            $ _inc = Function(_cue.volume.adjust_master, _vid_key, 0.1)
            $ _is_muted = _vid_entry.get("video_file_muted", False)
            hbox:
                spacing 10
                box_wrap True
                box_wrap_spacing 3
                use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _dec, _vid_entry, _inc)
                use cue_checkbox(_is_muted, "Mute audio track",
                    Function(_cue_toggle_video_mute),
                    "Mute the video's audio track.\nDoes not affect Cue SFX.")
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
            $ _active_vol = _active_pool.get("volume", _cue.volume.VOL_DEFAULT)
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
                box_wrap True
                box_wrap_spacing 3
                text _active_label style "cue_txt"

                null width 5

                use cue_icon_btn("♻", Function(_cue.markers.video.duplicate_pool, _vid_target), "Duplicate pool", None)
                use cue_icon_btn("✕", Function(_cue.markers.video.remove_pool, _vid_target), "Delete pool", None)

                # Volume controls
                $ _vol_target.setdefault("volume", _cue.volume.VOL_DEFAULT)
                $ _dec = Function(_cue.volume.adjust_video, -0.1)
                $ _inc = Function(_cue.volume.adjust_video, 0.1)
                null width 5
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
                use cue_file_list([], _cue.markers.detach_active_video_ts, (), _active_eff, 5,
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
            text ("Click the V button in the SFX Library to create a new pool "
                "or add to the active pool.") style "cue_help"
