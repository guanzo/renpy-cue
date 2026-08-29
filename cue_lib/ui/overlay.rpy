###############################################################################
# Overlay Screen
###############################################################################


###############################################################################
# Runtime Driver — invisible always-on screen that drives the tick engine,
# catches global hotkeys, and runs background polls.
###############################################################################

# Put timers here, because for some stupid reason they occupy space in the layout.
screen cue_runtime_driver():
    zorder 10000
    use cue_runtime_keybinds()
    use cue_runtime_timers()


screen cue_runtime_keybinds():
    # Hardcoded fallback (not rebindable): some games claim backtick for their
    # own console, so Shift+Alt+E is a guaranteed-free alternative.
    key "alt_shift_K_e" action Function(_cue.overlay.toggle)
    key CUE_KEYMAP_TOGGLE_OVERLAY action Function(_cue.overlay.toggle)
    key CUE_KEYMAP_COPY_CONTEXT action Function(_cue.markers.copy_context)
    key CUE_KEYMAP_PASTE_CONTEXT action Function(_cue.markers.paste_context)
    key CUE_KEYMAP_TOGGLE_SFX_ACTIVE action Function(_cue.trigger.toggle_active)
    key CUE_KEYMAP_PAUSE action Function(renpy.invoke_in_new_context, renpy.pause)
    key CUE_KEYMAP_UNDO action Function(_cue.undo.undo)
    key CUE_KEYMAP_REDO action Function(_cue.undo.redo)
    key CUE_KEYMAP_SPEED_UP action Function(_cue.speed_resolver.cycle_speed, 1)
    key CUE_KEYMAP_SPEED_DOWN action Function(_cue.speed_resolver.cycle_speed, -1)
    key CUE_KEYMAP_TOGGLE_SFX_LIBRARY action Function(_cue.overlay.toggle_section, CUE_SFX_LIBRARY_HEADER)

    if CUE_DEBUG:
        key CUE_KEYMAP_QUIT_RELAUNCH action Function(renpy.quit, relaunch=True)

    if _cue.overlay.is_visible:
        key CUE_KEYMAP_TOGGLE_SFX_SIDEBAR action Function(_cue.sfx.library.toggle_sidebar_mode)
        key CUE_KEYMAP_PAGE_SFX action Function(_cue.overlay.set_page, CuePage.SFX)
        key CUE_KEYMAP_PAGE_MUSIC action Function(_cue.overlay.set_page, CuePage.MUSIC)
        key CUE_KEYMAP_PAGE_IMPORT action Function(_cue.overlay.set_page, CuePage.IMPORT)
        key CUE_KEYMAP_PAGE_SETTINGS action Function(_cue.overlay.set_page, CuePage.SETTINGS)

        if _cue.overlay.active_page == CuePage.SFX:
            key CUE_KEYMAP_TARGET_VIDEO action Function(_cue.markers.set_target_context, CueContextType.VIDEO)
            key CUE_KEYMAP_TARGET_IMAGE action Function(_cue.markers.set_target_context, CueContextType.IMAGE)
            key CUE_KEYMAP_TARGET_DIALOGUE action Function(_cue.markers.set_target_context, CueContextType.DIALOGUE)
            key CUE_KEYMAP_TARGET_LOOP action Function(_cue.markers.set_target_context, CueContextType.LOOP)


screen cue_runtime_timers():
    $ _is_busy = (
        _cue.backups.is_busy
        or _cue.exporter.is_busy
        or _cue.importer.is_importing
        or _cue.url_importer.is_downloading
        or _cue.video_editor.job_queue.jobs)

    # One restart poll for all background ops.  Fires only while one is live
    # and the overlay is up, so progress text re-renders and the timer drops
    # out once the op finishes.
    if _cue.overlay.is_visible and _is_busy:
        timer 0.25 repeat True action Function(renpy.restart_interaction, _update_screens=False)

    $ _sfx_dl = _cue.sfx.library.sfx_pack
    if _cue.overlay.is_visible and _sfx_dl.state in ("downloading", "done"):
        timer 0.25 repeat True action [
            Function(_sfx_dl.poll_sfx_pack),
            Function(renpy.restart_interaction, _update_screens=False),
        ]

    if _cue.overlay.active_page == CuePage.IMPORT:
        timer 2.0 repeat True action Function(_cue.importer.scan)
    elif _cue.overlay.active_page == CuePage.SETTINGS:
        timer 0.5 repeat True action Function(_cue.backups.poll, _update_screens=False)

    timer 0.02 repeat True action Function(_cue_tick_trigger, _update_screens=False)

###############################################################################
# Main Overlay — the sidebar frame.
###############################################################################

