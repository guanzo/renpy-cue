# Legacy (7.x) testcases -- old Ren'Py test DSL. No testsuite/hooks/keysym/
# advance, and `renpy test <name>` runs ONE testcase per invocation. There is
# no reporter on 7.x and the process exits 0 even on failure, so assertions
# call renpy.quit(status=1) to surface a nonzero exit code.
#
# `run Jump("start")` uses the store Jump action (deferred, one-shot): it
# jumps the game to label start, whose say statement opens a fresh interact
# and re-fires start_interact_callbacks -- which is what shows the overlay.
#
# There is no `keysym` DSL statement on 7.x, so keys are posted via
# renpy.test.testkey. Note: 7.4's testkey maps K_ESCAPE to the literal
# "\e" (backslash-e, 2 chars in Python 2, where "\e" isn't an escape), so
# get_keycode() crashes on `ord(u) < 32`. Patch the map to the real ESC
# control char first -- down() and up() both read it.

# Runs after the mod's init 999 (which hydrates seamless_transition from
# persistent): video_seamless_transition_preserves_position leaves it on via
# persistent, so a later run's video_sfx_edit_locked_off_base_speed would
# start with set_speed in queue mode -- it needs the 1.5x variant to exist and
# never writes the pref, so the assertion sees the base speed.
init 1000 python:
    # Reset trigger/context state so each testcase starts clean.  Legacy forks
    # a fresh process per testcase, so this is belt-and-suspenders, but the
    # direct marker seeding below writes no disk state and reads no leaked
    # state -- the fields exist across both DSLs.
    def _cue_test_reset():
        _cue.trigger.active = True
        _cue.trigger.last_played = []
        _cue.trigger.played_video_keys.clear()
        _cue.trigger.loop_states = {}
        _cue.trigger.excl_channels.clear()
        _cue.trigger._prev_eff_elapsed = -1.0
        _cue.current_file = ""
        _cue.current_dialogue = ""
        _cue.prev_dialogue = ""
        _cue.ctx._shake_just_happened = False
        _cue.vid_manager.last_elapsed = 0.0
        # The test game's start label never clears the scene, so a prior
        # testcase's displayable stays on the master layer.  Re-showing a
        # different image then puts the new one BELOW the stale top entry and
        # fire_context never sees the intended change.  Clear the layer so each
        # show is a genuine context change (mirrors a real game's scene cut).
        renpy.scene()

    # Runtime intensity fixtures: create real soft//hard//empty/ level folders
    # under the audio dir (and remove them again) so the resolver and fire-path
    # testcases exercise real folders, not just in-memory refs.  hard/ gets two
    # files so _cue_pick_file takes the avoid-repeats branch and records the
    # fire in last_played (a single-file list never records it).
    def _cue_intensity_folders():
        import os as _os
        import shutil as _shutil
        _ad = _cue.paths.audio_dir
        for _name in ("soft", "hard", "empty"):
            _dir = _ad + _name
            if not _os.path.isdir(_dir):
                _os.makedirs(_dir)
        _shutil.copy2(_ad + "sfx_001.ogg", _ad + "soft/sfx_001.ogg")
        _shutil.copy2(_ad + "sfx_001.ogg", _ad + "hard/sfx_001.ogg")
        _shutil.copy2(_ad + "sfx_002.ogg", _ad + "hard/sfx_002.ogg")
        _cue.sfx.library.scan()

    def _cue_intensity_cleanup():
        import os as _os
        import shutil as _shutil
        _ad = _cue.paths.audio_dir
        for _name in ("soft", "hard", "empty"):
            _shutil.rmtree(_ad + _name, ignore_errors=True)
        _cue.sfx.library.scan()

    def _cue_intensity_toggle_folders():
        # Like _cue_intensity_folders, but soft/ also gets a second file so
        # fires FROM soft/ are recorded in last_played (a single-file list
        # never records a pick).  Used by the per-video toggle testcases.
        _cue_intensity_folders()
        import shutil as _shutil
        _shutil.copy2(_cue.paths.audio_dir + "sfx_002.ogg", _cue.paths.audio_dir + "soft/sfx_002.ogg")
        _cue.sfx.library.scan()

    def _cue_played_from(folder):
        # True once last_played recorded a fire picked from folder (a resolved
        # intensity level folder, e.g. "hard/").
        return any(_p.startswith(folder) for _p in _cue.trigger.last_played)

    # Zero-arg predicate for the legacy wait waiter (7.x can't wait on a bare
    # predicate -- see the init -10 waiter).
    def _cue_intensity_fired():
        return _cue_played_from("hard/")

    def _cue_intensity_soft_fired():
        return _cue_played_from("soft/")

    # The video_seamless testcase re-enables it itself.
    _cue.speed_resolver.seamless_transition = False

