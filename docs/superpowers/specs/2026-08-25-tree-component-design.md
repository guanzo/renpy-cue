# Reusable Tree Component

Date: 2026-08-25

## Problem

The folder/file tree UI is duplicated across four surfaces that render the same
row shape — `[indent] [buttons...] [toggle-or-name]` — from data that is already
unified (`CueAudioTreeManager.visible_tree`, depth-annotated flat rows):

1. SFX Library file tree (`cue_file_tree`, `sfx_library.rpy`)
2. Music Library file tree (`_cue_music_file_tree`, `music_page.rpy`)
3. Collapsible sections (Recently Used/, Pool Presets/, Video Presets/, Music
   Presets/, Intensity Groups/)
4. Pool file lists (`_cue_file_list_vbox`, `components.rpy`)

The copies have drifted (music file rows order `[plus][play]`, SFX `[play][plus]`;
music folders have no play button; SFX carries a warn icon and intensity add-mode
`+` swap). Every behavior change must be hand-applied to N copies. The search
filtering / expansion gating / add-mode branching lives in `.rpy` screens that
pytest cannot touch.

## Constraint

**1:1 output.** Nothing is added, removed, or reordered visually. Every button,
tooltip, enabled-gate, gap, and warn icon reproduces the current UI exactly. This
refactor is behavior-preserving; it changes where the logic lives, not what it is.

## Architecture

Every row the tree renders is a data dict; one dumb screen draws any dict.

### Row schema

```python
{
    "key": "tree:sfx/foo.wav",     # unique id (hover tracking)
    "type": "folder" | "file" | "action" | "help",
    "label": "foo.wav",            # display text
    "depth": 1,                    # indent levels; pad = depth * _cue_indent
    "buttons": [{"icon", "action", "tt", "enabled", "bg"}, ...],
    "hover_buttons": [...],        # extra buttons, shown only while row hovered
    "toggle": Function(...),       # folder: click label to expand/collapse
    "action": Function(...),       # action: click label to run
    "tt": "...",                   # action: tooltip
    "warn": "reason",              # file: triangle-exclamation + tooltip
    "gap": 1,                      # file: null width before the label
}
```

### `cue_tree_rows(rows)` — the renderer (`components.rpy`)

`vbox spacing 2`; per row: indent (`_cue_indent * depth`), then `buttons` via
`cue_icon_btn`, then `hover_buttons` while `_hovered_key == key` (each with
`on_hover`/`on_unhover` keeping the key alive), then by type:

- folder: `cue_txt_button(label, toggle)` with hover tracking
- action: `cue_txt_button(label, action, tt)`
- help: `etext label style "cue_help"`
- file: `null width gap`, `etext label color text_accent`, warn icon if `warn`

