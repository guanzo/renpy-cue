###############################################################################
# Reusable Component Screens
###############################################################################

init -900 python:
    class _CueFieldValue(FieldInputValue):
        """Like FieldInputValue but takes a dotted path string.

        _CueFieldValue("_cue.video_editor.factor_text") is equivalent to
        FieldInputValue("_cue.video_editor", "factor_text") — it splits
        on the LAST dot and treats everything before it as the object
        expression, everything after as the field name.
        """
        def __init__(self, dotted_path, default=True):
            _dot = dotted_path.rfind(".")
            if _dot == -1:
                # No dot: treat as a simple store variable
                self._obj_expr = "store"
                self._field = dotted_path
            else:
                self._obj_expr = dotted_path[:_dot]
                self._field = dotted_path[_dot + 1:]
            # Evaluate now so FieldInputValue gets the actual object, not
            # a string. In Python 2 screen strings are unicode, which fails
            # FieldInputValue's isinstance(obj, str) gate in get_text/set_text.
            _obj = renpy.python.py_eval(self._obj_expr)
            FieldInputValue.__init__(self, _obj, self._field, default=default)

    class _CueVolumeValue(DictValue):
        """A DictValue that persists the owning marker after the bar changes.

        DictValue writes ``dict[key]`` through its changed() hook; we save the
        marker (passed in as marker_key) on top of that."""
        def __init__(self, entry_dict, field, marker_key, **kwargs):
            DictValue.__init__(self, entry_dict, field, **kwargs)
            self._marker_key = marker_key

        def changed(self, value):
            super(_CueVolumeValue, self).changed(value)
            _cue.volume.marker_queue_save(self._marker_key)



# Vertical divider: thin line for visual separation between controls.
screen cue_v_divider(height=14, width=2, color=None):
    fixed:
        ysize height
        xsize width
        add Solid(color or _cue_color_divider)

# Horizontal divider: thin full-width line.
screen cue_h_divider(color=None):
    add Solid(color or _cue_color_divider) ysize 1


# Volume row: label + slider bar
screen cue_vol_row(label_text, entry_dict, key):
    hbox:
        spacing 3
        text label_text style "cue_txt" size 11
        bar:
            value _CueVolumeValue(entry_dict, "volume", key, range=_cue.volume.VOL_MAX)
            xsize 60
            ysize 14
            left_bar Solid(_cue_color_bar_active)
            right_bar Solid(_cue_color_bg_input)
            thumb Solid(_cue_color_text)
            hover_thumb Solid(_cue_color_text_white)

# Icon button: tiny button with cue_btn_icon / cue_btn_icon_text styles.
# Most callers don't need xsize (style default is 14); pass an int to override.
# Pass tt=None to skip the tooltip.
# `label` is an icon name ("clipboard", "xmark") or plain text ("-", "V").
# Names mapped in CueIconManager render as PNG images (white, shown at
# 12px from a 32px source, dimmed via alpha when disabled); everything
# else falls back to text.
screen cue_icon_btn(label, action, tt=None, xsize=16, enabled=True, bg=None, icon_color=None):
    $ _icon = _cue.icons.displayable_for(label, icon_color) if _cue.icons is not None else None
    if _icon is not None:
        button:
            style "cue_btn_icon"
            ysize 16
            if xsize is not None:
                xsize xsize
            if tt is not None:
                tooltip tt
            sensitive enabled
            action action
            if bg is not None:
                background bg
            if enabled:
                add _icon xalign 0.5 yalign 0.5
            else:
                add _icon xalign 0.5 yalign 0.5 alpha 0.35
    else:
        textbutton label:
            style "cue_btn_icon"
            text_style "cue_btn_icon_text"
            ysize 16
            if xsize is not None:
                xsize xsize
            if tt is not None:
                tooltip tt
            sensitive enabled
            action action
            if bg is not None:
                background bg

transform cue_icon_fade:
    alpha 0.5
    on hover:
        linear 0.1 alpha 1.0
    on idle:
        linear 0.1 alpha 0.5

screen cue_icon(label, tt=None, action=NullAction(), icon_color=None, size=12):
    $ _icon = _cue.icons.displayable_for(label, icon_color, size)
    button:
        style "empty"
        padding (0, 0)
        background None
        hover_background None
        action action
        if tt is not None:
            tooltip tt
        add _icon at cue_icon_fade

