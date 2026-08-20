# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false
# cue_lib/keybinds.py -- CueKeybindsManager: rebindable hotkey system.
#
# All cue hotkeys are routed through config.keymap entries (keymap names like
# "cue_toggle_overlay").  The cue_key_listener screen uses static keymap-name
# key statements, and runtime rebinds mutate config.keymap + clear the compiled
# event cache so changes take effect immediately.
#
# reportAttributeAccessIssue is disabled because renpy.config.keymap and
# renpy.display.behavior.clear_keymap_cache are dynamically assembled and
# not visible to the type checker.

import renpy
import renpy.display.behavior as _behavior  # pyright: ignore[reportMissingImports]

from cue_lib.state import _cue
from cue_lib.constants import (
    CUE_DEBUG,
    CUE_KEYMAP_TOGGLE_OVERLAY,
    CUE_KEYMAP_QUIT_RELAUNCH,
    CUE_KEYMAP_COPY_CONTEXT,
    CUE_KEYMAP_PASTE_CONTEXT,
    CUE_KEYMAP_TOGGLE_SFX_ACTIVE,
    CUE_KEYMAP_PAUSE,
    CUE_KEYMAP_UNDO,
    CUE_KEYMAP_REDO,
    CUE_KEYMAP_SPEED_UP,
    CUE_KEYMAP_SPEED_DOWN,
    CUE_KEYMAP_TOGGLE_SFX_LIBRARY,
    CUE_KEYMAP_TOGGLE_SFX_OVERLAY,
    CUE_KEYMAP_PAGE_SFX,
    CUE_KEYMAP_PAGE_MUSIC,
    CUE_KEYMAP_PAGE_IMPORT,
    CUE_KEYMAP_PAGE_SETTINGS,
    CUE_KEYMAP_TARGET_VIDEO,
    CUE_KEYMAP_TARGET_IMAGE,
    CUE_KEYMAP_TARGET_DIALOGUE,
    CUE_KEYMAP_TARGET_LOOP,
    CUE_SHARED_KEY_KEYBINDS,
)

MYPY = False
if MYPY:
    from typing import List, Optional
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]


# ---------------------------------------------------------------------------
# Keysym-to-display-label mapping
# ---------------------------------------------------------------------------

_KEY_DISPLAY = {
    "BACKQUOTE": "`",
    "BACKSPACE": "Bksp",
    "TAB": "Tab",
    "RETURN": "Enter",
    "ESCAPE": "Esc",
    "SPACE": "Space",
    "DELETE": "Del",
    "INSERT": "Ins",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PgUp",
    "PAGEDOWN": "PgDn",
    "UP": "Up",
    "DOWN": "Down",
    "LEFT": "Left",
    "RIGHT": "Right",
    "PAUSE": "Pause",
    "PRINT": "PrtSc",
    "MENU": "Menu",
    "CAPSLOCK": "Caps",
    "NUMLOCK": "NumLk",
    "SCROLLOCK": "ScrlLk",
    "SLASH": "/",
    "BACKSLASH": "\\",
    "PERIOD": ".",
    "COMMA": ",",
    "SEMICOLON": ";",
    "QUOTE": "'",
    "MINUS": "-",
    "EQUALS": "=",
    "LEFTBRACKET": "[",
    "RIGHTBRACKET": "]",
}

_MOD_DISPLAY = {
    "shift": "Shift",
    "ctrl": "Ctrl",
    "alt": "Alt",
    "meta": "Win",
}

_VALID_MODS = frozenset(("shift", "noshift", "ctrl", "alt", "meta"))

# Python 2 (Ren'Py 7.x): `str` is bytes and json decodes to `unicode`.  Accept
# both so saved keybind overrides aren't rejected as invalid on restart.
try:
    unicode  # pyright: ignore[reportUndefinedVariable, reportUnusedExpression]
except NameError:
    _KEY_STRING_TYPES = (str,)
else:
    _KEY_STRING_TYPES = (str, unicode)  # pyright: ignore[reportUndefinedVariable]


# ---------------------------------------------------------------------------
# Bridge functions for Function() screen actions (no lambdas in Ren'Py)
# ---------------------------------------------------------------------------

def _cue_keybind_start(action_id):
    # type: (str) -> None
    """Begin key-capture for the given action id."""
    _cue.keybinds.start_capture(action_id)


