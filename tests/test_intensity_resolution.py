# -*- coding: utf-8 -*-
# Tests for cue_lib.intensity resolution -- hook detection, level->folder
# mapping, multiplier lookup, and the full speed->level chain (slice 3).
# Pure logic: an injected is_populated predicate stands in for the SFX
# library, so no _cue reads are needed.

import pytest

from cue_lib.intensity import CueIntensityFlags, CueIntensityManager
from cue_lib.intensity.intensity import _cue_intensity_volume_mult


@pytest.fixture
def imgr(cue_env):
    """The intensity manager on the cue_env fixture's real db/paths."""
    return CueIntensityManager(cue_env.db)


def _two_level(cue_env):
    """An igroup with two levels: soft (L1) + hard (L2)."""
    m = CueIntensityManager(cue_env.db)
    assert m.create_igroup("Impacts") is None
    assert m.add_folder("Impacts", "soft/") is None
    assert m.add_folder("Impacts", "hard/") is None
    return m


def _populated(folder):
    # type: (str) -> bool
    return folder in ("soft/", "hard/")


# ==========================================================================
# resolve_hook -- folder-in-pool -> (igroup, level_index)
# ==========================================================================

def test_resolve_hook_finds_matching_folder(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_hook(["unrelated.ogg", "soft/"]) == ("Impacts", 0)
    assert m.resolve_hook(["hard/"]) == ("Impacts", 1)


def test_resolve_hook_ignores_direct_files(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_hook(["soft/a.ogg", "b.ogg"]) is None


def test_resolve_hook_none_when_unhooked(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_hook(["other/"]) is None
    assert m.resolve_hook([]) is None
    assert m.resolve_hook(None) is None


def test_resolve_hook_first_registered_group_wins(cue_env):
    m = CueIntensityManager(cue_env.db)
    m.create_igroup("A")
    m.create_igroup("B")
    m.add_folder("A", "shared/")
    m.add_folder("B", "shared/")
    assert m.resolve_hook(["shared/"]) == ("A", 0)


# ==========================================================================
# level_folder -- 1-based level -> folder
# ==========================================================================

def test_level_folder_maps_level_to_folder(cue_env):
    m = _two_level(cue_env)
    assert m.level_folder("Impacts", 1) == "soft/"
    assert m.level_folder("Impacts", 2) == "hard/"


def test_level_folder_out_of_range_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.level_folder("Impacts", 0) is None
    assert m.level_folder("Impacts", 3) is None
    assert m.level_folder("nope", 1) is None


# ==========================================================================
# level_multipliers -- (volume_mult, freq_mult) for a level
# ==========================================================================

def test_level_multipliers_ramp(cue_env):
    m = _two_level(cue_env)
    assert m.level_multipliers("Impacts", 1) == (1.0, 1.0)
    assert m.level_multipliers("Impacts", 2) == (1.25, 2.0)


def test_level_multipliers_clamps_out_of_range(cue_env):
    m = _two_level(cue_env)
    assert m.level_multipliers("Impacts", 0) == (1.0, 1.0)
    assert m.level_multipliers("Impacts", 99) == (1.25, 2.0)


def test_level_multipliers_missing_group_identity(cue_env):
    m = _two_level(cue_env)
    assert m.level_multipliers("nope", 1) == (1.0, 1.0)


def test_level_multipliers_empty_igroup_identity(cue_env):
    m = CueIntensityManager(cue_env.db)
    m.create_igroup("Empty")
    assert m.level_multipliers("Empty", 1) == (1.0, 1.0)


# ==========================================================================
# resolve_intensity -- full speed -> level -> folder chain
# ==========================================================================

def test_resolve_intensity_unhooked_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_intensity(["plain.ogg"], 1.0, [1.0], _populated) is None


def test_resolve_intensity_no_variants_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_intensity(["soft/"], 1.0, [], _populated) is None


def test_resolve_intensity_bands_speed_to_level(cue_env):
    m = _two_level(cue_env)
    # 2 levels over [0.7, 1.0, 1.3]: 0.7 -> L1 (soft), 1.0/1.3 -> L2 (hard).
    r = m.resolve_intensity(["soft/"], 0.7, [0.7, 1.0, 1.3], _populated)
    assert r is not None
    assert r.group == "Impacts"
    assert r.level == 1
    assert r.folder == "soft/"
    assert r.files == ["soft/"]

    r = m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], _populated)
    assert r is not None
    assert r.level == 2
    assert r.folder == "hard/"
    assert r.files == ["hard/"]


def test_resolve_intensity_volume_mult_is_clamped(cue_env):
    m = _two_level(cue_env)
    # Level 2 ramps to the volume max (1.25) and freq max (2.0).
    r = m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], _populated)
    assert r is not None
    assert r.volume_mult == 1.25
    assert r.freq_mult == 2.0


