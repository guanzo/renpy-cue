# System Design & UX Audit: Renpy Cue

## Context

Renpy Cue is a Ren'Py mod that attaches SFX (sound effects) to visual novel contexts — images, dialogue lines, video timestamps, and looping backgrounds. Users press backtick to open an overlay sidebar, browse audio files, and assign them to trigger points. The mod also supports video playback speed changes via ffmpeg.

This audit examines the codebase from two angles: engineering design and user experience, identifying what's overly complex and could be simplified.

---

## Engineering Perspective

### What's Well-Designed

- **Single `NoRollback` root object** (`_cue`): All state lives on one object excluded from Ren'Py's rollback system. Simple, correct, and consistent.
- **Class-per-feature organization**: Each manager class owns its state, logic, and screen hooks. Clean separation — `CueMarkerManager`, `CueVideoManager`, `CueVolumeManager`, etc.
- **Typed context accessors**: `_cue.markers.image`, `.dialogue`, `.video`, `.loop` provide domain-specific APIs over a shared data store. The `CueMarkerContext` ABC extracts common pool CRUD.
- **Key prefix scheme**: `i:`, `d:`, `v:`, `l:` prefixes create a flat namespace that's easy to debug, serialize, and extend.
- **Preset system with override merging**: `resolve_pool()` merges preset defaults with per-pool overrides, so users can tweak volume/frequency on a preset-backed pool without detaching. The detach-on-file-mutation pattern is clever.

### What's Over-Complicated

#### 1. Three Overlapping Speed Systems

There are **three separate video speed mechanisms** that interact in subtle ways:

| System | How | Where |
|---|---|---|
| Speed resolver | DynamicDisplayable wrapping, `.`/`,` keys cycle through variants | `_cue_resolver()`, `_cue_cycle_speed_new()` |
| Speed queue | Hardcoded `video_queue_map` dict, queues `play=[paths...]` sequences | `_cue_video_queue_speeds_for()`, `_cue_start_video_queue()` |
| Video editor | ffmpeg generates `.Nx.webm` variant files, async job queue | `CueVideoEditor`, worker threads |

The resolver has **4 separate caches** (`speed_prefs`, `resolver_paths`, `resolver_children`, `video_queue_map`) and the queue system has its own state (`video_queue_active_tag`, play-count tracking). Canceling a queue falls back to resolver mode. The resolver callback (`_cue_resolver`) has queue-awareness baked in — when `video_queue_active_tag` is set, it takes a different code path.

**Recommendation**: The speed queue is marked experimental and hardcoded. Either commit to it and unify it with the resolver (store queue configs in persistent markers like speed prefs), or remove it until needed. The resolver alone handles the 90% use case (cycle through available speeds).

#### 2. Legacy Migration Code Running on Every Load

`load_persistent()` calls **four migration/sanitization passes** every time:
- `_migrate_video_timestamps_to_pools()` — rename `timestamps` → `pools`
- `_sanitize_video_pools()` — strip pools without `time` key
- `_sanitize_video_presets()` — same for presets
- `_normalize_all()` — migrate `{files: [...]}` → `{pools: [{files: [...]}]}`, move entry-level frequency into pools

These are idempotent but run unconditionally. Once all users have migrated data, these should become one-time checks (e.g., a schema version number in the config).

**Recommendation**: Add a `_cue_config["schema_version"]` field. Run migrations only when the version is below the current one, then bump it.

#### 3. Fragile Video Seek via Stop/Restart

Forward frame-step works by unpausing and relying on `poll_autopause()` to re-pause at a target position. Backward seek **stops the channel entirely and replays from 0** with `pause_target`. This is inherently fragile — it depends on:
- The tick timer catching the position before it overshoots
- The channel not being used by something else during the stop/play gap
- The `time_offset` tracking not drifting

The `_finish_swap()` method even has `time.sleep(0.5)` to "release file locks" — a clear sign of fighting the engine.

