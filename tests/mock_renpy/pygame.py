# -*- coding: utf-8 -*-
"""Mock of pygame for unit tests.

Only cue_lib/ui/displayables.py imports pygame; it uses pygame.constants
key names, pygame.KEYDOWN, and pygame.KMOD_* modifier flags.
"""


class _Constants(object):
    # A few common key names; the real map is built at runtime from
    # pygame.constants dir().  Tests can add more via setattr.
    K_UP = 273
    K_DOWN = 274
    K_LEFT = 276
    K_RIGHT = 275
    K_a = 97
    K_z = 122
    K_RETURN = 13
    K_ESCAPE = 27


constants = _Constants()

KEYDOWN = 2
MOUSEMOTION = 4
MOUSEBUTTONDOWN = 5
MOUSEBUTTONUP = 6

KMOD_ALT = 256
KMOD_CTRL = 64
KMOD_META = 1024
KMOD_SHIFT = 1
KMOD_LALT = 256
KMOD_RALT = 512
KMOD_LSHIFT = 1
KMOD_RSHIFT = 2


class _Key(object):
    """Stub of pygame.key -- the timeline reads modifier state via
    get_mods(); tests that need a modifier raise the flags directly."""

    def get_mods(self):
        return 0


key = _Key()
