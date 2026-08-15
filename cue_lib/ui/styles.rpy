
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
define _cue_color_yellow = "#887722"
define _cue_color_red = "#664444"
define _cue_color_red_hover = "#885555"
define _cue_color_error = "#ff6666"

# --- Controls ---
define _cue_color_bar_active = "#007AFF"

style cue_frame is empty:
    background _cue_color_bg_overlay
    padding (4, 4)
    xfill True

style cue_popper_frame is empty:
    background "#000000ee"
    padding (8, 6)
    xfill False

style cue_btn is empty:
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    padding (2, 0)
    hover_sound None
    activate_sound None

style cue_btn_text is empty:
    size 12
    color _cue_color_text_white
    hover_color _cue_color_text_white
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5
    xanchor 0.5
    yanchor 0.5
    adjust_spacing False

style cue_btn_icon is empty:
    xysize (16, 16)
    padding (0, 0)
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    insensitive_background _cue_color_bg_dialog
    hover_sound None
    activate_sound None

style cue_btn_icon_text is empty:
    size 12
    color _cue_color_text_white
    insensitive_color _cue_color_bg_btn_hover
    font "DejaVuSans.ttf"
    xalign 0.5
    yalign 0.5
    xanchor 0.5
    yanchor 0.5
    adjust_spacing False
    hover_xoffset 0
    hover_yoffset 0
    hover_xalign 0.5
    hover_yalign 0.5
    padding (0, 0)

style cue_txt is empty:
    size 12
    color _cue_color_text
    font "DejaVuSans.ttf"

style cue_hdr is cue_txt:
    size 14
    color _cue_color_text_accent
    bold True

style cue_help is cue_txt:
    size 11
    color _cue_color_text_muted

style cue_input is cue_txt:
    size 12
    color _cue_color_text_white
    background _cue_color_bg_input
    xsize 72
    padding (2, 2)
    ypadding 2

style cue_vscrollbar:
    xsize 6
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)

style cue_scrollbar:
    ysize 6
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)

style cue_vbar_scroll is vscrollbar
style cue_vbar_scroll:
    xsize 6
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)