###############################################################################
# Overlay Screen
###############################################################################


###############################################################################
# Key Listener — invisible screen that catches global hotkeys and drives the
# tick engine.
###############################################################################

screen cue_key_listener():
    zorder 10000

    key CUE_KEYMAP_TOGGLE_OVERLAY action Function(_cue_toggle_overlay)
    key CUE_KEYMAP_COPY_CONTEXT action Function(_cue.markers.copy_context)
    key CUE_KEYMAP_PASTE_CONTEXT action Function(_cue.markers.paste_context)
    key CUE_KEYMAP_TOGGLE_ACTIVE action Function(_cue_toggle_active)
    key CUE_KEYMAP_PAUSE action Function(renpy.invoke_in_new_context, renpy.pause)
    key CUE_KEYMAP_UNDO action Function(_cue.undo.undo)
    key CUE_KEYMAP_REDO action Function(_cue.undo.redo)
    key CUE_KEYMAP_SPEED_UP action Function(_cue.speed_resolver.cycle_speed, 1)
    key CUE_KEYMAP_SPEED_DOWN action Function(_cue.speed_resolver.cycle_speed, -1)
    key CUE_KEYMAP_TOGGLE_SFX action Function(_cue.file_tree.toggle_section, CUE_SFX_LIBRARY_HEADER)
    if _cue.debug:
        key CUE_KEYMAP_QUIT_RELAUNCH action Function(renpy.quit, relaunch=True)
    timer 0.02 repeat True action Function(_cue_tick_trigger, _update_screens=False)

###############################################################################
# Main Overlay — the sidebar frame.
###############################################################################

init python:
    # Scale up UI as window shrinks.
    def _cue_overlay_zoom():
        pw, _ph = renpy.get_physical_size()
        vw = renpy.config.screen_width
        if pw > 0 and vw > 0:
            return max(1.0, float(vw) / float(pw))
        return 1.0

screen cue_overlay():

    zorder 9999
    modal False

    $ _z = _cue_overlay_zoom()

    button:
        at Transform(zoom=_z)
        xalign 0.0
        yalign 0.0
        xsize int(500 / _z)
        ysize int(renpy.config.screen_height / _z)
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

    # Place popper targets here.

    # --- Tooltip overlay (after poppers so it draws above them) ---
    if _tt:
        add CueTooltip(_tt)

    # --- Marker timeline tooltip (rendered last so it's always on top) ---
    add CueMarkerTooltipOverlay()


