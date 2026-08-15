# -*- coding: utf-8 -*-
# Tests for cue_lib.recent -- CueRecentManager, the most-recently-used
# pool-items tracker (files / folders / presets added to a pool).

import pytest

from renpy.store import persistent

from cue_lib.constants import CUE_RECENT_MAX, CueRecentKind
from cue_lib.recent import CueRecentManager


@pytest.fixture(autouse=True)
def _clean_persistent(monkeypatch):
    """Fresh persistent._cue_recent_pool_items for every test in this
    module (shared-state cleanup, same shape as test_video_editor.py)."""
    monkeypatch.setattr(persistent, "_cue_recent_pool_items", None, raising=False)


def test_touch_inserts_most_recent_first():
    mgr = CueRecentManager()

    mgr.touch(CueRecentKind.FILE, "a.wav")
    mgr.touch(CueRecentKind.FOLDER, "sub/")
    mgr.touch(CueRecentKind.PRESET, "boom")

    assert mgr.items() == [
        {"kind": "preset", "value": "boom"},
        {"kind": "folder", "value": "sub/"},
        {"kind": "file", "value": "a.wav"},
    ]


def test_touch_dedupes_and_moves_to_front():
    mgr = CueRecentManager()

    mgr.touch(CueRecentKind.FILE, "a.wav")
    mgr.touch(CueRecentKind.FILE, "b.wav")
    mgr.touch(CueRecentKind.FILE, "a.wav")

    assert mgr.items() == [
        {"kind": "file", "value": "a.wav"},
        {"kind": "file", "value": "b.wav"},
    ]


def test_cap_at_max_drops_oldest():
    mgr = CueRecentManager()

    for i in range(CUE_RECENT_MAX + 2):
        mgr.touch(CueRecentKind.FILE, "f%d.wav" % i)

    items = mgr.items()
    assert len(items) == CUE_RECENT_MAX
    assert items[0]["value"] == "f%d.wav" % (CUE_RECENT_MAX + 1)
    assert all(e["value"] != "f0.wav" for e in items)
    assert all(e["value"] != "f1.wav" for e in items)


def test_empty_value_ignored():
    mgr = CueRecentManager()

    mgr.touch(CueRecentKind.FILE, "")

    assert mgr.items() == []


def test_kinds_are_distinct_for_same_value():
    mgr = CueRecentManager()

    mgr.touch(CueRecentKind.FILE, "boom.wav")
    mgr.touch(CueRecentKind.PRESET, "boom.wav")
    mgr.touch(CueRecentKind.FOLDER, "boom/")

    assert mgr.items() == [
        {"kind": "folder", "value": "boom/"},
        {"kind": "preset", "value": "boom.wav"},
        {"kind": "file", "value": "boom.wav"},
    ]


def test_persistence_round_trip():
    mgr = CueRecentManager()

    mgr.touch(CueRecentKind.FILE, "a.wav")
    mgr.touch(CueRecentKind.PRESET, "boom")

    assert persistent._cue_recent_pool_items == mgr.items()

    fresh = CueRecentManager()
    fresh.load()
    assert fresh.items() == mgr.items()
