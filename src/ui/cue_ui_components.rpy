###############################################################################
# Reusable Component Screens
###############################################################################



# Vertical divider: thin line for visual separation between controls.
screen cue_v_divider(height=14, width=2, color=None):
    fixed:
        ysize height
        xsize width
        add Solid(color or _cue_color_divider)

# Horizontal divider: thin full-width line.
screen cue_h_divider(color=None):
    add Solid(color or _cue_color_divider) ysize 1


# Volume row: label + - button + slider bar + + button
# dec_action/inc_action are pre-built Function() objects — call sites differ
# in which adjust function they use (master vs pool vs video-pool vs loop).
screen cue_vol_row(label_text, dec_action, entry_dict, inc_action):
    hbox:
        spacing 3
        text label_text style "cue_txt" size 11
        textbutton "-":
            style "cue_btn_icon"
            text_style "cue_btn_icon_text"
            xsize 18
            action dec_action
        bar:
            value DictValue(entry_dict, "volume", range=5.0)
            xsize 60
            ysize 14
            left_bar Solid(_cue_color_bar_active)
            right_bar Solid(_cue_color_bg_input)
            thumb Solid(_cue_color_text)
            hover_thumb Solid(_cue_color_text_white)
            changed _cue.volume.on_bar_changed
        textbutton "+":
            style "cue_btn_icon"
            text_style "cue_btn_icon_text"
            xsize 18
            action inc_action

# Icon button: tiny button with cue_btn_icon / cue_btn_icon_text styles.
# Most callers don't need xsize (style default is 14); pass an int to override.
# Pass tt=None to skip the tooltip.
screen cue_icon_button(text, action, tt=None, xsize=16, enabled=True):
    textbutton text:
        style "cue_btn_icon"
        text_style "cue_btn_icon_text"
        ysize 16
        if xsize is not None:
            xsize xsize
        if tt is not None:
            tooltip tt
        sensitive enabled
        action action

# Base text button: all textbuttons should use this so style/typography
# live in one place. Pass bg/tooltip/sensitive/xsize/ysize to override.
screen cue_txt_button(label, action, bg=None, tt=None, sensitive=True,
                       xsize=0, ysize=0):
    textbutton label:
        style "cue_btn"
        text_style "cue_btn_text"
        action action
        sensitive sensitive
        if bg is not None:
            background bg
        if tt is not None:
            tooltip tt
        if xsize > 0:
            xsize xsize
        if ysize > 0:
            ysize ysize

# Selectable textbutton: highlights when selected, dims when not.
# active_color overrides the highlight (default: _cue_color_active).
screen cue_select_btn(label, selected, action, tt=None, sensitive=True,
                       active_color=None):
    $ _bg = (active_color or _cue_color_active) if selected else _cue_color_bg_btn
    use cue_txt_button(label, action, bg=_bg, tt=tt, sensitive=sensitive)

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
screen cue_float_input(field_name, commit_action, display_text):
    default editing = False
    key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
    key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
    if editing:
        input:
            style "cue_input"
            value VariableInputValue(field_name)
            default True
            xsize 80
            ysize 16
    else:
        use cue_txt_button(display_text,
            SetLocalVariable("editing", True),
            ysize=16, tt="Click to edit. Press Enter to confirm.")

# Reusable time input: -- - [textbutton | input] + ++ with nudge buttons and Enter-to-commit.
# field_name: string for VariableInputValue (e.g. "_cue.markers.video.edit_text")
# commit_action: Function() called on Enter to confirm
# dec100/dec10/inc10/inc100_action: Function() called by nudge buttons
screen cue_time_input(field_name, commit_action, dec100_action, dec10_action,
                      inc10_action, inc100_action, display_text):
    default editing = False
    key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
    key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
    hbox:
        spacing 3
        use cue_icon_button("--", dec100_action, None, 22)
        use cue_icon_button("-", dec10_action)

        if editing:
            input:
                style "cue_input"
                value VariableInputValue(field_name)
                default True
        else:
            use cue_txt_button(display_text,
                [SetLocalVariable("editing", True), Function(_cue.markers.video.sync_text)],
                tt="Click to edit. Press Enter to confirm.")

        use cue_icon_button("+", inc10_action)
        use cue_icon_button("++", inc100_action, None, 22)

