# -*- coding: utf-8 -*-
# Tests for cue_lib.preset_store.CuePresetStore -- the audio + video preset
# data leaf split out of CueMarkerStore.

import pytest

from cue_lib.constants import CUE_VOLUME_DEFAULT, CueLoopFrequency
from cue_lib.preset_store import CuePresetStore


@pytest.fixture
def presets(cue_env):
    """A preset store on a fresh temp DB, with a no-op on_save."""
    return CuePresetStore(cue_env.db, lambda: None)


# ---------------------------------------------------------------------------
# Audio preset CRUD
# ---------------------------------------------------------------------------


def test_preset_crud_round_trip(presets):
    presets.audio.create("Growl", {"files": ["a.ogg"], "volume": 0.8})
    assert presets.audio.get("Growl")["files"] == ["a.ogg"]
    assert presets.audio.list() == ["Growl"]
    presets.audio.delete("Growl")
    assert presets.audio.get("Growl") is None
    assert presets.audio.list() == []


def test_create_preset_deepcopies_input(presets):
    pool = {"files": ["a.ogg"]}
    presets.audio.create("G", pool)
    pool["files"].append("b.ogg")
    assert presets.audio.get("G")["files"] == ["a.ogg"]


def test_preset_remove_file_direct(presets):
    presets.audio.create("G", {"files": ["a.ogg", "b.ogg"]})
    presets.audio.preset_remove_file("G", "a.ogg")
    assert presets.audio.get("G")["files"] == ["b.ogg"]


def test_preset_remove_file_folder_child(monkeypatch, presets):
    # A child under a covering folder ref expands the ref to its remaining
    # children.  The lazy _cue_resolve_files seam is wired to a fake library.
    from types import SimpleNamespace

    from cue_lib.state import _cue

    monkeypatch.setattr(
        _cue, "sfx", SimpleNamespace(library=SimpleNamespace(files=["b/one.ogg", "b/two.ogg"], disabled_files=set()))
    )
    presets.audio.create("G", {"files": ["a.ogg", "b/"]})
    presets.audio.preset_remove_file("G", "b/two.ogg")
    assert presets.audio.get("G")["files"] == ["a.ogg", "b/one.ogg"]


def test_preset_remove_file_missing_preset_noop(presets):
    presets.audio.preset_remove_file("ghost", "a.ogg")  # must not raise


def test_preset_remove_file_absent_path_leaves_untouched(presets, monkeypatch):
    from types import SimpleNamespace

    from cue_lib.state import _cue

    monkeypatch.setattr(_cue, "sfx", SimpleNamespace(library=SimpleNamespace(files=[], disabled_files=set())))
    presets.audio.create("G", {"files": ["a.ogg"]})
    presets.audio.preset_remove_file("G", "zzz.ogg")
    assert presets.audio.get("G")["files"] == ["a.ogg"]


# ---------------------------------------------------------------------------
# Video preset CRUD
# ---------------------------------------------------------------------------


def test_video_preset_crud_round_trip(presets):
    entry = {"pools": [{"time": 3.0, "files": ["b.mp4"]}, {"time": 1.0, "files": ["a.mp4"]}], "volume": 0.5}
    presets.video.create("VP", entry, source_dur=10.0)
    preset = presets.video.get("VP")
    assert preset["pools"] == [
        {"time": 1.0, "files": ["a.mp4"], "volume": CUE_VOLUME_DEFAULT},
        {"time": 3.0, "files": ["b.mp4"], "volume": CUE_VOLUME_DEFAULT},
    ]
    assert preset["volume"] == 0.5
    assert preset["source_duration"] == 10.0
    assert presets.video.list() == ["VP"]
    presets.video.delete("VP")
    assert presets.video.get("VP") is None


def test_create_video_preset_skips_time_less_pools(presets):
    entry = {"pools": [{"time": 1.0}, {"no_time": True}, {"time": 3.0}]}
    presets.video.create("VP", entry)
    assert presets.video.get("VP")["pools"] == [
        {"time": 1.0, "files": [], "volume": CUE_VOLUME_DEFAULT},
        {"time": 3.0, "files": [], "volume": CUE_VOLUME_DEFAULT},
    ]


