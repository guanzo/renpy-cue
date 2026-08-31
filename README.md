<p align="center">
  <img src="./cue_lib/assets/images/branding/cue-wordmark.png" alt="Ren'Py Cue" width="200">
</p>

Add sound effects, music, and video effects to [Ren'Py](https://www.renpy.org/) games — without modifying the game's scripts.

<img width="600" height="338" alt="Image" src="https://github.com/user-attachments/assets/f32a0e56-78ad-4ae0-9644-ddeaa55cece8" />

<br/>

**Need help, want to share your setup, or just hang out? [Join the Cue Discord](https://discord.gg/kAVtFGcQYm)**

## Contents

* [What Cue Does](#what-cue-does)
* [Getting Started](#getting-started)
* [Using Cue With Multiple Games](#using-cue-with-multiple-games)
* [How Cue Works](#how-cue-works)
* [Requirements](#requirements)
* [For Developers](#for-developers)


## What Cue Does

🔊 Synchronized SFX

Add sound effects to images, dialogue, video timestamps, loops, and screen shakes.

🎵 Replay Music

Customize the music that plays during replays with your own songs or music from the game.

🎬 Video Speed Variants

Create slower or faster versions of a video, and switch or sequence between speeds during playback. 

🎛️ Presets

Build reusable SFX and music pools from your own files and folders, then save common setups as presets.

📦 Shared Setups

Reuse your audio, music, presets, and configuration across multiple games.

🔄 Import & Export

Export your Cue setup to share it with others.


## Getting Started

### 1. Install Cue

1. Download and extract the [latest release](https://github.com/guanzo/renpy-cue/releases/latest) (`cue_x.x.x.zip`).
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

1. Download and extract the pack you want to use. 
2. Run the game, then open Cue by pressing `` ` `` (backtick) or `Shift+Alt+E`. 
3. Go to **SFX Library**, and click **Open SFX Folder**. 
4. Copy the extracted audio files into the folder that opens.
5. Alternatively, you can add extra SFX folders in **Settings** -> **SFX Folders**

Cue was built with AVNs in mind, but Cue itself works the same on any Ren'Py game.

### 3. Create a SFX trigger

1. Start a replay and play until you reach an image where you want a sound.
2. Open Cue.
3. Find a sound in **SFX Library** and click the **+** button.
4. The next time this image appears on screen, your chosen sound will play.

## Using Cue With Multiple Games

The normal method is to install a separate copy of Cue into each game you want to use, following [Getting Started](#getting-started) above.

### Advanced: Share One Cue Installation

If you have Cue installed in several games and want one copy of the code to serve all of them, symlink `cue_lib/` instead of copying it into each game:

```text
<game1>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
<game2>/game/renpy_cue/cue_lib  ->  <your shared copy of cue_lib>
```

An update to the shared copy then propagates to every game at once. On Windows, use a directory junction (`mklink /J …`).

## How Cue Works

Cue attaches **pools** to **triggers** in a game.

A **pool** is a collection of SFX files and folders. 

A **trigger** can be an image, dialogue line, video timestamp, repeating loop, or a screen shake.

A **marker** contains a trigger and one or more pools. 

When a marker's trigger occurs, Cue plays a SFX from its pools.

<b>You can add individual files to a pool, but adding folders is recommended.</b> Any changes you make to a folder's contents are automatically reflected in the pool, so you can add or remove files later without updating the pool itself.

Pools can overlap when they play. More than one sound can play at once, and each pool can be set to overlap freely, cross-fade, or wait for a quiet moment before playing. This is an advanced setting you can leave alone until you need it.

### Video Speed & Effects

Requires [FFmpeg](https://www.ffmpeg.org/) v5+.

Cue can create slower motion or faster motion copies of any movie, then let you switch speeds while playing. You can also create multi-speed sequences and use procedural **auto-speed** rhythms such as `roller_coaster`, `build_up`, `edge`, and `tease` that vary each playthrough.

You only need to place Video SFX markers once, on the original video. When you switch to a speed variant, Cue automatically scales every marker's timestamp to match, so there's no need to re-time or re-place anything for each speed.

### Intensity Groups

Intensity Groups tie your sound effects to video speed. As a video speeds up or slows down, Cue automatically swaps in sounds that match, so slower speeds can use softer, sparser sounds while faster speeds use louder and more frequent ones.

It's the feature that brings everything together: video SFX, loop SFX, loop frequency, and volume can all react to video speed, without needing to configure each speed variant individually.

**How to set it up:**

1. **Generate a speed variant** — in the **Speed** tab, create at least one speed variant for the video (8+ is ideal, so each level has speeds to map to).
2. **Create an intensity group** — in the **SFX Library**, open the **Intensity Groups/** block, click **+ Group**, and give it a name.
3. **Add levels** — click **+ Level** to add one level per intensity step. Level 1 is the softest; the last level is the hardest. 3 levels is a good starting point.
4. **Add SFX to each level** — click the **folder** icon on a level row to enter add mode, then click **+** on any file or folder in the library to drop it into that level. Repeat for each level.
5. **Hook the group to a pool** — with a **video** or **loop** targeted, click **+** on any level row. Cue adds that level's folder to the pool and auto-enables intensity for that video.


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

Code must work on **Ren'Py 7.4.x and up**. Full rules are in `CLAUDE.md`.

### Repository Layout

- `cue_lib/` — the mod source: Python logic in `.py` files, screens and styles in `cue_lib/ui/*.rpy`.
- `cue_lib/cue_z.rpy` — the bootstrap: import-path setup, the init blocks that build and wire every manager, and the engine callbacks.
- `test_game/` — a minimal Ren'Py project used as the in-engine test harness.
- `tests/` — the headless pytest suite, run against a stub Ren'Py runtime (`tests/mock_renpy/`).
- `typings/` — Ren'Py runtime type stubs for static analysis.

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