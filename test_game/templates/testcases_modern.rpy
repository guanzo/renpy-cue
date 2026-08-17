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
    $ import os as _os
    assert eval (_base is not None)
    assert eval (_os.path.exists(_variant))
    assert eval (1.5 in _cue.speed_resolver.get_available_speeds(_base))

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
