# -*- coding: utf-8 -*-
# Tests for cue_lib.intensity resolution -- the speed->level chain, hook
# detection, multiplier lookup, and the per-video toggles.  Pure logic: an
# injected resolve_files identity resolver stands in for the SFX library, so no
# _cue reads are needed.

import pytest

from cue_lib.intensity import CueIntensityFlags, CueIntensityManager
from cue_lib.intensity.intensity import _cue_intensity_volume_mult


@pytest.fixture
def imgr(cue_env):
    """The intensity manager on the cue_env fixture's real db/paths."""
    return CueIntensityManager(cue_env.db)


def _resolve(files):
    # type: (list) -> list
    return [f for f in files if f != "hard/" or True]  # identity resolver


def _two_level(cue_env):
    """An igroup with two levels: soft (L1) + hard (L2)."""
    m = CueIntensityManager(cue_env.db)
    assert m._presets.create("Impacts") is None
    assert m.add_level("Impacts") == 1
    assert m.add_level_file("Impacts", 1, "soft/") is None
    assert m.add_level("Impacts") == 2
    assert m.add_level_file("Impacts", 2, "hard/") is None
    return m


# ==========================================================================
# resolve_pool_intensity -- full speed -> level -> files chain
# ==========================================================================


def test_resolve_pool_intensity_unhooked_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_pool_intensity(None, None, 1.0, [1.0], resolve_files=_resolve) is None


def test_resolve_pool_intensity_missing_group_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_pool_intensity("Nope", 1, 1.0, [1.0], resolve_files=_resolve) is None


def test_resolve_pool_intensity_bands_speed_to_level(cue_env):
    m = _two_level(cue_env)
    r = m.resolve_pool_intensity("Impacts", 1, 0.7, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    assert r.level == 1
    assert r.volume_mult == 1.0

    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    assert r.level == 2
    assert r.volume_mult == 1.25


def test_resolve_pool_intensity_enabled_off_plays_pinned_level(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(enabled=False)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], flags, _resolve)
    assert r is not None
    assert r.level == 1
    assert r.volume_mult == 1.0
    assert r.freq_mult == 1.0


def test_resolve_pool_intensity_volume_off_zeroes_volume_only(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(volume=False)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], flags, _resolve)
    assert r is not None
    assert r.level == 2
    assert r.volume_mult == 1.0  # toggle off
    assert r.freq_mult == 1.5  # still on


def test_resolve_pool_intensity_frequency_off_zeroes_freq_only(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(frequency=False)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], flags, _resolve)
    assert r is not None
    assert r.level == 2
    assert r.volume_mult == 1.25
    assert r.freq_mult == 1.0


def test_resolve_pool_intensity_sfx_levels_off_plays_pinned_level_scaled(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(sfx_levels=False)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], flags, _resolve)
    assert r is not None
    assert r.level == 2  # active level still drives scaling
    assert r.volume_mult == 1.25
    assert r.files == ["soft/"]  # pinned level's files play


def test_resolve_pool_intensity_no_variants_plays_pinned_level(cue_env):
    m = _two_level(cue_env)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [], resolve_files=_resolve)
    assert r is not None
    assert r.level == 1
    assert r.files == ["soft/"]


