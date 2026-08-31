---
name: icon
description: Add a Font Awesome icon to the mod (copy PNG, register in CUE_ICON_MAP)
argument-hint: <icon-name> [style]
---

# /icon

Adds Font Awesome Free icons to `cue_icon_btn`'s registry. Invoked as
`/icon <names> [style]`, e.g. `/icon clone regular`, `/icon heart`, or
`/icon chevron right,down,up,left` (names separated by commas; the
style applies to all of them). Style defaults to `solid`; valid styles:
solid, regular, brands.

## Steps

1. **Parse args**: `$ARGUMENTS` is a comma-separated list. Each item is
   `NAME` or `NAME STYLE` (style defaults to `solid`, and a bare trailing
   style applies to every item). When a space-separated item is ambiguous,
   prefer the parse where the name exists in the stash — e.g.
   `/icon chevron right,down,up,left` is four chevron-* names, while
   `/icon copy regular, paste regular` is two names each with an explicit
   style. Apply all following steps per item.
2. **Check the stash**: the icon must already be rasterized at
   `.local/icons/<STYLE>/<NAME>.png` (all FA free icons are there, white
   32px PNGs).
   - Missing there but present in another style: report the available
     style(s) and ask before continuing (`ls .local/icons/*/<NAME>*.png`).
   - Not in the stash at all: the name is not a FA free icon (or a typo).
     Search similar names (`ls .local/icons/solid | grep NAME`), show the
     closest matches, and stop.
   - No stash at all: run `bash .local/icons/convert.sh` first (needs
     rsvg-convert).
3. **Ship the PNG**: `cp .local/icons/<STYLE>/<NAME>.png
   cue_lib/assets/images/icons/<NAME>-<STYLE>.png`. Always name it
   `<name>-<style>.png`, never a bare `<name>.png`.
4. **Register it**: in `cue_lib/icons.py`, add one entry to `CUE_ICON_MAP`
   keeping the keys sorted:
   `"NAME": ("NAME-STYLE.png", False),`
   - If the name already exists as a key: report the current entry and
     stop (do not duplicate).
   - Mirrored icons (like "redo") are a manual follow-up: change False to
     True in the map entry.
5. **Sync the pipeline**: add a `copy_icon NAME` line (plus the style arg
   only if not solid, e.g. `copy_icon NAME regular`) to the ship list in
   `.local/icons/convert.sh` so a future regeneration reproduces the icon.
6. **Lint**: invoke the `/lint` skill. Must be CLEAN.
7. **Report**: the PNG path, the map line added, and the usage snippet:
   `use cue_icon_btn("NAME", ...)`.

## Context

- `cue_icon_btn` takes a label that is either an icon name (rendered as a
  PNG via `_cue.icons.displayable_for`) or plain text (rendered as text).
  Unknown names render as literal text, so a forgotten map line is visible
  in the UI immediately.
- Full manual recipe lives in the docstring of `cue_lib/icons.py`.
- `cue_lib/assets/images/icons/` is committed (ships with the mod);
  `.local/icons/` and `convert.sh` are gitignored local tooling.
