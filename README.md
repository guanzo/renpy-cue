# Ren'Py Cue

Ren'Py Cue lets you add your own sound effects, music, and video effects to [Ren'Py](https://www.renpy.org/) visual novels while you play — without editing the game's scripts.

Open Cue over the game, add sounds to the current image, dialogue, video, or other trigger, and Cue remembers your setup and plays them automatically when that trigger happens again.

<sub>Cue was built with AVNs in mind, and the official SFX pack contains NSFW audio. Cue itself works the same on any Ren'Py game, and you can load your own SFX instead if you'd rather keep things SFW.</sub>

## Getting Started

### 1. Install Cue

1. Download and extract Cue.
2. Open the game's `game` folder.
3. Copy the `renpy_cue` folder into it.

```text
Your Game/
└── game/
    └── renpy_cue/
        └── cue_lib/
```

### 2. Add some sounds

Cue needs sound files before it can play anything. Download the Cue SFX pack and extract it. Then open Cue, go to **SFX Library**, and click **Open SFX Folder**. Copy the extracted audio files into the folder that opens.

### 3. Add your first sound effect

1. Play until you reach an image where you want a sound.
2. Press `` ` `` (backtick) or `Shift+Alt+E` to open Cue.
3. Find a sound in **SFX Library**.
4. Click  the **+** button.
5. If the current image doesn't have a pool yet, Cue creates one automatically.

**[Screenshot: the game with the Cue overlay open, sitting on an image.]** Annotate ① the Image SFX pool / active pool, and ② the SFX Library panel.

### 4. Keep playing

Close Cue and continue playing. When the same image appears again, Cue plays sounds from its pool automatically.

## How Cue Works

Cue attaches **SFX pools** to triggers in a game.

A pool is a collection of sound files and folders. When its trigger occurs, Cue plays from that pool. A trigger can be:

- an image
- a dialogue line
- a video timestamp
- a repeating loop
- a screen shake

A trigger can have more than one pool. The **active pool** is the one you're currently editing and the one new sounds are added to.

Pools can also overlap when they play — more than one sound can sound at once, and each pool can be set to overlap freely, cross-fade, or wait for a quiet moment before playing. This is an advanced setting you can leave alone until you need it.

## What You Can Do

- **Add sound effects** to images, dialogue, videos, loops, and screen shakes.
- **Build reusable SFX pools** from your own files and folders, and save common setups as **presets**.
- **Customize replay music** with your own music or the game's existing tracks.
- **Add sounds to videos** with draggable timeline markers.
- **Create video speed variants** and switch or sequence between speeds while playing.
- **Reuse your setup across games** with shared audio, music, presets, and configuration.

## Video Speed & Effects

**Requires ffmpeg.**

Cue can pre-render slow-motion or fast-motion copies of any movie, then let you switch speeds while playing — including multi-speed sequences and procedural **auto-speed** rhythms (roller_coaster, build_up, edge, tease, and more) that vary each playthrough.

## Using Cue With Multiple Games

The normal method is to install a separate copy of Cue into each game you want to use, following [Getting Started](#getting-started) above.

### Advanced: Share One Cue Installation

If you have Cue installed in several games and want one copy of the code to serve all of them, symlink `cue_lib/` instead of copying it into each game:

```text
<game1>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
<game2>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
```

An update to the shared copy then propagates to every game at once. On Windows, use a directory junction (`mklink /J …`). Your **data** — markers, presets, audio, music — is already shared machine-wide through the data directory below, so only the code needs the symlink.

## Settings and Your Data

Press `` ` `` (backtick) or `Shift+Alt+E` to open the Cue overlay. **Settings** is where you can:

- relocate the **Cue Data Directory**;
- view, rebind, or reset every hotkey.

Cue keeps your SFX and music, pools and markers, presets, and generated video variants in one shared data folder, used by every game where Cue is installed. 

Cue also keeps **automatic hourly and manual backups** as zip files, and supports **undo/redo** (up to 20 steps) and **copy/paste** of a pool's configuration, so you can experiment without losing your setup.

### Default locations

- **Windows**: `%APPDATA%\renpy_cue`
- **macOS**: `~/Library/Application Support/renpy_cue`
- **Linux**: `$XDG_DATA_HOME/renpy_cue`, or `~/.local/share/renpy_cue`

You can also override the location with the `RENPY_CUE_DIR` environment variable.

## Requirements

- **Ren'Py 7.4 or newer** — works on both the 7.x (Python 2) and 8.x (Python 3) engine generations.
- **ffmpeg 5 or newer** — only required for creating video speed variants. Must be on `PATH`, or pointed to with the `RENPY_CUE_FFMPEG` / `RENPY_CUE_FFPROBE` environment variables.

## For Developers

### Repository Layout

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
- `bin/test_harness.sh <sdk>/renpy.sh` — runs the in-engine testcases harness against a real Ren'Py SDK (screen/engine code that pytest's mock can't drive). Picks `testcases_modern.rpy` (8.x) or `testcases_legacy.rpy` (7.x) based on the SDK version.

CI runs the harness against pinned Ren'Py **7.4.10** and **8.5.3** SDKs, plus lint and pytest on every push/PR.

### Local Setup

Requires Python **>= 3.10** and [Poetry](https://python-poetry.org/). After cloning:

```sh
poetry install
bin/lint.sh
bin/test.sh
```

## License

MIT — see [LICENSE](LICENSE).