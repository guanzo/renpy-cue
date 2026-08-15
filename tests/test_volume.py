# -*- coding: utf-8 -*-
# Tests for cue_lib.volume -- CueVolumeManager master/target volume math.
#
# The manager is data-pure: it reads/writes marker entries through the store
# (FakeMarkerStore: get/save_marker/resolve_pool), touches only ctx.current_file
# for the video key, and pokes renpy.restart_interaction (mocked no-op) after
# writes.  adjust_video's active-pool read goes through an injected markers
# seam so the singleton is never needed.

import pytest

from cue_lib.volume import CueVolumeManager
from cue_lib.state import _cue, CueContext
from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.util import create_vid_key

from tests.fakes import FakeMarkerStore, FakeMarkers


def make_entry(volume=None, pools=None):
    # type: (object, object) -> dict
    entry = {}
    if volume is not None:
        entry["volume"] = volume
    if pools is not None:
        entry["pools"] = pools
    return entry


@pytest.fixture
def store():
    return FakeMarkerStore()


@pytest.fixture
def ctx():
    return CueContext()


@pytest.fixture
def vol(store, ctx):
    return CueVolumeManager(store, ctx)


# ---------------------------------------------------------------------------
# get -- raw stored volume for entry or pool target
# ---------------------------------------------------------------------------

def test_get_none_entry_returns_default(vol):
    assert vol.get(None) == CUE_VOLUME_DEFAULT


def test_get_entry_default_volume(vol):
    assert vol.get(make_entry()) == CUE_VOLUME_DEFAULT


def test_get_entry_volume(vol):
    assert vol.get(make_entry(volume=0.8)) == 0.8


def test_get_pool_volume(vol):
    entry = make_entry(volume=2.0, pools=[{"volume": 0.5}])
    assert vol.get(entry, pool_index=0) == 0.5


def test_get_pool_out_of_range_falls_back_to_first(vol):
    entry = make_entry(volume=2.0, pools=[{"volume": 0.5}])
    assert vol.get(entry, pool_index=5) == 0.5


def test_get_pool_index_without_pools_uses_entry(vol):
    entry = make_entry(volume=0.7)
    assert vol.get(entry, pool_index=0) == 0.7


def test_get_pool_uses_resolved_volume(vol):
    # resolve_pool returns the pool's stored volume (fake echoes it).
    entry = make_entry(pools=[{"volume": 1.25}])
    assert vol.get(entry, pool_index=0) == 1.25


# ---------------------------------------------------------------------------
# write -- clamp + persist at entry or pool level
# ---------------------------------------------------------------------------

def test_write_entry_level(vol, store):
    store._data["k"] = make_entry()
    vol.write("k", 0.5)
    assert store._data["k"]["volume"] == 0.5
    assert store.saved_keys == ["k"]


def test_write_clamps_high(vol, store):
    store._data["k"] = make_entry()
    vol.write("k", 9.9)
    assert store._data["k"]["volume"] == 5.0


def test_write_clamps_low(vol, store):
    store._data["k"] = make_entry()
    vol.write("k", -3.0)
    assert store._data["k"]["volume"] == 0.0


def test_write_rounds_to_one_decimal(vol, store):
    store._data["k"] = make_entry()
    vol.write("k", 1.27)
    assert store._data["k"]["volume"] == 1.3


def test_write_pool_level(vol, store):
    store._data["k"] = make_entry(pools=[{"volume": 1.0}])
    vol.write("k", 0.4, pool_index=0)
    assert store._data["k"]["pools"][0]["volume"] == 0.4
    assert store.saved_keys == ["k"]


def test_write_missing_entry_is_noop(vol, store):
    vol.write("nope", 0.5)
    assert store.saved_keys == []


# ---------------------------------------------------------------------------
# adjust -- get current then write current + delta
# ---------------------------------------------------------------------------

def test_adjust_entry(vol, store):
    store._data["k"] = make_entry(volume=1.0)
    vol.adjust("k", 0.5)
    assert store._data["k"]["volume"] == 1.5


def test_adjust_negative(vol, store):
    store._data["k"] = make_entry(volume=1.0)
    vol.adjust("k", -0.3)
    assert store._data["k"]["volume"] == 0.7


def test_adjust_clamps_at_max(vol, store):
    store._data["k"] = make_entry(volume=4.8)
    vol.adjust("k", 0.5)
    assert store._data["k"]["volume"] == 5.0


def test_adjust_clamps_at_min(vol, store):
    store._data["k"] = make_entry(volume=0.2)
    vol.adjust("k", -0.5)
    assert store._data["k"]["volume"] == 0.0


def test_adjust_pool(vol, store):
    store._data["k"] = make_entry(volume=2.0, pools=[{"volume": 1.0}])
    vol.adjust("k", 0.3, pool_index=0)
    assert store._data["k"]["pools"][0]["volume"] == 1.3


