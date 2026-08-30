###############################################################################
# Multiselect input + dropdown styles
#
# CUE_SELECT_OPTION_H / CUE_SELECT_OPTION_GAP must stay in sync with the
# option row ysize and the vpgrid spacing here: CueSelect computes the
# dropdown height deterministically from those two constants.
###############################################################################

style cue_select_trigger is empty:
    xfill True
    background _cue_color_bg_input
    hover_background _cue_color_bg_input_hover
    padding (_cue_scale_ui(6), _cue_scale_ui(3))
    hover_sound None
    activate_sound None

style cue_select_trigger_text is cue_text:
    size _cue_scale_ui(11)
    color _cue_color_text_muted
    xalign 0.0
    yalign 0.5

style cue_select_chip is empty:
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    padding (_cue_scale_ui(4), _cue_scale_ui(1))
    yminimum _cue_scale_ui(14)
    hover_sound None
    activate_sound None

style cue_select_chip_text is cue_text:
    size _cue_scale_ui(10)
    color _cue_color_text_white
    xalign 0.0
    yalign 0.5

style cue_select_dropdown is empty:
    # xsize/position come from the trigger's rect in cue_select_dropdown;
    # height comes from the grow_and_scroll viewport inside.
    background _cue_color_bg_dialog
    padding (_cue_scale_ui(CUE_SELECT_FRAME_PAD / 2), _cue_scale_ui(CUE_SELECT_FRAME_PAD / 2))
    hover_sound None
    activate_sound None

style cue_select_option is empty:
    xfill True
    ysize _cue_scale_ui(CUE_SELECT_OPTION_H)
    background _cue_color_bg_input
    hover_background _cue_color_bg_btn_hover
    padding (_cue_scale_ui(6), 0)
    hover_sound None
    activate_sound None

style cue_select_option_text is cue_text:
    size _cue_scale_ui(11)
    color _cue_color_text
    xalign 0.0
    yalign 0.5
