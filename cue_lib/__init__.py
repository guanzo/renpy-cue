# -*- coding: utf-8 -*-
# cue_lib -- Ren'Py mod logic migrated from .rpy to .py.
# Modules are listed in dependency order (leaf-first, hub-last).
# Importing this package loads all submodules; the store bridge in
# cue_z.rpy binds the necessary names into the Ren'Py store.

# pyright: reportUnusedImport=false
# Every import below is a side-effect import -- Ren'Py's import_all()
# discovers modules through the package namespace, so they must be
# listed here even though no symbol is referenced directly.

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
from cue_lib import logger
from cue_lib import util
from cue_lib import backup
from cue_lib import db
from cue_lib.video import auto_speed, ffmpeg, repeater, speed, video, video_edit_queue, video_editor
from cue_lib import undo
from cue_lib import volume
from cue_lib.audio import audio_tree, music_tree, music, sfx_manager, user_music, game_music
from cue_lib import marker_context
from cue_lib import copy_paste
from cue_lib import markers
from cue_lib import trigger
from cue_lib import runtime
from cue_lib.ui import dialogs, displayables, icons, popper
