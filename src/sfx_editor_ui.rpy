
###############################################################################
# SECTION 4: Styles (game-agnostic — all properties explicit, no inheritance)
###############################################################################

style sfx_frame is empty:
    background "#000000ee"
    padding (8, 6)
    xfill True

style sfx_btn is empty:
    background "#444444"
    hover_background "#666666"
    padding (2, 0)
    hover_sound None
    activate_sound None

style sfx_btn_text is empty:
    size 13
    color "#ffffff"
    hover_color "#ffffff"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5

style sfx_btn_text_sm is sfx_btn_text:
    size 10

style sfx_btn_icon is empty:
    xysize (14, 14)
    padding (0, 0)
    background "#444444"
    hover_background "#666666"

style sfx_btn_icon_text is empty:
    size 10
    color "#ffffff"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5
    xanchor 0.5
    yanchor 0.5
    adjust_spacing False
    hover_xoffset 0
    hover_yoffset 0
    hover_xalign 0.5
    hover_yalign 0.5
    padding (0, 0)

style sfx_txt is empty:
    size 12
    color "#cccccc"
    font "DejaVuSans.ttf"

style sfx_hdr is sfx_txt:
    size 14
    color "#ffcc00"
    bold True

style sfx_help is sfx_txt:
    size 11
    color "#888888"

style sfx_input is sfx_txt:
    size 13
    color "#ffffff"
    background "#333333"
    xsize 72
    padding (2, 2)
    ypadding 2


###############################################################################
# SECTION 5: Overlay Screen
###############################################################################


