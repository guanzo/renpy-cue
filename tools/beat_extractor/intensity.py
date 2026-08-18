#!/usr/bin/env python3
"""Intensity classifier for extracted impact beats.

Classifies a set of beat WAVs by perceived "intensity" -- brightness (spectral
centroid) plus loudness (RMS) -- and copies them into tiered subfolders
(intensity_1 < intensity_2 < ... < intensity_N), originals untouched.

It is the scoring + tiering engine behind beat_extractor's --intensity-mode
flag, and also runs standalone over any folder of WAVs:

    python3 intensity.py FOLDER --out tiers/ --tiers 3

Intensity is NOT pitch. Impact beats are noise-like (a thud has no meaningful
F0), so the perceptible "high vs low" is brightness: the amplitude-weighted
mean spectral frequency (spectral centroid). Loudness (RMS) is the second
axis -- a louder beat reads as more intense even at the same brightness.
Neither alone is reliable: a loud dull thud and a soft bright crack each look
wrong on one axis, right on the other. The 2D score combines both.

    score = centroid_khz + (rms_db - rms_ref) / 4.0

The /4.0 says "1 kHz of brightness is worth 4 dB of loudness" -- calibrated
against real impact libraries where both axes vary together. Higher score =
brighter and/or louder = more intense.

Three score axes (--intensity-mode):
  bright_loud -- the classic 2D score above. Default.
  loud_rms    -- loudness only, whole-clip RMS.
  loud_peak   -- loudness only, single loudest sample (no tail-length
                 contamination -- the honest "how hard did it land").
Loud-only variants are always adaptive: a fixed dB boundary needs per-source
calibration, and fixed centroid thresholds have no meaning on a loudness axis.

Two boundary modes:
  adaptive (default) -- rms_ref is the batch median, so the RMS term is
      relative; tier boundaries are placed at the LARGEST GAPS in the sorted
      scores, so the tiering discovers the batch's natural clusters instead of
      forcing equal-sized buckets. Reproduces a hand-sorted 8/4 library split
      exactly with --tiers 2.
  fixed -- rms_ref is an absolute constant (--intensity-rms-ref, default the
      typical RMS of a loudnorm'd beat) and boundaries come from
      --intensity-centroid-low/high, expressed as centroid-equivalent scores.
      Reproduces the same standard across batches regardless of their levels.

Dev tool, system Python 3. Deps: numpy, and ffmpeg only for the optional
--normalize (loudnorm) path. Not Ren'Py code -- no cue_lib constraints apply.
"""

from __future__ import print_function

import argparse
import glob
import os
import shutil
import subprocess
import tempfile
import wave

import numpy as np

# Score formula: 1 kHz of brightness ~= 4 dB of loudness.
RMS_DIV = 4.0
# Absolute RMS reference for fixed mode: the typical RMS (dBFS) of a beat that
# has been loudnorm'd to I=-16:TP=-1.5:LRA=11. Measured across impact libraries.
DEFAULT_RMS_REF = -30.0
# Fixed-mode centroid boundaries (Hz), tunable. Below low -> tier 1, above
# high -> tier 3, in between -> tier 2.
DEFAULT_CENT_LOW = 3000.0
DEFAULT_CENT_HIGH = 4500.0


# ---------------------------------------------------------------------------
# WAV I/O + feature extraction


def read_wav(path):
    """Read a WAV to a mono float array in [-1, 1] plus sample rate."""
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, sr


def _ffmpeg(*args):
    """Run ffmpeg, failing loudly on error."""
    cmd = ["ffmpeg", "-v", "error", "-y"] + list(args)
    subprocess.run(cmd, check=True)