init -10 python:
    # The legacy test DSL cannot wait on an arbitrary predicate (`until` only
    # checks UI focus / action sensitivity), and a fixed pause races slow 7.x
    # movie startup under xvfb -- video_marker_fires_at_ts flaked on CI when
    # the movie hadn't reached elapsed > 0 within the pause.  `pause N until
    # run _cue_test_wait_until_true(...)` polls the predicate every frame via
    # the Action's get_sensitive(); after `deadline` it reports ready anyway so
    # the testcase fails on its own assertions below instead of hanging the
    # engine (a never-yielding executor gets no test-level timeout).
    import time as _test_time

    class CueTestWaitUntilTrue(renpy.ui.Action):
        def __init__(self, predicate, deadline):
            self.predicate = predicate
            self.deadline = deadline

        def get_sensitive(self):
            if self.predicate():
                return True
            return _test_time.time() >= self.deadline

        def __call__(self):
            return None

    def _cue_test_wait_until_true(predicate, deadline):
        return CueTestWaitUntilTrue(predicate, deadline)

    def _cue_vid_marker_ready():
        return (
            _cue.top_layer_type == "movie"
            and _cue.vid_manager.get_duration() > 0
            and _cue.vid_manager.get_elapsed() > 0.0
            and len(_cue.trigger.played_video_keys) >= 1
        )

    def _cue_io_idle():
        # Refresh/export/scan each run on a background thread; the roundtrip
        # must wait for the snapshot swap before acting on its results.
        return (
            not _cue.exporter.is_refreshing
            and not _cue.exporter.is_exporting
            and not _cue.importer.is_scanning
        )

testcase overlay_shows_on_start:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ if not renpy.get_screen("cue_overlay", layer="cue_layer"): renpy.quit(status=1)
    $ renpy.quit()

testcase page_nav:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    run Function(_cue_set_page, CuePage.MUSIC)
    $ if not (_cue.overlay_active_page == CuePage.MUSIC): renpy.quit(status=1)
    $ renpy.quit()

testcase import_page_nav:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    # _cue_set_page(IMPORT) scans imports/ and refreshes the export categories
    # before the page renders.  A compile error in the import/export page
    # fails this interaction.
    run Function(_cue_set_page, CuePage.IMPORT)
    pause 0.5
    $ if not (_cue.overlay_active_page == CuePage.IMPORT): renpy.quit(status=1)
    $ renpy.quit()

testcase import_banner_render:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    # An active package swaps the editor to the import and the toolbar shows
    # the edit banner (the click-swallowing shield was dropped).  Set the
    # active state directly -- the export/scan/activate path is covered by the
    # roundtrip testcase.  Rendering the SFX page under this state is the
    # smoke test: a broken banner screen fails this interaction.
    $ _cue.importer.is_active = True
    $ _cue.importer.active_import = "ShieldPkg"
    run Function(_cue_set_page, CuePage.SFX)
    pause 0.5
    $ _ok = _cue.overlay_active_page == CuePage.SFX
    $ _ok = _ok and _cue.importer.active_import_name() == "ShieldPkg"
    $ _ok = _ok and renpy.get_screen("cue_overlay", layer="cue_layer") is not None
    run Function(_cue.importer.deactivate)
    $ _ok = _ok and not _cue.importer.is_active
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase import_export_roundtrip:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    # Local harness runs leave exports/ + imports/ residue (the script only
    # wipes data/backups/video), so clear both dirs first -- the export name
    # and the copied .zip must be deterministic.
    $ import os as _os
    $ import shutil as _shutil
    $ _shutil.rmtree(_cue.exporter.exports_dir(), ignore_errors=True)
    $ _shutil.rmtree(_cue.importer.imports_dir(), ignore_errors=True)
    # The shared-root fixtures carry audio/, so the SFX category is non-empty.
    run Function(_cue.exporter.refresh)
    $ _deadline = _test_time.time() + 15.0
    pause 0.1 until run _cue_test_wait_until_true(_cue_io_idle, _deadline)
    $ _cue.exporter.name = "Roundtrip"
    run Function(_cue.exporter.export)
    # Refresh + zip build run on background threads; wait for the snapshot swap.
    $ _deadline = _test_time.time() + 15.0
    pause 0.1 until run _cue_test_wait_until_true(_cue_io_idle, _deadline)
    $ _ok = _cue.exporter.export_error == ""
    $ _ok = _ok and _cue.exporter.export_status != ""
    # A recipient drops the .zip into imports/; scan() auto-extracts it and
    # matches it to this game (same game_id -> AUTO).
    $ _zip_src = _os.path.join(_cue.exporter.exports_dir(), "Roundtrip.zip")
    $ _zip_dst = _os.path.join(_cue.importer.imports_dir(), "Roundtrip.zip")
    $ _os.makedirs(_cue.importer.imports_dir())
    $ _shutil.copy(_zip_src, _zip_dst)
    run Function(_cue.importer.scan)
    # Scan (list + extract + manifest read) also runs on a background thread.
    $ _deadline = _test_time.time() + 15.0
    pause 0.1 until run _cue_test_wait_until_true(_cue_io_idle, _deadline)
    $ _ok = _ok and len(_cue.importer.imports) == 1
    $ _ok = _ok and _cue.importer.imports[0]["valid"]
    $ _ok = _ok and _cue.importer.imports[0]["match"] == CueImportMatch.AUTO
    # The merge dialog opens on the scanned package and renders its category
    # rows + overwrite summary.
    run Function(_cue.dialogs.merge.open, "Roundtrip")
    pause 0.5
    $ _ok = _ok and renpy.get_screen("cue_merge_dialog", layer="cue_layer") is not None
    run Function(_cue.dialogs.merge.cancel)
    pause 0.5
    $ _ok = _ok and renpy.get_screen("cue_merge_dialog", layer="cue_layer") is None
    # Activate serves the whole editor from the extracted package: the
    # effective root follows.
    run Function(_cue.importer.activate, "Roundtrip")
    $ _ok = _ok and _cue.importer.is_active
    $ _ok = _ok and _cue.paths.root.endswith("Roundtrip")
    # Deactivate drops back to the live data tree.
    run Function(_cue.importer.deactivate)
    $ _ok = _ok and not _cue.importer.is_active
    $ _ok = _ok and _cue.paths.root == _cue.paths.original_root
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase confirm_dialog_escape:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    run Function(_cue.dialogs.confirm.show, "Really?", _cue_hide_overlay)
    pause 0.5
    $ if not renpy.get_screen("cue_confirm_dialog", layer="cue_layer"): renpy.quit(status=1)
    $ import pygame_sdl2
    $ import renpy.test.testkey as _testkey
    $ _testkey.code_to_unicode[pygame_sdl2.K_ESCAPE] = "\x1b"
    $ _testkey.down(None, "ESCAPE")
    $ _testkey.up(None, "ESCAPE")
    pause 0.5
    $ if renpy.get_screen("cue_confirm_dialog", layer="cue_layer"): renpy.quit(status=1)
    $ renpy.quit()

