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
