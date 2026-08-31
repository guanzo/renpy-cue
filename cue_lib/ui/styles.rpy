
###############################################################################
# Styles — all properties explicit, no inheritance
###############################################################################

# Color defines must exist before init-time style blocks in
# components/screens.rpy reference them. Run them earlier so the
# engine's (unspecified) file load order can't matter.
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
define _cue_color_bg_input_hover = "#383838"
define _cue_color_bg_input_active = "#484848"

# --- Text ---
define _cue_color_text = "#cccccc"
define _cue_color_text_white = "#ffffff"
define _cue_color_text_black = "#1A1A1A"
define _cue_color_text_accent = "#ffb60f"
define _cue_color_text_muted = "#aaaaaa"
define _cue_color_text_dim = "#888888"

# --- Semantic ---
define _cue_color_green = "#55aa55"
define _cue_color_green_hover = "#77cc77"
define _cue_color_active = "#567f56"
define _cue_color_active_hover = "#679067"
define _cue_color_selected_alt = "#446688"
define _cue_color_selected_alt_hover = "#5588aa"
define _cue_color_dark_yellow = "#886600"
define _cue_color_warn = "#ffd24a"
define _cue_color_red = "#664444"
define _cue_color_red_hover = "#885555"
define _cue_color_error = "#ff6666"

# --- Controls ---
define _cue_color_bar_active = "#3a5269"

define _cue_overlay_panel_width = 500
define _cue_btn_height = 16
# Tree cell height for the virtualized cue_tree_rows.  Text is a fixed 12px
# (never _cue_scale_ui'd), so at sub-1920 games the line (~16px) is taller than
# a scaled icon button; the 18px floor keeps cells tall enough at every scale.
define _cue_tree_row_h = max(_cue_scale_ui(18), 18)

define _cue_indent = "  "

style cue_frame is empty:
    background _cue_color_bg_panel
    padding (_cue_scale_ui(4), _cue_scale_ui(4))
    xfill True
    
# Section frame: styled frame + header, with transclude for child content.
style cue_section_hdr_btn is empty:
    background None
    hover_background _cue_color_bg_input
    padding (4, 2)
    xfill True
    hover_sound None
    activate_sound None

# Dialog shell: dark outer button whose 4px padding ring reads as a black
# border around the content panel, matching the overlay/sfx panels (outer
# padded container + nested dark frame).
style cue_dialog_wrapper is empty:
    xpos _cue_scale_ui(_cue_overlay_panel_width)
    ypos _cue_scale_ui(4)
    padding (_cue_scale_ui(4), _cue_scale_ui(4))
    background _cue_color_bg_overlay
    hover_background _cue_color_bg_overlay
    xmaximum _cue_scale_ui(408)

# Inner content panel of a dialog: the dark surface the actual dialog lives
# on, inset inside cue_dialog_wrapper's border ring.
style cue_dialog_content is empty:
    padding (_cue_scale_ui(16), _cue_scale_ui(8))
    background _cue_color_bg_dialog
    hover_background _cue_color_bg_dialog

style cue_popper_frame is empty:
    background "#000000ee"
    padding (_cue_scale_ui(8), _cue_scale_ui(6))
    xfill False

style cue_button is empty:
    yminimum _cue_scale_ui(_cue_btn_height)
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    insensitive_background _cue_color_bg_dialog
    padding (_cue_scale_ui(2), 0)
    hover_sound None
    activate_sound None

style cue_icon_button is empty:
    xysize (_cue_scale_ui(_cue_btn_height), _cue_scale_ui(_cue_btn_height))
    padding (0, 0)
    background _cue_color_bg_btn
    hover_background _cue_color_bg_btn_hover
    insensitive_background _cue_color_bg_dialog
    hover_sound None
    activate_sound None

style cue_scene_thumb is empty:
    padding (0, 0)
    background _cue_color_bg_overlay
    hover_background _cue_color_bg_overlay
    mouse "cue_pointer"
    hover_sound None
    activate_sound None

style cue_text is empty:
    size _cue_scale_ui(12)
    color _cue_color_text
    font "DejaVuSans.ttf"

style cue_button_text is cue_text:
    color _cue_color_text_white
    hover_color _cue_color_text_white
    insensitive_color _cue_color_text_dim
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
    size _cue_scale_ui(14)
    color _cue_color_text_accent
    bold True

style cue_help is cue_text:
    size _cue_scale_ui(11)
    color _cue_color_text_muted

# About-page hyperlinks.  {a=} tags need a per-style handler: theming the
# link means overriding hyperlink_functions on the text's own style (not the
# global style.hyperlink_text), and the click handler must open the browser on
# 7.x too, where renpy.open_url does not exist.
init python:
    def _cue_about_link_styler(target):
        return style.cue_about_link_text

    def _cue_open_url(url):
        if hasattr(renpy, "open_url"):
            renpy.open_url(url)
        else:
            import webbrowser
            webbrowser.open(url)

style cue_about_link_text is cue_help:
    idle_color "#66aaff"
    hover_color "#7ab4ff"

style cue_about_link is cue_help:
    hyperlink_functions (_cue_about_link_styler, _cue_open_url, None)
    mouse "cue_pointer"

style cue_input is cue_text:
    color _cue_color_text_white
    background _cue_color_bg_input
    yalign 0.5
    yanchor 0.5
    adjust_spacing False

style cue_hbox is empty:
    spacing _cue_scale_ui(5)

style cue_vbox is empty:
    spacing _cue_scale_ui(5)

style cue_vscrollbar is empty:
    xsize _cue_scale_ui(6)
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)
    thumb_offset 0
    bar_vertical True
    bar_invert True
    bar_resizing False

style cue_scrollbar is empty:
    ysize _cue_scale_ui(6)
    base_bar Solid(_cue_color_bg_scrollbar)
    thumb Solid(_cue_color_divider)
    hover_thumb Solid(_cue_color_text_dim)
    thumb_offset 0
    bar_vertical False

style cue_sidebar_handle is empty:
    mouse "cue_resize"
