# -*- coding: utf-8 -*-
# Tests for cue_lib.intensity -- the intensity group registry.
# Igroups are shared presets: one JSON per igroup under data/presets/intensity/,
# persisted via the db's preset store.  A group is an ordered list of levels;
# each level is a pool of folders/files with a stable id.  Level order = 1..N.

import json
import os

import pytest

from cue_lib.constants import CUE_INTENSITY_FREQ_MAX, CUE_INTENSITY_PRESET_TYPE, CUE_INTENSITY_VOLUME_MAX
from cue_lib.intensity import CueIntensityManager, _level_ramp


@pytest.fixture
def imgr(cue_env):
    """The intensity manager on the cue_env fixture's real db/paths."""
    return CueIntensityManager(cue_env.db)


def _intensity_dir(cue_env):
    return cue_env.paths.intensity_preset_dir


def _igroup_files(cue_env):
    d = _intensity_dir(cue_env)
    if not os.path.isdir(d):
        return []
    return sorted(os.listdir(d))


# ==========================================================================
# _level_ramp -- ramp-default multiplier generation
# ==========================================================================


def test_level_ramp_single_level_is_identity():
    assert _level_ramp(1, CUE_INTENSITY_VOLUME_MAX) == [1.0]
    assert _level_ramp(1, CUE_INTENSITY_FREQ_MAX) == [1.0]


def test_level_ramp_two_levels_ends_at_max():
    assert _level_ramp(2, CUE_INTENSITY_VOLUME_MAX) == [1.0, 1.25]
    assert _level_ramp(2, CUE_INTENSITY_FREQ_MAX) == [1.0, 1.5]


def test_level_ramp_three_levels_linear():
    assert _level_ramp(3, CUE_INTENSITY_VOLUME_MAX) == [1.0, 1.125, 1.25]


def test_level_ramp_strictly_increasing_to_max():
    ramp = _level_ramp(5, CUE_INTENSITY_FREQ_MAX)
    assert len(ramp) == 5
    assert all(ramp[i] < ramp[i + 1] for i in range(len(ramp) - 1))
    assert ramp[0] == 1.0
    assert ramp[-1] == CUE_INTENSITY_FREQ_MAX


# ==========================================================================
# create / list / get / rename / delete
# ==========================================================================


def test_create_empty_igroup(cue_env, imgr):
    assert imgr.create_igroup("Impacts") is None
    assert imgr.list_igroups() == ["Impacts"]
    data = imgr.get_igroup("Impacts")
    assert data is not None
    assert data["levels"] == []
    assert data["next_ilevel_id"] == 1
    # One JSON per igroup, named {safe}_{sha1:8}.json, _key injected inside.
    files = _igroup_files(cue_env)
    assert len(files) == 1
    assert files[0].startswith("Impacts_")
    with open(os.path.join(_intensity_dir(cue_env), files[0])) as f:
        raw = json.load(f)
    assert raw["_key"] == "Impacts"


def test_create_blank_name_rejected(cue_env, imgr):
    assert imgr.create_igroup("   ") is not None
    assert imgr.list_igroups() == []


def test_create_duplicate_rejected(cue_env, imgr):
    imgr.create_igroup("Impacts")
    err = imgr.create_igroup("Impacts")
    assert err is not None
    assert "already exists" in err


def test_get_missing_igroup_returns_none(cue_env, imgr):
    assert imgr.get_igroup("nope") is None


def test_delete_igroup(cue_env, imgr):
    imgr.create_igroup("A")
    imgr.delete_igroup("A")
    assert imgr.list_igroups() == []
    assert _igroup_files(cue_env) == []


# ==========================================================================
# level editing -- stable ids on an ordered level list
# ==========================================================================


def test_add_level_assigns_stable_ids(cue_env, imgr):
    imgr.create_igroup("Impacts")
    assert imgr.add_level("Impacts") == 1
    assert imgr.add_level("Impacts") == 2
    data = imgr.get_igroup("Impacts")
    assert [lv["id"] for lv in data["levels"]] == [1, 2]
    assert data["next_ilevel_id"] == 3


def test_add_level_missing_igroup_returns_none(cue_env, imgr):
    assert imgr.add_level("nope") is None


