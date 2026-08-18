# -*- coding: utf-8 -*-
"""Mock of the Ren'Py top-level module for unit tests.

Only needs to satisfy import-time requirements of cue_lib modules; the
functions in renpy.exports are copied onto this module by
cue_lib/__init__.py's bridge loop (same as in the real runtime).
"""

# pyright: reportUnusedImport=false
# Side-effect imports: attribute access like renpy.config.gamedir and
# renpy.audio.music.get_pos() resolves through these bindings, mirroring
# the real runtime's package structure.
from . import config
from . import python
from . import store
from . import exports
from . import atl
from . import audio
from . import display
from . import text
from . import game
from . import curry
from . import focus
