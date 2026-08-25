# -*- coding: utf-8 -*-
# Tests for cue_lib.marker_store.CueMarkerStore -- the extracted marker data
# leaf behind CueMarkerManager.
#
# The store is constructed with a real CueDatabase + CuePaths (both already
# tested) plus an on_save callback, so the whole data/persistence layer runs
# headlessly with no _cue singleton.  This is the safety net the marker data
# layer lacked before the extraction: existing marker tests only exercised the
# context sub-objects through FakeManager.

import os

import pytest

from cue_lib.constants import CUE_VOLUME_DEFAULT, CueLoopFrequency
from cue_lib.intensity import CueIntensityResolution
from cue_lib.marker_store import CueMarkerStore, _cue_migrate_intensity_hooks


@pytest.fixture
def store(cue_env):
    """A store on a fresh temp DB, with a no-op on_save."""
    return CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)


# ---------------------------------------------------------------------------
# Dict-like surface
# ---------------------------------------------------------------------------


def test_dict_set_get_del(store):
    store["v_a"] = {"pools": []}
    assert "v_a" in store
    assert store["v_a"] == {"pools": []}
    del store["v_a"]
    assert "v_a" not in store


def test_dict_len_items_keys(store):
    store["v_a"] = {"pools": []}
    store["i_b"] = {"pools": [{"files": ["s.ogg"]}]}
    assert len(store) == 2
    assert set(store.keys()) == {"v_a", "i_b"}
    assert dict(store.items())["v_a"] == {"pools": []}


def test_get_missing_returns_default(store):
    assert store.get("v_nope") is None
    assert store.get("v_nope", "fallback") == "fallback"


def test_get_does_not_mutate_store(store):
    # A plain read must not rewrite the stored entry; legacy cleanup happens
    # on the load/create path, never on read.
    store._data["v_a"] = {"files": ["s.ogg"], "replay_id": "stale"}
    store.get("v_a")
    assert store._data["v_a"] == {"files": ["s.ogg"], "replay_id": "stale"}


def test_get_returns_normalized_entry(store):
    # Write-path creation normalizes legacy flat "files" into pools; get then
    # returns the live normalized entry without further mutation.
    store._data["v_a"] = {"files": ["s.ogg"]}
    store._get_or_create_entry("v_a")
    entry = store.get("v_a")
    assert entry["pools"] == [{"files": ["s.ogg"]}]
    assert store._data["v_a"]["pools"] == [{"files": ["s.ogg"]}]


def test_get_drops_replay_id_and_defaults_replay(store):
    # Legacy cleanup runs on the write path, not on read.
    store._data["v_a"] = {"pools": [], "replay_id": "stale"}
    store._get_or_create_entry("v_a")
    entry = store.get("v_a")
    assert "replay_id" not in entry
    assert entry["replay"] is False


def test_setdefault_and_pop(store):
    created = store.setdefault("v_a", {"pools": []})
    assert created == {"pools": [], "replay": False}
    assert store.setdefault("v_a", {"other": True}) == {"pools": [], "replay": False}
    assert store.pop("v_a") == {"pools": [], "replay": False}
    assert store.pop("v_a", "gone") == "gone"


# ---------------------------------------------------------------------------
# Entry / pool mutators
# ---------------------------------------------------------------------------


def test_get_or_create_entry_creates_and_reuses(store):
    entry = store._get_or_create_entry("i_a")
    # _normalize_entry defaults the "replay" flag in place.
    assert entry == {"pools": [], "replay": False}
    assert store._data["i_a"] is entry


def test_ensure_pool_creates_pool_with_default_volume(store):
    pool = store._ensure_pool("i_a", 0)
    assert pool == {"files": [], "volume": CUE_VOLUME_DEFAULT}


def test_ensure_pool_clamps_stale_index(store):
    store._data["i_a"] = {"pools": [{"files": ["s.ogg"]}]}
    assert store._ensure_pool("i_a", 99) == {"files": ["s.ogg"]}
    assert store._ensure_pool("i_a", -3) == {"files": ["s.ogg"]}


def test_add_file_to_pool_is_idempotent(cue_env):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: calls.append(1))
    s._add_file_to_pool("i_a", "s.ogg")
    s._add_file_to_pool("i_a", "s.ogg")
    assert s._data["i_a"]["pools"][0]["files"] == ["s.ogg"]
    assert len(calls) == 2  # one on_save per save


