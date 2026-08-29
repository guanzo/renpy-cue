# -*- coding: utf-8 -*-
# Tests for CueOverlay (cue_lib/ui/overlay.py) -- overlay lifecycle and
# section-frame toggle persistence.
#
# CueOverlay.__init__ touches no managers, so tests drive a fresh instance.
# toggle_section writes to persistent._cue, so every test resets it.

import pytest

from renpy.store import persistent

from cue_lib.constants import CUE_PERSIST_COLLAPSED_SECTIONS
from cue_lib.ui.overlay import CueOverlay


@pytest.fixture(autouse=True)
def _clean_persistent(monkeypatch):
    monkeypatch.setattr(persistent, "_cue", {})


def _overlay():
    return CueOverlay()


# ---------------------------------------------------------------------------
# initial state
# ---------------------------------------------------------------------------


def test_overlay_starts_hidden_on_sfx_page():
    ov = _overlay()
    assert ov.is_visible is False
    assert ov.active_page == 0  # CuePage.SFX
    assert ov.collapsed_sections == {}


# ---------------------------------------------------------------------------
# section-toggle persistence
# ---------------------------------------------------------------------------


def test_toggle_persists_section_state():
    ov = _overlay()
    ov.toggle_section("Video VFX")
    assert persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] == {"Video VFX": True}
    ov.toggle_section("Video VFX")
    assert persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] == {"Video VFX": False}


def test_toggle_multiple_sections_persisted_together():
    ov = _overlay()
    ov.toggle_section("Music Library")
    ov.toggle_section("Video VFX")
    assert persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] == {"Music Library": True, "Video VFX": True}


def test_load_restores_section_state():
    persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] = {"Video VFX": True, "Music Library": False}
    ov = _overlay()
    ov._load_collapsed_sections()
    assert ov.collapsed_sections == {"Video VFX": True, "Music Library": False}


def test_load_handles_none_persistent(monkeypatch):
    monkeypatch.setattr(persistent, "_cue", None)
    ov = _overlay()
    ov._load_collapsed_sections()
    assert ov.collapsed_sections == {}


def test_load_ignores_non_dict_blob():
    persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] = "garbage"
    ov = _overlay()
    ov._load_collapsed_sections()
    assert ov.collapsed_sections == {}


def test_load_absent_key_leaves_empty():
    ov = _overlay()
    ov._load_collapsed_sections()
    assert ov.collapsed_sections == {}


def test_load_coerces_values_to_bool():
    persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] = {"Video VFX": 1}
    ov = _overlay()
    ov._load_collapsed_sections()
    assert ov.collapsed_sections == {"Video VFX": True}
