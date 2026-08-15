# -*- coding: utf-8 -*-
# Test fixtures for renpy_cue.
#
# The mock renpy package in tests/mock_renpy/ is placed on sys.path BEFORE
# any cue_lib import so that every module-level `import renpy` resolves to
# the stub instead of the real runtime (which only exists inside a running
# Ren'Py game).

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
MOCK_RENPY_DIR = os.path.join(TESTS_DIR, "mock_renpy")

if MOCK_RENPY_DIR not in sys.path:
    sys.path.insert(0, MOCK_RENPY_DIR)


@pytest.fixture(autouse=True, scope="session")
def _silence_debug_log():
    """Keep _cue_log a no-op during tests.

    _cue_log reads CUE_DEBUG and writes {gamedir}/renpy_cue/debug.log -- in
    tests that would land in the repo root (mock gamedir is "") and clobber
    the real game's log file.

    Session-scoped and never restored: backups write their log line from a
    daemon thread after save_marker() returns, so a per-test restore would
    re-enable logging before the thread fires.  No test depends on CUE_DEBUG.
    """
    import cue_lib.constants as _constants

    _constants.CUE_DEBUG = False
    yield


@pytest.fixture
def cue_env(tmp_path):
    """Create a fresh Cue instance pointing at a temp root directory.

    The module-level _cue singleton (cue_lib.state._cue) is NOT touched;
    most unit tests only need the class, instantiated against tmp dirs.
    """
    import cue_lib.state as _state
    from cue_lib.db import CueDatabase
    from cue_lib.paths import CuePaths

    root = str(tmp_path / "cue_root")

    # Wire the minimal manager graph that unit tests exercise.  In the real
    # runtime this wiring lives in cue_z.rpy init -900; tests replicate the
    # parts they need and can override the rest per-test.
    cue = _state.Cue()
    paths = CuePaths(root, game_id="test_game")
    cue.paths = paths
    cue.db = CueDatabase(paths)
    cue.db.open()

    return cue
