# -*- coding: utf-8 -*-
# Tests for cue_lib.ui.displayables -- key-capture helpers and the seven
# creator-defined displayable classes.

import types

import pytest

import pygame as _pygame
import renpy as _renpy

import cue_lib.ui.displayables as _displ
from cue_lib.ui.displayables import (
    CueAutoSpeedChart,
    CueKeyCaptureDisplayable,
    CueVideoMarkerTooltip,
    CueSelfUpdatingLabel,
    CueSidebarResizeHandle,
    CueTooltip,
    CueVideoMarkerTimeline,
    CueVideoTimeline,
    _cue_build_key_code_map,
    _cue_keysym_from_event,
    _cue_intensity_color,
    _cue_sidebar_width_from_mouse,
    CUE_INTENSITY_COLOR_LOW,
    CUE_INTENSITY_COLOR_HIGH,
)
from cue_lib.constants import CUE_INTENSITY_HINT_COLOR, CUE_INTENSITY_NOTE
from renpy.display.core import IgnoreEvent


@pytest.fixture(autouse=True)
def _reset_marker_tip_mailbox():
    # Class-level tip state persists across tests -- clear it each time.  The
    # timeline singleton is wired to the patched _cue, so also drop it so the
    # next test rebuilds against its own fake.
    CueVideoMarkerTimeline._marker_tip_text = ""
    CueVideoMarkerTimeline._marker_tip_x = 0
    CueVideoMarkerTimeline._marker_tip_y = 0
    CueVideoMarkerTimeline._instance = None
    CueSidebarResizeHandle._instance = None


# ==========================================================================
# Key-capture helpers
# ==========================================================================


class _FakeConsts(object):
    K_A = 100
    K_B = 200
    K_LSHIFT = 1073742049  # bare modifier -- must be filtered


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
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_1, mod=_pygame.KMOD_CTRL | _pygame.KMOD_SHIFT)
    assert _cue_keysym_from_event(ev) == "ctrl_shift_K_1"


def test_keysym_from_event_alt():
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5, mod=_pygame.KMOD_ALT)
    assert _cue_keysym_from_event(ev) == "alt_K_F5"


def test_keysym_from_event_meta():
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5, mod=_pygame.KMOD_META)
    assert _cue_keysym_from_event(ev) == "meta_K_F5"


# ==========================================================================
# CueSelfUpdatingLabel
# ==========================================================================


def test_self_updating_label_renders_and_redraws(monkeypatch):
    redraws = []
    monkeypatch.setattr(_renpy, "redraw", lambda d, when: redraws.append((d, when)))
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
    return types.SimpleNamespace(cue=cue, vid=vid, seeks=seeks, timeline=CueVideoTimeline())


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


def _make_mtl(
    monkeypatch, markers_list, dur=10.0, speed=1.0, selected=None, current_file="", intensity_on=False, sfx_levels=True
):
    selected = set() if selected is None else selected
    video = types.SimpleNamespace(get_selected=lambda: selected, selected=selected, finalize_drag=lambda: None)
    markers = types.SimpleNamespace(video=video, get=(lambda key, default: {"pools": []} if current_file else default))
    speed_resolver = types.SimpleNamespace(get_current_speed=lambda: speed, banding_speeds=lambda tag: [0.7, 1.0, 1.3])
    repeater = types.SimpleNamespace(compute_preview_times=lambda: [])

    def _fake_flags(entry):
        return types.SimpleNamespace(enabled=True, sfx_levels=sfx_levels, volume=True, frequency=True)

    def _fake_pool_active(igroup, variants, flags):
        # A non-None igroup is the intensity hook, gated on the per-video
        # master switch (the real predicate is tested separately).
        return intensity_on and bool(igroup)

    intensity = types.SimpleNamespace(flags_from_entry=_fake_flags, is_pool_intensity_active=_fake_pool_active)
    cue = types.SimpleNamespace(
        markers=markers,
        speed_resolver=speed_resolver,
        current_file=current_file,
        intensity=intensity,
        dialogs=types.SimpleNamespace(repeater=repeater),
    )
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


def _fake_video_context(markers_list, duration=5.0):
    # type: (list, float) -> types.SimpleNamespace
    state = {"active": 0}

    def get_markers():
        return markers_list

    def get_active_index():
        return state["active"]

    def set_active_index(idx):
        state["active"] = idx

    def set_time(idx, t):
        markers_list[idx]["time"] = t

    def get_duration():
        return duration

    return types.SimpleNamespace(
        get_markers=get_markers,
        get_active_index=get_active_index,
        set_active_index=set_active_index,
        set_time=set_time,
        get_duration=get_duration,
    )


