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