# Base text button: all textbuttons should use this so style/typography
# live in one place. Pass bg/tooltip/sensitive/xsize/ysize to override.
screen cue_txt_button(label, action, bg=None, hover_bg=None, tt=None,
                    sensitive=True, xsize=0, ysize=0):
    textbutton label:
        style "cue_btn"
        text_style "cue_btn_text"
        action action
        sensitive sensitive
        if bg is not None:
            background bg
        if hover_bg is not None:
            hover_background hover_bg
        if tt is not None:
            tooltip tt
        if xsize is not None and xsize > 0:
            xsize xsize
        if ysize is not None and ysize > 0:
            ysize ysize

# Selectable textbutton: highlights when selected, dims when not.
# active_color overrides the highlight (default: _cue_color_active).
screen cue_select_btn(label, selected, action, tt=None, sensitive=True,
                       active_color=None):
    if selected:
        $ _bg = (active_color or _cue_color_active)
        $ _hover = _cue_color_active_hover
        use cue_txt_button(label, action, bg=_bg, hover_bg=_hover, tt=tt, sensitive=sensitive)
    else:
        use cue_txt_button(label, action, bg=_cue_color_bg_btn,
                           hover_bg=_cue_color_bg_btn_hover, tt=tt, sensitive=sensitive)

# Tab textbutton: selected tab is highlighted and non-interactive.
# switch_action fires when an inactive tab is clicked.
screen cue_tab_btn(label, selected, switch_action, tt=None):
    if selected:
        use cue_txt_button(label, NullAction(), bg=_cue_color_active, tt=tt)
    else:
        use cue_txt_button(label, switch_action, tt=tt)

# Float input: textbutton that becomes an input on click, Enter to confirm.
# field_name: string for VariableInputValue
# commit_action: Function() called on Enter — must return True (valid) or False (invalid)
# display_text: the label shown on the textbutton
screen cue_float_input(field_name, commit_action, display_text,
                       dec_action=None, inc_action=None):
    default editing = False
    hbox:
        spacing 3
        if dec_action is not None:
            use cue_icon_btn("-", dec_action)

        if editing:
            key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
            key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
            input:
                style "cue_input"
                value _CueFieldValue(field_name)
                default True
                xsize 80
                ysize 16
        else:
            use cue_txt_button(display_text,
                SetLocalVariable("editing", True),
                ysize=16, tt="Click to edit. Press Enter to confirm.")

        if inc_action is not None:
            use cue_icon_btn("+", inc_action)

# Reusable time input: -- - [textbutton | input] + ++ with nudge buttons and Enter-to-commit.
# field_name: string for VariableInputValue (e.g. "_cue.markers.video.edit_text")
# commit_action: Function() called on Enter to confirm
# dec100/dec10/inc10/inc100_action: Function() called by nudge buttons
screen cue_time_input(field_name, commit_action, dec100_action, dec10_action,
                      inc10_action, inc100_action, display_text):
    default editing = False
    hbox:
        spacing 3
        use cue_icon_btn("--", dec100_action, None, 22)
        use cue_icon_btn("-", dec10_action)

        if editing:
            key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
            key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
            input:
                style "cue_input"
                value _CueFieldValue(field_name)
                default True
        else:
            use cue_txt_button(display_text,
                [SetLocalVariable("editing", True), Function(_cue.markers.video.sync_text)],
                tt="Click to edit. Press Enter to confirm.")

        use cue_icon_btn("+", inc10_action)
        use cue_icon_btn("++", inc100_action, None, 22)

# Text input: textbutton that becomes an input on click, Enter to confirm.
# field_name: string for _CueFieldValue (e.g. "_cue.setup_dir_text")
# commit_action: Function() called on Enter to confirm
# display_text: the label shown on the textbutton
# editing_ref: optional object with a search_is_editing attribute; the screen
#   mirrors its local editing flag there so a parent screen can show/hide
#   sibling controls (e.g. the search bar's clear button while typing).
screen cue_text_input(field_name, commit_action, display_text, xsize=None, editing_ref=None):
    default editing = False
    $ height = 16
    if editing_ref is not None:
        $ editing_ref.search_is_editing = editing
    if editing:
        frame:
            # key must be inside frame, otherwise a parent vbox will add spacing
            # because it considers "key" to be a UI element.
            key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
            key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
            background _cue_color_bg_input
            padding (2, 0)
            ysize height
            #xfill True
            input:
                style "cue_input"
                value _CueFieldValue(field_name)
                default True
                copypaste True
                if xsize is not None:
                    xsize xsize
                ysize height
    else:
        use cue_txt_button(display_text,
            SetLocalVariable("editing", True),
            xsize=xsize, ysize=height, tt="Click to type. Enter to confirm.")

