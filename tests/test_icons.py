# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.icons -- CueIconManager name -> displayable lookup.

import types

import pytest

import renpy as _renpy

import cue_lib.ui.icons as _icons
from cue_lib.ui.icons import (
    CUE_ICON_MAP,
    CUE_ICON_SIZE,
    CUE_ICON_SRC_SIZE,
    CueIconManager,
)


class _RecordingTransform(object):
    """Records Transform() construction so zoom/xzoom/child are asserted."""

    def __init__(self, child, **kwargs):
        self.child = child
        self.kwargs = kwargs


@pytest.fixture
def icon_mgr(monkeypatch):
    mgr = CueIconManager(types.SimpleNamespace(icon=lambda f: "icons/" + f))
    monkeypatch.setattr(_icons, "Transform", _RecordingTransform)
    monkeypatch.setattr(_renpy, "loadable", lambda p: True)
    logs = []
    monkeypatch.setattr(_icons, "_cue_log", lambda msg: logs.append(msg))
    return mgr, logs


def test_icon_unknown_name_returns_none(icon_mgr):
    mgr, _logs = icon_mgr
    assert mgr.displayable_for("nope") is None


def test_icon_default_size_and_cache(icon_mgr):
    mgr, _logs = icon_mgr
    first = mgr.displayable_for("play")
    assert first.kwargs["zoom"] == CUE_ICON_SIZE / float(CUE_ICON_SRC_SIZE)
    assert first.kwargs["xzoom"] == 1.0
    assert first.child == "icons/play-solid.png"
    second = mgr.displayable_for("play")
    assert second is first  # cached per (name, color, size)


def test_icon_colored_variant_cached_separately(icon_mgr):
    mgr, _logs = icon_mgr
    tinted = mgr.displayable_for("play", color="#ff0000")
    # Tinting wraps the PNG in a MatrixColor.
    assert tinted.child.im == "icons/play-solid.png"
    plain = mgr.displayable_for("play")
    assert plain.child == "icons/play-solid.png"
    assert mgr.displayable_for("play", color="#ff0000") is tinted
    assert mgr.displayable_for("play") is plain


def test_icon_mirrored_flips_xzoom(icon_mgr):
    mgr, _logs = icon_mgr
    redo = mgr.displayable_for("redo")
    assert redo.kwargs["xzoom"] == -1.0


def test_icon_explicit_size_sets_zoom(icon_mgr):
    mgr, _logs = icon_mgr
    big = mgr.displayable_for("plus", size=24)
    assert big.kwargs["zoom"] == 24 / float(CUE_ICON_SRC_SIZE)


def test_icon_missing_image_logs_and_returns_none(icon_mgr, monkeypatch):
    mgr, logs = icon_mgr
    monkeypatch.setattr(_renpy, "loadable", lambda p: False)
    assert mgr.displayable_for("play") is None
    assert logs == ["CUE-ICON: missing image icons/play-solid.png"]


def test_icon_map_names_resolve(icon_mgr):
    mgr, _logs = icon_mgr
    for name in ("xmark", "chevron-down", "gear", "trash-can", "undo"):
        assert name in CUE_ICON_MAP
        assert mgr.displayable_for(name) is not None
