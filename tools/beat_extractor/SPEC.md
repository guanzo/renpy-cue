# Beat Extractor

A small command-line tool that slices individual impact beats ("spike + tail") out of a
video or audio file and writes them as a tidy set of game-ready SFX files, plus a CSV
report so every detection decision is auditable.

Works with system Python 3 (numpy + ffmpeg). It is a dev tool, **not** Ren'Py code --
none of the `cue_lib` compatibility constraints apply.

## The deal

- **You curate the window.** Point the tool at a time range where you can *see* clean
  beats (a cluster of spikes with quiet gaps). The tool handles slightly-sloppy bounds,
  but it is not a full-video auto-detector.
- **Sync is king.** Each output file starts with the spike at or near sample zero, so
  when the file is placed on a video timeline and the playhead hits the marker, the hit
  plays immediately. A short natural lead-in (attack buildup) is preserved only up to a
  cap; anything longer is trimmed.
- **Simple detection.** "Loud enough = beat." No spectral-flux machinery, no librosa.
  A fixed amplitude threshold finds the beats, which also makes detection immune to the
  "one loud edge event raises the bar for the whole window" failure of global-threshold
  detectors.

## Pipeline

1. **Extract the window** -> mono 44.1 kHz WAV (`_analysis.wav`). All later stages run
   on this file regardless of the source format/codec/channels.
2. **Find beats** -> mark every place the amplitude envelope crosses
   `--amplitude-threshold`. Each crossing is a beat's attack; the actual spike (max
   sample) is found within it.
3. **Recover sub-threshold beats** -> a quieter second impact in the same
   window slips under the threshold and gets absorbed by the previous clip's
   tail (the clip-end trough logic finds the *global* envelope minimum, which
   after a second beat sits in the far silence past it -- the clip carries both
   impacts, and after loudnorm the second is audible). For every gap between a
   beat's peak and the next beat's crossing -- and past the *last* beat, whose
   clip runs to the window end -- a candidate is a local envelope maximum that
   clears a minimum gap on both sides, reaches `secondary_ratio` x the primary
   beat's peak, and stands out from the decaying tail by `contrast_ratio` x
   the **median** envelope between them (a genuine rise out of decay, not tail
   ring-in or room tone -- the median, not the min, so one low noise hop in an
   elevated floor can't fabricate a trough). Found beats merge into the
   detection and split the merged clip into two.
4. **Set clip boundaries** ->
   - **Start:** back up from the spike while the envelope is monotonic until it reaches
     the attack base (where the rise begins / meets the noise floor), at most
     `--max-lead-in-ms` (default 80). Then pad `--pre-roll-ms` (default 25) of *real*
     pre-spike source audio before that -- so the hit sits a small distance into the file
     with the natural buildup/lead-in included, instead of being jammed at sample zero.
   - **End:** the **envelope trough** in the gap before the *next* beat. The current
     beat's tail decays toward the noise floor, then the next beat's precursor rises
     into its crossing -- a "sudden rise at the very end" that a too-long clip shows as
     a visible volume bump. The end is found by scanning the 1ms envelope between this
     beat's peak and the next beat's crossing and taking its **global minimum**: the
     point where the declining tail bottoms out before rising into the next attack. The
     clip ends one hop past that trough, so it finishes in genuine silence and never
     swallows any of the next beat's rise, however gradual the precursor. (A simple
     amplitude-floor walk back from the crossing fails here: it stops at the *first*
     quiet dip below the floor, which sits inside the rising precursor -- the tail
     still shows the end bump.) Beats are not contiguous; the gap between a beat's
     tail and the next beat's attack stays out of both files. The **last** beat ends
     at the analysis window's end (soft cap) -- the final beat is never lost.
5. **Hard floor** -> clips shorter than `--min-beat-ms` are dropped as `skipped_too_short`.
6. **Duration consistency** -> compute the median clip length; drop clips outside
   `--duration-ratio` x .. 1/`--duration-ratio` x the median as `dropped_duration_outlier`.
   This is what catches the partial beats that lurk at a sloppy window's edges. With
   fewer than 3 surviving beats the band is skipped entirely (the median is too fragile
   -- a single long clip that swallowed a second impact drags the band up around itself).
