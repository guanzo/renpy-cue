"""Pure-logic tests for beat_extractor -- no ffmpeg needed."""

import os
import tempfile

import numpy as np

from beat_extractor import (
    _clear_dir,
    _peak_envelope,
    _refine_clip_end,
    _refine_clip_start,
    build_clips,
    classify_gaps,
    clip_indices,
    detect_beats,
    filter_duration,
    filter_loudness,
    parse_timestamp,
    read_labels,
    read_wav,
    write_wav,
)

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
