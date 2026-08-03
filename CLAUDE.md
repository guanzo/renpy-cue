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

## Ren'Py Rollback Rules

- `_cue` is a `NoRollback()` instance. Never reassign `_cue` itself — only mutate its attributes.
- Anything reachable ONLY through `_cue` is excluded from rollback, regardless of its type (plain or Revertable). It only becomes rollback-tracked if it's ALSO reachable from another path (e.g. aliased from `persistent.x`) — so never alias `persistent.*` into `_cue.*`, always deep-copy via `_cue_editor_unwrap_persistent`.
- Inside `.rpy` files, `dict`, `list`, `set` (including `{}`/`[]` literals) are shadowed to return `RevertableDict`/`RevertableList`/`RevertableSet`, even when called as `dict(...)`/`list(...)`/`set(...)`.
- To get real plain Python types in `.rpy` code, use `python_dict(...)` / `python_list(...)` / `python_set(...)` (aliases to the true builtins, defined in `sfx_editor.rpy`). Never use bare `dict`/`list`/`set`/`{}`/`[]` when a plain type is required.
- `.py` files imported into the game don't have this shadowing issue — `dict`/`list`/`set` work normally there.