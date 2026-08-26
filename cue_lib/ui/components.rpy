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

        enter_action (optional) is run via renpy.run() when the focused
        input commits on Enter: the input's own input_enter path calls
        value.enter(), so the input can commit/exit editing without any
        `key` statement in the tree.  That keeps the editing frame
        single-child — a multi-child frame gets an implicit Fixed that
        claims all available height.
        """
        def __init__(self, dotted_path, default=True, enter_action=None):
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
            self.enter_action = enter_action

        def enter(self):
            if self.enter_action is not None:
                renpy.run(self.enter_action)
                renpy.restart_interaction()
            return FieldInputValue.enter(self)

    class _CueVolumeValue(DictValue):
        """A DictValue that persists the owning marker after the bar changes.

        DictValue writes ``dict[key]`` through its changed() hook; we save the
        marker (passed in as marker_key) on top of that via the deferred save
        queue (marker_queue_save) so a slider drag coalesces into one disk
        write. When ``multi_setter`` is given, changed() also fans the write
        out to every other selected pool (the video SFX multi-select volume
        path); the active pool is handled by DictValue's own write."""
        # FieldEquality over equality_fields gates Ren'Py's displayable-reuse
        # cache: a bar whose new value equals the cached one reuses it. Without
        # _multi_setter, a value built while multi_setter was None (rendered
        # before entering multi-select) compares equal to a method-carrying one,
        # so the None instance is reused and the fan-out is silently dropped.
        equality_fields = tuple(DictValue.equality_fields) + ('_multi_setter',)

        def __init__(self, entry_dict, field, marker_key, multi_setter=None, **kwargs):
            DictValue.__init__(self, entry_dict, field, **kwargs)
            self._marker_key = marker_key
            self._multi_setter = multi_setter

        def changed(self, value):
            super(_CueVolumeValue, self).changed(value)
            if self._multi_setter is not None:
                self._multi_setter(value)
            _cue.volume.marker_queue_save(self._marker_key)

    def _cue_split_dotted_path(dotted_path):
        # type: (str) -> tuple
        """Split "_cue.foo.bar" into (obj, "bar") like _CueFieldValue."""
        _dot = dotted_path.rfind(".")
        if _dot == -1:
            return (renpy.store, dotted_path)
        return (renpy.python.py_eval(dotted_path[:_dot]), dotted_path[_dot + 1:])

    def _cue_read_clipboard():
        # type: () -> str
        """Return the system clipboard text, or "" when unavailable or empty."""
        try:
            import pygame
            _raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if _raw:
                return _raw.decode("utf-8", "replace")
        except Exception:
            _cue_log("CUE-CLIPBOARD: could not read clipboard")
        return ""

    def _cue_paste_into_field(dotted_path):
        # type: (str) -> None
        """Paste clipboard text into the field addressed by dotted_path."""
        _clip = _cue_read_clipboard()
        if not _clip:
            return
        _pair = _cue_split_dotted_path(dotted_path)
        setattr(_pair[0], _pair[1], _clip)
        renpy.restart_interaction()



# Vertical divider: thin line for visual separation between controls.
screen cue_v_divider(height=14, width=2, color=None):
    style_group "cue"

    fixed:
        ysize height
        xsize width
        add Solid(color or _cue_color_divider)

# Horizontal divider: thin full-width line.
screen cue_h_divider(color=None):
    style_group "cue"

    add Solid(color or _cue_color_divider) ysize 1


# Volume row: label + slider bar. Pass multi_setter (a callable taking the
# new volume) to write to every selected pool during a video multi-select.
screen cue_vol_row(label_text, entry_dict, key, multi_setter=None):
    style_group "cue"

    hbox:
        spacing 3
        etext label_text size 11
        bar:
            value _CueVolumeValue(entry_dict, "volume", key, multi_setter=multi_setter, range=_cue.volume.VOL_MAX)
            xsize 60
            ysize 14
            left_bar Solid(_cue_color_bar_active)
            right_bar Solid(_cue_color_bg_input)
            thumb Solid(_cue_color_text)
            hover_thumb Solid(_cue_color_text_white)

