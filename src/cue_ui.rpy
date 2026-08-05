
###############################################################################
# SECTION 4: Styles (game-agnostic — all properties explicit, no inheritance)
###############################################################################

style cue_frame is empty:
    background "#000000ee"
    padding (8, 6)
    xfill True

style cue_btn is empty:
    background "#444444"
    hover_background "#666666"
    padding (2, 0)
    hover_sound None
    activate_sound None

style cue_btn_text is empty:
    size 12
    color "#ffffff"
    hover_color "#ffffff"
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5
    xanchor 0.5
    yanchor 0.5
    adjust_spacing False

style cue_btn_text_sm is cue_btn_text:
    size 10

style cue_btn_icon is empty:
    xysize (16, 16)
    padding (0, 0)
    background "#444444"
    hover_background "#666666"
    insensitive_background "#2a2a2a"
    hover_sound None
    activate_sound None

style cue_btn_icon_text is empty:
    size 12
    color "#ffffff"
    insensitive_color "#666666"
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

style cue_txt is empty:
    size 12
    color "#cccccc"
    font "DejaVuSans.ttf"

style cue_hdr is cue_txt:
    size 14
    color "#ffcc00"
    bold True

style cue_help is cue_txt:
    size 12
    color "#aaaaaa"

style cue_input is cue_txt:
    size 12
    color "#ffffff"
    background "#333333"
    xsize 72
    padding (2, 2)
    ypadding 2