def test_create_video_preset_no_pools_returns(presets):
    presets.video.create("VP", {"pools": []})
    assert presets.video.get("VP") is None


def test_create_video_preset_all_time_less_pools_returns(presets):
    presets.video.create("VP", {"pools": [{"files": ["a.ogg"]}, {"files": ["b.ogg"]}]})
    assert presets.video.get("VP") is None


def test_remove_video_preset_pool(presets):
    presets.video.create("VP", {"pools": [{"time": 1.0}, {"time": 2.0}]})
    presets.video.remove_video_preset_pool("VP", 0)
    assert [p["time"] for p in presets.video.get("VP")["pools"]] == [2.0]
    presets.video.remove_video_preset_pool("VP", 0)
    # Last pool removed -> the preset is deleted.
    assert presets.video.get("VP") is None


def test_remove_video_preset_pool_bad_index_noop(presets):
    presets.video.create("VP", {"pools": [{"time": 1.0}]})
    presets.video.remove_video_preset_pool("VP", 5)
    assert len(presets.video.get("VP")["pools"]) == 1


def test_remove_video_preset_pool_file(monkeypatch, presets):
    from types import SimpleNamespace

    from cue_lib.state import _cue

    monkeypatch.setattr(
        _cue, "sfx", SimpleNamespace(library=SimpleNamespace(files=["b/one.ogg", "b/two.ogg"], disabled_files=set()))
    )
    presets.video.create("VP", {"pools": [{"time": 1.0, "files": ["b/"]}, {"time": 2.0, "files": ["c.ogg"]}]})
    presets.video.remove_video_preset_pool_file("VP", 0, "b/two.ogg")
    assert presets.video.get("VP")["pools"][0]["files"] == ["b/one.ogg"]


def test_remove_video_preset_pool_file_direct(presets):
    presets.video.create("VP", {"pools": [{"time": 1.0, "files": ["a.ogg", "b.ogg"]}]})
    presets.video.remove_video_preset_pool_file("VP", 0, "a.ogg")
    assert presets.video.get("VP")["pools"][0]["files"] == ["b.ogg"]


# ---------------------------------------------------------------------------
# Sanitize / migration passes
# ---------------------------------------------------------------------------


def test_sanitize_video_presets_strips_time_less(presets):
    presets.video._presets["VP"] = {"pools": [{"time": 1.0}, {"no_time": True}]}
    assert presets.video._sanitize_video_presets() == 1
    assert presets.video._presets["VP"]["pools"] == [{"time": 1.0}]


def test_sanitize_video_presets_skips_preset_without_pools(presets):
    presets.video._presets["VP"] = {}
    presets.video._presets["V2"] = {"pools": [{"time": 1.0}]}
    assert presets.video._sanitize_video_presets() == 0


def test_migrate_preset_speed_mode_rename(presets):
    presets.video._presets["VP"] = {"speed_mode": "sequence"}
    presets.video._migrate_preset_speed_mode_rename()
    assert presets.video._presets["VP"]["speed_mode"] == "multi"


def test_migrate_video_presets_to_pools(presets):
    presets.video._presets["VP"] = {"timestamps": [{"time": 3.0}]}
    assert presets.video._migrate_video_presets_to_pools() == 1
    assert presets.video._presets["VP"]["pools"] == [{"time": 3.0}]
    assert "timestamps" not in presets.video._presets["VP"]


def test_migrate_video_presets_keeps_pools(presets):
    presets.video._presets["VP"] = {"pools": [{"time": 1.0}], "timestamps": [{"time": 9.0}]}
    assert presets.video._migrate_video_presets_to_pools() == 1
    assert "timestamps" not in presets.video._presets["VP"]


def test_migrate_preset_exclusive(presets):
    presets.audio._presets["P"] = {"exclusive": True}
    assert presets.audio._migrate_preset_exclusive() == 1
    assert presets.audio._presets["P"]["exclusive"]["group"] == 1


# ---------------------------------------------------------------------------
# Persistence round-trips (against a real CueDatabase)
# ---------------------------------------------------------------------------


