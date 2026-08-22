###############################################################################
# Cue — bootstrap and wiring.
# .py modules live in cue_lib/; this file has ONLY the init blocks needed
# to import the import, bridge names into the Ren'Py store for screens,
# and run the one-time runtime setup.
###############################################################################

python early:
    import sys
    import os

    _cue_lib_parent = os.path.join(renpy.config.gamedir, "renpy_cue")
    if _cue_lib_parent not in sys.path:
        sys.path.insert(0, _cue_lib_parent)

    def _cue_popper_factory(*args, **kwargs):
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

    def _cue_make_etext(*args, **kwargs):
        return CueSafeText(*args, **kwargs)

    # etext -- a 1:1 mirror of the built-in text statement (same positional,
    # keywords and properties) whose displayable escapes the value first.
    renpy.register_sl_displayable(
        "etext",
        _cue_make_etext,
        style="text",
        nchildren=0,
        scope=True,
        replaces=True,
    ).add_positional("text") \
        .add_property("slow") \
        .add_property("slow_done") \
        .add_property("substitute") \
        .add_property("scope") \
        .add_property_group("text")


init -999 python:
    import cue_lib

    # ---- Store bridge: bind every name that remaining .rpy files reference ----
    # _cue lives in cue_lib.state — bound to store at init -900 below

    from cue_lib.constants import (
        CuePage, CueLoopFrequency, CueContextType,
        CueImportCategory, CueImportMatch, CueExportScope,
        CueExportFileTypes,
        CUE_DEBUG, CUE_SFX_CHANNEL_COUNT,
        CUE_DEFAULT_VIDEO_SPEED,
        CUE_SFX_LIBRARY_HEADER, CUE_AUDIO_EXTS,
        CUE_HELP_SHIFT_SKIP_DELETE,
        CUE_MANUAL_BACKUP_NAME,
        CUE_IMPORT_CATEGORY_ORDER, CUE_IMPORT_CATEGORY_LABELS,
    )
    from cue_lib.util import (
        create_img_key as _cue_create_img_key,
        create_vid_key as _cue_create_vid_key,
        create_loop_key as _cue_create_loop_key,
        create_dlg_key as _cue_create_dlg_key,
        _cue_format_time, _cue_parse_time, _cue_clamp_time, _cue_speed_label,
        _cue_format_size, _cue_format_duration, _cue_escape_text,
        _cue_log, _cue_resolve_files, _cue_pick_file, _cue_query_matches,
        _cue_unwrap_displayable, _cue_ui_refresh,
        _cue_wrap_with_statement, _cue_wrap_config_show,
        _cue_strip_key_prefix,
        _cue_top_layer_name, _cue_top_movie_name, _cue_get_movie_play,
        _cue_unwrap_persistent,
        _cue_make_tab_action,
    )

    from cue_lib.ui.sl_statements.text import CueSafeText

    from cue_lib.logger import (
        _cue_logger,
    )

    from cue_lib.audio.sfx_manager import (
        _cue_sfx_channel_name,
    )

    from cue_lib.runtime import (
        _cue_toggle_overlay, _cue_show_overlay, _cue_hide_overlay,
        _cue_full_reload,
        _cue_refresh_context, _cue_log_context, _cue_get_top_layer,
        _cue_refresh_channel, _cue_tick_trigger,
        _cue_preview_music_preset,
        _cue_set_page,
        _cue_toggle_video_mute,
    )

    from cue_lib.video.speed import (
        _cue_create_select_speed, _cue_create_delete_sel, _cue_create_delete_speed,
    )

    from cue_lib.markers import (
        _cue_load_scalars_from_persistent,
        _cue_markers_send, _cue_target_assign_tt,
    )

    from cue_lib.ui.dialogs import (
        CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog,
        _cue_confirm_delete_preset, _cue_confirm_delete_video_preset,
        _cue_confirm_delete_music_preset, _cue_confirm_delete_igroup,
        _cue_maybe_apply_video_preset,
    )

    from cue_lib.ui.popper import (
        CuePopper, _cue_store_focus_rect, _cue_clear_focus_rect,
        _cue_get_focus_rect, _cue_compute_popup_position, _cue_draw_arrow,
    )

    from cue_lib.ui.displayables import (
        CueSelfUpdatingLabel, CueVideoTimeline, CueVideoMarkerTimeline,
        CueTooltip, CueVideoMarkerTooltip, CueAutoSpeedChart,
        CueKeyCaptureDisplayable,
    )

    from cue_lib.video.speed import (
        CueSpeedMode, CUE_TOAST_DURATION, CUE_TOAST_DURATION_SEAMLESS,
        CUE_TOAST_FADE_DURATION, CUE_TOAST_FADE_OFFSET,
    )
    from cue_lib.video.auto_speed import (
        _cue_auto_preset_label, _cue_auto_preset_description,
    )
    from cue_lib.constants import (
        CUE_AUTO_SPEED_MIN_VARIANTS, CUE_AUTO_SPEED_IDEAL_VARIANTS,
        CUE_KEYMAP_TOGGLE_OVERLAY, CUE_KEYMAP_QUIT_RELAUNCH,
        CUE_KEYMAP_COPY_CONTEXT, CUE_KEYMAP_PASTE_CONTEXT,
        CUE_KEYMAP_TOGGLE_SFX_ACTIVE, CUE_KEYMAP_PAUSE,
        CUE_KEYMAP_UNDO, CUE_KEYMAP_REDO,
        CUE_KEYMAP_SPEED_UP, CUE_KEYMAP_SPEED_DOWN,
        CUE_KEYMAP_TOGGLE_SFX_LIBRARY,
        CUE_KEYMAP_TOGGLE_SFX_OVERLAY,
        CUE_KEYMAP_PAGE_SFX, CUE_KEYMAP_PAGE_MUSIC,
        CUE_KEYMAP_PAGE_IMPORT, CUE_KEYMAP_PAGE_SETTINGS,
        CUE_KEYMAP_TARGET_VIDEO, CUE_KEYMAP_TARGET_IMAGE,
        CUE_KEYMAP_TARGET_DIALOGUE, CUE_KEYMAP_TARGET_LOOP,
    )
    from cue_lib.keybinds import (
        CueKeybindsManager, _cue_keybind_start, _cue_keybind_cancel,
        _cue_keybind_reset, _cue_keybind_override,
    )
    from cue_lib.video.video_edit_queue import (
        CUE_VE_MODE_NORMAL, CUE_VE_MODE_INTERPOLATE, CUE_VE_MODE_FAST_PREVIEW,
        CueJobStatus,
    )