testcase sfx_library_rows:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _ok = len(_cue.sfx.library.files) >= 2 and _cue.sfx.library.scan_error == ""
    $ _ok = _ok and "sfx_001.ogg" in _cue.sfx.library.files
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase sfx_file_tree_expand:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    run Function(_cue.sfx.library.toggle_folder, "Sub/")
    $ if not _cue.sfx.library.expanded_folders.get("Sub/", False): renpy.quit(status=1)
    $ renpy.quit()

testcase music_my_music_rows:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _ok = len(_cue.music.user_music.files) >= 1
    $ _ok = _ok and _cue.music.user_music.files[0].startswith("music/")
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase audio_presets_list:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    $ _ok = "Test Preset" in _cue.markers.list_presets()
    $ _ok = _ok and _cue.markers.get_preset("Test Preset")["files"] == ["sfx_001.ogg"]
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase intensity_groups_crud:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    # Registry CRUD + add-folder mode: enable per-group, add a tree folder.
    run Function(_cue.intensity.create_igroup, "Test Impacts")
    $ _ok = "Test Impacts" in _cue.intensity.list_igroups()
    $ _ok = _ok and _cue.intensity.get_igroup("Test Impacts")["folders"] == []
    run Function(_cue.sfx.library.toggle_igroup_add_mode, "Test Impacts")
    $ _ok = _ok and _cue.sfx.library.igroup_add_target == "Test Impacts"
    run Function(_cue.sfx.library.igroup_add_folder, "Test Impacts", "Sub/")
    $ _ok = _ok and _cue.intensity.get_igroup("Test Impacts")["folders"] == ["Sub/"]
    $ _ok = _ok and _cue.intensity.get_igroup("Test Impacts")["volume_multipliers"] == [1.0]
    $ _ok = _ok and _cue.intensity.add_folder("Test Impacts", "Sub/") is not None
    run Function(_cue.sfx.library.toggle_igroup_add_mode, "Test Impacts")
    $ _ok = _ok and _cue.sfx.library.igroup_add_target is None
    # Block + group rows compile and render on the SFX page.
    run Function(_cue.sfx.library.toggle_igroups_expand)
    $ _ok = _ok and _cue.sfx.library.igroups_expanded
    run Function(_cue.sfx.library.toggle_igroup_expand, "Test Impacts")
    $ _ok = _ok and _cue.sfx.library.expanded_igroups.get("Test Impacts", False)
    run Function(_cue_set_page, CuePage.SFX)
    pause 0.5
    # Add-mode branches render: folder-open icon + tree + becomes an adder.
    run Function(_cue.sfx.library.toggle_igroup_add_mode, "Test Impacts")
    pause 0.5
    run Function(_cue.sfx.library.toggle_igroup_add_mode, "Test Impacts")
    # New-group dialog smoke: opens, renders, cancels.
    run Function(_cue.dialogs.intensity.open)
    $ _ok = _ok and renpy.get_screen("cue_new_igroup_dialog", layer="cue_layer")
    run Function(_cue.dialogs.intensity.cancel)
    $ _ok = _ok and not renpy.get_screen("cue_new_igroup_dialog", layer="cue_layer")
    # Rename moves the group; one JSON lands on disk under data/presets/.
    run Function(_cue.intensity.rename_igroup, "Test Impacts", "Impacts 2")
    $ _ok = _ok and ("Impacts 2" in _cue.intensity.list_igroups())
    $ _ok = _ok and ("Test Impacts" not in _cue.intensity.list_igroups())
    $ import os as _os
    $ _ok = _ok and _os.path.isdir(_cue.paths.intensity_preset_dir)
    $ _ok = _ok and len([f for f in _os.listdir(_cue.paths.intensity_preset_dir) if f.startswith("Impacts")]) == 1
    $ if not _ok: renpy.quit(status=1)
    run Function(_cue.intensity.delete_igroup, "Impacts 2")
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase intensity_resolves_level_folders:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    # Real 3-level group; band [0.7, 1.0, 1.3] lands one speed per level.
    $ _cue_intensity_folders()
    run Function(_cue.intensity.create_igroup, "Resolve Test")
    run Function(_cue.intensity.add_folder, "Resolve Test", "soft/")
    run Function(_cue.intensity.add_folder, "Resolve Test", "hard/")
    run Function(_cue.intensity.add_folder, "Resolve Test", "empty/")
    # A pool hooked to soft/ (Level 1) resolves up to the active level's folder.
    $ _r1 = _cue.intensity.resolve_intensity(["soft/"], 0.7, [0.7, 1.0, 1.3])
    $ _ok = _r1 is not None and _r1.level == 1 and _r1.folder == "soft/"
    $ _ok = _ok and _r1.files == ["soft/sfx_001.ogg"]
    $ _ok = _ok and _r1.volume_mult == 1.0
    $ _r2 = _cue.intensity.resolve_intensity(["soft/"], 1.0, [0.7, 1.0, 1.3])
    $ _ok = _ok and _r2.level == 2 and _r2.folder == "hard/"
    $ _ok = _ok and _r2.files == ["hard/sfx_001.ogg", "hard/sfx_002.ogg"]
    $ _ok = _ok and _r2.volume_mult == 1.125
    # Fastest speed -> Level 3; its folder is empty, so silence (no fallback).
    $ _r3 = _cue.intensity.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3])
    $ _ok = _ok and _r3.level == 3 and _r3.folder == "empty/"
    $ _ok = _ok and _r3.files == []
    # A pool not hooked to any group resolves to nothing.
    $ _ok = _ok and _cue.intensity.resolve_intensity(["sfx_001.ogg"], 1.0, [0.7, 1.0, 1.3]) is None
    run Function(_cue.intensity.delete_igroup, "Resolve Test")
    $ _cue_intensity_cleanup()
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase intensity_loop_fire_path:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    # Real 3-level group; the loop pool hooks soft/ (Level 1's folder).
    $ _cue_intensity_folders()
    run Function(_cue.intensity.create_igroup, "Fire Test")
    run Function(_cue.intensity.add_folder, "Fire Test", "soft/")
    run Function(_cue.intensity.add_folder, "Fire Test", "hard/")
    run Function(_cue.intensity.add_folder, "Fire Test", "empty/")
    # An image tag can't start a speed sequence (no video path), so current
    # speed falls through to speed_pref = 1.0 -> Level 2 (hard/).
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_pref"] = 1.0
    $ _cue.markers._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": ["soft/"], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    # Poll until the loop records a Level-2 (hard/) fire -- a fixed pause races
    # slow 7.x audio-channel startup under xvfb (see the init -10 waiter).
    $ _test_wait_deadline = _test_time.time() + 10.0
    pause 0.5 until run _cue_test_wait_until_true(_cue_intensity_fired, _test_wait_deadline)
    $ _ok = _cue_played_from("hard/")
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("v_cueimg_a", None)
    run Function(_cue.intensity.delete_igroup, "Fire Test")
    $ _cue_intensity_cleanup()
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase intensity_toggle_master_off:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    # Master toggle off: the loop pool's group hook is ignored -- it plays its
    # OWN listed folder (soft/ as a plain folder) instead of the active level's
    # folder (hard/).  soft/ gets two files so the pick is recorded.
    $ _cue_intensity_toggle_folders()
    run Function(_cue.intensity.create_igroup, "Toggle Test")
    run Function(_cue.intensity.add_folder, "Toggle Test", "soft/")
    run Function(_cue.intensity.add_folder, "Toggle Test", "hard/")
    # The video entry carries a hooked (time-less) pool so the per-tick video
    # gate can resolve; a time-less pool never fires as a video marker.
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["pools"] = [{"files": ["soft/"], "volume": 1.0}]
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_pref"] = 1.0
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["intensity_enabled"] = False
    $ _cue.markers._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": ["soft/"], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    $ _test_wait_deadline = _test_time.time() + 10.0
    pause 0.5 until run _cue_test_wait_until_true(_cue_intensity_soft_fired, _test_wait_deadline)
    $ _ok = _cue_played_from("soft/")
    $ _ok = _ok and not _cue_played_from("hard/")
    # Master off -> no intensity mode: the per-tick video gate stays None.
    $ _ok = _ok and _cue.trigger._vid_intensity is None
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("v_cueimg_a", None)
    run Function(_cue.intensity.delete_igroup, "Toggle Test")
    $ _cue_intensity_cleanup()
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase intensity_toggle_sfx_levels_off:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    # SFX-levels off (master on): the loop pool plays its own listed folders
    # (soft/ as a plain folder) while the active level still drives volume --
    # intensity mode stays live (the video gate is a resolution, not None).
    $ _cue_intensity_toggle_folders()
    run Function(_cue.intensity.create_igroup, "Toggle Test")
    run Function(_cue.intensity.add_folder, "Toggle Test", "soft/")
    run Function(_cue.intensity.add_folder, "Toggle Test", "hard/")
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["pools"] = [{"files": ["soft/"], "volume": 1.0}]
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["speed_pref"] = 1.0
    $ _cue.markers._get_or_create_entry("v_cueimg_a")["intensity_sfx_levels"] = False
    $ _cue.markers._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": ["soft/"], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    $ _test_wait_deadline = _test_time.time() + 10.0
    pause 0.5 until run _cue_test_wait_until_true(_cue_intensity_soft_fired, _test_wait_deadline)
    $ _ok = _cue_played_from("soft/")
    $ _ok = _ok and not _cue_played_from("hard/")
    # Master still on -> intensity mode is live even though this pool plays
    # its own folders; the video gate is a resolution, not None.
    $ _ok = _ok and _cue.trigger._vid_intensity is not None
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("v_cueimg_a", None)
    run Function(_cue.intensity.delete_igroup, "Toggle Test")
    $ _cue_intensity_cleanup()
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase sfx_recently_used:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _ok = _cue.sfx.library._recent.entries() == []
    $ _ok = _ok and not _cue.sfx.library._recent.expanded
    run Function(_cue.markers.image.send_file, 0)
    $ _ok = _ok and _cue.sfx.library._recent.entries() == [{"type": "file", "ref": _cue.sfx.library.files[0]}]
    $ _ok = _ok and not _cue.sfx.library._recent.expanded
    run Function(_cue.markers.image.send_folder, "Sub/")
    $ _ok = _ok and _cue.sfx.library._recent.entries()[0] == {"type": "folder", "ref": "Sub/"}
    $ _ok = _ok and len(_cue.sfx.library._recent.entries()) == 2
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.markers.image.send_preset, "Test Preset")
    $ _ok = _ok and len(_cue.sfx.library._recent.entries()) == 3
    run Function(_cue.markers.image.send_preset, "Test Preset")
    $ _ok = _ok and len(_cue.sfx.library._recent.entries()) == 3
    $ _ok = _ok and _cue.sfx.library._recent.entries()[0] == {"type": "preset", "ref": "Test Preset"}
    run Function(_cue_set_page, CuePage.SFX)
    pause 0.5
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase music_recently_used:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _ok = _cue.music._recent is not None
    $ _ok = _ok and _cue.music._recent.entries() == []
    $ _ok = _ok and not _cue.music._recent.expanded
    run Function(_cue.music.add_user_song_to_trigger, "music/song_001.ogg")
    $ _ok = _ok and _cue.music._recent.entries() == [{"type": "file", "ref": "u:music/song_001.ogg"}]
    $ _ok = _ok and not _cue.music._recent.expanded
    run Function(_cue.music.add_user_folder_to_trigger, "music/")
    $ _ok = _ok and _cue.music._recent.entries()[0] == {"type": "folder", "ref": "u:music/"}
    $ _ok = _ok and len(_cue.music._recent.entries()) == 2
    run Function(_cue.music.add_user_folder_to_trigger, "music/")
    $ _ok = _ok and len(_cue.music._recent.entries()) == 2
    $ _ok = _ok and _cue.music._recent.entries()[0] == {"type": "folder", "ref": "u:music/"}
    run Function(_cue_set_page, CuePage.MUSIC)
    pause 0.5
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase sfx_target_context:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    run Function(_cue_set_page, CuePage.SFX)
    $ import pygame_sdl2
    $ import renpy.test.testkey as _testkey
    # Hotkeys select the target context on the SFX page.  No image/movie on
    # screen (reset), so a video/dialogue selection is kept as-is by the
    # fallback (nothing to fall back to).
    $ _testkey.down(None, "3")
    $ _testkey.up(None, "3")
    pause 0.5
    $ if not (_cue.markers.target_context == CueContextType.DIALOGUE): renpy.quit(status=1)
    $ _testkey.down(None, "4")
    $ _testkey.up(None, "4")
    pause 0.5
    $ if not (_cue.markers.target_context == CueContextType.LOOP): renpy.quit(status=1)
    $ _testkey.down(None, "1")
    $ _testkey.up(None, "1")
    pause 0.5
    $ if not (_cue.markers.target_context == CueContextType.VIDEO): renpy.quit(status=1)
    # Compile the preset + video preset + recently-used list rows.
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.sfx.library.toggle_presets_expand)
    run Function(_cue.sfx.library.toggle_video_presets_expand)
    # Image on screen: video target falls back to image; [+] routes there.
    $ _cue_test_reset()
    $ renpy.show("cueimg_a")
    pause 1.0
    $ if not (_cue.current_file == "cueimg_a"): renpy.quit(status=1)
    $ _testkey.down(None, "1")
    $ _testkey.up(None, "1")
    pause 0.5
    run Function(_cue_markers_send, "file", 0)
    $ if not _cue.markers.image.has_pools(): renpy.quit(status=1)
    $ if not _cue.markers.image.get_active_pool().get("files", []): renpy.quit(status=1)
    $ _cue.markers.image.clear()
    # Movie on screen: image target falls back to video; [+] routes there.
    $ _cue_test_reset()
    $ renpy.show("cuevid")
    pause 1.0
    $ if not (_cue.top_layer_type == "movie"): renpy.quit(status=1)
    $ _testkey.down(None, "2")
    $ _testkey.up(None, "2")
    pause 0.5
    run Function(_cue_markers_send, "folder", "Sub/")
    $ if not _cue.markers.video.has_pools(): renpy.quit(status=1)
    $ if "Sub/" not in _cue.markers.video.get_active_pool().get("files", []): renpy.quit(status=1)
    $ _cue.markers.video.clear()
    $ _cue_test_reset()
    $ renpy.quit()