# Icon button: tiny button with cue_icon_button / cue_icon_button_text styles.
# `label` is an icon name ("clipboard", "xmark") or plain text ("-", "V").
# Names mapped in CueIconManager render as PNG images, everything
# else falls back to text.
screen cue_icon_btn(label, action=NullAction(), tt=None, xsize=16, enabled=True, bg=None, icon_color=None,
                    on_hover=None, on_unhover=None):
    style_group "cue"

    $ _icon = _cue.icons.displayable_for(label, icon_color) if _cue.icons is not None else None
    if _icon is not None:
        button:
            style "cue_icon_button"
            if xsize is not None:
                xsize xsize
            if tt is not None:
                tooltip tt
            sensitive enabled
            action action
            if on_hover is not None:
                hovered on_hover
            if on_unhover is not None:
                unhovered on_unhover
            if bg is not None:
                background bg
            if enabled:
                add _icon xalign 0.5 yalign 0.5
            else:
                add _icon xalign 0.5 yalign 0.5 alpha 0.35
    else:
        textbutton label:
            style "cue_icon_button"
            text_style "cue_icon_button_text"
            if xsize is not None:
                xsize xsize
            if tt is not None:
                tooltip tt
            sensitive enabled
            action action
            if on_hover is not None:
                hovered on_hover
            if on_unhover is not None:
                unhovered on_unhover
            if bg is not None:
                background bg

transform cue_icon_fade:
    alpha 0.5
    on hover:
        linear 0.1 alpha 1.0
    on idle:
        linear 0.1 alpha 0.5

screen cue_icon(label, action=NullAction(), tt=None, icon_color=None, size=12,
                on_hover=None, on_unhover=None, fade=True, yoffset=1):
    style_group "cue"

    $ _icon = _cue.icons.displayable_for(label, icon_color, size)
    button:
        style "empty"
        xalign 0.5
        yalign 0.5
        yoffset yoffset
        padding (0, 0)
        background None
        hover_background None
        action action
        if on_hover is not None:
            hovered on_hover
        if on_unhover is not None:
            unhovered on_unhover
        if tt is not None:
            tooltip tt
        if fade:
            add _icon at cue_icon_fade
        else:
            add _icon

# Base text button: all textbuttons should use this so style/typography
# live in one place. Pass bg/tooltip/sensitive/xsize/ysize to override.
screen cue_txt_button(label, action, bg=None, hover_bg=None, tt=None,
                    sensitive=True, xsize=0, ysize=0, xminimum=0,
                    hovered=None, unhovered=None):
    style_group "cue"

    textbutton _cue_escape_text(label):
        action action
        sensitive sensitive
        if bg is not None:
            background bg
        if hover_bg is not None:
            hover_background hover_bg
        if tt is not None:
            tooltip tt
        if hovered is not None:
            hovered hovered
        if unhovered is not None:
            unhovered unhovered
        if xsize is not None and xsize > 0:
            xsize xsize
        if xminimum is not None and xminimum > 0:
            xminimum xminimum
        if ysize is not None and ysize > 0:
            ysize ysize

# Open-folder button: folder icon + label that opens dir_path in the OS file
# explorer.  Used by the empty Music/SFX library states so users can jump
# straight to the drop-folder.
screen cue_open_in_explorer_btn(dir_path, label):
    style_group "cue"

    $ _folder_icon = _cue.icons.displayable_for("folder-open") if _cue.icons is not None else None
    button:
        style "cue_button"
        action Function(_cue_open_in_os_file_explorer, dir_path)
        hbox:
            spacing 4
            if _folder_icon is not None:
                add _folder_icon yalign 0.5
            etext label style "cue_button_text"

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
    style_group "cue"

    default editing = False
    hbox:
        spacing 3
        if dec_action is not None:
            use cue_icon_btn("-", dec_action)

        if editing:
            key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
            key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
            input:
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
    style_group "cue"

    default editing = False
    hbox:
        spacing 3
        #use cue_icon_btn("--", dec100_action, None, 22)
        use cue_icon_btn("-", dec10_action)

        if editing:
            key "K_RETURN" action [commit_action, SetLocalVariable("editing", False)]
            key "K_KP_ENTER" action [commit_action, SetLocalVariable("editing", False)]
            input:
                value _CueFieldValue(field_name)
                default True
        else:
            use cue_txt_button(display_text,
                [SetLocalVariable("editing", True), Function(_cue.markers.video.sync_text)],
                tt="Click to edit. Press Enter to confirm.")

        use cue_icon_btn("+", inc10_action)
        #use cue_icon_btn("++", inc100_action, None, 22)