def test_remove_file_from_pool_prunes_empty(store):
    store._data["i_a"] = {"pools": [{"files": ["a.ogg", "b.ogg"]}]}
    store._remove_file_from_pool("i_a", 0)
    assert store._data["i_a"]["pools"][0]["files"] == ["b.ogg"]
    store._remove_file_from_pool("i_a", 0)
    assert "i_a" not in store._data


def test_stamp_preset_stamps_pool(store):
    store._stamp_preset("i_a", "My Preset")
    assert store._data["i_a"]["pools"][0] == {"preset": "My Preset"}


def test_detach_pool_resolves_preset_into_files(store):
    store.create_preset("Growl", {"files": ["a.ogg"], "volume": 0.8})
    store._data["i_a"] = {"pools": [{"preset": "Growl"}]}
    assert store._detach_pool("i_a", 0) is True
    pool = store._data["i_a"]["pools"][0]
    assert pool["files"] == ["a.ogg"]
    assert pool["volume"] == 0.8
    assert "preset" not in pool


def test_detach_pool_plain_pool_noop(store):
    store._data["i_a"] = {"pools": [{"files": ["a.ogg"]}]}
    assert store._detach_pool("i_a", 0) is False
    assert store._data["i_a"]["pools"][0]["files"] == ["a.ogg"]


def test_resolve_pool_uses_defaults(store):
    store.create_preset("Growl", {"files": ["a.ogg"], "volume": 0.8, "trigger_on_shake": True})
    r = store.resolve_pool({"preset": "Growl"})
    assert r.refs == ["a.ogg"]
    assert r.volume == 0.8
    assert r.trigger_on_shake is True
    assert r.frequency == CueLoopFrequency.MEDIUM
    assert r.exclusive.group == 0


def test_resolve_pool_surfaces_intensity_hook(store):
    pool = {"files": [], "igroup": "Impacts", "ilevel_id": 2}
    resolved = store.resolve_pool(pool)
    assert resolved.igroup == "Impacts"
    assert resolved.ilevel_id == 2


def test_resolve_pool_unhooked_has_none(store):
    resolved = store.resolve_pool({"files": ["a.ogg"]})
    assert resolved.igroup is None
    assert resolved.ilevel_id is None


class _StubIntensity(object):
    """Records fold calls; returns a canned resolution or None."""

    def __init__(self, resolution):
        self.resolution = resolution
        self.calls = []

    def resolve_pool_intensity(self, igroup, ilevel_id, current_speed, variants, flags=None):
        self.calls.append((igroup, ilevel_id, current_speed, variants, flags))
        return self.resolution


def test_resolve_pool_fold_no_speed_skips(store):
    # Without a speed, resolve_pool must not touch intensity: the hook stays
    # metadata-only and refs stay the pool's own ([] for hooked pools).
    resolved = store.resolve_pool({"files": [], "igroup": "Impacts", "ilevel_id": 1})
    assert resolved.refs == []
    assert resolved.intensity is None
    assert resolved.volume_mult is None
    assert resolved.freq_mult is None
    assert resolved.level is None
    assert resolved.igroup == "Impacts"
    assert resolved.ilevel_id == 1


def test_resolve_pool_fold_embeds_intensity(store):
    # With a speed, the fold calls intensity and embeds the resolution, so
    # resolved.files (expand=True) becomes the level files and the multipliers
    # are readable.
    store._intensity = _StubIntensity(CueIntensityResolution("Impacts", 2, 1.25, 1.5, ["hard/a.ogg"]))
    resolved = store.resolve_pool(
        {"files": [], "igroup": "Impacts", "ilevel_id": 1}, speed=1.3, variants=[0.7, 1.0, 1.3], expand=True
    )
    assert store._intensity.calls == [("Impacts", 1, 1.3, [0.7, 1.0, 1.3], None)]
    assert resolved.intensity is store._intensity.resolution
    assert resolved.refs == []
    assert resolved.files == ["hard/a.ogg"]
    assert resolved.volume_mult == 1.25
    assert resolved.freq_mult == 1.5
    assert resolved.level == 2
    assert resolved.igroup == "Impacts"
    assert resolved.ilevel_id == 1


