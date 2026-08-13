###############################################################################
# Cue — bootstrap and wiring.
# .py modules live in cue_lib/; this file has ONLY the init blocks needed
# to import the package, bridge names into the Ren'Py store for screens,
# and run the one-time runtime setup.
###############################################################################

python early:
    import sys
    import os

    _cue_lib_parent = os.path.join(renpy.config.gamedir, "renpy_cue")
    if _cue_lib_parent not in sys.path:
        sys.path.insert(0, _cue_lib_parent)

    def _cue_popper_factory(*args, **kwargs):
        """Factory for register_sl_displayable. Returns a CuePopper instance.
        CuePopper is resolved at call time (screen execution), by which point
        the init -999 bridge has imported it into store."""
        return CuePopper(*args, **kwargs)

    renpy.register_sl_displayable(
        "popper",
        _cue_popper_factory,
        style="default",
        nchildren=1,
        default_keywords={
            "placement": "top",
            "offset": 5,
            "viewport_margin": 8,
        },
    ).add_property("target").add_property("placement").add_property("offset").add_property("viewport_margin")


init -999 python:
    import cue_lib

    # ---- Store bridge: bind every name that remaining .rpy files reference ----
    # _cue lives in cue_lib.state — bound to store at init -900 below

    from cue_lib.constants import (
        CUE_SFX_CHANNEL_COUNT, CUE_DEFAULT_VIDEO_SPEED,
        CUE_POPPER_DEFAULT_OFFSET, CUE_POPPER_DEFAULT_MARGIN,
        CUE_SFX_LIBRARY_HEADER,
    )
    from cue_lib.util import (
        create_img_key as _cue_create_img_key,
        create_vid_key as _cue_create_vid_key,
        create_loop_key as _cue_create_loop_key,
        create_dlg_key as _cue_create_dlg_key,
        _cue_format_time, _cue_parse_time, _cue_clamp_time, _cue_speed_label,
        _cue_log, _cue_scan_audio, _cue_resolve_files, _cue_pick_file,
        _cue_unwrap_displayable, _cue_ui_refresh, _cue_is_screenshake,
        _cue_loop_still_playing, _cue_get_movie_or_image,
        _cue_top_layer_name, _cue_top_movie_name, _cue_get_movie_play,
        _cue_unwrap_persistent,
        _cue_make_tab_action,
    )

    from cue_lib.runtime import (
        _cue_toggle_overlay, _cue_show_overlay, _cue_hide_overlay,
        _cue_reload_presets,
        _cue_refresh_context, _cue_log_context, _cue_get_top_layer,
        _cue_refresh_channel, _cue_tick_trigger, _cue_play_sfx,
        _cue_preview_sfx, _cue_preview_preset, _cue_preview_folder, _cue_preview_video_preset, _cue_play_pool,
        _cue_toggle_active, _cue_toggle_settings, _cue_toggle_shake_trigger, _cue_toggle_video_mute,
        _cue_confirm_shared_dir,
    )

    from cue_lib.speed import (
        _cue_create_select_speed, _cue_create_delete_sel, _cue_create_delete_speed,
    )

    from cue_lib.dialogues import (
        CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog,
        _cue_confirm_delete_preset, _cue_confirm_delete_video_preset,
        _cue_maybe_apply_video_preset,
    )

    from cue_lib.popper import (
        CuePopper, _cue_store_focus_rect, _cue_clear_focus_rect,
        _cue_get_focus_rect, _cue_compute_popup_position, _cue_draw_arrow,
    )

    from cue_lib.ui.displayables import (
        CueSelfUpdatingLabel, CueVideoTimeline, CueVideoMarkerTimeline,
        CueTooltip, CueMarkerTooltipOverlay, CueAutoSpeedChart,
        CueKeyCaptureDisplayable,
    )

    from cue_lib.speed import (
        CueSpeedMode, CUE_TOAST_DURATION, CUE_TOAST_DURATION_SEAMLESS,
        CUE_TOAST_FADE_DURATION, CUE_TOAST_FADE_OFFSET,
    )
    from cue_lib.markers import CueLoopFrequency
    from cue_lib.auto_speed import (
        _cue_auto_preset_label, _cue_auto_preset_description,
    )
    from cue_lib.constants import (
        CUE_AUTO_SPEED_MIN_VARIANTS, CUE_AUTO_SPEED_IDEAL_VARIANTS, CUE_MULTI_SPEED_MIN_VARIANTS,
        CUE_KEYMAP_TOGGLE_OVERLAY, CUE_KEYMAP_QUIT_RELAUNCH,
        CUE_KEYMAP_COPY_CONTEXT, CUE_KEYMAP_PASTE_CONTEXT,
        CUE_KEYMAP_TOGGLE_ACTIVE, CUE_KEYMAP_PAUSE,
        CUE_KEYMAP_UNDO, CUE_KEYMAP_REDO,
        CUE_KEYMAP_SPEED_UP, CUE_KEYMAP_SPEED_DOWN,
        CUE_KEYMAP_TOGGLE_SFX,
        CUE_SHARED_KEY_KEYBINDS,
    )
    from cue_lib.keybinds import (
        CueKeybindsManager, _cue_keybind_start, _cue_keybind_cancel,
        _cue_keybind_reset, _cue_keybind_override,
    )
    from cue_lib.video_editor import CUE_VE_MODE_NORMAL, CUE_VE_MODE_INTERPOLATE, CUE_VE_MODE_FAST_PREVIEW