testcase music_presets:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _ok = True
    # Create a preset from stored u:/g: refs and read it back.
    run Function(_cue.music.create_preset, "Test Music Preset", ["u:music/song_001.ogg", "g:bgm/song_002.ogg"])
    $ _ok = _ok and "Test Music Preset" in _cue.music.list_presets()
    $ _ok = _ok and _cue.music.get_preset("Test Music Preset")["files"] == ["u:music/song_001.ogg", "g:bgm/song_002.ogg"]
    # Display rows resolve each stored ref to a My/Game Music path.
    $ _ok = _ok and _cue.music.preset_display_files(_cue.music.get_preset("Test Music Preset")) == ["My Music/song_001.ogg", "Game Music/bgm/song_002.ogg"]
    # Expand + render the Music page so the preset rows compile and display.
    run Function(_cue.music.toggle_presets_expand)
    $ _ok = _ok and _cue.music.presets_expanded
    run Function(_cue.music.toggle_preset_expand, "Test Music Preset")
    $ _ok = _ok and _cue.music.expanded_presets.get("Test Music Preset", False)
    run Function(_cue_set_page, CuePage.MUSIC)
    pause 0.5
    # Deleting removes it from memory and disk.
    run Function(_cue.music.delete_preset, "Test Music Preset")
    $ _ok = _ok and "Test Music Preset" not in _cue.music.list_presets()
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_movie_detected:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _ok = _cue.top_layer_type == "movie"
    $ _ok = _ok and _cue.vid_manager.channel is not None
    $ _ok = _ok and _cue.vid_manager.get_duration() > 0
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_sfx_timeline_seeded:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _ok = _cue.markers.video.has_markers()
    $ _ok = _ok and len(_cue.markers.video.get_markers()) >= 1
    $ _ok = _ok and 0 <= _cue.markers.video.active_pool < len(_cue.markers.video.get_markers())
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_multi_edit_fans_out:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.selected = {0, 1}
    $ _cue.markers.video.set_selected_volume(0.3)
    $ _vkey = _cue.markers.video._key()
    $ _vpools = _cue.markers.get(_vkey)["pools"]
    $ _ok = _vpools[0].get("volume") == 0.3
    $ _ok = _ok and _vpools[1].get("volume") == 0.3
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    $ _cue.markers.video.apply_preset_active("Test Preset")
    $ _vpools = _cue.markers.get(_vkey)["pools"]
    $ _ok = _ok and _vpools[0].get("preset") == "Test Preset"
    $ _ok = _ok and _vpools[1].get("preset") == "Test Preset"
    $ _cue.markers.detach_active_video_ts()
    $ _vpools = _cue.markers.get(_vkey)["pools"]
    $ _ok = _ok and ("preset" not in _vpools[0])
    $ _ok = _ok and ("preset" not in _vpools[1])
    $ _ok = _ok and _vpools[0].get("files") == ["sfx_001.ogg"]
    $ _ok = _ok and _vpools[1].get("files") == ["sfx_001.ogg"]
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_multi_duplicate_fans_out:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    # The fixture video carries pre-loaded marker data, so start from a clean
    # slate with three pools at times well inside the video duration (the
    # ~2s fixture would clamp copies of later sources to the end).
    $ _cue.markers.video.clear()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _vpools = _cue.markers.get(_cue.markers.video._key())["pools"]
    $ _vpools[0]["time"] = 0.2
    $ _vpools[1]["time"] = 0.4
    $ _vpools[2]["time"] = 0.6
    $ _cue.markers.video.selected = {0, 2}
    $ _gap = _cue.markers.video._duplicate_gap()
    $ _cue.markers.video.duplicate_pool(0)
    $ _vpools = _cue.markers.get(_cue.markers.video._key())["pools"]
    $ _ok = len(_vpools) == 5
    $ _times = [p["time"] for p in _vpools]
    $ _copy1 = any(abs(t - (0.2 + _gap)) < 1e-6 for t in _times)
    $ _copy2 = any(abs(t - (0.6 + _gap)) < 1e-6 for t in _times)
    $ _ok = _ok and _copy1 and _copy2
    $ _ok = _ok and len(_cue.markers.video.selected) == 2
    $ _ok = _ok and (_cue.markers.video.active_pool in _cue.markers.video.selected)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_multi_delete_pool_group:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.clear()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.selected = {0, 2}
    $ _cue.markers.video.delete_pool_ui()
    $ _vpools = _cue.markers.get(_cue.markers.video._key())["pools"]
    $ _ok = len(_vpools) == 1
    $ _ok = _ok and (_cue.markers.video.selected == set())
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase volume_value_equality_distinguishes_multisetter:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _d = {"volume": 1.0}
    $ _v_none = _CueVolumeValue(_d, "volume", "k", multi_setter=None, range=1.0)
    $ _v_set = _CueVolumeValue(_d, "volume", "k", multi_setter=_cue.markers.video.set_selected_volume, range=1.0)
    $ _v_set2 = _CueVolumeValue(_d, "volume", "k", multi_setter=_cue.markers.video.set_selected_volume, range=1.0)
    $ _ok = _v_none != _v_set
    $ _ok = _ok and _v_set == _v_set2
    $ _ok = _ok and _v_none == _v_none
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase volume_value_changed_fans_out_and_queues_save:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.selected = {0, 1}
    $ _vid_key = _cue.markers.video._key()
    $ _vpools = _cue.markers.get(_vid_key)["pools"]
    $ _vol_val = _CueVolumeValue(_vpools[0], "volume", _vid_key, multi_setter=_cue.markers.video.set_selected_volume, range=_cue.volume.VOL_MAX)
    # changed() triggers a restart_interaction (via DictValue.changed), whose
    # redraw can run the slow-tick save flush -- so the queued-save check must
    # happen in the same $ statement, before the event loop drains the set.
    $ _vol_val.changed(0.4); _queued = _vid_key in _cue.volume._pending_saves
    $ _ok = _vpools[0]["volume"] == 0.4 and _vpools[1]["volume"] == 0.4 and _queued
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_sfx_edit_locked_off_base_speed:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _ok = _cue.speed_resolver.get_current_speed() == CUE_DEFAULT_VIDEO_SPEED
    $ _cue.speed_resolver.set_speed(1.5)
    $ _ok = _ok and _cue.speed_resolver.get_current_speed() == 1.5
    $ _cue.speed_resolver.set_speed(CUE_DEFAULT_VIDEO_SPEED)
    $ _ok = _ok and _cue.speed_resolver.get_current_speed() == CUE_DEFAULT_VIDEO_SPEED
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_vfx_speed_sequence:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _cue.video_sequence.append_speed(1.5)
    $ _ok = 1.5 in (_cue.video_sequence.speeds_for(_cue.current_file) or [])
    $ _ok = _ok and _cue.video_sequence.get_mode() == CueSpeedMode.SINGLE
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_auto_speed_state:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _ok = _cue.auto_speed.active_preset == "roller_coaster"
    $ _ok = _ok and len(_cue.auto_speed.enabled_speeds) >= 1
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_speed_variant_created:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.video_editor.create(1.5)
    python:
        import os as _os
        import time as _time
        # Drive the encode to completion from here.  The job state machine only
        # advances via job_queue.poll() -- the tick timer can't run while this
        # python block holds the main thread, and renpy.pause is forbidden
        # inside a test python block (it starts an interaction mid-interaction).
        _queue = _cue.video_editor.job_queue
        _deadline = _time.time() + 30.0
        while _queue.processing and _time.time() < _deadline:
            _queue.poll()
            _time.sleep(0.1)
        _base = _cue.speed_resolver.base_path_for(_cue.current_file)
        _variant = _cue.speed_resolver.variant_path(_base, 1.5)
        _ok = not _queue.processing
        _ok = _ok and bool(_base)
        _ok = _ok and _os.path.exists(_variant)
        _ok = _ok and (1.5 in _cue.speed_resolver.get_available_speeds(_base))
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase click_create_tab_opens_editor:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _ok = not _cue.video_editor.active
    # Real mouse click on the Video VFX "Create" tab. Regression: the marker
    # timeline's MOUSEBUTTONUP handler once raised IgnoreEvent() on every
    # release (even over sibling buttons), which swallowed the button's
    # release globally and made the whole Video VFX tab unclickable.
    $ import renpy.test.testfocus as _testfocus
    $ import renpy.test.testmouse as _testmouse
    $ _focus = _testfocus.find_focus("Create")
    $ _pos = _testfocus.find_position(_focus, (None, None))
    $ _testmouse.click_mouse(1, _pos[0], _pos[1])
    pause 0.5
    $ _ok = _ok and _cue.video_editor.active
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_queue_error_msg_substitute_guard:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.video_editor.create(1.5)
    python:
        import time as _time
        _queue = _cue.video_editor.job_queue
        _deadline = _time.time() + 30.0
        while _queue.processing and _time.time() < _deadline:
            _queue.poll()
            _time.sleep(0.1)
    # Regression for the CI crash on runners without ffmpeg: a failed encode
    # sets error_msg to "[Errno 2] ...". The queue text used to be substituted,
    # so those brackets were py_eval'd and crashed the whole overlay on every
    # render. Both dynamic text lines are `substitute False` now -- render the
    # queue with a bracketed error (and bracketed filename) to prove it.
    $ _cue.video_editor.open_editor()
    $ _job = _cue.video_editor.job_queue.jobs[-1]
    $ _job.status = CueJobStatus.ERROR
    $ _job.vpath = "videos/[bracket] scene.mp4"
    $ _job.error_msg = "[Errno 2] No such file or directory: 'ffmpeg'"
    $ renpy.restart_interaction()
    pause 0.5
    $ _ok = _job.error_msg == "[Errno 2] No such file or directory: 'ffmpeg'"
    $ _cue.video_editor.close_editor()
    $ renpy.restart_interaction()
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_seamless_transition_preserves_position:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.video_editor.create(1.5)
    python:
        import os as _os
        import time as _time
        _queue = _cue.video_editor.job_queue
        _deadline = _time.time() + 30.0
        while _queue.processing and _time.time() < _deadline:
            _queue.poll()
            _time.sleep(0.1)
        _base = _cue.speed_resolver.base_path_for(_cue.current_file)
        # Isolate: base speed, no speed sequence, seamless off -- the base
        # file is what plays before the flip.  Explicit even though legacy
        # runs a fresh process per testcase, to mirror the modern template.
        _cue.video_sequence.clear_sequence()
        _cue.speed_resolver.seamless_transition = False
        _cue.speed_resolver._set_speed_pref(_cue.current_file, 1.0)
        renpy.restart_interaction()
    pause 0.3
    $ _before_ch = _cue.vid_manager.channel
    $ _before_playing = _cue.vid_manager.get_video_path()
    $ _ok = _before_ch is not None
    $ _ok = _ok and _os.path.basename(_before_playing or "") == _os.path.basename(_base)
    $ if not _ok: renpy.quit(status=1)
    $ _cue.speed_resolver.toggle_seamless()
    $ _cue.speed_resolver.set_speed(1.5)
    # set_speed() queues the variant with loop=True, which drops the base from
    # the channel's loop list -- the base plays to EOF (<=2s), SDL advances to
    # the queued variant (which then loops), and resolve() commits the flip on
    # the next render.  The pauses keep interactions flowing so resolve() runs;
    # capturing late is safe because the variant loops.
    pause 2.0
    pause 2.0
    $ _after_ch = _cue.vid_manager.channel
    $ _after_playing = _cue.vid_manager.get_video_path()
    $ _after_pos = _cue.vid_manager.get_elapsed()
    $ _after_dur = _cue.vid_manager.get_duration()
    $ _variant = _cue.speed_resolver.variant_path(_base, 1.5)
    $ _ok = _ok and (_after_ch == _before_ch)
    $ _ok = _ok and (_os.path.normpath(_after_playing) == _os.path.normpath(_variant))
    $ _ok = _ok and (0.0 <= _after_pos < _after_dur)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase img_trigger_fires_on_show:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _ok = len(_cue.trigger.last_played) >= 1
    $ _cue.markers.pop("i_cueimg_a", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase dlg_trigger_fires_on_say:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("d_cueimg_a__Hello")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    run Jump("cue_say_fire")
    pause 1.0
    $ _ok = len(_cue.trigger.last_played) >= 1
    $ _cue.markers.pop("d_cueimg_a__Hello", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase loop_trigger_fires_on_cycle:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    pause 2.0
    $ _ok = len(_cue.trigger.last_played) >= 1
    $ _cue.markers.pop("l_cueimg_a", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase video_marker_fires_at_ts:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("v_cuevid")["pools"] = [{"time": 0.0, "files": ["sfx_001.ogg"], "volume": 1.0}]
    $ renpy.show("cuevid")
    # Wait out the 7.x movie startup: the v_ marker fires on the first tick
    # even before the movie advances, but played_video_keys is wiped every tick
    # while last_elapsed == 0.  Only once the movie actually plays (elapsed > 0)
    # does the fired key stick.  Poll until it does (see the init -10 waiter
    # above) -- a fixed pause races slow 7.x startup under xvfb.
    $ _test_wait_deadline = _test_time.time() + 15.0
    pause 0.5 until run _cue_test_wait_until_true(_cue_vid_marker_ready, _test_wait_deadline)
    $ _ok = _cue.top_layer_type == "movie"
    $ _ok = _ok and _cue.vid_manager.get_duration() > 0
    $ _ok = _ok and _cue.vid_manager.get_elapsed() > 0.0
    $ _ok = _ok and len(_cue.trigger.played_video_keys) >= 1
    $ _cue.markers.pop("v_cuevid", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase img_oneshot_dedup_no_refire:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ _cue.markers._get_or_create_entry("i_cueimg_b")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _ok = len(_cue.trigger.last_played) == 1
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _ok = _ok and len(_cue.trigger.last_played) == 1
    $ renpy.show("cueimg_b")
    pause 1.0
    $ _ok = _ok and len(_cue.trigger.last_played) == 2
    $ _cue.markers.pop("i_cueimg_a", None)
    $ _cue.markers.pop("i_cueimg_b", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase shake_fires_on_with_vpunch:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "trigger_on_shake": True}]
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _cue.trigger.last_played = []
    run Jump("cue_shake_with")
    pause 1.0
    $ _ok = len(_cue.trigger.last_played) >= 1
    $ _cue.markers.pop("i_cueimg_a", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase shake_fires_on_at_vpunch:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "trigger_on_shake": True}]
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _cue.trigger.last_played = []
    run Jump("cue_shake_at")
    pause 1.0
    $ _ok = len(_cue.trigger.last_played) >= 1
    $ _cue.markers.pop("i_cueimg_a", None)
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase music_play_interceptor_installed:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    $ import renpy.audio.music as _music
    $ _ok = getattr(_music.play, "__name__", "") == "_on_play"
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

# Renders etext with tag + interpolation characters in the value, so the
# statement compiles and displays them literally (an unescaped value would
# crash the interaction or garble the text).
screen _cue_etext_smoke():
    style_group "cue"

    vbox:
        etext "{b}file[x].mp3"
        etext "{b}file[x].mp3" substitute False

testcase etext_escapes_dynamic_string:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    # CueSafeText escapes before Text substitutes: `{` is doubled for the tag
    # tokenizer (it stays doubled in .text), and the escaped `[` was collapsed
    # back to a literal by substitution -- .text holds the escaped form that
    # renders as the literal input.
    $ _t = CueSafeText("{b}file[x].mp3")
    $ _ok = _t.text[0] == "{{b}file[x].mp3"
    # substitute False: brackets are already literal (no substitution runs),
    # so only braces are doubled; the value still renders literally.
    $ _t2 = CueSafeText("{b}file[x].mp3", substitute=False)
    $ _ok = _ok and _t2.text[0] == "{{b}file[x].mp3"
    # Render the statement itself -- both variants display without the raw
    # string being parsed as a tag or interpolated.
    $ renpy.show_screen("_cue_etext_smoke", _layer="cue_layer")
    pause 0.5
    $ _ok = _ok and renpy.get_screen("_cue_etext_smoke", layer="cue_layer") is not None
    run Function(renpy.hide_screen, "_cue_etext_smoke")
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()