def test_resolve_pool_fold_dead_group_falls_back(store):
    # A hooked pool whose group resolves to nothing keeps its own files.
    store._intensity = _StubIntensity(None)
    resolved = store.resolve_pool(
        {"files": ["a.ogg"], "igroup": "Ghost", "ilevel_id": 1}, speed=1.3, variants=[0.7, 1.0, 1.3], expand=True
    )
    assert resolved.files == ["a.ogg"]
    assert resolved.intensity is None
    assert resolved.volume_mult is None
    assert resolved.igroup == "Ghost"


def test_resolve_pool_speed_without_hook_no_fold(store):
    # No igroup -> no intensity call even with a speed; own files unchanged.
    store._intensity = _StubIntensity(CueIntensityResolution("Nope", 1, 1.0, 1.0))
    resolved = store.resolve_pool({"files": ["a.ogg"]}, speed=1.3, variants=[0.7, 1.0, 1.3])
    assert store._intensity.calls == []
    assert resolved.refs == ["a.ogg"]
    assert resolved.intensity is None


def test_resolve_pool_expand_materializes_files(store):
    # expand=False (default): refs only, files is None, no library access.
    r = store.resolve_pool({"files": ["a.ogg"]})
    assert r.refs == ["a.ogg"]
    assert r.files is None
    # expand=True: files becomes the concrete playable list (folder refs
    # expanded; with no SFX library wired, refs pass through).
    r = store.resolve_pool({"files": ["a.ogg"]}, expand=True)
    assert r.refs == ["a.ogg"]
    assert r.files == ["a.ogg"]


def test_resolve_video_pools_resolves_preset_pools(store):
    store.create_preset("Growl", {"files": ["a.ogg"]})
    entry = {"pools": [{"time": 1.0, "preset": "Growl"}, {"time": 2.0, "files": ["b.ogg"]}]}
    resolved = store._resolve_video_pools(entry)
    assert resolved[0]["files"] == ["a.ogg"]
    assert "preset" not in resolved[0]
    assert resolved[1]["files"] == ["b.ogg"]


# ---------------------------------------------------------------------------
# Preset CRUD
# ---------------------------------------------------------------------------


def test_preset_crud_round_trip(store):
    store.create_preset("Growl", {"files": ["a.ogg"], "volume": 0.8})
    assert store.get_preset("Growl")["files"] == ["a.ogg"]
    assert store.list_presets() == ["Growl"]
    store.delete_preset("Growl")
    assert store.get_preset("Growl") is None
    assert store.list_presets() == []


def test_create_preset_deepcopies_input(store):
    pool = {"files": ["a.ogg"]}
    store.create_preset("G", pool)
    # Mutating the input after creation does not leak into the store.
    pool["files"].append("b.ogg")
    assert store.get_preset("G")["files"] == ["a.ogg"]


def test_video_preset_crud_round_trip(store):
    entry = {"pools": [{"time": 3.0, "files": ["b.mp4"]}, {"time": 1.0, "files": ["a.mp4"]}], "volume": 0.5}
    store.create_video_preset("VP", entry, source_dur=10.0)
    preset = store.get_video_preset("VP")
    # Pools are time-sorted; missing volume defaults to CUE_VOLUME_DEFAULT.
    assert preset["pools"] == [
        {"time": 1.0, "files": ["a.mp4"], "volume": CUE_VOLUME_DEFAULT},
        {"time": 3.0, "files": ["b.mp4"], "volume": CUE_VOLUME_DEFAULT},
    ]
    assert preset["volume"] == 0.5
    assert preset["source_duration"] == 10.0
    assert store.list_video_presets() == ["VP"]
    store.delete_video_preset("VP")
    assert store.get_video_preset("VP") is None


def test_create_video_preset_skips_time_less_pools(store):
    entry = {"pools": [{"time": 1.0}, {"no_time": True}, {"time": 3.0}]}
    store.create_video_preset("VP", entry)
    # Kept pools are normalized with an explicit (empty) files list.
    assert store.get_video_preset("VP")["pools"] == [
        {"time": 1.0, "files": [], "volume": CUE_VOLUME_DEFAULT},
        {"time": 3.0, "files": [], "volume": CUE_VOLUME_DEFAULT},
    ]


def test_create_video_preset_no_pools_returns(store):
    store.create_video_preset("VP", {"pools": []})
    assert store.get_video_preset("VP") is None


