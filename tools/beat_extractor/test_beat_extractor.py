"""Pure-logic tests for beat_extractor -- no ffmpeg needed."""

import argparse
import csv
import os
import tempfile

import numpy as np

from beat_extractor import (
    _clear_dir,
    build_parser,
    _find_subthreshold_beats,
    _intensity_pass,
    _merge_beats,
    _peak_envelope,
    _refine_clip_end,
    _refine_clip_start,
    _tier_counts,
    _write_outputs,
    build_clips,
    classify_gaps,
    clip_indices,
    detect_beats,
    filter_duration,
    filter_loudness,
    parse_timestamp,
    read_labels,
    read_wav,
    write_report,
    write_wav,
)

import beat_extractor as _be

SR = 44100


def _beat(sr, dur, freq=600.0, amp=0.8):
    """One spike+decay: sharp attack, exponential decay tail."""
    t = np.arange(int(dur * sr)) / sr
    attack = np.exp(-t * 400.0)
    return amp * attack * np.sin(2.0 * np.pi * freq * t)


def _ambient(sr, dur, amp=0.01):
    """Low-level stationary noise (room tone)."""
    return amp * np.random.default_rng(0).normal(size=int(dur * sr))


def _make_signal(beats, gap_amp=0.01, sr=SR):
    """Build a 4-beat window signal with quiet gaps."""
    pieces = []
    for b in beats:
        pieces.append(b)
        pieces.append(_ambient(sr, 0.4, gap_amp))
    return np.concatenate(pieces)


# ---------------------------------------------------------------------------
# parse_timestamp


class TestParseTimestamp(object):
    def test_raw_seconds(self):
        assert parse_timestamp("13.5") == 13.5

    def test_mm_ss(self):
        assert parse_timestamp("01:30") == 90.0

    def test_hh_mm_ss_fractional(self):
        assert parse_timestamp("00:13:10.448") == 13 * 60 + 10.448

    def test_whitespace(self):
        assert parse_timestamp(" 5 ") == 5.0

    def test_garbage(self):
        import pytest
        with pytest.raises(ValueError):
            parse_timestamp("banana")


# ---------------------------------------------------------------------------
# detection


class TestDetectBeats(object):
    def test_finds_four_beats(self):
        beats = [_beat(SR, 0.15) for _ in range(4)]
        x = _make_signal(beats)
        found = detect_beats(x, SR, threshold=0.15, max_lead_in_s=0.08)
        assert len(found) == 4
        # each beat's peak should be well above threshold
        assert all(b["peak"] > 0.6 for b in found)

    def test_quiet_noise_does_not_trigger(self):
        x = _ambient(SR, 2.0, amp=0.01)  # well below threshold 0.15
        found = detect_beats(x, SR, threshold=0.15, max_lead_in_s=0.08)
        assert len(found) == 0

    def test_crossing_before_peak(self):
        x = np.zeros(int(0.5 * SR))
        x[10000:11000] = 0.8 * np.hanning(1000)
        found = detect_beats(x, SR, threshold=0.15, max_lead_in_s=0.08)
        assert len(found) == 1
        b = found[0]
        assert b["crossing_i"] < b["peak_i"]
        assert b["peak_i"] == 10000 + 499  # peak of hanning window


class TestRefineClipStart(object):
    def test_no_buildup_starts_near_spike(self):
        x = np.zeros(int(0.3 * SR))
        x[5000:5200] = 0.9
        start = _refine_clip_start(x, SR, peak_i=5100, max_lead_in_s=0.08)
        # walk-back follows the plateau then stops at the base (index 5000)
        assert 5000 <= start <= 5100

    def test_buildup_is_kept(self):
        x = np.zeros(int(0.3 * SR))
        # slow ramp up to the spike (real attack buildup)
        n = 2000
        x[4000:4000 + n] = 0.9 * np.linspace(0.05, 1.0, n)
        x[4000 + n:4000 + n + 200] = 0.9
        start = _refine_clip_start(x, SR, peak_i=4000 + n + 100, max_lead_in_s=0.08)
        # should walk all the way back to the base of the ramp
        assert start <= 4000 + 5

    def test_buildup_capped_by_max_lead(self):
        x = np.zeros(int(1.0 * SR))
        n = int(0.5 * SR)  # way over the 80ms cap
        x[1000:1000 + n] = 0.9 * np.linspace(0.0, 1.0, n)
        peak_i = 1000 + n
        start = _refine_clip_start(x, SR, peak_i, max_lead_in_s=0.08)
        assert peak_i - start <= 0.08 * SR + 10