init -900 python:
    # Wire managers onto _cue.  Imports are lazy (inside the init block,
    # not at module level) to avoid circular refs — every manager module
    # does "from cue_lib.state import _cue", so state.py itself must not
    # import them.
    from cue_lib.marker_store import CueMarkerStore
    from cue_lib.markers import CueMarkerManager
    from cue_lib.undo import CueUndoManager
    from cue_lib.trigger import CueTriggerEngine
    from cue_lib.video.video import CueVideoManager
    from cue_lib.volume import CueVolumeManager
    from cue_lib.audio.music import CueMusicManager
    from cue_lib.video.repeater import CueMarkerRepeater
    from cue_lib.video.ffmpeg import CueFFmpeg
    from cue_lib.video.video_editor import CueVideoEditor
    from cue_lib.video.speed import CueVidSpeedResolver, CueVidSpeedSequence, CueSpeedToast
    from cue_lib.video.auto_speed import CueAutoSpeedGenerator
    from cue_lib.audio.sfx_manager import CueSfxManager
    from cue_lib.audio.recent import CueRecentManager, _cue_keep_sfx, _cue_keep_music
    from cue_lib.ui.icons import CueIconManager
    from cue_lib.ui.dialogs import (
        CuePresetDialog, CueVideoPresetDialog, CueConfirmDialog, CueMergeDialog,
        CueIntensityGroupDialog,
    )
    from cue_lib.intensity import CueIntensityManager
    from cue_lib.importer import CueImportManager
    from cue_lib.exporter import CueExportManager
    from cue_lib.url_importer import CueUrlImporter
    from cue_lib.settings import CueSettings
    from cue_lib.backup import CueBackupManager
    from cue_lib.db import CueDatabase
    from cue_lib.paths import CuePaths
    from cue_lib.state import _cue

    def _cue_wire_managers():
        """Build every manager as a function-local, in dependency order, then
        hand them to _cue in one assignment block.  Locals, not store vars, so
        the wiring leaves no footprint on the game's store namespace."""
        paths = CuePaths(CuePaths.resolve_root(), renpy.config.save_directory)

        backups = CueBackupManager(paths)
        db = CueDatabase(paths, backups)
        db.open()

        # The marker store owns the data layer; the manager coordinates around
        # it.  on_save closes over the undo local (late-bound: undo is built
        # below, but capture only runs on DB writes, after wiring completes).
        marker_store = CueMarkerStore(db, paths, lambda: undo.capture())

        vid_manager = CueVideoManager(_cue.ctx)
        volume = CueVolumeManager(_cue.ctx, marker_store)
        video_sequence = CueVidSpeedSequence(_cue.ctx, marker_store, vid_manager)
        speed_toast = CueSpeedToast()
        speed_resolver = CueVidSpeedResolver(
            _cue.ctx, marker_store, vid_manager,
            video_sequence, speed_toast, paths)
        auto_speed = CueAutoSpeedGenerator(
            _cue.ctx, marker_store, speed_resolver,
            vid_manager, video_sequence)

        # speed_resolver and auto_speed both take the sequence in their
        # constructors (a cycle), so the sequence late-binds them here.
        video_sequence.bind(speed_resolver, auto_speed)
        repeater = CueMarkerRepeater(_cue.ctx, marker_store, vid_manager)
        ffmpeg = CueFFmpeg()
        video_editor = CueVideoEditor(
            _cue.ctx, ffmpeg, speed_resolver,
            vid_manager, paths)

        undo = CueUndoManager(_cue.ctx, marker_store)
        trigger = CueTriggerEngine(
            marker_store, repeater, speed_resolver, vid_manager)
        sfx_manager = CueSfxManager(
            paths, db, volume, _cue.ctx, _cue._has_relative_volume)

        settings = CueSettings()
        keybinds = CueKeybindsManager(db)
        icons = CueIconManager(paths)
        music = CueMusicManager(_cue.ctx, marker_store, db, paths)
        
        # importer swaps the effective root while active and reloads via the
        # store-global full reload; exporter and merge_dialog complete the
        # import/export set.
        importer = CueImportManager(paths, db, _cue_full_reload)
        exporter = CueExportManager(paths)
        url_importer = CueUrlImporter(importer)

        merge_dialog = CueMergeDialog(importer)
        preset_dialog = CuePresetDialog()
        video_preset_dialog = CueVideoPresetDialog()
        confirm_dialog = CueConfirmDialog()
        intensity = CueIntensityManager(db)
        igroup_dialog = CueIntensityGroupDialog()

        # markers is the coordinator, wired LAST so every injected collaborator
        # (vid_manager, sfx_manager, trigger, video_editor) is already
        # constructed.  The store is its data layer; ctx carries the per-scene
        # context state.
        markers = CueMarkerManager(
            _cue.ctx, marker_store, vid_manager,
            sfx_manager, trigger, video_editor)

        # markers and sfx_manager take each other at construction -- break the
        # cycle with the same late-bind pattern as video_sequence.bind.
        sfx_manager.bind_markers(markers)

        # The "Recently Used" list lives on the SFX library tree: it records
        # SFX send_* attempts (the marker contexts funnel through
        # sfx_manager.library._recent).  Its prune existence check reads both
        # sfx_manager.library.files and markers.list_presets() at call time, so it is
        # built here where both are in scope.
        sfx_manager.library._recent = CueRecentManager(
            "recent_entries",
            lambda kind, ref: _cue_keep_sfx(kind, ref, sfx_manager.library.files, markers.list_presets()))
        # The SFX library tree's scoped click-and-drop commits through the
        # intensity manager; late-bound here (same pattern as _recent) so the
        # tree only needs its own constructors at build time.
        sfx_manager.library._intensity = intensity

        # Music's "Recently Used" list lives on the music manager: it records
        # add-to-trigger attempts through music's own _add_ref_to_trigger funnel.
        # Its prune existence check reads the two sub-managers' .files at call
        # time, so it is built here and only loaded once both scans ran.
        music._recent = CueRecentManager(
            "recent_music_entries",
            lambda kind, ref: _cue_keep_music(kind, ref, music.user_music, music.game_music))

        _cue.paths = paths
        _cue.db = db
        _cue.intensity = intensity
        _cue.markers = markers
        _cue.marker_store = marker_store

        _cue.vid_manager = vid_manager
        _cue.video_sequence = video_sequence
        _cue.video_editor = video_editor
        _cue.ffmpeg = ffmpeg
        _cue.speed_toast = speed_toast
        _cue.speed_resolver = speed_resolver
        _cue.auto_speed = auto_speed
        _cue.repeater = repeater

        _cue.trigger = trigger
        _cue.sfx = sfx_manager
        _cue.music = music
        _cue.volume = volume

        _cue.dialogs.preset = preset_dialog
        _cue.dialogs.video_preset = video_preset_dialog
        _cue.dialogs.confirm = confirm_dialog
        _cue.dialogs.merge = merge_dialog
        _cue.dialogs.intensity = igroup_dialog

        _cue.settings = settings
        _cue.keybinds = keybinds
        _cue.icons = icons
        _cue.undo = undo

        _cue.backups = backups
        backups.wire(db, markers._reload_after_restore, confirm_dialog)

        _cue.importer = importer
        _cue.exporter = exporter
        _cue.url_importer = url_importer

    _cue_wire_managers()


