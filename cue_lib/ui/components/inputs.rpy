###############################################################################
# Input Component Screens
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
            # List-element paths: "settings.folders[i]" binds a single element
            # of a list attribute instead of a scalar field (Settings folder
            # rows).  FieldInputValue can't address "folders[i]" via setattr,
            # so the list case routes get_text/set_text through the element.
            _attr, _sep, _rest = self._field.partition("[")
            if not _sep:
                self._is_list = False
                self._list = None
                self._index = 0
                FieldInputValue.__init__(self, _obj, self._field, default=default)
            else:
                self._is_list = True
                self._list = getattr(_obj, _attr)
                self._index = int(_rest.rstrip("]"))
            self.enter_action = enter_action

        def get_text(self):
            if self._is_list:
                try:
                    return self._list[self._index]
                except Exception:
                    return ""
            return FieldInputValue.get_text(self)

        def set_text(self, text):
            if self._is_list:
                self._list[self._index] = text
                renpy.restart_interaction()
                return
            FieldInputValue.set_text(self, text)

        def enter(self):
            if self.enter_action is not None:
                renpy.run(self.enter_action)
                renpy.restart_interaction()
            return FieldInputValue.enter(self)

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

    def _cue_clear_field_value(field_name):
        # type: (str) -> None
        """Empty the field addressed by a dotted path (a scalar attribute or
        a list-element path like "settings.folders[i]").  A Function action,
        not SetField, because a list element has no settable attribute."""
        _CueFieldValue(field_name).set_text("")

# Float input: textbutton that becomes an input on click, Enter to confirm.
# field_name: string for VariableInputValue
# commit_action: Function() called on Enter — must return True (valid) or False (invalid)
# display_text: the label shown on the textbutton
screen cue_float_input(field_name, commit_action, display_text,
                       dec_action=None, inc_action=None):
    style_group "cue"

    $ editing = (_cue.overlay.active_input == field_name)
    $ _start_edit = SetField(_cue.overlay, "active_input", field_name)
    $ _commit = [commit_action, SetField(_cue.overlay, "active_input", "")]

    hbox:
        spacing 3
        if dec_action is not None:
            use cue_icon_btn("-", dec_action)

        if editing:
            key "K_RETURN" action _commit
            key "K_KP_ENTER" action _commit
            input:
                value _CueFieldValue(field_name)
                default True
                xsize 80
                ysize 16
        else:
            use cue_txt_button(display_text,
                _start_edit,
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

    $ editing = (_cue.overlay.active_input == field_name)
    $ _start_edit = SetField(_cue.overlay, "active_input", field_name)
    $ _commit = [commit_action, SetField(_cue.overlay, "active_input", "")]

    hbox:
        spacing 3
        #use cue_icon_btn("--", dec100_action, None, 22)
        use cue_icon_btn("-", dec10_action)

        if editing:
            key "K_RETURN" action _commit
            key "K_KP_ENTER" action _commit
            input:
                value _CueFieldValue(field_name)
                default True
        else:
            use cue_txt_button(display_text,
                [_start_edit, Function(_cue.markers.video.sync_text)],
                tt="Click to edit. Press Enter to confirm.")

        use cue_icon_btn("+", inc10_action)
        #use cue_icon_btn("++", inc100_action, None, 22)

screen cue_text_input(field_name, commit_action, display_text, xsize=200,
                      clear_action=None, hint_icon="keyboard",
                      paste_btn=False, commit_on_enter=True):
    style_group "cue"

    $ ysize = 16
    # Each input derives its own editing flag from the shared _cue.overlay.active_input
    # (holds this field's dotted path while it's being edited, "" = none), so
    # only one field is in edit mode at a time.
    $ editing = (_cue.overlay.active_input == field_name)
    $ _start_edit = SetField(_cue.overlay, "active_input", field_name)
    $ _commit = [commit_action, SetField(_cue.overlay, "active_input", "")]
    $ _exit_edit = SetField(_cue.overlay, "active_input", "")

    if commit_on_enter:
        $ _enter = _commit
    else:
        $ _enter = _exit_edit

    if clear_action is not None:
        $ _clear_core = clear_action
    else:
        # Default clear: empty the field value.  A Function, not SetField,
        # because a list-element path ("settings.folders[i]") has no settable
        # attribute -- _CueFieldValue routes both through the right setter.
        $ _clear_core = Function(_cue_clear_field_value, field_name)
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
                background _cue_color_bg_input_active
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

