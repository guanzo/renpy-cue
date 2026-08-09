# Games to mod

E:\Porn\pGames\RaceOfLife-Race-of-Life-Episode-4-hotfix-v4-pc
E:\Porn\pGames\BeingADIK\BeingADIK-S1-S2-0.8.3-pc
E:\Porn\pGames\BeingADIK\BeingADIK-S3-0.11.1-pc-lin
E:\Porn\pGames\Dreamland-v0.6.0p-pc

# Ren'Py Version Compatibility

- RaceOfLife: Ren'Py 8.1.3
- BeingADIK S1-S2: Ren'Py 7.4.x
- BeingADIK S3: Ren'Py 7.4.x
- Dreamland: Ren'Py 8.5+

## Code must work across ALL versions (7.x and 8.x)

### FORBIDDEN (Python 3 only — crashes Ren'Py 7.x):
- No f-strings: use "...{}...".format(...) or "%s" % ...
- No type hints: def foo(x: int) -> str
- No from __future__ import annotations
- No matmul operator (@)

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

## Naming Conventions

Most logic lives in `.py` files under `cue_lib/`, which have their own module-level namespaces. However, `cue_z.rpy` bridges ~55 names into the Ren'Py store for screen actions (`Function()` calls) — and those names share a flat namespace with the game. To avoid collisions:

- **Module-level functions**: `_cue_` prefix — `_cue_play_sfx()`, `_cue_refresh_context()`, `_cue_tick_trigger()`
- **Module-level classes**: `Cue` prefix — `CueBeatManager`, `CueMarkerManager`, `CueVideoManager`
- **Module-level singleton**: `_cue` (the `NoRollback` instance, created in `cue_lib/state.py`)
- **`.py` file imports**: `import foo as _foo` — ensures the import is module-local, not exposed to the store

Function-local variables do NOT need underscores — they're scoped to their function and can't collide.

**Boolean naming**: use a prefix — `is_`, `has_`, `can_`, `did_`, `was_`, `should_`, `will_`. Not bare adjectives: `paused`, `visible`, `initialized`.

## Code Organization

- **Encapsulate features as classes.** When adding a new UI component, dialog, or feature, create a dedicated class that owns its state, logic, and screen hooks. Prefer `_cue.thing = ThingManager()` over scattered `_cue._thing_var1`, `_cue._thing_var2` and global `_cue_do_thing()` functions.
- **One class, one file** in `cue_lib/` when the class is substantial enough to stand alone (e.g. `beat.py` for `CueBeatManager`, `volume.py` for `CueVolumeManager`).
- **Screen code** lives in `cue_lib/ui/*.rpy` (screens + styles). The manager classes in `cue_lib/*.py` handle `renpy.show_screen`/`hide_screen` and provide callable methods for `Function()` screen actions.
- **Bootstrap** lives in `cue_lib/cue_z.rpy` (python early import-path setup + init blocks for bridge + callbacks) and `cue_lib/cue_popper.rpy` (sl-displayable registration). All other `.rpy` files under `src/` have been deleted. See `_typing/cue_lib/` for type stubs.
- **Ren'Py constraint**: `Function()` in screen actions can only reference module-level Python objects (no lambdas/closures), so the class instance must be reachable at a stable path — typically as an attribute of `_cue` (the `NoRollback` singleton).

## Ren'Py Rollback Rules

- `_cue` is a `NoRollback()` instance created at module level in `cue_lib/state.py`. Never reassign `_cue` itself — only mutate its attributes.
- `.py` modules under `cue_lib/` are invisible to rollback (Python module state is not tracked by Ren'Py). The store binding `from cue_lib.state import _cue` in `cue_z.rpy` init -900 is an import — not a `default` or `$` assignment — so no Ren'Py state is created.
- `.rpy` files still use shadowed `dict`/`list`/`set` (Revertable variants). `.py` files use real builtins — `dict`/`list`/`set` work normally there.
- **Prefer duck typing over `isinstance` for collection checks.** `isinstance(x, list)` fails on both plain lists (when `list` is shadowed to `RevertableList`) and RevertableLists (when comparing against the real `list` type). Use `hasattr(x, "__iter__") and not isinstance(x, (str, bytes))` to check for list-like types. Precedent: `_cue_unwrap_persistent` in `cue_lib/util.py`.

## Type Stubs

Pylance can't resolve most `renpy.*` names (Ren'Py uses dynamic `import *` from `renpy.exports`). To get autocomplete and type-checking:

- **`pyrightconfig.json`** — ALL Pylance/Pyright config lives here (`stubPath`, `extraPaths`, `pythonVersion`). Do NOT put `python.analysis.*` settings in `.vscode/settings.json` — they conflict with pyrightconfig.json.
- **`typings/renpy/`** — stubs for the Ren'Py runtime (third-party). Declares submodules plus top-level functions re-exported from `renpy.exports`. Configured via `stubPath` in pyrightconfig.json.
- **`cue_lib/*.pyi`** — stubs for our own modules, living alongside their `.py` counterparts. Pylance finds them automatically via PEP 561.
- **AFTER editing any `cue_lib/*.py`** — check whether the corresponding `cue_lib/*.pyi` needs updating (new/renamed/deleted functions, classes, or method signatures). Keep them in sync.