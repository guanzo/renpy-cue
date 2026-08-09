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
# AttributeError.  We fix this by giving the renpy module a __getattr__
# that falls back to renpy.exports, exactly mirroring .rpy behavior.
import renpy
import renpy.exports as _renpy_exports

class _RenPyModule(type(renpy)):
    def __getattr__(cls, name):
        # Module.__getattr__ is only invoked when normal lookup fails.
        # Fall back to renpy.exports -- this is what Ren'Py's exec context
        # effectively does in .rpy init blocks.
        try:
            return getattr(_renpy_exports, name)
        except AttributeError:
            raise AttributeError(
                "module 'renpy' has no attribute {!r}".format(name))

renpy.__class__ = _RenPyModule  # pyright: ignore[reportAttributeAccessIssue]
# NOTE: _renpy_exports and _RenPyModule must stay alive -- __getattr__
# reads _renpy_exports from this module's globals at call time.

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