screen cue_text_input(field_name, commit_action, display_text, xsize=200,
                      clear_action=None, hint_icon="keyboard",
                      paste_btn=False, commit_on_enter=True):
    style_group "cue"

    $ ysize = 16
    # Each input derives its own editing flag from the shared _cue.editing_input
    # (holds this field's dotted path while it's being edited, "" = none), so
    # only one field is in edit mode at a time.
    $ editing = (_cue.editing_input == field_name)
    $ _start_edit = SetField(_cue, "editing_input", field_name)
    $ _commit = [commit_action, SetField(_cue, "editing_input", "")]
    $ _exit_edit = SetField(_cue, "editing_input", "")

    if commit_on_enter:
        $ _enter = _commit
    else:
        $ _enter = _exit_edit

    $ _pair = _cue_split_dotted_path(field_name)
    $ _obj = _pair[0]
    $ _field = _pair[1]
    $ _has_text = bool(getattr(_obj, _field, ""))
    if clear_action is not None:
        $ _clear_core = clear_action
    else:
        # Default clear: empty the field value.
        $ _clear_core = SetField(_obj, _field, "")
    $ _clear = [_clear_core, _exit_edit]


    hbox:
        spacing 0
        yalign 0.5

        if editing:
            use cue_icon_btn("xmark", _clear, "Clear", bg=_cue_color_bg_input)
        elif paste_btn:
            use cue_icon_btn(
                "clipboard",
                [_start_edit, Function(_cue_paste_into_field, field_name)],
                "Paste from clipboard",
                bg=_cue_color_bg_input,
            )
        elif hint_icon:
            use cue_icon_btn(hint_icon, enabled=False, bg=_cue_color_bg_input)
        if editing:
            # Single child only: a second child makes the frame wrap its
            # contents in a Fixed, which claims all available height.
            # Enter is handled by the value's enter_action, not a key.
            frame:
                style "empty"
                background _cue_color_bg_input
                padding (6, 0)
                xsize xsize
                yminimum ysize
                input:
                    value _CueFieldValue(field_name, enter_action=_enter)
                    default True
                    copypaste True
                    xsize xsize
                    yminimum ysize
                    yoffset 1
        else:
            textbutton _cue_escape_text(display_text):
                action _start_edit
                text_xalign 0
                background _cue_color_bg_input
                hover_background _cue_color_bg_input_hover
                padding (6, 0)
                xsize xsize
                tooltip ("Click to type. Enter to confirm."
                    if commit_on_enter else "Click to type. Commit with the button.")

screen cue_search_bar(field_path, manager, hint="Search"):
    style_group "cue"

    $ _q = manager.search_query
    $ _label = _q if _q.strip() else hint
    vbox:
        spacing 4
        use cue_text_input(field_path, Function(manager.rebuild_tree), _label,
            clear_action=Function(manager.clear_search),
            hint_icon="magnifying-glass")

        if manager.search_truncated:
            etext "{} more results.  Narrow your search".format(manager.search_truncated) style "cue_help"