# =============================================================================
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen cue_overlay_content():
    fixed:
        xfill True
        yfill True
        vbox:
            spacing 4

            # --- Top bar: active checkbox + copy + paste + dump + restore + refresh + close ---
            use cue_header_toolbar()

            # --- Settings page replaces all content below the toolbar ---
            if _cue.is_settings_visible:
                use cue_settings_page()
            else:
                # --- Mode detection ---
                $ _is_video = _cue.top_layer_type == 'movie'

                # --- Video VFX / SFX ---
                if _is_video:
                    use cue_video_vfx()
                    use cue_video_sfx()

                # --- Image UI ---
                $ _has_image = bool(_cue.current_file) and not _is_video
                if _has_image:
                    $ _img_key = _cue_create_img_key(_cue.current_file)
                    use cue_context_section("Image SFX", _cue.markers.image, _img_key,
                        "Image: " + _cue.current_file, "image", "I",
                        "SFX plays when this image is displayed."):
                        $ _p = _cue._pool_ui["pool"]
                        use cue_checkbox(_p.get("trigger_on_shake", False),
                            "Trigger on screen shake",
                            Function(_cue_toggle_shake_trigger),
                            "Play SFX when a screen shake occurs")
                        use cue_exclusive_row(_cue.markers.image)

                # --- Dialogue UI ---
                $ _is_dialogue = bool(_cue.current_dialogue)
                if _is_dialogue:
                    $ _dlg_key = _cue_create_dlg_key((_cue.current_file, _cue.current_dialogue))
                    use cue_context_section("Dialogue SFX", _cue.markers.dialogue, _dlg_key,
                        "Dialogue: " + _cue.current_dialogue, "dialogue", "D",
                        "SFX plays when this line of dialogue is displayed."):
                        use cue_exclusive_row(_cue.markers.dialogue)

                # Loop SFX
                $ _loop_key = _cue_create_loop_key(_cue.current_file or "")
                use cue_context_section("Loop SFX", _cue.markers.loop, _loop_key,
                    None, "file", "L",
                    "SFX plays on a loop when this image/video is displayed."):
                    $ _freq = _cue._pool_ui.get("freq", CueLoopFrequency.NORMAL)
                    hbox:
                        spacing 5
                        box_wrap True
                        box_wrap_spacing 3
                        text "Interval:" style "cue_txt"
                        use cue_select_btn(
                            "Slowest",
                            (_freq == CueLoopFrequency.SLOWEST),
                            Function(_cue.markers.loop.set_frequency, CueLoopFrequency.SLOWEST),
                            tt="~6.3s between plays")
                        use cue_select_btn(
                            "Slow",
                            (_freq == CueLoopFrequency.SLOW),
                            Function(_cue.markers.loop.set_frequency, CueLoopFrequency.SLOW),
                            tt="~3.8s between plays")
                        use cue_select_btn(
                            "Normal",
                            (_freq == CueLoopFrequency.NORMAL),
                            Function(_cue.markers.loop.set_frequency, CueLoopFrequency.NORMAL),
                            tt="~2.1s between plays")
                        use cue_select_btn(
                            "Fast",
                            (_freq == CueLoopFrequency.FAST),
                            Function(_cue.markers.loop.set_frequency, CueLoopFrequency.FAST),
                            tt="~0.6s between plays")
                        use cue_select_btn(
                            "Fastest",
                            (_freq == CueLoopFrequency.FASTEST),
                            Function(_cue.markers.loop.set_frequency, CueLoopFrequency.FASTEST),
                            tt="~0.2s between plays")

                    use cue_exclusive_row(_cue.markers.loop)

                # Audio file browser (in-flow, only when overlay mode is OFF)
                if not _cue.file_tree.sfx_library_overlay_mode:
                    use cue_sfx_library(_is_video, _has_image, _is_dialogue)

        # SFX Library overlay mode: entire section floats at bottom
        if not _cue.is_settings_visible and _cue.file_tree.sfx_library_overlay_mode:
            $ _sfx_collapsed = _cue.file_tree.collapsed_sections.get(CUE_SFX_LIBRARY_HEADER, False)
            $ _sfx_z = _cue_overlay_zoom()
            $ _sfx_full_h = int(renpy.config.screen_height / _sfx_z)
            $ _sfx_40pct = int(_sfx_full_h * 0.4)
            $ _sfx_90pct = int(_sfx_full_h * 0.8)
            $ _sfx_800px = int(500 / _sfx_z)
            $ _sfx_h = max(_sfx_40pct, min(_sfx_800px, _sfx_90pct))
            frame:
                background None
                padding (0, 0)
                xfill True
                yalign 1.0
                if not _sfx_collapsed:
                    ysize _sfx_h
                vbox:
                    spacing 0
                    xfill True
                    if not _sfx_collapsed:
                        fixed:
                            xfill True
                            ysize 4
                            add Solid(_cue_color_bg_overlay)
                    use cue_sfx_library(_is_video, _has_image, _is_dialogue)

