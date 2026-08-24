# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.popper -- focus-rect helpers, the placement algorithm,
# arrow drawing, and the CuePopper displayable's render/add lifecycle.

import pytest

import renpy as _renpy

import cue_lib.ui.popper as _pop
from cue_lib.ui.popper import (
    CuePopper,
    _cue_clear_focus_rect,
    _cue_compute_popup_position,
    _cue_draw_arrow,
    _cue_get_focus_rect,
    _cue_store_focus_rect,
)


# ==========================================================================
# _cue_compute_popup_position -- placement + clamping
# ==========================================================================


def test_position_top_normal():
    x, y, arrow = _cue_compute_popup_position(100, 100, 50, 30, 40, 20, 1280, 720, "top", 5, 8)
    assert x == 105
    assert y == 75  # 100 - 20 - 5
    assert arrow == "down"


def test_position_top_flips_below_margin():
    # Anchor at y=0 -- popup would go to -25 (< margin 8), so it flips below.
    x, y, arrow = _cue_compute_popup_position(100, 0, 50, 30, 40, 20, 1280, 720, "top", 5, 8)
    assert y == 35  # 0 + 30 + 5
    assert arrow == "up"


def test_position_bottom_normal():
    x, y, arrow = _cue_compute_popup_position(100, 100, 50, 30, 40, 20, 1280, 720, "bottom", 5, 8)
    assert y == 135  # 100 + 30 + 5
    assert arrow == "up"


def test_position_bottom_flips_over_edge():
    # Anchor near the bottom -- popup would exceed vh - margin, flips above.
    x, y, arrow = _cue_compute_popup_position(100, 700, 50, 30, 40, 20, 1280, 720, "bottom", 5, 8)
    assert y == 675  # 700 - 20 - 5
    assert arrow == "down"


def test_position_left_normal():
    x, y, arrow = _cue_compute_popup_position(100, 100, 50, 30, 40, 20, 1280, 720, "left", 5, 8)
    assert x == 55  # 100 - 40 - 5
    assert arrow == "right"


def test_position_left_flips_on_margin():
    x, y, arrow = _cue_compute_popup_position(10, 100, 50, 30, 40, 20, 1280, 720, "left", 5, 8)
    assert x == 65  # 10 + 50 + 5
    assert arrow == "left"


def test_position_right_normal():
    x, y, arrow = _cue_compute_popup_position(100, 100, 50, 30, 40, 20, 1280, 720, "right", 5, 8)
    assert x == 155  # 100 + 50 + 5
    assert arrow == "left"


def test_position_right_flips_over_edge():
    x, y, arrow = _cue_compute_popup_position(1200, 100, 50, 30, 40, 20, 1280, 720, "right", 5, 8)
    assert x == 1155  # 1200 - 40 - 5
    assert arrow == "right"


def test_position_unknown_defaults_top_behavior():
    x, y, arrow = _cue_compute_popup_position(100, 100, 50, 30, 40, 20, 1280, 720, "bogus", 5, 8)
    assert arrow == "down"


def test_position_clamps_to_viewport():
    # Huge popup with a corner anchor clamps into the viewport: x hits the
    # margin floor, y is bounded by vh - ch - margin after the flip.
    x, y, arrow = _cue_compute_popup_position(0, 0, 50, 30, 1300, 700, 1280, 720, "top", 5, 8)
    assert x == 8
    assert y == 12
    assert arrow == "up"


# ==========================================================================
# _cue_draw_arrow
# ==========================================================================


def test_draw_arrow_directions():
    # px=py=0, pw=10, ph=20 -> center (5, 10).
    for direction, expected_pts in [
        ("down", [(-1, 20), (5, 26), (11, 20)]),
        ("up", [(-1, 0), (5, -6), (11, 0)]),
        ("right", [(10, 4), (16, 10), (10, 16)]),
        ("left", [(0, 4), (-6, 10), (0, 16)]),
    ]:
        r = _renpy.Render(10, 20)
        _cue_draw_arrow(r, 0, 0, 10, 20, direction)
        op = r.canvas().ops[-1]
        assert op[0] == "polygon"
        assert op[2] == expected_pts


# ==========================================================================
# focus-rect helpers (version-adaptive)
# ==========================================================================


@pytest.fixture
def anchors():
    _pop._cue_popper_anchors = {"btn": (0, 0, 40, 20)}
    yield _pop._cue_popper_anchors
    _pop._cue_popper_anchors = {}


def test_store_focus_rect_v8_captures(monkeypatch):
    called = []
    monkeypatch.setattr(_renpy, "capture_focus", lambda name: called.append(name))
    monkeypatch.setattr(_renpy, "version_tuple", (8, 0, 0))
    _cue_store_focus_rect("btn")
    assert called == ["btn"]


def test_store_focus_rect_v7_stores(anchors, monkeypatch):
    monkeypatch.setattr(_renpy, "version_tuple", (7, 4, 10))
    monkeypatch.setattr(_renpy, "focus_coordinates", lambda: (1, 2, 3, 4))
    _cue_store_focus_rect("btn")
    assert _pop._cue_popper_anchors["btn"] == (1, 2, 3, 4)