def test_adjust_missing_entry_is_noop(vol, store):
    vol.adjust("nope", 0.5)
    assert store.saved_keys == []


# ---------------------------------------------------------------------------
# get_master / set_master / adjust_master
# ---------------------------------------------------------------------------

def test_get_master_default(vol, store):
    assert vol.get_master("k") == CUE_VOLUME_DEFAULT


def test_get_master_reads_entry(vol, store):
    store._data["k"] = make_entry(volume=0.8)
    assert vol.get_master("k") == 0.8


def test_set_master(vol, store):
    store._data["k"] = make_entry()
    vol.set_master("k", 0.6)
    assert store._data["k"]["volume"] == 0.6
    assert store.saved_keys == ["k"]


def test_set_master_clamps(vol, store):
    store._data["k"] = make_entry()
    vol.set_master("k", 7.0)
    assert store._data["k"]["volume"] == 5.0


def test_set_master_missing_entry_is_noop(vol, store):
    vol.set_master("nope", 0.5)
    assert store.saved_keys == []


def test_adjust_master(vol, store):
    store._data["k"] = make_entry(volume=1.0)
    vol.adjust_master("k", -0.3)
    assert store._data["k"]["volume"] == 0.7


# ---------------------------------------------------------------------------
# get_effective -- master x target, clamped
# ---------------------------------------------------------------------------

def test_effective_none_entry_returns_default(vol):
    assert vol.get_effective(None) == CUE_VOLUME_DEFAULT


def test_effective_entry_only_is_master(vol):
    assert vol.get_effective(make_entry(volume=0.8)) == 0.8


def test_effective_pool_multiplies_master(vol):
    entry = make_entry(volume=2.0, pools=[{"volume": 0.5}])
    assert vol.get_effective(entry, pool_index=0) == 1.0


def test_effective_pool_default_volume_is_identity(vol):
    # pool with no volume key resolves to 1.0 -- master not double-counted.
    entry = make_entry(volume=0.8, pools=[{}])
    assert vol.get_effective(entry, pool_index=0) == 0.8


def test_effective_clamps_product_at_max(vol):
    entry = make_entry(volume=5.0, pools=[{"volume": 5.0}])
    assert vol.get_effective(entry, pool_index=0) == 5.0


def test_effective_pool_out_of_range_falls_back(vol):
    entry = make_entry(volume=2.0, pools=[{"volume": 0.5}])
    assert vol.get_effective(entry, pool_index=9) == 1.0


def test_effective_no_pools_returns_master(vol):
    entry = make_entry(volume=0.8)
    assert vol.get_effective(entry, pool_index=0) == 0.8


def test_effective_negative_clamps_at_min(vol):
    entry = make_entry(volume=-2.0, pools=[{"volume": 3.0}])
    assert vol.get_effective(entry, pool_index=0) == 0.0


# ---------------------------------------------------------------------------
# adjust_video -- active video pool via injected markers seam
# ---------------------------------------------------------------------------

def test_adjust_video_writes_active_pool(vol, store, ctx):
    ctx.current_file = "scene.ogv"
    key = create_vid_key("scene.ogv")
    store._data[key] = make_entry(volume=2.0, pools=[{"volume": 1.0}])
    injected = CueVolumeManager(store, ctx, markers=FakeMarkers(target_pool=0))
    injected.adjust_video(0.5)
    assert store._data[key]["pools"][0]["volume"] == 1.5
    assert store.saved_keys == [key]


def test_adjust_video_uses_injected_target_pool(vol, store, ctx):
    ctx.current_file = "scene.ogv"
    key = create_vid_key("scene.ogv")
    store._data[key] = make_entry(
        volume=2.0, pools=[{"volume": 1.0}, {"volume": 1.0}])
    injected = CueVolumeManager(store, ctx, markers=FakeMarkers(target_pool=1))
    injected.adjust_video(0.4)
    assert store._data[key]["pools"][0]["volume"] == 1.0  # untouched
    assert store._data[key]["pools"][1]["volume"] == 1.4


def test_adjust_video_missing_entry_is_noop(vol, ctx):
    ctx.current_file = "nope.ogv"
    vol.adjust_video(0.5)
    assert vol._store.saved_keys == []


def test_adjust_video_falls_back_to_singleton_markers(store, ctx, monkeypatch):
    ctx.current_file = "scene.ogv"
    key = create_vid_key("scene.ogv")
    store._data[key] = make_entry(volume=2.0, pools=[{"volume": 1.0}])
    monkeypatch.setattr(_cue, "markers", FakeMarkers(target_pool=0))
    CueVolumeManager(store, ctx).adjust_video(0.5)
    assert store._data[key]["pools"][0]["volume"] == 1.5