init -900 python:
    # Wire managers onto _cue.  Imports are lazy (inside the init block,
    # not at module level) to avoid circular refs — every manager module
    # does "from cue_lib.state import _cue", so state.py itself must not
    # import them.
    from cue_lib.markers import CueMarkerManager, CueLoopFrequency, CueExclusiveStart
    from cue_lib.undo import CueUndoManager
    from cue_lib.trigger import CueTriggerEngine
    from cue_lib.video import CueVideoManager
    from cue_lib.volume import CueVolumeManager
    from cue_lib.repeater import CueMarkerRepeater
    from cue_lib.ffmpeg import CueFFmpeg
    from cue_lib.video_editor import CueVideoEditor
    from cue_lib.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
    from cue_lib.auto_speed import CueAutoSpeedGenerator
    from cue_lib.file_tree import CueFileTreeManager
    from cue_lib.icons import CueIconManager
    from cue_lib.dialogues import CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog
    from cue_lib.db import CueDatabase
    from cue_lib.state import _cue

    _cue.markers = CueMarkerManager()
    _cue.undo = CueUndoManager()
    _cue.trigger = CueTriggerEngine()
    _cue.vid_manager = CueVideoManager()
    _cue.volume = CueVolumeManager()
    _cue.repeater = CueMarkerRepeater()
    _cue.ffmpeg = CueFFmpeg()
    _cue.video_editor = CueVideoEditor()
    _cue.speed_resolver = CueVidSpeedResolver()
    _cue.video_sequence = CueVidSpeedSequence()
    _cue.speed_toast = CueSpeedToast()
    _cue.auto_speed = CueAutoSpeedGenerator()
    _cue.file_tree = CueFileTreeManager()
    _cue.preset_dialog = CuePresetDialog()
    _cue.video_preset_dialog = CueVideoPresetDialog()
    _cue.confirm_dialog = CueConfirmDialog()
    _cue.keybinds = CueKeybindsManager()
    _cue.icons = CueIconManager()

    _cue.db = CueDatabase(_cue.shared_dir, renpy.config.save_directory)
    _cue.db.open()


