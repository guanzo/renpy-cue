# Ren'Py Version Compatibility

Code must work for 7.4.x and up.

## Code must work across ALL versions (7.x and 8.x)

### FORBIDDEN (Python 3 only — crashes Ren'Py 7.x):
- No f-strings: use "...{}...".format(...) or "%s" % ...
- No type hints: def foo(x: int) -> str
- No from __future__ import annotations
- No matmul operator (@)
- No non-ASCII characters in `.py` files: Ren'Py 7.x uses Python 2 which
  defaults to ASCII encoding. Use `--` instead of em dashes (`—`), straight
  quotes instead of curly quotes, etc.
- All classes MUST inherit from `object` (or another new-style class):
  `class Foo(object):` not `class Foo:`.  Python 2 old-style classes
  don't support `super()`, descriptors, or `__class__` assignment.

### FORBIDDEN (not in all versions):
- Character callback kwargs `what`/`start`/`end` — only in Ren'Py 8.2+
  Use `store._last_say_what` instead
- `renpy.get_displayable()` with `screen=`/`id=` kwargs — API varies
- `<from N>` syntax on movie channels — ignored, always restarts from 0

### FORBIDDEN (screen language):
- Python inline `x if cond else y` in screen property values ONLY works
  when the entire expression is wrapped in parentheses:
  `property ("#446644" if cond else "#444444")`.
  Without parens the parser reads `if` as a screen-language block.
- The same applies to `==` (and likely other comparison operators) in
  screen statement arguments — Ren'Py 7.4's parser misinterprets the
  expression as a keyword argument. Wrap in parens:
  `use foo_btn(label, (_x == some_val), action)`
- `VariableInputValue()` does NOT support dotted attribute paths like
  `"_cue.foo.bar"` — it calls `globals()[self.variable]` which only
  resolves flat names. Use `_CueFieldValue("_cue.foo.bar")` instead
  (defined in `cue_ui_components.rpy`).  Under the hood it splits on
  the last `.` and uses `FieldInputValue`.

### SAFE across all versions:
- `store._last_say_what` — current dialogue text
- `store._last_say_who` — current speaker
- `renpy.audio.music.get_pos()` / `get_duration()` / `is_playing()` / `get_playing()`
- `renpy.audio.music.set_pause()` / `set_volume()`
- `renpy.audio.music.register_channel()` / `channel_defined()`
- `renpy.get_showing_tags()` / `renpy.showing()`
- `renpy.list_files()`
- `config.overlay_screens` — persistent screen injection
- `config.all_character_callbacks` — list of callbacks
- `config.after_load_callbacks` — list of callbacks
- `config.developer` / `config.console`
- `renpy.show_screen()` / `hide_screen()` with `_layer=`
- `renpy.restart_interaction()`
- `renpy.add_layer()`

**NOTE**: In `.py` files, use the real module path `renpy.audio.music` (not `renpy.music`). `renpy.music` is a `sys.modules` alias set up at runtime by `import_all()` — it doesn't exist as a file on disk and won't resolve during `init -999` before the alias is created.

## Platform Gotchas

- **`os.rename` does NOT overwrite on Windows.** POSIX renames atomically
  over an existing destination; on Windows it raises `[Error 183] Cannot
  create a file when that file already exists`. If the destination may
  already exist (a zip you rewrite in place, a file you move into place),
  remove the stale destination first on `os.name == "nt"` before renaming —
  see `_cue_replace_file()` in `cue_lib/util.py`. This has bitten us multiple
  times; always reach for `_cue_replace_file()` rather than bare `os.rename`
  for overwrite semantics. Callers that rewrite a file in place should write
  a temp file first, then `_cue_replace_file(tmp, final)`.

## Naming Conventions

Most logic lives in `.py` files under `cue_lib/`, which have their own module-level namespaces. However, `cue_z.rpy` bridges ~55 names into the Ren'Py store for screen actions (`Function()` calls) — and those names share a flat namespace with the game. To avoid collisions:

- **Module-level functions**: `_cue_` prefix — `_cue_play_sfx()`, `_cue_refresh_context()`, `_cue_tick_trigger()`
- **Module-level classes**: `Cue` prefix — `CueMarkerRepeater`, `CueMarkerManager`, `CueVideoManager`
- **Module-level singleton**: `_cue` (the `NoRollback` instance, created in `cue_lib/state.py`)
- **`.py` file imports**: `import foo as _foo` — ensures the import is module-local, not exposed to the store

Function-local variables do NOT need underscores — they're scoped to their function and can't collide.

**Boolean naming**: use a prefix — `is_`, `has_`, `can_`, `did_`, `was_`, `should_`, `will_`. Not bare adjectives: `paused`, `visible`, `initialized`.

## Constants vs Magic Numbers

**Prefer named constants** over raw numbers/strings when a change would break
things if the copies got out of sync. The litmus test: *"if someone changed one
copy and forgot the other, would behavior silently break?"*