def test_store_focus_rect_v7_none_removes(anchors, monkeypatch):
    monkeypatch.setattr(_renpy, "version_tuple", (7, 4, 10))
    monkeypatch.setattr(_renpy, "focus_coordinates", lambda: (None, None, None, None))
    _cue_store_focus_rect("btn")
    assert "btn" not in _pop._cue_popper_anchors


def test_clear_focus_rect_v8(monkeypatch):
    called = []
    monkeypatch.setattr(_renpy, "clear_capture_focus", lambda name: called.append(name))
    monkeypatch.setattr(_renpy, "version_tuple", (8, 0, 0))
    _cue_clear_focus_rect("btn")
    assert called == ["btn"]


def test_clear_focus_rect_v7_pops(anchors, monkeypatch):
    monkeypatch.setattr(_renpy, "version_tuple", (7, 4, 10))
    _cue_clear_focus_rect("btn")
    assert "btn" not in _pop._cue_popper_anchors


def test_get_focus_rect_v8_returns_rect(monkeypatch):
    monkeypatch.setattr(_renpy, "version_tuple", (8, 0, 0))
    monkeypatch.setattr(_renpy, "get_focus_rect", lambda name: (1, 2, 3, 4))
    assert _cue_get_focus_rect("btn") == (1, 2, 3, 4)


def test_get_focus_rect_v8_none_fallback(monkeypatch):
    monkeypatch.setattr(_renpy, "version_tuple", (8, 0, 0))
    monkeypatch.setattr(_renpy, "get_focus_rect", lambda name: None)
    assert _cue_get_focus_rect("btn") == (None, None, None, None)


def test_get_focus_rect_v7_from_anchors(anchors, monkeypatch):
    monkeypatch.setattr(_renpy, "version_tuple", (7, 4, 10))
    assert _cue_get_focus_rect("btn") == (0, 0, 40, 20)
    assert _cue_get_focus_rect("missing") == (None, None, None, None)


def test_get_focus_rect_v7_empty_anchors(monkeypatch):
    # No stored anchor -> None tuple.
    monkeypatch.setattr(_renpy, "version_tuple", (7, 4, 10))
    _pop._cue_popper_anchors = {}
    assert _cue_get_focus_rect("btn") == (None, None, None, None)


# ==========================================================================
# CuePopper displayable
# ==========================================================================


@pytest.fixture
def popper(monkeypatch):
    _pop._cue_popper_anchors = {"target": (100, 100, 50, 30)}
    monkeypatch.setattr(_renpy, "version_tuple", (7, 4, 10))
    p = CuePopper(target="target", placement="top")
    yield p, _pop._cue_popper_anchors
    _pop._cue_popper_anchors = {}


def test_popper_empty_children_renders_blank(popper):
    p, _cue = popper
    r = p.render(400, 300, 0.0, 0.0)
    assert p._frame == 1
    assert p.offsets == [(0, 0)]
    assert r.width == 1


def test_popper_render_with_stored_rect(popper):
    p, _cue = popper
    p.add("child")  # Container.add appends to children
    r = p.render(400, 300, 0.0, 0.0)
    # Anchor (100,100,50,30), placement top -> popup above the anchor.
    assert p._stored_rect == (100, 100, 50, 30)
    assert r.blits  # child was placed
    assert any(op[0] == "polygon" for op in r.canvas().ops)  # arrow drawn


def test_popper_render_no_focus_rect(popper):
    p, _cue = popper
    _cue.clear()
    p.add("child")
    r = p.render(400, 300, 0.0, 0.0)
    assert p._stored_rect is None
    assert p.offsets == [(0, 0)]
    assert r.width == 1


def test_popper_render_hide_after_delay(popper, monkeypatch):
    p, _cue = popper
    p.add("child")
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (0, 0))
    first = p.render(400, 300, 0.0, 0.0)  # mouse outside -> arm hide timer
    assert p._hide_st is not None
    second = p.render(400, 300, 0.2, 0.0)  # past the delay -> clear + early return
    assert "target" not in _cue
    assert p._stored_rect is None
    assert second.blits == []


def test_popper_render_mouse_in_anchor_keeps_open(popper, monkeypatch):
    p, _cue = popper
    p.add("child")
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (110, 110))  # inside anchor
    p.render(400, 300, 0.0, 0.0)
    assert p._hide_st is None


def test_popper_render_mouse_in_popup_keeps_open(popper, monkeypatch):
    p, _cue = popper
    p.add("child")
    # Child renders 400x300 in the mock, so the "top" popup flips below the
    # anchor into y in [135, 435], x in [100, 500]. Mouse inside that box.
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (120, 200))
    p.render(400, 300, 0.0, 0.0)
    assert p._hide_st is None


def test_popper_add_wraps_child(popper):
    p, _cue = popper
    p.add("inner")
    assert len(p.children) == 1
    wrapped = p.children[0]
    # Button wraps a Window frame wraps the child.
    assert hasattr(wrapped, "children")
    assert p.visit() == p.children


def test_popper_defaults():
    p = CuePopper(target="t")
    assert p.placement == "top"
    assert p.offset == 5
    assert p.viewport_margin == 8
    assert p._hide_st is None
    assert p._stored_rect is None
    assert p._frame == 0
