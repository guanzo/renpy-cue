###############################################################################
# SFX Library Section
# Audio file browser with presets, video presets, and folder tree.
###############################################################################

screen cue_sfx_library(_is_video):
    style_group "cue"

    $ _sidebar_mode = _cue.sfx.library.is_sidebar_mode
    $ _ov_tt = "Sidebar Mode: When enabled, this section floats to the right as a sidebar.\n\n"
    $ _ov_tt = _ov_tt + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_SIDEBAR) + " to toggle sidebar mode.\n"
    $ _ov_tt = _ov_tt + _cue.keybinds.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_LIBRARY)
    if _sidebar_mode:
        $ _ov_tt = _ov_tt + " to toggle sidebar visibility."
    else:
        $ _ov_tt = _ov_tt + " to toggle expansion."

    $ _icons = [{
        "name": ("rectangle-vertical-history-flip" if _sidebar_mode else "rectangle-vertical-history"),
        "action": Function(_cue.sfx.library.toggle_sidebar_mode),
        "tt": _ov_tt
    }]

    $ add_folder_tip = "Add additional folder locations in Settings > Data Folder."

    $ sfx_tt = (
        "Add {} files to\n{}\n\n"
        "Click the + button to add files to the selected \"Target\"\n\n"
        "Prefer adding folders over single files.\n\n{}"
    ).format(", ".join(CUE_AUDIO_EXTS), _cue.paths.audio_dir, add_folder_tip)

    use cue_section_frame(CUE_SFX_LIBRARY_HEADER, tt=sfx_tt, icons=_icons):
        if _cue.sfx.library.tree:
            use cue_target_context()
            if _cue.sfx.library.add_to_pool_warning:
                etext _cue.sfx.library.add_to_pool_warning color _cue_color_error size 11
            null height 1
            use cue_search_bar("_cue.sfx.library.search_query", _cue.sfx.library)
        use cue_sfx_library_content(_is_video)

# Target-context bar: the [1]..[4] chips select where [+] rows dispatch.
# Current target highlighted; unavailable targets grayed (loop never grays).
# Second line shows the resolved target's active pool.
screen cue_target_context():
    style_group "cue"

    $ _target = _cue.markers.resolve_target_context()
    # Tooltips name the rebindable hotkey for each target (Settings > Keybinds).
    $ _tgt_video_tt = "Click the + button to add files to the Video SFX pool.\n"
    $ _tgt_video_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_VIDEO) + " to select."
    $ _tgt_image_tt = "Click the + button to add files to the Image SFX pool.\n"
    $ _tgt_image_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_IMAGE) + " to select."
    $ _tgt_dialogue_tt = "Click the + button to add files to the Dialogue SFX pool.\n"
    $ _tgt_dialogue_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_DIALOGUE) + " to select."
    $ _tgt_loop_tt = "Click the + button to add files to the Loop SFX pool.\n"
    $ _tgt_loop_tt += "Press " + _cue.keybinds.shortcut_label(CUE_KEYMAP_TARGET_LOOP) + " to select."
    hbox:
        spacing 2
        etext "Target:"
        use cue_select_btn("Video", (_target == CueContextType.VIDEO),
            Function(_cue.markers.set_target_context, CueContextType.VIDEO),
            tt=_tgt_video_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.VIDEO))
        use cue_select_btn("Image", (_target == CueContextType.IMAGE),
            Function(_cue.markers.set_target_context, CueContextType.IMAGE),
            tt=_tgt_image_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.IMAGE))
        use cue_select_btn("Dialogue", (_target == CueContextType.DIALOGUE),
            Function(_cue.markers.set_target_context, CueContextType.DIALOGUE),
            tt=_tgt_dialogue_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.DIALOGUE))
        use cue_select_btn("Loop", (_target == CueContextType.LOOP),
            Function(_cue.markers.set_target_context, CueContextType.LOOP),
            tt=_tgt_loop_tt,
            sensitive=_cue.markers.target_is_available(CueContextType.LOOP))
    hbox:
        spacing 2
        etext "Pool:"
        etext _cue.markers.target_active_label()


screen cue_sfx_library_content(_is_video):
    style_group "cue"

    $ _q = _cue.sfx.library.search_query
    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _unplayable = _cue.sfx.unplayable_files()
    viewport:
        xfill True
        mousewheel True
        scrollbars "vertical"
        vscrollbar_unscrollable "hide"
        use cue_tree_rows(_cue.sfx.library.content_rows(
            _q,
            _cue.presets.list_presets(),
            _cue.presets.list_video_presets(),
            _cue.intensity.list_igroups(),
            _is_video,
            _tgt_ok,
            _unplayable))