def test_mtl_get_timeline_singleton_wired_to_video_context(monkeypatch):
    markers_list = [{"time": 0.0}, {"time": 5.0}]
    video = _fake_video_context(markers_list, duration=5.0)
    cue = types.SimpleNamespace(markers=types.SimpleNamespace(video=video))
    monkeypatch.setattr(_displ, "_cue", cue)
    tl = CueVideoMarkerTimeline.get_timeline()
    assert tl is CueVideoMarkerTimeline.get_timeline(), "timeline must be a stable singleton"
    # Wired to the live video context's own methods, so the displayable reads
    # and writes the marker state through it.
    assert tl.get_dur() == 5.0
    assert tl.get_active_index() == 0
    video.set_active_index(2)
    assert tl.get_active_index() == 2


def test_mtl_reset_timeline_drag_clears_inflight_drag(monkeypatch):
    video = _fake_video_context([{"time": 0.0}])
    cue = types.SimpleNamespace(markers=types.SimpleNamespace(video=video))
    monkeypatch.setattr(_displ, "_cue", cue)
    tl = CueVideoMarkerTimeline.get_timeline()
    tl._drag_idx = 1
    tl._drag_on = True
    tl._drag_orig_times = {0: 0.5}
    CueVideoMarkerTimeline.reset_timeline_drag()
    assert tl._drag_idx == -1
    assert not tl._drag_on
    assert tl._drag_orig_times == {}


def test_mtl_render_basic(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    r = env.tl.render(200, 60, 0.0, 0.0)
    assert r.height == env.tl._total_h()  # 30
    ops = r.canvas().ops
    # 2 marker line-rects + 2 tab-rects.
    assert len([op for op in ops if op[0] == "rect"]) == 4
    assert CueVideoMarkerTimeline._marker_tip_text == ""


def test_mtl_render_scaled_and_preview(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], speed=2.0, selected={1})
    env.cue.dialogs.repeater.compute_preview_times = lambda: [2.5]
    r = env.tl.render(200, 60, 0.0, 0.0)
    ops = r.canvas().ops
    colors = [op[1] for op in ops if op[0] == "rect"]
    assert "#9966aa" in colors  # scaled active color
    assert "#775588" in colors  # scaled inactive color
    # 2 markers + 1 preview marker = 6 rects total.
    assert len(colors) == 6
    # Preview marker "?" text blits.
    assert len(r.blits) == 3


def test_mtl_render_with_selection_colors(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={1})
    r = env.tl.render(200, 60, 0.0, 0.0)
    colors = [op[1] for op in r.canvas().ops if op[0] == "rect"]
    assert "#669966" in colors  # active
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

    env.cue.dialogs.repeater.compute_preview_times = _preview
    env.tl.render(200, 60, 0.0, 0.0)
    assert visited == []


def test_mtl_render_while_dragging(monkeypatch):
    # Render while a drag is in flight -- the marker line turns blue as the
    # drag indicator, but the tab background keeps its normal color.
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
    # Line rects are 2px wide; tab rects are TAB_W wide.  The drag purple must
    # appear on the line only, never as a tab background.
    line_colors = [op[1] for op in r.canvas().ops if op[0] == "rect" and op[2][2] == 2]
    tab_colors = [op[1] for op in r.canvas().ops if op[0] == "rect" and op[2][2] != 2]
    assert "#7777cc" in line_colors
    assert "#7777cc" not in tab_colors


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


def test_mtl_render_publishes_tip_fallback(monkeypatch):
    # No hover/drag index yet -- falls back to the cursor-anchored point.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl._tip_text = "Tip!"
    env.tl._screen_x = 10
    env.tl._screen_y = 20
    env.tl._tip_x = 30
    env.tl._tip_y = 40
    env.tl.render(200, 60, 0.0, 0.0)
    assert CueVideoMarkerTimeline._marker_tip_text == "Tip!"
    assert CueVideoMarkerTimeline._marker_tip_x == 10 + 30
    assert CueVideoMarkerTimeline._marker_tip_y == 20 + 40


def test_mtl_render_publishes_tip_anchored_to_marker(monkeypatch):
    # Hovering marker 2 (t=5): the tip anchors to the tab, not the cursor.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl._tip_text = "Tip!"
    env.tl._screen_x = 10
    env.tl._screen_y = 20
    env.tl._tip_x = 30  # would-be cursor position -- must be ignored
    env.tl._tip_y = 40
    env.tl._hover_idx = 1
    env.tl.render(200, 60, 0.0, 0.0)
    # t=5 over dur=10, inner width 180 -> tab center at local x=100.
    assert CueVideoMarkerTimeline._marker_tip_text == "Tip!"
    assert CueVideoMarkerTimeline._marker_tip_x == 10 + 100
    # Tab bottom at local y = TRACK_H - 2 + TAB_H.
    assert CueVideoMarkerTimeline._marker_tip_y == 20 + (env.tl.TRACK_H - 2 + env.tl.TAB_H)


