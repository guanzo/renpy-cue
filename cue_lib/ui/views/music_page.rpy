###############################################################################
# Music Page
###############################################################################
screen grow_and_scroll(ymin=None, ymax=None, id=None):
    style_group "cue"

    $ viewport_id = "grow_scroll_" + (id or str(renpy.random.random()))

    frame:
        background None
        padding (0, 0)
        xfill True  # Fixed or minimum width
        
        side "c r":
            # Set the maximum height limit before scrolling kicks in
            if ymax is not None: 
                ymaximum ymax
            if ymin is not None: 
                yminimum ymin

            viewport id viewport_id:
                mousewheel True
                yfill False
                
                transclude

            # Vertical scrollbar that hides if content is short
            vbar value YScrollValue(viewport_id):
                unscrollable "hide"
                style "cue_vscrollbar"
                    

screen cue_music_page():
    style_group "cue"

    vbox:
        spacing 5
        $ music_tt = (
            "Default music triggers must be discovered by playing through the replay.\n\n"
            "Click a trigger to select it, then click the + button "
            "in My/Game Music to add a song to the trigger. "
            "With no trigger selected, + creates a new one for the current scene.\n\n"
            "If you add multiple songs, one will be picked at random.")
        use cue_section_frame("Music Triggers", tt=music_tt):
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                vbox:
                    spacing 5
                    hbox:
                        spacing 8
                        box_wrap True
                        box_wrap_spacing 3
                        etext "Now Playing:"
                        hbox:
                            yalign 0.5
                            use cue_icon_btn(
                                ("play" if _cue.music.is_paused else "pause"),
                                Function(_cue.music.toggle_pause),
                                enabled=(_cue.music.now_playing() is not None))
                        etext (_cue.music.now_playing() or "(None)") color _cue_color_text_accent
                    hbox:
                        spacing 8
                        box_wrap True
                        box_wrap_spacing 3
                        etext "Current Scene:"
                        etext (_cue.current_file or "(None)") color _cue_color_text_accent
                    
                    $ triggers = _cue.music.triggers()
                    if triggers:
                        use trigger_list(triggers)
                    
                    if not renpy.store._in_replay:
                        null height 5
                        $ _warn_icon = _cue.icons.displayable_for("triangle-exclamation", _cue_color_warn)
                        hbox:
                            spacing 5
                            add _warn_icon yalign 0.5
                            etext ("Customizing Music is only fully supported in replays, "
                                    "it may not work properly in game.") color _cue_color_warn
                    
                    null height 5
                    use cue_txt_button(
                        "+ Play music at current scene",
                        Function(_cue.music.create_scene_trigger))

        $ music_lib_tt = (
            "My Music: add {} files to \n{}\n\n"
            "Game Music is found with heuristics, it may not find all music.").format(
                ", ".join(CUE_AUDIO_EXTS), _cue.paths.music_dir)
        
        use cue_section_frame("Music Library", tt=music_lib_tt):
            if _cue.music.user_music.tree or _cue.music.game_music.tree:
                use cue_search_bar("_cue.music.library.search_query", _cue.music.library)
    
            viewport:
                xfill True
                yfill True
                mousewheel True
                scrollbars "vertical"
                vscrollbar_unscrollable "hide"
                vbox:
                    spacing 5
                    # "Recently Used/" at the top of the music content.  Rows
                    # preview/add the same display paths as the tree; search
                    # filters them on that display path too, and force-expands
                    # the list read-time (it shows whenever `_searching`).
                    $ _mq = _cue.music.library.search_query
                    $ _msearching = bool(_mq.strip())

                    $ _mrecent = _cue.music._recent
                    $ _mrecent_entries = _mrecent.entries() if _mrecent is not None else []
                    if _msearching:
                        $ _mrecent_entries = [e for e in _mrecent_entries
                            if _cue_query_matches(_cue.music.library.ref_display_path(e["ref"]), _mq)]
                    if _mrecent is not None and (not _msearching or _mrecent_entries):
                        hbox:
                            spacing 2
                            use cue_txt_button("Recently Used/", Function(_mrecent.toggle))
                        if _mrecent.expanded or _msearching:
                            use cue_music_recent_list(_mrecent_entries)

                    # "Music Presets/" -- saved trigger song lists.  Names join
                    # the search flow (filtered like the SFX preset sections).
                    $ _mpreset_names = _cue.music.list_presets()
                    if _msearching:
                        $ _mpreset_names = [n for n in _mpreset_names
                            if _cue_query_matches(n, _mq)]
                    if not _msearching or _mpreset_names:
                        hbox:
                            spacing 2
                            use cue_txt_button("Music Presets/",
                                Function(_cue.music.toggle_presets_expand))
                        if _cue.music.presets_expanded:
                            if not _mpreset_names:
                                etext "No music presets yet. Save a trigger's song list to fill this." style "cue_help"
                            use cue_music_presets_list(_mpreset_names)

                    # Per-source empty/error states -- one source can be empty
                    # while the other has files.
                    if not _cue.music.user_music.tree:
                        if _cue.music.user_music.scan_error:
                            etext _cue.music.user_music.scan_error color _cue_color_error
                        etext "No music found in: {}".format(_cue.paths.music_dir)
                        etext ("Add {} files there "
                            "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS))
                        use cue_open_in_explorer_btn(_cue.paths.music_dir, "Open Music folder")
                    if not _cue.music.game_music.tree:
                        if _cue.music.game_music.scan_error:
                            etext _cue.music.game_music.scan_error color _cue_color_error
                        etext "No music found in game directory."
                    $ _m_no_results = (_msearching and not _mrecent_entries
                        and not _mpreset_names
                        and not _cue.music.library.visible_tree)
                    if _cue.music.user_music.tree or _cue.music.game_music.tree:
                        if _m_no_results:
                            etext 'No files found for "{}".'.format(_mq)
                        else:
                            use cue_music_tree()

screen trigger_list(triggers):
    style_group "cue"

    default _hovered_key = None
    for trigger in triggers:
        null height 2
        button:
            style "empty"
            background (_cue_color_bg_input if trigger["selected"] else _cue_color_bg_panel)
            hover_background _cue_color_bg_input
            action Function(_cue.music.select_trigger, trigger["key"])
            hovered SetLocalVariable("_hovered_key", trigger["key"])
            unhovered SetLocalVariable("_hovered_key", None)
            padding (4, 4)
            xfill True
            vbox:
                spacing 3
                hbox:
                    xfill True
                    hbox:
                        use cue_icon_btn(
                            ("rotate-right" if trigger["is_default"] else "trash-can"),
                            Function(_cue.music.delete_trigger, trigger["key"]),
                            ("Reset to default" if trigger["is_default"] else "Delete trigger"))
                        etext trigger["label"] color _cue_color_text_accent
                    if trigger["songs"] and (_hovered_key == trigger["key"] or trigger["selected"]):
                        hbox:
                            xalign 1.0
                            use cue_icon(
                                "floppy-disk",
                                Function(_cue.dialogs.music_preset.open, trigger["key"]),
                                "Save songs as a preset",
                                on_hover=SetLocalVariable("_hovered_key", trigger["key"]),
                                on_unhover=SetLocalVariable("_hovered_key", None))
                if trigger["is_default"] and trigger["default_paths"]:
                    hbox:
                        spacing 6
                        use cue_icon_btn(
                            ("volume" if trigger["default_enabled"] else "volume-xmark"),
                            Function(_cue.music.toggle_default, trigger["key"]),
                            "Toggle default songs")
                        if trigger["default_enabled"]:
                            etext "Default music:" style "cue_help"
                        else:
                            etext "Default music: (Disabled)" style "cue_help" color _cue_color_text_muted
                    for _dpath in trigger["default_paths"]:
                        $ _dpath_display = _cue.music.default_display_path(_dpath)
                        hbox:
                            xoffset 22
                            if trigger["default_enabled"]:
                                etext _dpath_display
                            else:
                                etext _dpath_display color _cue_color_text_muted
                if trigger["songs"]:
                    for _idx, _song in enumerate(trigger["songs"]):
                        if _song.endswith("/"):
                            # Folder ref: expandable, count + detachable children.
                            # Display under the synthetic My/Game Music root, not
                            # the raw data path ("My Music/x/" not "music/x/").
                            $ _song_path = _cue.music.library.ref_display_path(_song)
                            $ _folder_expanded = _cue.music.expanded_file_refs.get(_song, False)
                            $ _folder_files = _cue.music.resolve_music_files([_song])
                            hbox:
                                spacing 6
                                use cue_icon_btn(
                                    "xmark",
                                    Function(
                                        _cue.music.remove_song_from_trigger,
                                        trigger["key"],
                                        _song),
                                    "Remove folder from trigger")
                                use cue_txt_button(
                                    _song_path,
                                    Function(_cue.music.toggle_file_ref_expand, _song))
                                etext ("({} files)".format(len(_folder_files))) style "cue_help"
                            if _folder_expanded:
                                for _child in _folder_files:
                                    hbox:
                                        spacing 6
                                        etext _cue_indent
                                        use cue_icon_btn(
                                            "xmark",
                                            Function(
                                                _cue.music.remove_song_from_folder_ref,
                                                trigger["key"],
                                                _idx,
                                                _child),
                                            "Remove file from the folder")
                                        $ _child_display = _cue.music.library.ref_display_path(_child)[len(_song_path):]
                                        etext _child_display
                        else:
                            # Show the full path under the synthetic My/Game
                            # Music root, matching the folder rows above.
                            $ _song_path = _cue.music.library.ref_display_path(_song)
                            hbox:
                                spacing 6
                                use cue_icon_btn(
                                    "xmark",
                                    Function(
                                        _cue.music.remove_song_from_trigger,
                                        trigger["key"],
                                        _song),
                                    "Remove song from trigger")
                                etext _song_path
                elif not trigger["is_default"]:
                    etext "No music added."

# Combined My/Game Music tree. One shared search bar filters both sources; the
# combined manager's visible_tree holds the merged display rows.  The search
# "no files found" message lives in cue_music_page, which also accounts for
# preset + recently-used matches.
screen cue_music_tree():
    style_group "cue"

    use cue_tree_rows(_cue.music.library.tree_rows(_cue.current_file))

# Recently Used rows, shown when the Recently Used folder is expanded.
# entries: filtered recent-entry dicts {type, ref}, most-recent-first, refs
# still tagged u:/g:.  Display paths come from ref_display_path, the inverse
# of the tree's add dispatch, so each row previews/adds the same path the
# tree would.  Folders carry only the add button, mirroring the file tree.
screen cue_music_recent_list(entries):
    style_group "cue"

    $ _m_sel_label = _cue.music.selected_trigger_label()
    $ _m_add_target = _m_sel_label if _m_sel_label else "a new trigger for the current scene"
    $ _m_add_tt = "Add song to " + _m_add_target
    $ _m_add_folder_tt = "Add folder to " + _m_add_target
    $ _m_add_enabled = (_cue.music.selected_key is not None
                        or bool(_cue.current_file))
    if not entries:
        etext "Songs you add to a trigger show up here." style "cue_help"
    for _re in entries:
        $ _re_path = _cue.music.library.ref_display_path(_re["ref"])
        hbox:
            spacing 2
            etext _cue_indent  # indent under Recently Used/
            if _re["type"] == "folder":
                use cue_icon_btn(
                    "plus",
                    Function(_cue.music.library.add_folder_to_trigger,
                             _re_path, record=False),
                    _m_add_folder_tt,
                    enabled=_m_add_enabled)
                etext _re_path color _cue_color_text_accent
            else:
                use cue_icon_btn(
                    "plus",
                    Function(_cue.music.library.add_song_to_trigger,
                             _re_path, record=False),
                    _m_add_tt,
                    enabled=_m_add_enabled)
                use cue_icon_btn(
                    "play",
                    Function(_cue.music.library.preview, _re_path),
                    "Play song")
                null width 2
                etext _re_path color _cue_color_text_accent


# Music preset rows, shown when the Music Presets/ folder is expanded.
# name_filter: preset names to show (None = all); set by the search flow.
# Apply: click replaces the selected trigger's songs; shift+click applies to
# the current scene (new trigger if the scene has none).  Disabled without a
# selected trigger, same as the music tree "+" buttons.
screen cue_music_presets_list(name_filter=None):
    style_group "cue"

    $ _names = name_filter if name_filter is not None else _cue.music.list_presets()
    $ _apply_tt = ("Click: Replace selected trigger's songs\n"
                   "Shift+Click: Apply to current scene (new trigger if none)")
    $ _apply_enabled = _cue.music.selected_key is not None
    for _pname in _names:
        $ _pdata = _cue.music.get_preset(_pname)
        $ _p_expanded = _cue.music.expanded_presets.get(_pname, False)
        $ _p_files = _cue.music.preset_display_files(_pdata) if _pdata else []
        hbox:
            spacing 2
            etext _cue_indent  # indent under Music Presets/
            use cue_icon_btn(
                "xmark",
                Function(_cue_confirm_delete_music_preset, _pname),
                "Delete preset" + CUE_HELP_SHIFT_SKIP_DELETE)
            use cue_icon_btn(
                "plus",
                Function(_cue.music.apply_preset, _pname),
                _apply_tt,
                enabled=_apply_enabled)
            use cue_icon_btn(
                "play",
                Function(_cue_preview_music_preset, _pname),
                "Play random song from preset")
            use cue_txt_button(_pname, Function(_cue.music.toggle_preset_expand, _pname))

        if _p_expanded:
            for _child in _p_files:
                hbox:
                    spacing 2
                    etext _cue_indent
                    use cue_icon_btn(
                        "xmark",
                        Function(_cue.music.preset_remove_file, _pname, _child),
                        "Remove file from preset")
                    use cue_icon_btn(
                        "play",
                        Function(_cue.music.library.preview, _child),
                        "Preview song")
                    null width 1
                    etext _child color _cue_color_text_accent size 11
