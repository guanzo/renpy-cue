"""Pure-logic tests for intensity.py -- no ffmpeg needed."""

import os
import wave

import numpy as np

from intensity import (
    DEFAULT_CENT_HIGH,
    DEFAULT_CENT_LOW,
    analyze_files,
    adaptive_boundaries,
    assign_tier,
    classify,
    copy_tiers,
    fixed_boundaries,
    intensity_score,
    peak_db,
    rms_db,
    read_wav,
    spectral_centroid,
)

SR = 44100


def _tone(freq, dur=0.3, amp=0.04):
    """A steady sine at freq. Default amp ~ loudnorm'd level (rms ~ -30 dBFS),
    so fixed-mode scores behave like real extracted beats."""
    t = np.arange(int(dur * SR)) / SR
    return amp * np.sin(2.0 * np.pi * freq * t)


def _write(dir_path, name, x):
    path = os.path.join(dir_path, name)
    write_wav(path, x, SR)
    return path


# ---------------------------------------------------------------------------
# features


class TestSpectralCentroid(object):
    def test_pure_sine_is_its_frequency(self):
        for freq in (200.0, 1000.0, 4000.0):
            c = spectral_centroid(_tone(freq), SR)
            # hann window + discrete FFT smear a bit; the peak still dominates
            assert abs(c - freq) / freq < 0.05, (freq, c)

    def test_higher_sine_brighter(self):
        assert spectral_centroid(_tone(4000), SR) > spectral_centroid(_tone(400), SR)


class TestRmsDb(object):
    def test_sine_rms(self):
        # sine amp a -> rms = a / sqrt(2)
        got = rms_db(_tone(440, amp=0.4))
        assert abs(got - 20.0 * np.log10(0.4 / np.sqrt(2))) < 0.05

    def test_louder_is_higher(self):
        assert rms_db(_tone(440, amp=0.8)) > rms_db(_tone(440, amp=0.2))


class TestPeakDb(object):
    def test_sine_peak_is_amplitude(self):
        # sine amp a -> peak = a
        got = peak_db(_tone(440, amp=0.4))
        assert abs(got - 20.0 * np.log10(0.4)) < 0.05

    def test_louder_is_higher(self):
        assert peak_db(_tone(440, amp=0.8)) > peak_db(_tone(440, amp=0.2))

    def test_peak_above_rms(self):
        # any nonzero signal peaks >= its rms, so peak_db >= rms_db
        assert peak_db(_tone(440, amp=0.4)) >= rms_db(_tone(440, amp=0.4))


class TestIntensityScore(object):
    def test_brighter_higher(self):
        assert intensity_score(4000, -30.0, -30.0) > intensity_score(2000, -30.0, -30.0)

    def test_louder_higher(self):
        assert intensity_score(3000, -25.0, -30.0) > intensity_score(3000, -35.0, -30.0)

    def test_brightness_loudness_tradeoff(self):
        # 1 kHz of brightness == 4 dB of loudness
        a = intensity_score(3000, -30.0, -30.0)
        b = intensity_score(4000, -34.0, -30.0)  # +1 kHz, -4 dB
        assert abs(a - b) < 1e-9


class TestAnalyzeFiles(object):
    def test_reads_each_file(self, tmp_path):
        p1 = _write(str(tmp_path), "a.wav", _tone(800))
        p2 = _write(str(tmp_path), "b.wav", _tone(3000))
        feats = analyze_files([p1, p2])
        assert len(feats) == 2
        names = {f["name"] for f in feats}
        assert names == {"a.wav", "b.wav"}
        by_name = {f["name"]: f for f in feats}
        assert by_name["a.wav"]["centroid_hz"] < by_name["b.wav"]["centroid_hz"]
        assert by_name["a.wav"]["rms_db"] < 0
        assert by_name["a.wav"]["peak_db"] < 0
        # score not yet assigned (rms_ref unknown until classify)
        assert "score" not in by_name["a.wav"]


# ---------------------------------------------------------------------------
# boundaries + assignment


