# Intensity Levels as Pools

Date: 2026-08-24

## Problem

An intensity group (igroup) is a named, ordered list of *folders* — folder order
is level order, one folder per level. To broaden a level (add another folder or
an individual file) the user must mutate the filesystem. Levels should instead
be pools: arbitrary lists of folders **and** files, editable in-app the same way
a marker pool is.

A second, entangled problem: the pool→igroup hook is implicit. A pool is hooked
when one of its `files` folder refs happens to be registered in an igroup
(`resolve_hook`). That is fragile once a level can be folder-less, and it
silently changes a pool's behavior when the user merely adds a folder for its
sounds.

## Data model

### `LevelDict` (new, `_types.py`)

```python
class LevelDict(TypedDict, total=False):
    id: int
    files: List[str]
```

No `volume`/`frequency` fields. The intensity ramp stays a pure function of
level count (`_level_ramp`), computed at resolve time — it is never user-edited
today, so it is not stored.

### Igroup JSON

```json
{
  "next_ilevel_id": 3,
  "levels": [
    { "id": 1, "files": ["soft/", "soft_extra.wav"] },
    { "id": 2, "files": ["hard/", "hard_b/"] }
  ]
}
```

Replaces `folders` + `volume_multipliers` + `frequency_multipliers`. `id` is a
stable per-level identity (see below); `next_ilevel_id` is a monotonic counter
that is never decremented, so a deleted level's id is never reused.

### `PoolDict` (extended, `_types.py`)

```python
igroup: str        # the intensity group name (hook)
ilevel_id: int     # stable id of the level the pool is pinned to (fallback)
```

A hooked pool has **empty `files`** — its content is the level, resolved live.
`files` stays meaningful only for non-hooked pools.

### Naming

Always `ilevel`-prefixed, never bare `level`: `igroup`, `ilevel_id`,
`next_ilevel_id`.

## Stable level ids

- `[+ Level]` assigns `id = next_ilevel_id`, then increments `next_ilevel_id`.
- Reorder/insert move the level dict; its `id` travels with it, so a pool's
  `ilevel_id` never retargets.
- Only *removing* the referenced level dangles the ref; resolution falls back
  to level 1 (the group's softest).

## Resolution semantics

The ramp is unchanged: `volume_mult` multiplies the pool's effective volume
(1.0 → `CUE_INTENSITY_VOLUME_MAX`); `freq_mult` divides the loop delay
(1.0 → `CUE_INTENSITY_FREQ_MAX`).

`resolve_pool_intensity` now takes `igroup` + `ilevel_id` (not `files`) and:

- no `igroup` → `None` (caller plays the pool's own `files`).
- `enabled` off → play the pinned level (`ilevel_id`), no scaling.
- `sfx_levels` off → play the pinned level (`ilevel_id`), scale volume/freq by
  the active level.
- `sfx_levels` on → band speed → active level, play its files, scale.

Loops are unaffected: `_tick_loop` already resolves every loop pool through
`resolve_pool_intensity`, and `freq_mult` scales the loop delay
(`_cue_effective_delay`).

## `intensity.py` changes

Delete (folder-discovery machinery, now inert):

- `_folder_index`, `_folder_index_cache`, `resolve_hook`, `group_for_folder`,
  `pool_group`, `check_add_folder`, `level_folder`.

Change:

- `add_folder` → `add_level` (new empty level) and `add_level_file` (append a
  file/folder ref to a level's `files`).
- `remove_level` / `move_level` → operate on `levels` (ids travel).
- `level_multipliers` → derive from `_level_ramp(len(levels), MAX)`, cached.
- `level_files(name, ilevel_id)` → resolve the level's files by id; dangling id
  → level 1.
- `resolve_pool_intensity(group, ilevel_id, speed, variants, flags)`.
- `resolve_video_intensity` / `current_level` / `video_hook` /
  `is_pool_intensity_active` → "first pool with `igroup` set" instead of
  "first folder-registered pool".

`banding.py` unchanged — level count is still `len(levels)`.

## Call sites

- `marker_store.py`: `resolve_pool` surfaces `igroup`/`ilevel_id` on
  `ResolvedPool`.
- `trigger.py`: `_vid_intensity_resolution`, `_tick_loop` (`:409`),
  `_fire_video_markers` (`:598`) pass `resolved.igroup`/`resolved.ilevel_id`.
- `marker_context.py`: remove `check_add_folder` calls in
  `CueMarkerContext.add_folder` (`:270`) and `CueVideoContext.add_folder`
  (`:464`, `:471`) — folders are inert.
- `video_vfx.rpy`: inspector reads group/level from pool fields; mapping list
  uses `level_files`.
- `displayables.py`: `is_pool_intensity_active` (`:346`) and `current_level`
  (`:890`) read pool fields.

## UI

- **Group row:** `[x] delete` · `[name]`.
- **`[+ Level]`:** below the group row (indented, shown when the group is
  expanded), mirroring how `[+ Group]` sits below "Intensity Groups/". Creates
  an empty level (id from `next_ilevel_id`) and auto-expands it.
- **Level row:** `[x] remove` · `[↑]` `[↓]` · `[+] add-to-target` (old `[V]`,
  now target-aware) · `[folder-plus] add-files toggle` · `[play] preview` ·
  "Level N" + its file list. Empty level shows help text
  ("Click the folder icon to add files").
- `[+]` writes `igroup` + `ilevel_id` on the active target context's pool;
  disabled when the target is image/dialogue (those pools never resolve
  intensity). Loops are an allowed target.
- Level file list mirrors the audio-tree file UI (per-file preview + remove).
- Add-files mode target becomes `(group, ilevel_id)`; the tree `[+]` appends to
  the level's `files`.

## Migration (on load)

- Old igroup (`folders` present): build `levels` with sequential ids
  (`next_ilevel_id = N+1`), dropping the two multiplier arrays (ramp is
  derived).
- Old folder-hooked pools: set `igroup` = group, `ilevel_id` = id of the level
  that held the first hook folder; clear `files` (a hooked pool's content is the
  level). Edge case: a pool that mixed a hook folder with other content loses
  that other content in the fallback — acceptable, empty fixtures today.

## Testing

- pytest: level add/remove/reorder with stable ids (dangling → level 1);
  `_level_ramp` derivation; the two migrations; `resolve_pool_intensity`
  group-driven resolution across `enabled`/`sfx_levels` states.
- harness: igroup editing, `[+]` hooking (video + loop), on both engine
  generations.
