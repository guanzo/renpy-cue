# Runs after the mod's init 999 (which hydrates seamless_transition from
# persistent): video_seamless_transition_preserves_position leaves it on via
# persistent, so a later run's video_sfx_edit_locked_off_base_speed would
# start with set_speed in queue mode -- it needs the 1.5x variant to exist and
# never writes the pref, so the assertion sees the base speed.
init 1000 python:
    # Reset trigger/context state so each testcase starts clean.  The modern
    # suite runs every testcase in one process, so last_played, loop_states,
    # played_video_keys, current_file, and the dialogue fields all leak
    # between testcases without this.
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
        _cue._shake_just_happened = False
        _cue.vid_manager.last_elapsed = 0.0
        # The test game's start label never clears the scene, so a prior
        # testcase's displayable stays on the master layer.  Re-showing a
        # different image then puts the new one BELOW the stale top entry and
        # fire_context never sees the intended change.  Clear the layer so each
        # show is a genuine context change (mirrors a real game's scene cut).
        renpy.scene()

    # The video_seamless testcase re-enables it itself.
    _cue.speed_resolver.seamless_transition = False

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

testcase sfx_recently_used:
    run Jump("start")
    # Wired and empty on a fresh game (harness wipes saves/persistent).
    assert eval (_cue.sfx_manager._recent is not None)
    assert eval (_cue.sfx_manager._recent.entries() == [])
    assert eval (not _cue.sfx_manager._recent.expanded)
    # A file send records the resolved path and expands the list.
    run Function(_cue.markers.image.send_file, 0)
    assert eval (_cue.sfx_manager._recent.entries() == [{"type": "file", "ref": _cue.sfx_manager.files[0]}])
    assert eval (_cue.sfx_manager._recent.expanded)
    # A folder send normalizes its ref and bumps to front.
    run Function(_cue.markers.image.send_folder, "Sub/")
    assert eval (_cue.sfx_manager._recent.entries()[0] == {"type": "folder", "ref": "Sub/"})
    assert eval (len(_cue.sfx_manager._recent.entries()) == 2)
    # A preset send records; repeating it bumps without duplicating.
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.markers.image.send_preset, "Test Preset")
    assert eval (len(_cue.sfx_manager._recent.entries()) == 3)
    run Function(_cue.markers.image.send_preset, "Test Preset")
    assert eval (len(_cue.sfx_manager._recent.entries()) == 3)
    assert eval (_cue.sfx_manager._recent.entries()[0] == {"type": "preset", "ref": "Test Preset"})
    # Render the SFX page so the Recently Used row compiles and displays.
    run Function(_cue_set_page, CuePage.SFX)

testcase music_recently_used:
    run Jump("start")
    # Wired and empty on a fresh game (harness wipes saves/persistent).
    assert eval (_cue.music._recent is not None)
    assert eval (_cue.music._recent.entries() == [])
    assert eval (not _cue.music._recent.expanded)
    # Adding a My Music song records its u:-tagged ref and expands the list.
    run Function(_cue.music.add_user_song_to_trigger, "music/song_001.ogg")
    assert eval (_cue.music._recent.entries() == [{"type": "file", "ref": "u:music/song_001.ogg"}])
    assert eval (_cue.music._recent.expanded)
    # A folder add normalizes its ref and bumps to front.
    run Function(_cue.music.add_user_folder_to_trigger, "music/")
    assert eval (_cue.music._recent.entries()[0] == {"type": "folder", "ref": "u:music/"})
    assert eval (len(_cue.music._recent.entries()) == 2)
    # Repeating an add bumps without duplicating.
    run Function(_cue.music.add_user_folder_to_trigger, "music/")
    assert eval (len(_cue.music._recent.entries()) == 2)
    assert eval (_cue.music._recent.entries()[0] == {"type": "folder", "ref": "u:music/"})
    # Render the Music page so the Recently Used row compiles and displays.
    run Function(_cue_set_page, CuePage.MUSIC)