# =============================================================================
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen sfx_editor_sidebar_content():
    vbox:
        spacing 4

        # --- Top bar: active checkbox + copy + paste + dump + restore + refresh + close ---
        hbox:
            spacing 2
            if _sfx.triggers_active:
                textbutton "☑ Active":
                    style "sfx_btn"
                    text_style "sfx_btn_text_sm"
                    background "#446644"
                    hover_background "#558855"
                    action Function(_sfx_editor_toggle_active)
                    tooltip "SFX triggers are ON (F4 to toggle)"
            else:
                textbutton "☐ Active":
                    style "sfx_btn"
                    text_style "sfx_btn_text_sm"
                    background "#664444"
                    hover_background "#885555"
                    action Function(_sfx_editor_toggle_active)
                    tooltip "SFX triggers are OFF (F4 to toggle)"
            null width 5
            textbutton "📋":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_copy_context)
                tooltip "Copy current context config"
            textbutton "📄":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_paste_context)
                tooltip "Paste context config"
            null width 5
            $ _backup_tooltip = "Backup config to " + _sfx.config_filename
            textbutton "💾":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_dump_markers)
                tooltip _backup_tooltip
            $ _restore_tooltip = "Restore config from " + _sfx.config_filename
            textbutton "📂":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_restore_markers_from_file)
                tooltip _restore_tooltip
            null width 5
            textbutton "⟳":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action [Function(_sfx_editor_refresh_detections), Function(_sfx_editor_scan_audio)]
                tooltip "Refresh detections"
            textbutton "✕":
                style "sfx_btn_icon"
                text_style "sfx_btn_icon_text"
                action Function(_sfx_editor_hide)
                tooltip "Close overlay"

        # --- Mode detection ---
        $ _is_video = _sfx.top_layer_type == 'movie'
        $ _is_dialogue = bool(_sfx.current_dialogue)

        # --- Video UI ---
        if _is_video:
            frame:
                background "#222222"
                padding (4, 4)
                xfill True
                yminimum 0
                has vbox
                spacing 5
                text "Video SFX" style "sfx_hdr"
                $ _vid_name = _sfx.current_file if _sfx.current_file else "?"
                text "Video: [_vid_name]" style "sfx_txt"
                hbox:
                    spacing 5
                    text "Time: [_sfx.current_time_str] / [_sfx.total_time_str]" style "sfx_txt"
                    add Solid("#555555") xsize 2 ysize 15
                    text "Frames: [_sfx.current_frame_str]/[_sfx.total_frame_str]" style "sfx_txt"
                hbox:
                    spacing 5
                    if _sfx.paused:
                        textbutton "▶":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_sfx_editor_toggle_pause)
                    else:
                        textbutton "⏸":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_sfx_editor_toggle_pause)
                    textbutton "⏮":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_coarse_seek, -1.0)
                    textbutton "-1f":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_seek_frame, -1)
                    textbutton "+1f":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_seek_frame, 1)
                    textbutton "⏭":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_sfx_editor_coarse_seek, 1.0)
                # Video marker tabs + active pool
                $ _vid_key = _sfx.VID_KEY_PREFIX + _sfx.current_file if _sfx.current_file else ""
                $ _vid_entry = _sfx.markers.get(_vid_key, {})
                $ _vid_entries = _vid_entry.get("timestamps", [])
                $ _vid_count = len(_vid_entries)
                $ _vid_target = _sfx.vid_target_pool
                $ _vid_target = max(0, min(_vid_target, _vid_count - 1)) if _vid_entries else 0
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                vbox:
                    spacing 5
                    text "Video Markers ([_vid_count])" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _vid_entries:
                            textbutton "Delete":
                                style "sfx_btn"
                                text_style "sfx_btn_text"
                                xsize 50
                                action Confirm(
                                    "Delete all video timestamp markers for the current video?\nThis cannot be undone.",
                                    Function(_sfx_editor_clear_video_markers))
                hbox:
                    spacing 2
                    textbutton "+ Pool":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        xsize 48
                        action Function(_sfx_editor_add_video_pool)
                        tooltip "Create a new empty timestamp at current time"
                    for pi in range(_vid_count):
                        $ _is_active = (pi == _vid_target)
                        $ _tab_label = str(pi + 1)
                        textbutton _tab_label:
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            if _is_active:
                                background "#666699"
                            else:
                                background "#444444"
                            action Function(_sfx_editor_set_vid_target_pool, pi)
                            tooltip "Select timestamp pool — V button adds files here"
                # Active pool display
                if _vid_entries and 0 <= _vid_target < _vid_count:
                    $ _active_ts = _vid_entries[_vid_target]
                    $ _active_files = _active_ts.get("files", [])
                    $ _active_vol = _active_ts.get("volume", _sfx.VOL_DEFAULT)
                    $ _active_label = "Pool " + str(_vid_target + 1) + " (" + str(len(_active_files)) + " files)"
                    hbox:
                        spacing 3
                        text _active_label style "sfx_txt" size 11
                        textbutton "✕":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            action Function(_sfx_editor_remove_video_pool, _vid_target)
                            tooltip "Delete this timestamp pool"
                    # Editable timestamp + nudge buttons
                    hbox:
                        spacing 3
                        text "Time:" style "sfx_txt" size 11
                        if _sfx.edit_video_ts_index == _vid_target:
                            input:
                                style "sfx_input"
                                value VariableInputValue("_sfx.edit_video_ts_text")
                                default True
                            textbutton "✓":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                action Function(_sfx_editor_commit_video_ts)
                                tooltip "Confirm edit"
                            textbutton "✕":
                                style "sfx_btn_icon"
                                text_style "sfx_btn_icon_text"
                                xsize 18
                                action Function(_sfx_editor_cancel_edit_video_ts)
                                tooltip "Cancel edit"
                        else:
                            textbutton _sfx_editor_format_time(_active_ts["time"]):
                                style "empty"
                                text_style "sfx_txt"
                                action Function(_sfx_editor_start_edit_video_ts)
                                tooltip "Click to edit timestamp"
                        textbutton "--":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_nudge_video_ts, -0.1)
                            tooltip "Nudge back 100 ms"
                        textbutton "-":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_nudge_video_ts, -0.01)
                            tooltip "Nudge back 10 ms"
                        textbutton "+":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_nudge_video_ts, 0.01)
                            tooltip "Nudge forward 10 ms"
                        textbutton "++":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_nudge_video_ts, 0.1)
                            tooltip "Nudge forward 100 ms"
                    # Volume controls
                    hbox:
                        spacing 3
                        text "Volume: {:.1f}".format(_active_vol) style "sfx_txt" size 11
                        textbutton "--":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_set_video_volume, 1.0)
                            tooltip "Reset pool volume to 1.0"
                        textbutton "-":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_adjust_video_volume, -0.1)
                        textbutton "+":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_adjust_video_volume, 0.1)
                        textbutton "++":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_set_video_volume, 5.0)
                            tooltip "Max volume (5.0)"
                    # File list
                    if _active_files:
                        vbox:
                            spacing 2
                            for fi, f in enumerate(_active_files):
                                hbox:
                                    spacing 5
                                    textbutton "✕":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_remove_video_file, _vid_target, fi)
                                    textbutton "▶":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_preview_sfx, f, _active_vol)
                                    text f style "sfx_txt" color "#ffcc00" size 11


        # --- Image UI ---
        $ _has_image = bool(_sfx.current_file) and not _is_video
        if _has_image:
            $ _img_key = _sfx.IMG_KEY_PREFIX + _sfx.current_file
            $ _img_entry = _sfx.markers.get(_img_key, {})
            $ _img_pools = _sfx_editor_get_pools(_img_entry)
            $ _img_target = _sfx.img_target_pool
            $ _img_target = max(0, min(_img_target, len(_img_pools) - 1)) if _img_pools else 0
            frame:
                background "#222222"
                padding (4, 4)
                xfill True
                yminimum 0
                has vbox
                spacing 5
                text "Image SFX" style "sfx_hdr"
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                vbox:
                    spacing 5
                    text "Image: [_sfx.current_file]" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _img_pools:
                            textbutton "Delete":
                                style "sfx_btn"
                                text_style "sfx_btn_text"
                                xsize 50
                                action Confirm(
                                    "Delete all image SFX pools for the current image?\nThis cannot be undone.",
                                    Function(_sfx_editor_clear_image_markers))
                                tooltip "Remove all image SFX pools"
                null height 5
                # Tab row: [+ Pool] [1] [2] ...
                hbox:
                    spacing 5
                    textbutton "+ Pool":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        xsize 48
                        action Function(_sfx_editor_add_pool, _img_key, "img")
                        tooltip "Add a new pool"
                    for pi, pool in enumerate(_img_pools):
                        $ _is_active = (pi == _img_target)
                        $ _tab_label = str(pi + 1)
                        $ _tab_count = len(pool.get("files", []))
                        textbutton _tab_label:
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            if _is_active:
                                background "#666699"
                            else:
                                background "#444444"
                            action Function(_sfx_editor_set_target_pool, "img", pi)
                            tooltip "Select Image SFX target pool — targets I button"
                # Active pool display
                if _img_pools and 0 <= _img_target < len(_img_pools):
                    $ _active_pool = _img_pools[_img_target]
                    $ _active_files = _active_pool.get("files", [])
                    $ _active_vol = _active_pool.get("volume", _img_entry.get("volume", 1.0))
                    $ _active_label = "Pool " + str(_img_target + 1) + " (" + str(len(_active_files)) + " files)"
                    hbox:
                        spacing 3
                        text _active_label style "sfx_txt" size 11
                        textbutton "✕":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            action Function(_sfx_editor_remove_pool, _img_key, _img_target, "img")
                            tooltip "Delete this pool"
                    hbox:
                        spacing 3
                        text "Volume: {:.1f}".format(_active_vol) style "sfx_txt" size 11
                        textbutton "--":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_set_volume, _img_key, 1.0, _img_target)
                            tooltip "Reset pool volume to 1.0"
                        textbutton "-":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_adjust_volume, _img_key, -0.1, _img_target)
                        textbutton "+":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_adjust_volume, _img_key, 0.1, _img_target)
                        textbutton "++":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_set_volume, _img_key, 5.0, _img_target)
                            tooltip "Max volume (5.0)"
                    if _active_files:
                        vbox:
                            spacing 2
                            for fi, f in enumerate(_active_files):
                                hbox:
                                    spacing 5
                                    textbutton "✕":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_remove_image_marker, _img_target, fi)
                                    textbutton "▶":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_preview_sfx, f, _active_vol)
                                    text f style "sfx_txt" color "#ffcc00" size 11

        # --- Dialogue UI ---
        if _is_dialogue:
            $ _dlg_key = _sfx.DLG_KEY_PREFIX + _sfx.current_file + "|" + _sfx.current_dialogue
            $ _dlg_entry = _sfx.markers.get(_dlg_key, {})
            $ _dlg_pools = _sfx_editor_get_pools(_dlg_entry)
            $ _dlg_target = _sfx.dlg_target_pool
            $ _dlg_target = max(0, min(_dlg_target, len(_dlg_pools) - 1)) if _dlg_pools else 0
            frame:
                background "#222222"
                padding (4, 4)
                xfill True
                yminimum 0
                has vbox
                spacing 5
                text "Dialogue SFX" style "sfx_hdr"
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                vbox:
                    spacing 5
                    text "Dialogue: [_sfx.current_dialogue]" style "sfx_txt"
                    hbox:
                        spacing 5
                        if _dlg_pools:
                            textbutton "Delete":
                                style "sfx_btn"
                                text_style "sfx_btn_text"
                                xsize 50
                                action Confirm(
                                    "Delete all dialogue SFX pools for the current line?\nThis cannot be undone.",
                                    Function(_sfx_editor_clear_dialogue_markers))
                                tooltip "Remove all dialogue SFX pools"
                null height 5
                # Tab row: [+ Pool] [1] [2] ...
                hbox:
                    spacing 2
                    textbutton "+ Pool":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        xsize 48
                        action Function(_sfx_editor_add_pool, _dlg_key, "dlg")
                        tooltip "Add a new pool"
                    for pi, pool in enumerate(_dlg_pools):
                        $ _is_active = (pi == _dlg_target)
                        $ _tab_label = str(pi + 1)
                        $ _tab_count = len(pool.get("files", []))
                        textbutton _tab_label:
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            xsize 22
                            if _is_active:
                                background "#666699"
                            else:
                                background "#444444"
                            action Function(_sfx_editor_set_target_pool, "dlg", pi)
                            tooltip "Select Dialogue SFX target pool — targets D button"
                # Active pool display
                if _dlg_pools and 0 <= _dlg_target < len(_dlg_pools):
                    $ _active_pool = _dlg_pools[_dlg_target]
                    $ _active_files = _active_pool.get("files", [])
                    $ _active_vol = _active_pool.get("volume", _dlg_entry.get("volume", 1.0))
                    $ _active_label = "Pool " + str(_dlg_target + 1) + " (" + str(len(_active_files)) + " files)"
                    hbox:
                        spacing 3
                        text _active_label style "sfx_txt" size 11
                        textbutton "✕":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            action Function(_sfx_editor_remove_pool, _dlg_key, _dlg_target, "dlg")
                            tooltip "Delete this pool"
                    hbox:
                        spacing 3
                        text "Volume: {:.1f}".format(_active_vol) style "sfx_txt" size 11
                        textbutton "--":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_set_volume, _dlg_key, 1.0, _dlg_target)
                            tooltip "Reset pool volume to 1.0"
                        textbutton "-":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_adjust_volume, _dlg_key, -0.1, _dlg_target)
                        textbutton "+":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 18
                            action Function(_sfx_editor_adjust_volume, _dlg_key, 0.1, _dlg_target)
                        textbutton "++":
                            style "sfx_btn_icon"
                            text_style "sfx_btn_icon_text"
                            xsize 22
                            action Function(_sfx_editor_set_volume, _dlg_key, 5.0, _dlg_target)
                            tooltip "Max volume (5.0)"
                    if _active_files:
                        vbox:
                            spacing 2
                            for fi, f in enumerate(_active_files):
                                hbox:
                                    spacing 5
                                    textbutton "✕":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_remove_dialogue_marker, _dlg_target, fi)
                                    textbutton "▶":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_preview_sfx, f, _active_vol)
                                    text f style "sfx_txt" color "#ffcc00" size 11

        if _sfx.scan_error:
            text "[_sfx.scan_error]" style "sfx_help" color "#ff6666"

        null height 6

        # ================================================================
        # SFX POOL
        # ================================================================
        $ _pool_key = _sfx.POOL_KEY_PREFIX + (_sfx.current_file or "")
        $ _pool_entry = _sfx.markers.get(_pool_key, {})
        $ _pool_files = _pool_entry.get("files", [])
        $ _pool_freq = _pool_entry.get("frequency", 1)
        $ _pool_count = len(_pool_files)
        frame:
            background "#222222"
            padding (4, 4)
            xfill True
            yminimum 0
            has vbox
            spacing 5

            text "Autoplay SFX" style "sfx_hdr"

            if _pool_files:
                hbox:
                    spacing 5
                    text "SFX Frequency" style "sfx_txt"
                    $ slow_selected = (_pool_freq == 0)
                    $ normal_selected = (_pool_freq == 1)
                    $ fast_selected = (_pool_freq == 2)
                    $ fastest_selected = (_pool_freq == 3)
                    textbutton "Slow":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if slow_selected:
                            background "#666699"
                        else:
                            background "#444444"
                        action Function(_sfx_editor_set_pool_frequency, _pool_key, 0)
                    textbutton "Normal":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if normal_selected:
                            background "#669966"
                        else:
                            background "#444444"
                        action Function(_sfx_editor_set_pool_frequency, _pool_key, 1)
                    textbutton "Fast":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if fast_selected:
                            background "#996666"
                        else:
                            background "#444444"
                        action Function(_sfx_editor_set_pool_frequency, _pool_key, 2)
                    textbutton "Fastest":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if fastest_selected:
                            background "#996699"
                        else:
                            background "#444444"
                        action Function(_sfx_editor_set_pool_frequency, _pool_key, 3)

                $ _pool_vol = _pool_entry.get("volume", 1.0)
                hbox:
                    spacing 3
                    text "Volume: {:.1f}".format(_pool_vol) style "sfx_txt" size 11
                    textbutton "--":
                        style "sfx_btn_icon"
                        text_style "sfx_btn_icon_text"
                        xsize 22
                        action Function(_sfx_editor_set_volume, _pool_key, 1.0)
                        tooltip "Reset volume to 1.0"
                    textbutton "-":
                        style "sfx_btn_icon"
                        text_style "sfx_btn_icon_text"
                        xsize 18
                        action Function(_sfx_editor_adjust_volume, _pool_key, -0.1)
                    textbutton "+":
                        style "sfx_btn_icon"
                        text_style "sfx_btn_icon_text"
                        xsize 18
                        action Function(_sfx_editor_adjust_volume, _pool_key, 0.1)
                    textbutton "++":
                        style "sfx_btn_icon"
                        text_style "sfx_btn_icon_text"
                        xsize 22
                        action Function(_sfx_editor_set_volume, _pool_key, 5.0)
                        tooltip "Max volume (5.0)"

                text "Pool files:" style "sfx_txt"
                textbutton "Delete":
                    style "sfx_btn"
                    text_style "sfx_btn_text"
                    xsize 50
                    action Confirm(
                        "Delete all files from the current auto-play pool?\nThis cannot be undone.",
                        Function(_sfx_editor_clear_pool))
                viewport:
                    xfill True
                    ymaximum 130
                    mousewheel True
                    vbox:
                        spacing 2
                        for i, filename in enumerate(_pool_files):
                            $ _ppv = _pool_entry.get("volume", 1.0)
                            hbox:
                                spacing 2
                                textbutton "✕":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_remove_from_pool, i)
                                textbutton "▶":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_preview_sfx, filename, _ppv)
                                text filename style "sfx_txt" color "#ffcc00" size 11
            else:
                text "Click the A button in the \"Audio files\" section to add files" style "sfx_help"

        # Audio file browser
        if _sfx.audio_tree:
            text "Audio files:" style "sfx_txt"
            viewport:
                xfill True
                yfill True
                mousewheel True
                scrollbars "vertical"
                vscrollbar_xsize 6
                vscrollbar_unscrollable "hide"
                vbox:
                    spacing 2
                    for item in _sfx.visible_tree:
                        hbox:
                            spacing 2
                            # Indent
                            if item["depth"] > 0:
                                text " " * item["depth"] style "sfx_txt"
                            if item["type"] == "folder":
                                if item["expanded"]:
                                    textbutton "▾":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                else:
                                    textbutton "▸":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_folder, item["full_path"])
                                if item["has_files"]:
                                    textbutton "V":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_video_markers, item["full_path"])
                                        tooltip "Add folder to active video timestamp pool"
                                    textbutton "I":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_image_markers, item["full_path"])
                                        tooltip "Add folder to Image SFX pool"
                                    textbutton "D":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_dialogue_markers, item["full_path"])
                                        tooltip "Add folder to Dialogue SFX pool"
                                    textbutton "A":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_add_folder_to_pool, item["full_path"])
                                        tooltip "Add folder to SFX Pool"
                                textbutton item["name"]:
                                    style "sfx_btn"
                                    text_style "sfx_btn_text_sm"
                                    action Function(_sfx_editor_toggle_folder, item["full_path"])
                                    xsize None
                                    ysize 14
                            else:
                                # Play preview
                                textbutton "▶":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_preview_sfx, item["full_path"])
                                    tooltip "Preview audio"
                                # Video marker (adds to active timestamp pool)
                                textbutton "V":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_video_marker, item["index"])
                                    tooltip "Add file to active video timestamp pool"
                                # Image SFX
                                textbutton "I":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_image_marker, item["index"])
                                    tooltip "Add to Image SFX pool"
                                # Dialogue SFX
                                textbutton "D":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_dialogue_marker, item["index"])
                                    tooltip "Add to Dialogue SFX pool"
                                # Autoplay SFX
                                textbutton "A":
                                    style "sfx_btn_icon"
                                    text_style "sfx_btn_icon_text"
                                    action Function(_sfx_editor_add_to_pool, item["index"])
                                    tooltip "Add to Autoplay SFX pool"
                                if item.get("enabled", True):
                                    textbutton "☑":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_file_enabled, item["full_path"])
                                        tooltip "Click to exclude from markers"
                                else:
                                    textbutton "☐":
                                        style "sfx_btn_icon"
                                        text_style "sfx_btn_icon_text"
                                        action Function(_sfx_editor_toggle_file_enabled, item["full_path"])
                                        tooltip "Click to include in markers"
                                text item["name"] style "sfx_txt" color "#ffcc00"


