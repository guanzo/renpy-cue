---
name: lint
description: Run pyright and report all diagnostics
---

# /lint

Run pyright on `cue_lib/`, `ruff format --check` on `cue_lib/` and `tests/`,
the 120-char line-length check on `cue_lib/` and `tests/`, the py2
trailing-comma guard on `cue_lib/`, and the Python 2.7 compatibility gate
(`bin/py2_check.sh`), and report ALL findings. Every pyright diagnostic must
either be fixed or suppressed with a `# pyright: ignore[rule]` comment.

The py2 gate is why `bin/lint.sh` needs the 7.4.10 SDK in `.local/`: pytest runs
under py3, so py3.6+ stdlib APIs (e.g. `zipfile.ZipInfo.is_dir`) and py2-invalid
syntax slip through the test suite. `bin/py2_check.sh` py2-compiles every
`cue_lib/**/*.py` (except `_types.py`), boots `import cue_lib` under the bundled
interpreter, and runs targeted runtime smokes. It is skipped loudly when the SDK
is absent (the CI `check` job) and enforced on the 7.4.10 harness leg in CI.

`tests/` is deliberately excluded from the pyright pass: the test suite is
white-box (pokes private seams, injects fakes, patches module aliases), so
strict type-checking against the `.pyi` public contract produces ~150 false
positives. The 120-char check still covers `tests/`.

## Command

```bash
bin/lint.sh
```

The checks live in `bin/lint.sh` -- the single source of truth shared with
CI, so the two callers can't drift apart. It runs pyright, `ruff format
--check`, the 120-char line-length check, and the py2 trailing-comma guard,
printing every finding.

**/lint is CLEAN only when `bin/lint.sh` exits 0 and prints `CLEAN`.** It
exits 1 and prints each `file:line: message` otherwise. (The raw pyright/awk
commands always exit 0 -- that's exactly why the script aggregates and
exits nonzero, and why both CI and this skill call the script rather than
inlining the commands.)

How the script maps to the four checks:

1. **pyright**: `pyright cue_lib/ --outputjson 2>/dev/null` (tests/ excluded
   by design), with the JSON parsed as `file:line: message`. Prints `CLEAN`
   when there are zero diagnostics. Missing `pyright` on PATH is a hard
   failure (exit 1), not a silent pass.
2. **ruff format**: `ruff format --check cue_lib tests` (config in
   `pyproject.toml`). Ruff is the deterministic enforcer of the 120-char and
   one-argument-per-line rules for `.py`/`.pyi`; `.rpy` is not parseable by
   ruff, so those wraps stay manual. Missing `ruff` on PATH is a hard
   failure, not a silent pass.
3. **line length (120 chars)**: `find cue_lib tests \( -name '*.py' -o
   -name '*.rpy' -o -name '*.pyi' \)` piped through awk, reporting lines over
   120 chars. `# type:` comment lines are exempt -- a comment cannot be
   wrapped. Lines carrying a `# pyright: ignore` comment are also exempt --
   see rule 5 below.
4. **py2 trailing-comma guard**: grep on `cue_lib/*.py` for a bare
   `*args,`/`**kwargs,` line. Ruff adds a trailing comma to width-split defs
   ending in `*args`/`**kwargs` -- py3-only, a SyntaxError under Ren'Py 7.x.
   Those defs are wrapped in `# fmt: off` / `# fmt: on` (see rule 8). This
   backstop catches new breakers before the legacy harness (~15 min) does.

## Reformatting lines over 120 chars

For `.py`/`.pyi`, run `ruff format cue_lib tests` first -- ruff is the
deterministic enforcer of the 120-char and one-argument-per-line rules
(config in `pyproject.toml`), so hand-wrapping those files just fights it.
The manual rules below apply to `.rpy` (ruff can't parse Ren'Py) and to the
`.py`/`.pyi` cases ruff can't fix: long string literals (rule 4), pyright
suppression priority (rule 5), py2-sensitive defs (rule 8), and the
blank-line review.

For files and cases ruff doesn't cover, apply in priority order; the goal is
the smallest change that fits and reads like the file around it.

1. **Shorten before wrapping**, only when genuinely equivalent -- a verbose
   `tt=` tooltip is often the real problem. Never silently rewrite
   user-facing copy; if the text must stay, wrap instead.
2. **Wrap at the outermost commas**: one argument per line, +4 hanging
   indent, `)` on the last argument's line. Do not group multiple outer
   arguments onto one continuation line -- every wrapped argument gets its
   own line. Each nested `Function(...)` / manager call stays on one line --
   break inside a nested call only if that call alone exceeds 120. No
   trailing whitespace.
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
6. **`.pyi` signatures**: ruff formats `.pyi` (one param per line when long,
   `->` on the last parameter's line). Use this rule only when hand-adjusting
   a signature ruff won't fix.
7. **Minimal diff**: touch the offending line only (plus the hoist line if
   needed). Never reflow neighboring lines that are already under 120.
8. **Py2-sensitive defs**: a def that splits across lines AND ends in
   `*args`/`**kwargs` gets a py3-only trailing comma from ruff. Wrap the def
   header in `# fmt: off` / `# fmt: on` and hand-write it WITHOUT the comma:
   ```python
       # ruff's width-split adds a py3-only trailing comma after **kwargs
       # (SyntaxError under Ren'Py 7.x / Python 2.7). Hand-written.
       # fmt: off
       def __init__(self, target, ..., **kwargs
       ):
       # fmt: on
   ```
   The directives must be EXACTLY `# fmt: off` / `# fmt: on` on their own
   lines -- any trailing text makes ruff ignore them. Precedent: popper.py
   `CuePopper.__init__`. Verify with the SDK's py2 interpreter
   (`PYTHONHOME=$PWD/.local/renpy-7.4.10-sdk/lib
   .local/renpy-7.4.10-sdk/lib/linux-x86_64/python -c "import py_compile;
   py_compile.compile('cue_lib/...', doraise=True)"`).

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

Note: `tests/` produces many `reportAttributeAccessIssue` / `reportArgumentType`
diagnostics because the suite is white-box (pokes private seams, injects fakes)
-- that is why tests/ is excluded from the pyright pass (see top).