def test_save_all_and_load_round_trip(presets, cue_env):
    presets.audio._presets["G"] = {"files": ["a.ogg"]}
    presets.video._presets["VP"] = {"pools": [{"time": 1.0}]}
    presets.save_all()

    fresh = CuePresetStore(cue_env.db, lambda: None)
    fresh.load()
    assert fresh.audio._presets["G"]["files"] == ["a.ogg"]
    assert fresh.video._presets["VP"]["pools"] == [{"time": 1.0}]


def test_load_runs_preset_migrations(presets, cue_env):
    presets.video._presets["VP"] = {"timestamps": [{"time": 3.0}], "speed_mode": "sequence"}
    presets.save_all()

    fresh = CuePresetStore(cue_env.db, lambda: None)
    fresh.load()
    assert fresh.video._presets["VP"]["pools"] == [{"time": 3.0}]
    assert fresh.video._presets["VP"]["speed_mode"] == "multi"


def test_reload_presets_merges_disk(presets, cue_env):
    other = CuePresetStore(cue_env.db, lambda: None)
    other.audio.create("Disk", {"files": ["d.ogg"]})

    presets.reload_presets()
    assert presets.audio.get("Disk") is not None


def test_reload_presets_no_db_returns(cue_env):
    s = CuePresetStore(None)
    s.reload_presets()  # must not raise


def test_delete_removed_files_preset_only_when_session_created(presets, cue_env):
    presets.audio.create("Sess", {"files": ["a.ogg"]})
    presets.audio.create("Old", {"files": ["b.ogg"]})
    presets._session_created = {("audio", "Sess")}
    old_presets = {"Sess": {"files": ["a.ogg"]}, "Old": {"files": ["b.ogg"]}}
    presets.audio._presets = {}  # restore drops both
    presets.delete_removed_files(old_presets, {}, {("audio", "Sess")})

    fresh = CuePresetStore(cue_env.db, lambda: None)
    fresh.load()
    assert "Sess" not in fresh.audio._presets
    assert "Old" in fresh.audio._presets


def test_delete_removed_files_keeps_present_preset(presets):
    presets.audio._presets["P"] = {"files": ["a.ogg"]}
    presets.delete_removed_files({"P": {"files": ["a.ogg"]}}, {}, set())
    assert "P" in presets.audio._presets


def test_delete_removed_files_keeps_present_video_preset(presets):
    presets.video._presets["VP"] = {"pools": [{"time": 1.0}]}
    presets.delete_removed_files({}, {"VP": {"pools": [{"time": 1.0}]}}, set())
    assert "VP" in presets.video._presets


def test_delete_removed_files_deletes_session_video_preset(presets, cue_env):
    presets.video.create("VP", {"pools": [{"time": 1.0}]})
    old_video_presets = {"VP": presets.video._presets["VP"]}
    presets.video._presets = {}
    presets.delete_removed_files({}, old_video_presets, {("video", "VP")})

    fresh = CuePresetStore(cue_env.db, lambda: None)
    fresh.load()
    assert "VP" not in fresh.video._presets


def test_delete_removed_files_no_db_returns(cue_env):
    s = CuePresetStore(None)
    s.delete_removed_files({}, {}, set())  # must not raise


def test_load_no_db_resets(cue_env):
    s = CuePresetStore(None)
    s.load()
    assert s.audio._presets == {}
    assert s.video._presets == {}


# ---------------------------------------------------------------------------
# on_save hook
# ---------------------------------------------------------------------------


def test_post_save_invokes_on_save(cue_env):
    calls = []
    s = CuePresetStore(cue_env.db, lambda: calls.append(1))
    s.audio._presets["p1"] = {"files": ["a.ogg"], "volume": 0.5}
    s.audio.save("p1")
    s.audio._db_save("p1")
    assert len(calls) == 2


def test_save_all_invokes_on_save_once(cue_env):
    calls = []
    s = CuePresetStore(cue_env.db, lambda: calls.append(1))
    s.audio._presets["G"] = {"files": ["a.ogg"]}
    s.video._presets["VP"] = {"pools": [{"time": 1.0}]}
    s.save_all()
    assert len(calls) == 1
