# -*- coding: utf-8 -*-
# Tests for cue_lib.volume -- CueVolumeManager master/target volume math.
#
# The manager is data-pure: it reads/writes marker entries through the store
# (FakeMarkerStore: get/save_marker/resolve_pool), and pokes
# renpy.restart_interaction (mocked no-op) after writes.

import pytest

from cue_lib.volume import CueVolumeManager
from cue_lib.state import CueContext
from cue_lib.constants import CUE_VOLUME_DEFAULT

from tests.fakes import FakeMarkerStore


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
    return CueVolumeManager(ctx, store)


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
    assert store._data["k"]["volume"] == 3.0


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
    assert store._data["k"]["volume"] == 3.0


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
    assert vol.get_effective(entry, pool_index=0) == 3.0


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
# marker_queue_save / flush_pending_saves -- deferred save queue
# ---------------------------------------------------------------------------


def test_flush_saves_queued_keys_once(store, ctx):
    injected = CueVolumeManager(ctx, store)
    injected.marker_queue_save("a")
    injected.marker_queue_save("b")
    injected.flush_pending_saves()
    assert sorted(store.saved_keys) == ["a", "b"]
    assert injected._pending_saves == set()


def test_flush_empty_queue_is_noop(store, ctx):
    injected = CueVolumeManager(ctx, store)
    injected.flush_pending_saves()
    assert store.saved_keys == []


def test_requeue_before_flush_dedupes(store, ctx):
    injected = CueVolumeManager(ctx, store)
    injected.marker_queue_save("a")
    injected.marker_queue_save("a")
    injected.flush_pending_saves()
    assert store.saved_keys == ["a"]
