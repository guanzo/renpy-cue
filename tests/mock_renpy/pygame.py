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

KMOD_ALT = 256
KMOD_CTRL = 64
KMOD_META = 1024
KMOD_SHIFT = 1
