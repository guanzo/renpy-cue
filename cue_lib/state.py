# cue_lib/state.py — _cue singleton + bootstrap wiring.
# The _cue object is created at module level (Python import time) and is
# therefore invisible to Ren'Py's rollback system.  The bootstrap() function
# wires all manager instances and default state onto it — called once from
# cue_z.rpy init -900.

import os
import renpy.python as _renpy_python

_cue = _renpy_python.NoRollback()


def bootstrap():
    """Wire all manager instances and default state onto _cue.
    Called from cue_z.rpy init -900 after all classes are defined."""

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

    # --- Debug flag ---
    _cue.debug = True

    # --- Context tracking ---
    _cue.current_file = ""
    _cue.current_dialogue = ""
    _cue.prev_dialogue = ""
    _cue.top_layer_type = None
    _cue.top_displayable = None
    _cue.current_replay = None
    _cue._logged_unknown_displayables = set()

    # --- Path constants ---
    _cue.base_dir = "renpy_cue"
    _cue.audio_dir = _cue.base_dir + "/audio"
    _cue.config_filename = "cue_config.json"
    _cue.config_path = os.path.join(renpy.config.gamedir, _cue.base_dir, _cue.config_filename)
    _cue.debug_log_filename = "debug.log"

    # --- Managers ---
    _cue.markers = CueMarkerManager()
    _cue.undo = CueUndoManager()

    # --- Volume constants ---
    _cue.VOL_DEFAULT = 1.0
    _cue.DEFAULT_VIDEO_SPEED = 1.0

    # --- Key prefix constants ---
    _cue.IMG_KEY_PREFIX = "i:"
    _cue.LOOP_KEY_PREFIX = "l:"
    _cue.DLG_KEY_PREFIX = "d:"
    _cue.VID_KEY_PREFIX = "v:"

    # --- Trigger engine ---
    _cue.trigger = CueTriggerEngine()

    # --- Video state ---
    _cue.vid_manager = CueVideoManager()

    # --- Volume manager ---
    _cue.volume = CueVolumeManager()

    # --- Repeat pattern dialog ---
    _cue.beat = CueBeatManager()

    # --- Video editor ---
    _cue.ffmpeg = CueFFmpeg()
    _cue.video_editor = CueVideoEditor()

    # --- Speed resolver + sequence ---
    _cue.speed_resolver = CueVidSpeedResolver()
    _cue.video_sequence = CueVidSpeedSequence(_cue.speed_resolver)
    _cue.speed_resolver.sequence = _cue.video_sequence
    _cue.speed_toast = CueSpeedToast()

    # --- UI state ---
    _cue.is_overlay_visible = False
    _cue.initialized = False
    _cue.file_tree = CueFileTreeManager()
    _cue._marker_tip_text = ""
    _cue.scan_error = None

    _cue.preset_dialog = CuePresetDialog()
    _cue.video_preset_dialog = CueVideoPresetDialog()
    _cue.confirm_dialog = CueConfirmDialog()

    # --- Audio file cache ---
    _cue.available_files = []
    _cue.audio_tree = []

    # --- Internal ---
    _cue._cue_next_sfx_channel = 0
    _cue._shake_just_happened = False
    _cue._preview_channel = None
