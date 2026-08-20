# -*- coding: utf-8 -*-
# Tests for cue_lib.markers.CueMarkerManager -- the coordinator that wraps a
# real CueMarkerStore and delegates to it.  The store runs on a real
# CueDatabase + CuePaths (cue_env, tmp dirs); the collaborators are fakes
# (FakeVidManager / FakeSfxManager) or plain None since the tested methods
# never touch trigger/video_editor.

import pytest

from cue_lib.constants import CUE_VOLUME_DEFAULT
from cue_lib.marker_store import CueMarkerStore
from cue_lib.markers import CueMarkerManager
from cue_lib.state import CueContext

from tests.fakes import FakeSfxManager, FakeVidManager


@pytest.fixture
def mgr(cue_env):
    store = CueMarkerStore(cue_env.db, cue_env.paths, lambda: None)
    ctx = CueContext()
    vid = FakeVidManager(duration=10.0)
    sfx = FakeSfxManager()
    return CueMarkerManager(ctx, store, vid, sfx, None, None)


# ---------------------------------------------------------------------------
# dict-like interface / _data passthrough
# ---------------------------------------------------------------------------

def test_manager_dict_interface(mgr):
    mgr["v_a"] = {"pools": []}
    assert "v_a" in mgr
    assert mgr.get("v_a")["pools"] == []  # get() normalizes (adds replay)
    assert len(mgr) == 1
    assert list(mgr.keys()) == ["v_a"]
    assert dict(mgr.items())["v_a"]["pools"] == []
    mgr.setdefault("v_a", {})
    mgr.pop("v_a")
    assert "v_a" not in mgr


def test_data_setter_writes_through_to_store(mgr):
    mgr._data = {"v_x": {"pools": []}}
    assert mgr._store._data["v_x"] == {"pools": []}


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------

