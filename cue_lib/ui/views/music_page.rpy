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
                        Function(_cue_consume_return, _cue.music.create_scene_trigger))

        $ music_lib_tt = (
            "My Music: add {} files to \n{}\n\n"
            "Game Music is found with heuristics, it may not find all music.\n\n"
            "Add additional folder locations in Settings > Data Folder.").format(
                ", ".join(CUE_AUDIO_EXTS), _cue.paths.music_dir)
        
        use cue_section_frame("Music Library", tt=music_lib_tt):
            if _cue.music.library.user_tree or _cue.music.library.game_tree:
                use cue_search_bar("_cue.music.library.search_query", _cue.music.library)
    
            viewport:
                xfill True
                yfill True
                mousewheel True
                scrollbars "vertical"
                vscrollbar_unscrollable "hide"
                $pass # https://github.com/renpy/renpy/issues/3474
                
                use cue_tree_rows(_cue.music.library.content_rows(
                    _cue.music.library.search_query,
                    _cue.presets.music.list(),
                    _cue.current_file))

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
                                        $ _child_path = _cue.music.library.ref_display_path(_child)
                                        $ _child_display = _child_path[len(_song_path):]
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