def test_resolve_pool_intensity_same_variants_consistent(cue_env):
    m = _two_level(cue_env)
    a = m.resolve_pool_intensity("Impacts", 1, 0.7, [0.7, 1.0, 1.3], resolve_files=_resolve)
    b = m.resolve_pool_intensity("Impacts", 1, 0.7, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert a is not None and b is not None
    assert (a.level, a.files, a.volume_mult) == (b.level, b.files, b.volume_mult)


# ==========================================================================
# resolve_video_intensity -- a video's active intensity (first hooked pool)
# ==========================================================================


def test_resolve_video_intensity_first_hooked_pool_wins(cue_env):
    m = _two_level(cue_env)
    hooks = [None, {"name": "Impacts", "level": 1}]
    r = m.resolve_video_intensity(hooks, 1.3, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    assert r.group == "Impacts"


def test_resolve_video_intensity_no_hooked_pool_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_video_intensity([None], 1.0, [1.0], resolve_files=_resolve) is None
    assert m.resolve_video_intensity([], 1.0, [1.0, 1.3], resolve_files=_resolve) is None


# ==========================================================================
# current_level -- (level, total) without file resolution
# ==========================================================================


def test_current_level_unhooked_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.current_level([None], 1.0, [0.7, 1.0, 1.3]) is None


def test_current_level_no_variants_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.current_level([{"name": "Impacts", "level": 1}], 1.0, []) is None
    assert m.current_level([{"name": "Impacts", "level": 1}], 1.0, None) is None


def test_current_level_master_off_is_none(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(enabled=False)
    assert m.current_level([{"name": "Impacts", "level": 1}], 1.3, [0.7, 1.0, 1.3], flags) is None


def test_current_level_bands_speed_to_level(cue_env):
    m = _two_level(cue_env)
    # 2 levels over [0.7, 1.0, 1.3]: 0.7 -> L1 (soft), 1.0/1.3 -> L2 (hard).
    assert m.current_level([{"name": "Impacts", "level": 1}], 0.7, [0.7, 1.0, 1.3]) == (1, 2)
    assert m.current_level([{"name": "Impacts", "level": 1}], 1.3, [0.7, 1.0, 1.3]) == (2, 2)


def test_current_level_first_hooked_pool_wins(cue_env):
    m = _two_level(cue_env)
    hooks = [None, {"name": "Impacts", "level": 1}]
    assert m.current_level(hooks, 1.3, [0.7, 1.0, 1.3]) == (2, 2)


def test_current_level_empty_pools_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.current_level([], 1.0, [0.7, 1.0, 1.3]) is None


# ==========================================================================
# video_hook -- the igroup of a video's first hooked pool
# ==========================================================================


def test_video_hook_first_group(cue_env):
    m = _two_level(cue_env)
    assert m.video_hook([None, {"name": "Impacts", "level": 2}]) == "Impacts"
    assert m.video_hook([None]) is None
    assert m.video_hook([]) is None


# ==========================================================================
# is_pool_intensity_active -- per-pool "intensity is live" predicate
# ==========================================================================


def test_is_pool_intensity_active(cue_env):
    m = _two_level(cue_env)
    assert m.is_pool_intensity_active("Impacts", [0.7, 1.0, 1.3]) is True
    assert m.is_pool_intensity_active(None, [0.7, 1.0, 1.3]) is False
    assert m.is_pool_intensity_active("Impacts", [1.0]) is False


def test_is_pool_intensity_active_toggle_off_is_false(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(enabled=False)
    assert m.is_pool_intensity_active("Impacts", [0.7, 1.0, 1.3], flags) is False


def test_is_pool_intensity_active_fewer_than_two_variants_is_false(cue_env):
    m = _two_level(cue_env)
    assert m.is_pool_intensity_active("Impacts", [1.0]) is False
    assert m.is_pool_intensity_active("Impacts", []) is False
    assert m.is_pool_intensity_active("Impacts", None) is False


# ==========================================================================
# Per-video toggles -- CueIntensityFlags + flags_from_entry
# ==========================================================================


def test_flags_from_entry_defaults_all_on(cue_env):
    m = CueIntensityManager(cue_env.db)
    f = m.flags_from_entry(None)
    assert (f.enabled, f.sfx_levels, f.volume, f.frequency) == (True, True, True, True)
    f = m.flags_from_entry({})
    assert (f.enabled, f.sfx_levels, f.volume, f.frequency) == (True, True, True, True)


def test_flags_from_entry_reads_fields(cue_env):
    m = CueIntensityManager(cue_env.db)
    f = m.flags_from_entry({"intensity": {"enabled": False, "sfx_levels": False, "volume": False, "frequency": False}})
    assert (f.enabled, f.sfx_levels, f.volume, f.frequency) == (False, False, False, False)


# ==========================================================================
# _cue_intensity_volume_mult -- the clamp baked into resolution.volume_mult
# ==========================================================================


def test_volume_mult_identity():
    assert _cue_intensity_volume_mult(1.0) == 1.0


def test_volume_mult_caps_at_max():
    assert _cue_intensity_volume_mult(3.0) == 1.25


def test_volume_mult_floor_never_lowers():
    assert _cue_intensity_volume_mult(0.5) == 1.0


def test_volume_mult_matches_resolution_baked_scale(cue_env):
    # resolve_pool_intensity bakes clamp(vm) into the resolution's volume_mult;
    # the fire path multiplies it into the pool volume.  The clamp function
    # must produce exactly the baked value.
    m = _two_level(cue_env)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    _, vm = m.level_multipliers("Impacts", r.level)
    assert r.volume_mult == _cue_intensity_volume_mult(vm)


# ==========================================================================
# variant_levels -- (speed, level) band map for the mapping inspector
# ==========================================================================


def test_variant_levels_even_two_bands(cue_env):
    m = _two_level(cue_env)
    assert m.variant_levels("Impacts", [0.6, 0.7, 0.8, 0.9, 1.0, 1.1]) == [
        (0.6, 1),
        (0.7, 1),
        (0.8, 1),
        (0.9, 2),
        (1.0, 2),
        (1.1, 2),
    ]


def test_variant_levels_even_three_bands(cue_env):
    m = CueIntensityManager(cue_env.db)
    assert m._presets.create("Three") is None
    assert m.add_level("Three") == 1
    assert m.add_level_file("Three", 1, "soft/") is None
    assert m.add_level("Three") == 2
    assert m.add_level_file("Three", 2, "hard/") is None
    assert m.add_level("Three") == 3
    assert m.add_level_file("Three", 3, "empty/") is None
    assert m.variant_levels("Three", [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]) == [
        (0.6, 1),
        (0.7, 1),
        (0.8, 1),
        (0.9, 2),
        (1.0, 2),
        (1.1, 2),
        (1.2, 3),
        (1.3, 3),
        (1.4, 3),
    ]


def test_variant_levels_unsorted_input_sorted(cue_env):
    m = _two_level(cue_env)
    assert m.variant_levels("Impacts", [1.1, 0.6, 0.9]) == [(0.6, 1), (0.9, 2), (1.1, 2)]


def test_variant_levels_single_level_none(cue_env):
    m = CueIntensityManager(cue_env.db)
    assert m._presets.create("One") is None
    assert m.add_level("One") == 1
    assert m.add_level_file("One", 1, "soft/") is None
    assert m.variant_levels("One", [0.7, 1.0, 1.3]) is None


def test_variant_levels_missing_group_none(cue_env):
    m = _two_level(cue_env)
    assert m.variant_levels("Nope", [0.7, 1.0]) is None


def test_variant_levels_no_variants_none(cue_env):
    m = _two_level(cue_env)
    assert m.variant_levels("Impacts", []) is None