def test_mtl_render_publishes_tip_anchored_during_drag(monkeypatch):
    # Dragging marker 1 (t=0): tip tracks the moving tab.
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl._tip_text = "Dragging"
    env.tl._screen_x = 10
    env.tl._screen_y = 20
    env.tl._hover_idx = -1
    env.tl._drag_idx = 0
    env.tl.render(200, 60, 0.0, 0.0)
    # t=0 -> tab center at local x = PAD_X.
    assert CueVideoMarkerTimeline._marker_tip_x == 10 + env.tl.PAD_X
    assert CueVideoMarkerTimeline._marker_tip_y == 20 + (env.tl.TRACK_H - 2 + env.tl.TAB_H)


def test_mtl_render_intensity_border_on_hooked_marker(monkeypatch):
    # Marker 1's pool is hooked to an intensity folder; marker 2's isn't.
    env = _make_mtl(
        monkeypatch,
        [{"time": 0.0, "igroup": {"name": "Impacts", "level": 1}}, {"time": 5.0}],
        current_file="clip.webm",
        intensity_on=True,
    )
    r = env.tl.render(200, 60, 0.0, 0.0)
    border_ops = [op for op in r.canvas().ops if op[0] == "rect" and op[1] == CUE_INTENSITY_HINT_COLOR]
    assert len(border_ops) == 1
    # The border is a strip flush under the tab's bottom edge, spanning the
    # tab width.  (Exact thickness is a live visual tweak -- not pinned here.)
    x, y, w, h = border_ops[0][2]
    assert y == env.tl.TRACK_H - 2 + env.tl.TAB_H
    assert w == env.tl.TAB_W
    assert h >= 1


def test_mtl_render_intensity_no_border_when_off(monkeypatch):
    env = _make_mtl(
        monkeypatch,
        [{"time": 0.0, "igroup": {"name": "Impacts", "level": 1}}, {"time": 5.0}],
        current_file="clip.webm",
        intensity_on=False,
    )
    r = env.tl.render(200, 60, 0.0, 0.0)
    colors = [op[1] for op in r.canvas().ops if op[0] == "rect"]
    assert CUE_INTENSITY_HINT_COLOR not in colors


def test_mtl_render_intensity_no_border_when_sfx_levels_off(monkeypatch):
    # Master toggle is on but "Swap SFX by level" is off: the pool stays on its
    # attached level folder, so it is not an intensity-swapped marker and the
    # hint strip (and its tooltip note) must not appear.
    env = _make_mtl(
        monkeypatch,
        [{"time": 0.0, "igroup": {"name": "Impacts", "level": 1}}, {"time": 5.0}],
        current_file="clip.webm",
        intensity_on=True,
        sfx_levels=False,
    )
    r = env.tl.render(200, 60, 0.0, 0.0)
    colors = [op[1] for op in r.canvas().ops if op[0] == "rect"]
    assert CUE_INTENSITY_HINT_COLOR not in colors
    env.tl._tip_text = "Pool 1 (0:00)"
    env.tl._hover_idx = 0
    env.tl.render(200, 60, 0.0, 0.0)
    tip = CueVideoMarkerTimeline._marker_tip_text
    assert CUE_INTENSITY_NOTE not in tip


def test_mtl_render_intensity_tooltip_note_on_hooked_marker(monkeypatch):
    env = _make_mtl(
        monkeypatch,
        [{"time": 0.0, "igroup": {"name": "Impacts", "level": 1}}, {"time": 5.0}],
        current_file="clip.webm",
        intensity_on=True,
    )
    env.tl._tip_text = "Pool 1 (0:00)"
    env.tl._hover_idx = 0
    env.tl.render(200, 60, 0.0, 0.0)
    tip = CueVideoMarkerTimeline._marker_tip_text
    assert tip.startswith("Pool 1 (0:00)")
    assert CUE_INTENSITY_NOTE in tip  # appended, not replacing the base text


def test_mtl_render_intensity_tooltip_no_note_unhooked(monkeypatch):
    env = _make_mtl(
        monkeypatch,
        [{"time": 0.0, "igroup": {"name": "Impacts", "level": 1}}, {"time": 5.0}],
        current_file="clip.webm",
        intensity_on=True,
    )
    env.tl._tip_text = "Pool 2 (0:05)"
    env.tl._hover_idx = 1
    env.tl.render(200, 60, 0.0, 0.0)
    assert CueVideoMarkerTimeline._marker_tip_text == "Pool 2 (0:05)"


