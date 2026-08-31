# Runs after the mod's init 999 (which hydrates seamless_transition from
# persistent): video_seamless_transition_preserves_position leaves it on via
# persistent, so a later run's video_sfx_edit_locked_off_base_speed would
# start with set_speed in queue mode -- it needs the 1.5x variant to exist and
# never writes the pref, so the assertion sees the base speed.
init -950 python:
    # The boot-time thumbnail fetch starts inside the mod's init -900 (via
    # _cue_load_initial_data), before _cue_test_reset's disable() can run.
    # Neutralize it here so the harness never hits the network.
    import cue_lib.thumbs as _cue_thumbs_mod
    _cue_thumbs_mod.CueThumbManager.maybe_download = lambda self: None

init 1000 python:
    # Reset trigger/context state so each testcase starts clean.  The modern
    # suite runs every testcase in one process, so last_played, loop_states,
    # played_keys, current_file, and the dialogue fields all leak
    # between testcases without this.
    def _cue_test_reset():
        _cue.replays.thumbs.disable()
        # set_page is a no-op on the already-active page, so a prior testcase
        # leaving active_page set would skip the target's scan().
        _cue.overlay.active_page = CuePage.SFX
        # The test game's start label never clears the scene, so a prior
        # testcase's displayable stays on the master layer.  Re-showing a
        # different image then puts the new one BELOW the stale top entry and
        # fire_context never sees the intended change.  Clear the layer FIRST
        # so the reload's context refresh sees a genuinely empty scene instead
        # of re-setting ctx.current_file from a stale displayable.
        renpy.scene()
        # A full reload re-derives every disk-backed layer -- markers, presets,
        # libraries, replays, thumbs, undo -- from the current root.  Any
        # in-memory marker seed a prior testcase left behind is wiped here, so
        # the disk-derived state never leaks.
        _cue_full_reload()
        # Runtime-driver leaks that aren't disk-backed and survive a reload.
        _cue.trigger.active = True
        _cue.trigger.last_played = []
        _cue.trigger.reset()
        _cue.trigger.excl.channels.clear()
        # The empty scene leaves the settled context stale; clear it so the
        # next show is a genuine change and the trigger tick has no phantom
        # target.
        _cue.current_file = ""
        _cue.top_layer_type = ""
        _cue.current_dialogue = ""
        _cue.prev_dialogue = ""
        _cue.ctx.current_who = ""
        _cue.ctx._shake_just_happened = False
        _cue.vid_manager.last_elapsed = 0.0
        # Music interception state leaks too: last_event, an uncleared pending
        # key_after capture, and a fake _in_replay all persist.
        _cue.music.last_event = None
        _cue.music._pending = None
        renpy.store._in_replay = None

    def _cue_scenes_seed():
        # Seed two markers through the store, not raw disk writes: scan() and
        # thumb_for() read the store's in-memory _data, so a marker that only
        # lands on disk is invisible to them.  One replay is valid, one whose
        # label no longer exists (the page disables play + shows a warning for
        # the latter).  Removed by _cue_scenes_cleanup.
        for _key, _label in (("v_scene_harness.ogv", "replay_harness"),
                             ("v_stale_harness.ogv", "no_such_label_harness")):
            _cue.markers[_key] = {"_key": _key, "replay": _label, "pools": []}

    def _cue_scenes_cleanup():
        for _key in ("v_scene_harness.ogv", "v_stale_harness.ogv"):
            if _key in _cue.markers:
                _cue.markers.pop(_key)

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

    def _cue_intensity_variants():
        # Write on-disk speed variants for the harness cuevid movie so
        # banding_speeds (which reads the video dir, not the stored
        # sequence) sees the full set.  Removed by _cue_intensity_variant_cleanup.
        import os as _os
        _vd = _cue.paths.video_dir
        if not _os.path.isdir(_vd):
            _os.makedirs(_vd)
        for _sp in (0.7, 1.3):
            with open(_os.path.join(_vd, "cuevideo_cue{:.1f}x.webm".format(_sp)), "wb") as _f:
                _f.write(b"x")
        _cue.speed_resolver.paths["cuevid"] = "cuevideo.webm"
        _cue.speed_resolver.invalidate_speed_cache()

    def _cue_intensity_variant_cleanup():
        import os as _os
        _vd = _cue.paths.video_dir
        for _sp in (0.7, 1.3):
            _p = _os.path.join(_vd, "cuevideo_cue{:.1f}x.webm".format(_sp))
            if _os.path.exists(_p):
                _os.remove(_p)

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

    def _cue_external_dirs():
        # Create two temp external Music/SFX folders (one audio file each)
        # under the data root; returns (music_dir, sfx_dir).  Exercises the
        # external-scan paths.  Cleaned up by _cue_external_cleanup.
        import os as _os
        _base = _cue.paths.root
        _md = _base + "/ExtMusic"
        _sd = _base + "/ExtSfx"
        for _d in (_md, _sd):
            if not _os.path.isdir(_d):
                _os.makedirs(_d)
        with open(_os.path.join(_md, "song.ogg"), "wb") as _f:
            _f.write(b"x")
        with open(_os.path.join(_sd, "drip.ogg"), "wb") as _f:
            _f.write(b"x")
        return _md, _sd

    def _cue_external_cleanup():
        # Remove the temp external folders and rescan both libraries so the
        # merged trees drop the external entries (modern runs every testcase
        # in one process).
        import os as _os
        import shutil as _shutil
        _base = _cue.paths.root
        _shutil.rmtree(_base + "/ExtMusic", ignore_errors=True)
        _shutil.rmtree(_base + "/ExtSfx", ignore_errors=True)
        _cue.music.library.external_folders = []
        _cue.sfx.library.external_folders = []
        _cue.music.library.scan()
        _cue.sfx.library.scan()

    def _cue_music_test_cleanup():
        # Tear down the music interception testcases: trigger-log mirror + DB
        # file, the seeded marker, the copied fixture, and detection state.
        import os as _os
        # Stop the channel before deleting its file: 8.1.3 shutdown fadeout
        # reloads the channel file and crashes if it is gone.
        renpy.audio.music.stop()
        _cue.music._pending = None
        _cue.music.last_event = None
        renpy.store._in_replay = None
        _cue.music._triggers.pop("test_replay", None)
        _cue.markers.pop("i_cueimg_a", None)
        for _p in (_cue.paths.music_trigger_path("test_replay"), _cue.paths.music_dir + "song_002.ogg"):
            if _os.path.isfile(_p):
                _os.remove(_p)

    # The video_seamless testcase re-enables it itself.
    _cue.speed_resolver.seamless_transition = False

testsuite global:
    before testcase:
        # Generous: a cold/loaded CI runner can take >2s to settle the SFX
        # page rebuild after a restart_interaction (sfx_target_context timed
        # out at the old 2.0 on 8.5.3/ubuntu-24.04). Slow-but-finite renders
        # time out; only a truly never-yielding render still hangs (bounded
        # by CUE_ENGINE_TIMEOUT in the harness).
        $ _test.timeout = 10.0
        $ _test.transition_timeout = 0.05
        $ _cue.overlay.is_visible = True

    teardown:
        exit

testcase overlay_shows_on_start:
    run Jump("start")
    assert screen "cue_overlay" layer "cue_layer"

testcase page_nav:
    run Jump("start")
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    assert eval (_cue.overlay.active_page == CuePage.MUSIC)

testcase settings_page_about:
    run Jump("start")
    # Rendering the Settings page exercises cue_about: a broken version line
    # or {a=} hyperlink style fails this interaction.
    run Function(_cue.overlay.set_page, CuePage.SETTINGS)
    assert eval (_cue.overlay.active_page == CuePage.SETTINGS)

testcase import_page_nav:
    run Jump("start")
    # _cue.overlay.set_page(IMPORT) scans imports/ and refreshes the export categories
    # before the page renders.  A compile error in the import/export page
    # fails this interaction.
    run Function(_cue.overlay.set_page, CuePage.IMPORT)
    assert eval (_cue.overlay.active_page == CuePage.IMPORT)

testcase scenes_page_render:
    run Jump("start")
    $ _cue_test_reset()
    # Scenes page lists replays-with-markers.  Seed one valid replay marker and
    # one whose label no longer exists, then render the page: scan() picks both
    # up, and the stale row's disabled play + warning branch must not break the
    # interaction.
    $ _cue_scenes_seed()
    run Function(_cue.overlay.set_page, CuePage.REPLAYS)
    assert eval (_cue.overlay.active_page == CuePage.REPLAYS)
    assert eval ({"replay": "replay_harness", "marker_count": 1} in _cue.replays.entries)
    assert eval ({"replay": "no_such_label_harness", "marker_count": 1} in _cue.replays.entries)
    assert eval (not renpy.has_label("no_such_label_harness"))
    $ _cue_scenes_cleanup()

testcase scene_row_thumbnails:
    run Jump("start")
    $ _cue_test_reset()
    # The thumbnail slot renders two displayables: a real image (the captured
    # marker filepath, scaled via Transform) and the placeholder frame for a
    # scene with no thumb.  Seed an image-carrying marker alongside the
    # placeholder-only scenes from scenes_page_render.
    $ _cue_scenes_seed()
    $ _cue.markers["v_thumb_harness.ogv"] = {"_key": "v_thumb_harness.ogv", "replay": "replay_harness", "pools": [], "filepath": "renpy_cue/cue_lib/assets/images/icons/gear-solid.png"}
    run Function(_cue.overlay.set_page, CuePage.REPLAYS)
    assert eval (_cue.replays.thumbs.thumb_for("replay_harness") == "renpy_cue/cue_lib/assets/images/icons/gear-solid.png")
    assert eval (_cue.replays.thumbs.thumb_for("no_such_label_harness") is None)
    pause 0.3
    $ _cue_scenes_cleanup()
    $ _cue.markers.pop("v_thumb_harness.ogv")