class TestAdaptiveBoundaries(object):
    def test_single_boundary_for_two_tiers(self):
        # two well-separated clusters; the seam lands between them
        scores = [1.0, 1.1, 1.2, 5.0, 5.1, 5.2]
        bnds = adaptive_boundaries(scores, 2)
        assert len(bnds) == 1
        assert 2.0 < bnds[0] < 4.0

    def test_two_boundaries_for_three_tiers(self):
        scores = [1.0, 1.1, 5.0, 5.1, 9.0, 9.1]
        bnds = adaptive_boundaries(scores, 3)
        assert len(bnds) == 2
        assert 2.0 < bnds[0] < 4.0
        assert 6.0 < bnds[1] < 8.0

    def test_fewer_scores_than_tiers_degrades(self):
        # only 2 distinct gaps for 4 tiers -> fewer boundaries, no crash
        bnds = adaptive_boundaries([1.0, 1.1, 5.0], 4)
        assert len(bnds) == 2

    def test_single_score_no_boundaries(self):
        assert adaptive_boundaries([3.5], 3) == []


class TestFixedBoundaries(object):
    def test_three_tiers(self):
        bnds = fixed_boundaries(3000.0, 4500.0, 3)
        assert bnds == [3.0, 4.5]

    def test_two_tiers_uses_only_high(self):
        assert fixed_boundaries(3000.0, 4500.0, 2) == [4.5]

    def test_rejects_other_counts(self):
        import pytest
        with pytest.raises(ValueError):
            fixed_boundaries(3000.0, 4500.0, 4)


class TestAssignTier(object):
    def test_below_all(self):
        assert assign_tier(2.0, [3.0, 4.5]) == 1

    def test_between(self):
        assert assign_tier(3.7, [3.0, 4.5]) == 2

    def test_above_all(self):
        assert assign_tier(6.0, [3.0, 4.5]) == 3

    def test_exact_boundary_is_upper_tier(self):
        assert assign_tier(3.0, [3.0, 4.5]) == 2

    def test_no_boundaries_always_one(self):
        assert assign_tier(9.0, []) == 1

    def test_single_boundary_two_tiers(self):
        assert assign_tier(4.0, [4.5]) == 1
        assert assign_tier(4.6, [4.5]) == 2


# ---------------------------------------------------------------------------
# classify (score + tier together)


def _feats(scores_centroid, rms_vals, peak_vals=None):
    """Feature dicts with centroid/rms, and a peak a few dB above rms unless
    given explicitly (peak >= rms always, so +3 dB is the realistic shape)."""
    if peak_vals is None:
        peak_vals = [r + 3.0 for r in rms_vals]
    return [{"centroid_hz": c, "rms_db": r, "peak_db": p}
            for c, r, p in zip(scores_centroid, rms_vals, peak_vals)]


class TestClassify(object):
    def test_adaptive_splits_8_4_like_hand_sorted_library(self):
        # the real Impact7 pattern: 8 medium, 4 high -- bright/loud wins
        feats = _feats(
            [4458, 4192, 4605, 3693, 4027, 3786, 3863, 3537, 4388, 4278, 4342, 4069],
            [-30.4, -29.3, -31.1, -29.7, -32.1, -29.1, -30.2, -27.7,
             -28.4, -26.8, -26.0, -24.8])
        classify(feats, "adaptive", tiers=2)
        tiers = [f["tier"] for f in feats]
        assert tiers == [1] * 8 + [2] * 4

    def test_adaptive_three_tiers_finds_three_clusters(self):
        feats = _feats([1000, 1100, 1200, 5000, 5100, 9000, 9100], [-30] * 7)
        classify(feats, "adaptive", tiers=3)
        tiers = [f["tier"] for f in feats]
        assert sorted(tiers) == [1, 1, 1, 2, 2, 3, 3]

    def test_fixed_three_tiers(self):
        feats = _feats(
            [2000, 2500, 3500, 3500, 4800, 5200],
            [-30.0] * 6)
        classify(feats, "fixed", tiers=3,
                 cent_low=DEFAULT_CENT_LOW, cent_high=DEFAULT_CENT_HIGH)
        assert [f["tier"] for f in feats] == [1, 1, 2, 2, 3, 3]

    def test_fixed_rms_boost_crosses_centroid_boundary(self):
        # quiet bright beat stays low; the same centroid but louder crosses
        quiet = _feats([4200], [-30.0])
        loud = _feats([4200], [-24.0])
        classify(quiet, "fixed", tiers=3)
        classify(loud, "fixed", tiers=3)
        # boundary high = 4.5; loud gets (4.2 + 6/4) = 5.7 -> tier 3
        assert quiet[0]["tier"] == 2
        assert loud[0]["tier"] == 3

    def test_adaptive_uses_batch_median_rms(self):
        feats = _feats([4000, 4000], [-40.0, -20.0])
        classify(feats, "adaptive", tiers=2)
        # median rms -30: bright-but-quiet below median, same centroid louder
        assert feats[0]["tier"] == 1
        assert feats[1]["tier"] == 2

    def test_empty_is_safe(self):
        feats = []
        classify(feats, "adaptive", tiers=3)
        assert feats == []

    def test_unknown_mode(self):
        import pytest
        with pytest.raises(ValueError):
            classify(_feats([3000], [-30]), "banana")


