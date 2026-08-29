# -*- coding: utf-8 -*-
"""Mock of renpy.config for unit tests."""

# Game directory -- tests point this at a tmp dir as needed.
gamedir = ""

# Save directory -- real Ren'Py always defines this (used by the shared-dir
# probe in cue_lib.settings.CueSettings.confirm_shared_dir).
save_directory = "save"

# Viewport size -- CueTooltip / CuePopper clamp against these.  Run at the
# 1920 UI reference width so _cue_scale_ui() is identity in unit tests.
screen_width = 1920
screen_height = 1080

keymap = {}
screen = {}
overlay_screens = []
all_character_callbacks = []
after_load_callbacks = []
start_interact_callbacks = []

developer = False
console = False

# Last-resort error handler (set by cue_lib.logger._cue_install_exception_handler).
exception_handler = None

# Monkeypatch targets (cue_z.rpy init 999 swaps these in the real runtime).
show = None
