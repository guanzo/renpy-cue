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
            "Click a trigger to select it, then click the + button "
            "in My/Game Music to add a song to the trigger.\n\n"
            "If you add multiple songs, one will be picked at random.\n\n"
            "Default music triggers must be discovered by playing through the replay.")
        use cue_section_frame("Music Triggers", tt=music_tt):
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                vbox:
                    spacing 5
                    hbox:
                        spacing 8
                        box_wrap True
                        box_wrap_spacing 3
                        text "Now Playing:"
                        text (_cue.music.now_playing() or "(None)") color _cue_color_text_accent
                    hbox:
                        spacing 8
                        box_wrap True
                        box_wrap_spacing 3
                        text "Current Scene:"
                        text (_cue.current_file or "(None)") color _cue_color_text_accent
                    
                    null height 5

                    $ triggers = _cue.music.triggers()
                   
                    if not triggers:
                        text "No music triggers for this replay yet."
                    else:
                        text "Music Triggers:"
                        use trigger_list(triggers)
                    
                    if not renpy.store._in_replay:
                        null height 4
                        $ _warn_icon = _cue.icons.displayable_for("triangle-exclamation", _cue_color_warn)
                        hbox:
                            spacing 6
                            add _warn_icon yalign 0.5
                            text ("Customizing Music is only fully supported in replays, "
                                    "it may not work properly in game.") color _cue_color_warn
                    
                    null height 4
                    use cue_txt_button(
                        "+ Play music starting at current scene",
                        Function(_cue.music.add_custom_trigger))

        $ music_lib_tt = (
            "My Music: add {} files to \n{}.\n\n"
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
                    # Per-source empty/error states -- one source can be empty
                    # while the other has files.
                    if not _cue.music.user_music.tree:
                        if _cue.music.user_music.scan_error:
                            text "[_cue.music.user_music.scan_error]" color _cue_color_error
                        text "No music found in: [_cue.paths.music_dir]"
                        text ("Add {} files there "
                            "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS))
                    if not _cue.music.game_music.tree:
                        if _cue.music.game_music.scan_error:
                            text "[_cue.music.game_music.scan_error]" color _cue_color_error
                        text "No music found in game directory."
                    if _cue.music.user_music.tree or _cue.music.game_music.tree:
                        use cue_music_tree()

screen trigger_list(triggers):
    style_group "cue"

    for trigger in triggers:
        null height 2
        button:
            style "empty"
            background (_cue_color_bg_input if trigger["selected"] else _cue_color_bg_panel)
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
                    text trigger["label"] color _cue_color_text_accent
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
                            text "Default: [_default_path]"
                        else:
                            text ("Default: [_default_path] "
                                    "(Disabled)") color _cue_color_text_muted
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
                                        text "    "
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
                                        text _child_display
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
                                text _song_name
                elif not trigger["is_default"]:
                    text "No music added."

# Combined Music Library file tree. Each row carries a play button plus an
# add-to-trigger "+" button. The combined manager routes display paths back to
# the correct (user- vs game-music) data model, and clears can_add on the
# synthetic "Game Music/" root.
screen _cue_music_file_tree(tree, add_folder, toggle_folder, preview, add_song):
    style_group "cue"

    $ _tree_add_tt = "Add song to " + (_cue.music.selected_trigger_label() or "(no trigger selected)")
    $ _tree_add_folder_tt = "Add folder to " + (_cue.music.selected_trigger_label() or "(no trigger selected)")
    $ _tree_add_enabled = _cue.music.selected_key is not None
    vbox:
        spacing 2
        for item in tree:
            hbox:
                spacing 2
                if item["depth"] > 0:
                    text " " * item["depth"]
                if item["type"] == "folder":
                    # can_add is False only on the synthetic "Game Music/" root,
                    # which groups several real folders and has no single data
                    # path to add.
                    use cue_icon_btn(
                        "plus",
                        Function(add_folder, item["full_path"]),
                        _tree_add_folder_tt,
                        None,
                        enabled=(_tree_add_enabled and item.get("can_add", True)))
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
                    text item["name"] color _cue_color_text_accent

# Combined My/Game Music tree. One shared search bar filters both sources; the
# combined manager's visible_tree holds the merged display rows.
screen cue_music_tree():
    style_group "cue"

    if _cue.music.library.search_query.strip() and not _cue.music.library.visible_tree:
        text 'No files found for "{}".'.format(_cue.music.library.search_query)
    else:
        use _cue_music_file_tree(
            _cue.music.library.visible_tree,
            _cue.music.library.add_folder_to_trigger,
            _cue.music.library.toggle_folder,
            _cue.music.library.preview,
            _cue.music.library.add_song_to_trigger)