screen cue_search_bar(field_path, manager, hint="Search..."):
    $ _q = manager.search_query
    $ _label = _q if _q.strip() else hint
    vbox:
        spacing 4
        hbox:
            spacing 6
            if _q.strip() or manager.search_is_editing:
                use cue_icon_btn("xmark", Function(manager.clear_search), "Clear search", None)
            use cue_text_input(field_path, Function(manager.rebuild_tree), _label, editing_ref=manager)

        if manager.search_truncated:
            text "{} more results -- narrow your search".format(manager.search_truncated) style "cue_help"

# Pool tab row: optional Delete button, + Pool button, numbered tabs [1][2]...
# tab_action_fn(tab_action_args..., pi) is called when tab pi is clicked.
# delete_xsize/tab_xsize override the default button width (pass None for default).
screen cue_pool_tabs(count, target, show_delete, delete_confirm, delete_action,
                     delete_tt, add_action, add_tt, tab_action_fn, tab_action_args,
                     tab_tt, exclusive_ctx=None):
    hbox:
        spacing 5
        box_wrap True
        box_wrap_spacing 3
        if show_delete:
            use cue_icon_btn(
                "xmark",
                Function(_cue.confirm_dialog.show, delete_confirm, delete_action),
                delete_tt,
                None,
            )
        if show_delete and exclusive_ctx is not None:
            # Only one-shots pass an exclusive_ctx -- the toggle lives in the
            # per-pool controls row for loops.
            $ _excl_on = bool(exclusive_ctx.get_active_pool().get("exclusive", {}).get("group"))
            $ _excl_bg = _cue_color_active if _excl_on else None
            $ _excl_tt = ("Disable exclusive playback" if _excl_on
                else "Exclusive playback: fade out SFX from previous scene then plays.")
            use cue_icon_btn(
                "layer-group",
                Function(exclusive_ctx.toggle_exclusive),
                tt=_excl_tt,
                bg=_excl_bg)
        textbutton "+ SFX Pool":
            style "cue_btn"
            text_style "cue_btn_text"
            action add_action
            tooltip add_tt
        for pi in range(count):
            $ _is_active = (pi == target)
            textbutton str(pi + 1):
                style "cue_btn"
                text_style "cue_btn_text"
                xsize 14
                background (_cue_color_active if _is_active else _cue_color_bg_btn)
                action _cue_make_tab_action(tab_action_fn, tab_action_args, pi)
                tooltip tab_tt

