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
