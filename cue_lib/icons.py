# cue_lib/icons.py -- CueIconManager: unicode glyph -> PNG icon lookup.
#
# cue_icon_btn buttons use unicode glyphs as labels, but the UI font
# (DejaVu Sans) has no emoji coverage, so many glyphs render as tofu.
# This manager maps each glyph to a Font Awesome Free 7.3.1 icon,
# rasterized to a white 32x32 PNG by .local/icons/convert.sh (source
# checkout).  Shipped PNGs live in cue_lib/images/icons/ and are
# referenced by game-dir-relative paths built from _cue.base_dir, so
# they resolve in any game the mod is symlinked into.
#
# This file must stay ASCII-only (Python 2 constraint), so glyph keys
# are \u escapes.  They compare equal to the literal glyphs parsed from
# .rpy files on both narrow and wide Python 2 builds.
#
# Glyph -> FA icon (solid style unless marked):
#   \u2715       multiplication x       -> xmark           (close/delete)
#   \u25b6       right-pointing tri     -> play
#   \u25b8       right small triangle   -> caret-right     (collapsed)
#   \u25be       down small triangle    -> caret-down      (expanded)
#   \U0001f4be   floppy disk            -> floppy-disk     (save)
#   \U0001f4cb   clipboard              -> clipboard       (copy context)
#   \U0001f4c4   page facing up         -> file            (paste context)
#   \U0001f4c2   open folder            -> folder-open     (restore)
#   \u21a9       left arrow with hook   -> reply           (undo)
#   \u21aa       right arrow with hook  -> reply mirrored  (redo)
#   \u23f8       double vertical bar    -> pause           (pause game)
#   \u27f3       clockwise gap arrow    -> rotate-right    (refresh)
#   \u2699       gear                   -> gear            (settings)
#   \u21ba       anticlockwise arrow    -> rotate-left     (reset keybind)
#   \u229e       squared plus           -> square-plus     (overlay mode on)
#   \u229f       squared minus          -> square-minus    (overlay mode off)
#   \u267b       recycling symbol       -> recycle         (duplicate pool)
#   \u2611       ballot box w/ check    -> square-check regular (enabled)
#   \u2610       ballot box             -> square regular       (disabled)

import renpy

from cue_lib.state import _cue
from cue_lib.util import _cue_log
from renpy.display.transform import Transform

MYPY = False
if MYPY:
    from typing import Any, Dict, Optional, Tuple

# PNGs are rendered at 32px (2x the 16px button) and shown at 14px via
# zoom 0.4375, matching the size-12 text glyphs they replace.
CUE_ICON_ZOOM = 0.4375

# glyph -> (filename, mirrored).  Mirrored entries flip the source
# horizontally (the redo hook arrow is the mirrored undo arrow).
CUE_ICON_MAP = {
    u"\u2715": ("xmark-solid.png", False),          # X
    u"\u25b6": ("play-solid.png", False),           # solid right triangle
    u"\u25b8": ("caret-right-solid.png", False),    # small right triangle
    u"\u25be": ("caret-down-solid.png", False),     # small down triangle
    u"\U0001f4be": ("floppy-disk-solid.png", False),
    u"\U0001f4cb": ("clipboard-solid.png", False),
    u"\U0001f4c4": ("file-solid.png", False),
    u"\U0001f4c2": ("folder-open-solid.png", False),
    u"\u21a9": ("reply-solid.png", False),          # undo hook arrow
    u"\u21aa": ("reply-solid.png", True),           # redo (mirrored)
    u"\u23f8": ("pause-solid.png", False),
    u"\u27f3": ("rotate-right-solid.png", False),
    u"\u2699": ("gear-solid.png", False),
    u"\u21ba": ("rotate-left-solid.png", False),
    u"\u229e": ("square-plus-solid.png", False),
    u"\u229f": ("square-minus-solid.png", False),
    u"\u267b": ("recycle-solid.png", False),
    u"\u2611": ("square-check-regular.png", False),
    u"\u2610": ("square-regular.png", False),
}  # type: Dict[str, Tuple[str, bool]]


class CueIconManager(object):
    """Resolves the glyphs used by cue_icon_btn to PNG displayables.

    Unmapped glyphs return None so the screen can fall back to plain
    text (ASCII labels like "+" and "-" keep working unchanged).
    """

    def __init__(self):
        self._displayables = {}  # type: Dict[str, Any]

    def displayable_for(self, glyph):
        # type: (str) -> Optional[Transform]
        if glyph not in CUE_ICON_MAP:
            return None
        cached = self._displayables.get(glyph)
        if cached is not None:
            return cached
        _filename, _mirrored = CUE_ICON_MAP[glyph]
        _path = _cue.base_dir + "/cue_lib/images/icons/" + _filename
        if not renpy.loadable(_path):
            _cue_log("CUE-ICON: missing image " + _path)
            return None
        displayable = Transform(
            _path,
            zoom=CUE_ICON_ZOOM,
            xzoom=-1.0 if _mirrored else 1.0,
        )
        self._displayables[glyph] = displayable
        return displayable