screen _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                            trigger_key, pool_index, folder_child_remove_fn,
                            folder_label, folder_children):
    vbox:
        spacing 2
        if folder_label is not None:
            # --- Virtual folder (e.g. preset-backed pool / video pool) ---
            $ _is_expanded = _cue.sfx_manager.expanded_file_refs.get(folder_label, False)
            $ _count = len(folder_children) if folder_children else 0
            hbox:
                spacing row_spacing
                use cue_icon_btn("xmark", Function(remove_fn, *remove_args), "Remove preset", None)
                use cue_icon_btn(
                    "play",
                    Function(_cue_preview_sfx, _cue_pick_file(folder_children or [""], False), preview_vol),
                    "Play random file from preset", None)
                use cue_txt_button(folder_label, Function(_cue.sfx_manager.toggle_file_ref_expand, folder_label))
                text "({} files)".format(_count) style "cue_help"

            if _is_expanded and folder_children:
                for _child in folder_children:
                    hbox:
                        spacing row_spacing
                        text "    " style "cue_txt"  # indent
                        if folder_child_remove_fn is not None:
                            use cue_icon_btn("xmark",
                                Function(folder_child_remove_fn, trigger_key, pool_index, 0, _child),
                                "Remove file from pool", None)
                        use cue_icon_btn("play", Function(_cue_preview_sfx, _child, preview_vol), None, None)
                        text _child style "cue_txt" color _cue_color_text_accent size 11

        for fi, f in enumerate(files):
            if f.endswith("/"):
                # --- Folder: expandable (matches SFX Library folder UI) ---
                $ _is_expanded = _cue.sfx_manager.expanded_file_refs.get(f, False)
                $ _count = len(_cue_resolve_files([f]))
                hbox:
                    spacing row_spacing
                    use cue_icon_btn("xmark", _cue_make_tab_action(remove_fn, remove_args, fi), "Remove folder", None)
                    use cue_icon_btn(
                        "play",
                        Function(_cue_preview_folder, f, preview_vol),
                        "Play random file from folder", None)
                    use cue_txt_button(f, Function(_cue.sfx_manager.toggle_file_ref_expand, f))
                    text "({} files)".format(_count) style "cue_help"

                if _is_expanded:
                    for _child in _cue_resolve_files([f]):
                        hbox:
                            spacing row_spacing
                            text "    " style "cue_txt"  # indent
                            if folder_child_remove_fn is not None:
                                use cue_icon_btn("xmark",
                                    Function(folder_child_remove_fn, trigger_key, pool_index, fi, _child),
                                    "Remove file from the folder", None)
                            use cue_icon_btn("play", Function(_cue_preview_sfx, _child, preview_vol), None, None)
                            $ _display = _child[len(f):]  # strip folder prefix
                            text _display style "cue_txt" color _cue_color_text_accent size 11
            else:
                # --- Regular file ---
                hbox:
                    spacing row_spacing
                    use cue_icon_btn("xmark", _cue_make_tab_action(remove_fn, remove_args, fi), None, None)
                    use cue_icon_btn("play", Function(_cue_preview_sfx, f, preview_vol), None, None)
                    text f style "cue_txt" color _cue_color_text_accent size 11

# Scrollable file list: only wraps in a viewport when content exceeds ~6 rows (120 px).
screen cue_file_list(files, remove_fn, remove_args, preview_vol, row_spacing,
                     trigger_key=None, pool_index=None, folder_child_remove_fn=None,
                     folder_label=None, folder_children=None):
    $ _rows = _cue.sfx_manager.count_file_list_rows(folder_label, folder_children, files)
    if _rows > 6:
        viewport:
            xfill True
            ymaximum 120
            mousewheel True
            scrollbars "vertical"
            style_group "cue"
            vscrollbar_unscrollable "hide"
            use _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                                    trigger_key, pool_index, folder_child_remove_fn,
                                    folder_label, folder_children)
    else:
        use _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                                trigger_key, pool_index, folder_child_remove_fn,
                                folder_label, folder_children)

# Section frame: styled frame + header, with transclude for child content.
style cue_section_hdr_btn is empty:
    background None
    hover_background _cue_color_bg_input
    padding (4, 2)
    xfill True
    hover_sound None
    activate_sound None

# Usage: use cue_section_frame("Title"):  ...children...
# Click the header to collapse/expand the section content.
# tt: optional string shown on a "?" icon left of the arrow (None to skip).
screen cue_section_frame(header_text, tt=None, icons=[]):
    $ _collapsed = _cue.collapsed_sections.get(header_text, False)
    $ _arrow_icon = "chevron-right" if _collapsed else "chevron-down"
    $ _arrow = _cue.icons.displayable_for(_arrow_icon)
    $ _question_icon = _cue.icons.displayable_for("question")
    frame:
        background _cue_color_bg_panel
        padding (4, 4)
        xfill True
        yminimum 0
        vbox:
            spacing 8
            xfill True
            button:
                style "cue_section_hdr_btn"
                action Function(_cue.toggle_section, header_text)
                hbox:
                    xfill True
                    text header_text style "cue_hdr"
                    null width 8
                    hbox:
                        xalign 1.0
                        spacing 10
                        yalign 0.5
                        for _icon in icons:
                            use cue_icon(
                                _icon["name"],
                                action=_icon.get("action", NullAction()),
                                tt=_icon.get("tt"),
                                size=_icon.get("size", 14),
                            )
                        if tt is not None:
                            use cue_icon("circle-question", tt=tt, size=14)
                        add _arrow yalign 0.5 alpha (0.7 if not _collapsed else 1.0)
            if not _collapsed:
                transclude