# ---------------------------------------------------------------------------
# Sanitize / migration passes
# ---------------------------------------------------------------------------


def test_sanitize_video_pools_strips_time_less(store):
    store._data["v_a"] = {"pools": [{"time": 1.0}, {"no_time": True}, {"time": 3.0}]}
    store._data["i_b"] = {"pools": [{"no_time": True}]}  # non-vid untouched
    assert store._sanitize_video_pools() == 1
    assert store._data["v_a"]["pools"] == [{"time": 1.0}, {"time": 3.0}]
    assert store._data["i_b"]["pools"] == [{"no_time": True}]


def test_sanitize_video_presets_strips_time_less(store):
    store._video_presets["VP"] = {"pools": [{"time": 1.0}, {"no_time": True}]}
    assert store._sanitize_video_presets() == 1
    assert store._video_presets["VP"]["pools"] == [{"time": 1.0}]


def test_normalize_all_wraps_pool_less_entries(store):
    store._data["i_a"] = {"files": ["s.ogg"]}
    assert store._normalize_all() is True
    assert store._data["i_a"]["pools"] == [{"files": ["s.ogg"]}]


def test_normalize_all_fans_loop_frequency_into_pools(store):
    store._data["l_a"] = {"pools": [{"files": []}, {"files": []}], "frequency": 2}
    assert store._normalize_all() is True
    for pool in store._data["l_a"]["pools"]:
        assert pool["frequency"] == 2
    assert "frequency" not in store._data["l_a"]


def test_normalize_all_no_change(store):
    store._data["i_a"] = {"pools": [{"files": ["s.ogg"]}]}
    assert store._normalize_all() is False


def test_migrate_legacy_exclusive_bool_true(store):
    store._data["l_a"] = {"pools": [{"exclusive": True}]}
    assert store._migrate_legacy_exclusive() == 1
    assert store._data["l_a"]["pools"][0]["exclusive"] == {"group": 1, "start": 2, "hold": True}


def test_migrate_legacy_exclusive_bool_false_removed(store):
    store._data["l_a"] = {"pools": [{"exclusive": False}]}
    assert store._migrate_legacy_exclusive() == 1
    assert "exclusive" not in store._data["l_a"]["pools"][0]


def test_migrate_legacy_exclusive_idempotent(store):
    store._data["l_a"] = {"pools": [{"exclusive": {"group": 1}}]}
    assert store._migrate_legacy_exclusive() == 0


def test_migrate_colon_key():
    assert CueMarkerStore._migrate_colon_key("v:file") == "v_file"
    assert CueMarkerStore._migrate_colon_key("i:a") == "i_a"
    assert CueMarkerStore._migrate_colon_key("l:a") == "l_a"
    assert CueMarkerStore._migrate_colon_key("d:a") == "d_a"
    assert CueMarkerStore._migrate_colon_key("d_a|b") == "d_a__b"


def test_migrate_speed_mode_rename(store):
    store._data["v_a"] = {"pools": [], "speed_mode": "sequence"}
    store._data["i_b"] = {"pools": [], "speed_mode": "sequence"}  # non-vid untouched
    store._video_presets["VP"] = {"speed_mode": "sequence"}
    store._migrate_speed_mode_rename()
    assert store._data["v_a"]["speed_mode"] == "multi"
    assert store._data["i_b"]["speed_mode"] == "sequence"
    assert store._video_presets["VP"]["speed_mode"] == "multi"


def test_migrate_video_timestamps_to_pools(store):
    store._data["v_a"] = {"timestamps": [{"time": 1.0}]}
    store._data["i_b"] = {"timestamps": [{"time": 2.0}]}  # non-vid untouched
    store._video_presets["VP"] = {"timestamps": [{"time": 3.0}]}
    entries, presets = store._migrate_video_timestamps_to_pools()
    assert (entries, presets) == (1, 1)
    assert store._data["v_a"]["pools"] == [{"time": 1.0}]
    assert "timestamps" not in store._data["v_a"]
    assert "timestamps" in store._data["i_b"]
    assert store._video_presets["VP"]["pools"] == [{"time": 3.0}]


# ---------------------------------------------------------------------------
# Intensity hook migration (legacy folder-hook -> igroup/ilevel_id)
# ---------------------------------------------------------------------------