### Must be constants (cross-file or cross-language sync)

| Pattern | Where | Example |
|---|---|---|
| Value used in multiple `.py` files | `constants.py` with `CUE_` prefix | `CUE_SFX_CHANNEL_COUNT`, `CUE_DEFAULT_VIDEO_SPEED` |
| Value used in `.py` AND `.rpy` | `constants.py`, imported into store via `cue_z.rpy` init -999 | `CUE_MULTI_SPEED_MIN_VARIANTS` |
| Value duplicated in same file | Module-level in that file, `CUE_` prefix | `CUE_SEEK_EPSILON` in `video.py` |
| Value mirrored between `.py` and `.rpy` | Single source in `.py`, `.rpy` reads it | `_cue.volume.VOL_MAX` instead of `range=5.0` |
| Number string mapped to behavior | Enum class | `CueLoopFrequency.SLOWEST`, `CueSpeedMode.SINGLE` |

### python early limitation

`cue_z.rpy` `python early` blocks run before `renpy.store` exists. Importing
from `cue_lib` there cascades into `file_tree.py` which needs `persistent`.
**Raw values in `python early` are acceptable** — there's no way around it.

### Don't bother (trivial / self-documenting / inherently local)

- **Retry counts** (`for _attempt in range(3)`) — obvious in context
- **Sleep delays** (`time.sleep(0.1)`) — local procedural logic
- **Artistic tuning** (generator probabilities, ffmpeg CRF values) — algorithm-defining, not config
- **Screen layout** (xpos, ypos, spacing, xsize) — Ren'Py can't reference Python constants in screen property position
- **Single-use sentinels** (`-9999`, `-1.0`) — self-documenting as "unset"

### constants.py

New cross-file constants go in `cue_lib/constants.py`. Every constant has a
`CUE_` prefix. Keep `cue_lib/constants.pyi` in sync — add every constant there
with `Final` annotation.

### Enum classes

When a discrete set of values maps to behavior branches, use a flat enum class
(inherit from `object`, no base enum — Python 2.7 compatibility):

```python
class CueLoopFrequency(object):
    SLOWEST = 4   # ~6.3s
    SLOW = 0      # ~3.8s
    NORMAL = 1    # ~2.1s
    FAST = 2      # ~0.6s
    FASTEST = 3   # ~0.2s
```

Import into store via `cue_z.rpy` init -999 so `.rpy` screens can use them.

## Code Organization

- **Encapsulate features as classes.** When adding a new UI component, dialog, or feature, create a dedicated class that owns its state, logic, and screen hooks. Prefer `_cue.thing = ThingManager()` over scattered `_cue._thing_var1`, `_cue._thing_var2` and global `_cue_do_thing()` functions.
- **One class, one file** in `cue_lib/` when the class is substantial enough to stand alone (e.g. `repeater.py` for `CueMarkerRepeater`, `volume.py` for `CueVolumeManager`).
- **Screen code** lives in `cue_lib/ui/*.rpy` (screens + styles). The manager classes in `cue_lib/*.py` handle `renpy.show_screen`/`hide_screen` and provide callable methods for `Function()` screen actions.
- **Bootstrap** lives in `cue_lib/cue_z.rpy` (python early import-path setup + sl-displayable registration + init blocks for bridge + callbacks). All other `.rpy` files under `src/` have been deleted. See `cue_lib/*.pyi` for type stubs.
- **Ren'Py constraint**: `Function()` in screen actions can only reference module-level Python objects (no lambdas/closures), so the class instance must be reachable at a stable path — typically as an attribute of `_cue` (the `NoRollback` singleton).

## Whitespace / Blank Lines

Logical sections are surrounded by blank lines. A block-opening statement
(`if`/`for`/`while`/`with`) that starts a new logical section gets a blank
line before it; a blank line follows a closed block before the next
section-level statement. Never leave a long function as one unbroken run of
statements.

Do NOT insert blanks between a guard and its early return (`if not x:` /
`return` chains stay tight), between `if`/`elif`/`else`, or inside
dict/list literals.

## Ren'Py Rollback Rules

- `_cue` is a `NoRollback()` instance created at module level in `cue_lib/state.py`. Never reassign `_cue` itself — only mutate its attributes.
- `.py` modules under `cue_lib/` are invisible to rollback (Python module state is not tracked by Ren'Py). The store binding `from cue_lib.state import _cue` in `cue_z.rpy` init -900 is an import — not a `default` or `$` assignment — so no Ren'Py state is created.
- `.rpy` files still use shadowed `dict`/`list`/`set` (Revertable variants). `.py` files use real builtins — `dict`/`list`/`set` work normally there.
- **Prefer duck typing over `isinstance` for collection checks.** `isinstance(x, list)` fails on both plain lists (when `list` is shadowed to `RevertableList`) and RevertableLists (when comparing against the real `list` type). Use `hasattr(x, "__iter__") and not isinstance(x, (str, bytes))` to check for list-like types. Precedent: `_cue_unwrap_persistent` in `cue_lib/util.py`.

## Persistent vs Shared Config

Two places to store state that survives restarts:

- **`persistent`** -- per-game. Each game the mod is installed to has its own.
  This is the default choice. Low-stakes convenience flags that don't need to
  carry across games live here, e.g. `triggers_active`, `encode_mode`.
- **Shared config** -- one JSON file shared across ALL games the mod is
  installed to. Use only when a setting should carry across games, e.g.
  custom keybinds. Access via `_cue.db.load_shared_config()` /
  `_cue.db.update_shared_config()`.

## Type Stubs

Pylance can't resolve most `renpy.*` names (Ren'Py uses dynamic `import *` from `renpy.exports`). To get autocomplete and type-checking:

- **`pyrightconfig.json`** — ALL Pylance/Pyright config lives here (`stubPath`, `extraPaths`, `pythonVersion`). Do NOT put `python.analysis.*` settings in `.vscode/settings.json` — they conflict with pyrightconfig.json.
- **`typings/renpy/`** — stubs for the Ren'Py runtime (third-party). Declares submodules plus top-level functions re-exported from `renpy.exports`. Configured via `stubPath` in pyrightconfig.json.
- **`cue_lib/*.pyi`** — stubs for our own modules, living alongside their `.py` counterparts. Pylance finds them automatically via PEP 561.
- **`cue_lib/_types.py`** — CANONICAL source for all TypedDict definitions (PoolDict, MarkerEntry, etc.). This is a real `.py` module that `.pyi` stubs import from. It is NEVER executed at runtime (only imported inside `if MYPY:` guards and by `.pyi` files), so it freely uses modern syntax (TypedDict, `from __future__ import annotations`). ONE definition per TypedDict — no duplication across `.pyi` files.
- **AFTER editing any `cue_lib/*.py`** — check whether the corresponding `cue_lib/*.pyi` needs updating (new/renamed/deleted functions, classes, or method signatures). Keep them in sync.
- **AFTER any changes to `cue_lib/` or `tests/`** — run `/lint` then `/test`. `/lint` must return `CLEAN` (see `.claude/skills/lint/SKILL.md` for the unfixable-error table); `/test` must pass (all tests green).
- **AFTER adding a new manager to `bootstrap()` in `state.py`** — you MUST add it to `state.pyi` (both the import and the attribute on `class Cue`). Otherwise `_cue.new_manager` shows "unknown attribute" in every consumer.
- **AFTER adding/changing a TypedDict** — update `cue_lib/_types.py` (the single source of truth). All `.pyi` files import from there.

### Self-File Hover (type info when viewing a function's own source file)

Pyright does NOT consult a module's `.pyi` stub when analyzing the module's own `.py` source. A `.pyi` describes the public contract for CONSUMERS; the module analyzing itself only sees its own source. Since our `.py` files have zero inline type annotations (Python 2.7/Ren'Py 7.x constraint — no `def foo(x: int)` syntax), self-file hover shows `Unknown` without extra help.

The fix: **PEP 484 function-signature type comments** (`# type:`) backed by a **MYPY guard** that makes TypedDict names visible to the type checker without triggering a runtime import.

#### Pattern

In each `.py` file that needs self-file hover, add after the last real import:

```python
MYPY = False
if MYPY:
    from typing import Optional  # only if needed
    from cue_lib._types import PoolDict, MarkerEntry  # whatever TypedDicts are referenced
```

Then add `# type:` comments to method signatures:

```python
def resolve_pool(self, pool):
    # type: (PoolDict) -> ResolvedPool
    ...
```

#### How it works

- `MYPY = False` makes this a dead block at runtime — Python 2.7 never enters it, so it never tries to import `_types.py` (which uses Python 3 syntax).
- Type checkers (Pyright, mypy) **special-case** `if MYPY:` / `if TYPE_CHECKING:` blocks — they are statically analyzed as if always taken, making the imported names available for `# type:` comment resolution.
- This is the standard, checker-endorsed idiom — NOT a workaround.

#### What needs a `# type:` comment

- Any function whose `.pyi` stub declares types involving TypedDicts (PoolDict, MarkerEntry, VideoPoolDict, RepeaterOffset, UndoSnapshot, etc.)
- Functions using only built-in types (str, int, float, bool, list) DON'T need a MYPY guard — `# type:` comments with builtins work without imports
- Internal helpers (`_foo`) can be annotated but it's lower priority — focus on public API methods first

#### The `_types.py` module

- NEVER imported at runtime — only by `.pyi` files and inside `if MYPY:` guards
- Uses `from __future__ import annotations` and `typing.TypedDict` — no Python 2.7 constraint
- One canonical definition per TypedDict — `.pyi` stubs import from here, never redeclare
- Located at `cue_lib/_types.py` (a real `.py` module) so Pyright can resolve it as an import target

