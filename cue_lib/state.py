# -*- coding: utf-8 -*-
# cue_lib/state.py -- _cue singleton.
# The _cue object is created at module level (Python import time) and is
# therefore invisible to Ren'Py's rollback system.
#
# Managers are wired externally by cue_z.rpy init -900 to avoid circular
# imports — state.py imports nothing from cue_lib, while every manager
# module imports _cue from here.

import os as _os
import renpy
import renpy.python as _renpy_python


class Cue(_renpy_python.NoRollback):
    """Root object for the Cue mod -- state, managers, constants, and caches."""

    def __init__(self):
        # --- Paths ---
        self.debug = True
        self.base_dir = "renpy_cue"

        self.config_filename = "cue_config.json"
        self.debug_log_filename = "debug.log"

        # --- Constants ---
        self.IMG_KEY_PREFIX = "i_"
        self.LOOP_KEY_PREFIX = "l_"
        self.DLG_KEY_PREFIX = "d_"
        self.VID_KEY_PREFIX = "v_"

        # --- Runtime state ---
        self.initialized = False
        self.is_overlay_visible = False
        self.is_settings_visible = False
        self.current_file = ""
        self.current_dialogue = ""
        self.prev_dialogue = ""
        self.top_layer_type = ""
        self.top_displayable = None
        self.current_replay = None
        self.scan_error = ""
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
        self.file_tree = None
        self.preset_dialog = None
        self.video_preset_dialog = None
        self.confirm_dialog = None
        self.keybinds = None

        # --- Audio cache ---
        self.available_files = []
        self.audio_tree = []

        # --- Internal ---
        self._cue_next_sfx_channel = 0
        self._shake_just_happened = False
        self._preview_channel = None
        self._logged_unknown_displayables = set()
        self._marker_tip_text = ""
        self._marker_tip_x = 0
        self._marker_tip_y = 0
        self._popper_anchors = {}
        self._seq_popup_index = -1
        self._vtl_screen_x = 0
        self._vtl_screen_y = 0
        self._chart_screen_x = 0
        self._chart_screen_y = 0

    @property
    def shared_dir(self):
        # type: () -> str
        """Platform-standard shared directory for cue data.

        Respects the RENPY_CUE_DIR environment override.  Otherwise:
          Windows : %APPDATA%/renpy_cue
          macOS   : ~/Library/Application Support/renpy_cue
          Linux   : $XDG_DATA_HOME/renpy_cue or ~/.local/share/renpy_cue
        """
        import sys as _sys
        env = _os.environ.get("RENPY_CUE_DIR", "")
        if env:
            return _os.path.normpath(env)

        if _sys.platform == "win32":
            base = _os.environ.get("APPDATA", "")
        elif _sys.platform == "darwin":
            base = _os.path.expanduser("~/Library/Application Support")
        else:
            base = _os.environ.get(
                "XDG_DATA_HOME",
                _os.path.expanduser("~/.local/share"),
            )
        return _os.path.normpath(_os.path.join(base, "renpy_cue")).replace("\\", "/")

    @property
    def config_path(self):
        # type: () -> str
        return _os.path.join(renpy.config.gamedir, self.base_dir, self.config_filename)

    @property
    def audio_dir(self):
        # type: () -> str
        return self.shared_dir + "/audio"


_cue = Cue()