def test_add_level_file_appends_and_dedupes(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    assert imgr.add_level_file("Impacts", 1, "soft/") is None
    assert imgr.add_level_file("Impacts", 1, "soft/a.ogg") is None
    err = imgr.add_level_file("Impacts", 1, "soft/")
    assert err is not None
    assert imgr.get_igroup("Impacts")["levels"][0]["files"] == ["soft/", "soft/a.ogg"]


def test_add_level_file_missing_group_or_level_errors(cue_env, imgr):
    imgr.create_igroup("Impacts")
    assert imgr.add_level_file("nope", 1, "soft/") is not None
    assert imgr.add_level_file("Impacts", 1, "soft/") is not None  # no level yet
    imgr.add_level("Impacts")
    assert imgr.add_level_file("Impacts", 99, "soft/") is not None


def test_remove_level_file(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 1, "soft/")
    imgr.remove_level_file("Impacts", 1, "soft/")
    assert imgr.get_igroup("Impacts")["levels"][0]["files"] == []


def test_remove_level_keeps_ids(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")  # id 1
    imgr.add_level("Impacts")  # id 2
    imgr.remove_level("Impacts", 0)
    assert [lv["id"] for lv in imgr.get_igroup("Impacts")["levels"]] == [2]


def test_remove_level_out_of_range_noop(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.remove_level("Impacts", 5)  # must not raise
    assert len(imgr.get_igroup("Impacts")["levels"]) == 1


def test_move_level_preserves_ids(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")  # id 1
    imgr.add_level("Impacts")  # id 2
    imgr.move_level("Impacts", 0, 1)
    assert [lv["id"] for lv in imgr.get_igroup("Impacts")["levels"]] == [2, 1]


def test_move_level_clamped(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level("Impacts")
    imgr.move_level("Impacts", 0, -1)  # can't move above top; must not raise
    assert [lv["id"] for lv in imgr.get_igroup("Impacts")["levels"]] == [1, 2]


def test_move_level_missing_igroup_noop(cue_env, imgr):
    imgr.move_level("nope", 0, 1)  # must not raise


# ==========================================================================
# level reads -- files by position/id + derived ramp multipliers
# ==========================================================================


def test_level_multipliers_derived_from_ramp(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level("Impacts")
    assert imgr.level_multipliers("Impacts", 1) == (1.0, 1.0)
    assert imgr.level_multipliers("Impacts", 2) == (1.25, 1.5)


def test_level_files_by_id_dangling_falls_back_to_level_one(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 1, "soft/")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 2, "hard/")
    assert imgr.level_files_by_id("Impacts", 99) == ["soft/"]  # dangling -> level 1
    assert imgr.level_files_by_id("Impacts", 2) == ["hard/"]


def test_level_files_by_index(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 1, "soft/")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 2, "hard/")
    assert imgr.level_files("Impacts", 1) == ["soft/"]
    assert imgr.level_files("Impacts", 2) == ["hard/"]
    assert imgr.level_files("Impacts", 3) is None
    assert imgr.level_files("nope", 1) is None


# ==========================================================================
# persistence -- on-disk JSON is the source of truth
# ==========================================================================


def test_igroups_survive_manager_rebuild(cue_env):
    m1 = CueIntensityManager(cue_env.db)
    m1.create_igroup("Impacts")
    m1.add_level("Impacts")
    m1.add_level_file("Impacts", 1, "a/")
    m2 = CueIntensityManager(cue_env.db)  # fresh manager, same db
    assert m2.list_igroups() == ["Impacts"]
    assert m2.get_igroup("Impacts")["levels"][0]["files"] == ["a/"]


def test_database_intensity_preset_type(cue_env):
    assert cue_env.db._preset_dir(CUE_INTENSITY_PRESET_TYPE) == cue_env.paths.intensity_preset_dir
    # db.open() created the dir.
    assert os.path.isdir(cue_env.paths.intensity_preset_dir)


def test_load_migrates_legacy_folders_to_levels(cue_env):
    # Hand-write the old igroup shape (folders + multiplier arrays) at the db's
    # canonical preset path, then load through a fresh manager.
    legacy = {
        "_key": "Legacy",
        "folders": ["soft/", "hard/"],
        "volume_multipliers": [1.0, 1.25],
        "frequency_multipliers": [1.0, 1.5],
    }
    fpath = cue_env.db._preset_path(CUE_INTENSITY_PRESET_TYPE, "Legacy")
    with open(fpath, "w") as f:
        json.dump(legacy, f)

    m = CueIntensityManager(cue_env.db)
    data = m.get_igroup("Legacy")
    assert data is not None
    assert data["levels"] == [{"id": 1, "files": ["soft/"]}, {"id": 2, "files": ["hard/"]}]
    assert data["next_ilevel_id"] == 3
    assert "folders" not in data
    assert "volume_multipliers" not in data
    assert "frequency_multipliers" not in data

    # The migration back-writes to disk, so a fresh manager reads the new shape.
    m2 = CueIntensityManager(cue_env.db)
    data2 = m2.get_igroup("Legacy")
    assert data2 is not None
    assert "folders" not in data2
    assert data2["levels"] == [{"id": 1, "files": ["soft/"]}, {"id": 2, "files": ["hard/"]}]


def test_load_leaves_new_shape_untouched(cue_env):
    m = CueIntensityManager(cue_env.db)
    m.create_igroup("Impacts")
    m.add_level("Impacts")
    m.add_level_file("Impacts", 1, "soft/")
    data = m.get_igroup("Impacts")
    assert data["levels"] == [{"id": 1, "files": ["soft/"]}]