class TestRefineClipEnd(object):
    def _two_spikes(self, gap_amp=0.001):
        """Two spikes separated by a quiet gap.

        Returns (x, peak0, cross1): the first spike's peak index and the
        second spike's crossing (first sample >= threshold).
        """
        sr = SR
        x = np.zeros(int(0.8 * sr))
        n_rise = 60
        # first spike: fast rise to the peak, then a decaying tail
        x[2000:2000 + n_rise] = 0.8 * np.linspace(0.02, 1.0, n_rise)
        x[2000 + n_rise:2000 + n_rise + 600] = np.exp(
            -np.arange(600) / 120.0) * 0.8
        # quiet gap (ambient noise floor)
        x[2600:16000] = gap_amp * np.random.default_rng(1).normal(
            size=16000 - 2600)
        # second spike: rises past threshold
        x[16000:16000 + n_rise] = 0.8 * np.linspace(0.02, 1.0, n_rise)
        x[16000 + n_rise:16000 + n_rise + 600] = np.exp(
            -np.arange(600) / 120.0) * 0.8
        peak0 = 2000 + n_rise - 1  # top of the first spike's rise
        cross1 = 16000 + int(np.argmax(np.abs(x[16000:]) >= 0.15))
        return x, peak0, cross1

    def test_cuts_at_trough_before_next_attack(self):
        x, peak0, cross1 = self._two_spikes()
        end = _refine_clip_end(x, SR, peak0, cross1)
        # end lands in the quiet gap, before the next spike's rise
        assert peak0 < end < cross1
        # the sample right before end is quiet (ambient floor), so the clip
        # never swallows the next beat's attack rise
        assert abs(x[end - 1]) < 0.05

    def test_excludes_next_attack_rise(self):
        x, peak0, cross1 = self._two_spikes()
        end = _refine_clip_end(x, SR, peak0, cross1)
        # end stops before the crossing, which is mid-attack of beat two
        assert end < cross1
        # the tail up to the end is at/below the ambient floor, not rising
        assert np.abs(x[end - 5:end]).max() < 0.05