def test_mtl_render_intensity_tooltip_no_note_when_off(monkeypatch):
    env = _make_mtl(
        monkeypatch,
        [{"time": 0.0, "igroup": {"name": "Impacts", "level": 1}}, {"time": 5.0}],
        current_file="clip.webm",
        intensity_on=False,
    )
    env.tl._tip_text = "Pool 1 (0:00)"
    env.tl._hover_idx = 0
    env.tl.render(200, 60, 0.0, 0.0)
    assert CueVideoMarkerTimeline._marker_tip_text == "Pool 1 (0:00)"


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
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={0, 1})
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


def test_mtl_event_hover_scaled_shows_pool_tooltip(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], speed=2.0)
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    # At 2.0x, marker 1 (t=5) draws at inner_x in [38, 52].  Scaled mode still
    # shows the pool tooltip on hover; the auto-scale note was removed.
    env.tl.event(ev, 55, 15, 0.0)
    assert "Pool 2 (00:05.00)" in env.tl._tip_text
    assert "Auto-scaled" not in env.tl._tip_text


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
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={0, 1})
    env.tl.render(200, 60, 0.0, 0.0)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    # x=40 -> inner_x=30 sits between the two marker tabs (no hit) -> clear.
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 40, 15, 0.0)
    assert env.video.selected == set()


def test_mtl_event_click_outside_bounds_noop(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={0, 1})
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
    monkeypatch.setattr(_pygame.key, "get_mods", lambda: _pygame.KMOD_LALT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 100, 15, 0.0)
    # Alt-click on marker 1 with no selection pulls in active (0) + hit (1).
    assert env.video.selected == {0, 1}
    # Active stays anchored (already in the group); no re-anchor needed.
    assert env.calls["set_active_index"] == []


def test_mtl_event_alt_click_removes_selected(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={1})
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods", lambda: _pygame.KMOD_LALT)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        env.tl.event(ev, 100, 15, 0.0)
    # marker 1 was selected; alt-click discards it and nothing stays active.
    assert env.video.selected == set()
    assert env.calls["set_active_index"] == []


def test_mtl_event_shift_click_selects_range(monkeypatch):
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}])
    env.tl.render(200, 60, 0.0, 0.0)
    monkeypatch.setattr(_pygame.key, "get_mods", lambda: _pygame.KMOD_LSHIFT)
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
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={0, 1})
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
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={0, 1})
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
    env = _make_mtl(monkeypatch, [{"time": 2.0}, {"time": 5.0}], selected={0, 1})
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
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={1})
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
    env = _make_mtl(monkeypatch, [{"time": 0.0}, {"time": 5.0}], selected={0, 1})
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
# CueSidebarResizeHandle
# ==========================================================================


class _SidebarEnv(object):
    """Mutable recording rig; width/counters are read fresh at assert time.

    A SimpleNamespace(**state) snapshots ints at construction, so counters
    mutated by the closures would read stale at assert time.
    """

    def __init__(self, width):
        self.width = width
        self.persists = 0
        self.restarts = 0
        self.library = types.SimpleNamespace(sidebar_width=width)


def _make_sidebar_env(monkeypatch, mouse=(0, 0), zoom=1.0, panel=500, width=320):
    # type: (Any, Tuple[int, int], float, int, int) -> Any
    """Patch renpy/_cue into a resize recording rig for the handle.

    The fake library clamps like the real CueSfxLibraryTree, so the
    no-op-when-clamped restart gate in the handle can be exercised.
    """
    env = _SidebarEnv(width)
    library = env.library

    def set_sidebar_width(w):
        env.width = max(200, min(640, int(w)))
        library.sidebar_width = env.width

    def persist_sidebar_state():
        env.persists += 1

    def restart_interaction():
        env.restarts += 1

    library.set_sidebar_width = set_sidebar_width
    library.persist_sidebar_state = persist_sidebar_state

    cue = types.SimpleNamespace(sfx=types.SimpleNamespace(library=library))
    monkeypatch.setattr(_displ, "_cue", cue)
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: mouse)
    monkeypatch.setattr(
        _renpy, "store", types.SimpleNamespace(_cue_overlay_zoom=lambda: zoom, _cue_overlay_panel_width=panel)
    )
    monkeypatch.setattr(_renpy, "restart_interaction", restart_interaction)

    return env


def test_sidebar_width_from_mouse_math():
    assert _cue_sidebar_width_from_mouse(800, 1.0, 500) == 300
    assert _cue_sidebar_width_from_mouse(800, 1.5, 500) == 700
    assert _cue_sidebar_width_from_mouse(600, 2.0, 500) == 700


def test_sidebar_handle_singleton_and_focusable():
    handle = CueSidebarResizeHandle.get_handle()
    assert handle is CueSidebarResizeHandle.get_handle()
    assert handle.focusable


def test_sidebar_handle_down_on_strip_starts_drag(monkeypatch):
    env = _make_sidebar_env(monkeypatch)
    handle = CueSidebarResizeHandle.get_handle()
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        handle.event(ev, 5, 100, 0.0)  # inside the 10px strip
    assert handle._dragging
    assert _renpy.display.interface.mouse == "cue_resize"  # pins the resize cursor
    assert env.width == 320  # a click alone never resizes


