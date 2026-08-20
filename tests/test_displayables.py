# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.displayables -- key-capture helpers and the six
# creator-defined displayable classes.

import types

import pytest

import pygame as _pygame
import renpy as _renpy

import cue_lib.ui.displayables as _displ
from cue_lib.ui.displayables import (
    CueAutoSpeedChart,
    CueKeyCaptureDisplayable,
    CueMarkerTooltipOverlay,
    CueSelfUpdatingLabel,
    CueTooltip,
    CueVideoMarkerTimeline,
    CueVideoTimeline,
    _cue_build_key_code_map,
    _cue_keysym_from_event,
)
from renpy.display.core import IgnoreEvent


@pytest.fixture(autouse=True)
def _reset_marker_tip_mailbox():
    # Class-level tip state persists across tests -- clear it each time.
    CueVideoMarkerTimeline._marker_tip_text = ""
    CueVideoMarkerTimeline._marker_tip_x = 0
    CueVideoMarkerTimeline._marker_tip_y = 0


# ==========================================================================
# Key-capture helpers
# ==========================================================================

class _FakeConsts(object):
    K_A = 100
    K_B = 200
    K_LSHIFT = 1073742049   # bare modifier -- must be filtered


def test_build_key_code_map_filters_bare_mods(monkeypatch):
    monkeypatch.setattr(_pygame, "constants", _FakeConsts())
    code_map = _cue_build_key_code_map()
    assert code_map[100] == "K_A"
    assert code_map[200] == "K_B"
    assert 1073742049 not in code_map


def test_keysym_from_event_ignores_non_keydown():
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, key=_pygame.K_F5, mod=0)
    assert _cue_keysym_from_event(ev) is None


def test_keysym_from_event_unmapped_key():
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=999, mod=0)
    assert _cue_keysym_from_event(ev) is None


def test_keysym_from_event_plain():
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5, mod=0)
    assert _cue_keysym_from_event(ev) == "K_F5"


def test_keysym_from_event_with_mods_sorted():
    ev = types.SimpleNamespace(
        type=_pygame.KEYDOWN, key=_pygame.K_1,
        mod=_pygame.KMOD_CTRL | _pygame.KMOD_SHIFT)
    assert _cue_keysym_from_event(ev) == "ctrl_shift_K_1"


def test_keysym_from_event_alt():
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5,
                               mod=_pygame.KMOD_ALT)
    assert _cue_keysym_from_event(ev) == "alt_K_F5"


def test_keysym_from_event_meta():
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5,
                               mod=_pygame.KMOD_META)
    assert _cue_keysym_from_event(ev) == "meta_K_F5"


# ==========================================================================
# CueSelfUpdatingLabel
# ==========================================================================

def test_self_updating_label_renders_and_redraws(monkeypatch):
    redraws = []
    monkeypatch.setattr(_renpy, "redraw",
                        lambda d, when: redraws.append((d, when)))
    label = CueSelfUpdatingLabel(lambda: "hi")
    r = label.render(100, 30, 0.0, 0.0)
    assert r.width == 100
    assert len(r.blits) == 1
    assert redraws == [(label, 0.05)]


# ==========================================================================
# CueVideoTimeline
# ==========================================================================

@pytest.fixture
def vtl(monkeypatch):
    seeks = []
    vid = types.SimpleNamespace(
        get_duration=lambda: 100.0,
        get_elapsed=lambda: 25.0,
        paused=False,
        channel="movie",
        seek_to=lambda t: seeks.append(t),
    )
    cue = types.SimpleNamespace(vid_manager=vid)
    monkeypatch.setattr(_displ, "_cue", cue)
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (200, 400))
    return types.SimpleNamespace(cue=cue, vid=vid, seeks=seeks,
                                 timeline=CueVideoTimeline())


def test_vtl_render_default(vtl):
    r = vtl.timeline.render(400, 60, 0.0, 0.0)
    assert vtl.timeline._w == 400
    assert vtl.timeline._bar_y == 22
    ops = r.canvas().ops
    # Background + playhead rects.
    assert ("rect", "#333333", (0, 22, 400, 16), 0) in ops
    assert ("rect", "#ffffff", (100, 22, 2, 16), 0) in ops
    # Mouse at (200,400) is not over the bar -- no seek tooltip.
    assert len(r.blits) == 0