class TestFindSubthresholdBeats(object):
    """A real impact below the amplitude threshold in a quiet gap must be
    recovered as its own beat, so a clip that swallowed it gets split."""

    def _three_beats(self, gap_amp=0.01):
        """primary (0.8) + sub-threshold secondary (0.3) + third (0.9)."""
        sr = SR
        b1 = _beat(sr, 0.15, amp=0.8)
        b2 = _beat(sr, 0.15, amp=0.3)
        b3 = _beat(sr, 0.15, amp=0.9)
        return np.concatenate([b1, _ambient(sr, 0.4, gap_amp),
                               b2, _ambient(sr, 0.4, gap_amp), b3])

    def test_recovers_subthreshold_second_beat(self):
        x = self._three_beats()
        beats = detect_beats(x, SR, threshold=0.5, max_lead_in_s=0.08)
        assert len(beats) == 2  # 0.3 sits below the 0.5 threshold
        extra = _find_subthreshold_beats(x, SR, beats, 0.08)
        assert len(extra) == 1
        # sits between the two detected peaks, at the planted 0.3 level
        assert beats[0]["peak_i"] < extra[0]["peak_i"] < beats[1]["peak_i"]
        assert extra[0]["peak"] > 0.25

    def test_clean_gap_finds_nothing(self):
        x = np.concatenate([_beat(SR, 0.15, amp=0.8),
                            _ambient(SR, 0.4),
                            _beat(SR, 0.15, amp=0.9)])
        beats = detect_beats(x, SR, threshold=0.5, max_lead_in_s=0.08)
        assert len(beats) == 2
        assert _find_subthreshold_beats(x, SR, beats, 0.08) == []

    def test_bump_on_elevated_floor_not_a_beat(self):
        # a 0.22 bump over an elevated floor passes the size ratio
        # (0.22 >= 0.25*0.8) but rises off ~0.05 of floor, not out of silence
        # (contrast < 6) -- tail ring / hum, not a real separate beat
        sr = SR
        x = np.concatenate([
            _beat(sr, 0.15, amp=0.8),
            _ambient(sr, 0.4, amp=0.02),   # elevated floor (1ms env ~0.05)
            _beat(sr, 0.15, amp=0.22),      # passes ratio, lacks contrast
            _ambient(sr, 0.4, amp=0.02),
            _beat(sr, 0.15, amp=0.9),
        ])
        beats = detect_beats(x, sr, threshold=0.5, max_lead_in_s=0.08)
        assert len(beats) == 2
        assert _find_subthreshold_beats(x, sr, beats, 0.08) == []

    def test_recovers_secondary_in_last_beats_tail(self):
        # a sub-threshold impact swallowed by the LAST beat is the win013
        # failure mode: the last clip ends at the window end, so the second
        # beat lives after the final detected crossing, not between two.
        sr = SR
        x = np.concatenate([
            _beat(sr, 0.15, amp=0.8),
            _ambient(sr, 0.4),
            _beat(sr, 0.15, amp=0.6),
            _ambient(sr, 0.4),
            _beat(sr, 0.15, amp=0.3),       # sub-threshold, after the last
            _ambient(sr, 0.2),
        ])
        beats = detect_beats(x, sr, threshold=0.5, max_lead_in_s=0.08)
        assert len(beats) == 2  # 0.3 sits below the 0.5 threshold
        extra = _find_subthreshold_beats(x, sr, beats, 0.08)
        assert len(extra) == 1
        assert extra[0]["peak_i"] > beats[-1]["peak_i"]  # past the last beat
        assert extra[0]["peak"] > 0.25
        # and it becomes a real clip boundary, splitting the long last beat
        merged = _merge_beats(beats, extra)
        build_clips(merged, len(x) / sr, sr, x, max_lead_in_s=0.08)
        assert len(merged) == 3
        assert merged[-1]["clip_end_s"] == len(x) / sr


class TestMergeBeats(object):
    def test_interleaves_and_sorts(self):
        b = [{"crossing_i": 100}, {"crossing_i": 300}]
        extra = [{"crossing_i": 200}, {"crossing_i": 50}]
        m = _merge_beats(b, extra)
        assert [x["crossing_i"] for x in m] == [50, 100, 200, 300]

    def test_no_extra_returns_detected(self):
        b = [{"crossing_i": 100}]
        assert _merge_beats(b, []) is b

    def test_overlap_dropped(self):
        b = [{"crossing_i": 100}, {"crossing_i": 200}]
        m = _merge_beats(b, [{"crossing_i": 200}])
        assert [x["crossing_i"] for x in m] == [100, 200]


class TestBuildClips(object):
    def _beats(self):
        b1 = {"crossing_i": 1000, "clip_start_i": 990}
        b2 = {"crossing_i": 2000, "clip_start_i": 1990}
        return [b1, b2]

    def test_boundaries(self):
        beats = self._beats()
        build_clips(beats, window_len_s=1.0, sr=SR)
        # without x, falls back to the next beat's refined attack base
        assert beats[0]["clip_end_s"] == 1990 / SR
        assert abs(beats[1]["clip_end_s"] - 1.0) < 1e-9  # last -> window end

    def test_last_beat_not_lost(self):
        beats = self._beats()
        build_clips(beats, 0.5, SR)
        assert beats[1]["duration_s"] > 0

    def test_end_in_silence_before_next_attack(self):
        # two beats separated by real silence; the first clip must end in the
        # quiet gap before the second beat's rise, never on its attack
        b0 = _beat(SR, 0.12)
        gap = _ambient(SR, 0.4, amp=0.005)
        b1 = _beat(SR, 0.12)
        x = np.concatenate([b0, gap, b1])
        beats = detect_beats(x, SR, threshold=0.15, max_lead_in_s=0.08)
        assert len(beats) == 2
        build_clips(beats, len(x) / SR, SR, x, max_lead_in_s=0.08)
        end0 = int(beats[0]["clip_end_s"] * SR)
        cross1 = beats[1]["crossing_i"]
        assert end0 < cross1  # ends before the next beat's attack
        assert abs(x[end0 - 1]) < 0.02  # last sample is quiet gap, not a rise


