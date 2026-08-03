
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
    size 12
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
    hover_sound None
    activate_sound None

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
    size 12
    color "#ffffff"
    background "#333333"
    xsize 72
    padding (2, 2)
    ypadding 2

style sfx_vscrollbar:
    xsize 4
    base_bar Solid("#1a1a1a")
    thumb Solid("#555555")
    hover_thumb Solid("#888888")


###############################################################################
# SECTION 4.5: Reusable Component Screens
###############################################################################

init -990 python:
    def _cue_make_tab_action(fn, args_tuple, pi):
        """Build Function(fn, *args_tuple, pi) — appends pi to fixed args.
        Used by sfx_pool_tabs and sfx_file_list to construct per-row actions
        inside a for loop, where the loop variable must be the last argument."""
        return Function(fn, *(tuple(args_tuple) + (pi,)))

# Volume row: label + - button + slider bar + + button
# dec_action/inc_action are pre-built Function() objects — call sites differ
# in which adjust function they use (master vs pool vs video-pool vs autoplay).
screen sfx_vol_row(label_text, dec_action, entry_dict, inc_action):
    hbox:
        spacing 3
        text label_text style "sfx_txt" size 11
        textbutton "-":
            style "sfx_btn_icon"
            text_style "sfx_btn_icon_text"
            xsize 18
            action dec_action
        bar:
            value DictValue(entry_dict, "volume", range=5.0)
            xsize 80
            ysize 14
            left_bar Solid("#007AFF")
            right_bar Solid("#333333")
            thumb Solid("#cccccc")
            hover_thumb Solid("#ffffff")
            changed _cue_editor_on_volume_bar_changed
        textbutton "+":
            style "sfx_btn_icon"
            text_style "sfx_btn_icon_text"
            xsize 18
            action inc_action

# Icon button: tiny button with sfx_btn_icon / sfx_btn_icon_text styles.
# Most callers don't need xsize (style default is 14); pass an int to override.
# Pass tt=None to skip the tooltip.
screen sfx_icon_button(text, action, tt, xsize):
    textbutton text:
        style "sfx_btn_icon"
        text_style "sfx_btn_icon_text"
        if xsize is not None:
            xsize xsize
        if tt is not None:
            tooltip tt
        action action

# Float input: textbutton that becomes an input on click, Enter to confirm.
# field_name: string for VariableInputValue
# commit_action: Function() called on Enter — must return True (valid) or False (invalid)
# display_text: the label shown on the textbutton
screen sfx_float_input(field_name, commit_action, display_text):
    default editing = False
    key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
    key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
    if editing:
        input:
            style "sfx_input"
            value VariableInputValue(field_name)
            default True
            xsize 80
    else:
        textbutton display_text:
            style "sfx_btn"
            text_style "sfx_btn_text"
            action SetLocalVariable("editing", True)
            tooltip "Click to edit. Press Enter to confirm."

# Reusable time input: -- - [textbutton | input] + ++ with nudge buttons and Enter-to-commit.
# field_name: string for VariableInputValue (e.g. "_cue.edit_video_ts_text")
# commit_action: Function() called on Enter to confirm
# dec100/dec10/inc10/inc100_action: Function() called by nudge buttons
screen sfx_time_input(field_name, commit_action, dec100_action, dec10_action,
                      inc10_action, inc100_action, display_text):
    default editing = False
    key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
    key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
    hbox:
        spacing 3
        use sfx_icon_button("--", dec100_action, "Nudge back 100 ms", 22)
        use sfx_icon_button("-", dec10_action, "Nudge back 10 ms", 18)

        if editing:
            input:
                style "sfx_input"
                value VariableInputValue(field_name)
                default True
        else:
            textbutton display_text:
                style "sfx_btn"
                text_style "sfx_btn_text"
                action [SetLocalVariable("editing", True), Function(_cue_editor_sync_video_ts_text)]
                tooltip "Click to edit. Press Enter to confirm."

        use sfx_icon_button("+", inc10_action, "Nudge forward 10 ms", 18)
        use sfx_icon_button("++", inc100_action, "Nudge forward 100 ms", 22)

