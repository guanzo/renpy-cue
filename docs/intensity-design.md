# Intensity -- design description (2026-08-21, committed after grilling)

Status: COMMITTED DESIGN. Nothing implemented. UI designed to MVP scope (see
"UI"). This doc supersedes the earlier brainstorm (baseline-anchored model),
which is abandoned.

## Terminology

Defined up front so the rest of the doc reads unambiguously. Numbers name
positions, never groups; groups are always named.

- **Group** -- the global palette template: a named, ordered folder list. Names
  are arbitrary strings ("Impacts", "Mouth"), never numbers. (Previously
  "intensity group" / "igroup".)
- **Level** -- a position *within a group*, 1..N, where N = the group's folder
  count. Level 1 = softest, Level N = hardest. Scoped to a group, not a global
  1..3; synonym for folder index.
- **Band** -- a contiguous slice of the video's sorted speed-variant list
  assigned to a level. Band N maps to level N. The speed-side counterpart of a
  level.
- **Variant** -- one playback speed in the banding set (a `_cue{X}x` file, a
  Multi sequence step, or an enabled Auto speed).
- **Hook** -- the single group folder added to a pool that links the pool to its
  group and auto-enables intensity.
- **Active level** -- the level a given pool is playing right now, resolved from
  the current speed.
- **Scaling anchor** -- the pool's configured volume and loop frequency: the
  reference every level multiplier scales from. Per-pool, not a new knob (it is
  the pool's existing settings). Distinct from the banding anchor that was
  killed (a speed->level pin); see Runtime behavior.
- **Pool** -- unchanged: the trigger engine's atomic unit.

## Goal

When the user plays a video at different speeds (0.9x, 1.1x, 1.5x, 2x...), the
trigger system should adapt its SFX output. A scalar -- **intensity** -- selects
which audio folder set plays at fire time and scales how loud and how often it
fires.

The system decouples the audio asset structure (**Intensity Group**) from the
video playback speeds (**Variant Mapping**), so creators don't tag files per
video. Two layers:

- **Global Intensity Groups** -- reusable sound palettes: ordered folder lists
  where order = level order (first = softest, last = hardest).
- **Per-pool hooks** -- adding one folder from an intensity group to a pool
  auto-enables intensity for that pool; the runtime plays the group's folder for
  the active level.

## Intensity Groups (global palette templates)

- A group is a named, **ordered folder list**. Folder order = level order: the
  first folder is Level 1 (softest), the last is Level N (hardest).
- **N = folder count**, user-supplied. Recommend 2-3, no cap.
- Each level carries a **volume multiplier** and a **frequency multiplier**,
  both **relative to the pool's configured base** (see Runtime behavior): Level
  1's multiplier is 1.0, so a level-1 fire is exactly the pool's volume and loop
  frequency; higher levels scale up from there. Defaults: a linear ramp, Level 1
  = 1.0 to Level N = max within the clamps. Every level's multiplier is
  editable.
- The registry maps each folder -> (group, level). This is the single source of
  truth the runtime consults.
- **Graceful degradation (downward only):** if the active level's folder is
  empty/missing, step to the next lower populated level; if Level 1 is empty,
  silence. Never step up -- softer-or-silent is the safe default.

## Per-pool setup

- Add **one** folder from an intensity group to a pool -> **auto-enables
  intensity** for that pool. The folder is a hook: the runtime identifies the
  group from it and plays the group's folder for the *active level*. The other
  group folders (B, C...) are never added to the pool.
  In the UI this is the `+` button on the group's folder rows (see UI): the
  folder lands in the currently-targeted pool as a normal pool entry, and the
  group is detected by membership.
- **Per-video toggles** (not per-pool): intensity on/off plus three independent
  sub-toggles -- **SFX-levels**, **volume**, **frequency** -- all default on.
  Intensity off -> pools play their listed folders plainly. SFX-levels off (with
  intensity on) -> hooked pools play their own listed folders (the hook folder
  as a plain folder) while the active level still drives volume/frequency.
- **Untagged folders** (in no group) play normally, always eligible -- this is
  what makes the system backwards compatible.
- **Guardrails:**
  - **One intensity group per pool.** Adding a second group's folder to the same
    pool is rejected with a clear message.
  - Multiple folders of the same group in one pool collapse to one hook
    (harmless).
  - A group-assigned pool is edited by CRUD-ing the group, not the pool.

## Mapping -- gap-aware banding

Intensity levels are spread **evenly across all speed variants**, not anchored
to 1.0x -- but the cut positions respect natural clusters in the variant
values, so intent encoded in non-uniform spacing is preserved.

- **Bands are computed per pool.** The **variant list** is shared per-video by
  mode:
  - **Multi** -> its `speed_sequence`.
  - **Auto** -> its enabled auto speeds.
  - **Single** -> intensity doesn't apply; pool plays directly.
  but **N comes from that pool's group's folder count**. Two pools with
  different groups (even different N) resolve independently: the same speed can
  land on different levels in different pools. Extrema always agree (all pools
  softest at the slowest speed, hardest at the fastest).
- **Gap-aware banding (largest-gap):** sort the variants, compute adjacent
  gaps, and cut at the **N-1 largest** gaps. A greedy approximation of Jenks
  natural breaks (1-D contiguous clustering minimizing within-band variance).
  Slowest band = Level 1, fastest = Level N.

  Formula (gap-split): `level` = band number of the variant's slot, where band
  boundaries are the N-1 largest adjacent gaps.

  Example: variants `[.5,.9,1,1.1,1.2,2]`, N=3. Gaps `.4,.1,.1,.1,.8` -> cut
  at `.8` and `.4` -> Level 1 = `.5`, Level 2 = `.9,1,1.1,1.2`, Level 3 = `2`.
  A "normal" cluster around 1x plus surprise spikes -- expressed by variant
  spacing, read by the algorithm.
- **Tie-break (uniform gaps):** when gaps tie -- the original
  `[.6,.7,.8,.9,1,1.1,1.2,1.3,1.4]` case, all gaps equal -- cut to keep band
  sizes most even: `level = ceil((rank + 1) * N / count)` (0-based rank,
  1-based level, extras to the faster bands). So gap-aware banding equals the
  plain rank/even split exactly whenever there is no clustering to detect; no
  "strict even" toggle is needed.

  With a second pool hooked to a 2-folder group (N=2), the same list bands as
  Level 1 = `.6,.7,.8,.9`, Level 2 = `1,1.1,1.2,1.3,1.4` -- so at 0.9x the N=3
  pool is on level 2 while the N=2 pool is still on level 1.
- **A level change is per pool**, matching the per-pool `ready_at` timer model:
  drop-deferred/restart-timer fires independently per pool when its own bands
  cross.
- **More bands than gaps** (e.g. a 5-level group on a 3-variant video): auto
  banding cannot give every band a variant, so low levels come out unreachable
  (the even-split formula maps ranks to `L2,L4,L5`, leaving the softest empty).
  Cases like this are what the manual escape hatch covers.

- **1.0x's level is computed**, not configured -- shown in the mapping table. No
  baseline, no speed->level anchor, no offset. (The *scaling* anchor in Runtime
  behavior is a different axis and is unaffected.)
- **<2 distinct speeds** -> treated as single-speed (no intensity).
- **Off-list runtime speeds** (rare: direct `speed_pref`/sequence-step setting,
  transitions) -> snap to the nearest listed variant. Normal UI-driven operation
  only produces listed speeds.
- **Calibration for inherent video content** = the user's group choice per pool.
  Code can't see content (1x in one video can be wildly faster than 1x in
  another); the group's character is the knob. Choosing which group a pool uses
  IS the per-video adjustment. No separate offset.

