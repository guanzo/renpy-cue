# Minimal stubs for the pygame constants our code uses.
# Ren'Py bundles pygame internally; Pylance can't find it.

from typing import Any

# Event types
MOUSEMOTION: int
MOUSEBUTTONDOWN: int
MOUSEBUTTONUP: int
KEYDOWN: int
KEYUP: int

# Key constants
class key:
    @staticmethod
    def get_mods() -> int: ...

KMOD_LALT: int
KMOD_RALT: int
KMOD_LSHIFT: int
KMOD_RSHIFT: int
KMOD_LCTRL: int
KMOD_RCTRL: int