# Pool tab row: optional Delete button, + Pool button, numbered tabs [1][2]...
# tab_action_fn(tab_action_args..., pi) is called when tab pi is clicked.
# delete_xsize/tab_xsize override the default button width (pass None for default).
screen cue_pool_tabs(count, target, show_delete, delete_confirm, delete_action,
                     delete_tt, add_action, add_tt, tab_action_fn, tab_action_args=(),
                     tab_tt=None, exclusive_ctx=None, selected_tabs=()):
    style_group "cue"

    hbox:
        spacing 5
        box_wrap True
        box_wrap_spacing 3
        if show_delete:
            $ _delete_tt = delete_tt + CUE_HELP_SHIFT_SKIP_DELETE
            use cue_icon_btn(
                "xmark",
                Function(_cue.dialogs.confirm.show_or_run, delete_confirm, delete_action),
                _delete_tt,
            )
        if show_delete and exclusive_ctx is not None:
            # Only one-shots pass an exclusive_ctx -- the toggle lives in the
            # per-pool controls row for loops.
            $ _excl_on = bool(exclusive_ctx.get_active_pool().get("exclusive", {}).get("group"))
            $ _excl_bg = _cue_color_active if _excl_on else None
            $ _excl_tt = ("Disable exclusive playback" if _excl_on
                else "Exclusive playback: fade out SFX from previous scene then play.")
            use cue_icon_btn(
                "layer-group",
                Function(exclusive_ctx.toggle_exclusive),
                tt=_excl_tt,
                bg=_excl_bg)
        textbutton "+ SFX Pool":
            action add_action
            tooltip add_tt
        for pi in range(count):
            $ _is_active = (pi == target)
            # Selected-but-not-active tabs get a blue highlight so the
            # multi-select group reads at a glance (active green wins).
            $ _is_selected = (pi in selected_tabs)
            $ _tab_bg = (_cue_color_active if _is_active
                         else (_cue_color_selected_alt if _is_selected else _cue_color_bg_btn))
            $ _tab_hover = (_cue_color_active_hover if _is_active
                            else (_cue_color_selected_alt_hover if _is_selected else _cue_color_bg_btn_hover))
            textbutton str(pi + 1):
                xsize 14
                background _tab_bg
                hover_background _tab_hover
                action _cue_make_tab_action(tab_action_fn, tab_action_args, pi)
                if tab_tt is not None:
                    tooltip tab_tt

# Reusable tree: renders row dicts produced by the audio-tree managers'
# tree_rows() builders (one dict per visible row).  Folder rows expand via a
# toggle button; file rows are labels with an optional gap + warn icon.  Rows
# carry buttons in data, so the SFX and music trees share this renderer 1:1.
# Optional data fields (all default-off, stage-1 output unchanged):
#   size    -- file label font size (section rows use 11; tree rows default)
#   hover_buttons -- folder rows render them trailing the toggle at spacing 0
#   v_gap   -- null height after the row (2px spacers in section builders)
#   explorer -- action rows render cue_open_in_explorer_btn(dir, label)
#   color   -- help rows render etext in this color (error text)
screen cue_tree_rows(rows):
    style_group "cue"

    default _hovered_key = None
    vbox:
        spacing 2
        for _row in rows:
            hbox:
                spacing 2
                if _row["depth"] > 0:
                    etext _cue_indent * _row["depth"]
                for _b in _row.get("buttons", []):
                    use cue_icon_btn(
                        _b["icon"],
                        _b["action"],
                        tt=_b.get("tt"),
                        enabled=_b.get("enabled", True),
                        bg=_b.get("bg"),
                        on_hover=SetLocalVariable("_hovered_key", _row["key"]),
                        on_unhover=SetLocalVariable("_hovered_key", None))
                if _row["type"] == "folder":
                    hbox:
                        spacing 0
                        use cue_txt_button(
                            _row["label"],
                            _row["toggle"],
                            hovered=SetLocalVariable("_hovered_key", _row["key"]),
                            unhovered=SetLocalVariable("_hovered_key", None))
                        for _hb in _row.get("hover_buttons", []):
                            if _hovered_key == _row["key"]:
                                use cue_icon_btn(
                                    _hb["icon"],
                                    _hb["action"],
                                    tt=_hb.get("tt"),
                                    enabled=_hb.get("enabled", True),
                                    bg=_hb.get("bg"),
                                    on_hover=SetLocalVariable("_hovered_key", _row["key"]),
                                    on_unhover=SetLocalVariable("_hovered_key", None))
                elif _row["type"] == "file":
                    null width _row.get("gap", 1)
                    if _row.get("size"):
                        etext _row["label"] color _cue_color_text_accent size _row["size"]
                    else:
                        etext _row["label"] color _cue_color_text_accent
                    if _row.get("warn"):
                        use cue_icon(
                            "triangle-exclamation",
                            tt=("Invalid file: " + _row["warn"]),
                            icon_color=_cue_color_warn)
                elif _row["type"] == "action":
                    if _row.get("explorer"):
                        use cue_open_in_explorer_btn(_row["explorer"], _row["label"])
                    else:
                        use cue_txt_button(_row["label"], _row["action"], tt=_row.get("tt"))
                elif _row["type"] == "help":
                    if _row.get("plain"):
                        if _row.get("color"):
                            etext _row["label"] color _row["color"]
                        else:
                            etext _row["label"]
                    elif _row.get("color"):
                        etext _row["label"] style "cue_help" color _row["color"]
                    else:
                        etext _row["label"] style "cue_help"
            if _row.get("v_gap"):
                null height _row["v_gap"]

