###############################################################################
# Music Page
###############################################################################
screen grow_and_scroll(ymin=None, ymax=None, id=None):
    $ viewport_id = "grow_scroll_" + (id or str(renpy.random.random()))

    frame:
        background None
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
                style "cue_vbar_scroll"
                    

screen cue_music_page():
    vbox:
        spacing 5
        $ music_tt = (
            "Click a trigger to select it, then click the + button "
            "in My/Game Music to add a song to the trigger.\n"
            "If you add multiple songs, one will be picked at random.\n\n"
            "Default music triggers must be discovered by playing through the replay.")
        use cue_section_frame("Music", tt=music_tt):
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                vbox:
                    spacing 5
                    hbox:
                        spacing 8
                        text "Now Playing:" style "cue_txt"
                        text (_cue.music.now_playing() or "(None)") style "cue_txt" color _cue_color_text_accent
                    hbox:
                        spacing 8
                        text "Current Scene:" style "cue_txt"
                        text (_cue.current_file or "(None)") style "cue_txt" color _cue_color_text_accent
                    
                    null height 5

                    $ triggers = _cue.music.triggers()
                   
                    if not triggers:
                        text "No music triggers for this replay yet." style "cue_txt"
                    else:
                        text "Music Triggers:" style "cue_txt"
                        use trigger_list(triggers)
                    
                    if not renpy.store._in_replay:
                        null height 4
                        $ _warn_icon = _cue.icons.displayable_for("triangle-exclamation", _cue_color_warn)
                        hbox:
                            spacing 6
                            add _warn_icon yalign 0.5
                            text ("Customizing Music is only fully supported in replays, "
                                    "it may not work properly in game.") style "cue_txt" color _cue_color_warn
                    
                    null height 4
                    use cue_txt_button("+ Play music starting at current scene", Function(_cue.music.add_custom_trigger))

        $ my_music_tt = "Add music files to\n{}".format(_cue.paths.music_dir)
        use cue_section_frame("My Music", tt=my_music_tt):
            if _cue.music.user_music.tree:
                use cue_search_bar("_cue.music.user_music.search_query", _cue.music.user_music)
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                vbox:
                    spacing 5
                    if not _cue.music.user_music.tree:
                        if _cue.music.user_music.scan_error:
                            text "[_cue.music.user_music.scan_error]" style "cue_txt" color _cue_color_error
                        text "No music found in: [_cue.paths.music_dir]" style "cue_txt"
                        text ("Add {} files there "
                            "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS)) style "cue_txt"
                    else:
                        use cue_music_tree()

        $ game_music_tt = "Game music is found with heuristics, this list may not be accurate."
        use cue_section_frame("Game Music", tt=game_music_tt):
            if _cue.music.game_music.tree:
                use cue_search_bar("_cue.music.game_music.search_query", _cue.music.game_music)
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                vbox:
                    spacing 5
                    if not _cue.music.game_music.tree:
                        if _cue.music.game_music.scan_error:
                            text "[_cue.music.game_music.scan_error]" style "cue_txt" color _cue_color_error
                        text ("No music found in game directory.").format(", ".join(CUE_GAME_MUSIC_DIRS)) style "cue_txt"
                    else:
                        use cue_game_music_tree()

screen trigger_list(triggers):
    for trigger in triggers:
        null height 2
        frame:
            background (_cue_color_green if trigger["selected"] else _cue_color_text_dim)
            padding (1, 1)  # border thickness
            xfill True
            button:
                background _cue_color_bg_panel
                hover_background _cue_color_bg_input
                action Function(_cue.music.select_trigger, trigger["key"])
                padding (4, 4)
                xfill True
                vbox:
                    spacing 3
                    hbox:
                        spacing 6
                        use cue_icon_btn(
                            ("rotate-right" if trigger["is_default"] else "trash-can"),
                            Function(_cue.music.delete_trigger, trigger["key"]),
                            ("Reset to default" if trigger["is_default"] else "Delete trigger"),
                            None)
                        text trigger["label"] style "cue_txt" color _cue_color_text_accent
                    if trigger["is_default"]:
                        $ _default_path = trigger["default_path"] or ""
                        hbox:
                            spacing 6
                            use cue_icon_btn(
                                ("volume" if trigger["default_enabled"] else "volume-xmark"),
                                Function(_cue.music.toggle_default, trigger["key"]),
                                "Toggle default song",
                                None)
                            if trigger["default_enabled"]:
                                text "Default: [_default_path]" style "cue_txt"
                            else:
                                text ("Default: [_default_path] "
                                        "(Disabled)") style "cue_txt" color _cue_color_text_muted
                    if trigger["songs"]:
                        for _idx, _song in enumerate(trigger["songs"]):
                            if _song.endswith("/"):
                                # Folder ref: expandable, count + detachable children.
                                $ _song_path = _cue.music.ref_path(_song)
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
                                        "Remove folder from trigger",
                                        None)
                                    use cue_txt_button(
                                        _song_path,
                                        Function(_cue.music.toggle_file_ref_expand, _song))
                                    text ("({} files)".format(len(_folder_files))) style "cue_help"
                                if _folder_expanded:
                                    for _child in _folder_files:
                                        hbox:
                                            spacing 6
                                            text "    " style "cue_txt"
                                            use cue_icon_btn(
                                                "xmark",
                                                Function(
                                                    _cue.music.remove_song_from_folder_ref,
                                                    trigger["key"],
                                                    _idx,
                                                    _child),
                                                "Remove file from the folder",
                                                None)
                                            $ _child_display = _child[len(_song_path):]
                                            text _child_display style "cue_txt"
                            else:
                                $ _song_name = _song.rsplit("/", 1)[-1]
                                hbox:
                                    spacing 6
                                    use cue_icon_btn(
                                        "xmark",
                                        Function(
                                            _cue.music.remove_song_from_trigger,
                                            trigger["key"],
                                            _song),
                                        "Remove song from trigger",
                                        None)
                                    text _song_name style "cue_txt"
                    elif not trigger["is_default"]:
                        text "No music added." style "cue_txt"