## Manual override (escape hatch)

Auto banding cannot express every intent, so each pool has an **Auto / Manual**
banding toggle. Off by default (Auto). Manual never affects other pools.

- **Manual = editable mapping table.** The same table the Inspector already
  shows, seeded from the auto result; each variant row gets a level dropdown
  (1..N). Arbitrary assignment is allowed -- empty bands and non-contiguous
  mappings included.
- **New variants** added after a manual map is set default to their auto-seeded
  level; the user may leave or change it.
- **Off-list runtime speeds** still snap to the nearest listed variant; the
  manual map governs the listed ones.
- Covers what auto cannot: non-contiguous intent (e.g. `.5` and `2` in one
  band, `1` alone), deliberately unreachable bands, and the more-bands-than-
  variants case.
- **Not the baseline resurrection.** Opt-in per pool, seeds from the auto
  result, no "baseline level" knob. The killed anchor was a default mechanism
  built on a baseline setting; manual is an explicit escape hatch with the whole
  map owned by the user.
- Design commitment only -- the build is a later milestone, after the auto path
  proves itself in the wild.

## Runtime behavior

- Each tick: read current speed -> resolve level via banding -> group folder for
  that level (with downward fallback) -> random file pick with repeat avoidance.
- **On level change:** currently-playing SFX finish untouched; pending/deferred
  fires are dropped; the new level's timer starts fresh (first fire after its
  normal delay). No per-tier timer state -- prime the new pool immediately, but
  follow all default timing logic.