def test_sidebar_handle_down_outside_strip_ignored(monkeypatch):
    env = _make_sidebar_env(monkeypatch)
    handle = CueSidebarResizeHandle.get_handle()
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert handle.event(ev, 50, 100, 0.0) is None
    assert not handle._dragging


def test_sidebar_handle_down_off_strip_clears_stale_drag(monkeypatch):
    env = _make_sidebar_env(monkeypatch)
    handle = CueSidebarResizeHandle.get_handle()
    handle._dragging = True  # a release was missed (mouse left the window)
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    assert handle.event(ev, 50, 100, 0.0) is None
    assert not handle._dragging
    assert _renpy.display.interface.mouse == "default"  # stale cursor not forced


def test_sidebar_handle_motion_resizes_when_dragging(monkeypatch):
    env = _make_sidebar_env(monkeypatch, mouse=(800, 400))
    handle = CueSidebarResizeHandle.get_handle()
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        handle.event(down, 5, 100, 0.0)
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    with pytest.raises(IgnoreEvent):
        handle.event(mot, -200, 100, 0.0)  # cursor may leave the strip
    assert env.width == 300  # 800 * 1.0 - 500
    assert env.restarts == 1  # only when the clamped width actually moved
    assert _renpy.display.interface.mouse == "cue_resize"  # cursor survives the drag


def test_sidebar_handle_motion_clamped_skips_restart(monkeypatch):
    env = _make_sidebar_env(monkeypatch, mouse=(2000, 400), width=640)
    handle = CueSidebarResizeHandle.get_handle()
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        handle.event(down, 5, 100, 0.0)
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    with pytest.raises(IgnoreEvent):
        handle.event(mot, 0, 0, 0.0)  # 1500 clamps to the same 640
    assert env.width == 640
    assert env.restarts == 0


def test_sidebar_handle_motion_ignored_when_not_dragging(monkeypatch):
    env = _make_sidebar_env(monkeypatch, mouse=(800, 400))
    handle = CueSidebarResizeHandle.get_handle()
    mot = types.SimpleNamespace(type=_pygame.MOUSEMOTION)
    assert handle.event(mot, 0, 0, 0.0) is None
    assert env.width == 320
    assert env.restarts == 0


def test_sidebar_handle_up_ends_drag_and_persists(monkeypatch):
    env = _make_sidebar_env(monkeypatch)
    handle = CueSidebarResizeHandle.get_handle()
    down = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, button=1)
    with pytest.raises(IgnoreEvent):
        handle.event(down, 5, 100, 0.0)
    up = types.SimpleNamespace(type=_pygame.MOUSEBUTTONUP, button=1)
    with pytest.raises(IgnoreEvent):
        handle.event(up, 5, 100, 0.0)
    assert not handle._dragging
    assert _renpy.display.interface.mouse == "default"  # cursor restored on drop
    assert env.persists == 1


def test_sidebar_handle_up_ignored_when_not_dragging(monkeypatch):
    env = _make_sidebar_env(monkeypatch)
    handle = CueSidebarResizeHandle.get_handle()
    up = types.SimpleNamespace(type=_pygame.MOUSEBUTTONUP, button=1)
    assert handle.event(up, 0, 0, 0.0) is None
    assert env.persists == 0


def test_sidebar_cursor_poll_applies_only_while_dragging(monkeypatch):
    # The periodic poll closes the interact() reset gap: it must re-assert the
    # resize cursor while dragging and leave the default alone otherwise.
    env = _make_sidebar_env(monkeypatch)
    handle = CueSidebarResizeHandle.get_handle()
    _renpy.display.interface.mouse = "default"
    _displ._cue_sidebar_poll_cursor()
    assert _renpy.display.interface.mouse == "default"
    handle._dragging = True
    _displ._cue_sidebar_poll_cursor()
    assert _renpy.display.interface.mouse == "cue_resize"
    handle._dragging = False


def test_sidebar_handle_render_draws_nothing():
    # The strip is an invisible resize zone -- no divider line, no grip icon.
    # Its only presence is the focus registration (asserted separately), so
    # the sidebar edge stays visually clean.
    handle = CueSidebarResizeHandle.get_handle()
    r = handle.render(10, 600, 0.0, 0.0)
    assert r.canvas().ops == []
    assert r.blits == []


def test_sidebar_handle_render_registers_focus_target():
    # Without Render.add_focus the handle never becomes the focused widget on
    # hover, so focus_at_point can't return it and its cursor never applies.
    handle = CueSidebarResizeHandle.get_handle()
    r = handle.render(10, 600, 0.0, 0.0)
    assert r.focus == (handle, 0, 0, 10, 600)