class TestClipIndices(object):
    def test_pads_back(self):
        i0, i1 = clip_indices(1.0, 1.4, SR, 0.025)
        assert i0 == int(1.0 * SR) - int(0.025 * SR)
        assert i1 == int(1.4 * SR)

    def test_clamps_to_zero(self):
        i0, _ = clip_indices(0.01, 0.1, SR, 0.05)
        assert i0 == 0

    def test_zero_roll_is_noop(self):
        i0, _ = clip_indices(0.5, 0.6, SR, 0.0)
        assert i0 == int(0.5 * SR)


# ---------------------------------------------------------------------------
# filters


class TestFilterDuration(object):
    def _beats(self, durations):
        return [{"duration_s": d, "status": None} for d in durations]

    def test_too_short_floor(self):
        beats = self._beats([0.1, 1.0, 1.05, 1.1])
        filter_duration(beats, min_beat_s=0.15, ratio=0.5)
        assert beats[0]["status"] == "too_short"
        assert beats[1]["status"] is None
        assert beats[2]["status"] is None
        assert beats[3]["status"] is None

    def test_duration_outlier(self):
        beats = self._beats([1.0, 1.0, 1.0, 0.2])
        filter_duration(beats, min_beat_s=0.08, ratio=0.5)
        # 0.2 clears the floor; median of survivors = 1.0, band 0.5..2.0
        assert beats[0]["status"] is None
        assert beats[3]["status"] == "duration_outlier"

    def test_band_recorded(self):
        beats = self._beats([1.0, 1.0, 1.0])
        filter_duration(beats, 0.05, 0.5)
        assert abs(beats[0]["duration_median"] - 1.0) < 1e-9
        assert beats[0]["duration_band"][0] == 0.5
        assert beats[0]["duration_band"][1] == 2.0

    def test_too_few_survivors_no_band(self):
        # 2 beats: the 4x-long outlier IS half the data, so the median can't
        # judge it -- the band must not engage (mirrors filter_loudness)
        beats = self._beats([0.5, 2.0])
        filter_duration(beats, 0.1, 0.5)
        assert all(b["status"] is None for b in beats)


class TestClassifyGaps(object):
    def _beat_signal(self, dur=0.3, gap_amp=0.01):
        x = _beat(SR, 0.12)
        x = np.concatenate([x, _ambient(SR, dur - 0.12, gap_amp)])
        return x

    def test_clean_gap(self):
        x = self._beat_signal(gap_amp=0.005)  # well under the -40 dBFS floor
        b = {"clip_start_s": 0.0, "clip_end_s": 0.3, "duration_s": 0.3, "status": None}
        classify_gaps(x, SR, [b], noise_floor_linear=10 ** (-40 / 20))
        assert b["status"] == "clean"

    def test_dirty_gap(self):
        x = self._beat_signal(gap_amp=0.3)  # loud chatter in the gap
        b = {"clip_start_s": 0.0, "clip_end_s": 0.3, "duration_s": 0.3, "status": None}
        classify_gaps(x, SR, [b], noise_floor_linear=10 ** (-40 / 20))
        assert b["status"] == "dirty"

    def test_already_skipped_not_touched(self):
        b = {"clip_start_s": 0.0, "clip_end_s": 0.3, "duration_s": 0.3,
             "status": "too_short"}
        x = self._beat_signal()
        classify_gaps(x, SR, [b], 0.001)
        assert b["status"] == "too_short"