def test_audio_preset_passthroughs(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    assert mgr.list_presets() == ["basic"]
    assert mgr.get_preset("basic")["files"] == ["a.ogg"]
    mgr.delete_preset("basic")
    assert mgr.get_preset("basic") is None


def test_video_preset_crud(mgr):
    mgr.create_video_preset("vp", {"pools": [{"time": 1.0, "files": ["a.ogg"]}],
                                   "volume": 0.7})
    assert mgr.get_video_preset("vp")["pools"][0]["time"] == 1.0
    assert mgr.list_video_presets() == ["vp"]
    mgr.delete_video_preset("vp")
    assert mgr.get_video_preset("vp") is None


def test_preset_remove_file_direct(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg", "b.ogg"]})
    mgr.preset_remove_file("basic", "a.ogg")
    assert mgr.get_preset("basic")["files"] == ["b.ogg"]


def test_preset_remove_file_missing_preset_noop(mgr):
    mgr.preset_remove_file("nope", "a.ogg")  # must not raise


def test_preset_remove_file_folder_ref(mgr):
    mgr._sfx_manager.files = ["music/a.ogg", "music/b.ogg", "other.ogg"]
    mgr.create_preset("fold", {"files": ["music/"]})
    mgr.preset_remove_file("fold", "music/a.ogg")
    assert mgr.get_preset("fold")["files"] == ["music/b.ogg"]


# ---------------------------------------------------------------------------
# resolve / stamp / detach
# ---------------------------------------------------------------------------

def test_resolve_pool_from_preset(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    r = mgr.resolve_pool({"preset": "basic"})
    assert r.files == ["a.ogg"]
    assert r.volume == 0.8


def test_stamp_preset_writes_preset_ref(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr._stamp_preset("i_scene.ogg", "basic", 0)
    assert mgr.get("i_scene.ogg")["pools"][0] == {"preset": "basic"}


def test_detach_pool_materializes_preset(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg", "b.ogg"], "volume": 0.8})
    mgr._stamp_preset("i_scene.ogg", "basic", 0)
    assert mgr._detach_pool("i_scene.ogg", 0) is True
    pool = mgr.get("i_scene.ogg")["pools"][0]
    assert pool["files"] == ["a.ogg", "b.ogg"]
    assert pool["volume"] == 0.8
    assert "preset" not in pool


def test_detach_pool_non_preset_returns_false(mgr):
    mgr["i_scene.ogg"] = {"pools": [{"files": ["a.ogg"]}]}
    assert mgr._detach_pool("i_scene.ogg", 0) is False


def test_detach_pool_out_of_range_returns_false(mgr):
    assert mgr._detach_pool("i_scene.ogg", 3) is False


def test_detach_pool_at_detaches_and_saves(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr._stamp_preset("i_scene.ogg", "basic", 0)
    mgr.detach_pool_at("i_scene.ogg", 0)
    pool = mgr.get("i_scene.ogg")["pools"][0]
    assert pool["files"] == ["a.ogg"]
    assert "preset" not in pool


def test_detach_active_video_ts(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    # Video pools carry "time" (the sanitizer strips time-less video pools on
    # save), so build the stamped marker the way production does.
    mgr["v_scene.ogv"] = {"pools": [{"preset": "basic", "time": 1.0}]}
    mgr.video.active_pool = 0
    mgr.detach_active_video_ts()
    pool = mgr.get("v_scene.ogv")["pools"][0]
    assert "preset" not in pool
    assert pool["files"] == ["a.ogg"]
    assert pool["time"] == 1.0  # marker time survives the detach


def test_detach_active_video_ts_multi_detaches_all_selected(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    mgr["v_scene.ogv"] = {"pools": [
        {"preset": "basic", "time": 1.0},
        {"preset": "basic", "time": 2.0},
        {"time": 3.0, "files": ["c.ogg"]},
    ]}
    mgr.video.selected = {0, 1}
    mgr.video.active_pool = 0
    mgr.detach_active_video_ts()
    pools = mgr.get("v_scene.ogv")["pools"]
    assert pools[0] == {"time": 1.0, "files": ["a.ogg"], "volume": 0.8}
    assert pools[1] == {"time": 2.0, "files": ["a.ogg"], "volume": 0.8}
    assert pools[2] == {"time": 3.0, "files": ["c.ogg"]}  # untouched (not selected)


def test_detach_active_video_ts_no_current_file(mgr):
    mgr.detach_active_video_ts()  # must not raise


def test_detach_active_video_ts_missing_entry(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.detach_active_video_ts()  # must not raise


# ---------------------------------------------------------------------------
# video preset out-of-range / apply
# ---------------------------------------------------------------------------

def test_video_preset_out_of_range_counts_overflow(mgr):
    mgr.create_video_preset("vp", {"pools": [{"time": 5.0}, {"time": 99.0}],
                                   "volume": 1.0})
    assert mgr.video_preset_out_of_range("vp") == 1


def test_video_preset_out_of_range_missing_preset(mgr):
    assert mgr.video_preset_out_of_range("missing") == 0


def test_video_preset_out_of_range_no_duration(mgr):
    mgr._vid_manager.duration = 0
    mgr.create_video_preset("vp", {"pools": [{"time": 5.0}], "volume": 1.0})
    assert mgr.video_preset_out_of_range("vp") == 0


def test_apply_video_preset_installs_sorted_pools(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.create_video_preset("vp", {"pools": [
        {"time": 5.0, "files": ["a.ogg"]}, {"time": 1.0, "files": ["b.ogg"]}],
        "volume": 0.8})
    mgr.apply_video_preset("vp")
    entry = mgr.get("v_scene.ogv")
    assert [p["time"] for p in entry["pools"]] == [1.0, 5.0]
    assert entry["pools"][0]["files"] == ["b.ogg"]
    assert entry["volume"] == 0.8


def test_apply_video_preset_drops_out_of_range_and_no_time(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.create_video_preset("vp", {"pools": [
        {"time": 5.0}, {"time": 99.0}, {"files": ["x.ogg"]}], "volume": 1.0})
    mgr.apply_video_preset("vp")
    entry = mgr.get("v_scene.ogv")
    assert [p["time"] for p in entry["pools"]] == [5.0]


def test_apply_video_preset_missing_preset_noop(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.apply_video_preset("missing")  # must not raise


def test_apply_video_preset_no_current_file_noop(mgr):
    mgr.create_video_preset("vp", {"pools": [{"time": 5.0}], "volume": 1.0})
    mgr.apply_video_preset("vp")  # must not raise


def test_resolve_video_pools_expands_preset(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg"], "volume": 0.8})
    pools = mgr._resolve_video_pools({"pools": [{"preset": "basic", "time": 1.0}]})
    assert pools[0]["files"] == ["a.ogg"]
    assert pools[0]["volume"] == 0.8
    assert "preset" not in pools[0]


# ---------------------------------------------------------------------------
# folder-ref file removal
# ---------------------------------------------------------------------------

def test_detach_folder_ref_in_files(mgr):
    mgr._sfx_manager.files = ["music/a.ogg", "music/b.ogg"]
    files = ["music/"]
    mgr._detach_folder_ref_in_files(files, 0, "music/a.ogg")
    assert files == ["music/b.ogg"]


def test_remove_file_from_preset_pool(mgr):
    mgr._sfx_manager.files = ["music/a.ogg", "music/b.ogg"]
    mgr.create_preset("fold", {"files": ["music/"]})
    mgr._stamp_preset("i_scene.ogg", "fold", 0)
    mgr._remove_file_from_preset_pool("i_scene.ogg", 0, 0, "music/a.ogg")
    pool = mgr.get("i_scene.ogg")["pools"][0]
    assert pool["files"] == ["music/b.ogg"]
    assert "preset" not in pool  # detached


def test_remove_file_from_folder_ref(mgr):
    mgr._sfx_manager.files = ["music/a.ogg", "music/b.ogg"]
    mgr.create_preset("fold", {"files": ["music/"]})
    mgr._stamp_preset("i_scene.ogg", "fold", 0)
    mgr._remove_file_from_folder_ref("i_scene.ogg", 0, 0, "music/a.ogg")
    pool = mgr.get("i_scene.ogg")["pools"][0]
    assert pool["files"] == ["music/b.ogg"]


def test_remove_file_from_preset_pool_multi_fans_out(mgr):
    # A multi-select on the current video routes the preset-child delete
    # through _remove_path_from_selected: every selected pool is detached and
    # the child dropped from each.
    mgr._ctx.current_file = "scene.ogv"
    mgr._sfx_manager.files = ["music/a.ogg", "music/b.ogg"]
    mgr.create_preset("fold", {"files": ["music/a.ogg", "music/b.ogg"]})
    mgr._data["v_scene.ogv"] = {"pools": [
        {"preset": "fold", "time": 1.0},
        {"preset": "fold", "time": 2.0},
    ]}
    mgr.video.active_pool = 0
    mgr.video.selected = {0, 1}
    mgr._remove_file_from_preset_pool("v_scene.ogv", 0, 0, "music/a.ogg")
    pools = mgr.get("v_scene.ogv")["pools"]
    assert pools[0]["files"] == ["music/b.ogg"]
    assert "preset" not in pools[0]  # detached
    assert pools[1]["files"] == ["music/b.ogg"]
    assert "preset" not in pools[1]


def test_remove_file_from_folder_ref_multi_fans_out(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr._sfx_manager.files = ["music/a.ogg", "music/b.ogg"]
    mgr._data["v_scene.ogv"] = {"pools": [
        {"time": 1.0, "files": ["music/"]},
        {"time": 2.0, "files": ["music/"]},
    ]}
    mgr.video.active_pool = 0
    mgr.video.selected = {0, 1}
    mgr._remove_file_from_folder_ref("v_scene.ogv", 0, 0, "music/a.ogg")
    pools = mgr.get("v_scene.ogv")["pools"]
    assert pools[0]["files"] == ["music/b.ogg"]
    assert pools[1]["files"] == ["music/b.ogg"]


def test_video_multi_file_edit_matches_current_video(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.video.selected = {0, 1}
    assert mgr._video_multi_file_edit("v_scene.ogv") is True
    assert mgr._video_multi_file_edit("v_other.ogv") is False


def test_video_multi_file_edit_requires_multi_selection(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.video.selected = {0}
    assert mgr._video_multi_file_edit("v_scene.ogv") is False


# ---------------------------------------------------------------------------
# entry / pool mutators (store passthroughs)
# ---------------------------------------------------------------------------

def test_get_or_create_entry_creates_pooled_entry(mgr):
    entry = mgr._get_or_create_entry("v_new")
    assert entry["pools"] == []  # get_or_create normalizes (adds replay)
    assert mgr.get("v_new")["pools"] == []


def test_ensure_pool_defaults(mgr):
    pool = mgr._ensure_pool("v_new", 0)
    assert pool["files"] == []
    assert pool["volume"] == CUE_VOLUME_DEFAULT


def test_add_and_remove_file_from_pool(mgr):
    mgr._add_file_to_pool("i_scene.ogg", "a.ogg", 0)
    assert mgr.get("i_scene.ogg")["pools"][0]["files"] == ["a.ogg"]
    mgr._remove_file_from_pool("i_scene.ogg", 0, 0)
    assert "i_scene.ogg" not in mgr._data  # emptied pool deletes the entry


# ---------------------------------------------------------------------------
# copy_context / paste_context
# ---------------------------------------------------------------------------

def test_copy_context_copies_all_key_types(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr._ctx.current_dialogue = "hello"
    mgr["v_scene.ogv"] = {"pools": [{"time": 1.0, "files": ["a.ogg"]}]}
    mgr["i_scene.ogv"] = {"pools": [{"files": ["b.ogg"]}]}
    mgr["d_scene.ogv__hello"] = {"pools": [{"files": ["c.ogg"]}]}
    mgr["l_scene.ogv"] = {"pools": [{"files": ["d.ogg"]}]}
    mgr.copy_context()
    assert set(mgr.clipboard["markers"].keys()) == {
        "v_scene.ogv", "i_scene.ogv", "d_scene.ogv__hello", "l_scene.ogv"}
    assert mgr.clipboard["source_file"] == "scene.ogv"


def test_paste_context_rewrites_keys_to_current_scene(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr._ctx.current_dialogue = "hello"
    mgr["v_scene.ogv"] = {"pools": [{"time": 1.0, "files": ["a.ogg"]}]}
    mgr["i_scene.ogv"] = {"pools": [{"files": ["b.ogg"]}]}
    mgr["d_scene.ogv__hello"] = {"pools": [{"files": ["c.ogg"]}]}
    mgr["l_scene.ogv"] = {"pools": [{"files": ["d.ogg"]}]}
    mgr.copy_context()

    mgr._ctx.current_file = "new.ogv"
    mgr._ctx.current_dialogue = "bye"
    mgr.paste_context()
    assert "v_new.ogv" in mgr._data
    assert "i_new.ogv" in mgr._data
    assert "d_new.ogv__bye" in mgr._data
    assert "l_new.ogv" in mgr._data
    assert "v_scene.ogv" in mgr._data  # source scene keeps its own markers


def test_paste_context_no_clipboard_noop(mgr):
    mgr.paste_context()  # must not raise


def test_paste_context_skips_unmatched_source_key(mgr):
    mgr._ctx.current_file = "new.ogv"
    mgr.clipboard = {"markers": {"v_old.ogv": {"pools": []}},
                     "source_file": "scene.ogv"}
    mgr.paste_context()
    assert "v_new.ogv" not in mgr._data


def test_paste_context_clamps_video_times_to_duration(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr._ctx.current_dialogue = "hi"
    mgr["v_scene.ogv"] = {"pools": [{"time": 99.0, "files": ["a.ogg"]}]}
    mgr.copy_context()

    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    assert mgr["v_new.ogv"]["pools"][0]["time"] == 10.0


# ---------------------------------------------------------------------------
# property setters / __delitem__
# ---------------------------------------------------------------------------

def test_presets_setter_writes_through(mgr):
    mgr._presets = {"p": {"files": ["a.ogg"]}}
    assert mgr._store._presets["p"]["files"] == ["a.ogg"]


def test_video_presets_setter_writes_through(mgr):
    mgr._video_presets = {"vp": {"pools": [], "volume": 1.0}}
    assert mgr._store._video_presets["vp"]["pools"] == []


def test_session_created_getter_setter(mgr):
    mgr._session_created = {("audio", "p")}
    assert mgr._session_created == {("audio", "p")}
    assert mgr._store._session_created == {("audio", "p")}


def test_delitem_deletes_from_store(mgr):
    mgr["i_scene.ogv"] = {"pools": []}
    del mgr["i_scene.ogv"]
    assert "i_scene.ogv" not in mgr._store._data


# ---------------------------------------------------------------------------
# apply_video_preset -- time-less pool drop (inject directly: create_video_preset
# strips time-less pools at save, so the branch is only reachable on raw data)
# ---------------------------------------------------------------------------

def test_apply_video_preset_drops_time_less_pool(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr._video_presets["vp"] = {"pools": [
        {"time": 5.0, "files": ["a.ogg"]}, {"files": ["x.ogg"]}], "volume": 1.0}
    mgr.apply_video_preset("vp")
    entry = mgr.get("v_scene.ogv")
    assert [p["time"] for p in entry["pools"]] == [5.0]


# ---------------------------------------------------------------------------
# _remove_file_from_preset_pool -- guard branches + direct-file else
# ---------------------------------------------------------------------------

def test_remove_file_from_preset_pool_missing_entry_noop(mgr):
    mgr._remove_file_from_preset_pool("nope", 0, 0, "a.ogg")  # must not raise


def test_remove_file_from_preset_pool_out_of_range_noop(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr["i_scene.ogv"] = {"pools": [{"files": ["a.ogg"]}]}
    mgr._remove_file_from_preset_pool("i_scene.ogv", 3, 0, "a.ogg")  # must not raise
    assert mgr.get("i_scene.ogv")["pools"][0]["files"] == ["a.ogg"]


def test_remove_file_from_preset_pool_direct_file(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr.create_preset("basic", {"files": ["a.ogg", "b.ogg"]})
    mgr._stamp_preset("i_scene.ogv", "basic", 0)
    mgr._remove_file_from_preset_pool("i_scene.ogv", 0, 0, "a.ogg")
    pool = mgr.get("i_scene.ogv")["pools"][0]
    assert pool["files"] == ["b.ogg"]


# ---------------------------------------------------------------------------
# _detach_folder_ref_in_files / _remove_file_from_folder_ref guards
# ---------------------------------------------------------------------------

def test_detach_folder_ref_plain_file_noop(mgr):
    files = ["a.ogg"]
    mgr._detach_folder_ref_in_files(files, 0, "a.ogg")
    assert files == ["a.ogg"]


def test_remove_file_from_folder_ref_missing_entry_noop(mgr):
    mgr._remove_file_from_folder_ref("nope", 0, 0, "music/a.ogg")  # must not raise


def test_remove_file_from_folder_ref_out_of_range_pool_noop(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr["i_scene.ogv"] = {"pools": [{"files": ["music/"]}]}
    mgr._remove_file_from_folder_ref("i_scene.ogv", 2, 0, "music/a.ogg")  # must not raise


def test_remove_file_from_folder_ref_out_of_range_file_noop(mgr):
    mgr._ctx.current_file = "scene.ogv"
    mgr["i_scene.ogv"] = {"pools": [{"files": ["music/"]}]}
    mgr._remove_file_from_folder_ref("i_scene.ogv", 0, 5, "music/a.ogg")  # must not raise


# ---------------------------------------------------------------------------
# save / persistence API passthroughs
# ---------------------------------------------------------------------------

def test_save_preset_passthrough(mgr):
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr.save_preset("basic")
    mgr._db_save_preset("basic")


def test_save_video_preset_passthrough(mgr):
    mgr._video_presets["vp"] = {"pools": [{"time": 1.0, "files": []}], "volume": 1.0}
    mgr.save_video_preset("vp")
    mgr._db_save_video_preset("vp")


def test_save_all_passthrough(mgr):
    mgr["i_scene.ogv"] = {"pools": [{"files": ["a.ogg"]}]}
    mgr.create_preset("basic", {"files": ["a.ogg"]})
    mgr._video_presets["vp"] = {"pools": [{"time": 1.0}], "volume": 1.0}
    mgr.save_all()


def test_delete_removed_files_no_removals(mgr):
    mgr["i_scene.ogv"] = {"pools": [{"files": ["a.ogg"]}]}
    mgr.delete_removed_files(
        set(mgr._data.keys()), dict(mgr._presets), dict(mgr._video_presets),
        set(mgr._session_created))


def test_load_persistent(mgr):
    mgr.load_persistent()


def test_reload_presets_merges_nothing(mgr):
    mgr.reload_presets()  # empty disk -> merge nothing, no raise


def test_copy_context_whitelists_entry_keys(mgr):
    # Speed keys reference variant files the target context may not have,
    # music is per-trigger audio intent, _key is derived, replay is
    # re-stamped -- none of them travel with a copied context.
    mgr._ctx.current_file = "scene.ogv"
    mgr["v_scene.ogv"] = {
        "pools": [{"time": 1.0, "files": ["a.ogg"]}],
        "volume": 0.8,
        "video_file_muted": True,
        "speed_pref": 2.0,
        "speed_sequence": [2.0, 1.0],
        "speed_mode": "manual",
        "disabled_auto_speeds": [1.0],
        "music": {"path": "bgm.ogg"},
        "_key": "v_scene.ogv",
        "replay": "some_replay",
    }
    mgr.copy_context()
    copied = mgr.clipboard["markers"]["v_scene.ogv"]
    assert set(copied.keys()) == {"pools", "volume", "video_file_muted"}
    assert copied["pools"][0]["time"] == 1.0
    assert copied["volume"] == 0.8
    assert copied["video_file_muted"] is True


def test_paste_context_drops_infra_keys(mgr):
    # The original bug: a 2.0x context's speed keys leaked into a pasted
    # context that never had those speeds, breaking its markers.
    mgr._ctx.current_file = "scene.ogv"
    mgr["v_scene.ogv"] = {
        "pools": [{"time": 1.0, "files": ["a.ogg"]}],
        "speed_pref": 2.0,
        "speed_mode": "manual",
        "music": {"path": "bgm.ogg"},
        "replay": "old_replay",
    }
    mgr.copy_context()

    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    pasted = mgr["v_new.ogv"]
    assert set(pasted.keys()) == {"pools"}
    assert "speed_pref" not in pasted
    assert "speed_mode" not in pasted
    assert "music" not in pasted
    assert "replay" not in pasted  # not replaying, so no replay stamp


def test_paste_context_re_stamps_replay_when_in_replay(monkeypatch, mgr):
    import renpy.store

    mgr._ctx.current_file = "scene.ogv"
    mgr["i_scene.ogv"] = {"pools": [{"files": ["a.ogg"]}]}
    mgr.copy_context()

    monkeypatch.setattr(renpy.store, "_in_replay", "replay_x")
    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    assert mgr["i_new.ogv"]["pools"][0]["files"] == ["a.ogg"]
    assert mgr["i_new.ogv"]["replay"] == "replay_x"


class _Trigger(object):
    """Trigger stand-in: only the loop_states seam paste_context pops."""

    def __init__(self):
        self.loop_states = {}


def test_paste_context_clears_target_loop_state(mgr):
    trig = _Trigger()
    trig.loop_states = {"l_new.ogv": {"0": {"channels": ["old_ch"]}},
                        "l_other.ogv": {"0": {"channels": ["ch2"]}}}
    mgr._trigger = trig
    mgr._ctx.current_file = "scene.ogv"
    mgr["l_scene.ogv"] = {"pools": [{"files": ["a.ogg"]}]}
    mgr.copy_context()

    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    assert "l_new.ogv" not in trig.loop_states  # stale state for the pasted key dropped
    assert "l_other.ogv" in trig.loop_states  # unrelated keys untouched


def test_paste_context_keeps_loop_state_when_no_loop_pasted(mgr):
    trig = _Trigger()
    trig.loop_states = {"l_scene.ogv": {"0": {"channels": ["ch"]}}}
    mgr._trigger = trig
    mgr._ctx.current_file = "scene.ogv"
    mgr["i_scene.ogv"] = {"pools": [{"files": ["a.ogg"]}]}  # image only
    mgr.copy_context()

    mgr._ctx.current_file = "new.ogv"
    mgr.paste_context()
    assert "l_scene.ogv" in trig.loop_states  # untouched