init 999 python:
    if CUE_DEBUG:
        # Enable dev tools for this mod (Shift+R reload, Shift+O console)
        config.developer = True
        config.console = True
        config.keymap['console'].append('shift_K_t')

    def _cue_patch_runtime():
        """Reinstall the Ren'Py monkey patches.  Runs on every init (including
        Shift+R reload), because Ren'Py rebuilds config fresh on reload."""

        renpy.with_statement = _cue_wrap_with_statement(renpy.with_statement)
        renpy.config.show = _cue_wrap_config_show(renpy.config.show)

        import renpy.loader as _rl

        if not getattr(_rl.load, "_cue_loader_wrapped", False):
            _cue_orig_loader_load = _rl.load
            _cue_orig_loader_loadable = _rl.loadable
            _cue_orig_loader_open = _rl.open_file

            def _cue_loader_load(name, *args, **kwargs):
                try:
                    if os.path.isabs(name) and os.path.isfile(name):
                        return _cue_orig_loader_open(name, "rb")
                except (TypeError, ValueError):
                    pass
                return _cue_orig_loader_load(name, *args, **kwargs)

            def _cue_loader_loadable(name, *args, **kwargs):
                try:
                    if os.path.isabs(name) and os.path.isfile(name):
                        return True
                except (TypeError, ValueError):
                    pass
                return _cue_orig_loader_loadable(name, *args, **kwargs)

            _rl.load = _cue_loader_load
            _rl.loadable = _cue_loader_loadable
            _rl.load._cue_loader_wrapped = True

    def _cue_install_callbacks():
        """SFX channels, the overlay layer, and the game hooks (after-load /
        character / start-interact / replay).  Reinstalled on every init, like
        the patches: reload_all() restores renpy.* modules to their
        post-import state, wiping the config callback lists too."""
        
        # Register 8 dedicated SFX channels on the "sfx" mixer
        for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
            ch_name = _cue_sfx_channel_name(i)
            if not renpy.music.channel_defined(ch_name):
                renpy.music.register_channel(
                    ch_name, "sfx", loop=False, stop_on_mute=True, tight=False
                )

        # Create a layer above screens for the Cue UI, as a top layer so
        # scene transitions (with fade) never capture or transition it.
        config.top_layers.append("cue_layer")
        config.menu_clear_layers.append("cue_layer")

        def _cue_after_load():
            if _cue.is_overlay_visible:
                _cue.is_overlay_visible = False
                _cue.vid_manager.reset_pause()

        config.after_load_callbacks.append(_cue_after_load)

        def _cue_char_callback(event, interact=True, **kwargs):
            if event == "show":
                _cue.ctx.prev_dialogue = _cue.ctx.current_dialogue
                _cue.ctx.current_dialogue = getattr(store, '_last_say_what', '')
            elif event == "end":
                _cue.ctx.prev_dialogue = _cue.ctx.current_dialogue
                _cue.ctx.current_dialogue = ""

        config.all_character_callbacks.append(_cue_char_callback)

        # start_interact callback — detects context changes at interaction
        def _cue_start_interact_callback(*args, **kwargs):
            # Ensure the runtime driver is always active.
            if not renpy.get_screen("cue_runtime_driver", layer="cue_layer"):
                renpy.show_screen("cue_runtime_driver", _layer="cue_layer")
            # Keep overlay screen in sync with the NoRollback flag.
            # Rollback can undo renpy.hide_screen, so re-hide when the
            # flag says the overlay should not be visible.
            if _cue.is_overlay_visible and not renpy.get_screen("cue_overlay", layer="cue_layer"):
                renpy.show_screen("cue_overlay", _layer="cue_layer")
            elif not _cue.is_overlay_visible and renpy.get_screen("cue_overlay", layer="cue_layer"):
                renpy.hide_screen("cue_overlay", layer="cue_layer")

            _cue_refresh_context()

        config.start_interact_callbacks.append(_cue_start_interact_callback)

        _cue_original_after_replay = config.after_replay_callback

        def _cue_after_replay():
            _cue.sfx.fade_out()
            if _cue_original_after_replay is not None:
                _cue_original_after_replay()

        config.after_replay_callback = _cue_after_replay

    def _cue_load_initial_data():
        """Hydrate the freshly-wired managers from persistent/shared config and
        prime the SFX/music libraries.  Runs once, right after callbacks."""
        _cue_full_reload()
        _cue.video_editor.job_queue.load_from_persistent()
        _cue.speed_resolver.wrap_all_movies()
        _cue.music.install()

        _cue.initialized = True

    
    _v = getattr(renpy, "version_tuple", (0, 0, 0))
    _cue_log("INIT: renpy_version={}".format(".".join(str(x) for x in _v)))

    _cue_logger.clear_debug()
    _cue_logger.clear_error()
    _cue.keybinds.setup()
    _cue_patch_runtime()
    _cue_install_callbacks()

    if not _cue.initialized:
        _cue_load_initial_data()
        _cue_log("INIT: Done")
