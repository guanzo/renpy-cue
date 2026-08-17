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

testcase confirm_dialog_escape:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    run Function(_cue.confirm_dialog.show, "Really?", _cue_hide_overlay)
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
    $ _ok = len(_cue.sfx_manager.files) >= 2 and _cue.sfx_manager.scan_error == ""
    $ _ok = _ok and "sfx_001.ogg" in _cue.sfx_manager.files
    $ if not _ok: renpy.quit(status=1)
    $ renpy.quit()

testcase sfx_file_tree_expand:
    $ _cue.is_overlay_visible = True
    run Jump("start")
    pause 2.0
    run Function(_cue.sfx_manager.toggle_folder, "Sub/")
    $ if not _cue.sfx_manager.expanded_folders.get("Sub/", False): renpy.quit(status=1)
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
    $ _ok = _ok and 0 <= _cue.markers.video.target_pool < len(_cue.markers.video.get_markers())
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