# Pool tab row: optional Delete button, + Pool button, numbered tabs [1][2]...
# tab_action_fn(tab_action_args..., pi) is called when tab pi is clicked.
# delete_xsize/tab_xsize override the default button width (pass None for default).
screen sfx_pool_tabs(count, target, show_delete, delete_confirm, delete_action,
                     delete_tt, add_action, add_tt, tab_action_fn, tab_action_args,
                     tab_tt):
    hbox:
        spacing 5
        if show_delete:
            textbutton "Delete All":
                style "sfx_btn"
                text_style "sfx_btn_text"
                xsize 70
                action Confirm(delete_confirm, delete_action)
                tooltip delete_tt
        textbutton "+ Pool":
            style "sfx_btn"
            text_style "sfx_btn_text"
            xsize 48
            action add_action
            tooltip add_tt
        for pi in range(count):
            $ _is_active = (pi == target)
            textbutton str(pi + 1):
                style "sfx_btn"
                text_style "sfx_btn_text"
                xsize 14
                if _is_active:
                    background "#669966"
                else:
                    background "#444444"
                action _cue_make_tab_action(tab_action_fn, tab_action_args, pi)
                tooltip tab_tt

# Scrollable file list: ✕ remove + ▶ preview per row.
# remove_fn(remove_args..., fi) is called for row fi.
# preview_vol is the effective volume passed to _cue_editor_preview_cue.
# row_spacing controls horizontal gap in each row (5 for most, 2 for autoplay).
screen sfx_file_list(files, remove_fn, remove_args, preview_vol, row_spacing):
    viewport:
        xfill True
        ymaximum 120
        mousewheel True
        scrollbars "vertical"
        style_group "sfx"
        vscrollbar_unscrollable "hide"
        vbox:
            spacing 2
            for fi, f in enumerate(files):
                hbox:
                    spacing row_spacing
                    use sfx_icon_button("✕", _cue_make_tab_action(remove_fn, remove_args, fi), None, None)
                    use sfx_icon_button("▶", Function(_cue_editor_preview_cue, f, preview_vol), None, None)
                    text f style "sfx_txt" color "#ffcc00" size 11