def _impacts_igroups():
    return {"Impacts": {"levels": [{"id": 1, "files": ["soft/"]}, {"id": 2, "files": ["hard/"]}], "next_ilevel_id": 3}}


def test_migrate_intensity_hooks_rewrites_legacy_pool(store):
    store._data["v_a"] = {"pools": [{"files": ["soft/"]}]}
    count = _cue_migrate_intensity_hooks(store, _impacts_igroups())
    assert count == 1
    pool = store._data["v_a"]["pools"][0]
    assert pool["igroup"] == "Impacts"
    assert pool["ilevel_id"] == 1
    assert pool["files"] == []


def test_migrate_intensity_hooks_first_matching_folder_wins(store):
    # Mixed pool: the first folder ref present in an igroup wins; other
    # content is dropped (the hooked pool's content is now the level).
    store._data["v_a"] = {"pools": [{"files": ["a.ogg", "hard/", "soft/"]}]}
    count = _cue_migrate_intensity_hooks(store, _impacts_igroups())
    assert count == 1
    pool = store._data["v_a"]["pools"][0]
    assert pool["igroup"] == "Impacts"
    assert pool["ilevel_id"] == 2
    assert pool["files"] == []


def test_migrate_intensity_hooks_leaves_unhooked_pools_untouched(store):
    store._data["v_a"] = {"pools": [{"files": ["plain.ogg"]}]}
    store._data["l_b"] = {"pools": [{"files": []}]}
    assert _cue_migrate_intensity_hooks(store, _impacts_igroups()) == 0
    assert store._data["v_a"]["pools"][0]["files"] == ["plain.ogg"]
    assert "igroup" not in store._data["v_a"]["pools"][0]


def test_migrate_intensity_hooks_idempotent(store):
    store._data["v_a"] = {"pools": [{"files": ["soft/"]}]}
    _cue_migrate_intensity_hooks(store, _impacts_igroups())
    # A re-run finds no folder-hooks (files are empty) and changes nothing.
    assert _cue_migrate_intensity_hooks(store, _impacts_igroups()) == 0
    pool = store._data["v_a"]["pools"][0]
    assert pool["igroup"] == "Impacts"
    assert pool["ilevel_id"] == 1
    assert pool["files"] == []


# ---------------------------------------------------------------------------
# Persistence round-trips (against a real CueDatabase)
# ---------------------------------------------------------------------------


def test_save_all_and_load_from_db_round_trip(store, cue_env):
    store._data["v_a"] = {"pools": [{"time": 1.0}]}
    store._data["i_b"] = {"pools": [{"files": ["s.ogg"]}]}
    store._presets["G"] = {"files": ["a.ogg"]}
    store._video_presets["VP"] = {"pools": [{"time": 1.0}]}
    store.save_all()

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert fresh._data["v_a"]["pools"] == [{"time": 1.0}]
    assert fresh._data["i_b"]["pools"] == [{"files": ["s.ogg"]}]
    assert fresh._presets["G"]["files"] == ["a.ogg"]
    assert fresh._video_presets["VP"]["pools"] == [{"time": 1.0}]


def test_load_from_db_runs_migrations(store, cue_env):
    store._data["v_a"] = {"timestamps": [{"time": 1.0}], "speed_mode": "sequence"}
    store.save_all()

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert fresh._data["v_a"]["pools"] == [{"time": 1.0}]
    assert fresh._data["v_a"]["speed_mode"] == "multi"


def test_save_marker_single_key_round_trip(store, cue_env):
    store._data["v_a"] = {"pools": [{"time": 5.0}]}
    store.save_marker("v_a")

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert fresh._data["v_a"]["pools"] == [{"time": 5.0}]


def test_reload_presets_merges_disk(store, cue_env):
    other = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    other.create_preset("Disk", {"files": ["d.ogg"]})

    store.reload_presets()
    assert store.get_preset("Disk") is not None


def test_delete_removed_files_deletes_dropped_marker(store, cue_env):
    store._data["v_a"] = {"pools": []}
    store._data["v_b"] = {"pools": []}
    store.save_all()

    old_keys = set(store._data)
    del store._data["v_a"]
    store.delete_removed_files(old_keys, {}, {}, set())

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert "v_a" not in fresh._data
    assert "v_b" in fresh._data


