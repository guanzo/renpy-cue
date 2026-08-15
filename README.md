# Ren'Py Cue

Ren'Py Cue is a mod for [Ren'Py](https://www.renpy.org/) visual novels that layers custom sound and video effects on top of an existing game — an advanced marker/trigger/video/SFX cue system that needs **no game-script edits**.

From an in-game overlay you can:

- attach sound effects to the current image, dialogue line, video timestamp, loop cycle, or screen shake;
- replace or suppress music during replays;
- create and switch between ffmpeg-rendered video speed variants.

The mod watches the current scene — which images are shown, which line is being said, whether a movie is playing — and fires your configured SFX automatically when a trigger matches. Everything you configure is stored as plain JSON in a shared data directory, so your setup survives restarts and follows you across every game Cue is installed into.

## Features

- **SFX on context** — attach one or more audio pools to:
  - the current **image** (`i_` triggers)
  - a **dialogue line** (`d_` triggers, keyed by speaker + text)
  - a **video timestamp** (`v_` triggers, placed on a draggable timeline)
  - a **loop cycle** (`l_` triggers at 5 selectable intervals, ~0.2s to ~6.3s)
  - **screen shakes** (`vpunch` / `hpunch`)
- **Overlapping multi-pool playback** — up to 8 dedicated SFX channels on the `sfx` mixer, so several sounds can play at once, with per-pool exclusive-playback modes (overlap, cross-fade, wait for open air).
- **SFX Library** — browse the shared `audio/` folder in-game, preview files, and add them to any context; reusable **audio presets** and **video presets**; per-file global enable/disable.
- **Customize replay music** — Override the default music for a replay.
- **Video speed variants** — pre-render slow-/fast-motion copies of any movie via ffmpeg, then cycle speeds in-game; procedural **auto-speed** rhythms (roller_coaster, build_up, edge, tease, …) that vary each playthrough.
- **Undo / redo** (up to 20 steps), **copy/paste** of marker config, and **automatic hourly + manual** zip backups.
- **Rebindable hotkeys** and a **relocatable shared data directory**.

## Requirements

- **Ren'Py 7.4.x and up** — works on both the 7.x (Python 2) and 8.x (Python 3) engine generations.
- **ffmpeg 5.x+** — required only for the video speed-variant features. Must be on `PATH`, or point Cue at it with the `RENPY_CUE_FFMPEG` / `RENPY_CUE_FFPROBE` environment variables.

## Installation

Cue is a drop-in mod. Copy the `cue_lib/` folder into your game's `game/` directory as `renpy_cue/`:

```
<game>/game/renpy_cue/cue_lib/
```


### Using the mod in multiple games

If you want Cue installed across several games, **symlink `cue_lib/` instead of copying it**:

```
<game1>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
<game2>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
```

One copy of the code serves every game, and an update propagates to all of them at once. On Windows use a directory junction (`mklink /J …`). Your **data** — markers, presets, audio, music — is already shared machine-wide through the data directory below, so only the code needs the symlink.

## Usage

Press **`** (backquote) to open the Cue overlay. It has three pages:

- **SFX editor** (default) — context-sensitive.
  - On a **video**: **Video VFX** (speed selection, multi-speed sequences, auto-speed presets, and a Create tab that encodes speed variants with a quality picker and job queue) and **Video SFX** (a timeline visualizer with draggable markers, pause/play, per-marker volume, repeat-markers, mute-original-audio, and save-as-video-preset).
  - On an **image**: an **Image SFX** pool with volume, exclusive playback, and a "trigger on screen shake" toggle.
  - On **dialogue**: a **Dialogue SFX** pool for the current line.
  - The **Loop SFX** pool is always available.
  - The **SFX Library** section is a folder/file browser of the shared `audio/` dir with play preview and add-to-context buttons.
- **Music** — Now Playing and Current Scene readouts, per-replay music triggers (assign songs while playing through a scene), and the **My Music** (shared `music/` folder) and **Game Music** (the game's own bundled audio) trees.
- **Settings** — relocate the **Cue Data Directory**, and view, rebind, or reset every hotkey.

### Hotkeys

All hotkeys are rebindable from **Settings → Keybinds**.

| Action | Default |
| --- | --- |
| Toggle overlay | `` ` `` |
| Toggle SFX triggers on/off | Shift+3 |
| Toggle SFX Library section | Shift+S |
| Pause the game (auto-advancing scenes) | Shift+4 |
| Copy current marker config | Shift+1 |
| Paste marker config | Shift+2 |
| Undo last marker change | Shift+Q |
| Redo last undone change | Shift+W |
| Video speed up / down | M / N |
| Quit & relaunch the game (dev only) | F5 |

## Data directory

All markers, presets, shared config, user audio/music, backups, and speed-variant videos live in one shared directory. By default:

- **Windows**: `%APPDATA%\renpy_cue`
- **macOS**: `~/Library/Application Support/renpy_cue`
- **Linux**: `$XDG_DATA_HOME/renpy_cue`, or `~/.local/share/renpy_cue`

You can relocate it from **Settings → Cue Data Directory** (applies machine-wide, takes effect after restart), or override it with the `RENPY_CUE_DIR` environment variable. Every game with Cue installed shares this one directory. User media goes in two subfolders: `audio/` (SFX) and `music/`.

## Development

### Repository layout

- `cue_lib/` — the mod source: Python logic in `.py` files, screens and styles in `cue_lib/ui/*.rpy`.
- `cue_lib/cue_z.rpy` — the bootstrap: import-path setup, the init blocks that build and wire every manager, and the engine callbacks.
- `test_game/` — a minimal Ren'Py project used as the in-engine test harness.
- `tests/` — the headless pytest suite, run against a stub Ren'Py runtime (`tests/mock_renpy/`).
- `typings/` — Ren'Py runtime type stubs for static analysis.

### Compatibility

Code must work on **Ren'Py 7.4.x and up**, which means both the 7.x (Python 2) and 8.x (Python 3) engine generations. The 7.x constraint forbids f-strings, type hints, and other Python 3-only syntax in `.py` files. The full rules are in `CLAUDE.md`.

### Tooling

- `bin/lint.sh` — runs pyright on `cue_lib/` plus a 120-character line-length check. Prints `CLEAN` or exits nonzero.
- `bin/test.sh` — `poetry run pytest tests/ -q` (headless unit tests against the mock runtime).
- `bin/run_testcases.sh <sdk>/renpy.sh` — runs the in-engine testcases harness against a real Ren'Py SDK (screen/engine code that pytest's mock can't drive). Picks `testcases_modern.rpy` (8.x) or `testcases_legacy.rpy` (7.x) based on the SDK version.

CI runs the harness against pinned Ren'Py **7.4.10** and **8.5.3** SDKs, plus lint and pytest on every push/PR.

### Local setup

Requires Python **>= 3.10** and [Poetry](https://python-poetry.org/). After cloning:

```sh
poetry install
bin/lint.sh
bin/test.sh
```

## License

MIT — see [LICENSE](LICENSE).