screen _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                            marker_key, pool_index, folder_child_remove_fn,
                            folder_label, folder_children):
    style_group "cue"

    vbox:
        spacing 2
        if folder_label is not None:
            # --- Virtual folder (e.g. preset-backed pool / video pool) ---
            $ _is_expanded = _cue.sfx.library.expanded_file_refs.get(folder_label, False)
            $ _count = len(folder_children) if folder_children else 0
            hbox:
                spacing row_spacing
                use cue_icon_btn("xmark", Function(remove_fn, *remove_args), "Remove preset")
                use cue_icon_btn(
                    "play",
                    Function(_cue.sfx.preview_sfx, _cue_pick_file(folder_children or [""], False), preview_vol),
                    "Play random file from preset")
                use cue_txt_button(
                    folder_label,
                    Function(_cue.sfx.library.toggle_file_ref_expand, folder_label))
                etext "({} files)".format(_count) style "cue_help"

            if _is_expanded and folder_children:
                for _child in folder_children:
                    hbox:
                        spacing row_spacing
                        etext _cue_indent
                        if folder_child_remove_fn is not None:
                            use cue_icon_btn("xmark",
                                Function(folder_child_remove_fn, marker_key, pool_index, 0, _child),
                                "Remove file from pool")
                        use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, _child, preview_vol))
                        etext _child color _cue_color_text_accent size 11

        for fi, f in enumerate(files):
            if f.endswith("/"):
                # --- Folder: expandable (matches SFX Library folder UI) ---
                $ _is_expanded = _cue.sfx.library.expanded_file_refs.get(f, False)
                $ _count = len(_cue_resolve_files([f]))
                hbox:
                    spacing row_spacing
                    use cue_icon_btn("xmark", _cue_make_tab_action(remove_fn, remove_args, fi), "Remove folder")
                    use cue_icon_btn(
                        "play",
                        Function(_cue.sfx.preview_folder, f, preview_vol),
                        "Play random file from folder")
                    use cue_txt_button(f, Function(_cue.sfx.library.toggle_file_ref_expand, f))
                    etext "({} files)".format(_count) style "cue_help"

                if _is_expanded:
                    for _child in _cue_resolve_files([f]):
                        hbox:
                            spacing row_spacing
                            etext _cue_indent  # indent
                            if folder_child_remove_fn is not None:
                                use cue_icon_btn("xmark",
                                    Function(folder_child_remove_fn, marker_key, pool_index, fi, _child),
                                    "Remove file from the folder")
                            use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, _child, preview_vol))
                            $ _display = _child[len(f):]  # strip folder prefix
                            etext _display color _cue_color_text_accent size 11
            else:
                # --- Regular file ---
                hbox:
                    spacing row_spacing
                    use cue_icon_btn("xmark", _cue_make_tab_action(remove_fn, remove_args, fi))
                    use cue_icon_btn("play", Function(_cue.sfx.preview_sfx, f, preview_vol))
                    etext f color _cue_color_text_accent size 11