**Recommendation**: This is mostly a Ren'Py limitation (no native seek API). The current approach works but is the most likely source of bugs. Consider documenting the limitations clearly or adding a "seek accuracy" note in the UI.

#### 4. Channel Detection Reentrancy Guard

`_cue_refresh_channel()` has a `__refreshing_channel` boolean flag to prevent reentrant calls. This suggests the function has caused infinite loops or stack overflows in the past. The detection logic searches both `renpy.audio.audio.channels` (private API) AND hardcoded channel names (`"movie"`, `"_movie_1"`, `"_movie_2"`).

**Recommendation**: The guard suggests a fragile code path. At minimum, add a comment explaining what sequence of events causes reentry. Consider whether the tick-based channel refresh (called every 25ms even when nothing changed) could be throttled to only run on context changes.

#### 5. The `_cue_refresh_context` Function Is a God Function

At ~80 lines, this function does everything: detects the top displayable, refreshes the video channel, logs context, builds trigger keys, detects changes, fires triggers, handles screenshake dedup. It's the central nervous system of the mod and touches every subsystem.

**Recommendation**: Break into smaller functions: `_cue_detect_context()`, `_cue_detect_changes()`, `_cue_handle_context_change()`. The logic is sound but the monolith makes it hard to reason about side effects.

#### 6. Video Editor Job Queue Is a Full Async Runtime

The `CueVideoEditor` implements: background threading, a job queue with states (queued/analyzing/encoding/done/error), progress parsing from ffmpeg stdout, two-pass encoding support, cancel/retry/remove, temp file cleanup, backup/restore, orphan cleanup on init. The `_worker` method alone is ~140 lines.

This is a lot of infrastructure for a niche feature (video speed changes). The complexity is mostly necessary given ffmpeg's blocking nature and Ren'Py's single-threaded UI — but it's the single most complex file in the project.

**Recommendation**: This is justified complexity given the constraints. The main improvement would be extracting the worker thread logic into `cue_ffmpeg.rpy` so `cue_video_editor.rpy` focuses on state/UI.

---

## UX Perspective

### What's Good

- **Single hotkey to open/close** (backtick) — easy to discover, doesn't conflict with VN controls
- **Context-aware UI**: The overlay shows Image SFX, Dialogue SFX, or Video SFX depending on what's currently displayed
- **Preview button** (▶) on every audio file — immediate feedback
- **Drag-and-drop timeline** for video markers with multi-select (Alt+Click, Shift+Click)
- **Collapsible sections** keep the sidebar manageable
- **Presets** let users reuse SFX configurations across scenes

### What's Over-Complicated for Users

#### 1. The "Pool" Concept Is Exposed Too Early

Pools (groups of SFX that play simultaneously) are a power-user feature. But the UI puts pool tabs front and center: numbered `[1][2]...` buttons, a "+ Pool" button, and "Delete all image SFX" hovering over the ✕ icon. A new user just wants to add a moan to a scene — they shouldn't need to understand pools.

**Recommendation**: Hide pool tabs when there's only one pool. Auto-create the first pool. Only show "+ Pool" when the user has demonstrated understanding (e.g., after they've added files to the first pool). The advanced pool management could be behind a "Advanced" expander.

#### 2. Six Action Buttons Per Audio File

Each file in the SFX Library has: `▶ V I D L ☑/☐` (preview, video, image, dialogue, loop, disable). That's 6 tiny icon buttons per row. New users won't know what V, I, D, L mean without tooltips.

**Recommendation**: Consider a right-click context menu or a single "Add to..." button that shows a popup with the four context options. The disable toggle could move to a separate "Manage Files" mode. This would reduce each row to `▶ +` (preview + add).

#### 3. Two-Tier Volume (Master × Pool) Is Mathematically Sound but UX-Confusing

