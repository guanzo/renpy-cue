# Intensity -- design description (2026-08-19, brainstorm in progress)

Status: BRAINSTORM. One open decision (see bottom). Nothing implemented.

## Goal

When the user plays a video at different speeds (0.9x, 1.1x, 1.5x, 2x...), the
trigger system should adapt its SFX output. A single scalar -- **intensity** --
drives three knobs at fire time:

1. **Which SFX play** (pool selection by tier)
2. **How often loop SFX fire** (frequency)
3. **How loud** (volume scaling)

Intensity is a global value (one number for the whole scene), not per-trigger.

## How it sits in the existing system

The trigger engine (`CueTriggerEngine`, `cue_lib/trigger.py`) is the fire point.
It handles:

- **Loop triggers** (`l:` keys) -- `_tick_loop()` fires pooled SFX on a frequency cycle
- **Context triggers** (`i:`/`d:`/shake) -- `fire_context()` fires one-shots
- **Video triggers** (`v:` keys) -- `_tick_video()` fires SFX at marker times,
  already autoscaling marker times by speed (`effective_elapsed = elapsed * speed`)

A **pool** (`PoolDict`) is the atomic unit: `{files, volume, frequency, exclusive}`.
A trigger key maps to an **entry** with multiple pools; at fire time the engine
plays one random file from each pool concurrently (multi-pool "chords"). Loop
pools have `frequency` (discrete, mapped to a delay via `CueLoopFrequency`).

Current speed is already readable inside the engine via
`_speed_resolver.get_current_speed()`, which handles per-scene speed prefs and
speed sequences/auto-speed.

## Core concept

**Intensity is a first-class value** -- one integer in 1..3 (default 3 tiers,
extensible). It has a **source**: manual (user sets it directly) or auto
(derived from current speed each tick). Whatever the source, the fire-time
behavior is identical: the engine filters pools and scales volume by the
current intensity.

Two sources, one number:

- **Manual** -- user explicitly sets intensity (keybind cycles 1->2->3, or a
  control in the overlay). Default source. Use when speed is not the arousal
  driver (e.g. 1.0x at a scene's peak should be maximum intensity).
- **Auto** -- intensity recomputed each tick from `get_current_speed()` via a
  configurable curve. Opt-in.

Rationale: speed is a proxy for what the user wants to feel, and it lies.
Manual control is strictly more expressive; auto is just another source feeding
the same number, so it is a small addition, not a competing design.

## Auto mapping (speed -> intensity)

Configurable curve, global for v1:

- `intensity_baseline_speed` (default **1.0**)
- `intensity_baseline_tier` (default **2** -- the "neutral" tier)
- `intensity_step` (default **0.5** -- speed delta per tier)

Formula (computed each tick in auto mode):

```
intensity = clamp(baseline_tier + floor((speed - baseline_speed) / step), 1, 3)
```

Floor (not round) so any speed below baseline drops a tier immediately.
Defaults give the user's example:

- speed 1.0 -> tier 2
- speed 1.5 -> 2 + floor(0.5/0.5) = 3
- speed 2.0 -> 4 -> clamped to 3
- speed 0.8 -> 2 + floor(-0.4) = 1
- speed <= 0.5 -> 2 + floor(-1) = 1

## Where the label lives -- pool-level (working design)

Each pool gets an **intensity tag**: `intensity: 1 | 2 | 3 | absent`.
Absent (or 0) = **unset** = plays at every intensity. Tagged pools play only
when the current intensity equals their tag.

At intensity N, the engine fires: **pools tagged N + all unset pools.**

Why pool-level beats per-file tags:

- **Frequency intensity is free.** Higher-tier pools are separate pools, so the
  user sets a faster `frequency` on tier-3 pools. No new frequency mechanism.
- **Volume/exclusive also scale per tier** -- each tier pool carries its own
  volume and exclusive config naturally.
- **Minimal data change** -- one optional field on `PoolDict`;
  `_tick_loop`/`fire_context`/`_tick_video` filter pools by tier before firing.
- **Chords preserved** -- two pools at the same tier still play together.

## Volume scaling

Per-tier volume multipliers, applied at fire time on top of existing volume
(entry -> pool -> tier):

```
effective_volume = pool.volume * intensity_vols[current_intensity]
```

`intensity_vols` is a configurable curve, global for v1, default
`[0.9, 1.0, 1.25]` for tiers 1/2/3 (tier 2 = neutral 1.0).

## Engine behavior

- Resolve current intensity once per tick (auto: recompute from speed; manual:
  read the stored value).
- For each pool in the fire path: if `pool.intensity` is set and
  `!= current_intensity`, skip the pool (log it).
- When a loop pool is tier-skipped, leave its timing state (`pst`) untouched so
  it resumes on schedule when intensity returns to its tier -- do not treat it
  as "played".
- Apply `intensity_vols[tier]` to the pool volume when playing.

Scope: applies to **loop** and **context** pools (both fire from the same pool
model). Video-marker pools (also pools) can be included by the same filter for
consistency -- marker *timing* autoscale is separate and unaffected.
Include-vs-exclude for video markers is an open scope call.

## Backward compatibility

Existing saves' pools lack the `intensity` key -> all unset -> always play.
Default source = manual, default intensity = 2. A user who never configures
intensity sees zero behavior change.

## UI

- **Pool editor**: each pool row gets an intensity dropdown (`always / 1 / 2 / 3`).
- **Settings**: source toggle (manual/auto), auto curve fields (baseline speed,
  baseline tier, step), volume curve fields.
- **Overlay**: shows current intensity; in manual mode a cycle/+/-
  control; in auto mode optionally shows the derived value (e.g. "auto: 1.5x -> 3").
- **Keybind**: cycle intensity (manual), toggle source.

## Testing

- Pure logic: speed->intensity mapping (baseline/step/floor/clamp) -- pytest.
- Fire-time filtering: tier-skipped pools don't play; unset pools always play --
  pytest against the trigger engine (constructor-injected already).
- Volume scaling: effective volume = pool volume x tier multiplier -- pytest.

## Open decision

Pool-level labels (this description) vs per-file labels:

- **Pool-level** (recommended): one intensity dropdown per pool row; a pool's
  files are all that tier; frequency/volume/exclusive scale naturally per tier.
- **Per-file**: each file row gets a tier; one pool's files can span tiers; the
  engine filters a pool's files to tier-N at fire time. More granular, heavier
  UI, and frequency cannot scale (a pool has one frequency for all its files).