# ==========================================================================
# CueTooltip
# ==========================================================================


def test_tooltip_render_basic(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (500, 400))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    # text render is 350 wide / 100 tall in the mock; pad to 358x104.
    assert len(r.blits) == 1
    # No focus target -- anchor at the cursor, centered above it.
    assert r.blits[0][1] == (500 + (0 - 362) // 2, 400 - 108 - 4)


def test_tooltip_render_no_focus_clamps_to_right_edge(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (1200, 300))
    tip = CueTooltip("hello")
    r = tip.render(800, 600, 0.0, 0.0)
    tx, _ = r.blits[0][1]
    # Outer box is 362 wide (content + 1px border + 2px shadow).
    assert tx == 1280 - 362


def test_tooltip_render_no_focus_clamps_bottom(monkeypatch):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (1200, 800))
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
# CueVideoMarkerTooltip
# ==========================================================================


def test_tooltip_overlay_empty():
    r = CueVideoMarkerTooltip().render(800, 600, 0.0, 0.0)
    assert r.width == 1


def test_tooltip_overlay_centers_above_tab():
    # Tab anchor: tip point is the tab center; overlay builds a tab-sized
    # rect and mirrors CueTooltip's above/center placement.
    CueVideoMarkerTimeline._marker_tip_text = "Tip"
    CueVideoMarkerTimeline._marker_tip_x = 500 + CueVideoMarkerTimeline.TAB_W // 2
    CueVideoMarkerTimeline._marker_tip_y = 300
    r = CueVideoMarkerTooltip().render(800, 600, 0.0, 0.0)
    tx, ty = r.blits[0][1]
    assert tx == 500 + (CueVideoMarkerTimeline.TAB_W - 362) // 2
    assert ty == 300 - CueVideoMarkerTimeline.TAB_H - 108 - 4


def test_tooltip_overlay_flips_below_when_no_room_above():
    CueVideoMarkerTimeline._marker_tip_text = "Tip"
    CueVideoMarkerTimeline._marker_tip_x = 500 + CueVideoMarkerTimeline.TAB_W // 2
    CueVideoMarkerTimeline._marker_tip_y = 60  # tab near the top edge
    r = CueVideoMarkerTooltip().render(800, 600, 0.0, 0.0)
    _, ty = r.blits[0][1]
    assert ty == 60 - CueVideoMarkerTimeline.TAB_H + CueVideoMarkerTimeline.TAB_H + 4


def test_tooltip_overlay_matches_cue_tooltip_positioning(monkeypatch):
    # Same anchor rect as a focused CueTooltip -> identical blit position.
    anchor = (500, 286, CueVideoMarkerTimeline.TAB_W, CueVideoMarkerTimeline.TAB_H)
    monkeypatch.setattr(_renpy, "focus_coordinates", lambda: anchor)
    t = CueTooltip("Tip")
    CueVideoMarkerTimeline._marker_tip_text = "Tip"
    CueVideoMarkerTimeline._marker_tip_x = anchor[0] + CueVideoMarkerTimeline.TAB_W // 2
    CueVideoMarkerTimeline._marker_tip_y = anchor[1] + CueVideoMarkerTimeline.TAB_H
    ov = CueVideoMarkerTooltip()
    assert t.render(800, 600, 0.0, 0.0).blits[0][1] == ov.render(800, 600, 0.0, 0.0).blits[0][1]


def test_tooltip_overlay_clamps_to_screen():
    CueVideoMarkerTimeline._marker_tip_text = "Tip"
    CueVideoMarkerTimeline._marker_tip_x = 100
    CueVideoMarkerTimeline._marker_tip_y = 60
    r = CueVideoMarkerTooltip().render(800, 600, 0.0, 0.0)
    tx, ty = r.blits[0][1]
    # Tooltip is 362 wide and the tab anchor is near x=100; centering pushes
    # it off the left edge, and y has no room above so it flips below and
    # clamps. Anchor rect = (100-7, 60-14, 14, 14) = (93, 46, 14, 14).
    assert tx == 0
    assert ty == 46 + 14 + 4


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
    seq = types.SimpleNamespace(speeds_for=lambda tag: [1.0, 2.0, 3.0], current_step_index=lambda: 1)
    # No marker entry -> no intensity inputs; the chart renders uncolored.
    markers = types.SimpleNamespace(get=lambda key, default: default)
    cue = types.SimpleNamespace(current_file="v.ogv", video_sequence=seq, markers=markers)
    monkeypatch.setattr(_displ, "_cue", cue)
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (500, 500))
    return types.SimpleNamespace(cue=cue, seq=seq, chart=CueAutoSpeedChart())


