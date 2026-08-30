# -*- coding: utf-8 -*-
# Tests for the generic CueSelect manager (cue_lib/ui/components/select).
# The mock renpy.config.screen_width is 1920, so _cue_scale_ui is identity
# and all geometry numbers below are raw unscaled values.

import pytest

from cue_lib.state import _cue
from cue_lib.ui.components.select.select import (
    CUE_SELECT_FRAME_PAD,
    CUE_SELECT_MAX_H,
    CUE_SELECT_OPTION_GAP,
    CUE_SELECT_OPTION_H,
    CueSelect,
)
from cue_lib.ui.overlay import CueOverlay


@pytest.fixture(autouse=True)
def _wire_overlay(monkeypatch):
    """Give _cue a real overlay so CueSelect's open/close state lives there."""
    monkeypatch.setattr(_cue, "overlay", CueOverlay())


class _FakeSelect(CueSelect):
    def __init__(self, opts):
        CueSelect.__init__(self)
        self._opts = opts

    def options(self):
        return list(self._opts)


def _reset_cue(monkeypatch):
    monkeypatch.setattr(_cue.overlay, "active_dropdown", None)
    monkeypatch.setattr(_cue.overlay, "active_input_rect", None)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def test_toggle_adds_removes():
    s = _FakeSelect([])

    s.toggle("a")
    assert s.selected_keys() == ["a"]
    s.toggle("a")
    assert s.selected_keys() == []
    assert not s.is_selected("a")


def test_select_toggles_and_closes(monkeypatch):
    _reset_cue(monkeypatch)
    s = _FakeSelect([])
    _cue.overlay.active_input_rect = (0, 0, 300, 20)
    s.open()

    assert s.is_open()
    s.select("a")

    assert s.is_selected("a")
    assert not s.is_open()
    assert _cue.overlay.active_dropdown is None


def test_clear():
    s = _FakeSelect([])
    s.toggle("a")
    s.toggle("b")

    s.clear()

    assert s.selected_keys() == []


# ---------------------------------------------------------------------------
# open / close
# ---------------------------------------------------------------------------


def test_open_pins_int_trigger_rect(monkeypatch):
    _reset_cue(monkeypatch)
    s = _FakeSelect([])
    # Focus rects arrive as floats; the anchor must be ints or screen
    # xpos/ypos/xsize treat them as parent fractions.
    _cue.overlay.active_input_rect = (12.0, 34.0, 300.0, 20.0)

    s.open()

    assert s.is_open()
    assert _cue.overlay.active_dropdown is s
    assert s.trigger_rect() == (12, 34, 300, 20)


def test_toggle_open_toggles(monkeypatch):
    _reset_cue(monkeypatch)
    s = _FakeSelect([])
    assert not s.is_open()

    s.toggle_open()
    assert s.is_open()

    s.toggle_open()
    assert not s.is_open()
    assert _cue.overlay.active_dropdown is None


# ---------------------------------------------------------------------------
# deterministic geometry (fixed row height -> exact dropdown height)
# ---------------------------------------------------------------------------


def test_content_h_scales_with_options():
    assert _FakeSelect([])._content_h() == 0
    assert _FakeSelect(["a", "b"])._content_h() == 2 * CUE_SELECT_OPTION_H + 1 * CUE_SELECT_OPTION_GAP


def test_content_h_caps_at_max():
    n = CUE_SELECT_MAX_H // CUE_SELECT_OPTION_H + 10  # well past the cap
    assert _FakeSelect(list(range(n)))._content_h() == CUE_SELECT_MAX_H


def test_frame_h_includes_padding():
    s = _FakeSelect(["a", "b"])
    assert s.viewport_h() == 2 * CUE_SELECT_OPTION_H + 1 * CUE_SELECT_OPTION_GAP
    assert s.frame_h() == s.viewport_h() + CUE_SELECT_FRAME_PAD


def test_rect_and_is_inside_are_pure_rect(monkeypatch):
    _reset_cue(monkeypatch)
    s = _FakeSelect(["a", "b"])
    _cue.overlay.active_input_rect = (0.0, 100.0, 300.0, 20.0)
    s.open()

    r = s.rect()
    assert r is not None
    x, y, w, h = r
    assert (x, y, w) == (0, 100, 300)
    # Trigger (20px) plus the computed list height -- no dead zone below.
    assert h == 20 + s.frame_h()

    # Inside the trigger, inside the list, and just past the list edge.
    assert s.is_inside(150, 105)
    assert s.is_inside(150, 100 + 20 + s.frame_h() - 1)
    assert not s.is_inside(150, 100 + 20 + s.frame_h())
    assert not s.is_inside(301, 105)