class TestFilterLoudness(object):
    def _beats(self, peaks):
        return [{"peak_db": p, "status": "clean"} for p in peaks]

    def test_outlier_dropped(self):
        beats = self._beats([-10, -11, -9, -10, -30])  # -30 is 20 dB off
        filter_loudness(beats, outlier_db=6.0)
        statuses = [b["status"] for b in beats]
        assert statuses[-1] == "loudness_outlier"
        assert statuses[:4] == ["clean"] * 4

    def test_too_few_clean_engages_nothing(self):
        beats = self._beats([-10, -30])
        filter_loudness(beats, outlier_db=6.0)
        assert all(b["status"] == "clean" for b in beats)

    def test_band_recorded(self):
        beats = self._beats([-10, -10, -10, -10])
        filter_loudness(beats, 6.0)
        assert abs(beats[0]["loudness_median"] - (-10.0)) < 1e-9


# ---------------------------------------------------------------------------
# label files


class TestReadLabels(object):
    def _write(self, tmp_path, text):
        path = os.path.join(tmp_path, "labels.txt")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_parses_tab_separated(self, tmp_path):
        p = self._write(tmp_path, "12.939698\t14.298222\n15.358063\t16.822571\n")
        assert read_labels(p) == [(12.939698, 14.298222), (15.358063, 16.822571)]

    def test_ignores_label_text_and_blank_lines(self, tmp_path):
        p = self._write(tmp_path, "1.0\t2.0\tbeat one\n\n3.0\t4.0\t\n")
        assert read_labels(p) == [(1.0, 2.0), (3.0, 4.0)]

    def test_accepts_mm_ss_timestamps(self, tmp_path):
        p = self._write(tmp_path, "01:00\t02:00\n")
        assert read_labels(p) == [(60.0, 120.0)]

    def test_rejects_start_not_before_end(self, tmp_path):
        p = self._write(tmp_path, "5.0\t2.0\n")
        import pytest
        with pytest.raises(ValueError):
            read_labels(p)

    def test_rejects_garbage_line(self, tmp_path):
        p = self._write(tmp_path, "1.0\t2.0\nbanana\n")
        import pytest
        with pytest.raises(ValueError):
            read_labels(p)


# ---------------------------------------------------------------------------
# directory clearing


class TestClearDir(object):
    def test_removes_populated_tree(self, tmp_path):
        d = tmp_path / "out"
        (d / "sub").mkdir(parents=True)
        (d / "a.wav").write_text("x")
        (d / "sub" / "b.csv").write_text("y")
        _clear_dir(str(d))
        assert not os.path.exists(str(d))

    def test_missing_path_raises(self, tmp_path):
        import pytest
        with pytest.raises(OSError):
            _clear_dir(str(tmp_path / "nope"))


# ---------------------------------------------------------------------------
# WAV round trip


class TestWav(object):
    def test_round_trip(self):
        x = 0.5 * np.sin(2 * np.pi * 440 * np.arange(int(0.05 * SR)) / SR)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.wav")
            write_wav(path, x, SR)
            y, sr = read_wav(path)
        assert sr == SR
        assert len(y) == len(x)
        assert np.max(np.abs(y - x)) < 0.002  # 16-bit quantization


# ---------------------------------------------------------------------------
# _intensity_pass (flat vs grouped out dirs + per-mode report keys)