# Scrollable file list: only wraps in a viewport when content exceeds ~6 rows (120 px).
screen cue_file_list(files, remove_fn, remove_args, preview_vol, row_spacing=2,
                     marker_key=None, pool_index=None, folder_child_remove_fn=None,
                     folder_label=None, folder_children=None):
    style_group "cue"

    $ _rows = _cue.sfx.library.count_file_list_rows(folder_label, folder_children, files)
    if _rows > 6:
        viewport:
            xfill True
            ymaximum 120
            mousewheel True
            scrollbars "vertical"
            vscrollbar_unscrollable "hide"
            use _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                                    marker_key, pool_index, folder_child_remove_fn,
                                    folder_label, folder_children)
    else:
        use _cue_file_list_vbox(files, remove_fn, remove_args, preview_vol, row_spacing,
                                marker_key, pool_index, folder_child_remove_fn,
                                folder_label, folder_children)

# Collapsible replay list for an import row / preview banner.  Mirrors the
# file/folder UI: a toggle button labeled with the count, then per-replay
# rows with a Play action.  Play enters preview first (see
# CueImportManager.play_replay) and jumps straight to that replay.
screen cue_replay_toggle(_imp_key, _section):
    style_group "cue"

    $ _replays = _cue.importer.replays_for(_imp_key)
    if _replays:
        $ _is_open = _cue.importer.is_replays_expanded(_section, _imp_key)
        $ _caret = _cue.icons.displayable_for(
            "caret-down" if _is_open else "caret-right")
        button:
            style "cue_button"
            action Function(_cue.importer.toggle_replays, _section, _imp_key)
            hbox:
                spacing 4
                add _caret yalign 0.5
                etext "Replays ({})".format(len(_replays)) style "cue_button_text"


screen cue_replay_children(_imp_key, _section):
    # Expanded replay rows for a section+import.  Sits below the action-button
    # row so opening it pushes content down instead of relaying out the row.
    style_group "cue"

    $ _replays = _cue.importer.replays_for(_imp_key)
    if _replays and _cue.importer.is_replays_expanded(_section, _imp_key):
        for _r in _replays:
            hbox:
                spacing 6
                etext _cue_indent  # indent to match folder child rows
                use cue_icon_btn(
                    "play",
                    Function(_cue.importer.play_replay, _imp_key, _r["replay"]),
                    "Preview import and start replay",
                    enabled=_cue.importer.can_preview(_imp_key))
                etext _r["replay"] color _cue_color_text_accent size 11
                etext "{} marker(s)".format(_r["marker_count"]) color _cue_color_text_muted size 11

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
    style_group "cue"

    $ _collapsed = _cue.collapsed_sections.get(header_text, False)
    $ _arrow_icon = "chevron-right" if _collapsed else "chevron-down"
    $ _arrow = _cue.icons.displayable_for(_arrow_icon)
    $ _question_icon = _cue.icons.displayable_for("question")
    frame:
        yminimum 0
        vbox:
            spacing 8
            xfill True
            button:
                style "cue_section_hdr_btn"
                action Function(_cue.toggle_section, header_text)
                hbox:
                    xfill True
                    etext header_text style "cue_hdr"
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
                frame:
                    background None 
                    padding (4, 0) # match header xpadding added by cue_section_hdr_btn
                    vbox:
                        spacing 8
                        xfill True
                        transclude

# Read-only file list for a pool hooked to an intensity level: resolves the
# level's files/folders and shows them with a preview button only -- no
# remove (the files live in the level, not the pool; drop the hook by
# deleting the pool).  Level folders carry a hint bar + tooltip naming the
# hook.  Shared by Loop SFX (cue_context_section) and Video SFX.
screen cue_igroup_pool_files(igroup, ilevel_id, preview_vol):
    style_group "cue"

    $ _ilevel_files = _cue.intensity.level_files_by_id(igroup, ilevel_id or 0) or []
    if _ilevel_files:
        $ _rows = _cue.sfx.library.count_file_list_rows(None, None, _ilevel_files)
        if _rows > 6:
            viewport:
                xfill True
                ymaximum 120
                mousewheel True
                scrollbars "vertical"
                vscrollbar_unscrollable "hide"
                use _cue_igroup_pool_files_vbox(_ilevel_files, preview_vol, igroup, ilevel_id)
        else:
            use _cue_igroup_pool_files_vbox(_ilevel_files, preview_vol, igroup, ilevel_id)
    else:
        etext "This level has no files yet."


