<p align="center">
  <img src="./cue_lib/images/branding/cue-wordmark.png" alt="Ren'Py Cue" width="200">
</p>

Cue lets you add sound effects, music, and video effects to [Ren'Py](https://www.renpy.org/) visual novels.


**Need help, want to share your setup, or just hang out? [Join the Cue Discord](https://discord.gg/kAVtFGcQYm)**

## Contents

* [Getting Started](#getting-started)
* [How Cue Works](#how-cue-works)
* [Using Cue With Multiple Games](#using-cue-with-multiple-games)
* [Settings and Your Data](#settings-and-your-data)
* [Requirements](#requirements)
* [For Developers](#for-developers)

## Getting Started

### 1. Install Cue

1. Download and extract the [latest release](https://github.com/guanzo/renpy-cue/releases/latest).
2. Drop the `renpy_cue` folder into the game's `game` folder.

```text
Your Game/
└─ game/
   └─ renpy_cue/
```

### 2. Add some sounds

Cue needs sound files before it can play anything. You can start with either of these:

- **[Cue NSFW SFX Pack](https://github.com/guanzo/renpy-cue/releases/latest/download/cue_sfx.zip)**: A curated collection selected for Cue.
- **<a href="https://opennsfw.carrd.co/" target="_blank" rel="noopener noreferrer">OPENNSFW</a>**: High quality SFX + Voice Pack. Contains Free and Paid versions.

Download and extract the pack you want to use. Then run the game, open Cue, go to **SFX Library**, and click **Open SFX Folder**. Copy the extracted audio files into the folder that opens.

Cue was built with AVNs in mind, but Cue itself works the same on any Ren'Py game.

### 3. Add your first sound effect

1. Start a replay and play until you reach an image where you want a sound.
2. Press `` ` `` (backtick) or `Shift+Alt+E` to open Cue.
3. Find a sound in **SFX Library** and click the **+** button.
4. The next time this image appears on screen, your chosen sound will play.

## How Cue Works

Cue attaches **pools** to **triggers** in a game.

A **pool** is a collection of SFX files and folders. 

A **trigger** can be an image, dialogue line, video timestamp, repeating loop, or a screen shake.

A **marker** contains a trigger and one or more pools. 

When a marker's trigger occurs, Cue plays a SFX from its pools.

<b>You can add individual files to a pool, but adding folders is recommended.</b> Any changes you make to a folder's contents are automatically reflected in the pool, so you can add or remove files later without updating the pool itself.

Pools can overlap when they play. More than one sound can play at once, and each pool can be set to overlap freely, cross-fade, or wait for a quiet moment before playing. This is an advanced setting you can leave alone until you need it.

Some games simulate video using sequences of images rather than actual video files. These sequences cannot currently be used as triggers, but support is planned for a future version.

### What You Can Do

* **Add sound effects** to triggers.
* **Build reusable SFX pools** from your own files and folders, and save common setups as **presets**.
* **Customize replay music** with your own music or the game's existing tracks.
* **Create video speed variants** and switch or sequence between speeds while playing.
* **Reuse your setup across games** with shared audio, music, presets, and configuration.
* **Export and import** your Cue setup to share it with others or move it to different machines.

### Video Speed & Effects

**Requires ffmpeg.**

Cue can create slow-motion or fast-motion copies of any movie, then let you switch speeds while playing. You can also create multi-speed sequences and use procedural **auto-speed** rhythms such as `roller_coaster`, `build_up`, `edge`, and `tease` that vary each playthrough.

You only need to place Video SFX markers once, on the original video. When you switch to a speed variant, Cue automatically scales every marker's timestamp to match, so there's no need to re-time or re-place anything for each speed.

### Intensity Groups

Intensity Groups tie your sound effects to video speed. As a video speeds up or slows down, Cue automatically swaps in sounds that match, so slower speeds can use softer, sparser sounds while faster speeds use louder and more frequent ones.

It's the feature that brings everything together: video SFX, loop SFX, loop frequency, and volume can all react to video speed, without needing to configure each speed variant individually.

## Using Cue With Multiple Games

The normal method is to install a separate copy of Cue into each game you want to use, following [Getting Started](#getting-started) above.

### Advanced: Share One Cue Installation

If you have Cue installed in several games and want one copy of the code to serve all of them, symlink `cue_lib/` instead of copying it into each game:

```text
<game1>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
<game2>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
```

An update to the shared copy then propagates to every game at once. On Windows, use a directory junction (`mklink /J …`).

## Cue Data Folder

Cue keeps your SFX, music, markers, presets, and video speed variants in one shared data folder used by every game where Cue is installed.

### Default locations

* **Windows:** `%APPDATA%\renpy_cue`
* **macOS:** `~/Library/Application Support/renpy_cue`
* **Linux:** `$XDG_DATA_HOME/renpy_cue`, or `~/.local/share/renpy_cue`

You can change the data folder location in Cue's settings, or override it with the `RENPY_CUE_DIR` environment variable.

## Requirements

* **Ren'Py 7.4 or newer:** works on both the 7.x (Python 2) and 8.x (Python 3) engine versions. 7.2 up to 7.4 is best effort only — compatibility fixes there are limited to simple workarounds or are disabled.
* **ffmpeg 5 or newer:** only required for creating video speed variants. It must be on `PATH`, or pointed to with the `RENPY_CUE_FFMPEG` and `RENPY_CUE_FFPROBE` environment variables.

## For Developers

### Repository Layout

- `cue_lib/` — the mod source: Python logic in `.py` files, screens and styles in `cue_lib/ui/*.rpy`.
- `cue_lib/cue_z.rpy` — the bootstrap: import-path setup, the init blocks that build and wire every manager, and the engine callbacks.
- `test_game/` — a minimal Ren'Py project used as the in-engine test harness.
- `tests/` — the headless pytest suite, run against a stub Ren'Py runtime (`tests/mock_renpy/`).
- `typings/` — Ren'Py runtime type stubs for static analysis.

### Compatibility

Code must work on **Ren'Py 7.4.x and up**. Full rules are in `CLAUDE.md`.

### Tooling

- `bin/lint.sh` — runs pyright on `cue_lib/`.
- `bin/test.sh` — `poetry run pytest tests/ -q`, the headless unit suite against the mock runtime.
- `bin/test_harness.sh <sdk>/renpy.sh` — runs the in-engine testcase harness against a real Ren'Py SDK, for screen/engine code the pytest mock can't drive. Picks `testcases_modern.rpy` (8.x) or `testcases_legacy.rpy` (7.x) based on the SDK version.

### Local Setup

Requires Python **>= 3.10** and [Poetry](https://python-poetry.org/). After cloning:

```sh
poetry install
bin/lint.sh
bin/test.sh
```

## License

MIT. See [LICENSE](LICENSE).