def test_vtl_render_hovered_changes_bg(vtl, monkeypatch):
    monkeypatch.setattr(_renpy, "get_hovered", lambda: [vtl.timeline])
    r = vtl.timeline.render(400, 60, 0.0, 0.0)
    assert ("rect", "#3a3a3a", (0, 22, 400, 16), 0) in r.canvas().ops


def test_vtl_render_paused_playhead_color(vtl):
    vtl.vid.paused = True
    r = vtl.timeline.render(400, 60, 0.0, 0.0)
    assert ("rect", "#ffaa00", (100, 22, 2, 16), 0) in r.canvas().ops


def test_vtl_render_mouse_over_bar_shows_tooltip(vtl, monkeypatch):
    # Bar spans y in [22, 38]; put the cursor on it with the channel live.
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (120, 30))
    r = vtl.timeline.render(400, 60, 0.0, 0.0)
    assert len(r.blits) == 1  # the seek-tooltip blit


def test_vtl_render_zero_duration_skips_playhead(vtl):
    vtl.vid.get_duration = lambda: 0.0
    r = vtl.timeline.render(400, 60, 0.0, 0.0)
    ops = r.canvas().ops
    assert len([op for op in ops if op[0] == "rect"]) == 1  # bg only


def test_vtl_event_mousemotion_updates_screen_offsets(vtl, monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (250, 410))
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    assert vtl.timeline.event(ev, 50, 10, 0.0) is None
    assert vtl.timeline._screen_x == 200
    assert vtl.timeline._screen_y == 400


def test_vtl_event_click_on_bar_seeks(vtl):
    vtl.timeline.render(400, 60, 0.0, 0.0)  # sets _bar_y=22, _w=400
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        vtl.timeline.event(ev, 100, 25, 0.0)
    assert vtl.seeks == [25.0]  # 100/400 * 100


def test_vtl_event_click_off_bar_no_seek(vtl):
    vtl.timeline.render(400, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert vtl.timeline.event(ev, 100, 5, 0.0) is None
    assert vtl.seeks == []


def test_vtl_event_click_no_channel_no_seek(vtl):
    vtl.cue.vid_manager.channel = None
    vtl.timeline.render(400, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert vtl.timeline.event(ev, 100, 25, 0.0) is None
    assert vtl.seeks == []


def test_vtl_event_unhandled_button_noop(vtl):
    # Right-click is not a seek gesture -- falls through to return None.
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=3)
    assert vtl.timeline.event(ev, 50, 10, 0.0) is None


# ==========================================================================
# CueVideoMarkerTimeline
# ==========================================================================

def _make_mtl(monkeypatch, markers_list, dur=10.0, speed=1.0, selected=None):
    selected = set() if selected is None else selected
    video = types.SimpleNamespace(get_selected=lambda: selected,
                                  selected=selected,
                                  finalize_drag=lambda: None)
    markers = types.SimpleNamespace(video=video)
    speed_resolver = types.SimpleNamespace(get_current_speed=lambda: speed)
    repeater = types.SimpleNamespace(compute_preview_times=lambda: [])
    cue = types.SimpleNamespace(markers=markers, speed_resolver=speed_resolver,
                                repeater=repeater)
    monkeypatch.setattr(_displ, "_cue", cue)

    calls = {"set_time": [], "set_active_index": [], "finalize": 0}

    def _set_time(idx, t):
        calls["set_time"].append((idx, t))
        markers_list[idx]["time"] = t

    def _set_active(idx):
        calls["set_active_index"].append(idx)

    def _finalize():
        calls["finalize"] += 1

    video.finalize_drag = _finalize
    tl = CueVideoMarkerTimeline(
        get_markers=lambda: markers_list,
        get_active_index=lambda: 0,
        set_active_index=_set_active,
        set_time=_set_time,
        get_dur=lambda: dur,
    )
    return types.SimpleNamespace(tl=tl, cue=cue, video=video, calls=calls)


MTL_MARKERS = [{"time": 0.0}, {"time": 5.0}]


def test_mtl_render_basic(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    r = env.tl.render(200, 60, 0.0, 0.0)
    assert r.height == env.tl._total_h()  # 30
    ops = r.canvas().ops
    # 2 marker line-rects + 2 tab-rects.
    assert len([op for op in ops if op[0] == "rect"]) == 4
    assert CueVideoMarkerTimeline._marker_tip_text == ""


def test_mtl_render_scaled_and_preview(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], speed=2.0,
                    selected={1})
    env.cue.repeater.compute_preview_times = lambda: [2.5]
    r = env.tl.render(200, 60, 0.0, 0.0)
    ops = r.canvas().ops
    colors = [op[1] for op in ops if op[0] == "rect"]
    assert "#9966aa" in colors   # scaled active color
    assert "#775588" in colors   # scaled inactive color
    # 2 markers + 1 preview marker = 6 rects total.
    assert len(colors) == 6
    # Preview marker "?" text blits.
    assert len(r.blits) == 3


def test_mtl_render_with_selection_colors(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={1})
    r = env.tl.render(200, 60, 0.0, 0.0)
    colors = [op[1] for op in r.canvas().ops if op[0] == "rect"]
    assert "#669966" in colors   # active
    assert env.tl.SEL_BG in colors  # selected tab bg
    assert env.tl.SEL_LINE in colors  # selected tab line


def test_mtl_render_empty_markers(monkeypatch):
    env = _make_mtl(monkeypatch, [])
    r = env.tl.render(200, 60, 0.0, 0.0)
    assert r.canvas().ops == []


def test_mtl_render_zero_duration_skips_preview(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}], dur=0.0)
    visited = []

    def _preview():
        visited.append(1)
        return [1.0]

    env.cue.repeater.compute_preview_times = _preview
    env.tl.render(200, 60, 0.0, 0.0)
    assert visited == []


