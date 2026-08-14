###############################################################################
# Music Page
###############################################################################

screen cue_music_page():
    vbox:
        spacing 5
        use cue_section_frame("Music"):
            vbox:
                spacing 5
                if not _cue.current_replay:
                    text "Enter a replay to see its default music triggers." style "cue_help"
                else:
                    $ _triggers = _cue.music.triggers_for(_cue.current_replay)
                    if not _triggers:
                        text "No music triggers recorded for this replay yet." style "cue_help"
                    else:
                        for _t in _triggers:
                            hbox:
                                spacing 8
                                text (_t.get("key_after") or _t["key_before"]) style "cue_txt"
                                text _t["filepath"] style "cue_help"

        use cue_section_frame("My Music"):
            if not _cue.music.user_music.music_tree:
                if _cue.music.user_music.music_scan_error:
                    text "[_cue.music.user_music.music_scan_error]" style "cue_help" color _cue_color_error
                text ("Add {} files to your music folder "
                    "and click the refresh button.").format(", ".join(CUE_AUDIO_EXTS)) style "cue_help"
                text "[_cue.paths.music_dir]" style "cue_help"
            else:
                use cue_music_tree()

        use cue_section_frame("Game Music"):
            if not _cue.music.game_music.music_tree:
                if _cue.music.game_music.music_scan_error:
                    text "[_cue.music.game_music.music_scan_error]" style "cue_help" color _cue_color_error
                text ("No music found in game dirs ({})."
                    "Files are classified by folder name.").format(", ".join(CUE_GAME_MUSIC_DIRS)) style "cue_help"
            else:
                use cue_game_music_tree()


# My Music folder/file tree. Mirrors the SFX Library tree (cue_file_tree) but
# each file row carries only a play button.
screen cue_music_tree():
    viewport:
        xfill True
        yfill True
        mousewheel True
        scrollbars "vertical"
        style_group "cue"
        vscrollbar_unscrollable "hide"
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
    viewport:
        xfill True
        yfill True
        mousewheel True
        scrollbars "vertical"
        style_group "cue"
        vscrollbar_unscrollable "hide"
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
