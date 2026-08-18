# -*- coding: utf-8 -*-
# CueVideoMarkerTimeline interaction tests.  The timeline drops the
# multi-select group when the user clicks empty space, and group creation
# keeps the active marker as the anchor.
#
# Empty-click clear must restart the interaction so the SFX panel re-renders
# its tab highlights immediately -- regression: the stale blue selected-tab
# bg lingered until the mouse left the timeline area, because the click
# cleared the selection without restarting the interaction (motion over the
# timeline is swallowed by IgnoreEvent, so the screen never re-evaluated).
#
# Group creation must NOT move the active marker to the leftmost selected --
# regression: with pool 4 active, alt-clicking/shift-clicking a group made
# pool 1 active.

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
    """Stand-in for _cue.markers.video: the selected set, the active pool
    index, and the getter/setter the timeline's event() touches."""

    def __init__(self, selected, active=0):
        self.selected = set(selected)
        self.active = active
        self.set_active_calls = []

    def get_selected(self):
        return set(self.selected)

    def get_active(self):
        return self.active

    def set_active(self, pool_index):
        self.active = pool_index
        self.set_active_calls.append(pool_index)


def _make_timeline(selected, active=0, times=None):
    """A timeline over a 2s video at base speed, with the module _cue
    singleton pointed at the given selection/active state.  Returns the
    timeline plus the fake video context so tests can assert on it."""
    _cue.speed_resolver = _FakeSpeedResolver()
    video = _FakeVideoContext(selected, active)
    _cue.markers = SimpleNamespace(video=video)
    if times is None:
        times = [0.2, 0.4]
    timeline = CueVideoMarkerTimeline(
        get_markers=lambda: [{"time": t} for t in times],
        get_active=video.get_active,
        set_active=video.set_active,
        set_time=lambda i, t: None,
        get_dur=lambda: 2.0,
    )
    return timeline, video


def _click():
    """A plain left MOUSEBUTTONDOWN (position passed to event())."""
    return SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1)


def test_empty_click_drops_group_and_restarts_interaction(monkeypatch):
    calls = []
    monkeypatch.setattr(renpy, "restart_interaction",
                        lambda *a, **k: calls.append(a))
    timeline, video = _make_timeline({0, 1})

    assert video.selected == {0, 1}
    with pytest.raises(IgnoreEvent):
        # Both marker tabs sit at px=0 on the default 1px width, so x=15 is
        # clear of both while still inside the padded track (PAD_X=10, w=1).
        timeline.event(_click(), 15, 5, 0.0)

    assert video.selected == set()
    assert calls, ("empty-click clear must restart the interaction so the "
                   "SFX panel re-renders the tab highlights immediately")


def test_alt_click_group_keeps_active_anchor(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_LALT)
    timeline, video = _make_timeline(selected=set(), active=3,
                                     times=[0.2, 0.4, 0.6, 0.8])
    timeline._w = 200
    # Alt-click marker 1: its tab spans inner_x [13, 27] (px=20 on a 200px
    # track), so a screen click at x=30 lands on it.
    with pytest.raises(IgnoreEvent):
        timeline.event(_click(), 30, 15, 0.0)

    assert video.selected == {0, 3}
    assert video.active == 3, "group creation must keep the active anchor"
    assert video.set_active_calls == []


def test_alt_click_active_toggles_out_and_reanchors(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_LALT)
    timeline, video = _make_timeline(selected={0, 1, 3}, active=3,
                                     times=[0.2, 0.4, 0.6, 0.8])
    timeline._w = 200
    # Alt-click the active marker (pool 4, px=80 -> screen x=90): the group
    # drops it and the active re-anchors to the nearest remaining member by
    # time (pool 2 at 0.4 is closest to the removed 0.8, not pool 1 at 0.2).
    with pytest.raises(IgnoreEvent):
        timeline.event(_click(), 90, 15, 0.0)

    assert video.selected == {0, 1}
    assert video.active == 1
    assert video.set_active_calls == [1]


def test_alt_click_other_member_keeps_active(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_LALT)
    timeline, video = _make_timeline(selected={0, 1, 3}, active=3,
                                     times=[0.2, 0.4, 0.6, 0.8])
    timeline._w = 200
    # Alt-click a NON-active group member (pool 2, px=40 -> screen x=50):
    # it leaves the group but the active stays anchored.
    with pytest.raises(IgnoreEvent):
        timeline.event(_click(), 50, 15, 0.0)

    assert video.selected == {0, 3}
    assert video.active == 3
    assert video.set_active_calls == []


def test_shift_click_range_keeps_active_anchor(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_SHIFT)
    timeline, video = _make_timeline(selected=set(), active=3,
                                     times=[0.2, 0.4, 0.6, 0.8])
    timeline._w = 200
    # Shift-click marker 2: its tab spans inner_x [33, 47] (px=40), so a
    # screen click at x=50 lands on it.  Range runs active(0.8) back to the
    # click(0.4), selecting pools 2..4.
    with pytest.raises(IgnoreEvent):
        timeline.event(_click(), 50, 15, 0.0)

    assert video.selected == {1, 2, 3}
    assert video.active == 3, "group creation must keep the active anchor"
    assert video.set_active_calls == []
