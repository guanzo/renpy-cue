# -*- coding: utf-8 -*-
"""Mock of renpy.config for unit tests."""

# Game directory -- tests point this at a tmp dir as needed.
gamedir = ""

keymap = {}
screen = {}
overlay_screens = []
all_character_callbacks = []
after_load_callbacks = []
start_interact_callbacks = []

developer = False
console = False

# Monkeypatch targets (cue_z.rpy init 999 swaps these in the real runtime).
show = None