# Pool tab row: optional Delete button, + Pool button, numbered tabs [1][2]...
# tab_action_fn(tab_action_args..., pi) is called when tab pi is clicked.
# delete_xsize/tab_xsize override the default button width (pass None for default).
screen cue_pool_tabs(count, target, show_delete, delete_confirm, delete_action,
                     delete_tt, add_action, add_tt, tab_action_fn, tab_action_args,
                     tab_tt):
    hbox:
        spacing 5
        if show_delete:
            use cue_icon_button("✕", Function(_cue.confirm_dialog.show, delete_confirm, delete_action), delete_tt, None)
        textbutton "+ Pool":
            style "cue_btn"
            text_style "cue_btn_text"
            xsize 48
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

# Scrollable file list: ✕ remove + ▶ preview per row.
# remove_fn(remove_args..., fi) is called for row fi.
# preview_vol is the effective volume passed to _cue_preview_sfx.
# row_spacing controls horizontal gap in each row (5 for most, 2 for loop).
# folder_child_remove_fn(trigger_key, pool_index, fi, child_file) is called when
#   removing a single file from an expanded folder (detach operation).
#   Pass None to hide ✕ on folder children (e.g. for video pools).
# Inner vbox — extracted so cue_file_list can conditionally wrap it in a viewport.
screen _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                            trigger_key, pool_index, folder_child_remove_fn,
                            folder_label, folder_children):
    vbox:
        spacing 2
        if folder_label is not None:
            # --- Virtual folder (e.g. preset-backed pool / video pool) ---
            $ _is_expanded = _cue.file_tree.expanded_file_refs.get(folder_label, False)
            $ _count = len(folder_children) if folder_children else 0
            hbox:
                spacing row_spacing
                use cue_icon_button(("▾" if _is_expanded else "▸"),
                    Function(_cue.file_tree.toggle_file_ref_expand, folder_label), None, None)
                use cue_icon_button("✕", Function(remove_fn, *remove_args), "Remove preset", None)
                use cue_icon_button("▶", Function(_cue_preview_sfx, (folder_children or [""])[0], preview_vol), "Preview random file from preset", None)
                use cue_txt_button(folder_label, Function(_cue.file_tree.toggle_file_ref_expand, folder_label))
                text "({} files)".format(_count) style "cue_txt" color _cue_color_text_dim size 10
            if _is_expanded and folder_children:
                for _child in folder_children:
                    hbox:
                        spacing row_spacing
                        text "    " style "cue_txt"  # indent
                        if folder_child_remove_fn is not None:
                            use cue_icon_button("✕",
                                Function(folder_child_remove_fn, trigger_key, pool_index, 0, _child),
                                "Remove file from pool", None)
                        use cue_icon_button("▶", Function(_cue_preview_sfx, _child, preview_vol), None, None)
                        text _child style "cue_txt" color _cue_color_text_accent size 11
        for fi, f in enumerate(files):
            if f.endswith("/"):
                # --- Folder: expandable (matches SFX Library folder UI) ---
                $ _is_expanded = _cue.file_tree.expanded_file_refs.get(f, False)
                $ _count = len(_cue_resolve_files([f]))
                hbox:
                    spacing row_spacing
                    use cue_icon_button(("▾" if _is_expanded else "▸"),
                        Function(_cue.file_tree.toggle_file_ref_expand, f), None, None)
                    use cue_icon_button("✕", _cue_make_tab_action(remove_fn, remove_args, fi), "Remove folder", None)
                    use cue_icon_button("▶", Function(_cue_preview_sfx, (_cue_resolve_files([f]) or [""])[0], preview_vol), "Preview random file from folder", None)
                    use cue_txt_button(f, Function(_cue.file_tree.toggle_file_ref_expand, f))
                    text "({} files)".format(_count) style "cue_txt" color _cue_color_text_dim size 10
                if _is_expanded:
                    for _child in _cue_resolve_files([f]):
                        hbox:
                            spacing row_spacing
                            text "    " style "cue_txt"  # indent
                            if folder_child_remove_fn is not None:
                                use cue_icon_button("✕",
                                    Function(folder_child_remove_fn, trigger_key, pool_index, fi, _child),
                                    "Remove file from the folder", None)
                            use cue_icon_button("▶", Function(_cue_preview_sfx, _child, preview_vol), None, None)
                            $ _display = _child[len(f):]  # strip folder prefix
                            text _display style "cue_txt" color _cue_color_text_accent size 11
            else:
                # --- Regular file ---
                hbox:
                    spacing row_spacing
                    use cue_icon_button("✕", _cue_make_tab_action(remove_fn, remove_args, fi), None, None)
                    use cue_icon_button("▶", Function(_cue_preview_sfx, f, preview_vol), None, None)
                    text f style "cue_txt" color _cue_color_text_accent size 11

