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
3. **Set clip boundaries** ->
   - **Start:** back up from the spike while the envelope is monotonic until it reaches
     the attack base (where the rise begins / meets the noise floor), at most
     `--max-lead-in-ms` (default 80). Then pad `--pre-roll-ms` (default 25) of *real*
     pre-spike source audio before that -- so the hit sits a small distance into the file
     with the natural buildup/lead-in included, instead of being jammed at sample zero.
   - **End:** the next beat's attack. The **last** beat ends at the analysis window's
     end (soft cap) -- the final beat is never lost.
4. **Hard floor** -> clips shorter than `--min-beat-ms` are dropped as `skipped_too_short`.
5. **Duration consistency** -> compute the median clip length; drop clips outside
   `--duration-ratio` x .. 1/`--duration-ratio` x the median as `dropped_duration_outlier`.
   This is what catches the partial beats that lurk at a sloppy window's edges.
6. **Clean/dirty gap check** -> for each surviving clip, measure the RMS of its trailing
   region (last 60% of the clip -- the gap after the beat's decay). If it exceeds
   `--noise-floor-db` (default -40), the beat is `dirty`: logged in the CSV, **never
   extracted**.
7. **Loudness consistency** -> among clean beats, drop any whose peak dB is more than
   `--loudness-outlier-db` (default 6) from the clean set's median as
   `dropped_loudness_outlier`. (Engages only with >= 4 clean beats -- with fewer, the
   "typical" set is too small to trust.)
8. **Extract** -> one WAV per surviving beat (spike at the front, tail plays out).
9. **Clean up each file** ->
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
   - `loudnorm=I=-16:TP=-1.5:LRA=11` -- on unless `--no-normalize`. Makes the library
     consistent across source videos recorded at different levels.
10. **Report** -> `beat_report.csv`, one row per detected beat, written even on a dry run.

## CLI

```
python3 beat_extractor.py INPUT --start T --end T --out DIR [options]
```

| Flag | Default | Effect |
|---|---|---|
| `INPUT` (positional) | -- | Video or audio file |
| `--start` / `--end` | none | Window in the source (mm:ss, hh:mm:ss, or raw seconds). Omit both for the whole file |
| `--out` | `./output` | Output directory |
| `--amplitude-threshold` | 0.15 | "Loud enough = beat"; 0.1-0.4 all worked on reference material |
| `--max-lead-in-ms` | 80 | Max pre-spike buildup kept in a clip |
| `--pre-roll-ms` | 25 | Real pre-spike lead-in kept before each beat's hit (0 = spike at file start) |
| `--min-beat-ms` | 50 | Hard floor: clips shorter than this are dropped |
| `--duration-ratio` | 0.5 | Drop clips outside `ratio` x .. 1/`ratio` x the median length |
| `--noise-floor-db` | -40 | Gap RMS above this (in dBFS) makes a beat `dirty` |
| `--loudness-outlier-db` | 6 | Drop clean beats outside median +/- this (dB) |
| `--denoise` | off | Add `afftdn` broadband denoising |
| `--denoise-strength` | 12 | afftdn noise reduction in dB; higher = quieter floor (12 safe, ~25 aggressive, 40 near-silent but artifact-prone) |
| `--no-normalize` | off | Skip `loudnorm` |
| `--dry-run` | off | Report only -- no extraction or cleanup |

## Output layout

```
<out>/
  _analysis.wav         mono 44.1k window (input normalization)
  _raw/beat_002_raw.wav raw clips, one per surviving beat (pre-cleanup)
  beat_002.wav          final processed SFX
  beat_report.csv       audit trail
```

Files are named by **candidate index**, matching the CSV rows -- if `beat_001` was dirty,
there is simply no `beat_001.wav`, and row 1 in the CSV says why.

## Report columns

`index, start_sec, end_sec, duration_sec, peak_db, classification, duration_median,
duration_band, loudness_median, loudness_band`

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
  loudness). Fine for game SFX; `--no-normalize` if you want to compare raw.