- Marker triggers fire from the active level's folder at timestamps; loop
  timers stay per-pool (existing `ready_at` model).
- **Anchor: the pool's configured base.** `pool_volume` and `base_delay` below
  are the pool's own configured values -- that is the reference every level
  scales from, not a constant. Per-pool: the same group hooked to two pools
  yields the same *relative* scaling but different absolute loudness/frequency.
  Retuning the pool's base retunes every band proportionally -- one knob for the
  video's whole feel.
- **Volume** (every fire): `effective_volume = pool_volume * level_multiplier`,
  multiplier clamped to **[1.0, 1.25]** -- intensity never lowers volume below
  the pool's configured level (the pool's volume is the floor at Level 1); users
  lower the pool/master volume themselves if they want it quieter.
- **Frequency** (loop pools only): the next loop delay =
  `base_delay / level_multiplier`, clamped to the existing frequency range --
  **[0.2s fastest, 6s slowest]**. `base_delay` is the pool's configured loop
  frequency. Both directions are reachable within the clamp: higher levels fire
  faster, lower levels slower. With a "fastest" base the upper bands have no
  headroom (stuck at 0.2s); only the lower bands can go slower. A level change
  restarts the timer with the new level's scaled delay.

## UI

Two homes, matching the two-layer design. The Editor page is already at
capacity, so nothing here adds a new top-level page or collapsible section.

**Group manager -- SFX Library block.** An expandable `"Intensity Groups/"`
block inside the SFX Library section (the same scrollable vbox as Recently Used
/ Pool Presets / Video Presets / the file tree), collapsed by default. The
library is where the user does file/folder work, and groups are the same family
as presets (named folder collections) -- just ordered, and editable.

- `"New Group"` -> name modal (reuses the save-preset dialog pattern) -> an
  empty group.
- Group expanded -> **ordered level rows**: `Level 1: [folder]`, `Level 2:
  [folder]`, ... Folder order *is* the level definition, so the row label is
  level N.
- **Usage -- add a group to a pool:** a `+` button on each group **folder row**
  (not the group row, not files), matching the tree's per-row `+`. It appends
  that folder to the currently-targeted pool as a normal pool entry; the runtime
  detects the group by membership (see Per-pool setup).
- **Construction -- add a folder to a group:** scoped **click-and-drop**. A mode
  button in the igroup block (shown during group editing). Active -> the igroup
  rows become highlighted **drop zones**; click a folder in the tree, then click
  an igroup zone -> the folder appends as the next level. Exit ends the mode.
  Drop zones are igroup rows only -- target contexts are explicitly out of scope
  and the Target system is untouched. (Drag-and-drop was tried and failed; this
  is a deliberate two-click transfer instead.)
- **Reorder** = up/down icon buttons on the level rows (no drag anywhere in the
  codebase); **x** removes a level; levels renumber on any change.
- Guardrail: one group per pool; adding a second group's folder to a pool is
  rejected with a clear message.

**Per-video hooking -- Video SFX (the de-facto inspector).** The per-video
intensity toggle (auto-on when a group folder is added) plus the three
sub-toggles (SFX-levels / volume / frequency), the per-pool detected group, the
per-pool Auto/Manual banding toggle, and the real-time mapping table (speed list
-> bands -> levels -> folders), with explicit copy that adding a group folder
enables intensity.

Note: the codebase has no dropdown component; the mapping table follows the
`CueAutoSpeedChart` displayable precedent.

## Integration points (for the build)

- Folder -> group registry: new global config; groups reference game-relative
  folder paths.
- Per-pool group hook: extension to `PoolDict` (or a per-folder tag map).
- Reuse `_cue_resolve_files` / `_cue_pick_file` (folder expansion + repeat
  avoidance), per-pool `ready_at` timers in `_tick_loop`, and
  `_speed_resolver.get_current_speed()` each tick.
- Banding/level resolution is pure logic -> headless pytest (TDD). Folder
  registry + engine wiring + UI -> harness testcases.
- Backward compatibility: existing saves' pools have no group hook and no
  intensity tag -> all folders untagged -> play normally. A user who never
  configures intensity sees zero behavior change.
- Persistence: **groups are shared** -- one JSON per group at
  `shared_dir/data/presets/intensity/<name>.json`, like presets. **Usage state
  lives in the marker data** (per-game `persistent`): the hook is a folder in
  the pool's file list; the per-video toggles are video-level marker fields; the
  Auto/Manual banding mode and manual map are per-pool fields.
