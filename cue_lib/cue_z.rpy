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

python early:
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

    from cue_lib.util import (
        create_img_key, create_vid_key, create_loop_key, create_dlg_key,
        is_img_key, is_vid_key, is_dlg_key, is_loop_key,
        get_key_file, get_key_dialogue, get_key_prefix,
        _cue_format_time, _cue_parse_time, _cue_clamp_time, _cue_speed_label,
        _cue_log, _cue_scan_audio, _cue_resolve_files, _cue_pick_file,
        _cue_unwrap_displayable, _cue_ui_refresh, _cue_is_screenshake,
        _cue_loop_still_playing, _cue_get_movie_or_image,
        _cue_top_layer_name, _cue_top_movie_name, _cue_get_movie_play,
        _cue_unwrap_persistent,
    )

    from cue_lib.runtime import (
        _cue_TEST, _cue_toggle_overlay, _cue_show_overlay, _cue_hide_overlay,
        _cue_reload_presets,
        _cue_refresh_context, _cue_log_context, _cue_get_top_layer,
        _cue_refresh_channel, _cue_tick_trigger, _cue_play_sfx,
        _cue_preview_sfx, _cue_preview_preset, _cue_play_pool,
        _cue_toggle_active, _cue_toggle_shake_trigger,
    )

    from cue_lib.speed import (
        _cue_seq_btn_hovered, _cue_seq_popup_dismiss,
        _cue_seq_delete, _cue_seq_move_left, _cue_seq_move_right,
    )

    from cue_lib.ui_logic import (
        CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog,
        _cue_make_tab_action, _cue_count_file_list_rows,
        _cue_confirm_delete_preset, _cue_confirm_delete_video_preset,
        _cue_maybe_apply_video_preset, _cue_preview_video_preset,
        _cue_detach_active_video_ts, _cue_detach_pool_at,
    )

    from cue_lib.popper import (
        CuePopper, _cue_store_focus_rect, _cue_clear_focus_rect,
        _cue_get_focus_rect, _cue_compute_popup_position, _cue_draw_arrow,
        ARROW_SZ,
    )

    from cue_lib.displayables import (
        SelfUpdatingLabel, VideoTimeline, CueVideoMarkerTimeline,
        _Tooltip, _MarkerTooltipOverlay,
    )

    from cue_lib.speed import SpeedMode
    from cue_lib.video_editor import CUE_VE_MODE_NORMAL, CUE_VE_MODE_INTERPOLATE, CUE_VE_MODE_FAST_PREVIEW


init -900 python:
    from cue_lib import state
    state.bootstrap()
    from cue_lib.state import _cue


init 999 python:
    # Enable dev tools for this mod (Shift+R reload, Shift+O console)
    config.developer = True
    config.console = True

    config.keymap['console'].append('shift_K_t')

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
        for i in range(1, 9):
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