testcase cast_filter_renders:
    run Jump("start")
    $ _cue_test_reset()
    # Cast filter multiselect.  Seed cast files for the two scenes, select a
    # speaker, and render the page with a selected chip and the open dropdown
    # -- the wrapped-chip and vpgrid branches must not break the interaction.
    $ import json as _json
    $ import os as _os
    $ _rdir = _cue.paths.replay_dir
    $ if not _os.path.isdir(_rdir): _os.makedirs(_rdir)
    $ _f = lambda _p, _d: open(_p, "w").write(_json.dumps(_d))
    $ _f(_cue.paths.replay_path("replay_harness"), {"replay": "replay_harness", "characters": ["mc", "sg"]})
    $ _f(_cue.paths.replay_path("no_such_label_harness"), {"replay": "no_such_label_harness", "characters": ["mc"]})
    $ _cue_scenes_seed()
    run Function(_cue.overlay.set_page, CuePage.REPLAYS)
    $ _filter = _cue.replays.cast_filter
    $ _filter.toggle("sg")
    assert eval (sorted(_filter.selected) == ["sg"])
    assert eval (_filter.matches("replay_harness") and not _filter.matches("no_such_label_harness"))
    # Open the dropdown so the option vpgrid renders; then select an option
    # (which must close the list) and re-open it to close via the trigger.
    $ _cue.overlay.active_input_rect = (0, 0, 300, 20)
    $ _filter.toggle_open()
    pause 0.2
    assert eval (_filter.is_open())
    # The floating list anchors on this rect; focus rects arrive as floats,
    # and screen xpos treats floats as parent fractions, so the anchor must
    # be ints (a regression here silently renders the list off-screen).
    assert eval (_filter.trigger_rect() == (0, 0, 300, 20))
    # Selecting an option toggles it and closes the dropdown.
    $ _filter.select("mc")
    assert eval (not _filter.is_open())
    assert eval (_filter.is_selected("mc"))
    $ _filter.clear()
    $ _cue_scenes_cleanup()
    $ _os.remove(_cue.paths.replay_path("replay_harness"))
    $ _os.remove(_cue.paths.replay_path("no_such_label_harness"))

testcase import_banner_render:
    run Jump("start")
    $ _cue_test_reset()
    # An active package swaps the editor to the import and the toolbar shows
    # the edit banner (the click-swallowing shield was dropped).  Set the
    # active state directly -- the export/scan/activate path is covered by the
    # roundtrip testcase.  Rendering the SFX page under this state is the
    # smoke test: a broken banner screen fails this interaction.
    $ _cue.importer.is_active = True
    $ _cue.importer.active_import = "ShieldPkg"
    run Function(_cue.overlay.set_page, CuePage.SFX)
    assert eval (_cue.overlay.active_page == CuePage.SFX)
    assert eval (_cue.importer.active_import_name() == "ShieldPkg")
    assert eval (renpy.get_screen("cue_overlay", layer="cue_layer"))
    # Restore live state for the testcases that run after this one.
    run Function(_cue.importer.deactivate)
    assert eval (not _cue.importer.is_active)

testcase overlay_render_sweep:
    run Jump("start")
    # Render smoke for every sidebar page: a screen error in any page fails
    # its interaction, so the run Function calls are the real assertions. The
    # asserts guard against a page that renders but never activates.
    run Function(_cue.overlay.set_page, CuePage.SFX)
    assert eval (_cue.overlay.active_page == CuePage.SFX)
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    assert eval (_cue.overlay.active_page == CuePage.MUSIC)
    run Function(_cue.overlay.set_page, CuePage.REPLAYS)
    assert eval (_cue.overlay.active_page == CuePage.REPLAYS)
    run Function(_cue.overlay.set_page, CuePage.IMPORT)
    assert eval (_cue.overlay.active_page == CuePage.IMPORT)
    run Function(_cue.overlay.set_page, CuePage.SETTINGS)
    assert eval (_cue.overlay.active_page == CuePage.SETTINGS)
    assert screen "cue_overlay" layer "cue_layer"
    # Sidebar mode re-renders the SFX page as the compact library sidebar.
    run Function(_cue.overlay.set_page, CuePage.SFX)
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    assert eval (_cue.sfx.library.is_sidebar_mode is True)
    assert screen "cue_overlay" layer "cue_layer"
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    assert eval (_cue.sfx.library.is_sidebar_mode is False)

testcase import_export_roundtrip:
    run Jump("start")
    $ _cue_test_reset()
    # Local harness runs leave exports/ + imports/ residue (the script only
    # wipes data/backups/video), so clear both dirs first -- the export name
    # and the copied .zip must be deterministic.
    $ import os as _os
    $ import shutil as _shutil
    $ _shutil.rmtree(_cue.exporter.exports_dir(), ignore_errors=True)
    $ _shutil.rmtree(_cue.importer.imports_dir(), ignore_errors=True)
    # The shared-root fixtures carry audio/, so the SFX category is non-empty.
    run Function(_cue.exporter.refresh)
    # refresh() runs on a background thread; wait for the snapshot swap before
    # asserting the category counts are populated.
    pause 0.1 until eval (not _cue.exporter.is_refreshing) timeout 15.0
    assert eval (_cue.exporter.is_category_enabled(CueImportCategory.SFX))
    $ _cue.exporter.name = "Roundtrip"
    run Function(_cue.exporter.export)
    # The zip build runs on a background thread; wait for it to finish.
    pause 0.1 until eval (not _cue.exporter.is_exporting) timeout 15.0
    assert eval (_cue.exporter.export_error == "")
    assert eval (_cue.exporter.export_status != "")
    # A recipient drops the .zip into imports/; scan() auto-extracts it and
    # matches it to this game (same game_id -> AUTO).
    $ _zip_src = _os.path.join(_cue.exporter.exports_dir(), "Roundtrip.zip")
    $ _zip_dst = _os.path.join(_cue.importer.imports_dir(), "Roundtrip.zip")
    $ _os.makedirs(_cue.importer.imports_dir())
    $ _shutil.copy(_zip_src, _zip_dst)
    run Function(_cue.importer.scan)
    # Scan (list + extract + manifest read) also runs on a background thread.
    pause 0.1 until eval (not _cue.importer.is_scanning) timeout 15.0
    assert eval (len(_cue.importer.imports) == 1)
    assert eval (_cue.importer.imports[0]["valid"])
    assert eval (_cue.importer.imports[0]["match"] == CueImportMatch.AUTO)
    # The merge dialog opens on the scanned package and renders its category
    # rows + overwrite summary.  Dialogs are folded into cue_overlay gated on
    # _cue.dialogs.active_dialog, so the state gate is the render proof.
    run Function(_cue.dialogs.merge.open, "Roundtrip")
    assert eval (_cue.dialogs.active_dialog is _cue.dialogs.merge)
    keysym "K_ESCAPE"
    assert eval (_cue.dialogs.active_dialog is None)
    # Activate serves the whole editor from the extracted package: the
    # effective root follows, shared_config stays on the real data root.
    run Function(_cue.importer.activate, "Roundtrip")
    assert eval (_cue.importer.is_active)
    assert eval (_cue.paths.root.endswith("Roundtrip"))
    assert eval (_cue.paths.shared_config_path.startswith(_cue.paths.original_root))
    # Deactivate drops back to the live data tree.
    run Function(_cue.importer.deactivate)
    assert eval (not _cue.importer.is_active)
    assert eval (_cue.paths.root == _cue.paths.original_root)

testcase confirm_dialog_escape:
    run Jump("start")
    run Function(_cue.dialogs.confirm.show, "Really?", _cue.overlay.hide)
    assert eval (_cue.dialogs.active_dialog is _cue.dialogs.confirm)
    keysym "K_ESCAPE"
    assert eval (_cue.dialogs.active_dialog is None)

testcase sfx_library_rows:
    run Jump("start")
    assert eval (len(_cue.sfx.library.files) >= 2)
    assert eval (_cue.sfx.library.scan_error == "")
    assert eval ("sfx_001.ogg" in _cue.sfx.library.files)

testcase empty_library_open_folder_btn:
    run Jump("start")
    $ _cue_test_reset()
    # The empty-state Open Audio/Music folder button is the only place the
    # store-bridged _cue_open_in_os_file_explorer name resolves, so render both
    # pages with empty libraries.  _cue.overlay.set_page does not rescan, so the
    # in-memory empty holds for the render; restore the snapshot right after
    # so later testcases see the seeded libraries (reassign, not scan -- the
    # scan may carry fixtures other testcases created).
    $ _sfx_files = _cue.sfx.library.files
    $ _sfx_tree = _cue.sfx.library.tree
    $ _mu_user_files = _cue.music.library.user_files
    $ _mu_user_tree = _cue.music.library.user_tree
    $ _mu_game_tree = _cue.music.library.game_tree
    $ _cue.sfx.library.files = []
    $ _cue.sfx.library.tree = []
    $ _cue.music.library.user_files = []
    $ _cue.music.library.user_tree = []
    $ _cue.music.library.game_tree = []
    run Function(_cue.overlay.set_page, CuePage.SFX)
    assert eval (_cue.overlay.active_page == CuePage.SFX)
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    assert eval (_cue.overlay.active_page == CuePage.MUSIC)
    # Settings' Data Folder section carries the same button (Open Data Folder).
    run Function(_cue.overlay.set_page, CuePage.SETTINGS)
    assert eval (_cue.overlay.active_page == CuePage.SETTINGS)
    $ _cue.sfx.library.files = _sfx_files
    $ _cue.sfx.library.tree = _sfx_tree
    $ _cue.music.library.user_files = _mu_user_files
    $ _cue.music.library.user_tree = _mu_user_tree
    $ _cue.music.library.game_tree = _mu_game_tree

testcase sfx_file_tree_expand:
    run Jump("start")
    run Function(_cue.sfx.library.toggle_folder, "Sub/")
    assert eval (_cue.sfx.library.expanded_folders.get("Sub/", False))

testcase music_my_music_rows:
    run Jump("start")
    assert eval (len(_cue.music.library.user_files) >= 1)
    assert eval (_cue.music.library.user_files[0].startswith("music/"))

