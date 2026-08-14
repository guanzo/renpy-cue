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
                #ymaximum max(int(0.5 * renpy.config.screen_height), 300)
                ymaximum ymax
            if ymin is not None: 
                yminimum ymin
                #yminimum 200 

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
                    null height 10
                    
                    if not _cue.current_replay:
                        text "Enter a replay to see its default music triggers." style "cue_txt"
                    else:
                        $ _triggers = _cue.music.triggers_for(_cue.current_replay)
                        if not _triggers:
                            text "No music triggers recorded for this replay yet." style "cue_txt"
                        else:
                            for _t in _triggers:
                                hbox:
                                    spacing 8
                                    box_wrap True
                                    box_wrap_spacing 3
                                    text _cue_strip_key_prefix(_t.get("key_after") or _t["key_before"]) style "cue_txt"
                                    text _t["filepath"] style "cue_txt"

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


# My Music folder/file tree. Mirrors the SFX Library tree (cue_file_tree) but
# each file row carries only a play button.
screen cue_music_tree():
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
                    text item["name"] style "cue_txt" color _cue_color_text_accent


# Game Music folder/file tree. Mirrors cue_music_tree but lists the game's own
# bundled audio, discovered from the virtual filesystem by dir-name heuristic.
screen cue_game_music_tree():
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
                    text item["name"] style "cue_txt" color _cue_color_text_accent
