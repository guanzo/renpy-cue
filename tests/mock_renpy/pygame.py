# -*- coding: utf-8 -*-
"""Mock of pygame for unit tests.

Only cue_lib/ui/displayables.py imports pygame; it uses pygame.constants
key names, pygame.KEYDOWN, pygame.MOUSEMOTION/... button events, and the
pygame.KMOD_* modifier flags.
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
    K_F5 = 116
    K_1 = 49
    K_SPACE = 32
    K_KP_0 = 256
    # Bare modifiers -- filtered out of the keysym map.
    K_LSHIFT = 1073742049
    K_RSHIFT = 1073742051
    K_LCTRL = 1073742048
    K_RCTRL = 1073742052


constants = _Constants()

# Real pygame exposes key names at module level too (pygame.K_F5).
globals().update({n: getattr(constants, n) for n in dir(constants)})

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
KMOD_LCTRL = 64
KMOD_RCTRL = 128
KMOD_LMETA = 1024
KMOD_RMETA = 2048


class _Key(object):
    """Stub of pygame.key -- the timeline reads modifier state via
    get_mods(); tests that need a modifier raise the flags directly."""

    def get_mods(self):
        return 0


key = _Key()
