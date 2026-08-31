---
name: icon-pro
description: Add a Font Awesome Pro icon to the mod (extract webfont glyph, register in CUE_ICON_MAP)
argument-hint: <icon-name> [style]
---

# /icon-pro

Adds Font Awesome **Pro** icons to `cue_icon_btn`'s registry. Invoked as
`/icon-pro <names> [style]`, e.g. `/icon-pro sidebar-flip regular`, or
`/icon-pro border-light` (names separated by commas; the style applies to all
of them). Style defaults to `solid`; valid styles: solid, regular, light,
thin, brands.

Unlike the free `/icon`, the Pro package ships only css + webfonts (no
per-icon SVGs), so an icon's vector is a glyph in a style's woff2 keyed by a
unicode codepoint. The shape is rebuilt from the woff2 by
`.local/icons/pro_icon.py`. Output mirrors `/icon`: a white 32x32 PNG in
`cue_lib/assets/images/icons/` plus a `CUE_ICON_MAP` entry.

## Steps

1. **Parse args**: `$ARGUMENTS` is a comma-separated list. Each item is
   `NAME` or `NAME STYLE` (style defaults to `solid`). Apply all following
   steps per item.
2. **Ensure the Pro source**: the mirror must be at
   `.local/fontawesome-pro/` and the style font at
   `.local/fontawesome-pro/releases/v7.3.0/webfonts/fa-<style>-<weight>.woff2`.
   If the mirror is missing, clone it once (~44MB, gitignored):
   `git clone --depth 1 https://github.com/rizmyabdulla/fontawesome-pro .local/fontawesome-pro`.
3. **Extract the glyph**: from the repo root run
   `python3 .local/icons/pro_icon.py NAME STYLE`. It reads the codepoint from
   the css, pulls the glyph out of the woff2 (fonttools + brotli), wraps it in
   a y-flipped white SVG, and rasters it with `rsvg-convert` (letterboxed,
   never distorted). It prints `codepoint U+XXXX <png>` and exits non-zero on
   failure.
   - Missing `fonttools`/`brotli`: `python3 -m pip install fonttools brotli`.
   - Name not in the css: not a Pro icon (or a typo). Grep the codepoints
     (`grep ".fa-NAME" .local/fontawesome-pro/releases/v7.3.0/css/fontawesome.css`),
     show the closest matches, and stop.
   - Glyph missing from that style's font: report the available styles and
     stop -- do not silently fall back to another style.
4. **Ship the PNG**: the extractor writes
   `cue_lib/assets/images/icons/<NAME>-<STYLE>.png`. Always `<name>-<style>.png`,
   never a bare `<name>.png`.
5. **Register it**: in `cue_lib/ui/icons.py` (not `cue_lib/icons.py` -- the
   file lives under `ui/`), add one entry to `CUE_ICON_MAP` keeping the keys
   sorted:
   `"NAME": ("NAME-STYLE.png", False),`
   - If the name already exists as a key: report the current entry and stop
     (do not duplicate).
6. **Sync the pipeline**: add a `copy_icon_pro NAME STYLE` line (style
   included, since the Pro pipeline has no stash) to
   `.local/icons/convert.sh` so a regeneration reproduces the icon.
7. **Lint**: invoke the `/lint` skill. Must be CLEAN.
8. **Report**: the codepoint, the PNG path, the map line added, and the usage
   snippet: `use cue_icon_btn("NAME", ...)`.

## Context

- `cue_icon_btn` takes a label that is either an icon name (rendered as a PNG
  via `_cue.icons.displayable_for`) or plain text (rendered as text). Unknown
  names render as literal text, so a forgotten map line shows in the UI
  immediately.
- Pro glyphs are not square: a wide/tall glyph rasters to e.g. 32x24 or
  28x32, letterboxed within the 32x32 box. That's the same convention as the
  free PNGs (`copy-regular.png` is 28x32), so no special handling is needed.
- `.local/` (fontawesome-pro mirror, pro_icon.py, convert.sh) is gitignored
  local tooling; only the committed PNG + map entry ship with the mod.
