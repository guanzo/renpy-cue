# Exclusive SFX

This system prevents dialogue SFX from overlapping each other. Two design choices follow directly from that goal:

- **Video-marker SFX are exempt** from being faded out early.
- **Loop SFX are handled separately** from one-shots — loops never cut, or get cut by, one-shot dialogue.

These exemptions reflect a usage pattern (video pools tend to hold non-dialogue effects; loop pools tend to hold dialogue effects), not a hard content rule. The system doesn't inspect what's actually in a pool — it just treats `video` and `loop` as separate lanes from `oneshot`.

**Out of scope:** previews (the user manually pressing "Play" on a SFX file) never touch this system. Everything below applies only to SFX triggered by markers.

## Kinds (domains)

Every pool's `exclusive` dict drives one of three kinds, identified by a key prefix:

| Kind | Key prefix | Example | Role |
| ---- | ---- | ---- | ---- |
| `loop` | `l_` | `l_ambient_rain` | Fires on a frequency cycle; may hold and defer. |
| `oneshot` | `i_` / `d_` / shake | `i_door_creak`, `d_line042` | Fires once on context change. |
| `video` | `v_` | `v_explosion` | Fires at marked times in a video. |

The wait/hold gates are **kind-filtered**: a loop never blocks a one-shot or vice versa. Video SFX are only tracked so the one-shot cut-in sweep can spare them — they never block anything, and nothing waits on them.

## Tracking

`excl_channels` maps each active SFX channel to:

- `kind` — one of the above
- `scene` — the current file
- `line` — the `D_` key, or `None` for image/shake
- `hold` — the pool's `exclusive.hold` flag

`_track_excl_channel()` records a SFX when it starts; `_prune_excl_channels()` drops entries whose channel has gone silent.

## Grouping

A **group** is the set of SFX considered to share the air: a cut-in spares its own group and fades everything else. Grouping only matters within a kind.

- **Loops never share a group** — every loop competes with every other loop.
- **One-shots** in the same scene (file) share a group, **except** two dialogue SFX on different lines.

Concretely, within a scene: image, shake, and dialogue coexist in one group. A new dialogue line does *not* join that group — it cuts the previous one.

## Gates (checked before a SFX may start)

- **hold** — a *holding* same-kind SFX outside the group owns the air: a new one-shot drops instead of playing; a new loop defers and retries.
- **wait** — any same-kind SFX outside the group is already playing: one-shots drop (they can't defer); loops defer.

Video-marker SFX are exempt from both gates by construction.

## Cut-in sweeps (`start=FADE`)

`start` is either `PLAY` (start immediately, overlapping whatever's playing) or `FADE` (sweep out conflicting SFX first). The fade sweep is asymmetric:

- **One-shot fade** fades everything outside the current group — including other one-shots and loops (one-shots cut loops) — but **spares video-marker SFX**.
- **Loop fade** fades **only other loops**, never image/dialogue SFX.

Sweeps only touch the shared `_cue_N` SFX channels; the movie channel's own audio is never swept.