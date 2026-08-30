# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.focus -- the field edit-focus helpers.

from types import SimpleNamespace

import pytest

import renpy as _renpy

import cue_lib.ui.focus as _focus
from cue_lib.state import _cue
from cue_lib.ui.overlay import CueOverlay


@pytest.fixture(autouse=True)
def _wire_overlay(monkeypatch):
    """Give _cue a real overlay so focus.py's `object is _cue.overlay`
    identity check compares against an actual object, not None."""
    monkeypatch.setattr(_cue, "overlay", CueOverlay())


def _setfield(field, obj):
    """A stand-in for Ren'Py's SetField action (exposes .field and .object)."""
    return SimpleNamespace(field=field, object=obj, value="", kind="field")


def _focusable(x, y, w, h, action):
    """A stand-in for a Ren'Py focus_list entry."""
    return SimpleNamespace(x=x, y=y, w=w, h=h, widget=SimpleNamespace(action=action))


# ---------------------------------------------------------------------------
# _cue_action_manages_input
# ---------------------------------------------------------------------------


def test_setfield_on_active_input_is_managed():
    assert _focus._cue_action_manages_input(_setfield("active_input", _cue.overlay))


def test_setfield_on_another_object_is_not_managed():
    # Same field name, but not targeting the Cue singleton.
    other = SimpleNamespace()
    assert not _focus._cue_action_manages_input(_setfield("active_input", other))


def test_setfield_on_another_field_is_not_managed():
    # Same target, different field name.
    assert not _focus._cue_action_manages_input(_setfield("some_other", _cue.overlay))


def test_none_is_not_managed():
    assert not _focus._cue_action_manages_input(None)


def test_function_action_is_not_managed():
    # A Function-like action exposes neither .field nor .object.
    assert not _focus._cue_action_manages_input(SimpleNamespace(function=lambda: None))


def test_list_action_manages_if_any_element_does():
    action = [_setfield("other", _cue.overlay), _setfield("active_input", _cue.overlay)]
    assert _focus._cue_action_manages_input(action)


def test_list_action_not_managed_when_none_match():
    action = [_setfield("other", _cue.overlay), SimpleNamespace()]
    assert not _focus._cue_action_manages_input(action)


# ---------------------------------------------------------------------------
# _cue_focusable_at_point
# ---------------------------------------------------------------------------


def _patch_focus_list(monkeypatch, entries):
    stub = SimpleNamespace(focus_list=entries)
    monkeypatch.setattr(_renpy.display, "focus", stub, raising=False)


def test_backdrop_filtered_by_keep(monkeypatch):
    backdrop = _focusable(0, 0, 500, 1080, SimpleNamespace())  # Function action
    field = _focusable(32, 434, 200, 16, _setfield("active_input", _cue.overlay))
    _patch_focus_list(monkeypatch, [backdrop, field])

    got = _focus._cue_focusable_at_point(40, 440, _focus._cue_field_control)
    assert got is field


def test_innermost_wins_when_no_keep(monkeypatch):
    outer = _focusable(0, 0, 500, 1080, SimpleNamespace())
    inner = _focusable(32, 434, 200, 16, _setfield("active_input", _cue.overlay))
    _patch_focus_list(monkeypatch, [outer, inner])

    got = _focus._cue_focusable_at_point(40, 440)
    assert got is inner


def test_returns_none_when_only_backdrop_covers_point_with_keep(monkeypatch):
    backdrop = _focusable(0, 0, 500, 1080, SimpleNamespace())
    _patch_focus_list(monkeypatch, [backdrop])

    got = _focus._cue_focusable_at_point(40, 440, _focus._cue_field_control)
    assert got is None


def test_returns_none_when_point_is_empty(monkeypatch):
    _patch_focus_list(monkeypatch, [_focusable(0, 0, 100, 100, SimpleNamespace())])
    assert _focus._cue_focusable_at_point(500, 500, _focus._cue_field_control) is None
