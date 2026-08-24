# -*- coding: utf-8 -*-
# Tests for cue_lib.intensity.banding -- gap-aware banding (slice 1, pure).
# Auto mapping: sorted variants cut at the N-1 largest adjacent gaps; uniform
# ties break to the most even split (level = ceil((rank+1)*N/count)).  Slowest
# band = Level 1.  <2 distinct speeds -> single band (no intensity); off-list
# runtime speeds snap to the nearest listed variant.

from cue_lib.intensity.banding import _cue_band_speeds, _cue_resolve_level


# ==========================================================================
# _cue_band_speeds -- level per sorted distinct variant
# ==========================================================================


def test_uniform_speeds_even_split():
    # The design's canonical case: all gaps equal -> plain even split.
    speeds, levels = _cue_band_speeds([0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4], 3)
    assert speeds == [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
    assert levels == [1, 1, 1, 2, 2, 2, 3, 3, 3]


def test_uniform_speeds_n2_even_split():
    speeds, levels = _cue_band_speeds([0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4], 2)
    assert levels == [1, 1, 1, 1, 2, 2, 2, 2, 2]


def test_clustered_largest_gap_cuts():
    # Gaps .4,.1,.1,.1,.8 -> cut at .8 and .4: {.5}, {.9,1,1.1,1.2}, {2}.
    speeds, levels = _cue_band_speeds([0.5, 0.9, 1, 1.1, 1.2, 2], 3)
    assert levels == [1, 2, 2, 2, 2, 3]


def test_clustered_n2_cuts_only_largest_gap():
    # N=2: only the .8 gap is cut; the .4 and .1 gaps stay inside a band.
    speeds, levels = _cue_band_speeds([0.5, 0.9, 1, 1.1, 1.2, 2], 2)
    assert levels == [1, 1, 1, 1, 1, 2]


def test_more_bands_than_variants_unreachable_low_levels():
    # N=5 on 3 variants: ceil formula maps ranks to L2,L4,L5 (softest empty).
    speeds, levels = _cue_band_speeds([1, 1.5, 2], 5)
    assert levels == [2, 4, 5]


def test_n_equals_variant_count_one_per_band():
    speeds, levels = _cue_band_speeds([1, 1.5, 2], 3)
    assert levels == [1, 2, 3]


def test_single_speed_no_intensity():
    speeds, levels = _cue_band_speeds([1.0], 3)
    assert speeds == [1.0]
    assert levels == [1]


def test_two_identical_speeds_single_band():
    speeds, levels = _cue_band_speeds([1.0, 1.0], 3)
    assert speeds == [1.0]
    assert levels == [1]


def test_empty_variant_list():
    speeds, levels = _cue_band_speeds([], 3)
    assert speeds == []
    assert levels == []


def test_unsorted_input_sorted_output():
    # count=3, n=2: ceil formula -> 1, ceil(4/3)=2, ceil(6/3)=2.
    speeds, levels = _cue_band_speeds([2, 1, 1.5], 2)
    assert speeds == [1, 1.5, 2]
    assert levels == [1, 2, 2]


def test_tied_top_gaps_prefer_even_bands():
    # Three .3 gaps, two slots: cuts at {0,2} give band sizes 1,2,3, the most
    # even of the maximal-gap sets (lexicographic first on the tie).
    speeds, levels = _cue_band_speeds([0, 3, 6, 9, 10, 11], 3)
    assert levels == [1, 2, 2, 3, 3, 3]


# ==========================================================================
# _cue_resolve_level -- snap an off-list runtime speed to its band
# ==========================================================================


def _bands(variants, n):
    return _cue_band_speeds(variants, n)


def test_resolve_level_exact_speed():
    speeds, levels = _bands([0.5, 0.9, 1, 1.1, 1.2, 2], 3)
    assert _cue_resolve_level(1.1, speeds, levels) == 2
    assert _cue_resolve_level(2.0, speeds, levels) == 3


def test_resolve_level_snaps_nearest():
    speeds, levels = _bands([0.5, 0.9, 1, 1.1, 1.2, 2], 3)
    assert _cue_resolve_level(0.6, speeds, levels) == 1  # nearest .5
    assert _cue_resolve_level(1.9, speeds, levels) == 3  # nearest 2
    assert _cue_resolve_level(0.2, speeds, levels) == 1  # below slowest
    assert _cue_resolve_level(5.0, speeds, levels) == 3  # above fastest


def test_resolve_level_single_band():
    speeds, levels = _bands([1.0], 3)
    assert _cue_resolve_level(0.5, speeds, levels) == 1
    assert _cue_resolve_level(3.0, speeds, levels) == 1


def test_resolve_level_empty_bands():
    assert _cue_resolve_level(1.0, [], []) == 1