@pytest.fixture
def intensity_chart(monkeypatch):
    """Chart wired to a video whose pool is hooked to a 2-level group."""
    seq = types.SimpleNamespace(speeds_for=lambda tag: [1.0, 2.0, 3.0], current_step_index=lambda: 1)
    markers = types.SimpleNamespace(
        get=lambda key, default: {"pools": [{"igroup": {"name": "Impacts", "level": 1}}]},
        _resolve_video_pools=lambda entry: entry.get("pools", []),
    )
    speed_resolver = types.SimpleNamespace(banding_speeds=lambda tag: [0.7, 1.0, 1.3], get_current_speed=lambda: 1.3)

    def _flags(entry):
        return types.SimpleNamespace(enabled=True, sfx_levels=True, volume=True, frequency=True)

    def _current_level(pool_hooks, speed, variants, flags=None):
        # 2 levels: the slowest variant is L1, everything else L2.
        return (1, 2) if speed < 0.85 else (2, 2)

    intensity = types.SimpleNamespace(flags_from_entry=_flags, current_level=_current_level)
    cue = types.SimpleNamespace(
        current_file="v.ogv", video_sequence=seq, markers=markers, speed_resolver=speed_resolver, intensity=intensity
    )
    monkeypatch.setattr(_displ, "_cue", cue)
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (500, 500))
    return types.SimpleNamespace(cue=cue, chart=CueAutoSpeedChart())


def _capture_txt(monkeypatch):
    """Record the text of every Txt() the chart creates during a render."""
    texts = []
    real_txt = _displ.Txt

    def _recording_txt(text, *args, **kwargs):
        texts.append(text)
        return real_txt(text, *args, **kwargs)

    monkeypatch.setattr(_displ, "Txt", _recording_txt)
    return texts


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
    assert circles == [("circle", chart.chart.COLOR_DOT, (113, 45), chart.chart.DOT_R)]
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
# _cue_intensity_color -- level -> hex along the HSL hue path
# ==========================================================================


def test_intensity_color_endpoints():
    assert _cue_intensity_color(1, 3) == CUE_INTENSITY_COLOR_LOW
    assert _cue_intensity_color(3, 3) == CUE_INTENSITY_COLOR_HIGH
    assert _cue_intensity_color(1, 1) == CUE_INTENSITY_COLOR_HIGH


def test_intensity_color_clamps_out_of_range():
    assert _cue_intensity_color(0, 3) == CUE_INTENSITY_COLOR_LOW
    assert _cue_intensity_color(9, 3) == CUE_INTENSITY_COLOR_HIGH


def test_intensity_color_midpoint_is_hex():
    mid = _cue_intensity_color(2, 3)
    assert mid != CUE_INTENSITY_COLOR_LOW
    assert mid != CUE_INTENSITY_COLOR_HIGH
    assert len(mid) == 7 and mid.startswith("#")


# ==========================================================================
# CueAutoSpeedChart -- intensity coloring + level labels
# ==========================================================================


def test_chart_render_intensity_colors_bright_line(intensity_chart):
    r = intensity_chart.chart.render(200, 100, 0.0, 0.0)
    lines = [op for op in r.canvas().ops if op[0] == "line"]
    dim = [op for op in lines if op[1] == CueAutoSpeedChart.COLOR_DIM]
    bright = [op for op in lines if op[1] != CueAutoSpeedChart.COLOR_DIM]
    assert len(dim) == 2
    # Played portion uses the level color (current speed 1.3 -> L2 of 2 -> high).
    assert bright and all(op[1] == _cue_intensity_color(2, 2) for op in bright)


def test_chart_render_intensity_per_segment_colors(monkeypatch, intensity_chart):
    # Each played segment keeps its own step's level color instead of one
    # uniform color -- earlier segments persist as the playhead advances.
    intensity_chart.cue.video_sequence = types.SimpleNamespace(
        speeds_for=lambda tag: [0.7, 1.0, 1.3], current_step_index=lambda: 2
    )
    r = intensity_chart.chart.render(200, 100, 0.0, 0.0)
    bright = [op for op in r.canvas().ops if op[0] == "line" and op[1] != CueAutoSpeedChart.COLOR_DIM]
    # Segment 0 (0.7 -> L1) is low; segment 1 (1.0 -> L2) is high.
    assert [op[1] for op in bright] == [_cue_intensity_color(1, 2), _cue_intensity_color(2, 2)]


def test_chart_render_intensity_label(monkeypatch, intensity_chart):
    texts = _capture_txt(monkeypatch)
    intensity_chart.chart.render(200, 100, 0.0, 0.0)
    assert "2.0x (lvl 2)" in texts


def test_chart_render_intensity_tooltip(monkeypatch, intensity_chart):
    monkeypatch.setattr(_renpy, "get_mouse_pos", lambda: (35, 82))
    texts = _capture_txt(monkeypatch)
    intensity_chart.chart.render(200, 100, 0.0, 0.0)
    # Hovered step 1 (speed 1.0 -> L2); tooltip appends the level.
    assert any("step 1/3" in t and "(lvl 2)" in t for t in texts)