def test_mtl_render_while_dragging(monkeypatch):
    # Render while a drag is in flight -- the dragged tab turns blue.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 100, 15, 0.0)
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    with pytest.raises(IgnoreEvent):
        env.tl.event(mot, 120, 15, 0.0)
    assert env.tl._drag_on
    r = env.tl.render(200, 60, 0.0, 0.0)
    colors = [op[1] for op in r.canvas().ops if op[0] == "rect"]
    assert "#7777cc" in colors


def test_mtl_render_after_hover(monkeypatch):
    # Render after hovering a non-selected tab -- its bg lightens.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    env.tl.event(ev, 100, 15, 0.0)
    assert env.tl._hover_idx == 1
    r = env.tl.render(200, 60, 0.0, 0.0)
    colors = [op[1] for op in r.canvas().ops if op[0] == "rect"]
    assert "#666666" in colors


def test_mtl_render_uses_px_cache_when_dur_zero(monkeypatch):
    # A prior dur>0 render caches px; a dur==0 render falls back to it.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    assert hasattr(env.tl, "_px_cache")
    env.tl.get_dur = lambda: 0.0
    r = env.tl.render(200, 60, 0.0, 0.0)
    assert r is not None


def test_mtl_render_publishes_tip(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl._tip_text = "Tip!"
    env.tl._screen_x = 10
    env.tl._screen_y = 20
    env.tl._tip_x = 30
    env.tl._tip_y = 40
    env.tl.render(200, 60, 0.0, 0.0)
    assert CueVideoMarkerTimeline._marker_tip_text == "Tip!"
    assert CueVideoMarkerTimeline._marker_tip_x == 10 + 30 + 10
    assert CueVideoMarkerTimeline._marker_tip_y == 20 + 40


def test_mtl_event_mousemotion_hover_sets_tip(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)  # _w=180
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    # Marker 1 tab (t=5) sits at screen x in [93, 107], y in [8, 24].
    assert env.tl.event(ev, 100, 15, 0.0) is None
    assert "Pool 2" in env.tl._tip_text
    assert "Offset from Pool 1" in env.tl._tip_text
    assert env.tl._hover_idx == 1


def test_mtl_event_mousemotion_hover_multiselect_tip(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    env.tl.event(ev, 100, 15, 0.0)
    assert "[2 selected]" in env.tl._tip_text


def test_mtl_event_mousemotion_no_hit_clears_tip(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    env.tl._tip_text = "stale"
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    env.tl.event(ev, 0, 40, 0.0)  # y past the track
    assert env.tl._tip_text == ""


def test_mtl_event_motion_zero_duration_no_hit(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}], dur=0.0)
    env.tl.render(200, 60, 0.0, 0.0)
    env.tl._tip_text = "stale"
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    assert env.tl.event(ev, 100, 15, 0.0) is None
    assert env.tl._tip_text == ""


def test_mtl_event_hover_scaled_shows_note(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], speed=2.0)
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    # At 2.0x, marker 1 (t=5) draws at inner_x in [38, 52].
    env.tl.event(ev, 55, 15, 0.0)
    assert "[Auto-scaled from 1.0x." in env.tl._tip_text