# Section frame: styled frame + header, with transclude for child content.
# Usage: use sfx_section_frame("Title"):  ...children...
screen sfx_section_frame(header_text):
    frame:
        background "#222222"
        padding (4, 4)
        xfill True
        yminimum 0
        has vbox
        spacing 5
        text header_text style "sfx_hdr"
        transclude

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
            if _cue.triggers_active:
                textbutton "☑ SFX Active":
                    style "sfx_btn"
                    text_style "sfx_btn_text_sm"
                    background "#446644"
                    hover_background "#558855"
                    action Function(_cue_editor_toggle_active)
                    tooltip "SFX triggers are ON (F4 to toggle)"
            else:
                textbutton "☐ SFX Active":
                    style "sfx_btn"
                    text_style "sfx_btn_text_sm"
                    background "#664444"
                    hover_background "#885555"
                    action Function(_cue_editor_toggle_active)
                    tooltip "SFX triggers are OFF (F4 to toggle)"
            null width 5
            use sfx_icon_button("📋", Function(_cue_editor_copy_context), "Copy current context config (Shift + 1)", None)
            use sfx_icon_button("📄", Function(_cue_editor_paste_context), "Paste context config (Shift + 2)", None)
            null width 5
            $ _backup_tooltip = "Backup config to " + _cue.config_filename
            use sfx_icon_button("💾", Function(_cue_editor_dump_markers), _backup_tooltip, None)
            $ _restore_tooltip = "Restore config from " + _cue.config_filename
            use sfx_icon_button("📂", Function(_cue_editor_restore_markers_from_file), _restore_tooltip, None)
            null width 5
            use sfx_icon_button("⏸", Function(renpy.invoke_in_new_context, renpy.pause), "Pause game (F3)", None)
            use sfx_icon_button("⟳", [Function(_cue_editor_refresh_detections), Function(_cue_editor_scan_audio)], "Refresh overlay", None)
            use sfx_icon_button("✕", Function(_cue_editor_hide), "Close overlay", None)

        # --- Mode detection ---
        $ _is_video = _cue.top_layer_type == 'movie'
        $ _is_dialogue = bool(_cue.current_dialogue)

        # --- Video UI ---
        if _is_video:
            use sfx_section_frame("Video SFX"):
                $ _vid_name = _cue.current_file if _cue.current_file else "?"
                text "Video: [_vid_name]" style "sfx_txt"
                hbox:
                    spacing 5
                    hbox:
                        spacing 0
                        text "Time: " style "sfx_txt"
                        add SelfUpdatingLabel(_cue_editor_time_label_getter, style="sfx_txt")
                    add Solid("#555555") xsize 2 ysize 15
                    hbox:
                        spacing 0
                        text "Frames: " style "sfx_txt"
                        add SelfUpdatingLabel(_cue_editor_frame_label_getter, style="sfx_txt")
                hbox:
                    spacing 5
                    if _cue.paused:
                        textbutton "▶":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_cue_editor_toggle_pause)
                    else:
                        textbutton "⏸":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_cue_editor_toggle_pause)
                    textbutton "-1f":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_cue_editor_seek_frame, -1)
                        tooltip "Seek backwards 1 frame (inaccurate and requires restarting video)"
                    textbutton "+1f":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_cue_editor_seek_frame, 1)
                        tooltip "Seek forward 1 frame (inaccurate)"
                    
                    fixed:
                        ysize 14
                        xsize 2
                        add Solid("#555555")
                    textbutton "Repeat":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_cue_editor_open_repeat_dialog)
                        tooltip "Repeat selected markers at regular intervals across the video"
                    textbutton "Delete":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Confirm(_cue_editor_get_delete_confirm_message(), Function(_cue_editor_remove_selected_markers))
                        tooltip "Delete selected markers"
                    textbutton "?":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action NullAction()
                        tooltip "• Timestamp markers are draggable\n• Alt + Click or Shift + Click to create a selection group\n• Select markers and use Repeat to copy them at intervals"
                # --- Timeline visualizer ---
                fixed:
                    xfill True
                    ysize 18
                    add VideoTimeline()
                # Video marker tabs + active pool
                $ _vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
                $ _vid_entry = _cue.markers.get(_vid_key, {})
                $ _vid_entries = _vid_entry.get("timestamps", [])
                $ _vid_count = len(_vid_entries)
                $ _vid_target = _cue.vid_target_pool
                $ _vid_target = max(0, min(_vid_target, _vid_count - 1)) if _vid_entries else 0
                # --- Draggable video marker timeline ---
                if _vid_entries:
                    add _VideoMarkerTimeline(
                        get_markers=_cue_editor_mtl_get_markers,
                        get_active=_cue_editor_mtl_get_active,
                        set_active=_cue_editor_mtl_set_active,
                        set_time=_cue_editor_mtl_set_time,
                        get_dur=_cue_editor_mtl_get_dur,
                    )
                null height 5
                if _vid_entry:
                    $ _vid_entry.setdefault("volume", 1.0)
                    $ _master_vol = _vid_entry.get("volume", 1.0)
                    $ _dec = Function(_cue_editor_adjust_master_volume, _vid_key, -0.1)
                    $ _inc = Function(_cue_editor_adjust_master_volume, _vid_key, 0.1)
                    use sfx_vol_row("Master: {:.1f}".format(_master_vol), _dec, _vid_entry, _inc)
                use sfx_pool_tabs(_vid_count, _vid_target, bool(_vid_entries),
                    "Delete all video timestamp markers for the current video?",
                    Function(_cue_editor_clear_video_markers), "Delete all video SFX for the current video",
                    Function(_cue_editor_add_video_pool), "Create a new empty timestamp at current time",
                    _cue_editor_set_vid_target_pool, (), "Select timestamp pool — V button adds files here")
                # Active pool display
                if _vid_entries and 0 <= _vid_target < _vid_count:
                    $ _active_ts = _vid_entries[_vid_target]
                    $ _active_files = _active_ts.get("files", [])
                    $ _active_vol = _active_ts.get("volume", _cue.VOL_DEFAULT)
                    $ _active_eff = _cue_editor_get_effective_volume(_vid_entry, _vid_key, ts_index=_vid_target)
                    $ _active_label = "Pool " + str(_vid_target + 1) + " (" + str(len(_active_files)) + " files)"
                    hbox:
                        spacing 3
                        text _active_label style "sfx_txt" size 11
                        textbutton "Duplicate":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Function(_cue_editor_duplicate_video_pool, _vid_target)
                            tooltip "Duplicate this timestamp pool"
                        textbutton "Delete":
                            style "sfx_btn"
                            text_style "sfx_btn_text"
                            action Confirm("Delete this timestamp pool?", Function(_cue_editor_remove_video_pool, _vid_target))
                            tooltip "Delete this timestamp pool"
                    # Editable timestamp + nudge buttons
                    hbox:
                        spacing 3
                        text "Time:" style "sfx_txt" size 11
                        $ _dec10 = Function(_cue_editor_nudge_video_ts, -0.01)
                        $ _dec100 = Function(_cue_editor_nudge_video_ts, -0.1)
                        $ _inc10 = Function(_cue_editor_nudge_video_ts, 0.01)
                        $ _inc100 = Function(_cue_editor_nudge_video_ts, 0.1)
                        $ _commit = Function(_cue_editor_commit_video_ts)
                        $ _display = _cue_editor_format_time(_active_ts["time"])
                        use sfx_time_input("_cue.edit_video_ts_text", _commit, _dec100, _dec10,
                                           _inc10, _inc100, _display)
                    # Volume controls
                    $ _active_ts.setdefault("volume", 1.0)
                    $ _dec = Function(_cue_editor_adjust_video_volume, -0.1)
                    $ _inc = Function(_cue_editor_adjust_video_volume, 0.1)
                    $ _vol_label = "Volume: {:.1f} (eff {:.1f})".format(_active_vol, _active_eff)
                    use sfx_vol_row(_vol_label, _dec, _active_ts, _inc)
                    # File list
                    if _active_files:
                        use sfx_file_list(_active_files, _cue_editor_remove_video_file, (_vid_target,), _active_eff, 5)
                    else:
                        text "Click the V button in the SFX Library to add files to this pool." style "sfx_help"
                else:
                    text "Click the V button in the SFX Library to create a new pool or add to the active pool." style "sfx_help"


        # --- Image UI ---
        $ _has_image = bool(_cue.current_file) and not _is_video
        if _has_image:
            $ _img_key = create_img_key(_cue.current_file)
            $ _img_entry = _cue.markers.get(_img_key, {})
            $ _img_pools = _img_entry.get("pools", [])
            $ _img_target = _cue.img_target_pool
            $ _img_target = max(0, min(_img_target, len(_img_pools) - 1)) if _img_pools else 0
            use sfx_section_frame("Image SFX"):
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                vbox:
                    spacing 5
                    text "Image: [_cue.current_file]" style "sfx_txt"
                null height 5
                if _img_entry:
                    $ _img_entry.setdefault("volume", 1.0)
                    $ _master_vol = _img_entry.get("volume", 1.0)
                    $ _dec = Function(_cue_editor_adjust_master_volume, _img_key, -0.1)
                    $ _inc = Function(_cue_editor_adjust_master_volume, _img_key, 0.1)
                    use sfx_vol_row("Master: {:.1f}".format(_master_vol), _dec, _img_entry, _inc)
                # Tab row: [+ Pool] [1] [2] ...
                use sfx_pool_tabs(len(_img_pools), _img_target, bool(_img_pools),
                    "Delete all image SFX for the current image?",
                    Function(_cue_editor_clear_image_markers), "Delete all image SFX for the current image",
                    Function(_cue_editor_add_pool, _img_key, "img"), "Add a new pool",
                    _cue_editor_set_target_pool, ("img",), "Select Image SFX target pool — targets I button")
                # Active pool display
                if _img_pools and 0 <= _img_target < len(_img_pools):
                    $ _active_pool = _img_pools[_img_target]
                    $ _active_files = _active_pool.get("files", [])
                    $ _active_vol = _active_pool.get("volume", 1.0)
                    $ _active_eff = _cue_editor_get_effective_volume(_img_entry, _img_key, pool_index=_img_target)
                    $ _active_label = "Pool " + str(_img_target + 1) + " (" + str(len(_active_files)) + " files)"
                    hbox:
                        spacing 3
                        text _active_label style "sfx_txt" size 11
                        use sfx_icon_button("✕", Confirm("Delete this pool?", Function(_cue_editor_remove_pool, _img_key, _img_target, "img")), "Delete this pool", None)
                    $ _active_pool.setdefault("volume", 1.0)
                    $ _dec = Function(_cue_editor_adjust_volume, _img_key, -0.1, _img_target)
                    $ _inc = Function(_cue_editor_adjust_volume, _img_key, 0.1, _img_target)
                    $ _vol_label = "Volume: {:.1f} (eff {:.1f})".format(_active_vol, _active_eff)
                    use sfx_vol_row(_vol_label, _dec, _active_pool, _inc)
                    if _active_pool.get("trigger_on_shake", False):
                        textbutton "☑ Trigger on screen shake":
                            style "sfx_btn"
                            text_style "sfx_btn_text_sm"
                            action Function(_cue_editor_toggle_shake_trigger)
                            tooltip "Play SFX when a screen shake occurs"
                    else:
                        textbutton "☐ Trigger on screen shake":
                            style "sfx_btn"
                            text_style "sfx_btn_text_sm"
                            action Function(_cue_editor_toggle_shake_trigger)
                            tooltip "Play SFX when a screen shake occurs"
                    if _active_files:
                        use sfx_file_list(_active_files, _cue_editor_remove_image_marker, (_img_target,), _active_eff, 5)
                    else:
                        text "Click the I button in the SFX Library to add files to this pool." style "sfx_help"
                else:
                    text "Click the I button in the SFX Library to create a new pool or add files to the active pool." style "sfx_help"

        # --- Dialogue UI ---
        if _is_dialogue:
            $ _dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))
            $ _dlg_entry = _cue.markers.get(_dlg_key, {})
            $ _dlg_pools = _dlg_entry.get("pools", [])
            $ _dlg_target = _cue.dlg_target_pool
            $ _dlg_target = max(0, min(_dlg_target, len(_dlg_pools) - 1)) if _dlg_pools else 0
            use sfx_section_frame("Dialogue SFX"):
                fixed:
                    xfill True
                    ysize 1
                    add Solid("#555555")
                vbox:
                    spacing 5
                    text "Dialogue: [_cue.current_dialogue]" style "sfx_txt"
                null height 5
                if _dlg_entry:
                    $ _dlg_entry.setdefault("volume", 1.0)
                    $ _master_vol = _dlg_entry.get("volume", 1.0)
                    $ _dec = Function(_cue_editor_adjust_master_volume, _dlg_key, -0.1)
                    $ _inc = Function(_cue_editor_adjust_master_volume, _dlg_key, 0.1)
                    use sfx_vol_row("Master: {:.1f}".format(_master_vol), _dec, _dlg_entry, _inc)
                # Tab row: [+ Pool] [1] [2] ...
                use sfx_pool_tabs(len(_dlg_pools), _dlg_target, bool(_dlg_pools),
                    "Delete all dialogue SFX for the current dialogue?",
                    Function(_cue_editor_clear_dialogue_markers), "Delete all dialogue SFX for the current dialogue",
                    Function(_cue_editor_add_pool, _dlg_key, "dlg"), "Add a new pool",
                    _cue_editor_set_target_pool, ("dlg",), "Select Dialogue SFX target pool — targets D button")
                # Active pool display
                if _dlg_pools and 0 <= _dlg_target < len(_dlg_pools):
                    $ _active_pool = _dlg_pools[_dlg_target]
                    $ _active_files = _active_pool.get("files", [])
                    $ _active_vol = _active_pool.get("volume", 1.0)
                    $ _active_eff = _cue_editor_get_effective_volume(_dlg_entry, _dlg_key, pool_index=_dlg_target)
                    $ _active_label = "Pool " + str(_dlg_target + 1) + " (" + str(len(_active_files)) + " files)"
                    hbox:
                        spacing 3
                        text _active_label style "sfx_txt" size 11
                        use sfx_icon_button("✕", Confirm("Delete this pool?", Function(_cue_editor_remove_pool, _dlg_key, _dlg_target, "dlg")), "Delete this pool", None)
                    $ _active_pool.setdefault("volume", 1.0)
                    $ _dec = Function(_cue_editor_adjust_volume, _dlg_key, -0.1, _dlg_target)
                    $ _inc = Function(_cue_editor_adjust_volume, _dlg_key, 0.1, _dlg_target)
                    $ _vol_label = "Volume: {:.1f} (eff {:.1f})".format(_active_vol, _active_eff)
                    use sfx_vol_row(_vol_label, _dec, _active_pool, _inc)
                    if _active_files:
                        use sfx_file_list(_active_files, _cue_editor_remove_dialogue_marker, (_dlg_target,), _active_eff, 5)
                    else:
                        text "Click the D button in the SFX Library to add files to this pool." style "sfx_help"
                else:
                    text "Click the D button in the SFX Library to create a new pool or add to the active pool." style "sfx_help"

        if _cue.scan_error:
            text "[_cue.scan_error]" style "sfx_help" color "#ff6666"

        # ================================================================
        # Autoplay SFX
        # ================================================================
        $ _autoplay_key = create_autoplay_key(_cue.current_file or "")
        $ _autoplay_entry = _cue.markers.get(_autoplay_key, {})
        $ _autoplay_files = _autoplay_entry.get("files", [])
        $ _autoplay_freq = _autoplay_entry.get("frequency", 1)
        $ _autoplay_count = len(_autoplay_files)
        use sfx_section_frame("Autoplay SFX"):

            if _autoplay_files:
                hbox:
                    spacing 5
                    text "SFX Frequency" style "sfx_txt"
                    $ slow_selected = (_autoplay_freq == 0)
                    $ normal_selected = (_autoplay_freq == 1)
                    $ fast_selected = (_autoplay_freq == 2)
                    $ fastest_selected = (_autoplay_freq == 3)
                    textbutton "Slow":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if slow_selected:
                            background "#666699"
                        else:
                            background "#444444"
                        action Function(_cue_editor_set_autoplay_frequency, _autoplay_key, 0)
                    textbutton "Normal":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if normal_selected:
                            background "#669966"
                        else:
                            background "#444444"
                        action Function(_cue_editor_set_autoplay_frequency, _autoplay_key, 1)
                    textbutton "Fast":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if fast_selected:
                            background "#996666"
                        else:
                            background "#444444"
                        action Function(_cue_editor_set_autoplay_frequency, _autoplay_key, 2)
                    textbutton "Fastest":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        if fastest_selected:
                            background "#996699"
                        else:
                            background "#444444"
                        action Function(_cue_editor_set_autoplay_frequency, _autoplay_key, 3)

                $ _autoplay_entry.setdefault("volume", 1.0)
                $ _pool_vol = _autoplay_entry.get("volume", 1.0)
                $ _dec = Function(_cue_editor_adjust_volume, _autoplay_key, -0.1)
                $ _inc = Function(_cue_editor_adjust_volume, _autoplay_key, 0.1)
                use sfx_vol_row("Volume: {:.1f}".format(_pool_vol), _dec, _autoplay_entry, _inc)

                hbox:
                    spacing 5
                    text "Pool files:" style "sfx_txt"
                    textbutton "Delete":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Confirm(
                            "Delete all files from the current Autoplay pool?",
                            Function(_cue_editor_clear_autoplay_pool))
                        tooltip "Delete all files from the current Autoplay pool"
                use sfx_file_list(_autoplay_files, _cue_editor_remove_from_autoplay_pool, (), _autoplay_entry.get("volume", 1.0), 2)
            else:
                text "Click the A button in the SFX Library to add files." style "sfx_help"

        # Audio file browser
        if _cue.audio_tree:
            use sfx_section_frame("SFX Library"):
                viewport:
                    xfill True
                    yfill True
                    mousewheel True
                    scrollbars "vertical"
                    style_group "sfx"
                    vscrollbar_unscrollable "hide"
                    vbox:
                        spacing 2
                        for item in _cue.visible_tree:
                            hbox:
                                spacing 2
                                # Indent
                                if item["depth"] > 0:
                                    text " " * item["depth"] style "sfx_txt"
                                if item["type"] == "folder":
                                    if item["expanded"]:
                                        use sfx_icon_button("▾", Function(_cue_editor_toggle_folder, item["full_path"]), None, None)
                                    else:
                                        use sfx_icon_button("▸", Function(_cue_editor_toggle_folder, item["full_path"]), None, None)
                                    if item["has_files"]:
                                        use sfx_icon_button("V", Function(_cue_editor_add_folder_to_video_markers, item["full_path"]), "Add folder to active video timestamp pool", None)
                                        use sfx_icon_button("I", Function(_cue_editor_add_folder_to_image_markers, item["full_path"]), "Add folder to Image SFX pool", None)
                                        use sfx_icon_button("D", Function(_cue_editor_add_folder_to_dialogue_markers, item["full_path"]), "Add folder to Dialogue SFX pool", None)
                                        use sfx_icon_button("A", Function(_cue_editor_add_folder_to_autoplay_pool, item["full_path"]), "Add folder to Autoplay SFX Pool", None)
                                    textbutton item["name"]:
                                        style "sfx_btn"
                                        text_style "sfx_btn_text_sm"
                                        action Function(_cue_editor_toggle_folder, item["full_path"])
                                        xsize None
                                        ysize 14
                                else:
                                    # Play preview
                                    use sfx_icon_button("▶", Function(_cue_editor_preview_cue, item["full_path"]), "Preview audio", None)
                                    # Video marker (adds to active timestamp pool)
                                    use sfx_icon_button("V", Function(_cue_editor_add_video_marker, item["index"]), "Add file to active video timestamp pool", None)
                                    # Image SFX
                                    use sfx_icon_button("I", Function(_cue_editor_add_image_marker, item["index"]), "Add to Image SFX pool", None)
                                    # Dialogue SFX
                                    use sfx_icon_button("D", Function(_cue_editor_add_dialogue_marker, item["index"]), "Add to Dialogue SFX pool", None)
                                    # Autoplay SFX
                                    use sfx_icon_button("A", Function(_cue_editor_add_to_autoplay_pool, item["index"]), "Add to Autoplay SFX pool", None)
                                    if item.get("enabled", True):
                                        use sfx_icon_button("☑", Function(_cue_editor_toggle_file_enabled, item["full_path"]), "Click to exclude from markers", None)
                                    else:
                                        use sfx_icon_button("☐", Function(_cue_editor_toggle_file_enabled, item["full_path"]), "Click to include in markers", None)
                                    text item["name"] style "sfx_txt" color "#ffcc00"