def test_delete_removed_files_preset_only_when_session_created(store, cue_env):
    # load_from_db() always reads presets from disk -- no fresh fast-path.
    store.create_preset("Sess", {"files": ["a.ogg"]})
    store.create_preset("Old", {"files": ["b.ogg"]})
    # "Sess" is session-created; "Old" simulates a preset loaded from disk.
    store._session_created = {("audio", "Sess")}
    old_presets = {"Sess": {"files": ["a.ogg"]}, "Old": {"files": ["b.ogg"]}}
    store._presets = {}  # restore drops both
    store.delete_removed_files(set(), old_presets, {}, {("audio", "Sess")})

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert "Sess" not in fresh._presets
    assert "Old" in fresh._presets


# ---------------------------------------------------------------------------
# on_save hook
# ---------------------------------------------------------------------------


def test_post_save_invokes_on_save_once_per_write(cue_env):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: calls.append(1))
    s._data["v_a"] = {"pools": [{"time": 1.0}]}
    s.save_marker("v_a")
    s._db_save_marker("v_a")
    assert len(calls) == 2


def _spy_sanitize(calls):
    def _fn():
        calls.append(1)
        return set()

    return _fn


def test_post_save_skips_sanitize_on_preset_save(cue_env, monkeypatch):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    monkeypatch.setattr(s, "_sanitize_video_pools_tracked", _spy_sanitize(calls))
    s._presets["p1"] = {"files": ["a.ogg"], "volume": 0.5}
    s.save_preset("p1")
    assert calls == []


def test_post_save_skips_sanitize_on_audio_marker_save(cue_env, monkeypatch):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    monkeypatch.setattr(s, "_sanitize_video_pools_tracked", _spy_sanitize(calls))
    s._data["i_a"] = {"pools": []}
    s.save_marker("i_a")
    assert calls == []


def test_post_save_runs_sanitize_on_video_marker_save(cue_env, monkeypatch):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    monkeypatch.setattr(s, "_sanitize_video_pools_tracked", _spy_sanitize(calls))
    s._data["v_a"] = {"pools": []}
    s.save_marker("v_a")
    assert calls == [1]


def test_post_save_runs_sanitize_when_batch_has_video(cue_env, monkeypatch):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    monkeypatch.setattr(s, "_sanitize_video_pools_tracked", _spy_sanitize(calls))
    s._data["i_a"] = {"pools": []}
    s._data["v_b"] = {"pools": []}
    s.save_markers(["i_a", "v_b"])
    assert calls == [1]


def test_save_all_invokes_on_save_once(cue_env):
    calls = []
    s = CueMarkerStore(cue_env.db, cue_env.paths, lambda: calls.append(1))
    s._data["v_a"] = {"pools": []}
    s._data["i_b"] = {"pools": []}
    s.save_all()
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Branch tails -- all-time-less presets, legacy bools, missing/out-of-range
# targets, legacy files-shaped entries, and db-closed guards
# ---------------------------------------------------------------------------


def test_create_video_preset_all_time_less_pools_returns(store):
    entry = {"pools": [{"files": ["a.ogg"]}, {"files": ["b.ogg"]}]}
    store.create_video_preset("VP", entry)
    assert store.get_video_preset("VP") is None


def test_resolve_exclusive_legacy_bool_excl(store):
    pool = {"files": [], "exclusive": True}
    r = store.resolve_pool(pool)
    assert r.exclusive.group == 0


def test_resolve_exclusive_legacy_bool_base(store):
    store._presets["P"] = {"files": [], "exclusive": True}
    r = store.resolve_pool({"preset": "P"})
    assert r.exclusive.group == 0


def test_remove_file_from_pool_missing_entry_noop(store):
    store._remove_file_from_pool("ghost", 0)  # entry None -> return


def test_remove_file_from_pool_bad_pool_index_noop(store):
    store._data["v_a"] = {"pools": [{"files": ["a.ogg"]}]}
    store._remove_file_from_pool("v_a", 0, 3)  # pool index out of range


def test_remove_file_from_pool_legacy_files_branch(store):
    # An unnormalized entry shaped as {key: {"files": [...]}} (no pools).
    store._data["v_a"] = {"files": ["a.ogg"]}
    store._remove_file_from_pool("v_a", 0)
    assert "v_a" not in store._data