def test_mtl_event_click_selects_single(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 100, 15, 0.0)
    assert env.calls["set_active_index"] == [1]
    assert env.tl._drag_idx == 1
    assert env.tl._drag_start_x == 90
    assert env.calls["set_time"] == []


def test_mtl_event_click_empty_clears_selection(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    # x=40 -> inner_x=30 sits between the two marker tabs (no hit) -> clear.
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 40, 15, 0.0)
    assert env.video.selected == set()


def test_mtl_event_click_outside_bounds_noop(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert env.tl.event(ev, 500, 15, 0.0) is None  # inner_x=490 out of bounds
    assert env.video.selected == {0, 1}


def test_mtl_event_click_scaled_noop(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], speed=2.0)
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert env.tl.event(ev, 100, 15, 0.0) is None
    assert env.calls["set_active_index"] == []


def test_mtl_event_alt_click_toggles_selection(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods",
                        lambda: _pygame.KMOD_LALT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 100, 15, 0.0)
    # Alt-click on marker 1 with no selection pulls in active (0) + hit (1).
    assert env.video.selected == {0, 1}
    # Active stays anchored (already in the group); no re-anchor needed.
    assert env.calls["set_active_index"] == []


def test_mtl_event_alt_click_removes_selected(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={1})
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods",
                        lambda: _pygame.KMOD_LALT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 100, 15, 0.0)
    # marker 1 was selected; alt-click discards it and nothing stays active.
    assert env.video.selected == set()
    assert env.calls["set_active_index"] == []


def test_mtl_event_shift_click_selects_range(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods",
                        lambda: _pygame.KMOD_LSHIFT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 100, 15, 0.0)
    # Range from active (t=0) to hit (t=5) covers both markers.
    assert env.video.selected == {0, 1}
    # The anchor marker is already in the range; active is left untouched.
    assert env.calls["set_active_index"] == []


def test_mtl_event_shift_click_empty_range_select(monkeypatch):
    # Shift-click on empty track: range from active (t=0) to the click.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods", lambda: _pygame.KMOD_LSHIFT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 40, 15, 0.0)  # inner_x=30 -> click_time ~1.67
    assert env.video.selected == {0}


def test_mtl_event_shift_click_uses_existing_selection(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={1})
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods", lambda: _pygame.KMOD_LSHIFT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    # Click marker 0; nearest selected ref is marker 1 -> range [0, 5].
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 10, 15, 0.0)
    assert env.video.selected == {0, 1}


