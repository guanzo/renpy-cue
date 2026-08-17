# -*- coding: utf-8 -*-
# CueVideoMarkerTimeline interaction tests.  A plain click on empty timeline
# space drops the multi-select group; that path must restart the interaction
# so the SFX panel re-renders its tab highlights immediately.  Regression:
# the stale blue selected-tab bg lingered until the mouse left the timeline
# area, because the click cleared the selection without restarting the
# interaction (mouse motion over the timeline is swallowed by IgnoreEvent,
# so the screen never re-evaluated while the cursor stayed on it).

import pytest
from types import SimpleNamespace

import pygame
import renpy

from cue_lib.state import _cue
from cue_lib.ui.displayables import CueVideoMarkerTimeline, IgnoreEvent


class _FakeSpeedResolver(object):
    def get_current_speed(self):
        return 1.0


class _FakeVideoContext(object):
    """Stand-in for _cue.markers.video: the selected set plus the getter
    the timeline reads on every click."""

    def __init__(self, selected):
        self.selected = set(selected)

    def get_selected(self):
        return set(self.selected)


def _make_timeline(selected):
    """A timeline over a 2s video with two marker pools at base speed,
    with the module _cue singleton pointed at the given selection group."""
    _cue.speed_resolver = _FakeSpeedResolver()
    _cue.markers = SimpleNamespace(video=_FakeVideoContext(selected))
    return CueVideoMarkerTimeline(
        get_markers=lambda: [{"time": 0.2}, {"time": 0.4}],
        get_active=lambda: 0,
        set_active=lambda i: None,
        set_time=lambda i, t: None,
        get_dur=lambda: 2.0,
    )


def _click_empty():
    """MOUSEBUTTONDOWN at a spot with no marker tab under the cursor.
    Both marker tabs sit at px=0 on the default 1px width, so x=15 is clear
    of both while still inside the padded track (PAD_X=10, width=1)."""
    return SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1)


def test_empty_click_drops_group_and_restarts_interaction(monkeypatch):
    calls = []
    monkeypatch.setattr(renpy, "restart_interaction",
                        lambda *a, **k: calls.append(a))
    timeline = _make_timeline({0, 1})

    assert _cue.markers.video.selected == {0, 1}
    with pytest.raises(IgnoreEvent):
        timeline.event(_click_empty(), 15, 5, 0.0)

    assert _cue.markers.video.selected == set()
    assert calls, ("empty-click clear must restart the interaction so the "
                   "SFX panel re-renders the tab highlights immediately")
