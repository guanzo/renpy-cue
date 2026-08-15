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
        use cue_section_frame("Music"):
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

                    $ discover_tip = "Default music triggers must be discovered by playing through the replay."
                    $ triggers = _cue.music.trigger_boxes()
                   
                    text discover_tip style "cue_txt"
                    if not triggers:
                        text "No music triggers for this replay yet." style "cue_txt"
                    else:
                        text ("Click a trigger to select it, then click the + button "
                              "in My/Game Music to add a song to the trigger.") style "cue_txt"
                        use trigger_box_list(triggers)
                    null height 4
                    use cue_txt_button("+ Add music to current scene", Function(_cue.music.add_custom_trigger))

        use cue_section_frame("My Music"):
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                if not _cue.music.user_music.tree:
                    if _cue.music.user_music.scan_error:
                        text "[_cue.music.user_music.scan_error]" style "cue_txt" color _cue_color_error
                    text ("Add {} files to your music folder "
                        "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS)) style "cue_txt"
                    text "[_cue.paths.music_dir]" style "cue_txt"
                else:
                    use cue_music_tree()

        use cue_section_frame("Game Music"):
            use grow_and_scroll(200, max(int(0.30 * renpy.config.screen_height), 400)):
                if not _cue.music.game_music.tree:
                    if _cue.music.game_music.scan_error:
                        text "[_cue.music.game_music.scan_error]" style "cue_txt" color _cue_color_error
                    text ("No music found in game dirs ({})."
                        "Files are classified by folder name.").format(", ".join(CUE_GAME_MUSIC_DIRS)) style "cue_txt"
                else:
                    vbox:
                        spacing 5
                        text "Game music is found with heuristics, this list may not be accurate." style "cue_txt"
                        use cue_game_music_tree()

screen trigger_box_list(triggers):
    for trigger in triggers:
        null height 2
        frame:
            background (_cue_color_green if trigger["selected"] else _cue_color_text_dim)
            padding (1, 1)  # this is your border thickness
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
                            "trash-can",
                            Function(_cue.music.delete_trigger, trigger["key"]),
                            ("Reset to default" if trigger["is_default"] else "Delete trigger"),
                            None)
                        text trigger["label"] style "cue_txt" color _cue_color_text_accent
                    if trigger["is_default"]:
                        $ _default_path = trigger["default_path"] or ""
                        hbox:
                            spacing 6
                            use cue_icon_btn(
                                "xmark",
                                Function(_cue.music.toggle_default, trigger["key"]),
                                "Toggle default song",
                                None)
                            if trigger["default_enabled"]:
                                text "Default: [_default_path]" style "cue_txt"
                            else:
                                text ("Default: [_default_path] "
                                        "(Disabled)") style "cue_txt" color _cue_color_text_muted
                    if trigger["songs"]:
                        for _song in trigger["songs"]:
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

# My Music folder/file tree. Mirrors the SFX Library tree (cue_file_tree) but
# each file row carries a play button plus an add-to-trigger "+" button.
screen cue_music_tree():
    $ _tree_add_tt = "Add song to " + (_cue.music.selected_trigger_label() or "(no trigger selected)")
    $ _tree_add_enabled = _cue.music.selected_key is not None
    vbox:
        spacing 2
        for item in _cue.music.user_music.visible_tree:
            hbox:
                spacing 2
                if item["depth"] > 0:
                    text " " * item["depth"] style "cue_txt"
                if item["type"] == "folder":
                    use cue_txt_button(
                        item["name"],
                        Function(_cue.music.user_music.toggle_folder, item["full_path"]),
                    )
                else:
                    use cue_icon_btn("play", Function(_cue_preview_music, item["full_path"]), "Play song", None)
                    use cue_icon_btn(
                        "plus",
                        Function(_cue.music.add_song_to_trigger, item["full_path"]),
                        _tree_add_tt,
                        None,
                        enabled=_tree_add_enabled)
                    text item["name"] style "cue_txt" color _cue_color_text_accent


# Game Music folder/file tree. Mirrors cue_music_tree but lists the game's own
# bundled audio, discovered from the virtual filesystem by dir-name heuristic.
screen cue_game_music_tree():
    $ _game_add_tt = "Add song to " + (_cue.music.selected_trigger_label() or "(no trigger selected)")
    $ _game_add_enabled = _cue.music.selected_key is not None
    vbox:
        spacing 2
        for item in _cue.music.game_music.visible_tree:
            hbox:
                spacing 2
                if item["depth"] > 0:
                    text " " * item["depth"] style "cue_txt"
                if item["type"] == "folder":
                    use cue_txt_button(
                        item["name"],
                        Function(_cue.music.game_music.toggle_folder, item["full_path"]),
                    )
                else:
                    use cue_icon_btn(
                        "play",
                        Function(_cue_preview_game_music, item["full_path"]),
                        "Play song",
                        None,
                    )
                    use cue_icon_btn(
                        "plus",
                        Function(_cue.music.add_song_to_trigger, item["full_path"]),
                        _game_add_tt,
                        None,
                        enabled=_game_add_enabled)
                    text item["name"] style "cue_txt" color _cue_color_text_accent