screen cue_overlay():
    style_group "cue"

    zorder 9999
    # Modal only while a dialog is up so the dialog's input gets the keys
    # instead of the game's own keymap shortcuts.
    modal (_cue.dialogs.active_dialog is not None)

    button:
        style "empty"
        action NullAction()
        xalign 0.0
        yalign 0.0
        xsize _cue_scale_ui(_cue_overlay_panel_width)
        ysize renpy.config.screen_height
        padding (_cue_scale_ui(4), _cue_scale_ui(4))
        background None
        hover_background None
        frame:
            background _cue_color_bg_overlay
            yfill True
            use cue_overlay_content()

    # --- SFX sidebar: pinned to the panel's right edge. Folded in (not a
    # separate screen) so the overlay toggle hides it together with the panel. ---
    use cue_sfx_sidebar()

    use cue_dialogs()

    # --- Floating tooltip near mouse (auto-sizes to fit text) ---
    $ _tt = GetTooltip()

    # Place popper targets here.

    # --- Tooltip overlay (after poppers so it draws above them) ---
    if _tt:
        add CueTooltip(_tt)

    # --- Marker timeline tooltip ---
    add CueVideoMarkerTooltip()

# =============================================================================
# SUB-SCREEN: Sidebar content (shared between normal and fullscreen frames)
# =============================================================================

screen cue_overlay_content():
    style_group "cue"

    # SFX context flags -- same derivation as cue_sfx_page. Needed by the
    # floating SFX library below (sidebar mode), which doesn't run sfx_page.
    $ _is_video = _cue.top_layer_type == 'movie'

    fixed:
        xfill True
        yfill True
        vbox:
            spacing 5

            # --- Top bar: active checkbox + copy + paste + undo/redo + refresh + close ---
            use cue_header_toolbar()

            # While an import is active the editor edits the import, not live
            # data; the banner stays clickable (Merge/Deactivate) because it's
            # above the page.
            if _cue.importer.is_active:
                use cue_edit_banner()

            # --- Active page replaces all content below the toolbar ---
            if _cue.overlay.active_page == CuePage.SFX:
                use cue_sfx_page()
            elif _cue.overlay.active_page == CuePage.MUSIC:
                use cue_music_page()
            elif _cue.overlay.active_page == CuePage.IMPORT:
                use cue_import_export_page()
            else:
                use cue_settings_page()

screen cue_header_toolbar():
    style_group "cue"

    $ _sfx_toggle_keys = _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_ACTIVE)
    $ _sfx_toggle_on_tt = "SFX triggers are ON ({} to toggle)".format(_sfx_toggle_keys)
    $ _sfx_toggle_off_tt = "SFX triggers are OFF ({} to toggle)".format(_sfx_toggle_keys)
    $ _copy_tt = "Copy current scene markers (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_COPY_CONTEXT) + ")"
    $ _paste_tt = "Paste markers (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_PASTE_CONTEXT) + ")"
    $ _undo_tt = "Undo (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_UNDO) + ")"
    $ _redo_tt = "Redo (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_REDO) + ")"
    $ _pause_tt = "Pause game (" + _cue.keybinds.shortcut_label(CUE_KEYMAP_PAUSE)
    $ _pause_tt += ")\nUse to pause on scenes that auto advance."

    hbox:
        xfill True
        spacing 2
        hbox:
            spacing 5

            $ _sfx_bg = _cue_color_active if _cue.overlay.active_page == CuePage.SFX else None
            use cue_icon_btn("sliders", Function(_cue.overlay.set_page, CuePage.SFX), "Editor",
                bg=_sfx_bg)
            $ _music_bg = _cue_color_active if _cue.overlay.active_page == CuePage.MUSIC else None
            use cue_icon_btn("music", Function(_cue.overlay.set_page, CuePage.MUSIC), "Music",
                bg=_music_bg)
            $ _import_bg = _cue_color_active if _cue.overlay.active_page == CuePage.IMPORT else None
            use cue_icon_btn("file-zipper", Function(_cue.overlay.set_page, CuePage.IMPORT), "Import / Export",
                bg=_import_bg)
            $ _settings_bg = _cue_color_active if _cue.overlay.active_page == CuePage.SETTINGS else None
            use cue_icon_btn("gear", Function(_cue.overlay.set_page, CuePage.SETTINGS), "Settings",
                bg=_settings_bg)

            # Sidebar visibility toggle: same collapse flag as Shift+S, shown
            # only while sidebar mode is on.  The sidebar-flip icon may not be
            # registered yet -- cue_icon_btn falls back to text.
            if _cue.sfx.library.is_sidebar_mode:
                use cue_v_divider()
                $ _sidebar_open = not _cue.overlay.collapsed_sections.get(CUE_SFX_LIBRARY_HEADER, False)
                $ _sidebar_bg = _cue_color_active if _sidebar_open else None
                use cue_icon_btn(
                    "sidebar-flip",
                    Function(_cue.overlay.toggle_section, CUE_SFX_LIBRARY_HEADER),
                    "Toggle the SFX sidebar visibility ({}).".format(
                        _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_LIBRARY)),
                    bg=_sidebar_bg)


        hbox:
            xalign 1.0
            spacing 2
            
            $ _sfx_icon = "volume" if _cue.trigger.active else "volume-xmark"
            $ _sfx_tt = _sfx_toggle_on_tt if _cue.trigger.active else _sfx_toggle_off_tt
            $ _sfx_bg = _cue_color_active if _cue.trigger.active else _cue_color_dark_yellow
            use cue_icon_btn(_sfx_icon, Function(_cue.trigger.toggle_active), _sfx_tt, bg=_sfx_bg)

            null width 5
                   
            use cue_icon_btn("copy", Function(_cue.markers.copy_context), _copy_tt)
            use cue_icon_btn("paste", Function(_cue.markers.paste_context), _paste_tt)
            null width 5

            use cue_icon_btn("undo", Function(_cue.undo.undo), _undo_tt, enabled=_cue.undo.can_undo())
            use cue_icon_btn("redo", Function(_cue.undo.redo), _redo_tt, enabled=_cue.undo.can_redo())
            null width 5

            use cue_icon_btn(
                "pause",
                Function(renpy.invoke_in_new_context, renpy.pause),
                _pause_tt)
            use cue_icon_btn(
                "rotate-right",
                Function(_cue_full_reload),
                "Refresh")
            null width 5

            
            use cue_icon_btn("xmark", Function(_cue.overlay.hide), "Close overlay")

