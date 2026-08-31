# Support for the trigger-firing testcases.
#
# The test DSL's `$ renpy.show(...)` calls renpy.exports.show, which bypasses
# renpy.config.show -- fine for i_/d_/l_/v_ (they read the scene list), but the
# screenshake "at" path only runs through a real `show` statement, the "with"
# path only through a real `with` statement, and a say only sets
# store._last_say_what through a real say statement.

# Two distinct stills so a testcase can alternate context: re-showing the SAME
# image does not re-fire, a DIFFERENT one does.
image cueimg_a = "renpy_cue/cue_lib/assets/images/icons/gear-solid.png"
image cueimg_b = "renpy_cue/cue_lib/assets/images/icons/music-solid.png"

# The test game ships no screens.rpy, so without a `screen say` the engine's
# Character falls back to the legacy window display -- which never registers a
# "say" screen, so _cue_refresh_context's `renpy.get_screen("say") is None`
# guard clears current_dialogue before the d_ trigger can fire.  Real games
# always define this screen; the harness must too.
screen say(who, what):
    window:
        id "window"
        if who is not None:
            text who id "who"
        text what id "what"

define cuespk = Character("Speaker")

label cue_say_fire:
    show cueimg_a
    cuespk "Hello"
    return

label cue_shake_at:
    show cueimg_a at vpunch
    # Keep the scene alive until the next interaction's refresh consumes
    # _shake_just_happened.  Returning immediately would drop back to start's
    # black context, and the shake would fire with the wrong file key.
    pause 1.0
    return

label cue_shake_with:
    with vpunch
    return