def _normalize(path, out_path):
    """loudnorm a WAV to the same target beat_extractor uses (I=-16, TP=-1.5,
    LRA=11), so raw folders and processed beats score on the same level."""
    _ffmpeg("-i", path, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", out_path)


def spectral_centroid(x, sr):
    """Amplitude-weighted mean spectral frequency (Hz). Hann-windowed FFT over
    the whole clip -- brightness of the beat as a whole. Higher = brighter."""
    win = np.hanning(len(x))
    X = np.fft.rfft(x * win)
    mag = np.abs(X)
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    return float(np.sum(freqs * mag) / (np.sum(mag) + 1e-12))


def rms_db(x):
    """RMS level in dBFS."""
    return 20.0 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def peak_db(x):
    """Peak level in dBFS -- the single loudest sample."""
    return 20.0 * np.log10(np.max(np.abs(x)) + 1e-12)


def intensity_score(centroid_hz, rms, rms_ref):
    """The 2D intensity score. Higher = brighter and/or louder."""
    return centroid_hz / 1000.0 + (rms - rms_ref) / RMS_DIV


def analyze_files(paths, normalize=False):
    """Measure every file. Returns a list of feature dicts (path, name,
    centroid_hz, rms_db) -- score is added later, once rms_ref is known."""
    out = []
    for path in paths:
        if normalize:
            tag = "be_int_%d" % os.getpid()
            tmp = os.path.join(tempfile.gettempdir(), tag + ".wav")
            try:
                _normalize(path, tmp)
                x, sr = read_wav(tmp)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        else:
            x, sr = read_wav(path)
        out.append({
            "path": path,
            "name": os.path.basename(path),
            "centroid_hz": spectral_centroid(x, sr),
            "rms_db": rms_db(x),
            "peak_db": peak_db(x),
        })
    return out


# ---------------------------------------------------------------------------
# Boundaries + tier assignment


def adaptive_boundaries(scores, tiers):
    """N-1 boundaries at the largest gaps in the sorted scores.

    The batch's natural clusters are found by cutting at the biggest drops in
    the score distribution, so a hand-sorted library splits along the same
    seams (a quiet bright beat and a loud dull beat stay apart, because each
    keeps its cluster). Equal-count buckets would force a false 6/6 split on a
    genuine 8/4 library -- this does not. Returns fewer boundaries when the
    batch has fewer distinct gaps than tiers-1.
    """
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    n_cuts = min(tiers - 1, n - 1)
    if n_cuts <= 0:
        return []
    gaps = np.diff(s)
    idx = np.argsort(gaps)[::-1][:n_cuts]  # largest gaps first
    idx = np.sort(idx)  # back to ascending index order
    return [float(s[i] + s[i + 1]) / 2.0 for i in idx]


def fixed_boundaries(cent_low_hz, cent_high_hz, tiers):
    """Fixed-mode boundaries as centroid-equivalent scores.

    --tiers 2 uses only the high boundary (low/medium split collapses);
    --tiers 3 uses both. Scores are "centroid kHz + RMS boost", so a file
    louder than rms_ref lands above its raw centroid, a quieter one below.
    """
    if tiers == 2:
        return [cent_high_hz / 1000.0]
    if tiers == 3:
        return [cent_low_hz / 1000.0, cent_high_hz / 1000.0]
    raise ValueError("fixed thresholds support --tiers 2 or 3, got %d" % tiers)


def assign_tier(score, boundaries):
    """1-based tier. Below every boundary -> 1; one per boundary crossed."""
    if not boundaries:
        return 1
    return 1 + int(np.searchsorted(np.asarray(boundaries), score, side="right"))


def classify(features, mode, tiers=3, cent_low=DEFAULT_CENT_LOW,
             cent_high=DEFAULT_CENT_HIGH, rms_ref=DEFAULT_RMS_REF,
             which="bright_loud"):
    """Score + tier a list of feature dicts in place. Returns (features,
    boundaries, ref).

    mode: 'adaptive' or 'fixed' -- applies to bright_loud only; the loud-only
    variants are always adaptive (a fixed dB boundary needs per-source
    calibration, and fixed centroid thresholds mean nothing on a loudness
    axis).

    which: the score axis to classify on.
      bright_loud -- centroid + RMS (the classic 2D score).
      loud_rms    -- loudness only, RMS (whole-clip average energy).
      loud_peak   -- loudness only, peak (single loudest sample).
    Each feature gains 'score' and 'tier' in place.
    """
    if which == "bright_loud":
        if mode == "adaptive":
            ref = float(np.median([f["rms_db"] for f in features])) if features else rms_ref
            boundaries = adaptive_boundaries(
                [intensity_score(f["centroid_hz"], f["rms_db"], ref)
                 for f in features], tiers)
        elif mode == "fixed":
            ref = rms_ref
            boundaries = fixed_boundaries(cent_low, cent_high, tiers)
        else:
            raise ValueError("unknown mode: %r" % mode)
    elif which in ("loud_rms", "loud_peak"):
        key = "rms_db" if which == "loud_rms" else "peak_db"
        ref = float(np.median([f[key] for f in features])) if features else rms_ref
        boundaries = adaptive_boundaries([f[key] for f in features], tiers)
    else:
        raise ValueError("unknown which: %r" % which)
    for f in features:
        if which == "bright_loud":
            f["score"] = intensity_score(f["centroid_hz"], f["rms_db"], ref)
        else:
            f["score"] = f[key]
        f["tier"] = assign_tier(f["score"], boundaries)
    return features, boundaries, ref


# ---------------------------------------------------------------------------
# Tiered copies


def copy_tiers(features, out_dir):
    """Copy each file into out_dir/intensity_N/ (N = its tier), preserving the
    original filename so a tiered file maps straight back to the report row.
    Originals are untouched. Returns a list of written paths."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for f in features:
        d = os.path.join(out_dir, "intensity_%d" % f["tier"])
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f["name"])
        shutil.copyfile(f["path"], dst)
        written.append(dst)
    return written


# ---------------------------------------------------------------------------
# CLI


def _print_table(features, which, boundaries, ref):
    print("intensity classification (mode=%s, ref=%.1f dBFS):" % (
        which, ref))
    if boundaries:
        print("  boundaries: " + ", ".join("%.3f" % b for b in boundaries))
    print("  %-28s %9s %9s %9s %8s %5s" % (
        "file", "centHz", "rmsDb", "peakDb", "score", "tier"))
    for f in sorted(features, key=lambda f: f["score"], reverse=True):
        print("  %-28s %9.1f %9.1f %9.1f %8.3f %5d" % (
            f["name"], f["centroid_hz"], f["rms_db"], f["peak_db"],
            f["score"], f["tier"]))


def build_parser():
    p = argparse.ArgumentParser(
        prog="intensity",
        description="Classify beat WAVs by intensity and copy them into "
                    "intensity_N/ subfolders.",
    )
    p.add_argument("folder", help="folder of *.wav files to classify")
    p.add_argument("--out", default="tiers",
                   help="output directory (default: ./tiers)")
    p.add_argument("--intensity-mode",
                   choices=["bright_loud", "loud_rms", "loud_peak", "all"],
                   default="bright_loud",
                   help="score axis: bright_loud (brightness + RMS, default), "
                        "loud_rms (RMS only), loud_peak (peak only), or all "
                        "(all three, under <out>/intensity_groups/)")
    p.add_argument("--thresholds", choices=["fixed", "adaptive"],
                   default="adaptive",
                   help="tier boundary mode, bright_loud only; loud-only "
                        "variants are always adaptive (default: adaptive)")
    p.add_argument("--tiers", type=int, default=3,
                   help="number of intensity tiers (default: 3)")
    p.add_argument("--intensity-centroid-low", type=float,
                   default=DEFAULT_CENT_LOW,
                   help="fixed-mode low/high centroid boundary (Hz) "
                        "(default: %s)" % DEFAULT_CENT_LOW)
    p.add_argument("--intensity-centroid-high", type=float,
                   default=DEFAULT_CENT_HIGH,
                   help="fixed-mode high centroid boundary (Hz) "
                        "(default: %s)" % DEFAULT_CENT_HIGH)
    p.add_argument("--intensity-rms-ref", type=float, default=DEFAULT_RMS_REF,
                   help="fixed-mode absolute RMS reference, dBFS "
                        "(default: %s)" % DEFAULT_RMS_REF)
    p.add_argument("--no-normalize", action="store_true",
                   help="do not loudnorm before scoring")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    paths = sorted(glob.glob(os.path.join(args.folder, "*.wav")))
    if not paths:
        print("no *.wav files in %s" % args.folder)
        return 1
    features = analyze_files(paths, normalize=not args.no_normalize)
    which_list = (["bright_loud", "loud_rms", "loud_peak"]
                  if args.intensity_mode == "all"
                  else [args.intensity_mode])
    for which in which_list:
        work = [dict(f) for f in features]  # classify mutates; keep originals
        work, boundaries, ref = classify(
            work, args.thresholds, tiers=args.tiers,
            cent_low=args.intensity_centroid_low,
            cent_high=args.intensity_centroid_high,
            rms_ref=args.intensity_rms_ref, which=which)
        _print_table(work, which, boundaries, ref)
        if args.intensity_mode == "all":
            out_dir = os.path.join(args.out, "intensity_groups",
                                   "intensity_by_%s" % which)
        else:
            out_dir = args.out
        written = copy_tiers(work, out_dir)
        print("copied %d file(s) into %s/intensity_N/" % (len(written),
                                                          out_dir))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
