# cue_lib/icons.py -- CueIconManager: icon name -> PNG displayable lookup.
#
# cue_icon_btn buttons take a label that is either an icon name or plain
# text.  Names resolve to Font Awesome Free 7.3.1 icons, rasterized to
# white 32x32 PNGs by .local/icons/convert.sh (source checkout).  Shipped
# PNGs live in cue_lib/images/icons/ and are referenced by game-dir-
# relative paths built from _cue.base_dir, so they resolve in any game
# the mod is symlinked into.
#
# Adding a new icon:
#   1. Add <name>-solid.png (or -regular.png) to cue_lib/images/icons/:
#      either by listing the FA icon in .local/icons/convert.sh and
#      re-running it, or by copying from the .local/icons/<style>/ stash.
#   2. Add one entry to CUE_ICON_MAP below.
#   3. Use cue_icon_btn("name", ...) in any screen.

import renpy

from cue_lib.state import _cue
from cue_lib.util import _cue_log
from renpy.display.transform import Transform

MYPY = False
if MYPY:
    from typing import Any, Dict, Optional, Tuple

# PNGs are rendered at 32px (2x the 16px button) and shown at 12px via
# zoom 0.375, matching the size-12 text glyphs they replace.
CUE_ICON_ZOOM = 0.375

# name -> (filename, mirrored).  Mirrored entries flip the source
# horizontally ("redo" is the mirrored "undo" hook arrow).
CUE_ICON_MAP = {
    "xmark": ("xmark-solid.png", False),
    "chevron-down": ("chevron-down-solid.png", False),
    "chevron-left": ("chevron-left-solid.png", False),
    "chevron-right": ("chevron-right-solid.png", False),
    "chevron-up": ("chevron-up-solid.png", False),
    "circle": ("circle-solid.png", False),
    "circle-outline": ("circle-regular.png", False),
    "floppy-disk": ("floppy-disk-solid.png", False),
    "clipboard": ("clipboard-solid.png", False),
    "clone": ("clone-regular.png", False),
    "copy": ("copy-regular.png", False),
    "file": ("file-solid.png", False),
    "folder-open": ("folder-open-solid.png", False),
    "undo": ("reply-solid.png", False),
    "redo": ("reply-solid.png", True),
    "paste": ("paste-regular.png", False),
    "pause": ("pause-solid.png", False),
    "play": ("play-solid.png", False),
    "question": ("question-solid.png", False),
    "rotate-right": ("rotate-right-solid.png", False),
    "gear": ("gear-solid.png", False),
    "rotate-left": ("rotate-left-solid.png", False),
    "square-plus": ("square-plus-solid.png", False),
    "square-minus": ("square-minus-solid.png", False),
    "recycle": ("recycle-solid.png", False),
    "square-check": ("square-check-regular.png", False),
    "square": ("square-regular.png", False),
}  # type: Dict[str, Tuple[str, bool]]


class CueIconManager(object):
    """Resolves icon names used by cue_icon_btn to PNG displayables.

    Unknown names return None so the screen can fall back to plain
    text (labels like "+" and "V" keep working unchanged).
    """

    def __init__(self):
        self._displayables = {}  # type: Dict[str, Any]

    def displayable_for(self, name):
        # type: (str) -> Optional[Transform]
        if name not in CUE_ICON_MAP:
            return None
        cached = self._displayables.get(name)
        if cached is not None:
            return cached
        _filename, _mirrored = CUE_ICON_MAP[name]
        _path = _cue.base_dir + "/cue_lib/images/icons/" + _filename
        if not renpy.loadable(_path):
            _cue_log("CUE-ICON: missing image " + _path)
            return None
        displayable = Transform(
            _path,
            zoom=CUE_ICON_ZOOM,
            xzoom=-1.0 if _mirrored else 1.0,
        )
        self._displayables[name] = displayable
        return displayable
