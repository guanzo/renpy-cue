# -*- coding: utf-8 -*-
# Tests for cue_lib.pool -- ephemeral pool-row views with per-mode dispatch.
#
# A view wraps one pool row; the mode (concrete / preset-linked / igroup-
# hooked) decides which op set runs.  Views are ephemeral: each op re-resolves
# the row from the live dict, and one view is valid for one operation (a prune
# can pop the row out from under it).
#
# The store is a real CueMarkerStore on a temp DB (same shape as
# test_marker_store); folder expansion patches _cue.sfx.library like
# test_preset_store does.

from types import SimpleNamespace

import pytest

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.marker_store import CueMarkerStore
from cue_lib.pool import CueAudioPreset, CuePool, CueVideoPresetPool
from cue_lib.state import _cue

KEY = "i_a"


@pytest.fixture
def store(cue_env):
    """A marker store on a fresh temp DB, with a no-op on_save."""
    return CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)


@pytest.fixture
def sfx_lib(monkeypatch):
    """Patch the _cue.sfx.library seam _cue_resolve_files reads."""
    lib = SimpleNamespace(files=["b/one.ogg", "b/two.ogg"], disabled_files=set())
    monkeypatch.setattr(_cue, "sfx", SimpleNamespace(library=lib))
    return lib


# ---------------------------------------------------------------------------
# Concrete mode
# ---------------------------------------------------------------------------


def test_add_file_appends_ref(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}]}
    assert store.pool(KEY, 0).add_file("b.ogg") is True
    assert store[KEY]["pools"][0]["files"] == ["a.ogg", "b.ogg"]


def test_add_file_dedupes(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}]}
    assert store.pool(KEY, 0).add_file("a.ogg") is True
    assert store[KEY]["pools"][0]["files"] == ["a.ogg"]


def test_add_file_creates_missing_entry_and_pool(store):
    store.pool(KEY, 0).add_file("f.ogg")
    assert store[KEY]["pools"] == [{"files": ["f.ogg"], "volume": CUE_VOLUME_DEFAULT}]


def test_remove_file_by_path(store):
    store[KEY] = {"pools": [{"files": ["a.ogg", "b.ogg"]}]}
    assert store.pool(KEY, 0).remove_file("a.ogg") is True
    assert store[KEY]["pools"][0]["files"] == ["b.ogg"]


def test_remove_file_absent_returns_false(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}]}
    assert store.pool(KEY, 0).remove_file("zzz.ogg") is False
    assert store[KEY]["pools"][0]["files"] == ["a.ogg"]


def test_remove_file_expands_folder_ref(store, sfx_lib):
    sfx_lib.files = ["b/one.ogg", "b/two.ogg", "c/three.ogg"]
    store[KEY] = {"pools": [{"files": ["b/"]}]}
    assert store.pool(KEY, 0).remove_file("b/one.ogg") is True
    assert store[KEY]["pools"][0]["files"] == ["b/two.ogg"]


def test_remove_file_prunes_row_and_entry(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}]}
    assert store.pool(KEY, 0).remove_file("a.ogg") is True
    assert KEY not in store


def test_remove_file_prunes_row_keeps_entry(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}, {"files": ["b.ogg"]}]}
    assert store.pool(KEY, 0).remove_file("a.ogg") is True
    assert store[KEY]["pools"] == [{"files": ["b.ogg"]}]


def test_remove_file_missing_row_returns_false(store):
    assert store.pool(KEY, 3).remove_file("a.ogg") is False


def test_clear_files_empties_pool(store):
    store[KEY] = {"pools": [{"files": ["a.ogg", "b.ogg"]}]}
    assert store.pool(KEY, 0).clear_files() is True
    assert store[KEY]["pools"] == [{"files": []}]


def test_clear_files_empty_returns_false(store):
    store[KEY] = {"pools": [{"files": []}]}
    assert store.pool(KEY, 0).clear_files() is False


# ---------------------------------------------------------------------------
# Preset-linked mode: auto-detach on edit
# ---------------------------------------------------------------------------


@pytest.fixture
def preset(store):
    store._preset_store._presets["boom"] = {"files": ["p.ogg"], "volume": 0.5, "frequency": 3}
    return store._preset_store._presets["boom"]


def test_add_file_detaches_preset_then_appends(store, preset):
    store[KEY] = {"pools": [{"preset": "boom"}]}
    assert store.pool(KEY, 0).add_file("n.ogg") is True
    pool = store[KEY]["pools"][0]
    assert "preset" not in pool
    assert pool["files"] == ["p.ogg", "n.ogg"]
    assert pool["volume"] == 0.5
    assert pool["frequency"] == 3


def test_remove_file_detaches_preset_then_removes(store, preset):
    store[KEY] = {"pools": [{"preset": "boom"}]}
    assert store.pool(KEY, 0).remove_file("p.ogg") is True
    # The preset's only file was dropped and the pool pruned the row + entry.
    assert KEY not in store


def test_clear_files_detaches_preset_then_clears(store, preset):
    store[KEY] = {"pools": [{"preset": "boom"}]}
    assert store.pool(KEY, 0).clear_files() is True
    pool = store[KEY]["pools"][0]
    assert "preset" not in pool
    assert pool["files"] == []
    assert pool["volume"] == 0.5