init 999 python:
    # Enable dev tools for this mod (Shift+R reload, Shift+O console)
    config.developer = True
    config.console = True

    if _cue.debug:
        config.keymap['console'].append('shift_K_t')

    # Register cue keybinds and load any saved overrides from shared config.
    # Must run after config.keymap is fully populated (after the console
    # append above) so collision scanning sees all built-in entries.
    _cue.keybinds.setup()

    # Clear debug log for fresh session
    try:
        log_dir = os.path.join(renpy.config.gamedir, _cue.base_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        log_path = os.path.join(log_dir, _cue.debug_log_filename)
        open(log_path, "w").close()
    except Exception:
        pass

    # monkeypatch renpy.with_statement
    _original_with_statement = renpy.with_statement

    def _cue_with_hook(trans, always=False, paired=None, clear=True):
        if _cue_is_screenshake(trans):
            _cue._shake_just_happened = True
        return _original_with_statement(trans, always=always, paired=paired, clear=clear)

    renpy.with_statement = _cue_with_hook

    # Hook config.show to detect vpunch/hpunch applied as at-transforms
    # (e.g. "scene foo at vpunch, cum1").  When shakes are applied via "at"
    # instead of "with", they bypass with_statement entirely.
    _original_config_show = renpy.config.show

    def _cue_config_show(name, at_list=None, layer='master', what=None,
                            zorder=None, tag=None, behind=None, atl=None):
        if at_list:
            for t in at_list:
                if _cue_is_screenshake(t):
                    _cue._shake_just_happened = True
                    break
        return _original_config_show(name, at_list=at_list, layer=layer,
                                        what=what, zorder=zorder, tag=tag,
                                        behind=behind, atl=atl)

    renpy.config.show = _cue_config_show


    if not _cue.initialized:
        # Detect Ren'Py version for relative_volume support (added in 7.5)
        _v = getattr(renpy, 'version_tuple', (0, 0, 0))
        _cue._has_relative_volume = (_v >= (7, 5, 0))
        _cue_log("INIT: renpy_version={} relative_volume={}".format(
            ".".join(str(x) for x in _v), _cue._has_relative_volume))

        # Register 8 dedicated SFX channels on the "sfx" mixer
        for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
            ch_name = "_cue_{}".format(i)
            if not renpy.music.channel_defined(ch_name):
                renpy.music.register_channel(
                    ch_name, "sfx", loop=False, stop_on_mute=True, tight=False
                )

        # Create a layer above screens for the Cue UI.
        renpy.add_layer("cue_layer", above="screens")

        # Register after_load callback
        def _cue_after_load():
            if _cue.is_overlay_visible:
                _cue.is_overlay_visible = False
                _cue.vid_manager.reset_pause()

        config.after_load_callbacks.append(_cue_after_load)

        # Character callback — updates dialogue text only (context change
        # detection now lives in start_interact_callbacks below).
        def _cue_char_callback(event, interact=True, **kwargs):
            if event == "show":
                _cue.prev_dialogue = _cue.current_dialogue
                _cue.current_dialogue = getattr(store, '_last_say_what', '')
            elif event == "end":
                _cue.prev_dialogue = _cue.current_dialogue
                _cue.current_dialogue = ""

        config.all_character_callbacks.append(_cue_char_callback)

        # start_interact callback — detects context changes at interaction
        def _cue_start_interact_callback(*args, **kwargs):
            # Ensure key listeners are always active.
            if not renpy.get_screen("cue_key_listener", layer="cue_layer"):
                renpy.show_screen("cue_key_listener", _layer="cue_layer")
            # Keep overlay screen in sync with the NoRollback flag.
            # Rollback can undo renpy.hide_screen, so re-hide when the
            # flag says the overlay should not be visible.
            if _cue.is_overlay_visible and not renpy.get_screen("cue_overlay", layer="cue_layer"):
                renpy.show_screen("cue_overlay", _layer="cue_layer")
            elif not _cue.is_overlay_visible and renpy.get_screen("cue_overlay", layer="cue_layer"):
                renpy.hide_screen("cue_overlay", layer="cue_layer")

            _cue_refresh_context()

        config.start_interact_callbacks.append(_cue_start_interact_callback)

        # Load markers from persistent so SFX work immediately (before overlay is ever opened)
        _cue.markers.load_persistent()
        _cue.video_editor.job_queue.load_from_persistent()
        _cue.undo.seed()  # seed undo baseline after initial load
        _cue.speed_resolver.wrap_all_movies()
        _cue_scan_audio()

        _cue.initialized = True
        _cue_log("INIT: Done")