class TestIntensityPass(object):
    """_intensity_pass needs real beat WAVs (analyze_files reads them) but
    no ffmpeg -- write_wav provides the inputs."""

    def _make(self, tmp_path, intensity_mode):
        out = str(tmp_path / "out")
        beats = os.path.join(out, "beats")
        os.makedirs(beats)
        write_wav(os.path.join(beats, "beat_000.wav"),
                  _beat(SR, 0.3, freq=400.0, amp=0.2), SR)
        write_wav(os.path.join(beats, "beat_001.wav"),
                  _beat(SR, 0.3, freq=4000.0, amp=0.9), SR)
        beats = [
            {"candidate_index": 0, "clip_start_s": 1.0, "clip_end_s": 1.3,
             "duration_s": 0.3, "peak_db": -6.0},
            {"candidate_index": 1, "clip_start_s": 1.4, "clip_end_s": 1.7,
             "duration_s": 0.3, "peak_db": -1.0},
        ]
        args = argparse.Namespace(
            out=out,
            intensity_mode=intensity_mode,
            thresholds="adaptive",
            tiers=3,
            intensity_centroid_low=3000.0,
            intensity_centroid_high=4500.0,
            intensity_rms_ref=-30.0,
        )
        return beats, args

    def test_all_writes_grouped_tree_and_all_keys(self, tmp_path):
        beats, args = self._make(tmp_path, "all")
        res = _intensity_pass(beats, args)
        assert sorted(res) == ["bright_loud", "loud_peak", "loud_rms"]
        groups = os.path.join(args.out, "intensity_groups")
        for which in ("bright_loud", "loud_rms", "loud_peak"):
            root = os.path.join(groups, "intensity_by_%s" % which)
            tiers = sorted(d for d in os.listdir(root)
                           if d.startswith("intensity_"))
            assert tiers  # at least one tier folder holding copies
            n_files = sum(len(os.listdir(os.path.join(root, t)))
                          for t in tiers)
            assert n_files == 2
        for b in beats:
            # common features always attached; every mode scored + tiered
            assert b["centroid_hz"] > 0
            assert b["rms_db"] < 0
            assert b["intensity_peak_db"] < 0
            assert b["intensity_tier"] in (1, 2, 3)
            assert b["loud_rms_tier"] in (1, 2, 3)
            assert b["loud_peak_tier"] in (1, 2, 3)

    def test_single_loud_peak_writes_flat_layout(self, tmp_path):
        beats, args = self._make(tmp_path, "loud_peak")
        _intensity_pass(beats, args)
        assert not os.path.exists(os.path.join(args.out, "intensity_groups"))
        tiers = sorted(d for d in os.listdir(args.out)
                       if d.startswith("intensity_"))
        assert tiers
        assert len(os.listdir(os.path.join(args.out, tiers[0]))) >= 1

    def test_report_carries_every_axis_column(self, tmp_path):
        beats, args = self._make(tmp_path, "bright_loud")
        _intensity_pass(beats, args)
        report = os.path.join(args.out, "beat_report.csv")
        write_report(report, beats, 0.0, include_intensity=True)
        with open(report) as f:
            header = f.readline().strip().split(",")
        for col in ("centroid_hz", "rms_db", "intensity_score",
                    "intensity_tier", "intensity_peak_db",
                    "loud_rms_score", "loud_rms_tier",
                    "loud_peak_score", "loud_peak_tier"):
            assert col in header, col
        # bright_loud-only run: bright columns filled, loud axes blank
        with open(report) as f:
            rows = list(csv.reader(f))[1:]
        for row in rows:
            assert row[header.index("intensity_score")] != ""
            assert row[header.index("loud_rms_score")] == ""


# ---------------------------------------------------------------------------
# _write_outputs (clean -> beats/, non-clean -> beats_dropped/<cat>/)


