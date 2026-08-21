# -*- coding: utf-8 -*-
# cue_lib/text.py -- CueSafeText, the displayable behind the etext screen
# statement.  A Text subclass that escapes its value so literal {/[
# render instead of being parsed as tags/interpolation.

from renpy.text.text import Text
from cue_lib.util import _cue_escape_text


class CueSafeText(Text):
    """Text subclass that escapes its value so it displays literally.
    {/[ are doubled so the parsers collapse them back to literals.
    Brackets are only doubled when substitution will run (Text substitutes
    whenever substitute is not False), so substitute False sites keep []
    literal and stay correct."""

    def __init__(self, text, **kwargs):
        brackets = kwargs.get("substitute") is not False
        Text.__init__(self, _cue_escape_text(text, brackets=brackets) or "", **kwargs)