Owns `default _hovered_key = None` (transient UI state; survives interaction
restarts, resets on screen wipe like today's `_hovered_level`).

### Shared helpers (`.py`, pytest-able)

- `_section_rows(key, label, toggle_fn, expanded, searching, has_any, child_fn,
  auto_show=True)` — collapsible-section header + children-when-open. Header
  hides during a search unless `has_any()`. `auto_show=False` for video/music
  presets (content does not auto-expand on search).
- `_folder_rows(key, label, depth, toggle_fn, expanded, searching, buttons,
  children)` — folder row + children while open.
- `_file_row(key, label, depth, buttons, warn=None, gap=1)` — file leaf.

### Builders

Per-manager methods return the full row stream with buttons attached:

- `CueAudioTreeManager.tree_rows(*state)` — iterate `visible_tree` (already
  flattened; children of collapsed folders are absent), emit a folder/file row
  per item, buttons from `self.row_buttons(item, *state)` (default `[]`), file
  gap from `self.file_gap` (default 1).
- `CueSfxLibraryTree.row_buttons(item, target_ok, target_tt, unplayable)` — SFX
  configs (play/plus, intensity add-mode swap, warn from `unplayable`).
- `CueCombinedMusicTree.row_buttons(item, current_file)` — music configs
  (plus/play, no folder play, trigger-gated), `file_gap = 2`.
- `content_rows(...)` on each manager — stage 2: concatenates section builders +
  `tree_rows()`. Stage 1 calls `tree_rows()` directly.

Non-owned state is passed in, never read from globals: the screen computes
`target_ok` / `target_tt` / `unplayable` (SFX) and `current_file` (music) and
feeds them to `tree_rows()`. Builders only read `self`-owned state
(`ilevel_add_target`, `_file_index`, `_paths`) and their params, so pytest can
drive them without a wired `_cue` store.

`Function()` objects are built in `.py`; `renpy.curry` provides `Function`.
Actions reference only stable managers / module functions (`_cue.*`), per
CLAUDE.md.

### Evolution rules

- Row kinds are closed (`folder` | `file` | `action` | `help`). New variation
  lands as a data field or a button config, not a new branch in `cue_tree_rows`;
  a new kind is added only when the *label* rendering itself must differ.
- The only branch in the renderer is label rendering. Do not split it into
  per-kind screens — that re-duplicates the shared button/indent/hover markup
  this refactor exists to remove.
- `gap` (1 vs 2) exists only to preserve today's 1:1 layout — parity debt, noted
  by a comment at the call site, and the first candidate to normalize if the
  parity constraint is ever relaxed.
- No mutable default arguments (Python 2): the helpers take `buttons` / `children`
  as required params; optionals default to `None`/immutables.

## Stage 1 — file trees (this pass)

Replace `cue_file_tree` (SFX) and `_cue_music_file_tree` + `cue_music_tree`
(music) with `cue_tree_rows` + `tree_rows()` builders. Sections and pool lists
are untouched.

### Files

- `cue_lib/ui/components.rpy`: add `cue_tree_rows`.
- `cue_lib/audio/audio_tree.py`: add `tree_rows()`, `row_buttons()`, `file_gap`.
- `cue_lib/audio/sfx_manager.py`: `CueSfxLibraryTree` overrides `row_buttons()`,
  `warn_reason()`.
- `cue_lib/audio/music_tree.py`: `CueCombinedMusicTree` overrides `row_buttons()`,
  `file_gap = 2`.
- `cue_lib/ui/views/sfx_library.rpy`: `cue_file_tree` body → `use
  cue_tree_rows(_cue.sfx.library.tree_rows())`.
- `cue_lib/ui/views/music_page.rpy`: `cue_music_tree` → same on
  `_cue.music.library.tree_rows()`; delete `_cue_music_file_tree` (defined and
  used only here, music_page.rpy:270/314).
- `cue_lib/audio/audio_tree.pyi`, `sfx_manager.pyi`, `music_tree.pyi`: stub the
  new methods.

### Parity checklist (must reproduce exactly)

| Detail | SFX tree | Music tree |
|---|---|---|
| File row button order | play, plus | plus, play |
| Folder buttons | play (if `has_files`), plus | plus only (no play) |
| File label gap | `null width 1` (`gap: 1`) | `null width 2` (`gap: 2`) |
| Plus gate (normal) | `target_is_available` | `selected_key or current_file` |
| Plus gate (intensity add-mode) | swap to level-add; dup-check; `selected_alt` bg | n/a |
| File play tooltip | "Preview audio" | "Play song" |
| Folder play tooltip | "Play random file from folder" | n/a |
| Warn icon | triangle-exclamation + "Invalid file: {reason}" | none |
| Row container | rows are direct children of content vbox (spacing 2) | `vbox spacing 2` |
| Row hbox spacing | 2 | 2 |
| Intensity add-mode tooltip | "Add this {folder/file} to Level {lv} of {group}." | n/a |

`cue_tree_rows` is a `vbox spacing 2`, so in the SFX content screen it renders
as one nested child of the content vbox. That is visually identical to direct
children (outer spacing 2 above/below the block, inner spacing 2 between rows) —
do not "flatten" it.

The intensity add-mode swap and warn icon are the only SFX special cases; both
stay in `row_buttons()` / `warn_reason()`.

### Stage-1 tests

- pytest: `tree_rows()` for both managers under normal / searching /
  intensity-add-mode states — assert exact `buttons` icon order, `tt`, `enabled`,
  `bg`, `gap`, `warn`, `depth`. Expected values come from the parity table above
  (not from memory of the screen code), so the test and the code read from the
  same reference.
- harness: SFX Library and Music page render headless on both engine generations.
- Visual parity is a manual check: launch with `RENPY_HEADLESS=0` and eyeball the
  two screens against the current build before committing.

## Stage 2 — collapsible sections

Sections become `_section_rows` + child builders (`_recent_rows`, `_preset_rows`,
`_video_preset_rows`, `_intensity_rows`, music equivalents). `content_rows()`
concatenates them with `tree_rows()`. The `+ Group` / `+ Level` rows become
`action` rows; level-row hover chevrons become `hover_buttons`.

## Stage 3 — pool file lists

`_cue_file_list_vbox` / `_cue_igroup_pool_files_vbox` become `_folder_rows` +
`_file_row` builders (folders detected by trailing `/`, shallow depths). Gated
behind stage 2; skipped if stages 1–2 don't land clean.

## Verification

- `/lint` CLEAN, `/test` pass, `/test-harness` pass before commit.
- `cue_lib` coverage not reduced without a note.
- `.pyi` updated with the new public API.
- Each stage lands as its own commit; stage boundaries are not crossed.