class TestWriteOutputs(object):
    """_write_outputs slices every beat out of the analysis window; clean ones
    go processed to beats/, every other category to beats_dropped/<cat>/."""

    def _make(self, tmp_path):
        out = str(tmp_path / "out")
        raw_dir = os.path.join(out, "_raw")
        beats_dir = os.path.join(out, "beats")
        dropped_dir = os.path.join(out, "beats_dropped")
        for d in (out, raw_dir, beats_dir, dropped_dir):
            os.makedirs(d)
        x = _ambient(SR, 1.5, 0.5)
        beats = [
            {"candidate_index": 0, "clip_start_s": 0.05, "clip_end_s": 0.35,
             "duration_s": 0.3, "peak_db": -10.0},
            {"candidate_index": 1, "clip_start_s": 0.40, "clip_end_s": 0.70,
             "duration_s": 0.3, "peak_db": -9.0, "status": "dirty"},
            {"candidate_index": 2, "clip_start_s": 0.75, "clip_end_s": 0.95,
             "duration_s": 0.2, "peak_db": -8.0, "status": "too_short"},
            {"candidate_index": 3, "clip_start_s": 1.00, "clip_end_s": 1.40,
             "duration_s": 0.4, "peak_db": -7.0, "status": "duration_outlier"},
        ]
        args = argparse.Namespace(pre_roll_ms=0.0, denoise=False,
                                  normalize=False, denoise_strength=12.0)
        return x, beats, args, raw_dir, beats_dir, dropped_dir

    def test_clean_processed_and_dropped_categorized(self, tmp_path, monkeypatch):
        x, beats, args, raw_dir, beats_dir, dropped_dir = self._make(tmp_path)
        # process_clip shells out to ffmpeg; stub it as a raw->processed copy
        monkeypatch.setattr(
            _be, "process_clip",
            lambda r, o, d, n, s: write_wav(o, read_wav(r)[0], SR))
        written, dropped = _write_outputs(beats, x, SR, args, raw_dir,
                                          beats_dir, dropped_dir)

        assert [w[0] for w in written] == [0]
        assert os.path.exists(os.path.join(raw_dir, "beat_000_raw.wav"))
        assert os.path.exists(os.path.join(beats_dir, "beat_000.wav"))

        assert sorted(set(c for _, c in dropped)) == [
            "dirty", "dropped_duration_outlier", "skipped_too_short"]
        assert os.path.exists(
            os.path.join(dropped_dir, "dirty", "beat_001.wav"))
        assert os.path.exists(
            os.path.join(dropped_dir, "skipped_too_short", "beat_002.wav"))
        assert os.path.exists(
            os.path.join(dropped_dir, "dropped_duration_outlier",
                         "beat_003.wav"))
        # nothing clean leaked into a category dir, nothing dropped into beats/
        assert sorted(os.listdir(beats_dir)) == ["beat_000.wav"]


# CLI: --intensity-mode alone gates the intensity pass


class TestIntensityCli(object):
    """--intensity is gone; --intensity-mode (default None) turns the pass on."""

    def test_default_off(self):
        args = build_parser().parse_args(["song.mp4"])
        assert args.intensity_mode is None

    def test_intensity_mode_enables_pass(self):
        args = build_parser().parse_args(["song.mp4", "--intensity-mode",
                                          "loud_rms"])
        assert args.intensity_mode == "loud_rms"

    def test_old_intensity_flag_rejected(self):
        import pytest
        with pytest.raises(SystemExit):
            build_parser().parse_args(["song.mp4", "--intensity"])


class TestVerboseCli(object):
    """-v/--verbose opts into per-window and per-beat detail lines."""

    def test_default_off(self):
        assert build_parser().parse_args(["song.mp4"]).verbose is False

    def test_long_and_short_flags(self):
        assert build_parser().parse_args(
            ["song.mp4", "--verbose"]).verbose is True
        assert build_parser().parse_args(
            ["song.mp4", "-v"]).verbose is True


class TestTierCounts(object):
    """_tier_counts groups clean beats per mode's tier, matching intensity_N/."""

    def test_counts_clean_by_tier(self):
        beats = [
            {"status": "clean", "intensity_tier": 1},
            {"status": "clean", "intensity_tier": 1},
            {"status": "clean", "intensity_tier": 3},
            {"status": "dirty", "intensity_tier": 2},
            {"status": "clean"},  # no tier attached -- pass never scored it
        ]
        assert _tier_counts(beats, "bright_loud") == {1: 2, 3: 1}

    def test_loud_mode_uses_own_key(self):
        beats = [
            {"status": "clean", "loud_rms_tier": 2},
            {"status": "clean", "loud_rms_tier": 2},
            {"status": "clean", "loud_rms_tier": 1},
        ]
        assert _tier_counts(beats, "loud_rms") == {1: 1, 2: 2}
        assert _tier_counts(beats, "bright_loud") == {}  # no intensity_tier

    def test_empty_when_no_clean(self):
        assert _tier_counts([{"status": "dirty"}], "loud_peak") == {}
