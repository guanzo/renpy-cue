# -*- coding: utf-8 -*-
# cue_lib -- Ren'Py mod logic migrated from .rpy to .py.
# Modules are listed in dependency order (leaf-first, hub-last).
# Importing this package loads all submodules; the store bridge in
# cue_z.rpy binds the necessary names into the Ren'Py store.

# ---------------------------------------------------------------------------
# Ren'Py exports bridge
# ---------------------------------------------------------------------------
# In .rpy init blocks, Ren'Py's exec context makes every renpy.exports name
# available as a bare renpy.xxx() call.  Regular Python imports don't get
# that treatment -- renpy.image, renpy.Render, renpy.get_screen, etc. raise
# AttributeError.  We fix this by copying any missing names from
# renpy.exports onto the renpy module.
import renpy
import renpy.exports as _renpy_exports

for _name in dir(_renpy_exports):
    if _name.startswith("_"):
        continue
    if not hasattr(renpy, _name):
        setattr(renpy, _name, getattr(_renpy_exports, _name))

# ---------------------------------------------------------------------------
# Load submodules in dependency order
# ---------------------------------------------------------------------------

from cue_lib import state
from cue_lib import util
from cue_lib import ffmpeg
from cue_lib import worker
from cue_lib import undo
from cue_lib import volume
from cue_lib import file_tree
from cue_lib import video
from cue_lib import beat
from cue_lib import markers
from cue_lib import trigger
from cue_lib import video_editor
from cue_lib import speed
from cue_lib import runtime
from cue_lib import ui_logic
from cue_lib import displayables
from cue_lib import popper
