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
        self.initialized = False


class Cue(_renpy_python.NoRollback):
    """Root object for the Cue mod -- state, managers, constants, and caches."""

    def __init__(self):
        # --- Runtime state ---
        self.initialized = False
        self.is_overlay_visible = False
        self.overlay_active_page = CuePage.SFX
        self.collapsed_sections = {}       # section_name -> bool (cue_section_frame)
        self.sfx_library_overlay_mode = False  # SFX Library section floats at 50% height
        self.ctx = CueContext()          # per-frame scene state (current_file, dialogue, top layer)
        self.top_displayable = None
        self.setup_dir_text = ""      # text bound to the Shared Dir input
        self.shared_dir_error = ""    # error line under the Shared Dir input
        self.shared_dir_success = ""  # success line under the Shared Dir input
        self._has_relative_volume = False

        # --- Manager slots (wired by cue_z.rpy init -900) ---
        self.db = None
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
        self.sfx_manager = None
        self.preset_dialog = None
        self.video_preset_dialog = None
        self.confirm_dialog = None
        self.keybinds = None
        self.icons = None
        self.music = None
        self.paths = None

        # --- Internal ---
        self._cue_next_sfx_channel = 0
        self._shake_just_happened = False
        self._preview_channel = None
        self._logged_unknown_displayables = set()
        self._marker_tip_text = ""
        self._marker_tip_x = 0
        self._marker_tip_y = 0
        self._popper_anchors = {}
        self._vtl_screen_x = 0
        self._vtl_screen_y = 0
        self._chart_screen_x = 0
        self._chart_screen_y = 0

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

    def toggle_sfx_library_overlay_mode(self):
        # type: () -> None
        """Toggle overlay mode for the SFX Library section.
        Enabling overlay mode collapses the section if expanded.
        Exiting overlay mode expands the section if collapsed."""
        was_overlay = self.sfx_library_overlay_mode
        self.sfx_library_overlay_mode = not was_overlay

        renpy.restart_interaction()


_cue = Cue()