def test_detach_delegates_to_store(store, preset):
    store[KEY] = {"pools": [{"preset": "boom"}]}
    assert store.pool(KEY, 0).detach() is True
    pool = store[KEY]["pools"][0]
    assert "preset" not in pool
    assert pool["files"] == ["p.ogg"]


def test_detach_noop_on_concrete(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}]}
    assert store.pool(KEY, 0).detach() is False


# ---------------------------------------------------------------------------
# Igroup-hooked mode: read-only guard, clear drops the hook
# ---------------------------------------------------------------------------


def test_igroup_add_file_refuses(store):
    store[KEY] = {"pools": [{"files": [], "igroup": {"name": "g", "level": 2}}]}
    assert store.pool(KEY, 0).add_file("a.ogg") is False
    assert store[KEY]["pools"][0] == {"files": [], "igroup": {"name": "g", "level": 2}}


def test_igroup_remove_file_refuses(store):
    store[KEY] = {"pools": [{"files": [], "igroup": {"name": "g", "level": 2}}]}
    assert store.pool(KEY, 0).remove_file("a.ogg") is False
    assert "igroup" in store[KEY]["pools"][0]


def test_igroup_clear_files_drops_hook(store):
    store[KEY] = {"pools": [{"files": [], "igroup": {"name": "g", "level": 2}}]}
    assert store.pool(KEY, 0).clear_files() is True
    assert store[KEY]["pools"][0] == {"files": []}


# ---------------------------------------------------------------------------
# One-view-per-op contract
# ---------------------------------------------------------------------------


def test_pruned_view_no_longer_resolves(store):
    view = store.pool(KEY, 0)
    store[KEY] = {"pools": [{"files": ["a.ogg"]}]}
    assert view.remove_file("a.ogg") is True
    # A remove that pruned the row (and entry) invalidates the view.
    assert view._pool_dict() is None


def test_fresh_view_after_prune_resolves_next_row(store):
    store[KEY] = {"pools": [{"files": ["a.ogg"]}, {"files": ["b.ogg"]}]}
    store.pool(KEY, 0).remove_file("a.ogg")
    # A fresh view locates the surviving row at its new position.
    assert store.pool(KEY, 0)._pool_dict() == {"files": ["b.ogg"]}


# ---------------------------------------------------------------------------
# CueAudioPreset -- never prunes
# ---------------------------------------------------------------------------


def test_audio_view_add_file(store):
    store._preset_store.create_preset("boom", {"files": ["a.ogg"]})
    view = store._preset_store.audio("boom")
    assert isinstance(view, CueAudioPreset)
    assert view.add_file("b.ogg") is True
    assert store._preset_store._presets["boom"]["files"] == ["a.ogg", "b.ogg"]


def test_audio_view_remove_file_keeps_empty_preset(store):
    store._preset_store.create_preset("boom", {"files": ["a.ogg"]})
    assert store._preset_store.audio("boom").remove_file("a.ogg") is True
    assert store._preset_store._presets["boom"]["files"] == []


def test_audio_view_clear_files(store):
    store._preset_store.create_preset("boom", {"files": ["a.ogg"]})
    assert store._preset_store.audio("boom").clear_files() is True
    assert store._preset_store._presets["boom"]["files"] == []


def test_audio_view_add_missing_preset_returns_false(store):
    assert store._preset_store.audio("nope").add_file("a.ogg") is False


# ---------------------------------------------------------------------------
# CueVideoPresetPool -- keeps its time slot, never prunes the row
# ---------------------------------------------------------------------------


def test_video_pool_view_add_file(store):
    store._preset_store.create_video_preset("mv", {"pools": [{"time": 1.0, "files": ["a.mkv"]}]})
    view = store._preset_store.video_pool("mv", 0)
    assert isinstance(view, CueVideoPresetPool)
    assert view.add_file("b.mkv") is True
    assert store._preset_store._video_presets["mv"]["pools"][0]["files"] == ["a.mkv", "b.mkv"]


def test_video_pool_view_remove_file_keeps_row(store):
    store._preset_store.create_video_preset("mv", {"pools": [{"time": 1.0, "files": ["a.mkv"]}]})
    assert store._preset_store.video_pool("mv", 0).remove_file("a.mkv") is True
    pool = store._preset_store._video_presets["mv"]["pools"][0]
    assert pool["time"] == 1.0
    assert pool["files"] == []


def test_video_pool_view_clear_files(store):
    store._preset_store.create_video_preset("mv", {"pools": [{"time": 1.0, "files": ["a.mkv"]}]})
    assert store._preset_store.video_pool("mv", 0).clear_files() is True
    assert store._preset_store._video_presets["mv"]["pools"][0]["files"] == []


def test_video_pool_view_missing_row_returns_false(store):
    store._preset_store.create_video_preset("mv", {"pools": [{"time": 1.0, "files": ["a.mkv"]}]})
    assert store._preset_store.video_pool("mv", 3).remove_file("a.mkv") is False


def test_video_pool_view_missing_preset_returns_false(store):
    assert store._preset_store.video_pool("nope", 0).remove_file("a.mkv") is False
