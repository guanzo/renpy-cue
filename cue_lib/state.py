# -*- coding: utf-8 -*-
# cue_lib/state.py -- _cue singleton.
# The _cue object is created at module level (Python import time) and is
# therefore invisible to Ren'Py's rollback system.
#
# Managers are wired externally by cue_z.rpy init -900 to avoid circular
# imports.  state.py imports nothing from other cue_lib modules at the top
# -- every manager imports _cue from here, so importing them back would
# deadlock.

import renpy
import renpy.python as _renpy_python

from cue_lib.constants import CuePage  # re-exported: consumers import it from cue_lib.state


class CueContext(object):
    def __init__(self):
        self.current_file = ""
        self.current_dialogue = ""
        self.prev_dialogue = ""
        self.top_layer_type = ""
        self.top_displayable = None
        self._shake_just_happened = False


class Cue(_renpy_python.NoRollback):
    """Root object for the Cue mod -- state, managers, constants, and caches."""

    def __init__(self):
        # --- Runtime state ---
        self.initialized = False
        self.is_overlay_visible = False
        self.overlay_active_page = CuePage.SFX
        self.collapsed_sections = {}  # section_name -> bool (cue_section_frame)
        self.ctx = CueContext()  # per-frame scene state (current_file, dialogue, top layer)
        self.editing_input = ""  # dotted path of the text input in edit mode (cue_text_input)

        # --- Manager slots (wired by cue_z.rpy init -900) ---
        self.db = None
        self.intensity = None
        self.backups = None  # CueBackupManager, injected into db at init -900
        self.markers = None
        self.undo = None
        self.trigger = None
        self.vid_manager = None
        self.volume = None
        self.repeater = None
        self.ffmpeg = None
        self.video_editor = None
        self.speed_resolver = None
        self.video_sequence = None
        self.speed_toast = None
        self.auto_speed = None
        self.sfx = None
        self.settings = None  # CueSettings
        self.dialogs = None  # CueDialogs (wired by cue_z.rpy init -900)
        self.keybinds = None
        self.icons = None
        self.music = None
        self.paths = None
        self.importer = None
        self.exporter = None
        self.url_importer = None

    @property
    def _has_relative_volume(self):
        # type: () -> bool
        """True on Ren'Py 7.5+ -- play() accepts relative_volume there."""
        return getattr(renpy, "version_tuple", (0, 0, 0)) >= (7, 5, 0)

    # ------------------------------------------------------------------
    # Scene state (read-through to ctx)
    #
    # The per-frame scene values now live on _cue.ctx.  These properties
    # keep the 80+ legacy `_cue.current_file` readers/writers working
    # without touching them.  Producers in runtime.py/cue_z.rpy write the
    # context directly; everyone else reads through these.
    # ------------------------------------------------------------------

    @property
    def current_file(self):
        # type: () -> str
        return self.ctx.current_file

    @current_file.setter
    def current_file(self, value):
        # type: (str) -> None
        self.ctx.current_file = value

    @property
    def current_dialogue(self):
        # type: () -> str
        return self.ctx.current_dialogue

    @current_dialogue.setter
    def current_dialogue(self, value):
        # type: (str) -> None
        self.ctx.current_dialogue = value

    @property
    def prev_dialogue(self):
        # type: () -> str
        return self.ctx.prev_dialogue

    @prev_dialogue.setter
    def prev_dialogue(self, value):
        # type: (str) -> None
        self.ctx.prev_dialogue = value

    @property
    def top_layer_type(self):
        # type: () -> str
        return self.ctx.top_layer_type

    @top_layer_type.setter
    def top_layer_type(self, value):
        # type: (str) -> None
        self.ctx.top_layer_type = value

    # ------------------------------------------------------------------
    # Section frames (shared by all pages via cue_section_frame)
    # ------------------------------------------------------------------

    def toggle_section(self, section_name):
        # type: (str) -> None
        """Toggle expand/collapse for a cue_section_frame."""
        self.collapsed_sections[section_name] = not self.collapsed_sections.get(section_name, False)
        renpy.restart_interaction()


_cue = Cue()
