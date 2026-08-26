# Release Pipeline

Date: 2026-08-25

## Problem

The README points users at `https://github.com/guanzo/renpy-cue/releases/latest`,
but there is no published-release process. There is no version number anywhere, so
nothing can be stamped, no version can be shown in-game, and no release asset is
ever built or attached. Users must clone and install from source by hand.

Two assets are wanted per release:

1. The mod — a `renpy_cue/` folder users drop into a game's `game/` dir.
2. The official SFX pack — a zip of the user's local audio library, shipped
   separately from the mod.

## Constraint

- **Single source of truth for the version.** `CUE_VERSION` in
  `cue_lib/constants.py` is the only place the number lives. In-game display, the
  README, the release tag, the asset filenames, and the changelog all derive from
  it. No duplicated version string.
- **Source-only artifact.** Cue is a mod, not a game binary — no per-OS builds.
  One cross-platform zip works for Windows/macOS/Linux and Ren'Py 7.x/8.x.
- **No bytecode in the asset.** `.rpyc`/`.pyo`/`__pycache__` are version-specific
  and must be stripped. The shipped zip may contain only `.py`/`.rpy`/`.pyi`/data.
- **SFX source is outside the repo and path-agnostic in code.** The SFX pack source
  is not in git, so it cannot be built on a CI runner — it is built and uploaded
  locally. No absolute path or env detail is committed: the source directory is read
  from the gitignored `.env` (`CUE_SFX_SOURCE_DIR`) and passed to the builder as a
  parameter.

## Version

`CUE_VERSION = "0.1.0"` in `cue_lib/constants.py`, mirrored as `CUE_VERSION: str`
in `constants.pyi`. Bridged into the Ren'Py store via the `cue_z.rpy` `init -900`
block: `_cue.VERSION = CUE_VERSION`. Add `VERSION` to the `_cue` signature in
`state.pyi`. Screens render `_cue.VERSION` with `_cue_escape_text()` (user-facing
text). Placement (e.g. the overlay sidebar header, next to the app name) is an
implementation choice.

## Conventional Commits

Document the commit message convention in CLAUDE.md: allowed prefixes (`feat`,
`fix`, `refactor`, `perf`, `docs`, `style`, `test`, `build`, `chore`, `revert`),
optional `(scope)`, and `!`/`BREAKING CHANGE:` for breaking changes.

Rationale: this is the sticky, hard-to-retrofit decision — everything else in the
release flow is generated at release time and swappable. It keeps git-cliff's
categorized output meaningful and leaves the door open to automatic versioning
later. Enforcement: CLAUDE.md governs agent-authored commits. A commitlint CI check
is a later, optional step.

## Release notes + changelog (`git-cliff`)

`git-cliff` (a committed `cliff.toml`, a dev dependency) reads the commit range to
produce, at release time, (a) the categorized notes for this version and (b) the
full `CHANGELOG.md`. Both come from the same commit diff, so the tag, the notes,
and the changelog cannot drift. The generated `CHANGELOG.md` is committed in the
release commit; the notes become the GitHub release body.

**Exception — the first release.** The first release (`v0.1.0`) has no prior tag, so
git-cliff would sweep the entire history into one giant note. For the first release
the skill writes a short hand-written note (version, the two assets, a README link)
and seeds a concise `CHANGELOG.md`. Categorized git-cliff notes and appended
changelog entries apply from the second release onward.

## Asset builder — `bin/build_release_asset.sh`

Shared, deterministic builder for the mod zip. Input: `CUE_VERSION`. Output:
`renpy_cue_<ver>.zip` with a single top-level `renpy_cue/` containing `cue_lib/`
(source + `images/`), stripped of `.rpyc`/`.pyo`/`__pycache__`. The file list is
explicit (only `cue_lib/`), so `tests/`, `bin/`, `tools/`, `docs/`, `README.md`
never ship. Built from the same copy-and-strip primitive `bin/test_harness.sh`
already uses (lines 134-138), wrapped as a zip.

## SFX pack asset (local)

`bin/build_sfx_asset.sh <src_dir> <version>` — generic and path-agnostic. It zips the
source directory into `renpy_cue_sfx_<ver>.zip`, excluding `test_bad`. The actual
source directory is read from the gitignored `.env` (`CUE_SFX_SOURCE_DIR`) by the
skill and passed in; no absolute path is committed. Rebuilt and re-uploaded on every
release with no change detection — the user does not care whether the pack changed,
only that the latest is downloadable.

## `/release` skill (local publisher)

`.claude/skills/release/SKILL.md`. Flow:

1. Confirm the tree is clean and read the current `CUE_VERSION`.
2. Prompt for the manual semver bump (major/minor/patch) -> compute the new version.
3. Write `CUE_VERSION` into `constants.py` + `constants.pyi`.
4. Gate: `/lint`, `/test`, then the harness on both generations
   (`bin/test_harness.sh .local/renpy-8.5.3-sdk/renpy.sh` and
   `... .local/renpy-7.4.10-sdk/renpy.sh`).
5. Generate notes + changelog — git-cliff for a normal release, or a short
   hand-written note + seeded `CHANGELOG.md` for the first release; commit the
   version bump + `CHANGELOG.md`.
6. Dry-run the mod zip (`bin/build_release_asset.sh`) to verify contents (no
   bytecode, has `cue_lib/__init__.py` and `images/`).
7. Build the SFX zip with `bin/build_sfx_asset.sh` from `$CUE_SFX_SOURCE_DIR`
   (gitignored `.env`), excluding `test_bad`.
8. **STOP and present the plan** — version, filenames, git commit list — and wait
   for confirmation (release is a publish; the user commits themselves).
9. On confirm: tag `v<ver>`, push (triggers the GA `release` job).
10. Wait for the release to be created, then `gh release edit v<ver>
    --notes-file <git-cliff-notes>` (swap in the categorized notes) and
    `gh release upload v<ver> renpy_cue_sfx_<ver>.zip --clobber`.
11. Report the release URL.

The mod zip is attached by the runner; the SFX zip and the final notes are added by
the skill, which is why the skill must wait for the release to exist before
uploading.

## GitHub Actions — `release.yml`

Triggers on `push: tags: ['v*']`. On a clean runner: checkout, setup python, run
the fast gate (`bin/lint.sh` + `bin/test.sh`) to confirm the tag is green, assert
`CUE_VERSION` matches the tag (fail a stale/foreign tag), build the mod zip with
`bin/build_release_asset.sh`, and `gh release create v<ver> --title ... --generate-notes
<zip>` to attach it. Auto-notes provide a default body immediately; the skill
replaces it with the git-cliff notes afterward.

## Verification

- `/lint` CLEAN, `/test`, harness on both generations pass before the tag.
- Mod zip contents verified: no `.rpyc`/`.pyo`/`__pycache__`; has
  `cue_lib/__init__.py`; no `tests/`/`bin/`/`tools/`/`docs/`.
- SFX zip contains the source category folders and not `test_bad`.
- No env paths committed: grep the repo for the data directory / mount prefix.
- The `release` job is green on the tag; the release page shows both assets and the
  notes; `_cue.VERSION` renders in-game.