When master=0.8 and pool=1.5, the effective volume is 1.2, and the UI shows "Volume: 1.5 (1.2 total)". Users think in terms of "how loud is this SFX" — the multiplication model means changing master affects all pools, which may surprise someone who just wants to make one pool quieter.

**Recommendation**: For most users, a single volume slider per pool is sufficient. The master volume could be an advanced feature hidden behind a "Volume Mixer" expander. Or, make master additive instead of multiplicative (pool_volume + master_offset).

#### 4. The SFX/VFX Tab Split in Video Context

When a video is playing, the overlay shows "SFX" and "VFX" tabs. SFX has the marker timeline (the core feature). VFX opens a completely different UI with: speed factor input, interpolate toggle, fast preview toggle, custom speed presets, create button, and a job queue. This is a video editing tool embedded in an SFX tool.

**Recommendation**: The VFX tab is a separate tool. Consider splitting it into its own overlay (e.g., Ctrl+Shift+` for video tools, backtick for SFX tools). This also solves the issue of the overlay being too tall when both SFX and VFX content is visible.

#### 5. The Repeat Pattern Dialog

This dialog has: anchor time, interval in seconds (with nudge buttons), repeat count, a preview of how many markers will be created, and ghost markers on the timeline. It's powerful but presents 5+ controls for a single operation. The ghost preview is excellent — but the dialog could be inline rather than floating.

**Recommendation**: Integrate the repeat controls into the main Video SFX section (below the timeline) rather than as a floating dialog. Show ghost markers whenever an interval is set (real-time preview).

#### 6. Copy/Paste Context Is Invisible

Shift+1 copies, Shift+2 pastes. There's no visual feedback about what's on the clipboard, or even that the copy succeeded. Users can accidentally overwrite markers by pasting into the wrong scene.

**Recommendation**: Show a brief toast/notification on copy ("Copied 3 video markers, 1 image pool, 2 dialogue pools"). Show the clipboard contents in a small hoverable indicator.

#### 7. Too Many Top-Level Buttons in the Header

The top bar has: SFX Active toggle, copy, paste, backup, restore, pause game, refresh, close. That's 8 buttons plus a toggle. Backup/restore are power-user operations that could move to a menu.

**Recommendation**: Group into: `[Active] [Copy] [Paste]` | `[Refresh] [Close]`. Move backup/restore to a "..." menu or the bottom of the SFX Library section.

---

## Summary of Recommendations (Priority Order)

### High Impact, Lower Effort

1. **Remove or finalize the hardcoded speed queue experiment** — it's marked experimental and adds a parallel code path to the resolver
2. **Add schema versioning to skip legacy migrations** — four sanitization passes on every load is wasteful
3. **Auto-hide pool tabs when there's only one pool** — cleans up the UI for the 80% use case
4. **Show a clipboard status indicator** — prevents accidental paste-overwrites

### Medium Impact, Medium Effort

5. **Reduce per-file button count** — consolidate V/I/D/L into a single "Add to..." action
6. **Split VFX tab into its own overlay or hotkey** — keeps the SFX overlay focused
7. **Break up `_cue_refresh_context`** — improves maintainability without behavior changes
8. **Inline the Repeat Pattern dialog** — integrates it into the main flow

### Lower Priority / Nice to Have

9. **Extract worker thread logic from CueVideoEditor into cue_ffmpeg.rpy** — separation of concerns
10. **Simplify two-tier volume or hide it behind advanced settings** — reduces cognitive load
11. **Document the channel detection reentrancy guard** — explains why it exists

---

## Verification

No code changes are proposed in this audit. To validate the analysis:
1. Open the overlay in any supported Ren'Py game
2. Walk through each UI section (Video SFX, Image SFX, Dialogue SFX, Loop SFX, SFX Library)
3. Note which concepts require reading tooltips to understand
4. Count the number of buttons/controls visible at once
5. Trace the code path for a single context change (set a breakpoint in `_cue_refresh_context`)
