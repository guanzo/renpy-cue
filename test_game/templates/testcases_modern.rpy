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
