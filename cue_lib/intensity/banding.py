# -*- coding: utf-8 -*-
# cue_lib/intensity/banding.py -- gap-aware banding (slice 1, pure engine math).
#
# Auto speed-to-intensity mapping: sort the pool's variant speeds, cut at the
# N-1 largest adjacent gaps (a greedy Jenks natural-breaks approximation), and
# tie-break uniform gaps to the most even split.  Slowest band = Level 1.
# The trigger engine caches a pool's (speeds, levels) band map and snaps each
# tick's runtime speed through _cue_resolve_level.

import itertools
import math

MYPY = False
if MYPY:
    from typing import List, Tuple  # pyright: ignore[reportUnusedImport]

# Belt-and-suspenders bound on the cut-set search.  Real variant lists are
# small (a pool's speed variants), so the exhaustive "most even" tie-break is
# cheap; a pathological input falls back to the plain even-split formula.
CUE_BAND_MAX_SETS = 50000

# Gap sums are float subtraction noise (0.7-0.6 != 0.8-0.7 exactly), so compare
# them rounded to this many decimals -- far below any real speed-step gap.
CUE_BAND_GAP_PRECISION = 6


def _ncr(n, r):
    # type: (int, int) -> int
    """Binomial coefficient, exact int math (Py2.7 has no math.comb)."""
    if r > n or r < 0:
        return 0
    r = min(r, n - r)
    num = 1
    for i in range(r):
        num = num * (n - i) // (i + 1)
    return num


def _band_sizes(count, cuts):
    # type: (int, Tuple[int, ...]) -> List[int]
    """Per-band speed counts for a sorted cut-index tuple (cuts separate
    speeds[i] and speeds[i+1]).  Last boundary is the final speed."""
    sizes = []
    start = 0
    for c in cuts + (count - 1,):
        sizes.append(c - start + 1)
        start = c + 1
    return sizes


def _band_evenness(sizes, count):
    # type: (List[int], int) -> float
    """Sum of squared deviations of band sizes from the even target; lower is
    more even.  Tie-break key among maximal-gap cut sets."""
    target = count / float(len(sizes))
    return sum((size - target) ** 2 for size in sizes)


def _cue_band_speeds(variants, n):
    # type: (List[float], int) -> Tuple[List[float], List[int]]
    """Banded levels for the sorted distinct variant speeds.

    Returns (speeds, levels): `speeds` ascending, `levels[i]` the 1-based
    intensity band (1 = slowest) for `speeds[i]`.  Fewer than 2 distinct
    speeds (or n < 2) yield a single level-1 band -- no intensity."""
    speeds = sorted(set(variants))
    count = len(speeds)
    if count < 2 or n < 2:
        return speeds, [1] * count

    # More bands than variants: only the even-split formula applies, leaving
    # the softest bands unreachable.
    if n >= count:
        return speeds, [int(math.ceil((rank + 1) * n / float(count))) for rank in range(count)]

    gaps = [speeds[i + 1] - speeds[i] for i in range(count - 1)]
    n_cuts = n - 1
    if _ncr(count - 1, n_cuts) > CUE_BAND_MAX_SETS:
        return speeds, [int(math.ceil((rank + 1) * n / float(count))) for rank in range(count)]

    # Cut at the n-1 largest gaps; among tied maximal-gap sets keep the most
    # even (lexicographic first on the tie).  Small inputs -> enumerate.
    best_cuts = ()
    best_key = None
    for cuts in itertools.combinations(range(count - 1), n_cuts):
        sizes = _band_sizes(count, cuts)
        gap_sum = round(sum(gaps[i] for i in cuts), CUE_BAND_GAP_PRECISION)
        key = (gap_sum, -_band_evenness(sizes, count))
        if best_key is None or key > best_key:
            best_key = key
            best_cuts = cuts

    levels = []
    band = 1
    cut_set = set(best_cuts)
    for i in range(count):
        levels.append(band)
        if i in cut_set:
            band += 1
    return speeds, levels


def _cue_resolve_level(speed, speeds, levels):
    # type: (float, List[float], List[int]) -> int
    """Intensity level for a runtime `speed`, snapping to the nearest listed
    variant.  Empty or single-band maps resolve to level 1."""
    if not speeds:
        return 1
    best_i = 0
    best_d = abs(speed - speeds[0])
    for i in range(1, len(speeds)):
        d = abs(speed - speeds[i])
        if d < best_d:
            best_d = d
            best_i = i
    return levels[best_i]
