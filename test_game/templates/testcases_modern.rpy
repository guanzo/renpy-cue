testsuite global:
    before testcase:
        $ _test.timeout = 2.0
        $ _test.transition_timeout = 0.05
        $ _cue.is_overlay_visible = True

    teardown:
        exit

testcase overlay_shows_on_start:
    run Jump("start")
    assert screen "cue_overlay" layer "cue_layer"

testcase page_nav:
    run Jump("start")
    run Function(_cue_set_page, CuePage.MUSIC)
    assert eval (_cue.overlay_active_page == CuePage.MUSIC)

testcase confirm_dialog_escape:
    run Jump("start")
    run Function(_cue.confirm_dialog.show, "Really?", _cue_hide_overlay)
    assert screen "cue_confirm_dialog" layer "cue_layer"
    keysym "K_ESCAPE"
    assert not screen "cue_confirm_dialog" layer "cue_layer"

testcase sfx_library_rows:
    run Jump("start")
    assert eval (len(_cue.sfx_manager.files) >= 2)
    assert eval (_cue.sfx_manager.scan_error == "")
    assert eval ("sfx_001.ogg" in _cue.sfx_manager.files)

testcase sfx_file_tree_expand:
    run Jump("start")
    run Function(_cue.sfx_manager.toggle_folder, "Sub/")
    assert eval (_cue.sfx_manager.expanded_folders.get("Sub/", False))

testcase music_my_music_rows:
    run Jump("start")
    assert eval (len(_cue.music.user_music.files) >= 1)
    assert eval (_cue.music.user_music.files[0].startswith("music/"))

testcase audio_presets_list:
    run Jump("start")
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    assert eval ("Test Preset" in _cue.markers.list_presets())
    assert eval (_cue.markers.get_preset("Test Preset")["files"] == ["sfx_001.ogg"])

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
    assert eval (0 <= _cue.markers.video.target_pool < len(_cue.markers.video.get_markers()))

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
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
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
    assert eval (_cue.markers.video.target_pool in _sel)

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
    $ _vol_val.changed(0.4)
    # The slider path end-to-end: DictValue writes the active dict, the
    # multi_setter fans out to the other selected pool, and the marker save
    # is queued (deferred), not written immediately.
    assert eval (_vpools[0]["volume"] == 0.4)
    assert eval (_vpools[1]["volume"] == 0.4)
    assert eval (_vid_key in _cue.volume._pending_saves)

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

testcase click_create_tab_opens_editor:
    run Jump("start")
    $ _test.timeout = 5.0
    # page_nav leaves overlay_active_page on MUSIC, and store state persists
    # between testcases in the same process. _cue_set_page restarts the
    # interaction, so the sidebar actually rebuilds with the SFX page.
    run Function(_cue_set_page, CuePage.SFX)
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