screen _cue_igroup_pool_files_vbox(_ilevel_files, preview_vol, igroup, ilevel_id):
    style_group "cue"

    # The hint bar marks a folder as an intensity-hooked level folder. Show it
    # only while intensity is on AND "Swap SFX by level" is on (the current
    # video's toggles) -- otherwise the pool stays on its level folder and the
    # hint is a lie.
    $ _flags = _cue.intensity.flags_from_entry(
        _cue.markers.get(_cue_create_vid_key(_cue.current_file) if _cue.current_file else "", {}))
    # Tooltip names the hook; the note pairs with the orange hint bar, appended
    # only when the bar is actually shown (matches the marker-timeline tip).
    $ _hook_tt = "Attached to intensity group '{}'.".format(igroup)
    if _flags.enabled and _flags.sfx_levels:
        $ _hook_tt += "\n[" + CUE_INTENSITY_NOTE + "]"
    vbox:
        spacing 2
        for _f in _ilevel_files:
            if _f.endswith("/"):
                $ _is_expanded = _cue.sfx.library.expanded_file_refs.get(_f, False)
                $ _count = len(_cue_resolve_files([_f]))
                hbox:
                    spacing 2
                    use cue_icon_btn(
                        "play",
                        Function(_cue.sfx.preview_folder, _f, preview_vol),
                        "Play random file from folder")
                    hbox:
                        spacing 0
                        # Intensity hint: a left bar marks this folder as a
                        # level folder; the tooltip names the hook.
                        if _flags.enabled and _flags.sfx_levels:
                            add Solid(CUE_INTENSITY_HINT_COLOR) xsize 2 ysize 14 yalign 0.5
                        use cue_txt_button(
                            _f,
                            Function(_cue.sfx.library.toggle_file_ref_expand, _f),
                            tt=_hook_tt)
                    etext "({} files)".format(_count) style "cue_help"
                if _is_expanded:
                    for _child in _cue_resolve_files([_f]):
                        hbox:
                            spacing 2
                            etext _cue_indent  # indent
                            use cue_icon_btn(
                                "play",
                                Function(_cue.sfx.preview_sfx, _child, preview_vol),
                                "Preview audio")
                            $ _display = _child[len(_f):]  # strip folder prefix
                            etext _display color _cue_color_text_accent size 11
            else:
                hbox:
                    spacing 2
                    use cue_icon_btn(
                        "play",
                        Function(_cue.sfx.preview_sfx, _f, preview_vol),
                        "Preview audio")
                    etext _f color _cue_color_text_accent size 11

