#!/usr/bin/env python3
"""Beat Extractor -- slice impact beats out of a video/audio window.

Given a video/audio file and a time window containing a cluster of impact beats
(spike + decay, with quiet gaps), writes one WAV per beat (spike at the front,
tail plays out) plus a CSV audit report. See SPEC.md for the design.

Dev tool, system Python 3. Deps: numpy + ffmpeg on PATH.

Windows paths (e.g. E:\\media\\song.mp4) are converted to WSL
paths (/mnt/e/media/song.mp4) automatically.

Example:
python3 beat_extractor.py "song.mp4" --start 00:13:10 --end 00:13:12

Batch mode -- windows come from an Audacity label export (start<TAB>end per
line); beats across every window are numbered sequentially and land flat in
beats/ next to _raw/:
python3 beat_extractor.py "song.mp4" --labels "E:\\labels.txt"
"""

from __future__ import print_function

import argparse
import csv
import os
import subprocess
import sys
import tempfile

import numpy as np

try:
    import wave  # noqa: F401  (imported explicitly where used, kept here for clarity)
except ImportError:  # pragma: no cover -- wave is stdlib, never missing
    pass

from intensity import DEFAULT_CENT_HIGH as _DEFAULT_CENT_HIGH
from intensity import DEFAULT_CENT_LOW as _DEFAULT_CENT_LOW
from intensity import DEFAULT_RMS_REF as _DEFAULT_RMS_REF
from intensity import analyze_files as _intensity_analyze
from intensity import classify as _intensity_classify
from intensity import copy_tiers as _intensity_copy

# ---------------------------------------------------------------------------
# Path helpers


def win_to_wsl(path):
    """Convert a Windows path to a WSL path so ffmpeg can open it.

    'E:\\media\\a b.mp4' -> '/mnt/e/media/a b.mp4'.
    POSIX paths (already absolute) and relative paths pass through, with stray
    backslashes fixed to forward slashes; a trailing double-quote from a sloppy
    copy-paste is dropped.
    """
    s = path.strip()
    if len(s) >= 2 and s[-1] == '"':
        s = s[:-1]
    if s.startswith("/"):
        return s
    if len(s) >= 2 and s[0].isalpha() and s[1] == ":":
        drive = s[0].lower()
        rest = s[2:].lstrip("\\/").replace("\\", "/")
        return "/mnt/%s/%s" % (drive, rest)
    return s.replace("\\", "/")


def _clear_dir(path):
    """Recursively delete a directory tree, path-based.

    shutil.rmtree is NOT used: since Python 3.12 it deletes via fd-relative
    syscalls (os.unlink(..., dir_fd=...)), which fail with EACCES on WSL
    drvfs mounts (/mnt/...). Plain path-based unlink works there. Raises
    OSError naming the file if a Windows process holds a lock on it.
    """
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            os.unlink(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))
    os.rmdir(path)


# ---------------------------------------------------------------------------
# Timestamps


def parse_timestamp(text):
    """Parse mm:ss, hh:mm:ss (fractional seconds allowed) or raw seconds."""
    text = text.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        raise ValueError("cannot parse timestamp: %r" % text)
    return float(text)


# ---------------------------------------------------------------------------
# Label files (Audacity exports)


def read_labels(path):
    """Parse an Audacity label export into (start, end) windows.

    Each data line is 'start<TAB>end<TAB>[label]' -- the label text is
    ignored, blank lines are skipped, times may be fractional seconds or
    mm:ss/hh:mm:ss. Returns a list of (start, end) tuples.
    """
    windows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) < 2:
                raise ValueError("bad label line: %r" % line)
            start = parse_timestamp(fields[0])
            end = parse_timestamp(fields[1])
            if start >= end:
                raise ValueError("label start not before end: %r" % line)
            windows.append((start, end))
    return windows


# ---------------------------------------------------------------------------
# ffmpeg


def _ffmpeg(*args):
    """Run ffmpeg, failing loudly on error."""
    cmd = ["ffmpeg", "-v", "error", "-y"] + list(args)
    subprocess.run(cmd, check=True)


def extract_analysis(input_path, start, end, out_wav):
    """Render the requested window to mono 44.1kHz WAV.

    Seeking happens as an input option (-ss before -i) so the output starts at
    the requested time; the reference material verifies this is frame-accurate
    for mp4/aac. Times are relative to the analysis WAV afterward.
    """
    args = []
    if start is not None:
        args += ["-ss", "%f" % start]
    if end is not None:
        args += ["-to", "%f" % end]
    args += ["-i", input_path, "-ac", "1", "-ar", "44100", "-f", "wav", out_wav]
    _ffmpeg(*args)


_AFFTDN_LATENCY = None


