init python:
    if renpy.version_tuple < (7, 4):
        # 7.2.x's test driver (renpy.test.testexecution.execute) only advances
        # while the screen redraws, and a static headless scene never does -- so
        # `renpy test` stalls before the first testcase. Force a per-frame
        # redraw so the driver runs; 7.4+ schedules its own redraws.
        config.needs_redraw_callbacks.append(lambda: True)

label start:
    "cue test harness"
    return