###############################################################################
# SECTION 6: Repeat Pattern Dialog
###############################################################################

screen sfx_repeat_pattern_dialog():
    $ anchor = _cue.repeat_pattern_anchor
    $ offsets = _cue.repeat_pattern_offsets
    $ sel_count = _cue.repeat_pattern_sel_count

    button:
        xpos 500
        ypos 8
        padding (16, 8)
        background "#2a2a2a"
        hover_background "#2a2a2a"
        xmaximum 400
        action NullAction()

        vbox:
                spacing 8
                text "Repeat Pattern" style "sfx_hdr"

                hbox:
                    spacing 5
                    text "Selected:" style "sfx_txt"
                    text "{} marker(s)".format(sel_count) style "sfx_txt" color "#ffcc00"

                hbox:
                    spacing 5
                    text "Anchor:" style "sfx_txt"
                    text _cue_editor_format_time(anchor) style "sfx_txt" color "#ffcc00"

                null height 5

                hbox:
                    spacing 3
                    xalign 0.0
                    text "Interval (s):" style "sfx_txt" size 12
                    $ _commit = Function(_cue_editor_commit_repeat_interval)
                    $ _display = _cue.repeat_interval_text
                    use sfx_icon_button("-", Function(_cue_editor_nudge_repeat_interval, -0.1), "Nudge back 100 ms", 18)
                    use sfx_float_input("_cue.repeat_interval_text", _commit, _display)
                    use sfx_icon_button("+", Function(_cue_editor_nudge_repeat_interval, 0.1), "Nudge forward 100 ms", 18)

                hbox:
                    spacing 3
                    xalign 0.0
                    text "Repeat:" style "sfx_txt" size 12
                    $ _dec = Function(_cue_editor_nudge_repeat_count, -1)
                    $ _inc = Function(_cue_editor_nudge_repeat_count, 1)
                    $ _commit = Function(_cue_editor_commit_repeat_count)
                    $ _display = _cue.repeat_count_text
                    use sfx_icon_button("-", _dec, "Decrement by 1", 18)
                    use sfx_float_input("_cue.repeat_count_text", _commit, _display)
                    use sfx_icon_button("+", _inc, "Increment by 1", 18)

                $ _preview_label = _cue_editor_repeat_preview_text()
                text _preview_label style "sfx_help"

                null height 5

                hbox:
                    spacing 8
                    xalign 1.0
                    textbutton "Cancel":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action Function(_cue_editor_hide_repeat_dialog)
                    textbutton "Apply":
                        style "sfx_btn"
                        text_style "sfx_btn_text"
                        action [
                            Function(_cue_editor_do_repeat_pattern),
                            Function(_cue_editor_hide_repeat_dialog),
                        ]
