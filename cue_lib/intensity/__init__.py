# -*- coding: utf-8 -*-
# cue_lib/intensity -- the intensity group subsystem.
#
# banding.py (gap-aware speed banding) and intensity.py (the group registry,
# resolution manager, and level multiplier math) live here.  The package
# re-exports the manager API so consumers keep importing
# `from cue_lib.intensity import CueIntensityManager` unchanged.
#
# Submodules are imported in dependency order (leaf-first) -- Ren'Py's
# import_all() discovers modules through the package namespace, so they must
# be loaded even when only the package name is imported.

# pyright: reportUnusedImport=false

from cue_lib.intensity import banding
from cue_lib.intensity import intensity

from cue_lib.intensity.intensity import (
    CueIntensityFlags,
    CueIntensityManager,
    CueIntensityResolution,
    _level_ramp,
)
