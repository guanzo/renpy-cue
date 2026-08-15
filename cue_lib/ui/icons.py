# cue_lib/icons.py -- CueIconManager: icon name -> PNG displayable lookup.
#
# cue_icon_btn buttons take a label that is either an icon name or plain
# text.  Names resolve to Font Awesome Free 7.3.1 icons, rasterized to
# white 32x32 PNGs by .local/icons/convert.sh (source checkout).  Shipped
# PNGs live in cue_lib/images/icons/ and are referenced by game-dir-
# relative paths built from _cue.paths.in_game_base_dir, so they resolve in any game
# the mod is symlinked into.
#
# Adding a new icon:
#   1. Add <name>-solid.png (or -regular.png) to cue_lib/images/icons/:
#      either by listing the FA icon in .local/icons/convert.sh and
#      re-running it, or by copying from the .local/icons/<style>/ stash.
#   2. Add one entry to CUE_ICON_MAP below.
#   3. Use cue_icon_btn("name", ...) in any screen.

import renpy

from cue_lib.util import _cue_log
# Tinting uses the classic im.MatrixColor operator, which ships with every
# Ren'Py 7.4+ (the `matrixcolor` Transform property only arrived in 7.5).
from renpy.display.im import MatrixColor, matrix
from renpy.display.transform import Transform

MYPY = False
if MYPY:
    from typing import Any, Dict, Optional, Tuple
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]

# PNGs are rendered at 32px (2x the 16px button) and shown at CUE_ICON_SIZE
# via zoom CUE_ICON_SIZE / CUE_ICON_SRC_SIZE, matching the size-12 text
# glyphs they replace.  displayable_for derives the zoom from the source
# size, so an explicit size re-renders the original PNG at the exact zoom --
# large icons stay crisp instead of scaling an already-zoomed smaller render.
CUE_ICON_SRC_SIZE = 32
CUE_ICON_SIZE = 12

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
    "circle-question": ("circle-question-regular.png", False),
    "circle-xmark": ("circle-xmark-solid.png", False),
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
    "plus": ("plus-solid.png", False),
    "question": ("question-solid.png", False),
    "rotate-right": ("rotate-right-solid.png", False),
    "gear": ("gear-solid.png", False),
    "layer-group": ("layer-group-solid.png", False),
    "music": ("music-solid.png", False),
    "rotate-left": ("rotate-left-solid.png", False),
    "sliders": ("sliders-solid.png", False),
    "square-plus": ("square-plus-solid.png", False),
    "square-minus": ("square-minus-solid.png", False),
    "recycle": ("recycle-solid.png", False),
    "square-check": ("square-check-regular.png", False),
    "square": ("square-regular.png", False),
    "trash-can": ("trash-can-solid.png", False),
    "triangle-exclamation": ("triangle-exclamation-solid.png", False),
    "volume": ("volume-solid.png", False),
    "volume-xmark": ("volume-xmark-solid.png", False),
}  # type: Dict[str, Tuple[str, bool]]


class CueIconManager(object):
    """Resolves icon names used by cue_icon_btn to PNG displayables.

    Unknown names return None so the screen can fall back to plain
    text (labels like "+" and "V" keep working unchanged).
    """

    def __init__(self, paths):
        # type: (CuePaths) -> None
        self._paths = paths
        self._displayables = {}  # type: Dict[Tuple[str, Optional[str], int], Any]

    def displayable_for(self, name, color=None, size=None):
        # type: (str, Optional[str], Optional[int]) -> Optional[Transform]
        """Resolve an icon name to a displayable, optionally recolored.

        The base (white) icon is cached per name; a colored variant is
        cached per (name, color) so each color is built once and reused.
        Color is any Ren'Py color: the tint maps the icon's white to it
        (black stays black), so the shape is preserved.  Tinting is done
        with im.MatrixColor, which works on every Ren'Py 7.4+.

        size is the on-screen size in pixels; None means the standard
        CUE_ICON_SIZE (12px).  The zoom is derived from the source PNG's
        resolution, so an explicit size re-renders the original at the exact
        zoom -- never an upscaled smaller render."""
        if name not in CUE_ICON_MAP:
            return None
        if size is None:
            size = CUE_ICON_SIZE
        cache_key = (name, color, size)
        cached = self._displayables.get(cache_key)
        if cached is not None:
            return cached
        _filename, _mirrored = CUE_ICON_MAP[name]
        _path = self._paths.in_game_base_dir + "/cue_lib/images/icons/" + _filename
        if not renpy.loadable(_path):
            _cue_log("CUE-ICON: missing image " + _path)
            return None
        _source = _path
        if color is not None:
            # im.MatrixColor maps white -> color (black stays black);
            # colorize's args are reversed vs ColorizeMatrix (black, white).
            _source = MatrixColor(_path, matrix.colorize("#000000", color))
        displayable = Transform(
            _source,
            zoom=size / float(CUE_ICON_SRC_SIZE),
            xzoom=-1.0 if _mirrored else 1.0,
        )
        self._displayables[cache_key] = displayable
        return displayable