screen cue_header_toolbar():
    $ _toggle_on_tt = "SFX triggers are ON (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_ACTIVE) + " to toggle)"
    $ _toggle_off_tt = "SFX triggers are OFF (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_ACTIVE) + " to toggle)"
    $ _copy_tt = "Copy current config (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_COPY_CONTEXT) + ")"
    $ _paste_tt = "Paste config (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_PASTE_CONTEXT) + ")"
    $ _undo_tt = "Undo (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_UNDO) + ")"
    $ _redo_tt = "Redo (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_REDO) + ")"
    $ _pause_tt = "Pause game (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_PAUSE) + ")\nUse to pause on scenes that auto advance."
    hbox:
        xfill True
        spacing 2
        use cue_checkbox(_cue.trigger.active, "SFX Active",
            Function(_cue_toggle_active),
            _toggle_on_tt, _toggle_off_tt,
            _cue_color_active, _cue_color_green_hover, _cue_color_red, _cue_color_red_hover)
        hbox:
            xalign 1.0
            spacing 2
            use cue_icon_btn("copy", Function(_cue.markers.copy_context), _copy_tt, None)
            use cue_icon_btn("paste", Function(_cue.markers.paste_context), _paste_tt, None)
            null width 5

            use cue_icon_btn("undo", Function(_cue.undo.undo), _undo_tt, None, enabled=_cue.undo.can_undo())
            use cue_icon_btn("redo", Function(_cue.undo.redo), _redo_tt, None, enabled=_cue.undo.can_redo())
            null width 5

            $ _backup_tooltip = "Backup config to " + _cue.config_filename
            use cue_icon_btn("floppy-disk", Function(_cue.markers.backup_to_file), _backup_tooltip, None)
            $ _restore_tooltip = "Restore config from " + _cue.config_filename
            use cue_icon_btn("folder-open", Function(_cue.markers.restore_from_file), _restore_tooltip, None)
            null width 5

            use cue_icon_btn(
                "pause",
                Function(renpy.invoke_in_new_context, renpy.pause),
                _pause_tt, None)
            use cue_icon_btn(
                "rotate-right",
                [Function(_cue_reload_presets), Function(_cue_refresh_context), Function(_cue_scan_audio)],
                "Refresh overlay", None)
            null width 5

            $ _settings_bg = _cue_color_active if _cue.is_settings_visible else None
            use cue_icon_btn("gear", Function(_cue_toggle_settings), "Settings", None,
                bg=_settings_bg)
            null width 5
            
            use cue_icon_btn("xmark", Function(_cue_hide_overlay), "Close overlay", None)


###############################################################################
# Speed-change toast — subtle indicator in the top-left corner
###############################################################################

transform cue_speed_toast_fade(duration=CUE_TOAST_DURATION):
    alpha 0.7
    pause (duration - CUE_TOAST_FADE_OFFSET)
    linear CUE_TOAST_FADE_DURATION alpha 0.0

screen cue_speed_toast():
    zorder 10001
    hbox:
        at cue_speed_toast_fade(_cue.speed_toast.toast_duration)
        xalign 0.5
        ypos 14
        spacing 12
        for _sp in _cue.speed_toast.toast_speeds:
            $ _pending = _cue.speed_resolver._pending_speed
            $ _playing = (_cue.speed_resolver._pre_pending_speed
                if _pending is not None
                else _cue.speed_resolver._get_speed_pref(_cue.speed_toast.toast_tag))
            $ _is_pending = _pending is not None and _sp == _pending
            $ _is_active = _sp == _playing
            text _cue_speed_label(_sp):
                style "cue_txt"
                color ("#ffcc00" if _is_pending
                    else "#ffffff" if _is_active
                    else "#cccccc")
                size (28 if _is_active else 26)
                bold _is_active
    # Auto-hide after the fade completes, but only when there is no
    # pending seamless transition.  While a speed change is queued,
    # the toast stays visible so the user can see what speed they
    # selected.  When the transition completes, resolve() calls
    # show() again, which restarts the timer.
    if _cue.speed_resolver._pending_speed is None:
        timer _cue.speed_toast.toast_duration action Function(_cue.speed_toast.clear)


