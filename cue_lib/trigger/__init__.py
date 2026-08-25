# -*- coding: utf-8 -*-
# cue_lib/trigger -- the SFX trigger subsystem.
#
# The CueTriggerEngine split into a thin coordinator plus per-domain classes:
# context.py (i_/d_/shake one-shots), loop.py (l_ key frequency-cycle state
# machine), video.py (v_ key marker-timed fires), exclusive.py (the shared
# cut-in/gate registry), and trigger_debug.py (anomaly detection).  The
# package re-exports the engine API so consumers keep importing
# `from cue_lib.trigger import CueTriggerEngine` unchanged.
#
# Submodules are imported in dependency order (leaf-first) -- Ren'Py's
# import_all() discovers modules through the package namespace, so they must
# be loaded even when only the package name is imported.

# pyright: reportUnusedImport=false

import random as _random
import time as _time
import renpy.audio.music as _music

from cue_lib.state import _cue

from cue_lib.trigger import helpers
from cue_lib.trigger import exclusive
from cue_lib.trigger import trigger_debug
from cue_lib.trigger import context
from cue_lib.trigger import loop
from cue_lib.trigger import video
from cue_lib.trigger import engine

from cue_lib.trigger.engine import CueTriggerEngine
from cue_lib.trigger.exclusive import CUE_EXCL_KIND_LOOP, CUE_EXCL_KIND_ONESHOT, CUE_EXCL_KIND_VIDEO
from cue_lib.trigger.helpers import _cue_effective_delay, _cue_loop_still_playing