testcase sfx_target_context:
    run Jump("start")
    $ _cue_test_reset()
    # Hotkeys select the target context on the SFX page (bar + [+] rows compile).
    run Function(_cue_set_page, CuePage.SFX)
    keysym "K_3"
    assert eval (_cue.markers.target_context == CueContextType.DIALOGUE)
    keysym "K_4"
    assert eval (_cue.markers.target_context == CueContextType.LOOP)
    keysym "K_1"
    assert eval (_cue.markers.target_context == CueContextType.VIDEO)
    # Compile the preset + video preset + recently-used list rows ([+] rows).
    run Function(_cue.markers.create_preset, "Test Preset", {"files": ["sfx_001.ogg"], "volume": 1.0})
    run Function(_cue.sfx_manager.toggle_presets_expand)
    run Function(_cue.sfx_manager.toggle_video_presets_expand)
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
    run Function(_cue.music.create_preset, "Test Music Preset", ["u:music/song_001.ogg", "g:bgm/song_002.ogg"])
    assert eval ("Test Music Preset" in _cue.music.list_presets())
    assert eval (_cue.music.get_preset("Test Music Preset")["files"] == ["u:music/song_001.ogg", "g:bgm/song_002.ogg"])
    # Display rows resolve each stored ref to a My/Game Music path.
    assert eval (_cue.music.preset_display_files(_cue.music.get_preset("Test Music Preset")) == ["My Music/song_001.ogg", "Game Music/bgm/song_002.ogg"])
    # Expand + render the Music page so the preset rows compile and display.
    run Function(_cue.music.toggle_presets_expand)
    assert eval (_cue.music.presets_expanded)
    run Function(_cue.music.toggle_preset_expand, "Test Music Preset")
    assert eval (_cue.music.expanded_presets.get("Test Music Preset", False))
    run Function(_cue_set_page, CuePage.MUSIC)
    # Deleting removes it from memory and disk.
    run Function(_cue.music.delete_preset, "Test Music Preset")
    assert eval ("Test Music Preset" not in _cue.music.list_presets())

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
    $ import os as _os
    assert eval (_base is not None)
    assert eval (_os.path.exists(_variant))
    assert eval (1.5 in _cue.speed_resolver.get_available_speeds(_base))

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
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ renpy.show("cueimg_a")
    pause 1.0
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("i_cueimg_a", None)

testcase dlg_trigger_fires_on_say:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("d_cueimg_a__Hello")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    run Jump("cue_say_fire")
    pause 1.0
    assert eval (_cue.current_file == "cueimg_a")
    assert eval (_cue.current_dialogue == "Hello")
    assert eval (_cue.markers.get("d_cueimg_a__Hello") is not None)
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("d_cueimg_a__Hello", None)

testcase loop_trigger_fires_on_cycle:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("l_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "frequency": CueLoopFrequency.FASTEST}]
    $ renpy.show("cueimg_a")
    pause 0.1 until eval (len(_cue.trigger.last_played) >= 1) timeout 5.0
    assert eval (len(_cue.trigger.last_played) >= 1)
    $ _cue.markers.pop("l_cueimg_a", None)

testcase video_marker_fires_at_ts:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("v_cuevid")["pools"] = [{"time": 0.0, "files": ["sfx_001.ogg"], "volume": 1.0}]
    $ renpy.show("cuevid")
    pause 1.0
    assert eval (_cue.top_layer_type == "movie")
    assert eval (_cue.vid_manager.get_duration() > 0)
    # played_video_keys is wiped every tick while last_elapsed == 0, so a stuck
    # audio clock would hang the poll below. Fail here instead.
    assert eval (_cue.vid_manager.get_elapsed() > 0.0)
    pause 0.1 until eval (len(_cue.trigger.played_video_keys) >= 1) timeout 10.0
    assert eval (len(_cue.trigger.played_video_keys) == 1)
    $ _cue.markers.pop("v_cuevid", None)

testcase img_oneshot_dedup_no_refire:
    run Jump("start")
    $ _cue_test_reset()
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
    $ _cue.markers._get_or_create_entry("i_cueimg_b")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0}]
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
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "trigger_on_shake": True}]
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
    $ _cue.markers._get_or_create_entry("i_cueimg_a")["pools"] = [{"files": ["sfx_001.ogg", "sfx_002.ogg"], "volume": 1.0, "trigger_on_shake": True}]
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
