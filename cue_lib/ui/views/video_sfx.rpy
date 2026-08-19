###############################################################################
# Video SFX Section
# Video timeline, marker pools, time editing, and SFX volume.
###############################################################################

screen cue_video_sfx():
    style_group "cue"

    use cue_section_frame("Video SFX"):
        $ _vid_name = _cue.current_file if _cue.current_file else "?"
        text "Video: [_vid_name]"

        # --- Speed gate: SFX editing is only meaningful on the 1.0x
        #     original.  Variants autoscale from the 1.0x markers, so
        #     editing is locked off otherwise. ---
        $ _cur_speed = _cue.speed_resolver.get_current_speed()
        $ _is_base_speed = (_cur_speed == CUE_DEFAULT_VIDEO_SPEED)
        # Multi-select group present (drives the toolbar/tab highlighting).
        $ _multi_selected = len(_cue.markers.video.get_selected()) > 1

        # --- SFX content ---
        hbox:
            spacing 5
            hbox:
                spacing 0
                text "Time: "
                add CueSelfUpdatingLabel(_cue.vid_manager.time_label, style="cue_text")
            hbox:
                spacing 0
                text "Frames: "
                add CueSelfUpdatingLabel(_cue.vid_manager.frame_label, style="cue_text")
        hbox:
            spacing 5
            yalign 0.5
            use cue_icon_btn(
                ("play" if _cue.vid_manager.paused else "pause"),
                Function(_cue.vid_manager.toggle_pause),
                ("Play" if _cue.vid_manager.paused else "Pause"))

            if _is_base_speed:
                $ _has_markers = _cue.markers.video.has_markers()
                use cue_icon_btn(
                    "floppy-disk",
                    Function(_cue.video_preset_dialog.open),
                    "Save all video markers as a preset",
                    None,
                    enabled=(not _multi_selected),
                )
                use cue_icon_btn("xmark",
                    (Function(_cue.markers.video.remove_selected) if _has_markers else NullAction()),
                    "Delete selected markers" if _has_markers else "No markers to delete", None)
                use cue_txt_button("Repeat Markers", Function(_cue.repeater.open),
                    tt="Repeat selected markers at regular intervals across the video")
                use cue_icon("circle-question",
                    tt=("• Markers and marker groups are draggable.\n\n"
                    + "• (Shift + Click) or (Alt + Click) to create a marker group.\n\n"
                    + "• (Alt + Shift + Click) selects every marker that continues "
                    + "the interval between the active marker and the clicked marker.\n\n"
                    + "• Use \"Repeat Markers\" to copy selected markers at an interval.\n\n"
                    + "• Get your markers timed to the first \"beat\", then use "
                    + "\"Repeat Markers\" to find to right interval."),
                    size=14)
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
        $ _vid_target = _cue.markers.video.active_pool
        $ _vid_target = max(0, min(_vid_target, _vid_count - 1)) if _vid_entries else 0
        # --- Draggable video marker timeline ---
        if _vid_entries:
            add CueVideoMarkerTimeline(
                get_markers=_cue.markers.video.get_markers,
                get_active_index=_cue.markers.video.get_active_index,
                set_active_index=_cue.markers.video.set_active_index,
                set_time=_cue.markers.video.set_time,
                get_dur=_cue.markers.video.get_duration,
            ) yoffset -8
        if _is_base_speed:
            if _vid_entry:
                $ _vid_entry.setdefault("volume", _cue.volume.VOL_DEFAULT)
                $ _master_vol = _vid_entry.get("volume", _cue.volume.VOL_DEFAULT)
                $ _is_muted = _vid_entry.get("video_file_muted", False)
                hbox:
                    spacing 10
                    box_wrap True
                    box_wrap_spacing 3
                    use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _vid_entry, _vid_key)
                    use cue_checkbox(_is_muted, "Mute audio track",
                        Function(_cue_toggle_video_mute),
                        "Mute the video's audio track.\nDoes not affect Cue SFX.")
            use cue_pool_tabs(_vid_count, _vid_target, bool(_vid_entries),
                "Delete all video markers for the current video?",
                Function(_cue.markers.video.clear), "Delete all video SFX for the current video",
                Function(_cue.markers.video.add_pool), "Create a new empty marker at current time",
                _cue.markers.video.select_tab,
                selected_tabs=_cue.markers.video.get_selected())

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
                    $ _active_label = "Pool " + str(_vid_target + 1)
                hbox:
                    spacing 5
                    box_wrap True
                    box_wrap_spacing 3
                    text _active_label
                    if _multi_selected:
                        $ _n_selected = len(_cue.markers.video.get_selected())
                        text "(Edits apply to all {} selected markers)".format(_n_selected) style "cue_help"

                hbox:
                    spacing 5
                    box_wrap True
                    box_wrap_spacing 3

                    text "Time:"
                    $ _dec10 = Function(_cue.markers.video.nudge, -0.01)
                    $ _dec100 = Function(_cue.markers.video.nudge, -0.1)
                    $ _inc10 = Function(_cue.markers.video.nudge, 0.01)
                    $ _inc100 = Function(_cue.markers.video.nudge, 0.1)
                    $ _commit = Function(_cue.markers.video.commit_text)
                    $ _display = _cue_format_time(_active_pool.get("time", 0))
                    use cue_time_input("_cue.markers.video.edit_text", _commit, _dec100, _dec10,
                                        _inc10, _inc100, _display)
                                     
                    null width 3
                       
                    use cue_icon_btn(
                        "clone",
                        Function(_cue.markers.video.duplicate_pool, _vid_target),
                        ("Duplicate selected pools" if _multi_selected else "Duplicate pool"),
                        None,
                    )
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.markers.video.delete_pool_ui),
                        ("Delete selected pools" if _multi_selected else "Delete pool"),
                        None,
                    )
                    use cue_icon_btn(
                        "file-circle-minus",
                        Function(_cue.markers.video.clear_selected_files),
                        ("Delete all files from selected pools" if _multi_selected else "Delete all files from pool"),
                        None,
                    )

                    null width 3

                    $ _vol_target.setdefault("volume", _cue.volume.VOL_DEFAULT)
                    $ _vol_label = "Volume: {:.1f}".format(_active_vol)
                    $ _vol_multi_setter = _cue.markers.video.set_selected_volume if _multi_selected else None
                    use cue_vol_row(_vol_label, _vol_target, _vid_key, multi_setter=_vol_multi_setter)
                
                if _is_preset_ts:
                    use cue_file_list([], _cue.markers.detach_active_video_ts, (), _active_eff, 5,
                        folder_label=_preset_name, folder_children=_active_files,
                        trigger_key=_vid_key, pool_index=_vid_target,
                        folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                elif _raw_files:
                    use cue_file_list(_raw_files, _cue.markers.video.remove_file, (_vid_target,), _active_eff, 5,
                        trigger_key=_vid_key, pool_index=_vid_target,
                        folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
                else:
                    text "SFX plays when this video reaches the marked time(s)."
                    text "Click + in the SFX Library with Video selected to add files to this pool."
            else:
                text "SFX plays when this video reaches the marked time(s)."
                text ("Click + in the SFX Library with Video selected to create a new pool "
                    "or add to the active pool.")
        else:
            null height 5
            text ("Only the original video (1.0x) can be edited. Speed variants inherit "
                + "the 1.0x configuration. Switch back to 1.0x to edit markers.")