testcase audio_presets_list:
    run Jump("start")
    run Function(_cue.presets.audio.create, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    assert eval ("Test Preset" in _cue.presets.audio.list())
    assert eval (_cue.presets.audio.get("Test Preset")["files"] == ["sfx_001.ogg"])

testcase intensity_groups_crud:
    run Jump("start")
    # Registry CRUD: create, list, get, and the empty-igroup default shape.
    run Function(_cue.presets.intensity.create, "Test Impacts")
    assert eval ("Test Impacts" in _cue.presets.intensity.list())
    assert eval (_cue.presets.intensity.get("Test Impacts")["levels"] == [])
    assert eval (_cue.presets.intensity.get("Test Impacts")["next_ilevel_id"] == 1)
    # [+ Level] creates an empty level and auto-expands group + level.
    run Function(_cue.sfx.library.add_level, "Test Impacts")
    assert eval (_cue.presets.intensity.get("Test Impacts")["levels"] == [{"id": 1, "files": []}])
    assert eval (_cue.sfx.library.expanded_igroups.get("Test Impacts", False))
    assert eval (1 in _cue.sfx.library.expanded_ilevels.get("Test Impacts", set()))
    # Add-files mode: toggle per-level, add a tree folder ref directly.
    run Function(_cue.sfx.library.toggle_ilevel_add_mode, "Test Impacts", 1)
    assert eval (_cue.sfx.library.ilevel_add_target == ("Test Impacts", 1))
    run Function(_cue.sfx.library.ilevel_add_folder, "Test Impacts", 1, "Sub/")
    assert eval (_cue.presets.intensity.get("Test Impacts")["levels"][0]["files"] == ["Sub/"])
    assert eval (_cue.sfx.library.level_has_file("Test Impacts", 1, "Sub/"))
    # Level folder refs render as expandable folder UI (shared with the tree).
    run Function(_cue.sfx.library.toggle_file_ref_expand, "Sub/")
    assert eval (_cue.sfx.library.expanded_file_refs.get("Sub/", False))
    run Function(_cue.sfx.library.toggle_file_ref_expand, "Sub/")
    assert eval (not _cue.sfx.library.expanded_file_refs.get("Sub/", False))
    # A duplicate add is rejected by add_level_file (the tree disables the
    # button via level_has_file, so a direct call surfaces the guard).
    $ _err = _cue.intensity.add_level_file("Test Impacts", 1, "Sub/")
    assert eval (_err is not None)
    assert eval (_cue.presets.intensity.get("Test Impacts")["levels"][0]["files"] == ["Sub/"])
    # Toggling again exits add-files mode.
    run Function(_cue.sfx.library.toggle_ilevel_add_mode, "Test Impacts", 1)
    assert eval (_cue.sfx.library.ilevel_add_target is None)
    # Block + group rows compile and render on the SFX page.  Entering add
    # mode auto-expanded the level, so it starts expanded here.
    run Function(_cue.sfx.library.toggle_igroups_expand)
    assert eval (_cue.sfx.library.igroups_expanded)
    assert eval (_cue.sfx.library.expanded_igroups.get("Test Impacts", False))
    run Function(_cue.sfx.library.toggle_igroup_expand, "Test Impacts")
    assert eval (_cue.sfx.library.expanded_igroups.get("Test Impacts", False) is False)
    run Function(_cue.sfx.library.toggle_ilevel_expand, "Test Impacts", 1)
    assert eval (1 not in _cue.sfx.library.expanded_ilevels.get("Test Impacts", set()))
    run Function(_cue.overlay.set_page, CuePage.SFX)
    pause 0.5
    # Add-mode branches render: level row + file tree becomes an adder.
    run Function(_cue.sfx.library.toggle_ilevel_add_mode, "Test Impacts", 1)
    pause 0.5
    run Function(_cue.sfx.library.toggle_ilevel_add_mode, "Test Impacts", 1)
    # New-group dialog smoke: opens, renders, cancels.
    run Function(_cue.dialogs.intensity.open)
    assert eval (_cue.dialogs.active_dialog is _cue.dialogs.intensity)
    run Function(_cue.dialogs.intensity.cancel)
    assert eval (_cue.dialogs.active_dialog is None)
    # One JSON landed on disk under data/presets/intensity/.
    $ import os as _os
    $ _ok = _os.path.isdir(_cue.paths.intensity_preset_dir)
    $ _ok = _ok and len([f for f in _os.listdir(_cue.paths.intensity_preset_dir) if f.startswith("Test")]) == 1
    assert eval (_ok)
    # Delete removes it from memory and disk.
    run Function(_cue.presets.intensity.delete, "Test Impacts")
    assert eval ("Test Impacts" not in _cue.presets.intensity.list())

testcase intensity_resolves_level_folders:
    run Jump("start")
    $ _cue_test_reset()
    # Real 3-level group; band [0.7, 1.0, 1.3] lands one speed per level.
    $ _cue_intensity_folders()
    run Function(_cue.presets.intensity.create, "Resolve Test")
    run Function(_cue.sfx.library.add_level, "Resolve Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Resolve Test", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Resolve Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Resolve Test", 2, "hard/")
    run Function(_cue.sfx.library.add_level, "Resolve Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Resolve Test", 3, "empty/")
    # A pool hooked to Level 1 resolves up to the active level's files.
    $ _r1 = _cue.intensity.resolve_pool_intensity("Resolve Test", 1, 0.7, [0.7, 1.0, 1.3])
    assert eval (_r1 is not None)
    assert eval (_r1.level == 1)
    assert eval (_r1.files == ["soft/sfx_001.ogg"])
    assert eval (_r1.volume_mult == 1.0)
    $ _r2 = _cue.intensity.resolve_pool_intensity("Resolve Test", 1, 1.0, [0.7, 1.0, 1.3])
    assert eval (_r2.level == 2)
    assert eval (_r2.files == ["hard/sfx_001.ogg", "hard/sfx_002.ogg"])
    assert eval (_r2.volume_mult == 1.125)
    # Fastest speed -> Level 3; its folder is empty, so silence (no fallback).
    $ _r3 = _cue.intensity.resolve_pool_intensity("Resolve Test", 1, 1.3, [0.7, 1.0, 1.3])
    assert eval (_r3.level == 3)
    assert eval (_r3.files == [])
    # A pool not hooked to any group resolves to nothing.
    assert eval (_cue.intensity.resolve_pool_intensity(None, None, 1.0, [0.7, 1.0, 1.3]) is None)
    run Function(_cue.presets.intensity.delete, "Resolve Test")
    $ _cue_intensity_cleanup()

testcase intensity_loop_fire_path:
    run Jump("start")
    $ _cue_test_reset()
    # Real 3-level group; the loop pool hooks Level 1 (soft/).
    $ _cue_intensity_folders()
    run Function(_cue.presets.intensity.create, "Fire Test")
    run Function(_cue.sfx.library.add_level, "Fire Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Fire Test", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Fire Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Fire Test", 2, "hard/")
    run Function(_cue.sfx.library.add_level, "Fire Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Fire Test", 3, "empty/")
    # An image tag can't start a speed sequence (no video path), so current
    # speed falls through to speed_pref = 1.0 -> Level 2 (hard/).
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["multi_speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["speed_pref"] = 1.0
    $ _cue.marker_store._get_or_create_entry("l_cueimg_a")["pools"] = [{"igroup": {"name": "Fire Test", "level": 1}, "files": [], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    pause 0.1 until eval (_cue_played_from("hard/")) timeout 5.0
    assert eval (_cue_played_from("hard/"))
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("v_cueimg_a", None)
    run Function(_cue.presets.intensity.delete, "Fire Test")
    $ _cue_intensity_cleanup()

testcase intensity_toggle_master_off:
    run Jump("start")
    $ _cue_test_reset()
    # Master toggle off: banding is disabled, so the loop pool plays its PINNED
    # level's files (Level 1 = soft/) instead of the active level (hard/),
    # unscaled.  soft/ gets two files so the pick is recorded.
    $ _cue_intensity_toggle_folders()
    run Function(_cue.presets.intensity.create, "Toggle Test")
    run Function(_cue.sfx.library.add_level, "Toggle Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Toggle Test", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Toggle Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Toggle Test", 2, "hard/")
    # The video entry carries a hooked (time-less) pool so the per-tick video
    # gate can resolve; a time-less pool never fires as a video marker.
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["pools"] = [{"igroup": {"name": "Toggle Test", "level": 1}, "files": [], "volume": 1.0}]
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["multi_speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["speed_pref"] = 1.0
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["intensity"] = {"enabled": False}
    $ _cue.marker_store._get_or_create_entry("l_cueimg_a")["pools"] = [{"igroup": {"name": "Toggle Test", "level": 1}, "files": [], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    pause 0.1 until eval (_cue_played_from("soft/")) timeout 5.0
    assert eval (_cue_played_from("soft/"))
    assert eval (not _cue_played_from("hard/"))
    # Master off -> no intensity mode: the per-tick video gate stays None.
    assert eval (_cue.trigger._vid_intensity is None)
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("v_cueimg_a", None)
    run Function(_cue.presets.intensity.delete, "Toggle Test")
    $ _cue_intensity_cleanup()

testcase intensity_toggle_sfx_levels_off:
    run Jump("start")
    $ _cue_test_reset()
    # SFX-levels off (master on): the loop pool plays the PINNED level's files
    # (soft/) while the active level still drives volume -- intensity mode
    # stays live (the video gate is a resolution, not None).
    $ _cue_intensity_toggle_folders()
    run Function(_cue.presets.intensity.create, "Toggle Test")
    run Function(_cue.sfx.library.add_level, "Toggle Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Toggle Test", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Toggle Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Toggle Test", 2, "hard/")
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["pools"] = [{"igroup": {"name": "Toggle Test", "level": 1}, "files": [], "volume": 1.0}]
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["multi_speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["speed_pref"] = 1.0
    $ _cue.marker_store._get_or_create_entry("v_cueimg_a")["intensity"] = {"sfx_levels": False}
    $ _cue.marker_store._get_or_create_entry("l_cueimg_a")["pools"] = [{"igroup": {"name": "Toggle Test", "level": 1}, "files": [], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    pause 0.1 until eval (_cue_played_from("soft/")) timeout 5.0
    assert eval (_cue_played_from("soft/"))
    assert eval (not _cue_played_from("hard/"))
    assert eval (_cue.trigger._vid_intensity is not None)
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("v_cueimg_a", None)
    run Function(_cue.presets.intensity.delete, "Toggle Test")
    $ _cue_intensity_cleanup()

testcase intensity_tab_view:
    run Jump("start")
    $ _cue_test_reset()
    # Video VFX Intensity tab: tri-state view switch, hook + mapping from the
    # live video, and the screen's flag-toggle write path.
    $ _cue_intensity_folders()
    run Function(_cue.presets.intensity.create, "Tab Test")
    run Function(_cue.sfx.library.add_level, "Tab Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Tab Test", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Tab Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Tab Test", 2, "hard/")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue_intensity_variants()
    $ _vidk = _cue_create_vid_key(_cue.current_file)
    $ _cue.marker_store._get_or_create_entry(_vidk)["pools"] = [{"igroup": {"name": "Tab Test", "level": 1}, "files": [], "volume": 1.0}]
    $ _cue.marker_store._get_or_create_entry(_vidk)["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.marker_store._get_or_create_entry(_vidk)["multi_speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.marker_store._get_or_create_entry(_vidk)["speed_pref"] = 1.0
    # Open the SFX page with the Intensity tab; render the inspector.
    run Function(_cue.overlay.set_page, CuePage.SFX)
    run Function(_cue.video_editor.show_tab, CueVideoEditorTab.INTENSITY)
    $ renpy.restart_interaction()
    pause 0.5
    assert eval (_cue.video_editor.tab == CueVideoEditorTab.INTENSITY)
    assert eval (not _cue.video_editor.active)
    # The inspector resolves the hook group + live mapping from the video.
    $ _vid_entry = _cue.markers.get(_vidk, {})
    $ _vid_entries = _cue.markers._resolve_video_pools(_vid_entry)
    $ _pools_hooks = [p.get("igroup") for p in _vid_entries]
    assert eval (_cue.intensity.video_hook(_pools_hooks) == "Tab Test")
    $ _variants = _cue.speed_resolver.banding_speeds(_cue.current_file)
    assert eval (_variants == [0.7, 1.0, 1.3])
    $ _mapping = _cue.intensity.variant_levels("Tab Test", _variants)
    assert eval (_mapping == [(0.7, 1), (1.0, 2), (1.3, 2)])
    $ _cur = _cue.speed_resolver.speed_for(_cue.current_file)
    $ _res = _cue.intensity.resolve_video_intensity(_pools_hooks, _cur, _variants)
    assert eval (_res is not None and _res.level == 2)
    assert eval (_res.files == ["hard/sfx_001.ogg", "hard/sfx_002.ogg"])
    # Screen write path: toggling a flag persists and the live resolution honors it.
    run Function(_cue_toggle_intensity_flag, "enabled")
    $ _entry = _cue.markers.get(_vidk, {})
    $ _flags = _cue.intensity.flags_from_entry(_entry)
    assert eval (_entry.get("intensity", {}).get("enabled", True) is False)
    # Master off -> intensity mode inactive (the video gate is off); the
    # resolution falls back to the pinned level (Level 1), unscaled.
    assert eval (not _cue.intensity.is_pool_intensity_active("Tab Test", _variants, flags=_flags))
    $ _res_off = _cue.intensity.resolve_video_intensity(_pools_hooks, _cur, _variants, flags=_flags)
    assert eval (_res_off is not None and _res_off.level == 1 and _res_off.volume_mult == 1.0)
    run Function(_cue_toggle_intensity_flag, "enabled")
    # SINGLE mode is intensity-capable: the variant set is mode-independent.
    $ _entry["speed_mode"] = CueSpeedMode.SINGLE
    $ _cue.markers.save_marker(_vidk)
    assert eval (_cue.speed_resolver.banding_speeds(_cue.current_file) == [0.7, 1.0, 1.3])
    $ _single_res = _cue.intensity.resolve_video_intensity(_pools_hooks, 1.0, _variants)
    assert eval (_single_res is not None and _single_res.level == 2)
    $ _entry["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.markers.save_marker(_vidk)
    # Tab switching round-trips between all three views.
    run Function(_cue.video_editor.show_tab, CueVideoEditorTab.SPEED)
    assert eval (_cue.video_editor.tab == CueVideoEditorTab.SPEED)
    run Function(_cue.video_editor.show_tab, CueVideoEditorTab.CREATE)
    assert eval (_cue.video_editor.tab == CueVideoEditorTab.CREATE)
    run Function(_cue.video_editor.show_tab, CueVideoEditorTab.SPEED)
    $ _cue.markers.pop(_vidk, None)
    run Function(_cue.presets.intensity.delete, "Tab Test")
    $ _cue_intensity_cleanup()
    $ _cue_intensity_variant_cleanup()

testcase sfx_recently_used:
    run Jump("start")
    # Wired and empty on a fresh game (harness wipes saves/persistent).
    assert eval (_cue.sfx.library._recent is not None)
    assert eval (_cue.sfx.library._recent.entries() == [])
    assert eval (not _cue.sfx.library._recent.expanded)
    # A file send records the resolved path; it does not expand the list.
    run Function(_cue.markers.image.send_file, 0)
    assert eval (_cue.sfx.library._recent.entries() == [{"type": "file", "ref": _cue.sfx.library.files[0]}])
    assert eval (not _cue.sfx.library._recent.expanded)
    # A folder send normalizes its ref and bumps to front.
    run Function(_cue.markers.image.send_folder, "Sub/")
    assert eval (_cue.sfx.library._recent.entries()[0] == {"type": "folder", "ref": "Sub/"})
    assert eval (len(_cue.sfx.library._recent.entries()) == 2)
    # A preset send records; repeating it bumps without duplicating.
    run Function(_cue.presets.audio.create, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.markers.image.send_preset, "Test Preset")
    assert eval (len(_cue.sfx.library._recent.entries()) == 3)
    run Function(_cue.markers.image.send_preset, "Test Preset")
    assert eval (len(_cue.sfx.library._recent.entries()) == 3)
    assert eval (_cue.sfx.library._recent.entries()[0] == {"type": "preset", "ref": "Test Preset"})
    # Render the SFX page so the Recently Used row compiles and displays.
    run Function(_cue.overlay.set_page, CuePage.SFX)

testcase music_recently_used:
    run Jump("start")
    # Wired and empty on a fresh game (harness wipes saves/persistent).
    assert eval (_cue.music._recent is not None)
    assert eval (_cue.music._recent.entries() == [])
    assert eval (not _cue.music._recent.expanded)
    # Adding a My Music song records its u:-tagged ref; it does not expand.
    run Function(_cue.music.add_user_song_to_trigger, "music/song_001.ogg")
    assert eval (_cue.music._recent.entries() == [{"type": "file", "ref": "u:music/song_001.ogg"}])
    assert eval (not _cue.music._recent.expanded)
    # A folder add normalizes its ref and bumps to front.
    run Function(_cue.music.add_user_folder_to_trigger, "music/")
    assert eval (_cue.music._recent.entries()[0] == {"type": "folder", "ref": "u:music/"})
    assert eval (len(_cue.music._recent.entries()) == 2)
    # Repeating an add bumps without duplicating.
    run Function(_cue.music.add_user_folder_to_trigger, "music/")
    assert eval (len(_cue.music._recent.entries()) == 2)
    assert eval (_cue.music._recent.entries()[0] == {"type": "folder", "ref": "u:music/"})
    # Render the Music page so the Recently Used row compiles and displays.
    run Function(_cue.overlay.set_page, CuePage.MUSIC)

testcase intensity_hook_level_to_target:
    run Jump("start")
    $ _cue_test_reset()
    # The level-row [+] hooks the resolved target's active pool through
    # _cue_send_level_to_target: video/loop pools get igroup + ilevel_id (files
    # cleared); image pools are one-shot and can't hold a hook -- a no-op there.
    $ _cue_intensity_folders()
    run Function(_cue.presets.intensity.create, "Guard A")
    run Function(_cue.sfx.library.add_level, "Guard A")
    run Function(_cue.sfx.library.ilevel_add_folder, "Guard A", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Guard A")
    run Function(_cue.sfx.library.ilevel_add_folder, "Guard A", 2, "hard/")
    # Image on screen -> [+] resolves to the image context (video unavailable);
    # hooking a level is a no-op there (one-shot pools can't hold a hook).
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval (_cue.current_file == "cueimg_a")
    $ _cue.markers.set_target_context(CueContextType.IMAGE)
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["soft/"], "volume": 1.0}]
    run Function(_cue_send_level_to_target, "Guard A", 1)
    $ _files = _cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"][0]["files"]
    assert eval (_files == ["soft/"])
    assert eval (_cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"][0].get("igroup") is None)
    # LOOP target with the image still on screen: the loop pool gets the hook.
    $ _cue.markers.set_target_context(CueContextType.LOOP)
    $ _cue.marker_store._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": [], "volume": 1.0, "frequency": CueLoopFrequency.MEDIUM}]
    run Function(_cue_send_level_to_target, "Guard A", 2)
    $ _hook_pool = _cue.marker_store._get_or_create_entry("l_cueimg_a")["pools"][0]
    assert eval (_hook_pool.get("igroup")["name"] == "Guard A")
    assert eval (_hook_pool.get("igroup")["level"] == 2)
    assert eval (_hook_pool.get("files") == [])
    $ _cue.markers.pop("l_cueimg_a", None)
    $ _cue.markers.pop("i_cueimg_a", None)
    # Restore the default target so the one-process suite sees no leak.
    $ _cue.markers.set_target_context(CueContextType.VIDEO)
    run Function(_cue.presets.intensity.delete, "Guard A")
    $ _cue_intensity_cleanup()

testcase intensity_hook_pool_renders:
    run Jump("start")
    $ _cue_test_reset()
    # A pool hooked to an intensity level renders its level's files read-only
    # (preview button only -- no remove) on the Loop and Video SFX sections.
    # A render crash here fails the interaction.
    $ _cue_intensity_folders()
    run Function(_cue.presets.intensity.create, "Hook Render")
    run Function(_cue.sfx.library.add_level, "Hook Render")
    run Function(_cue.sfx.library.ilevel_add_folder, "Hook Render", 1, "soft/")
    # Video target: hook the active video pool, render the Video SFX section.
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    run Function(_cue.overlay.set_page, CuePage.SFX)
    pause 0.2
    run Function(_cue_send_level_to_target, "Hook Render", 1)
    $ _vidk = _cue_create_vid_key(_cue.current_file)
    $ _vp = _cue.marker_store._get_or_create_entry(_vidk)["pools"][0]
    assert eval (_vp.get("igroup")["name"] == "Hook Render")
    assert eval (_vp.get("files") == [])
    $ _vl = _cue.intensity.level_files_by_id("Hook Render", _vp.get("igroup")["level"] or 0)
    assert eval (_vl == ["soft/"])
    pause 0.3
    # Loop target: hook a loop pool, render the Loop SFX section.
    $ _cue.markers.set_target_context(CueContextType.LOOP)
    $ _loop_key = _cue_create_loop_key(_cue.current_file or "")
    $ _cue.marker_store._get_or_create_entry(_loop_key)["pools"] = [
        {"files": [], "volume": 1.0, "frequency": CueLoopFrequency.MEDIUM}]
    run Function(_cue_send_level_to_target, "Hook Render", 1)
    $ _lp = _cue.marker_store._get_or_create_entry(_loop_key)["pools"][0]
    assert eval (_lp.get("igroup")["name"] == "Hook Render")
    $ _lr = _cue.markers.resolve_pool(_lp)
    assert eval (_lr.igroup["name"] == "Hook Render" and _lr.refs == [])
    pause 0.3
    # Cleanup.
    $ _cue.markers.pop(_loop_key, None)
    $ _cue.markers.pop(_vidk, None)
    $ _cue.markers.set_target_context(CueContextType.VIDEO)
    run Function(_cue.presets.intensity.delete, "Hook Render")
    $ _cue_intensity_cleanup()

testcase sfx_target_context:
    run Jump("start")
    $ _cue_test_reset()
    # Hotkeys select the target context on the SFX page (bar + [+] rows compile).
    # _cue.overlay.set_page does not re-render the keybind screen, so settle a frame
    # before the first keysym or it races the SFX hotkey registration.
    run Function(_cue.overlay.set_page, CuePage.SFX)
    pause 0.1
    keysym "K_3"
    assert eval (_cue.markers.target_context == CueContextType.DIALOGUE)
    keysym "K_4"
    assert eval (_cue.markers.target_context == CueContextType.LOOP)
    keysym "K_1"
    assert eval (_cue.markers.target_context == CueContextType.VIDEO)
    # Compile the preset + video preset + recently-used list rows ([+] rows).
    run Function(_cue.presets.audio.create, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.sfx.library.toggle_presets_expand)
    run Function(_cue.sfx.library.toggle_video_presets_expand)
    # Image on screen: video target falls back to image; [+] routes there.
    $ _cue_test_reset()
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval (_cue.current_file == "cueimg_a")
    assert eval (_cue.markers.target_is_available(CueContextType.IMAGE))
    keysym "K_1"
    run Function(_cue_markers_send, "file", 0)
    assert eval (_cue.markers.image.has_pools())
    $ _cue.markers.image.clear()
    # Movie on screen: image target falls back to video; [+] routes there.
    $ _cue_test_reset()
    $ renpy.show("cuevid")
    pause 1.0
    assert eval (_cue.top_layer_type == "movie")
    keysym "K_2"
    run Function(_cue_markers_send, "folder", "Sub/")
    assert eval (_cue.markers.video.has_pools())
    $ _cue.markers.video.clear()
    $ _cue_test_reset()
    # Note: search-field typing not exercised here -- driving an input's
    # focus needs a click primitive the test DSL lacks. Ren'Py's Input
    # consumes text keys (K_1..K_4) while focused, so screen hotkeys don't
    # fire mid-typing; verified manually.

testcase music_presets:
    run Jump("start")
    # Create a preset from stored u:/g: refs and read it back.
    run Function(_cue.presets.music.create, "Test Music Preset", ["u:music/song_001.ogg", "g:bgm/song_002.ogg"])
    assert eval ("Test Music Preset" in _cue.presets.music.list())
    assert eval (_cue.presets.music.get("Test Music Preset")["files"] == ["u:music/song_001.ogg", "g:bgm/song_002.ogg"])
    # Display rows resolve each stored ref to a My/Game Music path.
    assert eval (_cue.music.preset_display_files(_cue.presets.music.get("Test Music Preset")) == ["My Music/song_001.ogg", "Game Music/bgm/song_002.ogg"])
    # Expand + render the Music page so the preset rows compile and display.
    run Function(_cue.music.toggle_presets_expand)
    assert eval (_cue.music.presets_expanded)
    run Function(_cue.music.toggle_preset_expand, "Test Music Preset")
    assert eval (_cue.music.expanded_presets.get("Test Music Preset", False))
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    # Deleting removes it from memory and disk.
    run Function(_cue.presets.music.delete, "Test Music Preset")
    assert eval ("Test Music Preset" not in _cue.presets.music.list())

testcase video_movie_detected:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    assert eval (_cue.top_layer_type == "movie")
    assert eval (_cue.vid_manager.channel is not None)
    assert eval (_cue.vid_manager.get_duration() > 0)

testcase video_sfx_timeline_seeded:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    assert eval (_cue.markers.video.has_markers())
    assert eval (len(_cue.markers.video.get_markers()) >= 1)
    assert eval (0 <= _cue.markers.video.active_pool < len(_cue.markers.video.get_markers()))

testcase video_marker_timeline_drag_survives_restart:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    # Seed a marker so the SFX page renders the draggable timeline.
    $ _cue.markers.video.add_pool()
    pause 0.5
    # The class-level get_timeline() returns the singleton displayable, so
    # drag state set on it must survive the timer-fired restart_interaction
    # that re-runs the screen body.  An inline-constructed timeline would be a
    # fresh object after the restart, wiping the state -- the regression this
    # guards.  _tip_text is not asserted: it is hover-mutable by design, so a
    # hover event during the pause legitimately recomputes it.
    $ _tl = CueVideoMarkerTimeline.get_timeline()
    $ _tl._drag_idx = 0
    $ _tl._drag_on = True
    $ renpy.restart_interaction()
    pause 0.3
    $ _tl2 = CueVideoMarkerTimeline.get_timeline()
    assert eval (_tl2 is _tl)
    assert eval (_tl2._drag_idx == 0)
    assert eval (_tl2._drag_on)

testcase video_multi_edit_fans_out:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.selected = {0, 1}
    $ _cue.markers.video.set_selected_volume(0.3)
    $ _vkey = _cue.markers.video._key()
    $ _vpools = _cue.markers.get(_vkey)["pools"]
    assert eval (_vpools[0].get("volume") == 0.3)
    assert eval (_vpools[1].get("volume") == 0.3)
    run Function(_cue.presets.audio.create, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    $ _cue.markers.video.apply_preset_active("Test Preset")
    $ _vpools = _cue.markers.get(_vkey)["pools"]
    assert eval (_vpools[0].get("preset") == "Test Preset")
    assert eval (_vpools[1].get("preset") == "Test Preset")
    $ _cue.markers.detach_active_video_ts()
    $ _vpools = _cue.markers.get(_vkey)["pools"]
    assert eval ("preset" not in _vpools[0])
    assert eval ("preset" not in _vpools[1])
    assert eval (_vpools[0].get("files") == ["sfx_001.ogg"])
    assert eval (_vpools[1].get("files") == ["sfx_001.ogg"])

testcase video_multi_duplicate_fans_out:
    run Jump("start")
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
    assert eval (len(_vpools) == 5)
    $ _times = [p["time"] for p in _vpools]
    $ _copy1 = any(abs(t - (0.2 + _gap)) < 1e-6 for t in _times)
    $ _copy2 = any(abs(t - (0.6 + _gap)) < 1e-6 for t in _times)
    assert eval (_copy1 and _copy2)
    $ _sel = _cue.markers.video.selected
    assert eval (len(_sel) == 2)
    assert eval (_cue.markers.video.active_pool in _sel)

testcase video_multi_delete_pool_group:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.clear()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.selected = {0, 2}
    $ _cue.markers.video.delete_pool_ui()
    $ _vpools = _cue.markers.get(_cue.markers.video._key())["pools"]
    assert eval (len(_vpools) == 1)
    assert eval (_cue.markers.video.selected == set())

testcase volume_value_equality_distinguishes_multisetter:
    run Jump("start")
    $ _d = {"volume": 1.0}
    $ _v_none = _CueVolumeValue(_d, "volume", "k", multi_setter=None, range=1.0)
    $ _v_set = _CueVolumeValue(_d, "volume", "k", multi_setter=_cue.markers.video.set_selected_volume, range=1.0)
    $ _v_set2 = _CueVolumeValue(_d, "volume", "k", multi_setter=_cue.markers.video.set_selected_volume, range=1.0)
    # FieldEquality over equality_fields gates the displayable-reuse cache:
    # a value carrying multi_setter must not equal one without it, or the
    # screen keeps reusing a cached multi_setter=None instance and the
    # fan-out is silently dropped.
    assert eval (_v_none != _v_set)
    assert eval (_v_set == _v_set2)
    assert eval (_v_none == _v_none)

testcase volume_value_changed_fans_out_and_queues_save:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.add_pool()
    $ _cue.markers.video.selected = {0, 1}
    $ _vid_key = _cue.markers.video._key()
    $ _vpools = _cue.markers.get(_vid_key)["pools"]
    $ _vol_val = _CueVolumeValue(_vpools[0], "volume", _vid_key, multi_setter=_cue.markers.video.set_selected_volume, range=_cue.volume.VOL_MAX)
    # The slider path end-to-end: DictValue writes the active dict, the
    # multi_setter fans out to the other selected pool, and the marker save
    # is queued (deferred), not written immediately. changed() triggers a
    # restart_interaction (via DictValue.changed), whose redraw can run the
    # slow-tick save flush -- so the queued-save check must happen in the same
    # $ statement, before the event loop drains the set.
    $ _vol_val.changed(0.4); _queued = _vid_key in _cue.volume._pending_saves
    assert eval (_vpools[0]["volume"] == 0.4)
    assert eval (_vpools[1]["volume"] == 0.4)
    assert eval (_queued)

testcase video_sfx_edit_locked_off_base_speed:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    assert eval (_cue.speed_resolver.get_current_speed() == CUE_DEFAULT_VIDEO_SPEED)
    $ _cue.speed_resolver.set_speed(1.5)
    assert eval (_cue.speed_resolver.get_current_speed() == 1.5)
    $ _cue.speed_resolver.set_speed(CUE_DEFAULT_VIDEO_SPEED)
    assert eval (_cue.speed_resolver.get_current_speed() == CUE_DEFAULT_VIDEO_SPEED)

testcase video_vfx_speed_sequence:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.markers.video.add_pool()
    $ _cue.video_sequence.append_speed(1.5)
    assert eval (1.5 in (_cue.video_sequence.speeds_for(_cue.current_file) or []))
    assert eval (_cue.video_sequence.get_mode() == CueSpeedMode.SINGLE)

testcase video_auto_speed_state:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    assert eval (_cue.auto_speed.active_preset == "roller_coaster")
    assert eval (len(_cue.auto_speed.enabled_speeds) >= 1)

testcase video_speed_variant_created:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.video_editor.create(1.5)
    pause 0.1 until eval (not _cue.video_editor.job_queue.processing) timeout 30.0
    $ _base = _cue.speed_resolver.base_path_for(_cue.current_file)
    $ _variant = _cue.speed_resolver.variant_path(_base, 1.5)
    # base_path_for returns a game-relative vpath; variant_path(base, 1.0)
    # resolves it to a real fs path so ffprobe (which runs from the harness
    # CWD, not gamedir) can open it.
    $ _base_fs = _cue.speed_resolver.variant_path(_base, 1.0)
    $ _ff = _cue.video_editor._ffmpeg
    $ _dur_base = _ff.probe_duration(_base_fs)
    $ _dur_var = _ff.probe_duration(_variant)
    $ import os as _os
    assert eval (_base is not None)
    assert eval (_os.path.exists(_variant))
    assert eval (1.5 in _cue.speed_resolver.get_available_speeds(_base))
    # The real encode output is correct: duration scales by 1/factor, and the
    # default remove_audio=True strips the (present) audio track.
    assert eval (_dur_base > 0)
    assert eval (abs(_dur_var - _dur_base / 1.5) < 0.3)
    assert eval (_ff.probe_has_audio(_base_fs) is True)
    assert eval (_ff.probe_has_audio(_variant) is False)
    # remove_audio=False keeps the audio track on the next variant.
    $ _cue.video_editor.remove_audio = False
    $ _cue.video_editor.create(2.0)
    pause 0.1 until eval (not _cue.video_editor.job_queue.processing) timeout 30.0
    $ _variant2 = _cue.speed_resolver.variant_path(_base, 2.0)
    assert eval (_os.path.exists(_variant2))
    assert eval (_ff.probe_has_audio(_variant2) is True)
    $ _cue.video_editor.remove_audio = True

testcase click_create_tab_opens_editor:
    run Jump("start")
    $ _test.timeout = 5.0
    # page_nav leaves active_page on MUSIC, and store state persists
    # between testcases in the same process. _cue.overlay.set_page restarts the
    # interaction, so the sidebar actually rebuilds with the SFX page.
    run Function(_cue.overlay.set_page, CuePage.SFX)
    $ renpy.show("cuevid")
    pause 2.0
    assert eval (_cue.top_layer_type == "movie")
    # The store says movie, but the SFX page's video sections only appear
    # after the screen rebuilds -- restart + render one frame so the Create
    # tab is in the tree the click will target.
    $ renpy.restart_interaction()
    pause 0.3
    assert eval (not _cue.video_editor.active)
    # Real mouse click on the Video VFX "Create" tab. Regression: the marker
    # timeline's MOUSEBUTTONUP handler once raised IgnoreEvent() on every
    # release (even over sibling buttons), which swallowed the button's
    # release globally and made the whole Video VFX tab unclickable.
    click "Create"
    assert eval (_cue.video_editor.active)

testcase video_queue_error_msg_substitute_guard:
    run Jump("start")
    $ _test.timeout = 10.0
    run Function(_cue.overlay.set_page, CuePage.SFX)
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.video_editor.create(1.5)
    pause 0.1 until eval (not _cue.video_editor.job_queue.processing) timeout 30.0
    # Regression for the CI crash on runners without ffmpeg: a failed encode
    # sets error_msg to "[Errno 2] ...". The queue text used to be substituted,
    # so those brackets were py_eval'd and crashed the whole overlay on every
    # render. Both dynamic text lines are `substitute False` now -- render the
    # queue with a bracketed error (and bracketed filename) to prove it.
    $ _cue.video_editor.show_tab(CueVideoEditorTab.CREATE)
    $ _job = _cue.video_editor.job_queue.jobs[-1]
    $ _job.status = CueJobStatus.ERROR
    $ _job.vpath = "videos/[bracket] scene.mp4"
    $ _job.error_msg = "[Errno 2] No such file or directory: 'ffmpeg'"
    $ renpy.restart_interaction()
    pause 0.3
    assert eval (_job.error_msg == "[Errno 2] No such file or directory: 'ffmpeg'")
    $ _cue.video_editor.show_tab(CueVideoEditorTab.SPEED)
    $ renpy.restart_interaction()

testcase video_seamless_transition_preserves_position:
    run Jump("start")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue.video_editor.create(1.5)
    pause 0.1 until eval (not _cue.video_editor.job_queue.processing) timeout 30.0
    $ _base = _cue.speed_resolver.base_path_for(_cue.current_file)
    # Isolate from prior testcases: base speed, no speed sequence, seamless off
    # -- so the base file is what's actually playing before the flip.
    $ _cue.video_sequence.clear_sequence()
    $ _cue.speed_resolver.seamless_transition = False
    $ _cue.speed_resolver._set_speed_pref(_cue.current_file, 1.0)
    $ renpy.restart_interaction()
    pause 0.3
    $ _before_ch = _cue.vid_manager.channel
    $ _before_playing = _cue.vid_manager.get_video_path()
    assert eval (_before_ch is not None)
    assert eval (_os.path.basename(_before_playing or "") == _os.path.basename(_base))
    $ _cue.speed_resolver.toggle_seamless()
    $ _cue.speed_resolver.set_speed(1.5)
    pause 0.1 until eval (_cue.speed_resolver._pending_speed is None) timeout 15.0
    $ _after_ch = _cue.vid_manager.channel
    $ _after_playing = _cue.vid_manager.get_video_path()
    $ _after_pos = _cue.vid_manager.get_elapsed()
    $ _after_dur = _cue.vid_manager.get_duration()
    $ _variant = _cue.speed_resolver.variant_path(_base, 1.5)
    assert eval (_after_ch == _before_ch)
    assert eval (_os.path.normpath(_after_playing) == _os.path.normpath(_variant))
    assert eval (0.0 <= _after_pos < _after_dur)

testcase img_trigger_fires_on_show:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("i_cueimg_a", None)

testcase dlg_trigger_fires_on_say:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("d_cueimg_a__Hello")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    run Jump("cue_say_fire")
    pause 1.0
    assert eval (_cue.current_file == "cueimg_a")
    assert eval (_cue.current_dialogue == "Hello")
    assert eval (_cue.markers.get("d_cueimg_a__Hello") is not None)
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("d_cueimg_a__Hello", None)

testcase replay_cast_records_speakers:
    run Jump("start")
    $ _cue_test_reset()
    $ import json as _json
    $ import os as _os
    $ _cast_path = _cue.paths.replay_path("test_replay")
    $ renpy.store._in_replay = "test_replay"
    run Jump("cue_say_fire")
    pause 0.5
    # Character callback resolved the speaker (the character's tag, matching
    # _last_say_who) and recorded the replay cast.
    assert eval (_cue.ctx.current_who == "cuespk")
    assert eval (_os.path.exists(_cast_path))
    assert eval (_json.load(open(_cast_path))["characters"] == ["cuespk"])
    # A dialogue marker created while the speaker line is on screen captures
    # the speaker at creation (first write wins).
    $ _cue.marker_store._get_or_create_entry("d_cueimg_a__Hello")
    assert eval (_cue.markers.get("d_cueimg_a__Hello")["speaker"] == "cuespk")
    $ _cue.markers.pop("d_cueimg_a__Hello", None)
    $ if _os.path.exists(_cast_path): _os.remove(_cast_path)

testcase loop_trigger_fires_on_cycle:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    pause 0.1 until eval (len(_cue.trigger.last_played) >= 1) timeout 5.0
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("l_cueimg_a", None)

testcase video_marker_fires_at_ts:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("v_cuevid")["pools"] = [{"time": 0.0, "files": ["sfx_001.ogg"], "volume": 1.0}]
    $ renpy.show("cuevid")
    pause 1.0
    assert eval (_cue.top_layer_type == "movie")
    assert eval (_cue.vid_manager.get_duration() > 0)
    # played_keys is wiped every tick while last_elapsed == 0, so a stuck
    # audio clock would hang the poll below. Fail here instead.
    assert eval (_cue.vid_manager.get_elapsed() > 0.0)
    pause 0.1 until eval (len(_cue.trigger.video.played_keys) >= 1) timeout 10.0
    assert eval (len(_cue.trigger.video.played_keys) == 1)
    $ _cue.markers.pop("v_cuevid", None)

testcase img_oneshot_dedup_no_refire:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ _cue.marker_store._get_or_create_entry("i_cueimg_b")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) == 1)
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) == 1)
    $ renpy.show("cueimg_b")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) == 2)
    $ _cue.markers.pop("i_cueimg_a", None)
    $ _cue.markers.pop("i_cueimg_b", None)

testcase shake_fires_on_with_vpunch:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "trigger_on_shake": True}]
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _cue.trigger.last_played = []
    run Jump("cue_shake_with")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("i_cueimg_a", None)

testcase shake_fires_on_at_vpunch:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "trigger_on_shake": True}]
    $ renpy.show("cueimg_a")
    pause 1.0
    $ _cue.trigger.last_played = []
    run Jump("cue_shake_at")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("i_cueimg_a", None)

testcase music_play_interceptor_installed:
    run Jump("start")
    $ import renpy.audio.music as _music
    assert eval (getattr(_music.play, "__name__", "") == "_on_play")

testcase music_play_pause_toggle:
    run Jump("start")
    $ import renpy.audio.music as _music
    # Play the committed silent fixture; the Music page then renders a live
    # play/pause button in the Now Playing row.
    run Function(_cue.music.library.preview, "u:music/song_001.ogg")
    pause 0.5
    assert eval (_cue.music.now_playing() is not None)
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    pause 0.5
    assert eval (_music.get_pause(channel="music") == False)
    run Function(_cue.music.toggle_pause)
    assert eval (_music.get_pause(channel="music") == True)
    run Function(_cue.music.toggle_pause)
    assert eval (_music.get_pause(channel="music") == False)

testcase music_default_trigger_captured:
    run Jump("start")
    $ _cue_test_reset()
    $ import renpy.audio.music as _music
    $ _default = _cue.paths.music_dir + "song_001.ogg"
    $ renpy.show("cueimg_a")
    pause 1.0
    $ renpy.store._in_replay = "test_replay"
    $ _music.play(_default, channel="music")
    pause 0.5
    # Interception recorded the play event and anchored a default trigger to
    # the scene on screen; the real engine played the file.
    assert eval (_cue.music.last_event is not None)
    assert eval (_cue.music.last_event["type"] == "play")
    assert eval (_cue.music.last_event["channel"] == "music")
    assert eval (_cue.music.last_event["in_replay"] == "test_replay")
    assert eval (len(_cue.music.triggers_for("test_replay")) == 1)
    assert eval (_cue.music.triggers_for("test_replay")[0]["key_before"] == "i_cueimg_a")
    assert eval (_cue.music.triggers_for("test_replay")[0]["filepaths"] == [_default])
    assert eval (_music.get_playing(channel="music") is not None)
    $ _cue_music_test_cleanup()

testcase music_default_override_replaces:
    run Jump("start")
    $ _cue_test_reset()
    $ import renpy.audio.music as _music
    $ import shutil as _shutil
    $ _default = _cue.paths.music_dir + "song_001.ogg"
    $ _shutil.copy2(_default, _cue.paths.music_dir + "song_002.ogg")
    $ renpy.show("cueimg_a")
    pause 1.0
    $ renpy.store._in_replay = "test_replay"
    # Capture the scripted default for the scene, then customize it: the first
    # user song disables the default, so a replay `play music` is replaced.
    $ _music.play(_default, channel="music")
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["music"] = ["u:music/song_002.ogg"]
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["music_default_disabled"] = True
    $ _cue.music._pending = None
    $ _music.play(_default, channel="music")
    pause 0.5
    assert eval ("song_002" in (_music.get_playing(channel="music") or ""))
    assert eval (_cue.music.now_playing() is not None)
    # The override is skipped for _record: the replacement never re-records
    # the trigger with the custom path.
    assert eval (_cue.music.triggers_for("test_replay")[0]["filepaths"] == [_default])
    $ _cue_music_test_cleanup()

testcase music_default_suppress_when_disabled:
    run Jump("start")
    $ _cue_test_reset()
    $ import renpy.audio.music as _music
    $ _default = _cue.paths.music_dir + "song_001.ogg"
    $ renpy.show("cueimg_a")
    pause 1.0
    $ renpy.store._in_replay = "test_replay"
    $ _music.play(_default, channel="music")
    pause 0.5
    assert eval (_music.get_playing(channel="music") is not None)
    # Disable the recorded default with no replacement songs: the replay's
    # `play music` is silenced, not forwarded.
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["music_default_disabled"] = True
    $ _cue.music._pending = None
    $ _music.play(_default, channel="music")
    pause 0.5
    assert eval (not _music.get_playing(channel="music"))
    # The silenced play records nothing -- last_event is still the capture.
    assert eval (_cue.music.last_event["filenames"] == _default)
    $ _cue_music_test_cleanup()

testcase music_interceptor_forwards_other_channels:
    run Jump("start")
    $ _cue_test_reset()
    $ import renpy.audio.music as _music
    $ _default = _cue.paths.music_dir + "song_001.ogg"
    $ renpy.show("cueimg_a")
    pause 1.0
    # Sound/voice funnel through the same wrapped functions; even in replay
    # they forward untouched and never record a music event or trigger.
    $ renpy.store._in_replay = "test_replay"
    $ _music.play(_default, channel="sound")
    pause 0.5
    assert eval (_cue.music.last_event is None)
    assert eval (_cue.music._triggers.get("test_replay") is None)
    assert eval ("song_001" in (_music.get_playing(channel="sound") or ""))
    $ _music.stop(channel="sound")
    $ _cue_music_test_cleanup()

testcase music_custom_auto_plays_on_scene_change:
    run Jump("start")
    $ _cue_test_reset()
    $ import renpy.audio.music as _music
    # A custom-trigger scene (music list, no recorded default) auto-plays its
    # pool via the scene-change hook when the player lands on it.
    $ _cue.marker_store._get_or_create_entry("i_cueimg_a")["music"] = ["u:music/song_001.ogg"]
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval ("song_001" in (_music.get_playing(channel="music") or ""))
    # play_custom_music goes straight to the original, so nothing is recorded.
    assert eval (_cue.music.last_event is None)
    $ _cue_music_test_cleanup()

# Renders etext with tag + interpolation characters in the value, so the
# statement compiles and displays them literally (an unescaped value would
# crash the interaction or garble the text).
screen _cue_etext_smoke():
    style_group "cue"

    vbox:
        etext "{b}file[x].mp3"
        etext "{b}file[x].mp3" substitute False

testcase etext_escapes_dynamic_string:
    run Jump("start")
    # CueSafeText escapes before Text substitutes: `{` is doubled for the tag
    # tokenizer (it stays doubled in .text), and the escaped `[` was collapsed
    # back to a literal by substitution -- .text holds the escaped form that
    # renders as the literal input.
    $ _t = CueSafeText("{b}file[x].mp3")
    assert eval (_t.text[0] == "{{b}file[x].mp3")
    # substitute False: brackets are already literal (no substitution runs),
    # so only braces are doubled; the value still renders literally.
    $ _t2 = CueSafeText("{b}file[x].mp3", substitute=False)
    assert eval (_t2.text[0] == "{{b}file[x].mp3")
    # Render the statement itself -- both variants display without the raw
    # string being parsed as a tag or interpolated.
    $ renpy.show_screen("_cue_etext_smoke", _layer="cue_layer")
    pause 0.5
    assert screen "_cue_etext_smoke" layer "cue_layer"
    $ renpy.hide_screen("_cue_etext_smoke")

testcase pages_render_data:
    run Jump("start")
    $ _cue_test_reset()
    # Render smoke test: every page must execute its render code under
    # realistic data.  A screen referencing an unbridged store name (or any
    # render crash) fails the interaction, not just the assertions below.
    # Seed pool + video presets, an intensity group, recents and an expanded
    # tree folder so each section's data-driven branches actually run.
    run Function(_cue.presets.audio.create, "Render Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.markers.create_video_preset, "Render Video Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.sfx.library.toggle_presets_expand)
    run Function(_cue.sfx.library.toggle_video_presets_expand)
    run Function(_cue.sfx.library.toggle_folder, "Sub/")
    # In-memory recents (no persistent write) so the row render runs.
    $ _cue.sfx.library._recent._entries = [{"type": "file", "ref": "sfx_001.ogg"}]
    $ _cue.sfx.library._recent.expanded = True
    run Function(_cue.presets.intensity.create, "Render IGroup")
    run Function(_cue.sfx.library.add_level, "Render IGroup")
    run Function(_cue.sfx.library.ilevel_add_folder, "Render IGroup", 1, "Sub/")
    run Function(_cue.sfx.library.toggle_igroups_expand)
    run Function(_cue.sfx.library.toggle_igroup_expand, "Render IGroup")
    # Music preset + recent for the Music page rows.
    run Function(_cue.presets.music.create, "Render Music Preset", ["u:music/song_001.ogg"])
    run Function(_cue.music.toggle_presets_expand)
    run Function(_cue.music.toggle_preset_expand, "Render Music Preset")
    $ _cue.music._recent._entries = [{"type": "file", "ref": "u:music/song_001.ogg"}]
    $ _cue.music._recent.expanded = True
    # Walk every page; each set_page + pause re-renders that page.
    run Function(_cue.overlay.set_page, CuePage.SFX)
    pause 0.5
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    pause 0.5
    run Function(_cue.overlay.set_page, CuePage.IMPORT)
    pause 0.5
    run Function(_cue.overlay.set_page, CuePage.SETTINGS)
    pause 0.5
    # Overlay survived the walk on the final page.
    assert eval (renpy.get_screen("cue_overlay", layer="cue_layer") is not None)
    assert eval (_cue.overlay.active_page == CuePage.SETTINGS)
    # Cleanup so reordering never leaks seeded state into later testcases.
    run Function(_cue.presets.audio.delete, "Render Preset")
    run Function(_cue.presets.video.delete, "Render Video Preset")
    run Function(_cue.presets.intensity.delete, "Render IGroup")
    run Function(_cue.presets.music.delete, "Render Music Preset")
    $ _cue.sfx.library._recent._entries = []
    $ _cue.sfx.library._recent.expanded = False
    $ _cue.music._recent._entries = []
    $ _cue.music._recent.expanded = False

testcase zz_tmp_mapping_shot:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue_intensity_folders()
    run Function(_cue.presets.intensity.create, "Tab Test")
    run Function(_cue.sfx.library.add_level, "Tab Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Tab Test", 1, "soft/")
    run Function(_cue.sfx.library.add_level, "Tab Test")
    run Function(_cue.sfx.library.ilevel_add_folder, "Tab Test", 2, "hard/")
    $ renpy.show("cuevid")
    pause 1.0
    $ _cue_intensity_variants()
    $ _vidk = _cue_create_vid_key(_cue.current_file)
    $ _cue.marker_store._get_or_create_entry(_vidk)["pools"] = [{"igroup": {"name": "Tab Test", "level": 1}, "files": [], "volume": 1.0}]
    $ _cue.marker_store._get_or_create_entry(_vidk)["speed_mode"] = CueSpeedMode.MULTI
    $ _cue.marker_store._get_or_create_entry(_vidk)["multi_speed_sequence"] = [0.7, 1.0, 1.3]
    $ _cue.marker_store._get_or_create_entry(_vidk)["speed_pref"] = 1.0
    run Function(_cue.overlay.set_page, CuePage.SFX)
    run Function(_cue.video_editor.show_tab, CueVideoEditorTab.INTENSITY)
    $ renpy.restart_interaction()
    pause 0.5
    $ renpy.screenshot("/tmp/cue_mapping.png")
    pause 0.5
    $ _cue.markers.pop(_vidk, None)
    run Function(_cue.presets.intensity.delete, "Tab Test")
    $ _cue_intensity_cleanup()
    $ _cue_intensity_variant_cleanup()

testcase sfx_sidebar_mode_renders:
    run Jump("start")
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    run Jump("start")
    # The sidebar is folded into cue_overlay, so the overlay being mounted is
    # the render proof; the mode flag gates its content.
    assert eval (renpy.get_screen("cue_overlay", layer="cue_layer") is not None)
    assert eval (_cue.sfx.library.is_sidebar_mode is True)
    run Function(_cue.overlay.toggle_section, CUE_SFX_LIBRARY_HEADER)
    run Jump("start")
    # Collapsed while in sidebar mode: the sidebar screen stays shown but its
    # content (and the toolbar visibility button) disappear -- render must not
    # error.
    assert eval (_cue.overlay.collapsed_sections.get(CUE_SFX_LIBRARY_HEADER, False))
    run Function(_cue.overlay.toggle_section, CUE_SFX_LIBRARY_HEADER)
    # Restore state so later testcases render the in-overlay SFX section.
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    run Jump("start")

testcase sfx_sidebar_with_confirm_dialog:
    run Jump("start")
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    run Function(_cue.dialogs.confirm.show, "Really?", _cue.dialogs.confirm.hide)
    run Jump("start")
    assert eval (_cue.dialogs.active_dialog is _cue.dialogs.confirm)
    assert eval (renpy.get_screen("cue_overlay", layer="cue_layer") is not None)
    run Function(_cue.dialogs.confirm.hide)
    run Jump("start")
    assert eval (_cue.dialogs.active_dialog is None)
    # Restore state so later testcases render the in-overlay SFX section.
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    run Jump("start")

testcase sfx_sidebar_resize:
    run Jump("start")
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    run Jump("start")
    # Sidebar is folded into cue_overlay; its resize handle is a stable
    # focusable singleton wired into the (now in-overlay) screen.
    assert eval (renpy.get_screen("cue_overlay", layer="cue_layer") is not None)
    # The resize handle is a stable focusable singleton wired into the screen.
    # Live drag math is covered by pytest -- the screen `dragged` callback
    # only fires on drop with a 2-arg signature, so drags are raw mouse
    # events on the handle.
    assert eval (CueSidebarResizeHandle.get_handle() is CueSidebarResizeHandle.get_handle())
    assert eval (CueSidebarResizeHandle.get_handle().focusable)
    # Hover must hit the handle: Render.add_focus registers the strip so
    # focus_at_point returns it, which is what drives its style.mouse cursor.
    run Jump("start")
    assert eval (renpy.display.render.focus_at_point(int(_cue_scale_ui(_cue_overlay_panel_width) + _cue_scale_ui(_cue.sfx.library.sidebar_width) - _cue_scale_ui(5)), int(renpy.config.screen_height / 2)).widget is CueSidebarResizeHandle.get_handle())
    # The resize cursor must hold for the whole drag. Focus follows the mouse,
    # so once it outruns the 10px strip the handle's style.mouse no longer
    # applies; the handle re-asserts interface.mouse = "cue_resize" on every
    # drag MOTION, the only focus-independent cursor path. Drive one motion
    # straight on the handle and prove the cursor is applied -- pytest covers
    # the full gesture end to end.
    python:
        import pygame
        renpy.display.interface.mouse = "default"
        _h = CueSidebarResizeHandle.get_handle()
        _h._dragging = True
        _ev = pygame.event.Event(pygame.MOUSEMOTION, {"pos": (0, 0)})
        try:
            _h.event(_ev, 5, 100, 0.0)
        except renpy.display.core.IgnoreEvent:
            pass
        _ok = renpy.display.interface.mouse == "cue_resize"
        _h._dragging = False
        renpy.display.interface.mouse = "default"
        if not _ok:
            raise Exception("RESIZE-CURSOR-NOT-APPLIED")
    # Clamps to the max ratio at the top end...
    run Function(_cue.sfx.library.set_sidebar_width, 99999)
    run Jump("start")
    assert eval (_cue.sfx.library.sidebar_width == max(CUE_SIDEBAR_MIN_WIDTH, int(CUE_UI_REF_WIDTH * CUE_SIDEBAR_MAX_WIDTH_RATIO)))
    # ...and to the sidebar minimum at the bottom end.
    run Function(_cue.sfx.library.set_sidebar_width, 1)
    run Jump("start")
    assert eval (_cue.sfx.library.sidebar_width == CUE_SIDEBAR_MIN_WIDTH)
    # Restore state so later testcases render the in-overlay SFX section.
    run Function(_cue.sfx.library.toggle_sidebar_mode)
    run Jump("start")

testcase tree_render:
    run Jump("start")
    $ _cue_test_reset()
    # Every row cue_tree_rows can draw -- folder (with trailing hover buttons),
    # file (gap + warn + size), action (plain + explorer), help (color + v_gap).
    # A compile or layout error in the shared renderer fails this.
    $ _rows = [
        {"key": "t1", "type": "folder", "label": "Folder/", "depth": 0,
         "buttons": [], "toggle": Function(_cue.sfx.library.toggle_folder, "Folder/"),
         "hover_buttons": [{"icon": "chevron-up", "action": NullAction(), "tt": "Move level up"}]},
        {"key": "t2", "type": "file", "label": "a.wav", "depth": 1,
         "buttons": [{"icon": "play", "action": NullAction(), "tt": "Preview audio"}],
         "warn": "bad format", "gap": 1, "size": 11},
        {"key": "t3", "type": "action", "label": "+ Group", "depth": 0,
         "action": NullAction(), "tt": "Create a new intensity group."},
        {"key": "t4", "type": "help", "label": "No files yet.", "depth": 0,
         "color": _cue_color_error, "v_gap": 2},
        {"key": "t5", "type": "action", "label": "Open Music folder", "depth": 0,
         "explorer": "fake/dir"},
    ]
    $ renpy.show_screen("cue_tree_rows", _rows, _layer="cue_layer")
    pause 0.5
    assert screen "cue_tree_rows" layer "cue_layer"
    $ renpy.hide_screen("cue_tree_rows")


testcase settings_page_folder_sections:
    run Jump("start")
    $ _cue_test_reset()
    # Rendering the Settings page exercises the Data Folder section's new
    # SFX/Music folder row editors; a broken cue_sfx_folders or
    # cue_music_folders screen fails this interaction.  The lists hydrate from
    # shared config (empty in a fresh fixture root).
    run Function(_cue.overlay.set_page, CuePage.SETTINGS)
    assert eval (_cue.overlay.active_page == CuePage.SETTINGS)
    run Function(_cue.settings.prepare_for_page)
    assert eval (_cue.settings.music_folders == [])
    assert eval (_cue.settings.sfx_folders == [])

testcase music_external_tree_renders:
    run Jump("start")
    $ _cue_test_reset()
    # A configured external Music folder becomes a top-level tree entry; the
    # Music page render under that state is the smoke test for the external
    # row path.
    $ _md, _sd = _cue_external_dirs()
    $ _cue.music.library.external_folders = [_md]
    $ _cue.music.library.scan()
    assert eval (len(_cue.music.library.external_files) == 1)
    assert eval (_cue.music.library.external_sources[0]["label"] == "ExtMusic")
    assert eval (any(_e.get("name") == "ExtMusic/" for _e in _cue.music.library.tree))
    run Function(_cue.overlay.set_page, CuePage.MUSIC)
    assert eval (_cue.overlay.active_page == CuePage.MUSIC)
    $ _cue_external_cleanup()

testcase sfx_external_tree_renders:
    run Jump("start")
    $ _cue_test_reset()
    # The SFX library wraps built-ins in the synthetic "SFX/" root and
    # appends external folders below it; rendering the SFX page under that
    # state exercises the per-source tree rows.
    $ _md, _sd = _cue_external_dirs()
    $ _cue.sfx.library.external_folders = [_sd]
    $ _cue.sfx.library.scan()
    assert eval (len(_cue.sfx.library.external_files) == 1)
    assert eval (_cue.sfx.library.external_sources[0]["label"] == "ExtSfx")
    assert eval (len(_cue.sfx.library.tree) >= 2)
    assert eval (_cue.sfx.library.tree[0]["name"] == "SFX/")
    assert eval (any(_e.get("name") == "ExtSfx/" for _e in _cue.sfx.library.tree))
    run Function(_cue.overlay.set_page, CuePage.SFX)
    assert eval (_cue.overlay.active_page == CuePage.SFX)
    $ _cue_external_cleanup()

testcase empty_state_settings_tip:
    run Jump("start")
    $ _cue_test_reset()
    # Empty per-source state renders the SFX empty-state rows, including the
    # new Settings > Data Folder tip line; a broken tip row fails this.
    $ _sfx_builtin_tree = _cue.sfx.library.builtin_tree
    $ _sfx_builtin_scan_error = _cue.sfx.library.builtin_scan_error
    $ _sfx_external_sources = _cue.sfx.library.external_sources
    $ _cue.sfx.library.builtin_tree = []
    $ _cue.sfx.library.builtin_scan_error = ""
    $ _cue.sfx.library.external_sources = []
    run Function(_cue.overlay.set_page, CuePage.SFX)
    assert eval (_cue.overlay.active_page == CuePage.SFX)
    $ _cue.sfx.library.builtin_tree = _sfx_builtin_tree
    $ _cue.sfx.library.builtin_scan_error = _sfx_builtin_scan_error
    $ _cue.sfx.library.external_sources = _sfx_external_sources