def test_mtl_event_shift_click_active_out_of_range(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    env.tl.get_active_index = lambda: 5  # invalid index -> early return
    monkeypatch.setattr(_pygame.key, "get_mods", lambda: _pygame.KMOD_LSHIFT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert env.tl.event(ev, 100, 15, 0.0) is None
    assert env.video.selected == set()


def test_mtl_event_other_button_noop(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=3)
    assert env.tl.event(ev, 100, 15, 0.0) is None


def test_mtl_event_drag_single_after_threshold(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 100, 15, 0.0)
    assert env.tl._drag_idx == 1 and not env.tl._drag_on

    # Drag 20px right (well past the 4px threshold).
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    with pytest.raises(IgnoreEvent):
        env.tl.event(mot, 120, 15, 0.0)
    assert env.tl._drag_on
    assert len(env.calls["set_time"]) == 1
    assert "Pool 2" in env.tl._tip_text
    # delta = (110/180 - 90/180) * 10 = 1.11
    idx, t = env.calls["set_time"][0]
    assert idx == 1
    assert abs(t - (5.0 + (20 / 180.0) * 10.0)) < 1e-6


def test_mtl_event_drag_multi_select_group(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 10, 15, 0.0)  # hit marker 0 (t=0) at px=10
    assert env.tl._drag_idx == 0

    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    with pytest.raises(IgnoreEvent):
        env.tl.event(mot, 40, 15, 0.0)  # 30px right -> delta = 30/180*10 = 1.67
    assert env.tl._drag_on
    # Both selected markers move by the same delta.
    assert len(env.calls["set_time"]) == 2
    d = (30 / 180.0) * 10.0
    assert env.calls["set_time"][0][0] == 0
    assert abs(env.calls["set_time"][0][1] - d) < 1e-6
    assert env.calls["set_time"][1][0] == 1
    assert abs(env.calls["set_time"][1][1] - (5.0 + d)) < 1e-6
    assert "(2 selected)" in env.tl._tip_text


def test_mtl_event_drag_clamps_to_duration(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 10, 15, 0.0)
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    # Drag far right -- clamps to keep marker 1 (5.0) at most 10.0.
    with pytest.raises(IgnoreEvent):
        env.tl.event(mot, 190, 15, 0.0)
    assert env.calls["set_time"][1][1] <= 10.0 + 1e-6


def test_mtl_event_drag_clamps_to_zero(monkeypatch):
    # Group min is 2.0, so dragging left clamps at marker 0 hitting 0.0.
    env = _make_mtl(monkeypatch, [{"time": 2.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 100, 15, 0.0)  # hit marker 1 (t=5)
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    # Drag far left -- raw delta is -5.0, lo_room is -2.0 -> clamp at -2.0.
    with pytest.raises(IgnoreEvent):
        env.tl.event(mot, -200, 15, 0.0)
    assert abs(env.calls["set_time"][0][1]) < 1e-6


def test_mtl_event_mouseup_finalizes_drag(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={1})
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 100, 15, 0.0)
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    with pytest.raises(IgnoreEvent):
        env.tl.event(mot, 120, 15, 0.0)  # becomes a drag
    up = types.SimpleNamespace(type=_pygame.MOUSEBUTTONUP, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(up, 120, 15, 0.0)
    assert env.calls["finalize"] == 1
    assert env.tl._drag_idx == -1


def test_mtl_event_mouseup_click_clears_multiselect(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}],
                    selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(down, 100, 15, 0.0)  # click on a multi-selected marker
    up = types.SimpleNamespace(type=_pygame.MOUSEBUTTONUP, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(up, 100, 15, 0.0)
    assert env.calls["finalize"] == 0
    assert env.video.selected == set()


def test_mtl_event_mouseup_no_drag_noop(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    up = types.SimpleNamespace(type=_pygame.MOUSEBUTTONUP, button=1)
    assert env.tl.event(up, 100, 15, 0.0) is None


# ==========================================================================
# CueTooltip
# ==========================================================================

def test_tooltip_render_basic(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (500, 400))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    # text render is 350 wide / 100 tall in the mock; pad to 358x104.
    assert len(r.blits) == 1
    assert r.blits[0][1] == (512, 392)


def test_tooltip_render_flips_left_on_right_edge(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (1000, 400))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    tx, _ = r.blits[0][1]
    # Outer box is 362 wide (content + 1px border + 2px shadow).
    assert tx == 1000 - 362 - 12


def test_tooltip_render_clamps_bottom_and_negative(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (1000, 700))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    _, ty = r.blits[0][1]
    assert ty == 720 - 108


def test_tooltip_render_clamps_negative_top(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (-50, -10))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    tx, ty = r.blits[0][1]
    assert tx == 0
    assert ty == 0


def test_tooltip_draws_border_and_shadow(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (500, 400))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    tip_render = r.blits[0][0]
    # Outer box = content 358x104 + 1px border all around + 2px shadow.
    assert tip_render.width == 362
    assert tip_render.height == 108
    # Shadow blit: translucent black child render, offset 2px.
    shadow, pos = tip_render.blits[0]
    assert pos == (2, 2)
    assert shadow.width == 360
    assert shadow.height == 106
    assert shadow.alpha == 0.45
    assert shadow.canvas().ops[0] == ("rect", "#000000", (0, 0, 360, 106), 0)
    ops = tip_render.canvas().ops
    assert ops[0] == ("rect", "#555555", (0, 0, 360, 106), 1)  # border outline
    assert ops[1] == ("rect", "#2e2e2e", (1, 1, 358, 104), 0)  # interior fill


def test_tooltip_focus_anchors_above_element(monkeypatch):
    monkeypatch.setattr(_renpy, "focus_coordinates", lambda: (200, 300, 100, 40))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    tx, ty = r.blits[0][1]
    # Centered over the element, sitting above it with a 4px gap.
    assert tx == 200 + (100 - 362) // 2
    assert ty == 300 - 108 - 4


def test_tooltip_focus_flips_below_when_no_room_above(monkeypatch):
    monkeypatch.setattr(_renpy, "focus_coordinates", lambda: (300, 20, 120, 30))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    _, ty = r.blits[0][1]
    # Above would go negative, so it lands below the element instead.
    assert ty == 20 + 30 + 4


def test_tooltip_focus_clamps_to_right_edge(monkeypatch):
    monkeypatch.setattr(_renpy, "focus_coordinates", lambda: (1200, 300, 100, 40))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    tx, ty = r.blits[0][1]
    # Centering would push past the right edge (1280); clamp to the edge.
    assert tx == 1280 - 362
    assert ty == 300 - 108 - 4


# ==========================================================================
# CueMarkerTooltipOverlay
# ==========================================================================

def test_tooltip_overlay_empty():
    r = CueMarkerTooltipOverlay().render(800, 600, 0.0, 0.0)
    assert r.width == 1


def test_tooltip_overlay_with_text():
    CueVideoMarkerTimeline._marker_tip_text = "Tip"
    CueVideoMarkerTimeline._marker_tip_x = 50
    CueVideoMarkerTimeline._marker_tip_y = 60
    r = CueMarkerTooltipOverlay().render(800, 600, 0.0, 0.0)
    assert r.blits[0][1] == (50, 60)


# ==========================================================================
# CueAutoSpeedChart
# ==========================================================================

def test_compute_points_less_than_two():
    assert CueAutoSpeedChart._compute_points([], 200, 100) == ([], 0.0, 0.0)
    assert CueAutoSpeedChart._compute_points([1.0], 200, 100) == ([], 0.0, 0.0)


def test_compute_points_three_speeds():
    points, lo, hi = CueAutoSpeedChart._compute_points([1.0, 2.0, 3.0], 200, 100)
    assert (lo, hi) == (1.0, 3.0)
    assert points[0] == (35, 82)
    assert points[1] == (113, 45)
    assert points[2] == (192, 8)


def test_compute_points_flat_speeds():
    points, lo, hi = CueAutoSpeedChart._compute_points([2.0, 2.0], 200, 100)
    assert (lo, hi) == (2.0, 2.0)
    assert points[0][1] == points[1][1]


@pytest.fixture
def chart(monkeypatch):
    seq = types.SimpleNamespace(
        speeds_for=lambda tag: [1.0, 2.0, 3.0],
        current_step_index=lambda: 1,
    )
    cue = types.SimpleNamespace(current_file="v.ogv", video_sequence=seq)
    monkeypatch.setattr(_displ, "_cue", cue)
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (500, 500))
    return types.SimpleNamespace(cue=cue, seq=seq, chart=CueAutoSpeedChart())


def test_chart_render_too_small(chart):
    r = chart.chart.render(50, 50, 0.0, 0.0)
    assert r.canvas().ops == []


def test_chart_render_no_current_file(monkeypatch, chart):
    chart.cue.current_file = ""
    r = chart.chart.render(200, 100, 0.0, 0.0)
    assert r.canvas().ops == []


def test_chart_render_no_sequence(monkeypatch, chart):
    chart.cue.video_sequence = None
    r = chart.chart.render(200, 100, 0.0, 0.0)
    assert r.canvas().ops == []


def test_chart_render_hover_exception_swallowed(monkeypatch, chart):
    # get_mouse_pos returning None raises inside the tooltip block; the
    # try/except lets the rest of the chart render anyway.
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: None)
    r = chart.chart.render(200, 100, 0.0, 0.0)
    assert len(r.canvas().ops) > 0
    assert len(r.blits) == 3  # labels still blitted


def test_chart_visit_is_empty(chart):
    assert chart.chart.visit() == []


def test_chart_render_full(monkeypatch, chart):
    r = chart.chart.render(200, 100, 0.0, 0.0)
    ops = r.canvas().ops
    # Polyline: 2 dim segments + 1 bright segment for the played portion.
    lines = [op for op in ops if op[0] == "line"]
    assert len(lines) == 3
    dim = [op for op in lines if op[1] == chart.chart.COLOR_DIM]
    assert len(dim) == 2
    bright = [op for op in lines if op[1] == chart.chart.COLOR_BRIGHT]
    assert bright and bright[0][2] == (35, 82) and bright[0][3] == (113, 45)
    # Progress dot at point 1.
    circles = [op for op in ops if op[0] == "circle"]
    assert circles == [("circle", chart.chart.COLOR_DOT, (113, 45),
                        chart.chart.DOT_R)]
    # Mouse at (500,500) is outside the chart -> no hover tooltip; the 3
    # blits are the min/max y-axis labels and the current-speed label.
    assert len(r.blits) == 3


def test_chart_render_hover_tooltip(monkeypatch, chart):
    # Cursor on the first point -> tooltip renders near it.
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (35, 82))
    r = chart.chart.render(200, 100, 0.0, 0.0)
    assert len(r.blits) == 4  # y-axis labels + current-speed + tooltip


def test_chart_event_mousemotion(monkeypatch, chart):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (300, 250))
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    assert chart.chart.event(ev, 40, 30, 0.0) is None
    assert chart.chart._screen_x == 260
    assert chart.chart._screen_y == 220


# ==========================================================================
# CueKeyCaptureDisplayable
# ==========================================================================

def test_key_capture_render():
    r = CueKeyCaptureDisplayable().render(800, 600, 0.0, 0.0)
    assert (r.width, r.height) == (0, 0)


def test_key_capture_ignores_non_keydown(monkeypatch):
    calls = []
    monkeypatch.setattr(_displ, "_cue",
                        types.SimpleNamespace(keybinds=types.SimpleNamespace(
                            on_captured=lambda k: calls.append(k))))
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, key=_pygame.K_F5,
                               mod=0)
    assert CueKeyCaptureDisplayable().event(ev, 0, 0, 0.0) is None
    assert calls == []


def test_key_capture_forwards_keysym(monkeypatch):
    calls = []
    monkeypatch.setattr(_displ, "_cue",
                        types.SimpleNamespace(keybinds=types.SimpleNamespace(
                            on_captured=lambda k: calls.append(k))))
    kc = CueKeyCaptureDisplayable()
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5, mod=0)
    with pytest.raises(IgnoreEvent):
        kc.event(ev, 0, 0, 0.0)
    assert calls == ["K_F5"]


def test_key_capture_unmapped_key_no_forward(monkeypatch):
    calls = []
    monkeypatch.setattr(_displ, "_cue",
                        types.SimpleNamespace(keybinds=types.SimpleNamespace(
                            on_captured=lambda k: calls.append(k))))
    kc = CueKeyCaptureDisplayable()
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=999, mod=0)
    with pytest.raises(IgnoreEvent):
        kc.event(ev, 0, 0, 0.0)
    assert calls == []