style cue_vscrollbar:
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
        Used by cue_pool_tabs and cue_file_list to construct per-row actions
        inside a for loop, where the loop variable must be the last argument."""
        return Function(fn, *(tuple(args_tuple) + (pi,)))

    def _cue_count_file_list_rows(folder_label, folder_children, files):
        """Estimate visible rows in cue_file_list. Used to decide whether
        the viewport scroll wrapper (ymaximum 120) is needed."""
        rows = 0
        
        if folder_label is not None:
            rows += 1  # folder header
            if _cue.file_tree.expanded_file_refs.get(folder_label, False) and folder_children:
                rows += len(folder_children)
        for f in files:
            rows += 1  # file row or folder-ref header
            if f.endswith("/"):
                if _cue.file_tree.expanded_file_refs.get(f, False):
                    rows += len(_cue_resolve_files([f]))
        return rows

# Volume row: label + - button + slider bar + + button
# dec_action/inc_action are pre-built Function() objects — call sites differ
# in which adjust function they use (master vs pool vs video-pool vs loop).
screen cue_vol_row(label_text, dec_action, entry_dict, inc_action):
    hbox:
        spacing 3
        text label_text style "cue_txt" size 11
        textbutton "-":
            style "cue_btn_icon"
            text_style "cue_btn_icon_text"
            xsize 18
            action dec_action
        bar:
            value DictValue(entry_dict, "volume", range=5.0)
            xsize 60
            ysize 14
            left_bar Solid("#007AFF")
            right_bar Solid("#333333")
            thumb Solid("#cccccc")
            hover_thumb Solid("#ffffff")
            changed _cue.volume.on_bar_changed
        textbutton "+":
            style "cue_btn_icon"
            text_style "cue_btn_icon_text"
            xsize 18
            action inc_action

# Icon button: tiny button with cue_btn_icon / cue_btn_icon_text styles.
# Most callers don't need xsize (style default is 14); pass an int to override.
# Pass tt=None to skip the tooltip.
screen cue_icon_button(text, action, tt=None, xsize=16, enabled=True):
    textbutton text:
        style "cue_btn_icon"
        text_style "cue_btn_icon_text"
        ysize 16
        if xsize is not None:
            xsize xsize
        if tt is not None:
            tooltip tt
        sensitive enabled
        action action

screen cue_folder_txt_button(label, action_fn, ysize=16):
    textbutton label:
        style "cue_btn"
        text_style "cue_btn_text"
        action action_fn
        ysize ysize

# Float input: textbutton that becomes an input on click, Enter to confirm.
# field_name: string for VariableInputValue
# commit_action: Function() called on Enter — must return True (valid) or False (invalid)
# display_text: the label shown on the textbutton
screen cue_float_input(field_name, commit_action, display_text):
    default editing = False
    key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
    key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
    if editing:
        input:
            style "cue_input"
            value VariableInputValue(field_name)
            default True
            xsize 80
            ysize 16
    else:
        textbutton display_text:
            style "cue_btn"
            text_style "cue_btn_text"
            ysize 16
            action SetLocalVariable("editing", True)
            tooltip "Click to edit. Press Enter to confirm."

# Reusable time input: -- - [textbutton | input] + ++ with nudge buttons and Enter-to-commit.
# field_name: string for VariableInputValue (e.g. "_cue.markers.video.edit_text")
# commit_action: Function() called on Enter to confirm
# dec100/dec10/inc10/inc100_action: Function() called by nudge buttons
screen cue_time_input(field_name, commit_action, dec100_action, dec10_action,
                      inc10_action, inc100_action, display_text):
    default editing = False
    key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
    key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
    hbox:
        spacing 3
        use cue_icon_button("--", dec100_action, None, 22)
        use cue_icon_button("-", dec10_action)

        if editing:
            input:
                style "cue_input"
                value VariableInputValue(field_name)
                default True
        else:
            textbutton display_text:
                style "cue_btn"
                text_style "cue_btn_text"
                action [SetLocalVariable("editing", True), Function(_cue.markers.video.sync_text)]
                tooltip "Click to edit. Press Enter to confirm."

        use cue_icon_button("+", inc10_action)
        use cue_icon_button("++", inc100_action, None, 22)

# Pool tab row: optional Delete button, + Pool button, numbered tabs [1][2]...
# tab_action_fn(tab_action_args..., pi) is called when tab pi is clicked.
# delete_xsize/tab_xsize override the default button width (pass None for default).
screen cue_pool_tabs(count, target, show_delete, delete_confirm, delete_action,
                     delete_tt, add_action, add_tt, tab_action_fn, tab_action_args,
                     tab_tt):
    hbox:
        spacing 5
        if show_delete:
            use cue_icon_button("✕", Function(_cue.confirm_dialog.show, delete_confirm, delete_action), delete_tt, None)
        textbutton "+ Pool":
            style "cue_btn"
            text_style "cue_btn_text"
            xsize 48
            action add_action
            tooltip add_tt
        for pi in range(count):
            $ _is_active = (pi == target)
            textbutton str(pi + 1):
                style "cue_btn"
                text_style "cue_btn_text"
                xsize 14
                if _is_active:
                    background "#669966"
                else:
                    background "#444444"
                action _cue_make_tab_action(tab_action_fn, tab_action_args, pi)
                tooltip tab_tt

# Scrollable file list: ✕ remove + ▶ preview per row.
# remove_fn(remove_args..., fi) is called for row fi.
# preview_vol is the effective volume passed to _cue_preview_sfx.
# row_spacing controls horizontal gap in each row (5 for most, 2 for loop).
# folder_child_remove_fn(trigger_key, pool_index, fi, child_file) is called when
#   removing a single file from an expanded folder ref (detach operation).
#   Pass None to hide ✕ on folder children (e.g. for video pools).
# Inner vbox — extracted so cue_file_list can conditionally wrap it in a viewport.
screen _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                            trigger_key, pool_index, folder_child_remove_fn,
                            folder_label, folder_children):
    vbox:
        spacing 2
        if folder_label is not None:
            # --- Virtual folder (e.g. preset-backed pool / video pool) ---
            $ _is_expanded = _cue.file_tree.expanded_file_refs.get(folder_label, False)
            $ _count = len(folder_children) if folder_children else 0
            hbox:
                spacing row_spacing
                if _is_expanded:
                    use cue_icon_button("▾", Function(_cue.file_tree.toggle_file_ref_expand, folder_label), None, None)
                else:
                    use cue_icon_button("▸", Function(_cue.file_tree.toggle_file_ref_expand, folder_label), None, None)
                use cue_icon_button("✕", Function(remove_fn, *remove_args), "Remove preset", None)
                use cue_icon_button("▶", Function(_cue_preview_sfx, (folder_children or [""])[0], preview_vol), "Preview random file from preset", None)
                use cue_folder_txt_button(folder_label, Function(_cue.file_tree.toggle_file_ref_expand, folder_label))
                text "({} files)".format(_count) style "cue_txt" color "#888888" size 10
            if _is_expanded and folder_children:
                for _child in folder_children:
                    hbox:
                        spacing row_spacing
                        text "    " style "cue_txt"  # indent
                        if folder_child_remove_fn is not None:
                            use cue_icon_button("✕",
                                Function(folder_child_remove_fn, trigger_key, pool_index, 0, _child),
                                "Remove file from pool", None)
                        use cue_icon_button("▶", Function(_cue_preview_sfx, _child, preview_vol), None, None)
                        text _child style "cue_txt" color "#ffcc00" size 11
        for fi, f in enumerate(files):
            if f.endswith("/"):
                # --- Folder ref: expandable (matches SFX Library folder UI) ---
                $ _is_expanded = _cue.file_tree.expanded_file_refs.get(f, False)
                $ _count = len(_cue_resolve_files([f]))
                hbox:
                    spacing row_spacing
                    if _is_expanded:
                        use cue_icon_button("▾", Function(_cue.file_tree.toggle_file_ref_expand, f), None, None)
                    else:
                        use cue_icon_button("▸", Function(_cue.file_tree.toggle_file_ref_expand, f), None, None)
                    use cue_icon_button("✕", _cue_make_tab_action(remove_fn, remove_args, fi), "Remove folder ref", None)
                    use cue_icon_button("▶", Function(_cue_preview_sfx, (_cue_resolve_files([f]) or [""])[0], preview_vol), "Preview random file from folder", None)
                    use cue_folder_txt_button(f, Function(_cue.file_tree.toggle_file_ref_expand, f))
                    text "({} files)".format(_count) style "cue_txt" color "#888888" size 10
                if _is_expanded:
                    for _child in _cue_resolve_files([f]):
                        hbox:
                            spacing row_spacing
                            text "    " style "cue_txt"  # indent
                            if folder_child_remove_fn is not None:
                                use cue_icon_button("✕",
                                    Function(folder_child_remove_fn, trigger_key, pool_index, fi, _child),
                                    "Remove file from the folder ref", None)
                            use cue_icon_button("▶", Function(_cue_preview_sfx, _child, preview_vol), None, None)
                            $ _display = _child[len(f):]  # strip folder ref prefix
                            text _display style "cue_txt" color "#ffcc00" size 11
            else:
                # --- Regular file ---
                hbox:
                    spacing row_spacing
                    use cue_icon_button("✕", _cue_make_tab_action(remove_fn, remove_args, fi), None, None)
                    use cue_icon_button("▶", Function(_cue_preview_sfx, f, preview_vol), None, None)
                    text f style "cue_txt" color "#ffcc00" size 11

# Scrollable file list: only wraps in a viewport when content exceeds ~6 rows (120 px).
screen cue_file_list(files, remove_fn, remove_args, preview_vol, row_spacing,
                     trigger_key=None, pool_index=None, folder_child_remove_fn=None,
                     folder_label=None, folder_children=None):
    $ _rows = _cue_count_file_list_rows(folder_label, folder_children, files)
    if _rows > 6:
        viewport:
            xfill True
            ymaximum 120
            mousewheel True
            scrollbars "vertical"
            style_group "cue"
            vscrollbar_unscrollable "hide"
            use _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                                    trigger_key, pool_index, folder_child_remove_fn,
                                    folder_label, folder_children)
    else:
        use _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                                trigger_key, pool_index, folder_child_remove_fn,
                                folder_label, folder_children)

# Section frame: styled frame + header, with transclude for child content.
style cue_section_hdr_btn is empty:
    background None
    hover_background "#333333"
    padding (4, 2)
    xfill True
    hover_sound None
    activate_sound None

# Usage: use cue_section_frame("Title"):  ...children...
# Click the header to collapse/expand the section content.
screen cue_section_frame(header_text):
    $ _collapsed = _cue.file_tree.collapsed_sections.get(header_text, False)
    $ _arrow = "▸" if _collapsed else "▾"  # ▸ collapsed, ▾ expanded
    frame:
        background "#222222"
        padding (4, 4)
        xfill True
        yminimum 0
        vbox:
            spacing 8
            button:
                style "cue_section_hdr_btn"
                action Function(_cue.file_tree.toggle_section, header_text)
                hbox:
                    xfill True
                    text header_text style "cue_hdr"
                    null width 8
                    text _arrow style "cue_help" xalign 1.0
            if not _collapsed:
                transclude

# Generic context section: shared by dialogue, image, and loop SFX.
# ctx: marker context with add_pool, remove_pool, clear, set_active,
#      get_active, remove_file (e.g. _cue.markers.dialogue)
# vol_key: trigger key for volume/marker lookups
# subtitle: optional "Label: value" text below header (None to skip)
# subject: noun for confirm messages ("dialogue", "image", "file")
# btn_letter: "D", "I", or "L" for hint messages
# description: short line explaining when this SFX triggers (None to skip)
# Transclude: extra UI between pool label and volume row (shake toggle,
#             frequency selector). Reads _cue._pool_ui["pool"].
screen cue_context_section(section_title, ctx, vol_key, subtitle, subject, btn_letter, description=None):
    $ _entry = _cue.markers.get(vol_key, {})
    $ _pools = _entry.get("pools", [])
    $ _target = ctx.get_active()
    $ _target = max(0, min(_target, len(_pools) - 1)) if _pools else 0
    use cue_section_frame(section_title):
        if subtitle is not None:
            fixed:
                xfill True
                ysize 1
                add Solid("#555555")
            vbox:
                spacing 5
                text subtitle style "cue_txt"
        if _entry:
            $ _entry.setdefault("volume", 1.0)
            $ _master_vol = _entry.get("volume", 1.0)
            $ _dec = Function(_cue.volume.adjust_master, vol_key, -0.1)
            $ _inc = Function(_cue.volume.adjust_master, vol_key, 0.1)
            use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _dec, _entry, _inc)
        use cue_pool_tabs(len(_pools), _target, bool(_pools),
            "Delete all {} for the current {}?".format(section_title.lower(), subject),
            Function(ctx.clear), "Delete all {} for the current {}".format(section_title.lower(), subject),
            Function(ctx.add_pool), "Add a new pool",
            ctx.set_active, (), "Select {} target pool — targets {} button".format(section_title, btn_letter))

        if _pools and 0 <= _target < len(_pools):
            $ _active_pool = _pools[_target]
            $ _r = _cue.markers.resolve_pool(_active_pool)
            $ _is_preset_pool = "preset" in _active_pool
            $ _active_pool.setdefault("volume", _r.volume)
            $ _active_vol = _r.volume
            $ _active_eff = _cue.volume.get_effective(_entry, vol_key, pool_index=_target)
            if _is_preset_pool:
                $ _active_label = "Pool " + str(_target + 1) + " (Preset: " + _active_pool["preset"] + ")"
            else:
                $ _active_label = "Pool " + str(_target + 1) + " (" + str(len(_cue_resolve_files(_r.files))) + " files)"
            $ _cue._pool_ui = {"pool": _active_pool, "files": _r.files, "target": _target, "freq": _r.frequency}
            hbox:
                spacing 5
                text _active_label style "cue_txt" size 11
                null width 5
                use cue_icon_button("💾", Function(_cue.preset_dialog.open, vol_key, _target), "Save pool as a preset", None)
                use cue_icon_button("✕", Function(ctx.remove_pool, _target), "Delete pool", None)
                $ _dec = Function(_cue.volume.adjust, vol_key, -0.1, _target)
                $ _inc = Function(_cue.volume.adjust, vol_key, 0.1, _target)
                null width 5
                if abs(_active_vol - _active_eff) > 0.01:
                    $ _vol_label = "Volume: {:.1f} ({:.1f} total)".format(_active_vol, _active_eff)
                else:
                    $ _vol_label = "Volume: {:.1f}".format(_active_vol)
                use cue_vol_row(_vol_label, _dec, _active_pool, _inc)

            transclude
            if _r.files:
                if _is_preset_pool:
                    # Preset-backed: render as expandable folder
                    use cue_file_list([], _cue_detach_pool_at, (vol_key, _target), _active_eff, 5,
                        trigger_key=vol_key, pool_index=_target,
                        folder_label=_active_pool["preset"],
                        folder_children=_cue_resolve_files(_r.files),
                        folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                else:
                    use cue_file_list(_r.files, ctx.remove_file, (_target,), _active_eff, 5,
                        trigger_key=vol_key, pool_index=_target,
                        folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
            else:
                if description is not None:
                    text description style "cue_help"
                text "Click the {} button in the SFX Library to add files to this pool.".format(btn_letter) style "cue_help"
        else:
            if description is not None:
                text description style "cue_help"
            text "Click the {} button in the SFX Library to create a new pool or add files to the active pool.".format(btn_letter) style "cue_help"

# Toggle textbutton: ☑ label when checked, ☐ when unchecked.
# on_bg/on_hover/off_bg/off_hover override backgrounds per state (None = style default).
screen cue_toggle_btn(checked, label, action, tt_on, tt_off=None,
                       on_bg=None, on_hover=None, off_bg=None, off_hover=None,
                       enabled=True):
    if checked:
        textbutton "☑ " + label:
            style "cue_btn"
            text_style "cue_btn_text"
            sensitive enabled
            if on_bg is not None:
                background on_bg
            if on_hover is not None:
                hover_background on_hover
            action action
            tooltip tt_on
    else:
        textbutton "☐ " + label:
            style "cue_btn"
            text_style "cue_btn_text"
            sensitive enabled
            if off_bg is not None:
                background off_bg
            if off_hover is not None:
                hover_background off_hover
            action action
            if tt_off is None:
                tooltip tt_on
            else:
                tooltip tt_off

###############################################################################
# SECTION 5: Overlay Screen
###############################################################################


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
                "#446644", "#558855", "#664444", "#885555")
            null width 5
            use cue_icon_button("📋", Function(_cue.markers.copy_context), "Copy current context config (Shift + 1)", None)
            use cue_icon_button("📄", Function(_cue.markers.paste_context), "Paste context config (Shift + 2)", None)
            null width 5
            $ _backup_tooltip = "Backup config to " + _cue.config_filename
            use cue_icon_button("💾", Function(_cue.markers.backup_to_file), _backup_tooltip, None)
            $ _restore_tooltip = "Restore config from " + _cue.config_filename
            use cue_icon_button("📂", Function(_cue.markers.restore_from_file), _restore_tooltip, None)
            null width 5
            use cue_icon_button("⏸", Function(renpy.invoke_in_new_context, renpy.pause), "Pause game (F3)", None)
            use cue_icon_button("⟳", [Function(_cue_refresh_context), Function(_cue_scan_audio)], "Refresh overlay", None)
            use cue_icon_button("✕", Function(_cue_hide_overlay), "Close overlay", None)

        # --- Mode detection ---
        $ _is_video = _cue.top_layer_type == 'movie'
        $ _is_dialogue = bool(_cue.current_dialogue)

        # --- Video UI ---
        if _is_video and not _cue.video_editor.active:
            use cue_section_frame("Video SFX"):
                $ _vid_name = _cue.current_file if _cue.current_file else "?"
                text "Video: [_vid_name]" style "cue_txt"
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
                    if _cue.vid_manager.paused:
                        textbutton "▶":
                            style "cue_btn"
                            text_style "cue_btn_text"
                            action Function(_cue.vid_manager.toggle_pause)
                    else:
                        textbutton "⏸":
                            style "cue_btn"
                            text_style "cue_btn_text"
                            action Function(_cue.vid_manager.toggle_pause)
                    textbutton "-1f":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.vid_manager.seek_frame, -1)
                        tooltip "Seek backwards 1 frame (inaccurate and requires restarting video)"
                    textbutton "+1f":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.vid_manager.seek_frame, 1)
                        tooltip "Seek forward 1 frame (inaccurate)"
                
                    fixed:
                        ysize 14
                        xsize 2
                        add Solid("#555555")
                    textbutton "Edit Video":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.video_editor.open_editor)
                        tooltip "Change the playback speed of this video"
                    fixed:
                        ysize 14
                        xsize 2
                        add Solid("#555555")
                    textbutton "Repeat":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.beat.open)
                        tooltip "Repeat selected markers at regular intervals across the video"
                    $ _has_markers = _cue.markers.video.has_markers()
                    use cue_icon_button("💾", Function(_cue.video_preset_dialog.open), "Save all video markers as a preset", None)
                    use cue_icon_button("✕",
                        Function(_cue.markers.video.remove_selected) if _has_markers else NullAction(),
                        "Delete selected markers" if _has_markers else "No markers to delete", None)
                    use cue_icon_button("?", 
                        NullAction(), 
                        ("• Markers and marker groups are draggable.\n"
                        + "• (Alt + Click) or (Shift + Click) to create a marker group.\n"
                        + "• Use Repeat to copy selected markers at an interval.\n"
                        + "• Get your markers timed to the first 'beat', find the interval to the next 'beat', then use Repeat to finish."), 
                        None)
                # --- Timeline visualizer ---
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
                    $ _active_files = _active_pool.get("files", [])
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
                        text _active_label style "cue_txt" size 11

                        null width 5

                        use cue_icon_button("♻", Function(_cue.markers.video.duplicate_pool, _vid_target), "Duplicate pool", None)
                        use cue_icon_button("✕", Function(_cue.markers.video.remove_pool, _vid_target), "Delete pool", None)

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
                        $ _display = _cue_format_time(_active_pool["time"])
                        use cue_time_input("_cue.markers.video.edit_text", _commit, _dec100, _dec10,
                                           _inc10, _inc100, _display)
                    # File list
                    if _is_preset_ts:
                        # Preset-backed: render as expandable folder via cue_file_list
                        use cue_file_list([], _cue_detach_active_video_ts, (), _active_eff, 5,
                            folder_label=_preset_name, folder_children=_active_files,
                            trigger_key=_vid_key, pool_index=_vid_target,
                            folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                    elif _active_files:
                        use cue_file_list(_active_files, _cue.markers.video.remove_file, (_vid_target,), _active_eff, 5,
                            trigger_key=_vid_key, pool_index=_vid_target,
                            folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
                    else:
                        text "SFX plays when this video reaches the marked time(s)." style "cue_help"
                        text "Click the V button in the SFX Library to add files to this pool." style "cue_help"
                else:
                    text "SFX plays when this video reaches the marked time(s)." style "cue_help"
                    text "Click the V button in the SFX Library to create a new pool or add to the active pool." style "cue_help"


        # --- Video Editor ---
        if _is_video and _cue.video_editor.active:
            $ _ved = _cue.video_editor
            use cue_section_frame("Video Editor"):
                hbox:
                    spacing 4
                    textbutton "← Back to Video SFX":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.video_editor.close_editor)
                $ _vid_name = _cue.current_file if _cue.current_file else "?"
                text "Video: [_vid_name]" style "cue_txt"
                if _ved.has_backup:
                    textbutton "Restore Original Video":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.video_editor.open_restore)
                        tooltip "Restore the original video file from backup"
                hbox:
                    spacing 4
                    text "Speed:" style "cue_txt" size 11
                    $ _commit = Function(_cue.video_editor.commit_text)
                    $ _display = "{:.1f}x".format(float(_ved.factor_text))
                    use cue_icon_button("-", Function(_cue.video_editor.nudge, -0.1))
                    use cue_float_input("_cue.video_editor.factor_text", _commit, _display)
                    use cue_icon_button("+", Function(_cue.video_editor.nudge, 0.1))
                    null width 5
                hbox:
                    spacing 4
                    $ _source_fps = _ved.source_fps
                    use cue_toggle_btn(_ved.interpolate, "Interpolate Frames",
                        Function(_cue.video_editor.toggle_interpolate),
                        "Uses ffmpeg to generate in-between frames for smoother motion. Video takes longer to edit.",
                        enabled=_source_fps > 0 and _source_fps < 55)
                    if _source_fps < 0:
                        text "Checking source fps..." style "cue_help" size 10 yalign 0.5
                    elif _source_fps >= 55:
                        text "Already {}fps — no interpolation needed".format(_source_fps) style "cue_help" size 10 yalign 0.5
                    elif _ved.interpolate:
                        $ _target_fps = min(60, _source_fps * 2)
                        text "{}fps → {}fps".format(_source_fps, _target_fps) style "cue_help" size 10 yalign 0.5
                    else:
                        text "Source: {}fps".format(_source_fps) style "cue_help" size 10 yalign 0.5
                hbox:
                    spacing 4
                        Function(_cue.video_editor.toggle_fast_preview),
                        "Fast low-quality encode to judge the edited speed. Disables frame interpolation.")
                    text "Faster encode, lower quality" style "cue_help" size 10 yalign 0.5
                null height 3
                textbutton "Create":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    sensitive _ved._ready
                    action Function(_cue.video_editor.prepare_create)
                if _ved.last_error:
                    text _ved.last_error style "cue_txt" size 11 color "#ff6666"

                # --- Edit queue ---
                if _ved._jobs:
                    add Solid("#555555") ysize 1
                    timer 0.2 repeat True action [
                        Function(_cue.video_editor.poll),
                        Function(_cue.video_editor._refresh_ui),
                    ]
                    frame:
                        background "#222222"
                        padding (4, 4)
                        yminimum 0
                        xfill True
                        vbox:
                            spacing 3
                            text "Edit Queue" style "cue_txt" size 14 bold True
                            null height 2
                            for _job in _ved._jobs:
                                hbox:
                                    spacing 4
                                    if _job.status in ("queued", "analyzing", "encoding"):
                                        use cue_icon_button("✕", Function(_cue.video_editor.cancel_job, _job.job_id), "Cancel job", None)
                                    else:
                                        use cue_icon_button("✕", Function(_cue.video_editor.remove_job, _job.job_id), "Remove from queue", None)
                                    text _job.filename() style "cue_txt" size 11
                                    text "(" + _job.status_text() + ")" style "cue_txt" size 11
                                    if _job.status != "queued":
                                        $ _elapsed = int(_job.elapsed())
                                        text ("%d:%02d" % (_elapsed // 60, _elapsed % 60)) style "cue_txt" size 11 color "#aaaaaa"

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
                text "Interval" style "cue_txt" size 11
                $ slow_selected = (_freq == 0)
                $ normal_selected = (_freq == 1)
                $ fast_selected = (_freq == 2)
                $ fastest_selected = (_freq == 3)
                textbutton "Slow":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    if slow_selected:
                        background "#669966"
                    else:
                        background "#444444"
                    action Function(_cue.markers.loop.set_frequency, 0)
                textbutton "Normal":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    if normal_selected:
                        background "#669966"
                    else:
                        background "#444444"
                    action Function(_cue.markers.loop.set_frequency, 1)
                textbutton "Fast":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    if fast_selected:
                        background "#669966"
                    else:
                        background "#444444"
                    action Function(_cue.markers.loop.set_frequency, 2)
                textbutton "Fastest":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    if fastest_selected:
                        background "#669966"
                    else:
                        background "#444444"
                    action Function(_cue.markers.loop.set_frequency, 3)

        # Audio file browser
        use cue_section_frame("SFX Library"):
            if not _cue.audio_tree:
                text "[_cue.scan_error]" style "cue_help" color "#ff6666"
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
                            if _cue.file_tree.presets_expanded:
                                use cue_icon_button("▾", Function(_cue.file_tree.toggle_presets_expand), None, None)
                            else:
                                use cue_icon_button("▸", Function(_cue.file_tree.toggle_presets_expand), None, None)
                            $ _preset_names = _cue.markers.list_presets()
                            use cue_folder_txt_button("Presets/", Function(_cue.file_tree.toggle_presets_expand))
                        if _cue.file_tree.presets_expanded:
                            for _pname in _preset_names:
                                $ _pdata = _cue.markers.get_preset(_pname)
                                $ _p_expanded = _cue.file_tree.expanded_presets.get(_pname, False)
                                $ _p_files = _cue_resolve_files(_pdata.get("files", [])) if _pdata else []
                                $ _pfile_count = len(_p_files)
                                hbox:
                                    spacing 2
                                    text "  " style "cue_txt"  # indent under Presets/
                                    if _p_expanded:
                                        use cue_icon_button("▾", Function(_cue.file_tree.toggle_preset_expand, _pname), None, None)
                                    else:
                                        use cue_icon_button("▸", Function(_cue.file_tree.toggle_preset_expand, _pname), None, None)
                                    use cue_icon_button("✕", Function(_cue_confirm_delete_preset, _pname), "Delete preset", None)
                                    use cue_icon_button("▶", Function(_cue_preview_preset, _pname), "Preview random file from preset", None)
                                    use cue_icon_button("V", Function(_cue.markers.video.apply_preset, _pname), "Apply preset to current video at playhead position", None, enabled=_is_video)
                                    use cue_icon_button("I", Function(_cue.markers.image.apply_preset, _pname), "Apply preset to active Image SFX pool", None, enabled=_has_image)
                                    use cue_icon_button("D", Function(_cue.markers.dialogue.apply_preset, _pname), "Apply preset to active Dialogue SFX pool", None, enabled=_is_dialogue)
                                    use cue_icon_button("L", Function(_cue.markers.loop.apply_preset, _pname), "Apply preset to active Loop SFX pool", None)
                                    use cue_folder_txt_button(_pname, Function(_cue.file_tree.toggle_preset_expand, _pname))
                                if _p_expanded:
                                    for _child in _p_files:
                                        hbox:
                                            spacing 2
                                            text "    " style "cue_txt"  # double indent
                                            use cue_icon_button("✕", Function(_cue.markers.preset_remove_file, _pname, _child), "Remove file from preset", None)
                                            use cue_icon_button("▶", Function(_cue_preview_sfx, _child), "Preview file", None)
                                            text _child style "cue_txt" color "#ffcc00" size 11
                        # --- Video Presets folder ---
                        hbox:
                            spacing 2
                            if _cue.file_tree.video_presets_expanded:
                                use cue_icon_button("▾", Function(_cue.file_tree.toggle_video_presets_expand), None, None)
                            else:
                                use cue_icon_button("▸", Function(_cue.file_tree.toggle_video_presets_expand), None, None)
                            $ _vp_names = _cue.markers.list_video_presets()
                            use cue_folder_txt_button("Video Presets/", Function(_cue.file_tree.toggle_video_presets_expand))
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
                                    if _vp_expanded:
                                        use cue_icon_button("▾", Function(_cue.file_tree.toggle_video_preset_expand, _vpname), None, None)
                                    else:
                                        use cue_icon_button("▸", Function(_cue.file_tree.toggle_video_preset_expand, _vpname), None, None)
                                    use cue_icon_button("✕", Function(_cue_confirm_delete_video_preset, _vpname), "Delete video preset", None)
                                    use cue_icon_button("▶", Function(_cue_preview_video_preset, _vpname), "Preview random file from video preset", None)
                                    use cue_icon_button("V", Function(_cue_maybe_apply_video_preset, _vpname), "Apply video markers to the current video", None, enabled=_is_video)
                                    use cue_folder_txt_button(_vpname, Function(_cue.file_tree.toggle_video_preset_expand, _vpname))
                                if _vp_expanded:
                                    for _pool in _vp_pools:
                                        $ _pool_time = _pool.get("time", 0)
                                        $ _pool_files = len(_cue_resolve_files(_pool.get("files", [])))
                                        hbox:
                                            spacing 2
                                            text "    " style "cue_txt"  # double indent
                                            text "{} ({} files)".format(_cue_format_time(_pool_time), _pool_files) style "cue_txt" color "#ffcc00" size 11
                        # --- Folder/file tree ---
                        for item in _cue.file_tree.visible_tree:
                            hbox:
                                spacing 2
                                # Indent
                                if item["depth"] > 0:
                                    text " " * item["depth"] style "cue_txt"
                                if item["type"] == "folder":
                                    if item["expanded"]:
                                        use cue_icon_button("▾", Function(_cue.file_tree.toggle_folder, item["full_path"]), None, None)
                                    else:
                                        use cue_icon_button("▸", Function(_cue.file_tree.toggle_folder, item["full_path"]), None, None)
                                    if item["has_files"]:
                                        use cue_icon_button("V", Function(_cue.markers.video.add_folder, item["full_path"]), "Add folder to active video pool", None, enabled=_is_video)
                                        use cue_icon_button("I", Function(_cue.markers.image.add_folder, item["full_path"]), "Add folder to Image SFX pool", None, enabled=_has_image)
                                        use cue_icon_button("D", Function(_cue.markers.dialogue.add_folder, item["full_path"]), "Add folder to Dialogue SFX pool", None, enabled=_is_dialogue)
                                        use cue_icon_button("L", Function(_cue.markers.loop.add_folder, item["full_path"]), "Add folder to Loop SFX Pool", None)
                                    use cue_folder_txt_button(item["name"], Function(_cue.file_tree.toggle_folder, item["full_path"]))
                                else:
                                    # Play preview
                                    use cue_icon_button("▶", Function(_cue_preview_sfx, item["full_path"]), "Preview audio", None)
                                    # Video marker (adds to active pool)
                                    use cue_icon_button("V", Function(_cue.markers.video.add_file, item["index"]), "Add file to active video pool", None, enabled=_is_video)
                                    # Image SFX
                                    use cue_icon_button("I", Function(_cue.markers.image.add_file, item["index"]), "Add to Image SFX pool", None, enabled=_has_image)
                                    # Dialogue SFX
                                    use cue_icon_button("D", Function(_cue.markers.dialogue.add_file, item["index"]), "Add to Dialogue SFX pool", None, enabled=_is_dialogue)
                                    # Loop SFX
                                    use cue_icon_button("L", Function(_cue.markers.loop.add_file, item["index"]), "Add to Loop SFX pool", None)
                                    if item.get("enabled", True):
                                        use cue_icon_button("☑", Function(_cue.file_tree.toggle_file_enabled, item["full_path"]), "Click to disable globally", None)
                                    else:
                                        use cue_icon_button("☐", Function(_cue.file_tree.toggle_file_enabled, item["full_path"]), "Click to enable globally", None)
                                    text item["name"] style "cue_txt" color "#ffcc00"


###############################################################################
# SECTION 6: Repeat Pattern Dialog
###############################################################################

screen cue_repeat_pattern_dialog():
    $ anchor = _cue.beat.anchor
    $ offsets = _cue.beat.offsets
    $ sel_count = _cue.beat.sel_count

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
                text "Repeat Pattern" style "cue_hdr"

                hbox:
                    spacing 5
                    text "Selected:" style "cue_txt"
                    text "{} marker(s)".format(sel_count) style "cue_txt" color "#ffcc00"

                hbox:
                    spacing 5
                    text "Anchor:" style "cue_txt"
                    text _cue_format_time(anchor) style "cue_txt" color "#ffcc00"

                null height 5

                hbox:
                    spacing 3
                    xalign 0.0
                    text "Interval (s):" style "cue_txt" size 12
                    $ _commit = Function(_cue.beat.commit_interval)
                    $ _display = _cue.beat.interval_text
                    use cue_icon_button("-", Function(_cue.beat.nudge_interval, -0.1))
                    use cue_float_input("_cue.beat.interval_text", _commit, _display)
                    use cue_icon_button("+", Function(_cue.beat.nudge_interval, 0.1))

                hbox:
                    spacing 3
                    xalign 0.0
                    text "Repeat:" style "cue_txt" size 12
                    $ _dec = Function(_cue.beat.nudge_count, -1)
                    $ _inc = Function(_cue.beat.nudge_count, 1)
                    $ _commit = Function(_cue.beat.commit_count)
                    $ _display = _cue.beat.count_text
                    use cue_icon_button("-", _dec)
                    use cue_float_input("_cue.beat.count_text", _commit, _display)
                    use cue_icon_button("+", _inc)

                $ _preview_label = _cue.beat.preview_text()
                text _preview_label style "cue_help"

                null height 5

                hbox:
                    spacing 8
                    textbutton "Cancel":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action Function(_cue.beat.hide)
                    textbutton "Apply":
                        style "cue_btn"
                        text_style "cue_btn_text"
                        action [
                            Function(_cue.beat.apply),
                            Function(_cue.beat.hide),
                        ]


###############################################################################
# SECTION 7: Save Preset Dialog
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
        background "#2a2a2a"
        hover_background "#2a2a2a"
        xmaximum 400
        action NullAction()

        vbox:
            spacing 8
            text "Save Preset" style "cue_hdr"

            hbox:
                spacing 5
                text "Files:" style "cue_txt"
                text "{} file(s)".format(_file_count) style "cue_txt" color "#ffcc00"

            hbox:
                spacing 5
                text "Volume:" style "cue_txt"
                text "{:.1f}".format(_r.volume) style "cue_txt" color "#ffcc00"

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
                textbutton "Cancel":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    action Function(_d.cancel)
                textbutton "Save":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    action [
                        Function(_d.commit),
                    ]


###############################################################################
# SECTION 7b: Save Video Preset Dialog
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
        background "#2a2a2a"
        hover_background "#2a2a2a"
        xmaximum 400
        action NullAction()

        vbox:
            spacing 8
            text "Save Video Preset" style "cue_hdr"

            hbox:
                spacing 5
                text "Markers:" style "cue_txt"
                text "{} marker(s)".format(_marker_count) style "cue_txt" color "#ffcc00"

            hbox:
                spacing 5
                text "Span:" style "cue_txt"
                text _span_text style "cue_txt" color "#ffcc00"

            hbox:
                spacing 5
                text "Files:" style "cue_txt"
                text "{} file(s)".format(_total_files) style "cue_txt" color "#ffcc00"

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
                textbutton "Cancel":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    action Function(_d.cancel)
                textbutton "Save":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    action [
                        Function(_d.commit),
                    ]


###############################################################################
# SECTION 8: Confirm Dialog
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
        background "#2a2a2a"
        hover_background "#2a2a2a"
        xmaximum 400
        action NullAction()

        vbox:
            spacing 8
            text _d.message style "cue_txt"

            null height 5

            hbox:
                spacing 8
                xalign 0.5
                textbutton "Cancel":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    action Function(_d.hide)
                textbutton "OK":
                    style "cue_btn"
                    text_style "cue_btn_text"
                    action [
                        Function(_d.hide),
                        _d.on_confirm,
                    ]


init -990 python:
    def _cue_confirm_delete_preset(preset_name):
        """Show confirmation dialog for preset deletion."""
        _cue.confirm_dialog.show(
            "Delete preset '{}'?".format(preset_name),
            Function(_cue.markers.delete_preset, preset_name),
        )

    def _cue_confirm_delete_video_preset(preset_name):
        """Show confirmation dialog for video preset deletion."""
        _cue.confirm_dialog.show(
            "Delete video preset '{}'?".format(preset_name),
            Function(_cue.markers.delete_video_preset, preset_name),
        )

    def _cue_maybe_apply_video_preset(preset_name):
        """Apply a video preset, warning if markers would be dropped."""
        out_count = _cue.markers.video_preset_out_of_range(preset_name)
        if out_count > 0:
            preset = _cue.markers.get_video_preset(preset_name)
            total = len(preset.get("pools", [])) if preset else 0
            dur = _cue.vid_manager.get_duration()
            msg = "{} of {} marker(s) won't fit (video is {:.1f}s). Apply anyway?".format(
                out_count, total, dur)
            _cue.confirm_dialog.show(
                msg,
                Function(_cue.markers.apply_video_preset, preset_name))
        else:
            _cue.markers.apply_video_preset(preset_name)

    def _cue_preview_video_preset(preset_name):
        """Preview a random file from a video preset."""
        preset = _cue.markers.get_video_preset(preset_name)
        if preset is None:
            return
        all_files = []
        for pool in preset.get("pools", []):
            all_files.extend(pool.get("files", []))
        resolved = _cue_resolve_files(all_files)
        if resolved:
            import random as _random
            f = _random.choice(resolved)
            _cue_preview_sfx(f)

    def _cue_detach_active_video_ts(*args):
        """Detach the active video pool from its preset reference.
        Called by the ✕ button on a preset folder ref in cue_file_list."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return
        entry = _cue.markers.get(vid_key)
        if entry is None:
            return
        _cue.markers._detach_pool(vid_key, _cue.markers.video.target_pool)
        _cue.markers.save_persistent()

    def _cue_detach_pool_at(trigger_key, pool_index):
        """Detach a pool from its preset reference at the given trigger_key
        and pool_index. Called by the ✕ on a preset folder in cue_file_list."""
        _cue.markers._detach_pool(trigger_key, pool_index)
        _cue.markers.save_persistent()