# --- Active dialog: folded in gated on the live _cue.dialogs.active_dialog
# so the overlay toggle hides it without losing its state. Dialog screens are
# top-level on their own only when shown directly; the use inlines them. ---
screen cue_dialogs():
    $ _dlg = _cue.dialogs.active_dialog
    if isinstance(_dlg, CuePoolPresetDialog):
        use cue_save_preset_dialog()
    elif isinstance(_dlg, CueMusicPresetDialog):
        use cue_save_music_preset_dialog()
    elif isinstance(_dlg, CueVideoPresetDialog):
        use cue_save_video_preset_dialog()
    elif isinstance(_dlg, CueIntensityGroupDialog):
        use cue_new_igroup_dialog()
    elif isinstance(_dlg, CueConfirmDialog):
        use cue_confirm_dialog()
    elif isinstance(_dlg, CueMergeDialog):
        use cue_merge_dialog()
    elif isinstance(_dlg, CueMarkerRepeater):
        use cue_repeat_markers_dialog()

# =============================================================================
# SUB-SCREEN: SFX sidebar -- full-height column pinned to the overlay panel's
# right edge.  Renders only while sidebar mode is on and the SFX Library
# section is expanded; otherwise the screen stays mounted but empty.
# =============================================================================

screen cue_sfx_sidebar():
    style_group "cue"

    # Same video-context derivation as cue_overlay_content.
    $ _is_video = _cue.top_layer_type == 'movie'

    if _cue.sfx.library.is_sidebar_mode and not _cue.overlay.collapsed_sections.get(CUE_SFX_LIBRARY_HEADER, False):
        button:
            style "empty"
            action NullAction()
            padding (0, _cue_scale_ui(4))
            yalign 0.0
            xpos _cue_scale_ui(_cue_overlay_panel_width)
            xsize _cue_scale_ui(_cue.sfx.library.sidebar_width)
            ysize renpy.config.screen_height
            background None
            hover_background None
            frame:
                background _cue_color_bg_overlay
                yfill True
                use cue_sfx_library(_is_video)

            # Resize handle: drag the game-facing right edge to change width.
            # Custom displayable -- the screen `dragged` callback only fires on
            # drop with a 2-arg signature, so live resize needs raw mouse events.
            # Sized to the padded content rect so it hugs the colored frame.
            add CueSidebarResizeHandle.get_handle() at Transform(
                xalign=1.0, xsize=_cue_scale_ui(10),
                ysize=renpy.config.screen_height - _cue_scale_ui(8))

###############################################################################
# Speed-change toast — subtle indicator in the top-left corner
###############################################################################

transform cue_speed_toast_fade(duration=CUE_TOAST_DURATION):
    alpha 0.7
    pause (duration - CUE_TOAST_FADE_OFFSET)
    linear CUE_TOAST_FADE_DURATION alpha 0.0

screen cue_speed_toast():
    style_group "cue"

    zorder 10001
    hbox:
        at cue_speed_toast_fade(_cue.speed_toast.toast_duration)
        xalign 0.5
        ypos _cue_scale_ui(14)
        spacing _cue_scale_ui(12)
        for _sp in _cue.speed_toast.toast_speeds:
            $ _pending = _cue.speed_resolver._pending_speed
            $ _playing = (_cue.speed_resolver._pre_pending_speed
                if _pending is not None
                else _cue.speed_resolver._get_speed_pref(_cue.speed_toast.toast_tag))
            $ _is_pending = _pending is not None and _sp == _pending
            $ _is_active = _sp == _playing
            etext _cue_speed_label(_sp):
                color ("#ffcc00" if _is_pending
                    else "#ffffff" if _is_active
                    else "#cccccc")
                size (_cue_scale_ui(28) if _is_active else _cue_scale_ui(26))
                bold _is_active
    # Auto-hide after the fade completes, but only when there is no
    # pending seamless transition.  While a speed change is queued,
    # the toast stays visible so the user can see what speed they
    # selected.  When the transition completes, resolve() calls
    # show() again, which restarts the timer.
    if _cue.speed_resolver._pending_speed is None:
        timer _cue.speed_toast.toast_duration action Function(_cue.speed_toast.clear)


