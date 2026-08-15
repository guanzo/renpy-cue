---
name: lint
description: Run pyright and report all diagnostics
---

# /lint

Run pyright and the 120-char line-length check on `cue_lib/` and `tests/` and
report ALL diagnostics. Every diagnostic must either be fixed or suppressed
with a `# pyright: ignore[rule]` comment.

## Command 1: pyright

```bash
pyright cue_lib/ tests/ --outputjson 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
count=0
for diag in d.get('generalDiagnostics',[]):
    count+=1
    print('{}:{}: {}'.format(diag.get('file','?'),diag.get('range',{}).get('start',{}).get('line','?'),diag.get('message','')))
for f in d.get('diagnostics',[]):
    for diag in f.get('diagnostics',[]):
        count+=1
        print('{}:{}: {}'.format(f.get('file','?'),diag.get('range',{}).get('start',{}).get('line','?'),diag.get('message','')))
if count==0:
    print('CLEAN')
"
```

## Command 2: line length (120 chars)

```bash
find cue_lib tests \( -name '*.py' -o -name '*.rpy' -o -name '*.pyi' \) -print0 \
  | xargs -0 awk 'length($0) > 120 && $0 !~ /^[[:space:]]*# type:/ \
      && $0 !~ /# pyright: ignore/ \
      {printf "%s:%d: %d chars\n", FILENAME, FNR, length($0)}'
```

No output means no violations. `# type:` comment lines are exempt -- a
comment cannot be wrapped. Lines carrying a `# pyright: ignore` comment are
also exempt -- see rule 5 below.

**/lint is CLEAN only when Command 1 prints `CLEAN` and Command 2 prints
nothing.**

## Reformatting lines over 120 chars

Apply in priority order; the goal is the smallest change that fits and reads
like the file around it.

1. **Shorten before wrapping**, only when genuinely equivalent -- a verbose
   `tt=` tooltip is often the real problem. Never silently rewrite
   user-facing copy; if the text must stay, wrap instead.
2. **Wrap at the outermost commas**: one argument per line, +4 hanging
   indent, `)` on the last argument's line. Each nested `Function(...)` /
   manager call stays on one line -- break inside a nested call only if that
   call alone exceeds 120. Break at the highest-level comma that fits, not
   every comma. No trailing whitespace.
   ```renpy
   use cue_select_btn(
       "Wait for other SFX to finish",
       (_start == CueExclusiveStart.WAIT),
       Function(ctx.set_exclusive_start, CueExclusiveStart.WAIT),
       tt="Waits until no SFX outside this group is playing, then plays")
   ```
3. **Hoist a long or repeated sub-expression into a `$` local** when that is
   the smaller change (precedent: `cue_lib/ui/components.rpy:358-361`).
4. **Long string literals**: adjacent-literal concatenation inside parens,
   broken at phrase boundaries:
   ```python
   return ("error", "ffmpeg not found. Install ffmpeg and restart the game, "
           "or set RENPY_CUE_FFMPEG environment variable.")
   ```
5. **`# pyright: ignore[...]` comments** must stay on the line the diagnostic
   is on -- break the code before the comment, keep the comment as the tail.
   If the line still exceeds 120 that way, leave it long: **pyright
   suppression takes priority over the 120 limit.** Splitting the line can
   move the diagnostic to generalDiagnostics where the comment stops working
   (precedent: `trigger.py` `_cue_play_pool` call).
6. **`.pyi` signatures**: parameters on continuation lines in logical groups
   (one per line when long), 4-space hanging indent, `->` return on the last
   parameter's line.
7. **Minimal diff**: touch the offending line only (plus the hoist line if
   needed). Never reflow neighboring lines that are already under 120.

## Review step: blank lines

Not a mechanical check -- judged by eye on the diff. Logical sections are
surrounded by blank lines: blank BEFORE a block-opening `if`/`for`/`while`/
`with` that starts a new section, blank AFTER a closed block before the next
section-level statement. No long function as one unbroken run of statements.

Do NOT insert blanks between a guard and its early return (`if not x:` /
`return` chains stay tight), between `if`/`elif`/`else`, or inside
dict/list literals.

## Genuinely unfixable diagnostics

These can't be fixed due to Ren'Py / Python 2 constraints. Suppress with
`# pyright: ignore[rule]` (inline, per-line, or per-file).

**Caveat**: "not accessed" diagnostics may be false positives when the
symbol is consumed by `.rpy` files (Ren'Py screen actions, `$` init blocks,
`Function()` calls). Pyright only analyzes `.py` and `.pyi` — it can't see
usages in `.rpy`. Before suppressing, verify the symbol isn't actually
referenced by `.rpy` with a project-wide grep (`grep -r name cue_lib/`).

| Rule | Why unfixable | Where |
|---|---|---|
| `reportUndefinedVariable` on `unicode` | Python 2 built-in checked via `try: unicode / except NameError` | `db.py`, `util.py` |
| `reportAttributeAccessIssue` on `.child` / `._target` / `.target` | Ren'Py displayables are C/Cython objects; attributes guarded by `hasattr()` | `util.py:_cue_unwrap_displayable` |
| `reportAttributeAccessIssue` on `default_play_callback` | `renpy.display.video` is dynamically assembled | `speed.py` |
| `reportUnusedImport` / `reportUnusedFunction` / etc. — consumed by `.rpy` only | Pyright can't see usages in Ren'Py screen code / `$` init blocks / `Function()` calls. Verify with `grep` before suppressing. | Any `.py` symbol referenced by `cue_z.rpy` or UI screens |
| `reportUnusedImport` on MYPY-guarded imports | Only referenced in `# type:` comments; removing breaks self-file hover | Various `.py` files, `if MYPY:` blocks |
| `reportUnusedImport` on `__init__.py` side-effect imports | Required for Ren'Py `import_all()` module discovery | `__init__.py` |
| `reportUnusedImport` on `.pyi` re-exports | Stub imports exist so consumers can import from the module | `state.pyi`, `ui_logic.pyi`, etc. |
| `reportArgumentType` / `reportGeneralTypeIssues` on `PoolDict` | `PoolDict(total=False)` is a catch-all; video pools have `time` but flow through PoolDict APIs; TypedDict literals can't narrow via `# type:` comments | `repeater.py`, `trigger.py` |
| `reportAttributeAccessIssue` / `reportArgumentType` in `tests/` | White-box tests deliberately poke private or duck-typed seams (`_mgr`, `_key`, `FakeManager`, private methods) against the `.pyi` production contract. Suppress inline -- this is expected, not a production-style failure | `tests/test_markers_context.py`, `tests/fakes.py` |