def test_resolve_intensity_empty_level_folder_silent(cue_env):
    m = _two_level(cue_env)
    def pop(folder):
        return folder == "soft/"  # hard/ is empty
    # Fast band lands on L2 -> hard/ empty -> no files (silence).
    r = m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], pop)
    assert r is not None
    assert r.folder == "hard/"
    assert r.files == []
    # Scaling still follows the active level, not the (empty) folder.
    assert r.volume_mult == 1.25


def test_resolve_intensity_single_variant_single_level(cue_env):
    m = CueIntensityManager(cue_env.db)
    m.create_igroup("Solo")
    m.add_folder("Solo", "only/")
    r = m.resolve_intensity(["only/"], 1.0, [1.0], _populated)
    assert r is not None
    assert r.level == 1
    assert r.folder == "only/"
    assert r.volume_mult == 1.0
    assert r.freq_mult == 1.0


def test_resolve_intensity_same_variants_consistent(cue_env):
    m = _two_level(cue_env)
    a = m.resolve_intensity(["soft/"], 0.7, [0.7, 1.0, 1.3], _populated)
    b = m.resolve_intensity(["soft/"], 0.7, [0.7, 1.0, 1.3], _populated)
    assert a is not None and b is not None
    assert (a.level, a.folder, a.volume_mult) == (b.level, b.folder, b.volume_mult)


# ==========================================================================
# video_level -- global scale for a video's first hooked pool
# ==========================================================================

def test_video_level_uses_first_hooked_pool(cue_env):
    m = _two_level(cue_env)
    pools = [["plain.ogg"], ["soft/"], ["soft/", "hard/"]]
    r = m.video_level(pools, 1.3, [0.7, 1.0, 1.3], _populated)
    assert r is not None
    assert r.group == "Impacts"
    assert r.level == 2
    assert r.volume_mult == 1.25


def test_video_level_no_hooked_pool_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.video_level([["plain.ogg"], ["other.ogg"]], 1.0, [1.0], _populated) is None


def test_video_level_empty_pools_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.video_level([], 1.0, [1.0, 1.3], _populated) is None


# ==========================================================================
# Per-video toggles (slice 4) -- CueIntensityFlags + flags_from_entry
# ==========================================================================

def test_flags_from_entry_defaults_all_on(cue_env):
    m = CueIntensityManager(cue_env.db)
    f = m.flags_from_entry(None)
    assert (f.enabled, f.sfx_levels, f.volume, f.frequency) == (True, True, True, True)
    f = m.flags_from_entry({})
    assert (f.enabled, f.sfx_levels, f.volume, f.frequency) == (True, True, True, True)


def test_flags_from_entry_reads_fields(cue_env):
    m = CueIntensityManager(cue_env.db)
    f = m.flags_from_entry({
        "intensity_enabled": False,
        "intensity_sfx_levels": False,
        "intensity_volume": False,
        "intensity_frequency": False,
    })
    assert (f.enabled, f.sfx_levels, f.volume, f.frequency) == (False, False, False, False)


