# -*- coding: utf-8 -*-
# cue_lib/state.py -- _cue singleton.
# The _cue object is created at module level (Python import time) and is
# therefore invisible to Ren'Py's rollback system.
#
# Managers are wired externally by cue_z.rpy init -900 to avoid circular
# imports.  state.py imports only cue_lib.constants (a leaf module with no
# imports of its own), while every manager module imports _cue from here.

import renpy
import renpy.python as _renpy_python


class CuePage(object):
    """Overlay sidebar page tabs.

    Members are plain ints so screens can compare against _cue.overlay_active_page
    (Python 2.7-safe -- no enum base class).
    """
    SFX = 0       # SFX editor (markers / library)
    MUSIC = 1     # Music page
    SETTINGS = 2  # Settings page


class Cue(_renpy_python.NoRollback):
    """Root object for the Cue mod -- state, managers, constants, and caches."""

    def __init__(self):
        # --- Paths ---
        self.debug = True
        self.base_dir = "renpy_cue"
        self.debug_log_filename = "debug.log"

        # --- Constants ---
        self.IMG_KEY_PREFIX = "i_"
        self.LOOP_KEY_PREFIX = "l_"
        self.DLG_KEY_PREFIX = "d_"
        self.VID_KEY_PREFIX = "v_"

        # --- Runtime state ---
        self.initialized = False
        self.is_overlay_visible = False
        self.overlay_active_page = CuePage.SFX
        self.is_exclusive_row_visible = False
        self.collapsed_sections = {}       # section_name -> bool (cue_section_frame)
        self.sfx_library_overlay_mode = False  # SFX Library section floats at 50% height
        self.current_file = ""
        self.current_dialogue = ""
        self.prev_dialogue = ""
        self.top_layer_type = ""
        self.top_displayable = None
        self.current_replay = None
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
        self.music_manager = None
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