# Generic context section: shared by dialogue, image, and loop SFX.
# ctx: marker context with add_pool, remove_pool, clear, set_active_index,
#      get_active_index, remove_file (e.g. _cue.markers.dialogue)
# key: trigger key for volume/marker lookups
# subtitle: optional "Label: value" text below header (None to skip)
# subject: noun for confirm messages ("dialogue", "image", "file")
# btn_letter: "D", "I", or "L" for hint messages
# description: short line explaining when this SFX triggers (None to skip)
# Transclude: extra UI between pool label and volume row (shake toggle,
#             frequency selector, exclusive controls). Each transcluded
#             section resolves its own active pool via ctx.get_active_pool().
screen cue_context_section(section_title, ctx, key, subtitle, subject, btn_letter, description=None):
    style_group "cue"

    $ _entry = _cue.markers.get(key, {})
    $ _pools = _entry.get("pools", [])
    $ _target = ctx.get_active_index()
    $ _target = max(0, min(_target, len(_pools) - 1)) if _pools else 0
    # Human name of this context for the [+] hint text (I/D/L -> Image/Dialogue/Loop).
    $ _ctx_label = {"I": "Image", "D": "Dialogue", "L": "Loop"}.get(btn_letter, "SFX")

    # sync back: clamps stale target after file switch so set_frequency/set_exclusive_* don't no-op
    $ ctx.set_active_index(_target)

    use cue_section_frame(section_title):
        if subtitle is not None:
            etext subtitle
        if _entry:
            $ _entry.setdefault("volume", _cue.volume.VOL_DEFAULT)
            $ _master_vol = _entry.get("volume", _cue.volume.VOL_DEFAULT)
            use cue_vol_row("Master Volume: {:.1f}".format(_master_vol), _entry, key)
        if key:
            $ _excl_ctx = ctx if ctx.ONE_SHOT else None
            use cue_pool_tabs(len(_pools), _target, bool(_pools),
                "Delete all {} for the current {}?".format(section_title.lower(), subject),
                Function(ctx.clear), "Delete all {} for the current {}".format(section_title.lower(), subject),
                Function(ctx.add_pool), "",
                ctx.set_active_index,
                exclusive_ctx=_excl_ctx)

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
                $ _active_label = "Pool " + str(_target + 1)
            hbox:
                spacing 5
                box_wrap True
                box_wrap_spacing 3
                etext _active_label
                null width 5
                use cue_icon_btn(
                    "floppy-disk",
                    Function(_cue.dialogs.pool_preset.open, key, _target),
                    "Save pool as a preset",
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
                use cue_icon_btn("xmark", Function(ctx.remove_pool, _target), "Delete pool")
                null width 5
                $ _vol_label = "Volume: {:.1f}".format(_active_vol)
                use cue_vol_row(_vol_label, _active_pool, key)

            transclude
            if _r.igroup is not None:
                use cue_igroup_pool_files(_r.igroup, _r.ilevel_id or 0, _active_eff)
            elif _r.refs:
                if _is_preset_pool:
                    # Preset-backed: render as expandable folder
                    use cue_file_list([], _cue.markers.detach_pool_at, (key, _target), _active_eff,
                        marker_key=key, pool_index=_target,
                        folder_label=_active_pool["preset"],
                        folder_children=_cue_resolve_files(_r.refs),
                        folder_child_remove_fn=_cue.markers._remove_file_from_preset_pool)
                else:
                    use cue_file_list(_r.refs, ctx.remove_file, (_target,), _active_eff,
                        marker_key=key, pool_index=_target,
                        folder_child_remove_fn=_cue.markers._remove_file_from_folder_ref)
            else:
                if key and description is not None:
                    etext description
                if key:
                    etext ("Click + in the SFX Library with {} targeted "
                        "to add files to this pool.").format(_ctx_label)
        else:
            if key and description is not None:
                etext description
            if key:
                etext ("Click + in the SFX Library with {} targeted to create a new pool "
                    "or add files to the active pool.").format(_ctx_label)

# Toggle button: square-check icon when checked, square when unchecked.
# on_bg/on_hover/off_bg/off_hover override backgrounds per state (None = style default).
screen cue_checkbox(checked, label, action, tt_on=None, tt_off=None,
                    on_bg=None, on_hover=None, off_bg=None, off_hover=None,
                    enabled=True):
    style_group "cue"

    $ _icon = _cue.icons.displayable_for("square-check" if checked else "square")
    button:
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
        transform:
            # Dim the whole row when disabled. alpha is a transform property,
            # so it has to wrap the content rather than sit on the text/add.
            alpha (0.35 if not enabled else 1.0)
            hbox:
                spacing 5
                add _icon yalign 0.5 yoffset 1
                etext label color _cue_color_text_white

# Radio button: solid circle icon tinted with the active color when
# selected, outline circle when not.
# Exclusivity within a group is enforced by the shared action target.
screen cue_radio_btn(checked, label, action, tt=None, enabled=True):
    style_group "cue"
    $ _icon = _cue.icons.displayable_for("circle" if checked else "circle-outline")
    button:
        sensitive enabled
        action action
        if tt is not None:
            tooltip tt
        hbox:
            spacing 5
            add _icon yalign 0.5
            etext label

## Colors matching the Bulma "is-link" notification style — tweak to taste
screen notification(text, 
                    bg=_cue_color_bg_btn, 
                    dismissable=False,
                    text_color=_cue_color_text,
                    icon=None,
                    icon_color=None):
    style_group "cue"

    $ _icon = _cue.icons.displayable_for(icon, icon_color)
    $ _icon_close = _cue.icons.displayable_for("circle-xmark")

    frame:
        background bg
        padding (28, 24, 56, 24)  # extra right padding to leave room for the close button
        xfill True

        hbox:
            spacing 12
            add _icon yalign 0.0

            etext text:
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
    style_group "cue"

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