# Scrollable file list: only wraps in a viewport when content exceeds ~6 rows (120 px).
screen cue_file_list(files, remove_fn, remove_args, preview_vol, row_spacing,
                     trigger_key=None, pool_index=None, folder_child_remove_fn=None,
                     folder_label=None, folder_children=None):
    $ _rows = _cue_count_file_list_rows(folder_label, folder_children, files)
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
screen cue_section_frame(header_text):
    $ _collapsed = _cue.file_tree.collapsed_sections.get(header_text, False)
    $ _arrow = "▸" if _collapsed else "▾"  # ▸ collapsed, ▾ expanded
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
                action Function(_cue.file_tree.toggle_section, header_text)
                hbox:
                    xfill True
                    text header_text style "cue_hdr"
                    null width 8
                    text _arrow style "cue_help" xalign 1.0
            if not _collapsed:
                transclude

# Generic context section: shared by dialogue, image, and loop SFX.
# ctx: marker context with add_pool, remove_pool, clear, set_active,
#      get_active, remove_file (e.g. _cue.markers.dialogue)
# vol_key: trigger key for volume/marker lookups
# subtitle: optional "Label: value" text below header (None to skip)
# subject: noun for confirm messages ("dialogue", "image", "file")
# btn_letter: "D", "I", or "L" for hint messages
# description: short line explaining when this SFX triggers (None to skip)
# Transclude: extra UI between pool label and volume row (shake toggle,
#             frequency selector). Reads _cue._pool_ui["pool"].
screen cue_context_section(section_title, ctx, vol_key, subtitle, subject, btn_letter, description=None):
    $ _entry = _cue.markers.get(vol_key, {})
    $ _pools = _entry.get("pools", [])
    $ _target = ctx.get_active()
    $ _target = max(0, min(_target, len(_pools) - 1)) if _pools else 0
    use cue_section_frame(section_title):
        if subtitle is not None:
            use cue_h_divider()
            vbox:
                spacing 5
                text subtitle style "cue_txt"
        if _entry:
            $ _entry.setdefault("volume", 1.0)
            $ _master_vol = _entry.get("volume", 1.0)
            $ _dec = Function(_cue.volume.adjust_master, vol_key, -0.1)
            $ _inc = Function(_cue.volume.adjust_master, vol_key, 0.1)
            use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _dec, _entry, _inc)
        use cue_pool_tabs(len(_pools), _target, bool(_pools),
            "Delete all {} for the current {}?".format(section_title.lower(), subject),
            Function(ctx.clear), "Delete all {} for the current {}".format(section_title.lower(), subject),
            Function(ctx.add_pool), "Create a SFX pool",
            ctx.set_active, (), "Select {} target pool — targets {} button".format(section_title, btn_letter))

        if _pools and 0 <= _target < len(_pools):
            $ _active_pool = _pools[_target]
            $ _r = _cue.markers.resolve_pool(_active_pool)
            $ _is_preset_pool = "preset" in _active_pool
            $ _active_pool.setdefault("volume", _r.volume)
            $ _active_vol = _r.volume
            $ _active_eff = _cue.volume.get_effective(_entry, vol_key, pool_index=_target)
            if _is_preset_pool:
                $ _active_label = "Pool " + str(_target + 1) + " (Preset: " + _active_pool["preset"] + ")"
            else:
                $ _active_label = "Pool " + str(_target + 1) + " (" + str(len(_cue_resolve_files(_r.files))) + " files)"
            $ _cue._pool_ui = {"pool": _active_pool, "files": _r.files, "target": _target, "freq": _r.frequency, "no_overlap": _r.no_overlap}
            hbox:
                spacing 5
                text _active_label style "cue_txt"
                null width 5
                use cue_icon_button("💾", Function(_cue.preset_dialog.open, vol_key, _target), "Save pool as a preset", None)
                use cue_icon_button("✕", Function(ctx.remove_pool, _target), "Delete pool", None)
                $ _dec = Function(_cue.volume.adjust, vol_key, -0.1, _target)
                $ _inc = Function(_cue.volume.adjust, vol_key, 0.1, _target)
                null width 5
                if abs(_active_vol - _active_eff) > 0.01:
                    $ _vol_label = "Volume: {:.1f} ({:.1f} total)".format(_active_vol, _active_eff)
                else:
                    $ _vol_label = "Volume: {:.1f}".format(_active_vol)
                use cue_vol_row(_vol_label, _dec, _active_pool, _inc)

            transclude
            if _r.files:
                if _is_preset_pool:
                    # Preset-backed: render as expandable folder
                    use cue_file_list([], _cue_detach_pool_at, (vol_key, _target), _active_eff, 5,
                        trigger_key=vol_key, pool_index=_target,
                        folder_label=_active_pool["preset"],
                        folder_children=_cue_resolve_files(_r.files),
                        folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                else:
                    use cue_file_list(_r.files, ctx.remove_file, (_target,), _active_eff, 5,
                        trigger_key=vol_key, pool_index=_target,
                        folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
            else:
                if description is not None:
                    text description style "cue_help"
                text "Click the {} button in the SFX Library to add files to this pool.".format(btn_letter) style "cue_help"
        else:
            if description is not None:
                text description style "cue_help"
            text "Click the {} button in the SFX Library to create a new pool or add files to the active pool.".format(btn_letter) style "cue_help"

# Toggle textbutton: ☑ label when checked, ☐ when unchecked.
# on_bg/on_hover/off_bg/off_hover override backgrounds per state (None = style default).
screen cue_toggle_btn(checked, label, action, tt_on=None, tt_off=None,
                       on_bg=None, on_hover=None, off_bg=None, off_hover=None,
                       enabled=True):
    if checked:
        textbutton "☑ " + label:
            style "cue_btn"
            text_style "cue_btn_text"
            sensitive enabled
            if on_bg:
                background on_bg
            if on_hover:
                hover_background on_hover
            action action
            if tt_on:
                tooltip tt_on
    else:
        textbutton "☐ " + label:
            style "cue_btn"
            text_style "cue_btn_text"
            sensitive enabled
            if off_bg:
                background off_bg
            if off_hover:
                hover_background off_hover
            action action
            if tt_off or tt_on:
                tooltip (tt_on if tt_off is None else tt_off)

# Radio textbutton: ● label when selected, ○ when not.
# Exclusivity within a group is enforced by the shared action target.
screen cue_radio_btn(checked, label, action, tt=None, enabled=True):
    if checked:
        $ _label = "{color=" + _cue_color_active + "}●{/color} " + label
        textbutton _label:
            style "cue_btn"
            text_style "cue_btn_text"
            sensitive enabled
            action action
            if tt is not None:
                tooltip tt
    else:
        textbutton "○ " + label:
            style "cue_btn"
            text_style "cue_btn_text"
            sensitive enabled
            action action
            if tt is not None:
                tooltip tt