def test_detach_pool_copies_preset_metadata(store):
    store._presets["P"] = {
        "files": ["a.ogg", "b.ogg"],
        "frequency": CueLoopFrequency.FAST,
        "trigger_on_shake": True,
        "exclusive": {"group": 2, "start": 0, "hold": False},
    }
    store._data["l_x"] = {"pools": [{"preset": "P"}]}

    ok = store._detach_pool("l_x", 0)

    assert ok
    pool = store._data["l_x"]["pools"][0]
    assert "preset" not in pool
    assert pool["files"] == ["a.ogg", "b.ogg"]
    assert pool["frequency"] == CueLoopFrequency.FAST
    assert pool["trigger_on_shake"] is True
    assert pool["exclusive"]["group"] == 2


def test_sanitize_video_presets_skips_preset_without_pools(store):
    store._video_presets["VP"] = {}
    store._video_presets["V2"] = {"pools": [{"time": 1.0}]}
    assert store._sanitize_video_presets() == 0


def test_sanitize_video_pools_tracked_strips_and_logs(store):
    store._data["v_bad"] = {"pools": [{"files": ["a.ogg"]}, {"time": 2.0}]}
    modified = store._sanitize_video_pools_tracked()
    assert modified == {"v_bad"}
    assert store._data["v_bad"]["pools"] == [{"time": 2.0}]


def test_migrate_legacy_exclusive_preset(store):
    store._presets["P"] = {"exclusive": True}
    assert store._migrate_legacy_exclusive() == 1
    assert store._presets["P"]["exclusive"]["group"] == 1


def test_migrate_video_timestamps_keeps_pools(store):
    store._data["v_a"] = {"pools": [{"time": 1.0}], "timestamps": [{"time": 9.0}]}
    entries, presets = store._migrate_video_timestamps_to_pools()
    assert entries == 1
    assert store._data["v_a"]["pools"] == [{"time": 1.0}]
    assert "timestamps" not in store._data["v_a"]


def test_migrate_video_timestamps_preset_keeps_pools(store):
    store._video_presets["VP"] = {"pools": [{"time": 1.0}], "timestamps": [{"time": 9.0}]}
    entries, presets = store._migrate_video_timestamps_to_pools()
    assert presets == 1
    assert "timestamps" not in store._video_presets["VP"]


def test_reload_presets_no_db_returns(cue_env):
    s = CueMarkerStore(None, cue_env.paths)
    s.reload_presets()  # must not raise


def test_save_markers_deletes_missing_key(store, cue_env):
    store.save_markers(["ghost"])  # not in _data -> delete path

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert "ghost" not in fresh._data


def test_post_save_resaves_sanitized_video_pools(store, cue_env):
    store._data["v_dirty"] = {"pools": [{"files": ["a.ogg"]}]}
    store._db_save_marker("v_dirty")

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    # The malformed pool was stripped on save and re-persisted.
    assert fresh._data["v_dirty"]["pools"] == []


def test_delete_removed_files_no_db_returns(cue_env):
    s = CueMarkerStore(None, cue_env.paths)
    s.delete_removed_files(set(), {}, {}, set())  # must not raise


def test_delete_removed_files_keeps_present_preset(store):
    store._presets["P"] = {"files": ["a.ogg"]}
    store.delete_removed_files(set(), {"P": {"files": ["a.ogg"]}}, {}, set())
    assert "P" in store._presets


def test_delete_removed_files_keeps_present_video_preset(store):
    store._video_presets["VP"] = {"pools": [{"time": 1.0}]}
    store.delete_removed_files(set(), {}, {"VP": {"pools": [{"time": 1.0}]}}, set())
    assert "VP" in store._video_presets


def test_delete_removed_files_deletes_session_video_preset(store, cue_env):
    store.create_video_preset("VP", {"pools": [{"time": 1.0}]})
    old_video_presets = {"VP": store._video_presets["VP"]}
    store._video_presets = {}  # restore dropped it
    store.delete_removed_files(set(), {}, old_video_presets, {("video", "VP")})

    fresh = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    fresh.load_from_db()
    assert "VP" not in fresh._video_presets


def test_load_from_db_no_db_resets(cue_env):
    s = CueMarkerStore(None, cue_env.paths)
    s.load_from_db()
    assert s._data == {}
    assert s._video_presets == {}
