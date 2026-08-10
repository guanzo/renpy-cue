# Speed Variant Integration — Design Notes

Status: discussion / pre-implementation. Date: 2026-08-06.

## Current state

- Speed variants are generated files: `{base}.{N}x.{ext}` (e.g. `anim.2.0x.webm`)
- Resolver swaps Movies via DynamicDisplayable when user cycles `.` / `,`
- Queue experiment (in progress): hardcoded tag → speed sequence, resolver
  builds Movie with `play=[paths...]`, `music.play()` gets the list atomically
- Markers fire on `v:` keys at fixed timestamps, no speed awareness

## Auto-scale (simple math, proven accurate)

```
effective_elapsed = elapsed * (current_speed / reference_speed)
```

A marker at 2.5s on 2.0x fires at the same visual frame at 5.0s on 1.0x.
No per-speed keys needed. Proven in quick test (`_cue_tick_video_triggers`).
Single multiplication per tick — no drift, no approximation.

**Limitation**: all speeds share the same SFX pools, loop frequency, and shake
settings. Fine for simple use, breaks down when user wants to vary per speed.

## Per-variant config (future)

### Key scheme

```
v:anim@1.0      v:anim@1.5      v:anim@2.0
```

- `@speed` suffix on existing key prefix
- Same key format otherwise — `create_vid_key(tag + "@{:.1f}".format(speed))`
- Auto-generated on variant creation via auto-scale math from the reference
  speed's markers
- User can override per-speed after generation

### Data flow

1. **Variant creation** (video editor): generate variant file → auto-scale
   markers from reference speed → create `v:tag@speed` entry → user adjusts
2. **Variant deletion**: drop `v:tag@speed` entry, delete file
3. **Marker edit on reference speed**: optionally backfill to existing
   variants (prompt or auto)

### Trigger mechanism

Context change fires `v:tag@1.0` on scene start (current speed is always
known at that point). Speed transitions mid-queue need a separate hook —
the VQ-PLAY file-change detector already tracks this. When file switches
from `anim.1.0x.webm` to `anim.1.5x.webm`, fire `v:tag@1.5` triggers and
clear played-keys for the old speed.

### Per-variant config beyond markers

Loop frequency, shake trigger, volume — all already per-pool in the marker
system. Just keyed by `v:tag@speed` instead of `v:tag`. No new data model.

## Queue config persistence

Currently hardcoded in `_cue.video_queue_map`. Needs to move to
`_cue.markers._data` (persisted via `save_persistent()`) with a UI.
Same pattern as video presets — store sequence per tag, editable in overlay.

## Touch points summary

| Area | Change needed |
|---|---|
| Key scheme | Add `@speed` suffix variant |
| Marker auto-scale | On variant create/delete, auto-generate per-speed markers |
| Trigger engine | Fire per-speed keys on file transitions (VQ-PLAY hook) |
| Queue config | Move from hardcoded dict to persisted markers data |
| UI | Speed-sequence editor, per-speed marker editing |
| Resolver | Already handles per-speed Movies via `(tag, speed)` cache key |

## Open questions

- Reference speed: always 1.0x? Or user-selectable? (current test hardcodes 2.0)
  - Default to 1.0x, let user override
- Backfill: if user edits 1.0x markers, prompt to backfill existing variants?
  - hmmm.. only if the existing variants have manual markers, otherwise autoscale should work automatically
- Queue cancel: return to which speed? Last in queue, or a default?
  - they cancel with ,(down speed) or . (up speed), to use their last speed_pref as the base, and go up/down from there.
- The overlay UI needs to be in sync with the variants.
  - As differnt variants play, the active variant's speed should be highlighted (as if the user clicked it)
  - markers should update whether they're auto scaled or manual variant markers
- need per variant config, so user can mess with volume, loop frequency, sfx pools, etc.
- need a way to pause on a variant to edit config