def test_resolve_intensity_master_off_is_none(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(enabled=False)
    assert m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], _populated, flags) is None


def test_resolve_intensity_volume_off_zeroes_volume_only(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(volume=False)
    r = m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], _populated, flags)
    assert r is not None
    assert r.level == 2
    assert r.folder == "hard/"
    assert r.volume_mult == 1.0      # toggle off
    assert r.freq_mult == 2.0        # still on


def test_resolve_intensity_frequency_off_zeroes_freq_only(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(frequency=False)
    r = m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], _populated, flags)
    assert r is not None
    assert r.folder == "hard/"
    assert r.volume_mult == 1.25
    assert r.freq_mult == 1.0


def test_resolve_intensity_sfx_levels_off_plays_pool_folder(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(sfx_levels=False)
    # The pool's own folder (soft/) plays while the level still drives scaling.
    r = m.resolve_intensity(["soft/"], 1.3, [0.7, 1.0, 1.3], _populated, flags)
    assert r is not None
    assert r.level == 2
    assert r.folder == "hard/"       # the level is still computed
    assert r.files == ["soft/"]      # but the pool's own folder plays
    assert r.volume_mult == 1.25
    assert r.freq_mult == 2.0


def test_video_level_master_off_is_none(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(enabled=False)
    assert m.video_level([["soft/"]], 1.3, [0.7, 1.0, 1.3], _populated, flags) is None


# ==========================================================================
# Hook detection + one-group-per-pool guardrail (slice 4)
# ==========================================================================

def test_group_for_folder_tagged_and_untagged(cue_env):
    m = _two_level(cue_env)
    assert m.group_for_folder("soft/") == "Impacts"
    assert m.group_for_folder("hard/") == "Impacts"
    assert m.group_for_folder("other/") is None


def test_pool_group_hooked_and_unhooked(cue_env):
    m = _two_level(cue_env)
    assert m.pool_group(["soft/"]) == "Impacts"
    assert m.pool_group(["plain.ogg", "soft/"]) == "Impacts"
    assert m.pool_group(["plain.ogg"]) is None
    assert m.pool_group([]) is None


def test_check_add_folder_allows_untagged(cue_env):
    m = _two_level(cue_env)
    assert m.check_add_folder(["soft/"], "plain.ogg") is None


def test_check_add_folder_allows_same_group(cue_env):
    m = _two_level(cue_env)
    # A second folder of the same group collapses to one hook -- harmless.
    assert m.check_add_folder(["soft/"], "hard/") is None


def test_check_add_folder_rejects_second_group(cue_env):
    m = _two_level(cue_env)
    m.create_igroup("Mouth")
    m.add_folder("Mouth", "lip/")
    err = m.check_add_folder(["soft/"], "lip/")
    assert err is not None
    assert "Mouth" in err and "Impacts" in err


# ==========================================================================
# _cue_intensity_volume_mult -- the clamp baked into resolution.volume_mult
# (moved here from the collapsed scaling.py; play_pool composes it with the
# pool volume)
# ==========================================================================

def test_volume_mult_identity():
    assert _cue_intensity_volume_mult(1.0) == 1.0


def test_volume_mult_caps_at_max():
    assert _cue_intensity_volume_mult(3.0) == 1.25


def test_volume_mult_floor_never_lowers():
    assert _cue_intensity_volume_mult(0.5) == 1.0


def test_volume_mult_matches_resolution_baked_scale(cue_env):
    # resolve_intensity bakes clamp(vm) into the resolution's volume_mult;
    # the fire path multiplies it into the pool volume.  The clamp function
    # must produce exactly the baked value.
    m = _two_level(cue_env)
    r = m.resolve_intensity(["soft/", "hard/"], 1.3, [0.7, 1.0, 1.3], is_populated=_populated)
    assert r is not None
    _, vm = m.level_multipliers("Impacts", r.level)
    assert r.volume_mult == _cue_intensity_volume_mult(vm)