def test_chart_render_no_intensity_keeps_white(chart):
    # The non-intensity chart's played portion stays COLOR_BRIGHT.
    r = chart.chart.render(200, 100, 0.0, 0.0)
    bright = [op for op in r.canvas().ops if op[0] == "line" and op[1] == CueAutoSpeedChart.COLOR_BRIGHT]
    assert bright


# ==========================================================================
# CueKeyCaptureDisplayable
# ==========================================================================


def test_key_capture_render():
    r = CueKeyCaptureDisplayable().render(800, 600, 0.0, 0.0)
    assert (r.width, r.height) == (0, 0)


def test_key_capture_ignores_non_keydown(monkeypatch):
    calls = []
    monkeypatch.setattr(
        _displ, "_cue", types.SimpleNamespace(keybinds=types.SimpleNamespace(on_captured=lambda k: calls.append(k)))
    )
    ev = types.SimpleNamespace(type=_pygame.MOUSEBUTTONDOWN, key=_pygame.K_F5, mod=0)
    assert CueKeyCaptureDisplayable().event(ev, 0, 0, 0.0) is None
    assert calls == []


def test_key_capture_forwards_keysym(monkeypatch):
    calls = []
    monkeypatch.setattr(
        _displ, "_cue", types.SimpleNamespace(keybinds=types.SimpleNamespace(on_captured=lambda k: calls.append(k)))
    )
    kc = CueKeyCaptureDisplayable()
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=_pygame.K_F5, mod=0)
    with pytest.raises(IgnoreEvent):
        kc.event(ev, 0, 0, 0.0)
    assert calls == ["K_F5"]


def test_key_capture_unmapped_key_no_forward(monkeypatch):
    calls = []
    monkeypatch.setattr(
        _displ, "_cue", types.SimpleNamespace(keybinds=types.SimpleNamespace(on_captured=lambda k: calls.append(k)))
    )
    kc = CueKeyCaptureDisplayable()
    ev = types.SimpleNamespace(type=_pygame.KEYDOWN, key=999, mod=0)
    with pytest.raises(IgnoreEvent):
        kc.event(ev, 0, 0, 0.0)
    assert calls == []


def test_setup_mouse_cursor_synthesizes_default_without_theme(monkeypatch):
    # A game with no mouse theme leaves config.mouse None. Making it
    # non-empty switches 7.x off the OS cursor, so a "default" entry is
    # mandatory (7.2.2 get_mouse_info KeyErrors otherwise); synthesize one
    # from the bundled arrow instead of dropping the mod's cursors.
    monkeypatch.setattr(_displ, "_cue", types.SimpleNamespace(paths=types.SimpleNamespace(icon=lambda n: "icons/" + n)))
    monkeypatch.setattr(_renpy.config, "mouse", None, raising=False)
    _displ._cue_setup_mouse_cursor()
    mouse = _renpy.config.mouse
    assert mouse["default"][0][0] == "icons/arrow-pointer-solid.png"
    assert mouse["cue_resize"][0][0] == "icons/arrows-left-right-solid.png"
    assert mouse["cue_pointer"][0][0] == "icons/hand-pointer-solid.png"


def test_setup_mouse_cursor_synthesizes_default_theme_without_default(monkeypatch):
    monkeypatch.setattr(_displ, "_cue", types.SimpleNamespace(paths=types.SimpleNamespace(icon=lambda n: "icons/" + n)))
    base = {"only_custom": [("custom.png", 0, 0)]}
    monkeypatch.setattr(_renpy.config, "mouse", dict(base), raising=False)
    _displ._cue_setup_mouse_cursor()
    mouse = _renpy.config.mouse
    assert mouse["only_custom"] == base["only_custom"]
    assert mouse["default"][0][0] == "icons/arrow-pointer-solid.png"


def test_setup_mouse_cursor_adds_cue_cursors(monkeypatch):
    monkeypatch.setattr(_displ, "_cue", types.SimpleNamespace(paths=types.SimpleNamespace(icon=lambda n: "icons/" + n)))
    base = {"default": [("arrow.png", 0, 0)], "wait": [("wait.png", 0, 0)]}
    monkeypatch.setattr(_renpy.config, "mouse", dict(base), raising=False)
    _displ._cue_setup_mouse_cursor()
    mouse = _renpy.config.mouse
    assert mouse["default"] == base["default"]
    assert mouse["cue_resize"][0][0] == "icons/arrows-left-right-solid.png"
    assert mouse["cue_pointer"][0][0] == "icons/hand-pointer-solid.png"
    # Function copies before mutating; original dict is untouched.
    assert "cue_resize" not in base