# My/Game Music file tree. Each row carries a play button plus an
# add-to-trigger "+" button. Shared by the two wrappers below, which pass the
# tree source (user- vs game-music) and the user/game-specific callables.
screen _cue_music_file_tree(tree, add_folder, toggle_folder, preview, add_song):
    $ _tree_add_tt = "Add song to " + (_cue.music.selected_trigger_label() or "(no trigger selected)")
    $ _tree_add_folder_tt = "Add folder to " + (_cue.music.selected_trigger_label() or "(no trigger selected)")
    $ _tree_add_enabled = _cue.music.selected_key is not None
    vbox:
        spacing 2
        for item in tree:
            hbox:
                spacing 2
                if item["depth"] > 0:
                    text " " * item["depth"] style "cue_txt"
                if item["type"] == "folder":
                    use cue_icon_btn(
                        "plus",
                        Function(add_folder, item["full_path"]),
                        _tree_add_folder_tt,
                        None,
                        enabled=_tree_add_enabled)
                    use cue_txt_button(
                        item["name"],
                        Function(toggle_folder, item["full_path"]),
                    )
                else:
                    use cue_icon_btn("play", Function(preview, item["full_path"]), "Play song", None)
                    use cue_icon_btn(
                        "plus",
                        Function(add_song, item["full_path"]),
                        _tree_add_tt,
                        None,
                        enabled=_tree_add_enabled)
                    text item["name"] style "cue_txt" color _cue_color_text_accent

# My Music folder/file tree. Mirrors the SFX Library tree (cue_file_tree) but
# each file row carries a play button plus an add-to-trigger "+" button.
screen cue_music_tree():
    if _cue.music.user_music.search_query.strip() and not _cue.music.user_music.visible_tree:
        text 'No files found for "{}".'.format(_cue.music.user_music.search_query) style "cue_txt"
    else:
        use _cue_music_file_tree(
            _cue.music.user_music.visible_tree,
            _cue.music.add_user_folder_to_trigger,
            _cue.music.user_music.toggle_folder,
            _cue_preview_music,
            _cue.music.add_user_song_to_trigger)

# Game Music folder/file tree. Lists the game's own bundled audio, discovered
# from the virtual filesystem by dir-name heuristic.
screen cue_game_music_tree():
    if _cue.music.game_music.search_query.strip() and not _cue.music.game_music.visible_tree:
        text 'No files found for "{}".'.format(_cue.music.game_music.search_query) style "cue_txt"
    else:
        use _cue_music_file_tree(
            _cue.music.game_music.visible_tree,
            _cue.music.add_game_folder_to_trigger,
            _cue.music.game_music.toggle_folder,
            _cue_preview_game_music,
            _cue.music.add_game_song_to_trigger)
