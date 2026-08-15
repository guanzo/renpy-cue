###############################################################################
# SFX Page
###############################################################################

screen cue_sfx_page():
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
            $ _img_r = _cue.markers.resolve_pool(_cue.markers.image.get_active_pool())
            use cue_checkbox(_img_r.trigger_on_shake,
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
        $ _loop_r = _cue.markers.resolve_pool(_cue.markers.loop.get_active_pool())
        $ _freq = _loop_r.frequency
        hbox:
            spacing 5
            box_wrap True
            box_wrap_spacing 3
            text "Interval:" style "cue_txt"
            use cue_select_btn(
                "Slowest",
                (_freq == CueLoopFrequency.SLOWEST),
                Function(_cue.markers.loop.set_frequency, CueLoopFrequency.SLOWEST),
                tt="~6.3s between plays")
            use cue_select_btn(
                "Slow",
                (_freq == CueLoopFrequency.SLOW),
                Function(_cue.markers.loop.set_frequency, CueLoopFrequency.SLOW),
                tt="~3.8s between plays")
            use cue_select_btn(
                "Normal",
                (_freq == CueLoopFrequency.NORMAL),
                Function(_cue.markers.loop.set_frequency, CueLoopFrequency.NORMAL),
                tt="~2.1s between plays")
            use cue_select_btn(
                "Fast",
                (_freq == CueLoopFrequency.FAST),
                Function(_cue.markers.loop.set_frequency, CueLoopFrequency.FAST),
                tt="~0.6s between plays")
            use cue_select_btn(
                "Fastest",
                (_freq == CueLoopFrequency.FASTEST),
                Function(_cue.markers.loop.set_frequency, CueLoopFrequency.FASTEST),
                tt="~0.2s between plays")

    # Audio file browser (in-flow, only when overlay mode is OFF)
    if not _cue.sfx_library_overlay_mode:
        use cue_sfx_library(_is_video, _has_image, _is_dialogue)
