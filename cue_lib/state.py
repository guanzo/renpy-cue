# cue_lib/state.py — _cue singleton + bootstrap wiring.
# The _cue object is created at module level (Python import time) and is
# therefore invisible to Ren'Py's rollback system.  The bootstrap() function
# wires any remaining Ren'Py-dependent state — called once from
# cue_z.rpy init -900.

import os
import renpy
import renpy.python as _renpy_python


class Cue(_renpy_python.NoRollback):
    """Root object for the Cue mod — state, managers, constants, and caches."""

    def __init__(self):
        # --- Imports (function-level to avoid circular deps at module load) ---
        from cue_lib.markers import CueMarkerManager
        from cue_lib.undo import CueUndoManager
        from cue_lib.trigger import CueTriggerEngine
        from cue_lib.video import CueVideoManager
        from cue_lib.volume import CueVolumeManager
        from cue_lib.beat import CueBeatManager
        from cue_lib.ffmpeg import CueFFmpeg
        from cue_lib.video_editor import CueVideoEditor
        from cue_lib.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
        from cue_lib.file_tree import CueFileTreeManager
        from cue_lib.ui_logic import CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog

        # --- Paths ---
        self.debug = True
        self.base_dir = "renpy_cue"
        self.audio_dir = self.base_dir + "/audio"
        self.config_filename = "cue_config.json"
        self.config_path = ""  # set by bootstrap() once renpy.config is ready
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

        # --- Managers ---
        self.markers = CueMarkerManager()
        self.undo = CueUndoManager()
        self.trigger = CueTriggerEngine()
        self.vid_manager = CueVideoManager()
        self.volume = CueVolumeManager()
        self.beat = CueBeatManager()
        self.ffmpeg = CueFFmpeg()
        self.video_editor = CueVideoEditor()
        self.speed_resolver = CueVidSpeedResolver()
        self.video_sequence = CueVidSpeedSequence(self.speed_resolver)
        self.speed_resolver.sequence = self.video_sequence
        self.speed_toast = CueSpeedToast()
        self.file_tree = CueFileTreeManager()
        self.preset_dialog = CuePresetDialog()
        self.video_preset_dialog = CueVideoPresetDialog()
        self.confirm_dialog = CueConfirmDialog()

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
    """Wire Ren'Py-dependent state once renpy.config is available.
    Called from cue_z.rpy init -900."""
    _cue.config_path = os.path.join(renpy.config.gamedir, _cue.base_dir, _cue.config_filename)
