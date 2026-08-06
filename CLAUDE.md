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
- `renpy.music.get_pos()` / `get_duration()` / `is_playing()` / `get_playing()`
- `renpy.music.set_pause()` / `set_volume()`
- `renpy.music.register_channel()` / `channel_defined()`
- `renpy.get_showing_tags()` / `renpy.showing()`
- `renpy.list_files()`
- `config.overlay_screens` — persistent screen injection
- `config.all_character_callbacks` — list of callbacks
- `config.after_load_callbacks` — list of callbacks
- `config.developer` / `config.console`
- `renpy.show_screen()` / `hide_screen()` with `_layer=`
- `renpy.restart_interaction()`
- `renpy.add_layer()`

## Naming Conventions

Ren'Py concatenates all `.rpy` files into a single flat namespace. To avoid collisions with other mods and built-in game code, module-level names MUST be prefixed:

- **Module-level functions**: `_cue_` prefix — `_cue_play_sfx()`, `_cue_refresh_context()`, `_cue_tick_trigger()`
- **Module-level classes**: `Cue` prefix — `CueBeatManager`, `CueMarkerManager`, `CueVideoManager`
- **Module-level singleton**: `_cue` (the `NoRollback` instance)
- **`init python:` block imports**: `import foo as _foo` — keeps the import local to the block

Function-local variables do NOT need underscores — they're scoped to their function and can't collide.

**Boolean naming**: use a prefix — `is_`, `has_`, `can_`, `did_`, `was_`, `should_`, `will_`. Not bare adjectives: `paused`, `visible`, `initialized`.

## Code Organization

- **Encapsulate features as classes.** When adding a new UI component, dialog, or feature, create a dedicated class that owns its state, logic, and screen hooks. Prefer `_cue.thing = ThingManager()` over scattered `_cue._thing_var1`, `_cue._thing_var2` and global `_cue_do_thing()` functions.
- **One class, one file** (in `src/`) when the class is substantial enough to stand alone (e.g. `cue_beat.rpy` for `CueBeatManager`, `cue_volume.rpy` for `CueVolumeManager`).
- **Screen code in `cue_editor_ui.rpy`** reads from the class instance; the class handles `renpy.show_screen`/`hide_screen` and provides callable methods for `Function()` screen actions.
- **Ren'Py constraint**: `Function()` in screen actions can only reference module-level Python objects (no lambdas/closures), so the class instance must be reachable at a stable path — typically as an attribute of `_cue` (the `NoRollback` singleton).

## Ren'Py Rollback Rules

- `_cue` is a `NoRollback()` instance. Never reassign `_cue` itself — only mutate its attributes.
- Anything reachable ONLY through `_cue` is excluded from rollback, regardless of its type (plain or Revertable). It only becomes rollback-tracked if it's ALSO reachable from another path (e.g. aliased from `persistent.x`) — so never alias `persistent.*` into `_cue.*`, always deep-copy via `_cue_unwrap_persistent`.
- Inside `.rpy` files, `dict`, `list`, `set` (including `{}`/`[]` literals) are shadowed to return `RevertableDict`/`RevertableList`/`RevertableSet`, even when called as `dict(...)`/`list(...)`/`set(...)`.
- To get real plain Python types in `.rpy` code, use `python_dict(...)` / `python_list(...)` / `python_set(...)` (aliases to the true builtins, defined in `cue_editor.rpy`). Never use bare `dict`/`list`/`set`/`{}`/`[]` when a plain type is required.
- **Prefer duck typing over `isinstance` for collection checks.** `isinstance(x, list)` fails on both plain lists (when `list` is shadowed to `RevertableList`) and RevertableLists (when comparing against the real `list` type). Use `hasattr(x, "__iter__") and not isinstance(x, (str, bytes))` to check for list-like types. Precedent: `_cue_unwrap_persistent` in `src/cue_util.rpy`.
- `.py` files imported into the game don't have this shadowing issue — `dict`/`list`/`set` work normally there.