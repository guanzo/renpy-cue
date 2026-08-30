###############################################################################
# Generic multiselect input + dropdown (vue-multiselect-style)
#
# The screens consume a duck-typed "select" manager.  The expected shape:
#   is_open() -> bool
#   toggle_open()
#   selected_keys() -> sorted list
#   is_selected(key) -> bool
#   options() -> list
#   label(key) -> str
#   toggle(key)            # chip click, keeps the dropdown open
#   select(key)            # option click: toggle + close the dropdown
#   trigger_rect() -> (x, y, w, h) | None
#   viewport_h() -> int    # computed option-list height (content up to cap)
###############################################################################

screen cue_select_input(select, placeholder):
    style_group "cue"

    $ _selected = select.selected_keys()
    $ _caret = _cue.icons.displayable_for(
        "chevron-up" if select.is_open() else "chevron-down")
    button:
        style "cue_select_trigger"
        action Function(select.toggle_open)
        hbox:
            spacing 4
            xfill True
            if _selected:
                hbox:
                    box_wrap True
                    box_wrap_spacing _cue_scale_ui(3)
                    spacing _cue_scale_ui(3)
                    xfill True
                    for _key in _selected:
                        use cue_select_chip(select, _key)
            else:
                hbox:
                    xfill True
                    etext placeholder style "cue_select_trigger_text"
            add _caret yalign 0.5 xoffset -_cue_scale_ui(14)


screen cue_select_dropdown(select):
    style_group "cue"

    # Rendered by cue_overlay (not the page) so it floats over the page rows
    # at the trigger's on-screen rect; opening it must not shift the layout.
    # The trigger rect + fixed option heights make the rendered height
    # deterministic (see CueSelect.frame_h), so the click-outside rect in
    # focus.py matches it exactly -- no dead zone below a short list.
    $ _rect = select.trigger_rect()
    $ _options = select.options()
    if _rect:
        frame:
            style "cue_select_dropdown"
            xpos _rect[0]
            ypos _rect[1] + _rect[3]
            xsize _rect[2]
            use grow_and_scroll(select.viewport_h(), select.viewport_h()):
                vbox:
                    spacing _cue_scale_ui(CUE_SELECT_OPTION_GAP)
                    for _key in _options:
                        use cue_select_option(select, _key)


screen cue_select_option(select, key):
    style_group "cue"

    $ _display = select.label(key)
    button:
        style "cue_select_option"
        action Function(select.select, key)
        hbox:
            xfill True
            spacing 6
            etext _display style "cue_select_option_text"
            if select.is_selected(key):
                add (_cue.icons.displayable_for("circle-check", None, 11)) xalign 1.0 yalign 0.5


screen cue_select_chip(select, key):
    style_group "cue"

    $ _display = select.label(key)
    $ _x_icon = _cue.icons.displayable_for("xmark", None, 10)
    button:
        style "cue_select_chip"
        action Function(select.toggle, key)
        hbox:
            spacing 3
            etext _display style "cue_select_chip_text"
            add _x_icon yalign 0.5