7. **Clean/dirty gap check** -> for each surviving clip, measure the RMS of its trailing
   region (last 60% of the clip -- the gap after the beat's decay). If it exceeds
   `--noise-floor-db` (default -40), the beat is `dirty`: logged in the CSV and its
   raw slice kept in `beats_dropped/dirty/` for inspection, **never extracted** to
   `beats/`.
8. **Loudness consistency** -> among clean beats, drop any whose peak dB is more than
   `--loudness-outlier-db` (default 6) from the clean set's median as
   `dropped_loudness_outlier`. (Engages only with >= 4 clean beats -- with fewer, the
   "typical" set is too small to trust.)
9. **Extract** -> one WAV per surviving beat (spike at the front, tail plays out).
10. **Clean up each file** ->
    - `highpass=f=80` -- always on. Kills the low-frequency rumble (AC/hum) that
      normalization would otherwise make audible. Very safe for impact beats.
    - `afftdn=nf=-25:nr=N` -- only with `--denoise`, where N is `--denoise-strength`
      (default 12, range ~12-40). Broadband denoiser for ambient air/hiss; opt-in because
      it's the risky one (can dull the attack or add artifacts if pushed too hard). Higher
      strength = quieter noise floor.
    - `atrim=start=<afftdn latency>` -- added only with `--denoise`. afftdn is an FFT
      filter with a fixed forward latency (~25 ms); the trim removes it so a denoised
      beat's spike lands at the same `--pre-roll-ms` offset as a plain run -- denoise on
      and off share the same content window. Costs ~25 ms of quiet decay tail.
    - `loudnorm=I=-16:TP=-1.5:LRA=11` -- only with `--normalize`. Makes the library
      consistent across source videos recorded at different levels, but flattens raw
      amplitude differences (a soft hit and a hard hit both land near -16 LUFS). Off by
      default so a source's internal soft-to-hard dynamics survive into the intensity tiers.
11. **Report** -> `beat_report.csv`, one row per detected beat, written even on a dry run.
12. **Intensity pass** (enabled by `--intensity-mode`) -> classify the surviving clean
    beats by *intensity* -- brightness (spectral centroid) + loudness (RMS),
    the two things that actually read as "high vs low impact" -- and copy each
    into `intensity_1/ .. intensity_N/` subfolders, originals untouched. The
    pass runs on the already-extracted beat WAVs (raw levels by default, or
    loudnorm'd with `--normalize`) -- no second normalization either way, so
    the RMS it measures is the level the beat actually plays at. See "Intensity
    pass" below.

## Intensity pass

"Intensity" is not pitch: impact beats are noise-like (a thud has no meaningful
fundamental), so the perceptible difference is **brightness** (spectral
centroid -- the amplitude-weighted mean spectral frequency) plus **loudness**
(RMS). Neither alone is reliable: a loud dull thud and a soft bright crack each
look wrong on one axis and right on the other, so the two are combined into one
score:

    score = centroid_khz + (rms_db - rms_ref) / 4.0

The `/4.0` reads as "1 kHz of brightness is worth 4 dB of loudness" --
calibrated against real impact libraries where both axes vary together.
Higher score = brighter and/or louder = more intense. Verified on a hand-sorted
12-file library (8 medium, 4 high): both modes reproduce the split exactly.

Three score axes, picked with `--intensity-mode`:

- **bright_loud** (default) -- the 2D score above. When a source's soft and
  hard sections differ mostly in brightness, the brightness term can swamp
  loudness and the tiers may not separate them -- that's what the loud-only
  axes are for.
- **loud_rms** -- loudness only, whole-clip RMS. Whole-clip average energy,
  so a long quiet tail drags it down.
- **loud_peak** -- loudness only, the single loudest sample. No tail-length
  contamination -- the honest "how hard did it land".

Loud-only variants are **always adaptive** (a fixed dB boundary needs
per-source calibration; fixed centroid thresholds mean nothing on a loudness
axis), so `--thresholds`, `--intensity-centroid-low/high`, and
`--intensity-rms-ref` apply to `bright_loud` only. `--tiers` applies to all
axes.

Tier boundaries (how the score axis is cut into `--tiers` groups):

- **adaptive (default)** -- `rms_ref` is the batch median, so the RMS term is
  relative; boundaries sit at the **largest gaps** in the sorted scores, so the
  tiering discovers the batch's natural clusters rather than forcing
  equal-sized buckets. A quiet-bright beat and a loud-dull beat stay in their
  own clusters. (Equal-count buckets would force a false 6/6 split on a genuine
  8/4 library.)
- **fixed** -- `rms_ref` is an absolute constant (`--intensity-rms-ref`,
  default -30 dBFS, the typical RMS of a loudnorm'd beat) and boundaries come
  from `--intensity-centroid-low/high`, expressed as centroid-equivalent
  scores. A file louder than rms_ref lands above its raw centroid, a quieter
  one below. Reproduces the same standard across batches regardless of their
  levels -- but the reference is calibrated for loudnorm'd levels, so with
  raw (default, no `--normalize`) levels the RMS axis shifts and fixed mode
  is best used with `--normalize` or a tuned `--intensity-rms-ref`.

Files keep their `beat_*.wav` names inside the tier folders, so a tiered file
maps straight back to its `beat_report.csv` row. Single-mode runs write the
flat `<out>/intensity_1/..N/` layout; `--intensity-mode all` writes the three
variants side by side:

```
<out>/intensity_groups/
  intensity_by_bright_loud/intensity_1/..N/
  intensity_by_loud_rms/    intensity_1/..N/
  intensity_by_loud_peak/   intensity_1/..N/
```

The report is the full audit: when the intensity pass runs it always carries
every axis's columns (`centroid_hz`, `rms_db`, `intensity_peak_db`,
`intensity_score/tier`, `loud_rms_score/tier`, `loud_peak_score/tier`),
whether or not that axis's folders were written.

## CLI

```
python3 beat_extractor.py INPUT --start T --end T --out DIR [options]
python3 beat_extractor.py INPUT --labels LABELS.TXT --out DIR [options]
```

| Flag | Default | Effect |
|---|---|---|
| `INPUT` (positional) | -- | Video or audio file |
| `--start` / `--end` | none | Window in the source (mm:ss, hh:mm:ss, or raw seconds). Omit both for the whole file |
| `--labels` | none | Audacity label export (`start<TAB>end` per line): process every window in one run. Exclusive with `--start`/`--end`; Windows paths accepted |
| `--out` | `./output` | Output directory (cleared before each run) |
| `--amplitude-threshold` | 0.15 | "Loud enough = beat"; 0.1-0.4 all worked on reference material |
| `--max-lead-in-ms` | 80 | Max pre-spike buildup kept in a clip |
| `--pre-roll-ms` | 25 | Real pre-spike lead-in kept before each beat's hit (0 = spike at file start) |
| `--min-beat-ms` | 50 | Hard floor: clips shorter than this are dropped |
| `--duration-ratio` | 0.5 | Drop clips outside `ratio` x .. 1/`ratio` x the median length |
| `--noise-floor-db` | -40 | Gap RMS above this (in dBFS) makes a beat `dirty` |
| `--loudness-outlier-db` | 6 | Drop clean beats outside median +/- this (dB) |
| `--denoise` | off | Add `afftdn` broadband denoising |
| `--denoise-strength` | 12 | afftdn noise reduction in dB; higher = quieter floor (12 safe, ~25 aggressive, 40 near-silent but artifact-prone) |
| `--normalize` | off | Apply `loudnorm` to each beat (off by default, so raw source amplitude differences are preserved) |
| `--intensity-mode` | none (off) | Turns on the intensity pass and picks the score axis: `bright_loud` (brightness + RMS), `loud_rms` (RMS only), `loud_peak` (peak only), or `all` (all three, under `intensity_groups/`) |
| `--thresholds` | `adaptive` | Intensity boundary mode: `fixed` or `adaptive` (bright_loud only; loud-only variants are always adaptive) |
| `--tiers` | 3 | Number of intensity tiers (2 or 3 in fixed mode) |
| `--intensity-centroid-low` | 3000 | Fixed-mode low/high centroid boundary (Hz) |
| `--intensity-centroid-high` | 4500 | Fixed-mode high centroid boundary (Hz) |
| `--intensity-rms-ref` | -30 | Fixed-mode absolute RMS reference (dBFS) |
| `--dry-run` | off | Report only -- no extraction or cleanup |

## Output layout

Single window (`--start`/`--end`):

```
<out>/
  _analysis.wav         mono 44.1k window (input normalization)
  _raw/beat_002_raw.wav raw clips, one per surviving beat (pre-cleanup)
  beats/beat_002.wav    final processed SFX
  beats_dropped/        non-clean beats, raw slices, one dir per category:
    dirty/beat_001.wav    dirty /
    skipped_too_short/      skipped_too_short /
    dropped_duration_outlier/  dropped_duration_outlier /
    dropped_loudness_outlier/   dropped_loudness_outlier /
  beat_report.csv       audit trail
  intensity_1/beat_...  with the intensity pass: copies of the clean beats,
  intensity_2/beat_...    tiered (intensity_1 = lowest). Originals untouched.
  intensity_groups/     with --intensity-mode all: the three score axes, each
    intensity_by_.../     under its own tiered tree (see "Intensity pass").
```

Batch (`--labels`): beats from every window share one flat `beats/*.wav` set,
numbered **sequentially across all windows** in report order; each window keeps
its own analysis WAV.

```
<out>/
  _analysis/win000.wav  mono 44.1k window for label 0
  _analysis/win001.wav  ... one per label
  _raw/beat_002_raw.wav raw clips, one per surviving beat (pre-cleanup)
  beats/beat_002.wav    final processed SFX
  beats_dropped/        non-clean beats, raw slices (as above)
  beat_report.csv       audit trail (one combined report, "window" column)
```

`<out>` is **cleared before each run**, so a rerun never mixes stale files with
fresh ones. Files are named by **candidate index**, matching the CSV rows -- if
`beat_001` was dirty, there is no `beats/beat_001.wav` but there is a raw
`beats_dropped/dirty/beat_001.wav`, and row 1 in the CSV says why. In batch
mode the candidate index counts across every window. Category dirs that end up
empty (a run with no dirty beats) are simply absent.

## Report columns

`index, start_sec, end_sec, duration_sec, peak_db, classification, duration_median,
duration_band, loudness_median, loudness_band`

In batch (`--labels`) mode the report adds a leading **`window`** column carrying
each beat's window start (absolute into the source), so rows from different windows
are distinguishable. When the intensity pass runs, clean rows gain the
intensity columns **`centroid_hz, rms_db, intensity_score, intensity_tier,
intensity_peak_db,
loud_rms_score, loud_rms_tier, loud_peak_score, loud_peak_tier`** (blank on
non-clean rows, and blank for any axis that wasn't run) -- the intensity
decision for every axis, auditable like every other one.

- Times are **absolute into the original file** (window offset already added), so a row
  can be used to re-run a narrower window over a misclassified region.
- `classification` is one of: `clean`, `dirty`, `skipped_too_short`,
  `dropped_duration_outlier`, `dropped_loudness_outlier`.
- The `*_median` / `*_band` columns record what the reference band *was* when that beat
  was judged, so a review pass sees exactly why a beat was kept or dropped.

## Dependencies

- Python 3, `numpy`
- `ffmpeg` on PATH (extraction of the analysis window + the filter chain; the detector
  itself is pure numpy)

## Known honest limits

- A loud partial beat at the window edge can still survive the duration filter if it
  lands inside the "typical" length band -- the CSV will show it, and a tighter window
  fixes it.
- The clean/dirty and loudness checks are amplitude-only; they can't tell "quiet but
  foreign sound" from "acceptable room tone." Curated clean windows keep this from
  biting.
- `loudnorm` on clips shorter than ~300ms is approximate (single-pass measures partial
  loudness). Fine for game SFX; the default (no `--normalize`) compares raw levels.
