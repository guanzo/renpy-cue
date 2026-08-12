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
    key "K_F5" action Function(renpy.quit, relaunch=True)
    key "shift_K_1" action Function(_cue.markers.copy_context)
    key "shift_K_2" action Function(_cue.markers.paste_context)
    key "shift_K_q" action Function(_cue.undo.undo)
    key "shift_K_w" action Function(_cue.undo.redo)
    key "K_m" action Function(_cue.speed_resolver.cycle_speed, 1)
    key "K_n" action Function(_cue.speed_resolver.cycle_speed, -1)
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


    # --- Sequence button popup (edit actions) ---
    popper target "seq_btn" placement "top":
        hbox:
            spacing 2
            use cue_txt_button("❮", Function(_cue_seq_move_left), tt="Move left")
            use cue_txt_button("✕", Function(_cue_seq_delete), tt="Delete")
            use cue_txt_button("❯", Function(_cue_seq_move_right), tt="Move right")

    # --- Tooltip overlay (after poppers so it draws above them) ---
    if _tt:
        add CueTooltip(_tt)

    # --- Marker timeline tooltip (rendered last so it's always on top) ---
    add CueMarkerTooltipOverlay()


screen cue_popper_anchor(name, hover_fn):
    button:
        style "empty"
        padding (0, 0)
        action NullAction()
        hovered [Function(_cue_store_focus_rect, name), hover_fn]
        background None
        transclude


# =============================================================================
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen cue_overlay_content():
    vbox:
        spacing 4

        # --- Top bar: active checkbox + copy + paste + dump + restore + refresh + close ---
        hbox:
            spacing 2
            use cue_checkbox(_cue.trigger.active, "SFX Active",
                Function(_cue_toggle_active),
                "SFX triggers are ON (F4 to toggle)",
                "SFX triggers are OFF (F4 to toggle)",
                _cue_color_active, _cue_color_green_hover, _cue_color_red, _cue_color_red_hover)
            null width 5
            use cue_icon_btn("📋", Function(_cue.markers.copy_context), "Copy current config (Shift + 1)", None)
            use cue_icon_btn("📄", Function(_cue.markers.paste_context), "Paste config (Shift + 2)", None)
            null width 5
            use cue_icon_btn("↩", Function(_cue.undo.undo), "Undo (Shift + Q)", None, enabled=_cue.undo.can_undo())
            use cue_icon_btn("↪", Function(_cue.undo.redo), "Redo (Shift + W)", None, enabled=_cue.undo.can_redo())
            null width 5
            $ _backup_tooltip = "Backup config to " + _cue.config_filename
            use cue_icon_btn("💾", Function(_cue.markers.backup_to_file), _backup_tooltip, None)
            $ _restore_tooltip = "Restore config from " + _cue.config_filename
            use cue_icon_btn("📂", Function(_cue.markers.restore_from_file), _restore_tooltip, None)
            null width 5
            use cue_icon_btn("⏸", Function(renpy.invoke_in_new_context, renpy.pause), "Pause game (F3)", None)
            use cue_icon_btn("⟳", [Function(_cue_reload_presets), Function(_cue_refresh_context), Function(_cue_scan_audio)], "Refresh overlay", None)
            use cue_icon_btn("✕", Function(_cue_hide_overlay), "Close overlay", None)

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

        # --- Dialogue UI ---
        $ _is_dialogue = bool(_cue.current_dialogue)
        if _is_dialogue:
            $ _dlg_key = _cue_create_dlg_key((_cue.current_file, _cue.current_dialogue))
            use cue_context_section("Dialogue SFX", _cue.markers.dialogue, _dlg_key,
                "Dialogue: " + _cue.current_dialogue, "dialogue", "D",
                "SFX plays when this line of dialogue is displayed.")

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
                use cue_select_btn("Slowest", (_freq == CueLoopFrequency.SLOWEST), Function(_cue.markers.loop.set_frequency, CueLoopFrequency.SLOWEST), tt="~6.3s between plays")
                use cue_select_btn("Slow", (_freq == CueLoopFrequency.SLOW), Function(_cue.markers.loop.set_frequency, CueLoopFrequency.SLOW), tt="~3.8s between plays")
                use cue_select_btn("Normal", (_freq == CueLoopFrequency.NORMAL), Function(_cue.markers.loop.set_frequency, CueLoopFrequency.NORMAL), tt="~2.1s between plays")
                use cue_select_btn("Fast", (_freq == CueLoopFrequency.FAST), Function(_cue.markers.loop.set_frequency, CueLoopFrequency.FAST), tt="~0.6s between plays")
                use cue_select_btn("Fastest", (_freq == CueLoopFrequency.FASTEST), Function(_cue.markers.loop.set_frequency, CueLoopFrequency.FASTEST), tt="~0.2s between plays")
                use cue_v_divider()
                $ _is_exclusive = _cue._pool_ui.get("exclusive", False)
                use cue_checkbox(_is_exclusive, "Exclusive playback",
                    Function(_cue.markers.loop.set_exclusive, not _is_exclusive),
                    "Prevents other loop SFX from playing at the same time")

        # Audio file browser
        use cue_sfx_library(_is_video, _has_image, _is_dialogue)


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


