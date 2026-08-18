
###############################################################################
# Styles — all properties explicit, no inheritance
###############################################################################

# Color defines must exist before init-time style blocks in components.rpy
# reference them (components.rpy sorts before styles.rpy). Run them earlier.
init offset = -1

# --- Surfaces (dark theme, darkest → lightest) ---
define _cue_color_bg_overlay = "#000000ee"
define _cue_color_bg_scrollbar = "#1a1a1a"
define _cue_color_bg_panel = "#222222"
define _cue_color_bg_dialog = "#2a2a2a"
define _cue_color_bg_input = "#333333"
define _cue_color_border = "#786262"
define _cue_color_bg_btn = "#444444"
define _cue_color_divider = "#555555"
define _cue_color_bg_btn_hover = "#666666"

# --- Text ---
define _cue_color_text = "#cccccc"
define _cue_color_text_white = "#ffffff"
define _cue_color_text_accent = "#ffb60f"
define _cue_color_text_muted = "#aaaaaa"
define _cue_color_text_dim = "#888888"

# --- Semantic ---
define _cue_color_green = "#55aa55"
define _cue_color_green_hover = "#77cc77"
define _cue_color_active = "#567f56"
define _cue_color_active_hover = "#679067"
define _cue_color_selected = "#446688"
define _cue_color_yellow = "#887722"
define _cue_color_warn = "#ffd24a"
define _cue_color_red = "#664444"
define _cue_color_red_hover = "#885555"
define _cue_color_error = "#ff6666"

# --- Controls ---
define _cue_color_bar_active = "#007AFF"

define _cue_btn_height = 16

style cue_frame is empty:
    background _cue_color_bg_panel
    padding (4, 4)
    xfill True

style cue_popper_frame is empty:
    background "#000000ee"
    padding (8, 6)
    xfill False

style cue_button is empty:
    ysize _cue_btn_height
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    padding (2, 0)
    hover_sound None
    activate_sound None

style cue_icon_button is empty:
    xysize (_cue_btn_height, _cue_btn_height)
    padding (0, 0)
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    insensitive_background _cue_color_bg_dialog
    hover_sound None
    activate_sound None

style cue_text is empty:
    size 12
    color _cue_color_text
    font "DejaVuSans.ttf"

style cue_button_text is cue_text:
    color _cue_color_text_white
    hover_color _cue_color_text_white
    xalign 0.5
    yalign 0.5
    xanchor 0.5
    yanchor 0.5
    yoffset 1
    adjust_spacing False

style cue_icon_button_text is cue_button_text:
    insensitive_color _cue_color_bg_btn_hover
    padding (0, 0)

style cue_hdr is cue_text:
    size 14
    color _cue_color_text_accent
    bold True

style cue_help is cue_text:
    size 11
    color _cue_color_text_muted

style cue_input is cue_text:
    color _cue_color_text_white
    background _cue_color_bg_input
    yalign 0.5
    yanchor 0.5
    adjust_spacing False

style cue_hbox is empty:
    spacing 5

style cue_vbox is empty:
    spacing 5

style cue_vscrollbar is empty:
    xsize 6
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)
    thumb_offset 0
    bar_vertical True
    bar_invert True
    bar_resizing False

style cue_scrollbar is empty:
    ysize 6
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)
    thumb_offset 0
    bar_vertical False
    bar_resizing False
