# -*- coding: utf-8 -*-
# Tests for cue_lib.intensity -- the intensity group registry (slice 0).
# Igroups are shared presets: one JSON per igroup under data/presets/intensity/,
# persisted via the db's preset store.  Folder order = level order; each level
# carries ramp-default volume/frequency multipliers (UI editing deferred to the
# per-video inspector).

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
    assert data["folders"] == []
    assert data["volume_multipliers"] == []
    assert data["frequency_multipliers"] == []
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


def test_rename_igroup_moves_file(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_folder("Impacts", "Sub/")
    assert imgr.rename_igroup("Impacts", "Hits") is None
    assert imgr.list_igroups() == ["Hits"]
    assert imgr.get_igroup("Impacts") is None
    data = imgr.get_igroup("Hits")
    assert data is not None
    assert data["folders"] == ["Sub/"]
    files = _igroup_files(cue_env)
    assert len(files) == 1
    assert files[0].startswith("Hits_")


def test_rename_to_existing_rejected(cue_env, imgr):
    imgr.create_igroup("A")
    imgr.create_igroup("B")
    assert imgr.rename_igroup("A", "B") is not None


def test_rename_blank_rejected(cue_env, imgr):
    imgr.create_igroup("A")
    assert imgr.rename_igroup("A", "  ") is not None


def test_rename_missing_igroup_rejected(cue_env, imgr):
    assert imgr.rename_igroup("nope", "Hits") is not None


def test_delete_igroup(cue_env, imgr):
    imgr.create_igroup("A")
    imgr.delete_igroup("A")
    assert imgr.list_igroups() == []
    assert _igroup_files(cue_env) == []


# ==========================================================================
# level editing -- folder list is the level list
# ==========================================================================


def test_add_folder_ramps(cue_env, imgr):
    imgr.create_igroup("Impacts")
    assert imgr.add_folder("Impacts", "sfx/soft/") is None
    assert imgr.add_folder("Impacts", "sfx/hard/") is None
    data = imgr.get_igroup("Impacts")
    assert data["folders"] == ["sfx/soft/", "sfx/hard/"]
    assert data["volume_multipliers"] == [1.0, 1.25]
    assert data["frequency_multipliers"] == [1.0, 1.5]


def test_add_folder_dedupes(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_folder("Impacts", "sfx/soft/")
    err = imgr.add_folder("Impacts", "sfx/soft/")
    assert err is not None
    assert len(imgr.get_igroup("Impacts")["folders"]) == 1


def test_add_folder_missing_igroup(cue_env, imgr):
    err = imgr.add_folder("nope", "sfx/soft/")
    assert err is not None


def test_remove_level_renumbers(cue_env, imgr):
    imgr.create_igroup("Impacts")
    for folder in ["a/", "b/", "c/"]:
        imgr.add_folder("Impacts", folder)
    imgr.remove_level("Impacts", 0)
    data = imgr.get_igroup("Impacts")
    assert data["folders"] == ["b/", "c/"]
    assert data["volume_multipliers"] == [1.0, 1.25]
    assert data["frequency_multipliers"] == [1.0, 1.5]


def test_remove_level_out_of_range_noop(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_folder("Impacts", "a/")
    imgr.remove_level("Impacts", 5)  # must not raise
    assert imgr.get_igroup("Impacts")["folders"] == ["a/"]


def test_move_level(cue_env, imgr):
    imgr.create_igroup("Impacts")
    for folder in ["a/", "b/", "c/"]:
        imgr.add_folder("Impacts", folder)
    imgr.move_level("Impacts", 0, 1)
    assert imgr.get_igroup("Impacts")["folders"] == ["b/", "a/", "c/"]


def test_move_level_clamped(cue_env, imgr):
    imgr.create_igroup("Impacts")
    for folder in ["a/", "b/"]:
        imgr.add_folder("Impacts", folder)
    imgr.move_level("Impacts", 0, -1)  # can't move above top; must not raise
    assert imgr.get_igroup("Impacts")["folders"] == ["a/", "b/"]


def test_move_level_missing_igroup_noop(cue_env, imgr):
    imgr.move_level("nope", 0, 1)  # must not raise


# ==========================================================================
# persistence -- on-disk JSON is the source of truth
# ==========================================================================


def test_igroups_survive_manager_rebuild(cue_env):
    m1 = CueIntensityManager(cue_env.db)
    m1.create_igroup("Impacts")
    m1.add_folder("Impacts", "a/")
    m2 = CueIntensityManager(cue_env.db)  # fresh manager, same db
    assert m2.list_igroups() == ["Impacts"]
    assert m2.get_igroup("Impacts")["folders"] == ["a/"]


def test_database_intensity_preset_type(cue_env):
    assert cue_env.db._preset_dir(CUE_INTENSITY_PRESET_TYPE) == cue_env.paths.intensity_preset_dir
    # db.open() created the dir.
    assert os.path.isdir(cue_env.paths.intensity_preset_dir)