def _afftdn_latency():
    """Measure afftdn's fixed processing delay (seconds), cached per process.

    afftdn is an FFT overlap-save filter: it inherently shifts the whole signal
    forward by its window (1102 samples / ~25 ms at 44.1 kHz on ffmpeg 8). That
    would push the spike ~25 ms later than the pre-roll intends, so we trim the
    delay back out. Without the trim, --denoise and plain runs would not share
    the same content window.
    """
    global _AFFTDN_LATENCY
    if _AFFTDN_LATENCY is not None:
        return _AFFTDN_LATENCY
    sr = 44100
    x = np.zeros(sr)
    x[sr // 4] = 1.0  # single impulse sample
    tag = "be_impulse_%d" % os.getpid()
    inp = os.path.join(tempfile.gettempdir(), tag + "_in.wav")
    outp = os.path.join(tempfile.gettempdir(), tag + "_afftdn.wav")
    write_wav(inp, x, sr)
    try:
        _ffmpeg("-i", inp, "-af", "highpass=f=80,afftdn=nf=-25", outp)
        y, _ = read_wav(outp)
        peak_in = sr // 4
        peak_out = int(np.argmax(np.abs(y)))
        _AFFTDN_LATENCY = max(0, (peak_out - peak_in) / float(sr))
    finally:
        for p in (inp, outp):
            if os.path.exists(p):
                os.remove(p)
    return _AFFTDN_LATENCY


def process_clip(raw_path, out_path, do_denoise, do_normalize, denoise_strength):
    """Highpass always; afftdn only with --denoise; loudnorm unless skipped.

    When afftdn is used, its forward latency is trimmed back out (atrim) so the
    spike sits at the same --pre-roll-ms offset as a plain run -- denoise on and
    off share the same content window, differing only in noise. The trim shortens
    the clip by the latency (~25 ms of quiet decay tail).

    denoise_strength maps to afftdn's nr (noise reduction, dB). Higher is more
    aggressive: quieter noise floor but risk of artifacts / a dulled attack.
    """
    filters = ["highpass=f=80"]
    if do_denoise:
        filters.append("afftdn=nf=-25:nr=%d" % int(denoise_strength))
        latency = _afftdn_latency()
        if latency > 0:
            filters.append("atrim=start=%f" % latency)
    if do_normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    _ffmpeg("-i", raw_path, "-af", ",".join(filters), out_path)


# ---------------------------------------------------------------------------
# WAV I/O


def read_wav(path):
    """Read a WAV to a mono float array in [-1, 1] plus sample rate."""
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    """Write a mono float array as 16-bit WAV."""
    y = np.clip(x, -1.0, 1.0)
    data = (y * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


# ---------------------------------------------------------------------------
# Beat detection

LEAD_IN_FRAC = 0.02  # (kept for reference; the scan is envelope-monotonic, see below)


def _peak_envelope(x, sr, hop_s=0.001):
    """Per-hop maximum-abs envelope."""
    hop = max(1, int(round(sr * hop_s)))
    n = len(x)
    length = (n + hop - 1) // hop
    env = np.empty(length, dtype=np.float64)
    for i in range(length):
        env[i] = np.abs(x[i * hop:(i + 1) * hop]).max()
    return env, hop


def detect_beats(x, sr, threshold, max_lead_in_s, min_sep_s=0.08):
    """Find impact beats via amplitude-threshold crossing.

    Returns a list of beat dicts, each with:
      crossing_i      first sample index where |x| >= threshold
      peak_i / peak   argmax |x| within the beat and its value
      peak_db         peak in dBFS
      clip_start_i    refined start (attack base, capped at max_lead_in)
      clip_end_i      set later by build_clips
    """
    n = len(x)
    env, hop = _peak_envelope(x, sr)
    above = env > threshold

    # contiguous above-threshold runs, merged within min_sep
    runs = []
    i = 0
    length = len(env)
    while i < length:
        if not above[i]:
            i += 1
            continue
        j = i
        while j + 1 < length and above[j + 1]:
            j += 1
        start_t = i * hop / sr
        end_t = (j + 1) * hop / sr
        if runs and start_t - runs[-1][1] < min_sep_s:
            runs[-1] = (runs[-1][0], end_t)
        else:
            runs.append((start_t, end_t))
        i = j + 1

    beats = []
    for start_t, end_t in runs:
        i0 = int(start_t * sr)
        i1 = min(n, int(end_t * sr) + hop)
        if i1 <= i0:
            continue
        seg_abs = np.abs(x[i0:i1])
        peak_off = int(np.argmax(seg_abs))
        peak_i = i0 + peak_off
        peak = seg_abs[peak_off]

        # crossing = first sample rising past threshold within the run
        cross_rel = int(np.argmax(np.abs(x[i0:i1]) >= threshold))
        crossing_i = i0 + cross_rel

        beats.append({
            "crossing_i": crossing_i,
            "peak_i": peak_i,
            "peak": peak,
            "peak_db": 20.0 * np.log10(peak + 1e-12),
            "clip_start_i": _refine_clip_start(x, sr, peak_i, max_lead_in_s),
            "status": None,
        })
    return beats


def _refine_clip_start(x, sr, peak_i, max_lead_in_s):
    """Back up from the spike to the attack base, capped at max_lead_in.

    Walks backward from the peak while the 1ms envelope is (weakly) decreasing.
    That stops exactly at the base of the rise: with no buildup the stop is a
    couple ms before the spike (ambient jitter), with real buildup it follows
    the rise all the way back to where it meets the noise floor. The cap trims
    any longer pre-roll so the spike stays near the file's start.
    """
    n = len(x)
    max_lead = max(1, int(round(max_lead_in_s * sr)))
    scan_from = max(0, peak_i - max_lead)
    peak = abs(x[peak_i])
    floor = peak * 0.05  # attack base: signal dropped to ~5% of the spike
    k = peak_i
    prev = peak
    while k > scan_from:
        v = abs(x[k - 1])
        if v > prev * 1.05:  # rising again -- walked past a local min
            break
        if v < floor:  # dropped off the beat into the noise floor
            break
        prev = v
        k -= 1
    return k


def _find_subthreshold_beats(x, sr, beats, max_lead_in_s,
                             secondary_ratio=0.25, contrast_ratio=6.0,
                             min_gap_s=0.05, merge_s=0.04):
    """Find real impacts that sit below the amplitude threshold inside the
    quiet gap before the next detected beat, so a clip that swallowed a second
    beat gets split into two.

    The amplitude threshold finds "loud enough = beat", but a quieter second
    impact in the same window slips under it and gets absorbed by the previous
    clip's tail: the clip-end trough logic finds the *global* envelope minimum,
    which after a second beat sits in the far silence past it, so the clip
    carries both impacts (and after loudnorm the second is clearly audible).
    A candidate is a local envelope maximum between this beat's peak and the
    next beat's crossing (or the window end, for the last beat) that clears a
    minimum gap on both sides, reaches `secondary_ratio` x the primary beat's
    peak, and stands out from the decaying tail by `contrast_ratio` x the
    **median** envelope between them -- a genuine rise out of the decay, not
    tail ring-in or room tone. The median (not the min) is the floor: a single
    low noise hop in an elevated floor otherwise fabricates a deep trough and
    lets the hum masquerade as a beat. Candidates within `merge_s` merge,
    keeping the louder.

    Returns new beat dicts (same shape as detect_beats) sorted by crossing.
    """
    if not beats:
        return []
    env, hop = _peak_envelope(x, sr)
    min_gap = int(min_gap_s * sr)
    merge_hop = max(1, int(round(merge_s * sr / float(hop))))
    extra = []
    for i in range(len(beats)):
        a = beats[i]
        if i + 1 < len(beats):
            nxt_crossing = beats[i + 1]["crossing_i"]
        else:
            # the last beat's clip ends at the window end, so a quiet second
            # impact in its tail is swallowed too -- scan to the window end.
            nxt_crossing = len(x)
        j0 = (a["peak_i"] + min_gap) // hop
        j1 = min(len(env) - 1, (nxt_crossing - min_gap) // hop)
        if j1 <= j0:
            continue
        cand = []
        for k in range(j0, j1 + 1):
            if k > j0 and env[k - 1] > env[k]:
                continue
            if k < j1 and env[k + 1] > env[k]:
                continue
            v = env[k]
            if v <= 0:
                continue
            if v < secondary_ratio * a["peak"]:
                continue
            if v < contrast_ratio * np.median(env[j0:k + 1]):
                continue
            cand.append((k, v))
        cand.sort()
        merged = []
        for k, v in cand:
            if merged and k - merged[-1][0] <= merge_hop:
                if v > merged[-1][1]:
                    merged[-1] = (k, v)
            else:
                merged.append((k, v))
        for k, _v in merged:
            lo = k * hop
            hi = min(len(x), (k + 1) * hop)
            seg = x[lo:hi]
            off = int(np.argmax(np.abs(seg)))
            peak_i = lo + off
            peak = abs(seg[off])
            extra.append({
                "crossing_i": peak_i,
                "peak_i": peak_i,
                "peak": peak,
                "peak_db": 20.0 * np.log10(peak + 1e-12),
                "clip_start_i": _refine_clip_start(x, sr, peak_i,
                                                   max_lead_in_s),
                "status": None,
            })
    extra.sort(key=lambda b: b["crossing_i"])
    return extra


def _merge_beats(detected, extra):
    """Combine detected + sub-threshold beats, sorted by crossing, dropping
    any overlap (a secondary landing on an already-detected beat)."""
    if not extra:
        return detected
    all_beats = detected + extra
    all_beats.sort(key=lambda b: b["crossing_i"])
    merged = []
    for b in all_beats:
        if merged and b["crossing_i"] <= merged[-1]["crossing_i"]:
            continue  # overlap -- keep the earlier
        merged.append(b)
    return merged


def _refine_clip_end(x, sr, peak_i, crossing_i):
    """Cut at the deepest silence before the next beat; return the exclusive
    end index (one past the last quiet sample).

    The current beat's tail decays toward the noise floor, then the next
    beat's precursor rises into its crossing -- the "sudden rise at the very
    end" a too-long clip shows. Find the envelope trough in the gap
    [peak_i, crossing_i): the point where the declining volume bottoms out
    before rising into the next attack. End the clip there, so it finishes in
    genuine silence and never carries any of the next beat's rise, however
    gradual the precursor. A dirty/overlapping gap (no real silence) still
    ends at its quietest point, which the gap check flags.
    """
    env, hop = _peak_envelope(x, sr)
    j0 = peak_i // hop
    j1 = min(len(env) - 1, crossing_i // hop)
    if j1 <= j0:
        return crossing_i
    k = int(np.argmin(env[j0:j1 + 1]))  # trough hop offset from j0
    return min((j0 + k + 1) * hop, crossing_i)  # one past the trough hop


def build_clips(beats, window_len_s, sr, x=None, max_lead_in_s=0.08):
    """Set clip boundaries. Start = refined attack base, end = the envelope
    trough in the gap before the next beat (where its rise meets the noise
    floor) so the current clip ends in genuine silence and never swallows the
    next beat's rise. The last beat ends at the analysis window's end (soft
    cap)."""
    for i, b in enumerate(beats):
        b["clip_start_s"] = b["clip_start_i"] / sr
    for i, b in enumerate(beats):
        if i + 1 < len(beats):
            nxt = beats[i + 1]
            if x is not None:
                b["clip_end_s"] = _refine_clip_end(
                    x, sr, b["peak_i"], nxt["crossing_i"]) / sr
            else:
                b["clip_end_s"] = nxt["clip_start_i"] / sr
        else:
            b["clip_end_s"] = window_len_s
        if b["clip_end_s"] <= b["clip_start_s"]:
            b["clip_end_s"] = b["clip_start_s"] + 1.0 / sr
        b["duration_s"] = b["clip_end_s"] - b["clip_start_s"]


def clip_indices(clip_start_s, clip_end_s, sr, pre_roll_s):
    """Sample range for a clip, padded back by pre_roll (clamped to 0).

    The padded region is real pre-spike content from the source -- the natural
    buildup / gap before the hit. The spike ends up pre_roll after the file's
    start instead of at sample zero.
    """
    pre = max(0, int(round(pre_roll_s * sr)))
    i0 = max(0, int(clip_start_s * sr) - pre)
    i1 = max(i0 + 1, int(clip_end_s * sr))
    return i0, i1


# ---------------------------------------------------------------------------
# Filters


def filter_duration(beats, min_beat_s, ratio, min_count=3):
    """Hard floor (skipped_too_short) then duration-consistency outlier drop.

    The band needs a meaningful "typical length" to judge against. With fewer
    than `min_count` survivors the median is too fragile -- a single long beat
    (e.g. a clip that swallowed a second impact) is half the data and drags the
    band up around itself. That mirrors the loudness filter's min_count guard.
    """
    survivors = []
    for b in beats:
        if b["duration_s"] < min_beat_s:
            b["status"] = "too_short"
        else:
            survivors.append(b)
    if len(survivors) < min_count:
        return
    durations = np.array([b["duration_s"] for b in survivors])
    median = float(np.median(durations))
    lo, hi = ratio * median, median / ratio
    for b in survivors:
        b["duration_median"] = median
        b["duration_band"] = (lo, hi)
        if b["duration_s"] < lo or b["duration_s"] > hi:
            b["status"] = "duration_outlier"


def classify_gaps(x, sr, beats, noise_floor_linear):
    """Measure the trailing gap's RMS; above the floor the beat is dirty."""
    for b in beats:
        if b.get("status") is not None:
            continue
        duration = b["duration_s"]
        skip = 0.4 * duration  # last 60% is the gap after the decay
        i0 = int((b["clip_start_s"] + skip) * sr)
        i1 = int(b["clip_end_s"] * sr)
        if i1 <= i0:  # can't verify a gap -> don't extract
            b["status"] = "dirty"
            continue
        seg = x[i0:i1]
        rms = np.sqrt(np.mean(seg ** 2))
        b["gap_rms_db"] = 20.0 * np.log10(rms + 1e-12)
        if rms > noise_floor_linear:
            b["status"] = "dirty"
        else:
            b["status"] = "clean"


def filter_loudness(beats, outlier_db, min_count=4):
    """Drop clean beats far from the clean set's median peak dB.

    Engages only with enough clean beats -- a tiny set is too small to trust.
    """
    clean = [b for b in beats if b["status"] == "clean"]
    if len(clean) < min_count:
        return
    peaks = np.array([b["peak_db"] for b in clean])
    median = float(np.median(peaks))
    for b in clean:
        b["loudness_median"] = median
        b["loudness_band"] = (median - outlier_db, median + outlier_db)
        if abs(b["peak_db"] - median) > outlier_db:
            b["status"] = "loudness_outlier"


STATUS_NAMES = {
    "clean": "clean",
    "dirty": "dirty",
    "too_short": "skipped_too_short",
    "duration_outlier": "dropped_duration_outlier",
    "loudness_outlier": "dropped_loudness_outlier",
}


def classification(b):
    return STATUS_NAMES[b.get("status") or "clean"]


def _write_outputs(beats, x, sr, args, raw_dir, beats_dir, dropped_dir):
    """Write every beat's clip from the analysis window.

    Clean beats go to _raw/ (raw slice) + beats/ (processed SFX); every
    non-clean beat's raw slice goes to beats_dropped/<category>/ so a dropped
    beat can be inspected next to its CSV row (dirty/, skipped_too_short/,
    dropped_duration_outlier/, dropped_loudness_outlier/). Returns (written,
    dropped): (idx, duration_s, peak_db) and (idx, category) pairs.
    """
    written = []
    dropped = []
    for b in beats:
        idx = b["candidate_index"]
        i0, i1 = clip_indices(b["clip_start_s"], b["clip_end_s"], sr,
                              args.pre_roll_ms / 1000.0)
        if classification(b) == "clean":
            raw_path = os.path.join(raw_dir, "beat_%03d_raw.wav" % idx)
            out_path = os.path.join(beats_dir, "beat_%03d.wav" % idx)
            write_wav(raw_path, x[i0:i1], sr)
            process_clip(raw_path, out_path, args.denoise,
                         args.normalize, args.denoise_strength)
            written.append((idx, b["duration_s"], b["peak_db"]))
        else:
            cat_dir = os.path.join(dropped_dir, classification(b))
            os.makedirs(cat_dir, exist_ok=True)
            write_wav(os.path.join(cat_dir, "beat_%03d.wav" % idx),
                      x[i0:i1], sr)
            dropped.append((idx, classification(b)))
    return written, dropped


# ---------------------------------------------------------------------------
# Report


def write_report(path, beats, window_start, include_window=False,
                 include_intensity=False):
    """One CSV row per beat, times absolute into the original file.

    With include_window, each row carries the window's label (source start)
    in a leading "window" column -- used for --labels runs. With
    include_intensity, each row gains the intensity columns (centroid, rms,
    peak, plus each mode's score/tier) populated only on clean beats (blank
    elsewhere) -- added by the intensity pass. Every beat must carry
    "window_start" (absolute source offset); window_start is the fallback for
    single-window runs where beats lack it.
    """
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        header = [
            "index", "start_sec", "end_sec", "duration_sec", "peak_db",
            "classification", "duration_median", "duration_band",
            "loudness_median", "loudness_band",
        ]
        if include_window:
            header.insert(1, "window")
        if include_intensity:
            header += ["centroid_hz", "rms_db", "intensity_score",
                       "intensity_tier", "intensity_peak_db",
                       "loud_rms_score", "loud_rms_tier",
                       "loud_peak_score", "loud_peak_tier"]
        out.writerow(header)
        for i, b in enumerate(beats):
            ws = b.get("window_start", window_start)
            row = [
                i,
                _fmt(ws + b["clip_start_s"]),
                _fmt(ws + b["clip_end_s"]),
                _fmt(b["duration_s"]),
                _fmt(b["peak_db"]),
                classification(b),
                _fmt(b.get("duration_median", "")) if "duration_median" in b else "",
                _band(b.get("duration_band")),
                _fmt(b.get("loudness_median", "")) if "loudness_median" in b else "",
                _band(b.get("loudness_band")),
            ]
            if include_window:
                row.insert(1, _fmt(b.get("window_start", window_start)))
            if include_intensity:
                row += [
                    _fmt(b.get("centroid_hz", "")) if "centroid_hz" in b else "",
                    _fmt(b.get("rms_db", "")) if "rms_db" in b else "",
                    _fmt(b.get("intensity_score", "")) if "intensity_score" in b else "",
                    _fmt(b.get("intensity_tier", "")) if "intensity_tier" in b else "",
                    _fmt(b.get("intensity_peak_db", "")) if "intensity_peak_db" in b else "",
                    _fmt(b.get("loud_rms_score", "")) if "loud_rms_score" in b else "",
                    _fmt(b.get("loud_rms_tier", "")) if "loud_rms_tier" in b else "",
                    _fmt(b.get("loud_peak_score", "")) if "loud_peak_score" in b else "",
                    _fmt(b.get("loud_peak_tier", "")) if "loud_peak_tier" in b else "",
                ]
            out.writerow(row)


def _fmt(value):
    if value == "":
        return ""
    return "%.4f" % value


def _band(band):
    if not band:
        return ""
    return "%.4f..%.4f" % (band[0], band[1])


# ---------------------------------------------------------------------------
# CLI


def build_parser():
    p = argparse.ArgumentParser(
        prog="beat_extractor",
        description="Slice impact beats out of a video/audio window. See SPEC.md.",
    )
    p.add_argument("input", help="video or audio file")
    p.add_argument("--start", help="window start (mm:ss, hh:mm:ss, or seconds)")
    p.add_argument("--end", help="window end (mm:ss, hh:mm:ss, or seconds)")
    p.add_argument("--labels",
                   help="Audacity label export (start<TAB>end per line): process "
                        "every window in one run. Exclusive with --start/--end. "
                        "Windows paths accepted.")
    p.add_argument("--out", default="output",
                   help="output directory (default: ./output)")
    p.add_argument("--amplitude-threshold", type=float, default=0.15,
                   help="'loud enough = beat' (default 0.15)")
    p.add_argument("--max-lead-in-ms", type=float, default=80.0,
                   help="max pre-spike buildup kept in a clip (default 80)")
    p.add_argument("--pre-roll-ms", type=float, default=25.0,
                   help="real pre-spike lead-in kept before each beat's hit; "
                        "0 puts the spike at the file's start (default 25)")
    p.add_argument("--min-beat-ms", type=float, default=50.0,
                   help="hard floor for clip length (default 50)")
    p.add_argument("--duration-ratio", type=float, default=0.5,
                   help="drop clips outside ratio x .. 1/ratio x median length")
    p.add_argument("--noise-floor-db", type=float, default=-40.0,
                   help="gap RMS above this makes a beat dirty (default -40)")
    p.add_argument("--loudness-outlier-db", type=float, default=6.0,
                   help="drop clean beats outside median +/- this dB")
    p.add_argument("--denoise", action="store_true",
                   help="add afftdn broadband denoising")
    p.add_argument("--denoise-strength", type=float, default=12.0,
                   help="afftdn noise reduction in dB; higher = quieter noise "
                        "floor but risk of artifacts (default 12)")
    p.add_argument("--normalize", action="store_true",
                   help="apply loudnorm to each beat (off by default, so raw "
                        "source amplitude differences are preserved)")
    p.add_argument("--intensity-mode",
                   choices=["bright_loud", "loud_rms", "loud_peak", "all"],
                   help="turn on the intensity pass and pick the score axis: "
                        "bright_loud (brightness + RMS), loud_rms (RMS only), "
                        "loud_peak (peak only), or all (all three, under "
                        "<out>/intensity_groups/). Off when omitted")
    p.add_argument("--thresholds", choices=["fixed", "adaptive"],
                   default="adaptive",
                   help="intensity tier boundary mode, bright_loud only; "
                        "loud-only modes are always adaptive "
                        "(default: adaptive)")
    p.add_argument("--tiers", type=int, default=3,
                   help="number of intensity tiers (default: 3)")
    p.add_argument("--intensity-centroid-low", type=float,
                   default=_DEFAULT_CENT_LOW,
                   help="fixed-mode low/high centroid boundary, Hz "
                        "(default: %s)" % _DEFAULT_CENT_LOW)
    p.add_argument("--intensity-centroid-high", type=float,
                   default=_DEFAULT_CENT_HIGH,
                   help="fixed-mode high centroid boundary, Hz "
                        "(default: %s)" % _DEFAULT_CENT_HIGH)
    p.add_argument("--intensity-rms-ref", type=float, default=_DEFAULT_RMS_REF,
                   help="fixed-mode absolute RMS reference, dBFS "
                        "(default: %s)" % _DEFAULT_RMS_REF)
    p.add_argument("--dry-run", action="store_true",
                   help="report only, no extraction")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print every window and every written/dropped beat "
                        "file (default: condensed summary)")
    return p


def _analyze_window(x, sr, args):
    """Run detection + the four filters on one analysis window."""
    window_len_s = len(x) / sr
    beats = detect_beats(x, sr, args.amplitude_threshold,
                         args.max_lead_in_ms / 1000.0)
    # Recover real impacts that fell below the amplitude threshold inside the
    # quiet gaps (a clip that swallowed a second beat gets split into two).
    beats = _merge_beats(beats, _find_subthreshold_beats(
        x, sr, beats, args.max_lead_in_ms / 1000.0))
    build_clips(beats, window_len_s, sr, x,
                max_lead_in_s=args.max_lead_in_ms / 1000.0)
    filter_duration(beats, args.min_beat_ms / 1000.0, args.duration_ratio)
    classify_gaps(x, sr, beats, 10.0 ** (args.noise_floor_db / 20.0))
    filter_loudness(beats, args.loudness_outlier_db)
    return beats


def _intensity_pass(beats, args):
    """Score + tier the extracted clean beats (--intensity-mode).

    Runs on the already-extracted beat WAVs (raw levels unless --normalize
    was set) and attaches each mode's score/tier to every clean beat dict so
    the report is the full audit. Copies tiered files per --intensity-mode:
    single modes (bright_loud default, loud_rms, loud_peak) write the old
    flat <out>/intensity_1..N/; 'all' writes the three variants under
    <out>/intensity_groups/intensity_by_<which>/intensity_1..N/. The common
    features (centroid_hz, rms_db, intensity_peak_db) are attached once for
    every run; the score/tier keys are per-mode (intensity_* for bright_loud,
    loud_rms_* / loud_peak_* for the loud-only variants). Returns
    {which: (boundaries, ref)} or None when nothing was classified.
    """
    clean = [b for b in beats if classification(b) == "clean"]
    if not clean:
        print("intensity: no clean beats to classify")
        return None
    paths = [os.path.join(args.out, "beats", "beat_%03d.wav"
                          % b["candidate_index"]) for b in clean]
    feats = _intensity_analyze(paths)  # already extracted; no second normalize

    for b, f in zip(clean, feats):
        b["centroid_hz"] = f["centroid_hz"]
        b["rms_db"] = f["rms_db"]
        b["intensity_peak_db"] = f["peak_db"]

    if args.intensity_mode == "all":
        which_list = ["bright_loud", "loud_rms", "loud_peak"]
    else:
        which_list = [args.intensity_mode]

    result = {}
    for which in which_list:
        work = [dict(f) for f in feats]  # classify mutates; keep shared feats
        if which == "bright_loud":
            work, boundaries, ref = _intensity_classify(
                work, args.thresholds, tiers=args.tiers,
                cent_low=args.intensity_centroid_low,
                cent_high=args.intensity_centroid_high,
                rms_ref=args.intensity_rms_ref, which=which)
        else:
            work, boundaries, ref = _intensity_classify(
                work, args.thresholds, tiers=args.tiers, which=which)
        for b, f in zip(clean, work):
            if which == "bright_loud":
                b["intensity_score"] = f["score"]
                b["intensity_tier"] = f["tier"]
            else:
                suffix = which[len("loud_"):]  # "loud_rms" -> "rms"
                b["loud_%s_score" % suffix] = f["score"]
                b["loud_%s_tier" % suffix] = f["tier"]
        if args.intensity_mode == "all":
            out_dir = os.path.join(args.out, "intensity_groups",
                                   "intensity_by_%s" % which)
        else:
            out_dir = args.out
        _intensity_copy(work, out_dir)
        result[which] = (boundaries, ref)
    return result


def _tier_counts(beats, which):
    """{tier: count} over clean beats for one intensity mode.

    The pass attaches one tier key per mode: 'intensity_tier' for
    bright_loud, 'loud_<axis>_tier' otherwise. Only tiers with beats are
    returned -- matching the intensity_N/ folders copy_tiers creates.
    """
    key = "intensity_tier" if which == "bright_loud" else which + "_tier"
    counts = {}
    for b in beats:
        if classification(b) == "clean":
            tier = b.get(key)
            if tier is not None:
                counts[tier] = counts.get(tier, 0) + 1
    return counts


def main(argv=None):
    args = build_parser().parse_args(argv)
    input_path = win_to_wsl(args.input)

    if args.labels:
        if args.start is not None or args.end is not None:
            sys.exit("error: --labels is exclusive with --start/--end")
        labels_path = win_to_wsl(args.labels)
        try:
            windows = read_labels(labels_path)
        except (IOError, ValueError) as e:
            sys.exit("error: %s" % e)
    else:
        start = parse_timestamp(args.start) if args.start else None
        end = parse_timestamp(args.end) if args.end else None
        if start is not None and end is not None and start >= end:
            sys.exit("error: --start must be before --end")
        windows = [(start, end)]

    # Clear stale output from a previous run so leftover beat_*.wav files
    # (different beat count, renamed windows, etc.) can't linger next to fresh
    # ones. Keeps a rerun honest: output/ holds exactly this run's output.
    if os.path.isdir(args.out):
        try:
            _clear_dir(args.out)
        except OSError as e:
            sys.exit("error: cannot clear %s (is the file open in another "
                     "program?): %s" % (args.out, e))
    os.makedirs(args.out, exist_ok=True)
    raw_dir = os.path.join(args.out, "_raw")
    beats_dir = os.path.join(args.out, "beats")
    dropped_dir = os.path.join(args.out, "beats_dropped")
    if not args.dry_run:
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(beats_dir, exist_ok=True)
        os.makedirs(dropped_dir, exist_ok=True)

    # Run every window; beats get a global sequential index (candidate_index)
    # so files and CSV rows line up across windows.
    all_beats = []
    written = []  # (candidate_index, duration_s, peak_db) of extracted files
    dropped = []  # (candidate_index, category) of non-clean files
    window_info = []  # (index, start, end, analysis_len_s) for the summary

    for w_index, (start, end) in enumerate(windows):
        if args.labels:
            analysis_dir = os.path.join(args.out, "_analysis")
            os.makedirs(analysis_dir, exist_ok=True)
            analysis_path = os.path.join(analysis_dir, "win%03d.wav" % w_index)
        else:
            analysis_path = os.path.join(args.out, "_analysis.wav")
        extract_analysis(input_path, start, end, analysis_path)

        x, sr = read_wav(analysis_path)
        window_len_s = len(x) / sr
        beats = _analyze_window(x, sr, args)

        ws = start if start is not None else 0.0
        for i, b in enumerate(beats):
            b["window_start"] = ws
            b["candidate_index"] = len(all_beats) + i
        all_beats.extend(beats)
        window_info.append((w_index, start, end, window_len_s))

        if not args.dry_run:
            w, d = _write_outputs(beats, x, sr, args, raw_dir, beats_dir,
                                  dropped_dir)
            written.extend(w)
            dropped.extend(d)

    write_report(os.path.join(args.out, "beat_report.csv"), all_beats, 0.0,
                 include_window=args.labels,
                 include_intensity=args.intensity_mode is not None)

    counts = {}
    for b in all_beats:
        counts[classification(b)] = counts.get(classification(b), 0) + 1

    if args.labels:
        print("labels: %d window(s) from %s" % (len(windows), labels_path))
        if args.verbose:
            for w_index, start, end, wlen in window_info:
                print("  win%03d: %s -> %s (%.3fs)" % (
                    w_index, _fmt(start), _fmt(end), wlen))
    else:
        start, end = windows[0]
        print("window: %s -> %s (%.3fs)" % (
            _fmt(start) if start is not None else "0",
            _fmt(end) if end is not None else "EOF",
            window_info[0][3]))
    print("detected %d beat(s):" % len(all_beats))
    for name in ("clean", "dirty", "skipped_too_short",
                 "dropped_duration_outlier", "dropped_loudness_outlier"):
        if counts.get(name):
            print("  %-26s %d" % (name, counts[name]))
    if args.verbose and not args.dry_run:
        for idx, dur, peak in written:
            print("  wrote beats/beat_%03d.wav  %.3fs  %.3f dBFS"
                  % (idx, dur, peak))
        for idx, cat in dropped:
            print("  dropped beats_dropped/%s/beat_%03d.wav" % (cat, idx))

    if args.intensity_mode:
        if args.dry_run:
            print("intensity pass skipped (dry run -- nothing extracted)")
        else:
            res = _intensity_pass(all_beats, args)
            if res:
                n_clean = sum(1 for b in all_beats
                              if classification(b) == "clean")
                for which, (boundaries, ref) in sorted(res.items()):
                    thr = args.thresholds if which == "bright_loud" \
                        else "adaptive"
                    print("intensity[%s]: %d clean beat(s) -> %d tier(s), "
                          "%s thresholds (ref %.1f dBFS)"
                          % (which, n_clean, args.tiers, thr, ref))
                    if boundaries:
                        print("  boundaries: " +
                              ", ".join("%.3f" % b for b in boundaries))
                    for tier, count in sorted(
                            _tier_counts(all_beats, which).items()):
                        print("  intensity_%d: %d beat(s)" % (tier, count))

    print("report: %s" % os.path.join(args.out, "beat_report.csv"))


if __name__ == "__main__":
    main()