# Generic context section: shared by dialogue, image, and loop SFX.
# ctx: marker context with add_pool, remove_pool, clear, set_active,
#      get_active, remove_file (e.g. _cue.markers.dialogue)
# key: trigger key for volume/marker lookups
# subtitle: optional "Label: value" text below header (None to skip)
# subject: noun for confirm messages ("dialogue", "image", "file")
# btn_letter: "D", "I", or "L" for hint messages
# description: short line explaining when this SFX triggers (None to skip)
# Transclude: extra UI between pool label and volume row (shake toggle,
#             frequency selector, exclusive controls). Each transcluded
#             section resolves its own active pool via ctx.get_active_pool().
screen cue_context_section(section_title, ctx, key, subtitle, subject, btn_letter, description=None):
    $ _entry = _cue.markers.get(key, {})
    $ _pools = _entry.get("pools", [])
    $ _target = ctx.get_active()
    $ _target = max(0, min(_target, len(_pools) - 1)) if _pools else 0

    # sync back: clamps stale target after file switch so set_frequency/set_exclusive_* don't no-op
    $ ctx.set_active(_target)

    use cue_section_frame(section_title):
        if subtitle is not None:
            text subtitle style "cue_txt"
        if _entry:
            $ _entry.setdefault("volume", _cue.volume.VOL_DEFAULT)
            $ _master_vol = _entry.get("volume", _cue.volume.VOL_DEFAULT)
            use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _entry, key)
        if key:
            $ _excl_ctx = ctx if ctx.ONE_SHOT else None
            use cue_pool_tabs(len(_pools), _target, bool(_pools),
                "Delete all {} for the current {}?".format(section_title.lower(), subject),
                Function(ctx.clear), "Delete all {} for the current {}".format(section_title.lower(), subject),
                Function(ctx.add_pool), "Create a SFX pool",
                ctx.set_active, (), "Select {} target pool -- targets {} button".format(section_title, btn_letter),
                _excl_ctx)

        if _pools and 0 <= _target < len(_pools):
            $ _active_pool = _pools[_target]
            $ _r = _cue.markers.resolve_pool(_active_pool)
            $ _is_preset_pool = "preset" in _active_pool
            $ _active_pool.setdefault("volume", _r.volume)
            $ _active_vol = _r.volume
            $ _active_eff = _cue.volume.get_effective(_entry, key, pool_index=_target)
            if _is_preset_pool:
                $ _active_label = "Pool " + str(_target + 1) + " (Preset: " + _active_pool["preset"] + ")"
            else:
                $ _active_label = "Pool " + str(_target + 1) + " (" + str(len(_cue_resolve_files(_r.files))) + " files)"
            hbox:
                spacing 5
                box_wrap True
                box_wrap_spacing 3
                text _active_label style "cue_txt"
                null width 5
                use cue_icon_btn(
                    "floppy-disk",
                    Function(_cue.preset_dialog.open, key, _target),
                    "Save pool as a preset",
                    None,
                )
                if not ctx.ONE_SHOT:
                    $ _exclusive_on = bool(_r.exclusive.group)
                    $ _exclusive_bg = _cue_color_active if _exclusive_on else None
                    $ _excl_tt = ("Disable exclusive playback" if _exclusive_on
                        else ("Exclusive playback: waits for other Loop SFX to finish before playing, "
                              "blocking other Loop SFX until finished."))
                    use cue_icon_btn(
                        "layer-group",
                        Function(ctx.toggle_exclusive),
                        tt=_excl_tt,
                        bg=_exclusive_bg)
                use cue_icon_btn("xmark", Function(ctx.remove_pool, _target), "Delete pool", None)
                null width 5
                $ _vol_label = "Volume: {:.1f}".format(_active_vol)
                use cue_vol_row(_vol_label, _active_pool, key)

            transclude
            if _r.files:
                if _is_preset_pool:
                    # Preset-backed: render as expandable folder
                    use cue_file_list([], _cue.markers.detach_pool_at, (key, _target), _active_eff, 5,
                        trigger_key=key, pool_index=_target,
                        folder_label=_active_pool["preset"],
                        folder_children=_cue_resolve_files(_r.files),
                        folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                else:
                    use cue_file_list(_r.files, ctx.remove_file, (_target,), _active_eff, 5,
                        trigger_key=key, pool_index=_target,
                        folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
            else:
                if key and description is not None:
                    text description style "cue_txt"
                if key:
                    text ("Click the {} button in the SFX Library "
                        "to add files to this pool.").format(btn_letter) style "cue_txt"
        else:
            if key and description is not None:
                text description style "cue_txt"
            if key:
                text ("Click the {} button in the SFX Library to create a new pool "
                    "or add files to the active pool.").format(btn_letter) style "cue_txt"

# Toggle button: square-check icon when checked, square when unchecked.
# on_bg/on_hover/off_bg/off_hover override backgrounds per state (None = style default).
screen cue_checkbox(checked, label, action, tt_on=None, tt_off=None,
                    on_bg=None, on_hover=None, off_bg=None, off_hover=None,
                    enabled=True):
    $ _icon = _cue.icons.displayable_for("square-check" if checked else "square")
    button:
        style "cue_btn"
        sensitive enabled
        action action
        if checked:
            if on_bg:
                background on_bg
            if on_hover:
                hover_background on_hover
            if tt_on:
                tooltip tt_on
        else:
            if off_bg:
                background off_bg
            if off_hover:
                hover_background off_hover
            if tt_off or tt_on:
                tooltip (tt_on if tt_off is None else tt_off)
        hbox:
            spacing 5
            add _icon yalign 0.5
            text label style "cue_btn_text" yalign 0.5

# Radio button: solid circle icon tinted with the active color when
# selected, outline circle when not.
# Exclusivity within a group is enforced by the shared action target.
screen cue_radio_btn(checked, label, action, tt=None, enabled=True):
    $ _icon = _cue.icons.displayable_for("circle" if checked else "circle-outline")
    button:
        style "cue_btn"
        sensitive enabled
        action action
        if tt is not None:
            tooltip tt
        hbox:
            spacing 5
            add _icon yalign 0.5
            text label style "cue_btn_text" yalign 0.5

## Colors matching the Bulma "is-link" notification style — tweak to taste
screen notification(text, 
                    bg=_cue_color_bg_btn, 
                    dismissable=False,
                    text_color=_cue_color_text,
                    icon=None,
                    icon_color=None):
    $ _icon = _cue.icons.displayable_for(icon, icon_color)
    $ _icon_close = _cue.icons.displayable_for("circle-xmark")

    frame:
        background bg
        padding (28, 24, 56, 24)  # extra right padding to leave room for the close button
        xfill True

        hbox:
            spacing 12
            add _icon yalign 0.0

            text text:
                style "cue_txt"
                color text_color
                xfill True

        if dismissable:
            imagebutton:
                idle _icon_close
                hover _icon_close
                xalign 1.0
                yalign 0.0
                xoffset -12
                yoffset 12
                action Hide("notification")

# Popper anchor: wraps content and, on hover, captures the focused
# displayable's rect under `name`, so a `popper target "name"` elsewhere can
# position a popup against it.
#
# Basic usage (non-focusable content only):
#     use cue_popper_anchor("my_anchor", Function(_cue_my_hovered, arg)):
#         add SomeDisplayable()
#
# Then in "screen cue_overlay()", place the "popper target"
#
#    popper target "my_anchor":
#        hbox:
#            use cue_txt_button()
#
# CAVEAT: Ren'Py gives mouse focus to the INNERMOST focusable displayable,
# so a focusable button transcluded here (sensitive, with an action) steals
# focus and the anchor's `hovered` never fires -- the popper never shows.
# Anchor only plain text/add content, or use the workaround below.
#
# Workaround for wrapping a button: make the ANCHOR the interactive element
# (it has focus, so it receives the click) and transclude a non-focusable
# visual -- an insensitive button with a transparent background. The
# anchor's bg/hover_bg replace the button's own styling.
#
#     use cue_popper_anchor("spd_btn",
#             Function(_cue_spd_btn_hovered, _sp),
#             Function(_cue.speed_resolver.set_speed, _sp),
#             bg=_bg, hover_bg=_hover_bg):
#         use cue_txt_button(_label, NullAction(), bg="#00000000", sensitive=False)
screen cue_popper_anchor(name, hover_fn, action=NullAction(), bg=None, hover_bg=None):
    button:
        style "empty"
        padding (0, 0)
        action action
        hovered [Function(_cue_store_focus_rect, name), hover_fn]
        if bg is not None:
            background bg
        if hover_bg is not None:
            hover_background hover_bg
        transclude