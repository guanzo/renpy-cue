# -*- coding: utf-8 -*-
# cue_lib/state.py -- _cue singleton + bootstrap wiring.
# The _cue object is created at module level (Python import time) and is
# therefore invisible to Ren'Py's rollback system.  The bootstrap() function
# wires any remaining Ren'Py-dependent state -- called once from
# cue_z.rpy init -900.

import os
import renpy
import renpy.python as _renpy_python

MYPY = False
if MYPY:
    from cue_lib._types import AudioTreeNode


class Cue(_renpy_python.NoRollback):
    """Root object for the Cue mod -- state, managers, constants, and caches."""

    def __init__(self):
        # --- Paths ---
        self.debug = True
        self.base_dir = "renpy_cue"
        self.audio_dir = self.base_dir + "/audio"
        self.config_filename = "cue_config.json"
        self.config_path = ""  # set by bootstrap() once renpy.config is ready
        self.shared_dir = ""   # set by bootstrap()
        self.db_path = ""      # set by bootstrap()
        self.debug_log_filename = "debug.log"

        # --- Constants ---
        self.DEFAULT_VIDEO_SPEED = 1.0
        self.VOL_DEFAULT = 1.0
        self.IMG_KEY_PREFIX = "i:"
        self.LOOP_KEY_PREFIX = "l:"
        self.DLG_KEY_PREFIX = "d:"
        self.VID_KEY_PREFIX = "v:"

        # --- Runtime state ---
        self.initialized = False
        self.is_overlay_visible = False
        self.current_file = ""
        self.current_dialogue = ""
        self.prev_dialogue = ""
        self.top_layer_type = ""
        self.top_displayable = None
        self.current_replay = None
        self.scan_error = ""
        self._has_relative_volume = False

        # --- Managers (set by bootstrap) ---
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
        self.file_tree = None
        self.preset_dialog = None
        self.video_preset_dialog = None
        self.confirm_dialog = None

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


_cue = Cue()


def bootstrap():
    # type: () -> None
    """Wire Ren'Py-dependent state once renpy.config is available.
    Called from cue_z.rpy init -900."""

    # --- Imports (function-level -- no module-level deps on submodules) ---
    from cue_lib.markers import CueMarkerManager
    from cue_lib.undo import CueUndoManager
    from cue_lib.trigger import CueTriggerEngine
    from cue_lib.video import CueVideoManager
    from cue_lib.volume import CueVolumeManager
    from cue_lib.repeater import CueMarkerRepeater
    from cue_lib.ffmpeg import CueFFmpeg
    from cue_lib.video_editor import CueVideoEditor
    from cue_lib.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
    from cue_lib.file_tree import CueFileTreeManager
    from cue_lib.ui_logic import CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog

    _cue.markers = CueMarkerManager()
    _cue.undo = CueUndoManager()
    _cue.trigger = CueTriggerEngine()
    _cue.vid_manager = CueVideoManager()
    _cue.volume = CueVolumeManager()
    _cue.repeater = CueMarkerRepeater()
    _cue.ffmpeg = CueFFmpeg()
    _cue.video_editor = CueVideoEditor()
    _cue.speed_resolver = CueVidSpeedResolver()
    _cue.video_sequence = CueVidSpeedSequence(_cue.speed_resolver)
    _cue.speed_resolver.sequence = _cue.video_sequence
    _cue.speed_toast = CueSpeedToast()
    _cue.file_tree = CueFileTreeManager()
    _cue.preset_dialog = CuePresetDialog()
    _cue.video_preset_dialog = CueVideoPresetDialog()
    _cue.confirm_dialog = CueConfirmDialog()

    _cue.config_path = os.path.join(renpy.config.gamedir, _cue.base_dir, _cue.config_filename)

    # Set up the shared SQLite database (one DB for all games, partitioned by save_directory)
    from cue_lib.db import _cue_open_database
    _cue.db = _cue_open_database(renpy.config.save_directory)
    _cue.shared_dir = os.path.dirname(_cue.db.path)
    _cue.db_path = _cue.db.path