class TestClassifyModes(object):
    """which= dispatch: loud_rms / loud_peak classify on their own axis."""

    def test_loud_rms_tracks_rms_order(self):
        # identical brightness, wide RMS spread -> loud_rms cuts by RMS
        feats = _feats([3000] * 6, [-40, -38, -35, -20, -18, -16])
        classify(feats, "adaptive", tiers=3, which="loud_rms")
        assert [f["tier"] for f in feats] == [1, 1, 2, 3, 3, 3]

    def test_loud_peak_tracks_peak_order(self):
        # identical RMS, peak spread -> loud_peak cuts by peak
        feats = _feats([3000] * 4, [-30] * 4, peak_vals=[-25, -24, -8, -7])
        classify(feats, "adaptive", tiers=2, which="loud_peak")
        assert [f["tier"] for f in feats] == [1, 1, 2, 2]

    def test_loud_only_ignores_fixed_mode(self):
        # --thresholds fixed is meaningless on a loudness axis; loud_rms still
        # cuts adaptively at the real cluster seam, not the fixed 4.5 boundary
        feats = _feats([5000] * 4, [-40, -39, -22, -21])
        classify(feats, "fixed", tiers=2, which="loud_rms")
        assert [f["tier"] for f in feats] == [1, 1, 2, 2]

    def test_axes_disagree_on_brightness_only(self):
        # same loudness, brightness spread: bright_loud sees the seam, the
        # loud-only axes can't -- proves the three axes are genuinely distinct
        feats = _feats([1000, 2000, 5000, 6000], [-30] * 4, peak_vals=[-24] * 4)
        seen = {}
        for which in ("bright_loud", "loud_rms", "loud_peak"):
            work = [dict(f) for f in feats]  # classify mutates in place
            classify(work, "adaptive", tiers=2, which=which)
            seen[which] = [f["tier"] for f in work]
        assert seen["bright_loud"] == [1, 1, 2, 2]
        # loud-only sees no loudness variation at all, so it cannot split
        # (all four land in one tier; the exact tier number doesn't matter)
        assert len(set(seen["loud_rms"])) == 1
        assert len(set(seen["loud_peak"])) == 1

    def test_unknown_which(self):
        import pytest
        with pytest.raises(ValueError):
            classify(_feats([3000], [-30]), "adaptive", which="banana")


# ---------------------------------------------------------------------------
# tiered copies


class TestCopyTiers(object):
    def _files(self, tmp_path):
        src = str(tmp_path / "src")
        os.makedirs(src)
        a = _write(src, "a.wav", _tone(800))
        b = _write(src, "b.wav", _tone(5000))
        return src, a, b

    def test_copies_into_tier_folders_preserving_names(self, tmp_path):
        src, a, b = self._files(tmp_path)
        feats = analyze_files([a, b])
        classify(feats, "fixed", tiers=2)  # low sine tier 1, high sine tier 2
        out = str(tmp_path / "out")
        written = copy_tiers(feats, out)
        assert len(written) == 2
        assert os.path.exists(os.path.join(out, "intensity_1", "a.wav"))
        assert os.path.exists(os.path.join(out, "intensity_2", "b.wav"))
        # originals untouched
        assert os.path.exists(a) and os.path.exists(b)

    def test_same_tier_same_folder(self, tmp_path):
        src = str(tmp_path / "src")
        os.makedirs(src)
        p1 = _write(src, "x.wav", _tone(800))
        p2 = _write(src, "y.wav", _tone(1200))
        feats = analyze_files([p1, p2])
        classify(feats, "fixed", tiers=2)
        out = str(tmp_path / "out")
        copy_tiers(feats, out)
        assert len(os.listdir(os.path.join(out, "intensity_1"))) == 2


# ---------------------------------------------------------------------------
# WAV round trip (needed so analyze_files is testable without ffmpeg)


def write_wav(path, x, sr):
    y = np.clip(x, -1.0, 1.0)
    data = (y * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


class TestWav(object):
    def test_round_trip(self):
        x = _tone(440, dur=0.05)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.wav")
            write_wav(path, x, SR)
            y, sr = read_wav(path)
        assert sr == SR
        assert len(y) == len(x)
        assert np.max(np.abs(y - x)) < 0.002  # 16-bit quantization