def _cue_keybind_cancel():
    # type: () -> None
    """Cancel the current key-capture."""
    _cue.keybinds.cancel_capture()


def _cue_keybind_reset(action_id):
    # type: (str) -> None
    """Reset the given action to its default keysym."""
    _cue.keybinds.reset_binding(action_id)


def _cue_keybind_override():
    # type: () -> None
    """Confirm a colliding keybind, overriding the existing binding."""
    _cue.keybinds.confirm_override()


# ---------------------------------------------------------------------------
# CueKeybindsManager
# ---------------------------------------------------------------------------

class CueKeybindsManager(object):
    """Owns the metadata for every rebindable hotkey, drives key-capture,
    collision detection, persistence, and the settings UI."""

    def __init__(self, db):
        # type: (CueDatabase) -> None
        self._db = db            # shared config store for keybind persistence
        # Ordered list of action dicts.  Each dict:
        #   id          - action identity, also the config.keymap entry name
        #                 (CUE_KEYMAP_* constant; doubles as the persistence key)
        #   default     - default Ren'Py keysym string
        #   label       - human-readable display name
        #   desc        - tooltip description
        #   debug_only  - if True, only active when CUE_DEBUG is True
        self.actions = [
            {"id": CUE_KEYMAP_TOGGLE_OVERLAY,
             "default": "K_BACKQUOTE",
             "label": "Toggle Overlay",
             "desc": "Show or hide the Cue overlay"},
            {"id": CUE_KEYMAP_TOGGLE_SFX_ACTIVE,
             "default": "shift_K_3",
             "label": "Toggle SFX Triggers",
             "desc": "Enable or disable SFX triggers"},
            {"id": CUE_KEYMAP_TOGGLE_SFX_LIBRARY,
             "default": "shift_K_s",
             "label": "Toggle SFX Library",
             "desc": "Collapse or expand the SFX Library section"},
            {"id": CUE_KEYMAP_TOGGLE_SFX_OVERLAY,
             "default": "alt_K_a",
             "label": "Toggle SFX Overlay",
             "desc": "Toggle SFX Library overlay mode"},
            # noshift: a bare K_1..K_4 also matches Shift+1..4 in Ren'Py
            # (plain keys only exclude alt/ctrl/meta), so without it the
            # target keys would clobber shift_K_1/2/3/4 on the SFX page.
            {"id": CUE_KEYMAP_TARGET_VIDEO,
             "default": "noshift_K_1",
             "label": "Target Video",
             "desc": "SFX Library + target: Video SFX pool"},
            {"id": CUE_KEYMAP_TARGET_IMAGE,
             "default": "noshift_K_2",
             "label": "Target Image",
             "desc": "SFX Library + target: Image SFX pool"},
            {"id": CUE_KEYMAP_TARGET_DIALOGUE,
             "default": "noshift_K_3",
             "label": "Target Dialogue",
             "desc": "SFX Library + target: Dialogue SFX pool"},
            {"id": CUE_KEYMAP_TARGET_LOOP,
             "default": "noshift_K_4",
             "label": "Target Loop",
             "desc": "SFX Library + target: Loop SFX pool"},
            {"id": CUE_KEYMAP_PAGE_SFX,
             "default": "alt_K_1",
             "label": "Open SFX Editor",
             "desc": "Open SFX Editor page"},
            {"id": CUE_KEYMAP_PAGE_MUSIC,
             "default": "alt_K_2",
             "label": "Open Music",
             "desc": "Open Music page"},
            {"id": CUE_KEYMAP_PAGE_IMPORT,
             "default": "alt_K_3",
             "label": "Open Import / Export",
             "desc": "Open Import / Export page"},
            {"id": CUE_KEYMAP_PAGE_SETTINGS,
             "default": "alt_K_4",
             "label": "Open Settings",
             "desc": "Open Settings page"},
            {"id": CUE_KEYMAP_QUIT_RELAUNCH,
             "default": "K_F5",
             "label": "Quit & Relaunch",
             "desc": "Quit and relaunch the game (dev only)",
             "debug_only": True},
            {"id": CUE_KEYMAP_COPY_CONTEXT,
             "default": "shift_K_1",
             "label": "Copy Markers",
             "desc": "Copy current scene markers to clipboard"},
            {"id": CUE_KEYMAP_PASTE_CONTEXT,
             "default": "shift_K_2",
             "label": "Paste Markers",
             "desc": "Paste markers from clipboard"},
            {"id": CUE_KEYMAP_PAUSE,
             "default": "shift_K_4",
             "label": "Pause Game",
             "desc": "Pause the game (use on scenes that auto-advance)"},
            {"id": CUE_KEYMAP_UNDO,
             "default": "shift_K_q",
             "label": "Undo",
             "desc": "Undo last change"},
            {"id": CUE_KEYMAP_REDO,
             "default": "shift_K_w",
             "label": "Redo",
             "desc": "Redo last change"},
            {"id": CUE_KEYMAP_SPEED_UP,
             "default": "K_m",
             "label": "Speed Up",
             "desc": "Cycle video speed up by one step"},
            {"id": CUE_KEYMAP_SPEED_DOWN,
             "default": "K_n",
             "label": "Speed Down",
             "desc": "Cycle video speed down by one step"},
        ]

        self._capturing_id = ""         # action id currently being captured
        self.collision_message = ""     # shown in the capture modal
        self._pending_keysym = ""       # colliding key awaiting override confirm

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self):
        # type: () -> None
        """Register keymap entries and load saved overrides from shared config.

        Runs on every init (cue_z.rpy init 999, unguarded): reload_all()
        restores config.keymap to its post-import default, so the cue entries
        are wiped on Shift+R reload and must be re-registered.  Must run after
        the game's config.keymap is fully populated so collision scanning sees
        all built-ins.  Idempotent -- existing entries are left untouched.
        """
        # 1. Register defaults for any names not already present.
        for action in self.actions:
            if action["id"] not in renpy.config.keymap:
                renpy.config.keymap[action["id"]] = [action["default"]]

        # 2. Load saved overrides from shared config.  A saved "" means
        #    explicitly unbound (confirm_override writes it when a stolen
        #    key's default is still taken); a missing key means "use default".
        cfg = self._db.load_shared_config()
        saved = cfg.get(CUE_SHARED_KEY_KEYBINDS, {})
        if isinstance(saved, dict):
            for action in self.actions:
                ks = saved.get(action["id"])
                if ks is None:
                    continue
                if ks == "":
                    renpy.config.keymap[action["id"]] = []  # explicitly unbound
                elif self._is_valid_keysym(ks):
                    renpy.config.keymap[action["id"]] = [self._normalize_keysym(ks)]

        # 3. Clear the compiled event cache so the new entries / overrides
        #    take effect immediately.
        _behavior.clear_keymap_cache()

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    def get_keysym(self, action_id):
        # type: (str) -> str
        """Return the current keysym string for *action_id*.

        Reads from config.keymap; falls back to the default if the keymap
        entry is missing (should not happen after setup()).
        """
        action = self._get_action(action_id)
        if action is None:
            return action_id
        entry = renpy.config.keymap.get(action["id"])
        if entry is not None and len(entry) == 0:
            return ""  # explicitly unbound
        if entry and len(entry) > 0:  # pyright: ignore[reportOptionalSubscript]
            return entry[0]
        return action["default"]

    def keysym_label(self, keysym):
        # type: (str) -> str
        """Convert a Ren'Py keysym string to a human-readable label.

        Examples::

            "K_F5"              -> "F5"
            "K_BACKQUOTE"       -> "`"
            "shift_K_1"         -> "Shift+1"
            "ctrl_alt_K_F9"     -> "Ctrl+Alt+F9"
            "K_SLASH"           -> "/"
        """
        # Unbound.
        if not keysym:
            return "--"

        # Split into modifier prefix and key suffix.
        # Ren'Py keysym format:  [mod_]...[mod_]K_KEYNAME
        idx = keysym.rfind("K_")
        if idx < 0:
            return keysym

        key = keysym[idx + 2:]   # part after "K_"
        mods = keysym[:idx]      # everything before "K_" (may be empty)

        # Resolve the base key label.
        key_upper = key.upper()
        if key_upper in _KEY_DISPLAY:
            label = _KEY_DISPLAY[key_upper]
        elif key_upper.startswith("KP_"):
            # e.g. KP0, KP_PERIOD
            label = "Numpad " + key_upper[3:]
        elif len(key) == 1:
            label = key.upper()
        else:
            # F-keys ("F5"), and anything else we haven't mapped.
            label = key_upper

        # Build modifier prefix ("Ctrl+Alt+..."). Segment match so the
        # negative modifier "noshift" doesn't read as "shift" (substring).
        prefix = ""
        mod_segs = [s for s in mods.rstrip("_").split("_") if s]
        for mod in ("meta", "ctrl", "alt", "shift"):
            if mod in mod_segs:
                prefix += _MOD_DISPLAY[mod] + "+"

        return prefix + label

    def visible_actions(self):
        # type: () -> list
        """Return the list of action dicts that should be shown in settings.

        Filters out debug_only actions when CUE_DEBUG is False, and always
        hides quit_relaunch (dev tool, not user-configurable).
        """
        result = []
        for a in self.actions:
            if a["id"] == CUE_KEYMAP_QUIT_RELAUNCH:
                continue
            if a.get("debug_only") and not CUE_DEBUG:
                continue
            result.append(a)
        return result

    def current_label(self):
        # type: () -> str
        """Return the label of the action currently being captured."""
        action = self._get_action(self._capturing_id)
        if action is not None:
            return action.get("label", "")
        return ""

    def shortcut_label(self, action_id):
        # type: (str) -> str
        """Display text for the current binding of an action ("Shift+1")."""
        return self.keysym_label(self.get_keysym(action_id))

    # ------------------------------------------------------------------
    # Capture flow
    # ------------------------------------------------------------------

    def start_capture(self, action_id):
        # type: (str) -> None
        """Begin key capture for *action_id*."""
        self._capturing_id = action_id
        self.collision_message = ""
        self._pending_keysym = ""
        renpy.show_screen("cue_keybind_capture", _layer="cue_layer")
        renpy.restart_interaction()

    def cancel_capture(self):
        # type: () -> None
        """Abort the current capture without changing anything."""
        self._capturing_id = ""
        self.collision_message = ""
        self._pending_keysym = ""
        renpy.hide_screen("cue_keybind_capture", layer="cue_layer")
        renpy.restart_interaction()

    def on_captured(self, keysym):
        # type: (str) -> None
        """Called by CueKeyCaptureDisplayable when a key is pressed during capture.

        * Esc cancels.
        * Same key as current binding is a no-op (closes modal, no change).
        * Collision with another cue or Ren'Py keymap entry shows a warning.
        * Clean key applies the rebind, saves, and closes the modal.
        """
        if not self._capturing_id:
            return

        # Esc always cancels.
        if keysym == "K_ESCAPE":
            self.cancel_capture()
            return

        # Bare keys must not match shifted presses -- normalize before the
        # no-op/collision checks so every stored binding is noshift-clean.
        keysym = self._normalize_keysym(keysym)

        action = self._get_action(self._capturing_id)
        if action is None:
            self.cancel_capture()
            return

        # Compare against the normalized form too, so a bare default like
        # "K_BACKQUOTE" still reads as the same key as a "noshift_K_..." capture.
        current = self._normalize_keysym(self.get_keysym(self._capturing_id))

        # No-op: same key.
        if keysym == current:
            self.cancel_capture()
            return

        # Check for collisions.
        collisions = self._find_collisions(keysym, self._capturing_id)
        if collisions:
            self._pending_keysym = keysym
            self.collision_message = "Key {} is already used by:\n{}".format(
                self.keysym_label(keysym), ", ".join(collisions[:3])
            )
            renpy.restart_interaction()
            return

        # Clean — apply.
        self._apply_binding(action, keysym)

    def confirm_override(self):
        # type: () -> None
        """Apply the pending colliding binding and reset overridden Cue actions.

        For each Cue action that had its key overridden: reset to its
        default keysym if it is available, otherwise unbind (empty list).
        """
        if not self._pending_keysym or not self._capturing_id:
            self.cancel_capture()
            return

        action = self._get_action(self._capturing_id)
        if action is None:
            self.cancel_capture()
            return

        keysym = self._pending_keysym

        # Find Cue actions currently using this keysym (to reset them).
        overridden = []
        for a in self.actions:
            if a["id"] == self._capturing_id:
                continue
            entry = renpy.config.keymap.get(a["id"])
            if entry and keysym in entry:
                overridden.append(a)

        # Apply the new binding for the target action.
        renpy.config.keymap[action["id"]] = [keysym]

        # Reset each overridden Cue action to its default, or unbind.
        for a in overridden:
            default_collisions = self._find_collisions(a["default"], a["id"])
            if default_collisions:
                renpy.config.keymap[a["id"]] = []
            else:
                renpy.config.keymap[a["id"]] = [a["default"]]

        _behavior.clear_keymap_cache()
        self.collision_message = ""
        self._capturing_id = ""
        self._pending_keysym = ""
        renpy.hide_screen("cue_keybind_capture", layer="cue_layer")
        self.save()
        renpy.restart_interaction()

    # ------------------------------------------------------------------
    # Binding mutations
    # ------------------------------------------------------------------

    def _apply_binding(self, action, keysym):
        # type: (dict, str) -> None
        """Set *action*'s keymap entry to *keysym* and finalize capture."""
        renpy.config.keymap[action["id"]] = [keysym]
        _behavior.clear_keymap_cache()
        self.collision_message = ""
        self._capturing_id = ""
        renpy.hide_screen("cue_keybind_capture", layer="cue_layer")
        self.save()
        renpy.restart_interaction()

    def reset_binding(self, action_id):
        # type: (str) -> None
        """Reset *action_id* to its default keysym."""
        action = self._get_action(action_id)
        if action is None:
            return
        renpy.config.keymap[action["id"]] = [action["default"]]
        _behavior.clear_keymap_cache()
        self.save()
        renpy.restart_interaction()

    # ------------------------------------------------------------------
    # Collision detection
    # ------------------------------------------------------------------

    def _find_collisions(self, keysym, exclude_id):
        # type: (str, str) -> List[str]
        """Return a list of human-readable owner descriptions for *keysym*.

        Checks both cue's own keymap entries (excluding *exclude_id*) and
        Ren'Py built-in config.keymap entries.
        """
        owners = []

        # Cue keybinds (other actions).
        for a in self.actions:
            if a["id"] == exclude_id:
                continue
            entry = renpy.config.keymap.get(a["id"])
            if entry and keysym in entry:
                owners.append("Cue: {}".format(a.get("label", a["id"])))

        # Ren'Py built-ins.
        for name, entry in renpy.config.keymap.items():
            if name.startswith("cue_"):
                continue
            if hasattr(entry, "__iter__") and not isinstance(entry, (str, bytes)):
                if keysym in entry:
                    owners.append("Ren'Py: {}".format(name))

        return owners

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        # type: () -> None
        """Persist non-default bindings to the shared config file."""
        data = {}
        for a in self.actions:
            ks = self.get_keysym(a["id"])
            if ks != a["default"]:
                data[a["id"]] = ks
        self._db.update_shared_config({CUE_SHARED_KEY_KEYBINDS: data})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_action(self, action_id):
        # type: (str) -> Optional[dict]
        """Return the action dict for *action_id*, or None."""
        for a in self.actions:
            if a["id"] == action_id:
                return a
        return None

    @staticmethod
    def _normalize_keysym(keysym):
        # type: (str) -> str
        """Add ``noshift`` to a modifier-less keysym.

        A bare ``K_3`` in Ren'Py also matches ``Shift+3`` (plain keys only
        exclude alt/ctrl/meta), so without this a user-rebound plain key
        would clobber its Shift+ variant.  Applied on capture and on load so
        the invariant holds for every stored binding, not just the defaults.
        """
        if not keysym:
            return keysym
        idx = keysym.rfind("K_")
        if idx < 0:
            return keysym
        if not keysym[:idx].rstrip("_"):
            return "noshift_" + keysym[idx:]
        return keysym

    @staticmethod
    def _is_valid_keysym(keysym):
        # type: (str) -> bool
        """Return True if *keysym* looks like a valid Ren'Py keysym string."""
        if not isinstance(keysym, _KEY_STRING_TYPES):
            return False
        idx = keysym.rfind("K_")
        if idx < 0:
            return False
        # Validate modifier prefix (if any).
        if idx > 0:
            mods = keysym[:idx].rstrip("_").split("_")
            for m in mods:
                if m not in _VALID_MODS:
                    return False
        # Must have a non-empty key name after "K_".
        key = keysym[idx + 2:]
        if not key:
            return False
        return True
